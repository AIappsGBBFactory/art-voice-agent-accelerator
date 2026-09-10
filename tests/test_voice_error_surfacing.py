"""Tests for voice pipeline error classification and surfacing.

These cover the contract that turns an opaque Azure failure (a model deployment
that does not exist, a voice that is not available in the region, an expired
key, a throttled resource) into a structured, actionable error the operator can
actually see in the UI instead of silence.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.artagent.backend.src.ws_helpers.envelopes import make_error_envelope
from apps.artagent.backend.voice.shared.errors import (
    BENIGN_VOICELIVE_ERROR_CODES,
    WS_CLOSE_CODE_VOICE_ERROR,
    VoiceErrorInfo,
    classify_speech_cancellation,
    classify_voice_error,
    classify_voicelive_server_error,
    close_reason_for,
    emit_voice_error,
)


class _FakeWebSocket:
    """Minimal websocket double that records what was sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed_with: tuple[int, str] | None = None

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)


# ---------------------------------------------------------------------------
# classify_voice_error
# ---------------------------------------------------------------------------


def test_missing_model_deployment_is_named_and_actionable() -> None:
    """The headline case: config points at a model that isn't deployed."""
    exc = Exception(
        "Error code: 404 - {'error': {'code': 'DeploymentNotFound', 'message': "
        "'The API deployment for this resource does not exist.'}}"
    )

    info = classify_voice_error(exc, source="llm", model="gpt-4o-mini")

    assert info.code == "DeploymentNotFound"
    assert "gpt-4o-mini" in info.message
    assert info.remediation
    assert "deployment" in info.remediation.lower()
    assert info.source == "llm"


def test_model_name_is_recovered_from_the_error_when_not_supplied() -> None:
    exc = Exception("The model `gpt-5-turbo` does not exist or you do not have access to it.")

    info = classify_voice_error(exc, source="llm")

    assert info.code in {"DeploymentNotFound", "ModelUnavailableInRegion"}
    assert "gpt-5-turbo" in (info.message + (info.details or ""))


def test_authentication_failure_is_distinguished_from_a_missing_model() -> None:
    exc = Exception("Error code: 401 - Access denied due to invalid subscription key")

    info = classify_voice_error(exc, source="llm")

    assert info.code == "AuthenticationError"
    assert info.fatal is True
    assert info.remediation


def test_rate_limit_is_classified_and_not_fatal() -> None:
    exc = Exception("Error code: 429 - Requests to the ChatCompletions operation have exceeded")

    info = classify_voice_error(exc, source="llm")

    assert info.code == "RateLimitExceeded"
    assert info.fatal is False


def test_unsupported_parameter_names_the_offending_parameter() -> None:
    exc = Exception(
        "Error code: 400 - {'error': {'code': 'unsupported_parameter', 'message': "
        "\"Unsupported parameter: 'temperature' is not supported with this model.\", "
        "'param': 'temperature'}}"
    )

    info = classify_voice_error(exc, source="llm", model="o1-mini")

    assert info.code == "UnsupportedParameter"
    assert "temperature" in (info.message + (info.details or ""))


def test_content_filter_is_surfaced_as_its_own_code() -> None:
    exc = Exception(
        "Error code: 400 - The response was filtered due to the prompt triggering "
        "Azure OpenAI's content management policy."
    )

    info = classify_voice_error(exc, source="llm")

    assert info.code == "ContentFiltered"


def test_unknown_errors_still_produce_a_usable_envelope() -> None:
    info = classify_voice_error(RuntimeError("something bizarre"), source="llm")

    assert info.code == "UnknownError"
    assert info.message
    assert "something bizarre" in (info.details or "")


def test_classification_never_raises_on_odd_exceptions() -> None:
    class Weird(Exception):
        def __str__(self) -> str:  # pragma: no cover - exercised via classify
            raise ValueError("cannot stringify")

    info = classify_voice_error(Weird(), source="llm")
    assert isinstance(info, VoiceErrorInfo)
    assert info.code


# ---------------------------------------------------------------------------
# classify_speech_cancellation
# ---------------------------------------------------------------------------


def test_bad_voice_name_is_reported_as_voice_not_available() -> None:
    """The Speech SDK cancels rather than raising for an invalid voice."""
    details = (
        "Websocket upgrade failed: Bad request (400). "
        "The voice 'en-US-NotARealVoice' is not supported."
    )

    info = classify_speech_cancellation(details, voice="en-US-NotARealVoice", source="tts")

    assert info.code == "VoiceNotAvailable"
    assert "en-US-NotARealVoice" in (info.message + (info.details or ""))
    assert info.remediation


def test_speech_auth_failure_is_classified() -> None:
    info = classify_speech_cancellation(
        "WebSocket upgrade failed: Authentication error (401).", source="tts"
    )

    assert info.code == "AuthenticationError"
    assert info.fatal is True


def test_speech_throttling_is_classified() -> None:
    info = classify_speech_cancellation(
        "WebSocket upgrade failed: Too many requests (429).", source="tts"
    )

    assert info.code == "RateLimitExceeded"


def test_empty_cancellation_details_still_yields_an_error() -> None:
    info = classify_speech_cancellation(None, source="stt")

    assert info.code
    assert info.message
    assert info.source == "stt"


# ---------------------------------------------------------------------------
# classify_voicelive_server_error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(BENIGN_VOICELIVE_ERROR_CODES))
def test_benign_cancel_race_codes_are_dropped(code: str) -> None:
    """Cancelling a response that already finished is not a user-facing error."""
    assert classify_voicelive_server_error(code, "no active response") is None


def test_voicelive_model_error_is_surfaced() -> None:
    info = classify_voicelive_server_error(
        "invalid_request_error",
        "The model 'gpt-4o-realtime-preview' is not available in this region.",
        model="gpt-4o-realtime-preview",
    )

    assert info is not None
    assert info.source == "voicelive"
    assert info.remediation


def test_voicelive_unknown_code_still_surfaces() -> None:
    info = classify_voicelive_server_error("some_new_code", "boom")

    assert info is not None
    assert info.message


# ---------------------------------------------------------------------------
# close_reason_for
# ---------------------------------------------------------------------------


def test_close_reason_is_truncated_to_the_websocket_frame_limit() -> None:
    info = VoiceErrorInfo(
        code="DeploymentNotFound",
        message="x" * 500,
        source="llm",
    )

    reason = close_reason_for(info)

    assert len(reason.encode("utf-8")) <= 123
    assert reason.startswith("DeploymentNotFound:")


def test_short_close_reason_is_left_intact() -> None:
    info = VoiceErrorInfo(code="AuthenticationFailed", message="Bad key.", source="llm")

    assert close_reason_for(info) == "AuthenticationFailed: Bad key."


def test_close_reason_does_not_split_a_multibyte_character() -> None:
    info = VoiceErrorInfo(code="E", message="é" * 200, source="llm")

    reason = close_reason_for(info)

    assert len(reason.encode("utf-8")) <= 123
    reason.encode("utf-8").decode("utf-8")  # must not raise


# ---------------------------------------------------------------------------
# Envelope + delivery
# ---------------------------------------------------------------------------


def test_error_envelope_carries_the_fields_the_ui_renders() -> None:
    envelope = make_error_envelope(
        "The model deployment 'gpt-4o' was not found.",
        "DeploymentNotFound",
        session_id="s1",
        code="DeploymentNotFound",
        details="404 DeploymentNotFound",
        remediation="Deploy the model.",
        source="llm",
        fatal=True,
    )

    assert envelope["type"] == "error"
    payload = envelope["payload"]
    assert payload["code"] == "DeploymentNotFound"
    assert payload["remediation"] == "Deploy the model."
    assert payload["source"] == "llm"
    assert payload["fatal"] is True
    # Generic text-based UI paths read message/content.
    assert payload["message"] == payload["content"]
    assert payload["timestamp"]


@pytest.mark.asyncio
async def test_emit_voice_error_sends_an_error_envelope() -> None:
    ws = _FakeWebSocket()
    info = classify_voice_error(Exception("DeploymentNotFound"), source="llm", model="gpt-4o")

    await emit_voice_error(ws, info, session_id="s1")

    assert ws.sent, "expected an error envelope to be delivered"
    envelope = ws.sent[-1]
    assert envelope["type"] == "error"
    assert envelope["payload"]["code"] == "DeploymentNotFound"


@pytest.mark.asyncio
async def test_emit_voice_error_never_raises_without_a_websocket() -> None:
    """Error reporting must not itself become a new failure path."""
    info = classify_voice_error(Exception("boom"), source="llm")

    await emit_voice_error(None, info, session_id="s1")


@pytest.mark.asyncio
async def test_emit_voice_error_swallows_transport_failures() -> None:
    class Broken:
        async def send_json(self, payload: dict[str, Any]) -> None:
            raise RuntimeError("socket is gone")

    info = classify_voice_error(Exception("boom"), source="llm")

    await emit_voice_error(Broken(), info, session_id="s1")


def test_voice_error_close_code_is_in_the_private_use_range() -> None:
    assert 4000 <= WS_CLOSE_CODE_VOICE_ERROR <= 4999


# ---------------------------------------------------------------------------
# fail_websocket_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fatal_startup_failure_is_sent_then_closed_with_a_reason() -> None:
    """The headline end-to-end path: bad model config must not be silent."""
    from apps.artagent.backend.voice.shared.errors import fail_websocket_session

    ws = _FakeWebSocket()
    exc = Exception(
        "Error code: 404 - {'error': {'code': 'DeploymentNotFound', 'message': "
        "'The API deployment for this resource does not exist.'}}"
    )

    info = await fail_websocket_session(ws, exc, session_id="s1", source="llm", model="gpt-4o-mini")

    # The client is told what happened...
    assert ws.sent, "the error envelope must reach the client"
    payload = ws.sent[-1]["payload"]
    assert payload["code"] == "DeploymentNotFound"
    assert payload["remediation"]

    # ...before the socket is closed with a descriptive reason.
    assert ws.closed_with is not None
    code, reason = ws.closed_with
    assert code == WS_CLOSE_CODE_VOICE_ERROR
    assert "DeploymentNotFound" in reason
    assert len(reason.encode("utf-8")) <= 123
    assert info.code == "DeploymentNotFound"


@pytest.mark.asyncio
async def test_an_already_disconnected_socket_is_not_closed_again() -> None:
    from apps.artagent.backend.voice.shared.errors import fail_websocket_session
    from fastapi.websockets import WebSocketState

    ws = _FakeWebSocket()
    ws.client_state = WebSocketState.DISCONNECTED

    await fail_websocket_session(ws, Exception("boom"), session_id="s1")

    assert ws.closed_with is None


@pytest.mark.asyncio
async def test_a_preclassified_error_is_used_verbatim() -> None:
    """A handler's recorded startup error must not be re-classified into noise."""
    from apps.artagent.backend.voice.shared.errors import fail_websocket_session

    ws = _FakeWebSocket()
    recorded = VoiceErrorInfo(
        code="ModelUnavailableInRegion",
        message="The realtime model is not available in this region.",
        remediation="Pick a supported region.",
        source="voicelive",
        fatal=True,
    )

    info = await fail_websocket_session(
        ws, RuntimeError("a generic wrapper error"), session_id="s1", preclassified=recorded
    )

    assert info is recorded
    assert ws.sent[-1]["payload"]["code"] == "ModelUnavailableInRegion"


# ---------------------------------------------------------------------------
# Regression: failures that previously stayed invisible
# ---------------------------------------------------------------------------


class _FakeCancellationDetails:
    reason = "CancelledByService"
    error_code = "BadRequest"
    error_details = "Voice 'en-US-NotARealVoice' does not exist."


class _FakeResult:
    cancellation_details = _FakeCancellationDetails()


class _FakeCanceledEventArgs:
    """Stand-in for SpeechRecognitionCanceledEventArgs."""

    result = _FakeResult()


def test_speech_sdk_event_args_are_reduced_to_text() -> None:
    """The SDK hands cancel callbacks an event object, never a string."""
    from apps.artagent.backend.voice.speech_cascade.handler import _cancellation_text

    text = _cancellation_text(_FakeCanceledEventArgs())

    assert "does not exist" in text
    assert "BadRequest" in text
    assert _cancellation_text(None) == ""
    assert _cancellation_text("already text") == "already text"


def test_classifier_tolerates_non_string_error_details() -> None:
    """Classification must never raise while explaining someone else's failure."""
    info = classify_speech_cancellation(_FakeCanceledEventArgs(), voice="en-US-NotARealVoice")

    assert info.code
    assert info.source == "tts"


@pytest.mark.asyncio
async def test_non_fatal_failures_keep_the_client_reconnecting() -> None:
    """A transient failure must not permanently disable browser reconnect."""
    from apps.artagent.backend.voice.shared.errors import (
        WS_CLOSE_CODE_VOICE_ERROR,
        WS_CLOSE_CODE_VOICE_ERROR_RETRYABLE,
        fail_websocket_session,
    )

    transient = _FakeWebSocket()
    info = await fail_websocket_session(transient, ConnectionError("blip"), session_id="s1")
    assert info.fatal is False
    assert transient.closed_with[0] == WS_CLOSE_CODE_VOICE_ERROR_RETRYABLE

    fatal = _FakeWebSocket()
    await fail_websocket_session(
        fatal,
        Exception("Error code: 404 - DeploymentNotFound"),
        session_id="s1",
        source="llm",
    )
    assert fatal.closed_with[0] == WS_CLOSE_CODE_VOICE_ERROR


@pytest.mark.asyncio
async def test_the_same_error_is_not_rendered_twice() -> None:
    """A component and the endpoint both report a fatal error; the user sees one."""
    from apps.artagent.backend.voice.shared.errors import emit_voice_error

    ws = _FakeWebSocket()
    info = VoiceErrorInfo(
        code="DeploymentNotFound",
        message="The model deployment 'gpt-4o' was not found.",
        source="llm",
        fatal=True,
    )

    await emit_voice_error(ws, info, session_id="s1")
    await emit_voice_error(ws, info, session_id="s1")

    assert len(ws.sent) == 1

    other = VoiceErrorInfo(code="RateLimitExceeded", message="Throttled.", source="llm")
    await emit_voice_error(ws, other, session_id="s1")

    assert len(ws.sent) == 2
