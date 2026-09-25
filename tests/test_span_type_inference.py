"""@observe span type guesses."""

from traccia.instrumentation.decorator import _infer_type_from_attributes


def test_http_url_stays_a_normal_span():
    assert _infer_type_from_attributes({"http.url": "https://example.com/api"}) is None


def test_tool_name_is_a_tool():
    assert _infer_type_from_attributes({"tool.name": "search"}) == "tool"
    assert _infer_type_from_attributes({"tool": "search"}) == "tool"


def test_model_is_an_llm():
    assert _infer_type_from_attributes({"llm.model": "gpt-4o-mini"}) == "llm"
