"""Span processor that adds default GovernanceEvent attributes on every span."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from traccia.governance import schema as G
from traccia.tracer.provider import SpanProcessor

_logger = logging.getLogger(__name__)
_hipaa_warned = False


class GovernanceEnrichmentProcessor(SpanProcessor):
    """Ensures governance.event_type and integrity_hash exist before export."""

    def __init__(
        self,
        *,
        default_event_type: str = "inference",
        eu_risk_tier: Optional[str] = None,
        hipaa_enabled: bool = False,
    ) -> None:
        self._default_event_type = default_event_type
        self._eu_risk_tier = eu_risk_tier
        self._hipaa_enabled = hipaa_enabled

    def on_end(self, span: Any) -> None:
        global _hipaa_warned
        if not hasattr(span, "set_attribute"):
            return
        attrs = dict(span.attributes) if hasattr(span, "attributes") else {}
        event_type = attrs.get(G.EVENT_TYPE)
        if not event_type:
            name = str(attrs.get("name", "") or getattr(span, "name", "") or "")
            event_type = "tool_call" if "tool" in name.lower() else self._default_event_type
            span.set_attribute(G.EVENT_TYPE, event_type)
        if G.TIMESTAMP_SOURCE not in attrs:
            span.set_attribute(G.TIMESTAMP_SOURCE, "sdk")
        if self._eu_risk_tier and G.RISK_TIER not in attrs:
            span.set_attribute(G.RISK_TIER, self._eu_risk_tier)
        if self._hipaa_enabled:
            if G.HIPAA_FRAMEWORK_ENABLED not in attrs:
                span.set_attribute(G.HIPAA_FRAMEWORK_ENABLED, True)
            if attrs.get(G.REDACTION_APPLIED) and G.HIPAA_PHI_REDACTION_APPLIED not in attrs:
                span.set_attribute(G.HIPAA_PHI_REDACTION_APPLIED, True)
            if not _hipaa_warned:
                _hipaa_warned = True
                _logger.warning(
                    "Traccia HIPAA framework enabled on spans. Prefer redact_pii=True. "
                    "Traccia Cloud does not currently offer a signed BAA — contact the Traccia team "
                    "for healthcare onboarding. Enabling this does not make you HIPAA compliant."
                )
        if G.INTEGRITY_HASH not in attrs:
            trace_id = ""
            span_id = ""
            if hasattr(span, "context"):
                ctx = span.context
                trace_id = format(ctx.trace_id, "032x") if ctx else ""
                span_id = format(ctx.span_id, "016x") if ctx else ""
            payload = f"{trace_id}:{span_id}:{event_type}"
            span.set_attribute(G.INTEGRITY_HASH, hashlib.sha256(payload.encode()).hexdigest())
