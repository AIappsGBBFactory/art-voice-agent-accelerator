"""
Tests for utils.eval_span — eval-ready span content annotation.

Verifies:
- No-op when EVAL_SPAN_CONTENT_ENABLED is unset/false
- Content attached when enabled
- PII scrubbed by default; raw only when explicitly opted in
- Per-field truncation to bound span size
- Never raises (telemetry must not break a call)
"""

import json

import pytest

from utils import eval_span


class FakeSpan:
    """Minimal span double capturing set_attribute calls."""

    def __init__(self, recording: bool = True):
        self._recording = recording
        self.attributes: dict[str, object] = {}

    def is_recording(self) -> bool:
        return self._recording

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in (
        "EVAL_SPAN_CONTENT_ENABLED",
        "EVAL_SPAN_CONTENT_RAW",
        "EVAL_SPAN_CONTENT_MAX_CHARS",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def test_noop_when_disabled(monkeypatch):
    span = FakeSpan()
    eval_span.annotate_eval_content(
        span,
        input_messages=[{"role": "user", "content": "hello"}],
        output_text="hi there",
    )
    assert span.attributes == {}


def test_standard_otel_flag_enables_content(monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    span = FakeSpan()
    eval_span.annotate_eval_content(
        span,
        input_messages=[{"role": "user", "content": "hello"}],
        output_text="hi there",
    )
    assert "gen_ai.output.messages" in span.attributes
    assert "gen_ai.input.messages" in span.attributes


def test_noop_when_span_none(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    # Should not raise
    eval_span.annotate_eval_content(None, output_text="hi")


def test_attaches_content_when_enabled(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    span = FakeSpan()
    eval_span.annotate_eval_content(
        span,
        input_messages=[{"role": "user", "content": "what is my balance"}],
        output_text="Your balance is available.",
    )
    assert "gen_ai.input.messages" in span.attributes
    assert "gen_ai.output.messages" in span.attributes
    assert span.attributes["eval.content.scrubbed"] is True

    out = json.loads(span.attributes["gen_ai.output.messages"])
    assert out[0]["role"] == "assistant"
    assert "balance" in out[0]["content"]


def test_pii_scrubbed_by_default(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    span = FakeSpan()
    eval_span.annotate_eval_content(
        span,
        input_messages=[{"role": "user", "content": "my ssn is 123-45-6789"}],
        output_text="Thanks, noted.",
    )
    payload = span.attributes["gen_ai.input.messages"]
    assert "123-45-6789" not in payload
    assert "[SSN_REDACTED]" in payload


def test_raw_content_when_opted_in(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    monkeypatch.setenv("EVAL_SPAN_CONTENT_RAW", "true")
    span = FakeSpan()
    eval_span.annotate_eval_content(
        span,
        input_messages=[{"role": "user", "content": "my ssn is 123-45-6789"}],
    )
    payload = span.attributes["gen_ai.input.messages"]
    assert "123-45-6789" in payload
    assert span.attributes["eval.content.scrubbed"] is False


def test_truncation(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    monkeypatch.setenv("EVAL_SPAN_CONTENT_MAX_CHARS", "50")
    span = FakeSpan()
    eval_span.annotate_eval_content(span, output_text="x" * 500)
    payload = span.attributes["gen_ai.output.messages"]
    assert "truncated" in payload
    assert len(payload) < 200


def test_skips_non_recording_span(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    span = FakeSpan(recording=False)
    eval_span.annotate_eval_content(span, output_text="hi")
    assert span.attributes == {}


def test_missing_fields_skipped(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    span = FakeSpan()
    eval_span.annotate_eval_content(span, output_text="only output")
    assert "gen_ai.output.messages" in span.attributes
    assert "gen_ai.input.messages" not in span.attributes


def test_input_captures_only_latest_user_turn(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    span = FakeSpan()
    messages = [
        {"role": "system", "content": "you are a bank agent " * 500},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "latest question"},
    ]
    eval_span.annotate_eval_content(span, input_messages=messages)
    payload = json.loads(span.attributes["gen_ai.input.messages"])
    # Only the latest user turn is captured — not history or the large system prompt.
    assert len(payload) == 1
    assert payload[0]["role"] == "user"
    assert payload[0]["content"] == "latest question"


def test_input_skipped_when_no_user_message(monkeypatch):
    monkeypatch.setenv("EVAL_SPAN_CONTENT_ENABLED", "true")
    span = FakeSpan()
    eval_span.annotate_eval_content(
        span, input_messages=[{"role": "assistant", "content": "hi"}]
    )
    assert "gen_ai.input.messages" not in span.attributes

