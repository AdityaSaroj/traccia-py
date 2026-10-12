"""Tests for PII redaction helpers."""

from traccia.processors.redaction_processor import (
    apply_redaction_to_span,
    redact_attributes,
    redact_string,
)


class _FakeSpan:
    def __init__(self, attrs: dict):
        self._attributes = dict(attrs)

    @property
    def attributes(self):
        return self._attributes

    def set_attribute(self, key: str, value):
        self._attributes[key] = value


def test_redact_string_email_phone_ssn():
    raw = "Contact alice@corp.com or 555-123-4567; SSN 123-45-6789"
    out = redact_string(raw)
    assert "[REDACTED_EMAIL]" in out
    assert "[REDACTED_PHONE]" in out
    assert "[REDACTED_SSN]" in out
    assert "alice@corp.com" not in out


def test_redact_string_phi_heuristics():
    raw = "Patient MRN: A12B34; NPI 1234567890; DOB 01/15/1980"
    out = redact_string(raw)
    assert "[REDACTED_MRN]" in out
    assert "[REDACTED_NPI]" in out
    assert "[REDACTED_DOB]" in out
    assert "A12B34" not in out
    assert "1234567890" not in out


def test_redact_attributes_sensitive_keys():
    attrs = {
        "gen_ai.prompt": "Email me at bob@test.io",
        "http.url": "https://api.example.com",
    }
    out = redact_attributes(attrs)
    assert "[REDACTED_EMAIL]" in out["gen_ai.prompt"]
    assert out["http.url"] == attrs["http.url"]
    assert out["governance.redaction_applied"] is True


def test_apply_redaction_to_span_mutates():
    span = _FakeSpan({"gen_ai.completion": "Reach sue@example.org"})
    n = apply_redaction_to_span(span)
    assert n >= 1
    assert "[REDACTED_EMAIL]" in span.attributes["gen_ai.completion"]
    assert span.attributes["governance.redaction_applied"] is True


def test_redaction_allowlists_traccia_prompt_identity():
    attrs = {
        "traccia.prompt.name": "support-reply",
        "traccia.prompt.version": "3",
        "traccia.prompt.version_id": "uuid-1",
        "traccia.prompt.label": "production",
        "llm.prompt": "secret@example.com",
    }
    out = redact_attributes(attrs)
    assert out["traccia.prompt.name"] == "support-reply"
    assert out["traccia.prompt.version"] == "3"
    assert out["traccia.prompt.version_id"] == "uuid-1"
    assert out["traccia.prompt.label"] == "production"
    assert "[REDACTED_EMAIL]" in out["llm.prompt"]


def test_redaction_allowlists_traccia_policy_effect():
    attrs = {
        "traccia.policy.effect": "deny",
        "traccia.policy.matched": True,
        "llm.prompt": "secret@example.com",
    }
    out = redact_attributes(attrs)
    assert out["traccia.policy.effect"] == "deny"
    assert out["traccia.policy.matched"] is True
    assert "[REDACTED_EMAIL]" in out["llm.prompt"]


class _FakeEventSpan(_FakeSpan):
    def __init__(self, attrs: dict, events=None, status_description=None):
        super().__init__(attrs)
        self.events = events or []
        self.status_description = status_description


def test_processor_honors_redact_all_strings_for_opaque_keys():
    from traccia.processors.redaction_processor import RedactionSpanProcessor

    span = _FakeEventSpan({"opaque.field": "mail x@y.io", "count": 3})
    RedactionSpanProcessor(redact_all_strings=True).on_end(span)
    assert span.attributes["opaque.field"] == "mail [REDACTED_EMAIL]"
    assert span.attributes["count"] == 3


def test_default_redaction_covers_result_and_nested_values():
    span = _FakeEventSpan(
        {
            "result": "send to x@y.io",
            "llm.prompt": ["hi x@y.io", "ok"],
            "meta": {"text": "x@y.io", "nested": [{"content": "x@y.io"}]},
        }
    )
    apply_redaction_to_span(span)
    assert "x@y.io" not in repr(span.attributes)


def test_redaction_covers_events_exceptions_and_status():
    from traccia.processors.redaction_processor import RedactionSpanProcessor

    span = _FakeEventSpan(
        {"safe": "v"},
        events=[
            {"name": "custom", "attributes": {"payload": "x@y.io"}},
            {
                "name": "exception",
                "attributes": {
                    "exception.message": "bad x@y.io",
                    "exception.stacktrace": "Traceback ... ValueError: bad x@y.io",
                },
            },
        ],
        status_description="bad x@y.io",
    )
    RedactionSpanProcessor(redact_all_strings=True).on_end(span)
    assert "x@y.io" not in repr(span.events)
    assert span.status_description == "bad [REDACTED_EMAIL]"


def test_end_to_end_export_redacts_events_and_exceptions():
    from opentelemetry.sdk.trace import TracerProvider as OTelTracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from traccia.processors.redaction_processor import RedactionSpanProcessor
    from traccia.tracer.provider import TracerProvider

    provider = TracerProvider()
    provider.add_span_processor(RedactionSpanProcessor(redact_all_strings=True))
    exporter = InMemorySpanExporter()
    otel_provider = getattr(provider, "_otel_provider", None)
    if not isinstance(otel_provider, OTelTracerProvider):
        import pytest

        pytest.skip("provider does not expose an OTel SDK provider")
    otel_provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = provider.get_tracer("test")
    try:
        with tracer.start_as_current_span("op") as span:
            span.set_attribute("opaque", "x@y.io")
            span.add_event("custom", {"payload": "x@y.io"})
            raise ValueError("bad x@y.io")
    except ValueError:
        pass

    (exported,) = exporter.get_finished_spans()
    dump = repr(dict(exported.attributes)) + repr(
        [(e.name, dict(e.attributes or {})) for e in exported.events]
    ) + repr(exported.status.description)
    assert "x@y.io" not in dump
    assert any(e.name == "exception" for e in exported.events)
