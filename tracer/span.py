"""Span implementation - minimal wrapper around OpenTelemetry Span."""

from __future__ import annotations

import time
import traceback
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from opentelemetry.trace import Span as OTelSpan, Status, StatusCode
from opentelemetry.trace import set_span_in_context
from opentelemetry import context as context_api

if TYPE_CHECKING:
    from traccia.tracer.tracer import Tracer


class SpanStatus(Enum):
    UNSET = 0
    OK = 1
    ERROR = 2


class Span:
    """
    Minimal wrapper around OpenTelemetry Span.
    
    Provides Traccia API compatibility while using OTel span internally.
    """

    def __init__(
        self,
        otel_span: OTelSpan,
        tracer: "Tracer",
        parent_span_id: Optional[str] = None,
    ) -> None:
        """
        Initialize span wrapper.
        
        Args:
            otel_span: OpenTelemetry Span instance
            tracer: Traccia Tracer instance  
            parent_span_id: Parent span ID (hex string, for compatibility)
        """
        self._otel_span = otel_span
        self.tracer = tracer
        self.parent_span_id = parent_span_id
        self._ended = False
        self._activation_token = None
        
        # Store tracer reference on OTel span for context retrieval
        otel_span._traccia_tracer = tracer
        
        # Create Traccia-compatible properties
        from traccia.tracer.span_context import SpanContext
        from traccia.utils.helpers import format_trace_id, format_span_id
        
        otel_context = otel_span.get_span_context()
        self.context = SpanContext(
            trace_id=format_trace_id(otel_context.trace_id),
            span_id=format_span_id(otel_context.span_id),
            trace_flags=1 if otel_context.trace_flags.sampled else 0,
            trace_state=self._format_trace_state(otel_context.trace_state),
        )
        
        # Enrich tracestate with runtime metadata
        self._enrich_tracestate()
        
        # Expose span properties for processor access
        self.name = getattr(otel_span, 'name', 'unknown')
        self.start_time_ns = time.time_ns()
        self.end_time_ns: Optional[int] = None
        
        # Status
        self.status = SpanStatus.UNSET
        self.status_description: Optional[str] = None
        
        # Maintain attribute dict for easy access
        # This mirrors OTel span attributes
        self._attributes: Dict[str, Any] = {}

        # Events (including exceptions) are buffered until end() so enrichment
        # processors (e.g. redaction) can rewrite them before they reach OTel.
        self._events: List[Dict[str, Any]] = []

    def _format_trace_state(self, trace_state) -> Optional[str]:
        """Format OTel TraceState to W3C string format."""
        if not trace_state:
            return None
        items = []
        for key, value in trace_state.items():
            items.append(f"{key}={value}")
        return ",".join(items) if items else None

    def _enrich_tracestate(self) -> None:
        """Enrich tracestate with runtime metadata."""
        try:
            from traccia.context.propagators import format_tracestate, parse_tracestate
            from traccia import runtime_config
            
            base = parse_tracestate(self.context.trace_state or "")
            if runtime_config.get_tenant_id():
                base.setdefault("tenant", runtime_config.get_tenant_id())
            if runtime_config.get_project_id():
                base.setdefault("project", runtime_config.get_project_id())
            if runtime_config.get_debug():
                base.setdefault("dbg", "1")
            
            ts = format_tracestate(base)
            if ts:
                from traccia.tracer.span_context import SpanContext
                self.context = SpanContext(
                    trace_id=self.context.trace_id,
                    span_id=self.context.span_id,
                    trace_flags=self.context.trace_flags,
                    trace_state=ts,
                )
        except Exception:
            pass

    @property
    def attributes(self) -> Dict[str, Any]:
        """
        Get span attributes (read/write).
        
        This property provides direct access to attributes dict.
        Changes are synced to OTel span via set_attribute().
        """
        # Sync from OTel span if available (for processors that read directly)
        if not self._ended and hasattr(self._otel_span, 'attributes'):
            try:
                otel_attrs = getattr(self._otel_span, 'attributes', {})
                if otel_attrs:
                    # Merge OTel attributes into local dict
                    for k, v in otel_attrs.items():
                        if k not in self._attributes:
                            self._attributes[k] = v
            except Exception:
                pass
        return self._attributes

    @property
    def events(self) -> List[Dict[str, Any]]:
        """Get buffered span events (mutable by enrichment processors until end)."""
        return self._events

    @property
    def duration_ns(self) -> Optional[int]:
        """Get span duration in nanoseconds."""
        if self.end_time_ns is None:
            return None
        return self.end_time_ns - self.start_time_ns

    def set_attribute(self, key: str, value: Any) -> None:
        """Set an attribute on the span."""
        if self._ended:
            return
        
        # Store in local dict
        self._attributes[key] = value
        
        # Set on OTel span
        try:
            self._otel_span.set_attribute(key, value)
        except Exception:
            pass

    def add_event(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        timestamp_ns: Optional[int] = None,
    ) -> None:
        """Add an event to the span."""
        if self._ended:
            return
        self._events.append({
            "name": name,
            "attributes": dict(attributes) if attributes else {},
            "timestamp_ns": timestamp_ns if timestamp_ns is not None else time.time_ns(),
        })

    def record_exception(self, error: BaseException) -> None:
        """Record an exception event on the span."""
        if self._ended:
            return
        try:
            stacktrace = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        except Exception:
            stacktrace = ""
        self.add_event(
            "exception",
            {
                "exception.type": type(error).__qualname__,
                "exception.message": str(error),
                "exception.stacktrace": stacktrace,
                "exception.escaped": "False",
            },
        )
        self.set_status(SpanStatus.ERROR, str(error))

    def set_status(self, status: SpanStatus, description: Optional[str] = None) -> None:
        """Set the span status."""
        if self._ended:
            return
        
        self.status = status
        self.status_description = description
        
        # Convert and set on OTel span
        if status == SpanStatus.OK:
            otel_status = Status(status_code=StatusCode.OK, description=description)
        elif status == SpanStatus.ERROR:
            otel_status = Status(status_code=StatusCode.ERROR, description=description)
        else:
            otel_status = Status(status_code=StatusCode.UNSET, description=description)
        
        try:
            self._otel_span.set_status(otel_status)
        except Exception:
            pass

    def end(self) -> None:
        """
        End the span.
        
        Enrichment processors run BEFORE span.end() (span is still mutable).
        Export processors run AFTER span.end() (OTel handles this automatically).
        """
        if self._ended:
            return
        
        self.end_time_ns = time.time_ns()
        if self.status == SpanStatus.UNSET:
            self.status = SpanStatus.OK
            # Set status on OTel span as well
            try:
                from opentelemetry.trace import Status, StatusCode
                self._otel_span.set_status(Status(status_code=StatusCode.OK))
            except Exception:
                pass
        
        # 1. Run enrichment processors (span is still mutable)
        self.tracer._run_enrichment_processors(self)

        # 2. Flush buffered events and the (possibly rewritten) status to OTel
        self._flush_to_otel()
        
        # 3. End the OTel span (makes it immutable)
        try:
            self._otel_span.end(end_time=self.end_time_ns)
        except Exception:
            pass
        
        # 4. OTel export processors run automatically on ReadableSpan
        
        self._ended = True

    def _flush_to_otel(self) -> None:
        for event in self._events:
            try:
                self._otel_span.add_event(
                    name=event.get("name", "event"),
                    attributes=event.get("attributes") or None,
                    timestamp=event.get("timestamp_ns"),
                )
            except Exception:
                pass
        if self.status == SpanStatus.ERROR:
            try:
                self._otel_span.set_status(
                    Status(status_code=StatusCode.ERROR, description=self.status_description)
                )
            except Exception:
                pass

    # Context manager support
    def __enter__(self) -> "Span":
        """Enter context manager."""
        ctx = set_span_in_context(self._otel_span)
        self._activation_token = context_api.attach(ctx)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Exit context manager."""
        try:
            if exc:
                self.record_exception(exc)
            self.end()
        finally:
            if self._activation_token:
                context_api.detach(self._activation_token)
                self._activation_token = None
        return False

    async def __aenter__(self) -> "Span":
        """Enter async context manager."""
        ctx = set_span_in_context(self._otel_span)
        self._activation_token = context_api.attach(ctx)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Exit async context manager."""
        try:
            if exc:
                self.record_exception(exc)
            self.end()
        finally:
            if self._activation_token:
                context_api.detach(self._activation_token)
                self._activation_token = None
        return False
