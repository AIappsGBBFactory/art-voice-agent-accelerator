"""
Voice Pipeline Error Classification and Surfacing
=================================================

Both orchestration modes (SpeechCascade and VoiceLive) can fail for the same
class of configuration reasons: the agent points at a model deployment that
doesn't exist in the Azure AI Foundry resource, the configured neural voice
isn't available, credentials are wrong, or the deployment is out of quota.

Historically those failures were logged and swallowed, so the caller heard
silence and the operator UI showed nothing. This module provides:

* :class:`VoiceErrorInfo` - a normalized, user-presentable error record.
* :func:`classify_voice_error` - map an arbitrary exception to that record.
* :func:`classify_speech_cancellation` - map an Azure Speech SDK cancellation.
* :func:`classify_voicelive_server_error` - map a VoiceLive ``error`` event.
* :func:`emit_voice_error` - deliver the record to the client WebSocket.

Usage:
    from apps.artagent.backend.voice.shared.errors import (
        classify_voice_error,
        emit_voice_error,
    )

    try:
        await connect_to_model()
    except Exception as exc:
        info = classify_voice_error(exc, source="voicelive")
        await emit_voice_error(websocket, info, session_id=session_id)
        raise
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = get_logger("voice.shared.errors")

ErrorSource = Literal["llm", "tts", "stt", "voicelive", "config", "connection", "unknown"]

# WebSocket close code used when the session is torn down because of a
# configuration/runtime failure rather than a normal hangup. 4500 sits in the
# private-use range (4000-4999) so it never collides with protocol codes.
WS_CLOSE_CODE_VOICE_ERROR = 4500

# Same family, but signals a failure that may succeed on a retry (a network
# blip, a rate limit). Clients should reconnect with backoff rather than give up.
WS_CLOSE_CODE_VOICE_ERROR_RETRYABLE = 4501

# VoiceLive reports these when a barge-in cancel races a response that already
# completed. They are normal control flow, not failures.
BENIGN_VOICELIVE_ERROR_CODES = frozenset(
    {
        "response_cancel_not_active",
        "response_cancel_no_active_response",
    }
)

_MAX_DETAIL_CHARS = 400


@dataclass(frozen=True)
class VoiceErrorInfo:
    """A normalized, user-presentable voice pipeline error.

    Attributes:
        code: Machine-readable code, e.g. ``DeploymentNotFound``.
        message: Short user-facing description of what went wrong.
        details: Technical detail (raw provider text), truncated for transport.
        remediation: Actionable guidance for fixing the configuration.
        source: Pipeline stage that failed.
        fatal: Whether the session cannot continue after this error.
        spoken_message: What the agent should say aloud, if anything.
    """

    code: str
    message: str
    details: str = ""
    remediation: str = ""
    source: ErrorSource = "unknown"
    fatal: bool = False
    spoken_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable dict for WebSocket / logging use."""
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "fatal": self.fatal,
        }
        if self.details:
            payload["details"] = self.details
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    def as_json(self) -> str:
        """Serialize to a JSON string (used by ``OrchestratorResult.error``)."""
        return json.dumps(self.to_payload())

    def log_summary(self) -> str:
        """Return a compact single-line summary for logs."""
        return f"{self.code}: {self.message}" + (f" | {self.details}" if self.details else "")


def _truncate(text: str, limit: int = _MAX_DETAIL_CHARS) -> str:
    """Trim technical detail so it stays readable in the UI and in logs."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _coerce_error_text(value: Any) -> str:
    """Normalize an arbitrary SDK error payload into stripped text.

    Speech SDK callbacks hand back event-args objects rather than strings, and a
    classifier that assumes ``str`` would raise while trying to explain someone
    else's failure. Coercing here keeps classification total.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return str(value).strip()
    except Exception:  # pragma: no cover - defensive
        return ""


def _status_code_of(exception: BaseException, error_text: str = "") -> int | None:
    """Best-effort extraction of an HTTP status code from an SDK exception.

    Checks the structured attributes first, then falls back to parsing the
    message. Provider errors are frequently re-raised as a plain ``Exception``
    whose only trace of the status is text like ``Error code: 429 - ...``, so
    without the text fallback a throttling failure looks like an unknown error.
    """
    for attr in ("status_code", "http_status", "code"):
        value = getattr(exception, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exception, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status

    if error_text:
        match = re.search(r"(?:error code|status(?:\s+code)?)[:\s]+(\d{3})", error_text, re.I)
        if not match:
            match = re.search(r"\((\d{3})\)", error_text)
        if match:
            parsed = int(match.group(1))
            if 100 <= parsed <= 599:
                return parsed
    return None


def _extract_param(error_text: str) -> str | None:
    """Pull the offending parameter name out of an OpenAI error body."""
    match = re.search(r"'param':\s*'([^']+)'", error_text)
    if match:
        return match.group(1)
    match = re.search(r'"param":\s*"([^"]+)"', error_text)
    return match.group(1) if match else None


def _extract_model_name(error_text: str) -> str | None:
    """Pull a model/deployment name out of a provider error body."""
    for pattern in (
        r"[Dd]eployment(?: name)?[:\s'\"`]+([A-Za-z0-9._\-]+)",
        r"[Mm]odel[:\s'\"`]+([A-Za-z0-9._\-]+)",
    ):
        match = re.search(pattern, error_text)
        if match:
            return match.group(1)
    return None


# ─────────────────────────────────────────────────────────────────────
# Generic exception classification
# ─────────────────────────────────────────────────────────────────────


def classify_voice_error(
    exception: BaseException,
    *,
    source: ErrorSource = "unknown",
    model: str | None = None,
    voice: str | None = None,
    agent: str | None = None,
) -> VoiceErrorInfo:
    """Map an arbitrary exception onto a presentable :class:`VoiceErrorInfo`.

    Recognizes the Azure OpenAI / Azure AI Foundry and Azure Speech failure
    modes that configuration mistakes actually produce: a missing model
    deployment, a bad key or missing RBAC role, exhausted quota, a content
    filter block, an oversized context, and unsupported request parameters.

    Args:
        exception: The exception raised by the SDK or transport.

    Keyword Args:
        source: Pipeline stage that raised (``llm``, ``tts``, ``voicelive``...).
        model: Model/deployment name in play, included in the metadata.
        voice: Voice name in play, included in the metadata.
        agent: Active agent name, included in the metadata.

    Returns:
        A populated :class:`VoiceErrorInfo`. Never raises.
    """
    exc_name = type(exception).__name__
    try:
        error_text = str(exception) or exc_name
    except Exception:  # pragma: no cover - defensive: __str__ can itself raise
        error_text = exc_name
    lowered = error_text.lower()
    try:
        status = _status_code_of(exception, error_text)
    except Exception:  # pragma: no cover - defensive
        status = None
    metadata: dict[str, Any] = {"exception": exc_name}
    if model:
        metadata["model"] = model
    if voice:
        metadata["voice"] = voice
    if agent:
        metadata["agent"] = agent
    if status is not None:
        metadata["status_code"] = status

    def build(
        code: str,
        message: str,
        remediation: str,
        *,
        fatal: bool = False,
        spoken: str = "",
    ) -> VoiceErrorInfo:
        return VoiceErrorInfo(
            code=code,
            message=message,
            details=_truncate(error_text),
            remediation=remediation,
            source=source,
            fatal=fatal,
            spoken_message=spoken,
            metadata=metadata,
        )

    # ── Cancellation is control flow, not an error ──
    if isinstance(exception, asyncio.CancelledError):
        return build(
            "Cancelled",
            "The operation was cancelled.",
            "No action needed - this usually means the caller interrupted the agent.",
        )

    # ── Model / deployment not found ──
    deployment_markers = (
        "deploymentnotfound",
        "the api deployment for this resource does not exist",
        "does not exist and cannot be created",
        "model_not_found",
        "modelnotfound",
        "unknown model",
        "invalid model",
        "unsupported model",
        "does not exist or you do not have access",
        "do not have access to it",
        "resourcenotfound",
    )
    if any(marker in lowered for marker in deployment_markers) or (
        status == 404 and source in {"llm", "voicelive"}
    ):
        resolved_model = model or _extract_model_name(error_text)
        if resolved_model:
            metadata["model"] = resolved_model
        target = f"'{resolved_model}'" if resolved_model else "the configured model"
        return build(
            "DeploymentNotFound",
            f"The model deployment {target} was not found.",
            "Check that the agent's model/deployment name matches a deployment that "
            "exists in your Azure AI Foundry resource, and that the deployment is in "
            "the same region as the endpoint the app is pointed at.",
            fatal=True,
            spoken="I'm sorry, I'm not able to connect to my language model right now.",
        )

    # ── Model exists but is not available in this region/SKU ──
    if "not available in" in lowered or "not supported in region" in lowered:
        return build(
            "ModelUnavailableInRegion",
            "The configured model is not available in this region.",
            "Pick a region that offers this model, or select a model that is "
            "available in the region your Azure AI Foundry resource is deployed to.",
            fatal=True,
            spoken="I'm sorry, I'm not able to connect to my language model right now.",
        )

    # ── Authentication / authorization ──
    auth_markers = (
        "invalidapikey",
        "invalid api key",
        "access denied",
        "unauthorized",
        "permissiondenied",
        "authentication error",
        "credential",
        "please check subscription information",
    )
    if (
        status in {401, 403}
        or exc_name in {"AuthenticationError", "PermissionDeniedError", "ClientAuthenticationError"}
        or any(marker in lowered for marker in auth_markers)
    ):
        return build(
            "AuthenticationError",
            "Authentication with the Azure service failed.",
            "Verify the API key or that the app's managed identity has the required "
            "role (Cognitive Services OpenAI User / Speech User) on the resource, and "
            "that the endpoint URL is correct.",
            fatal=True,
            spoken="I'm sorry, I'm having trouble reaching my services right now.",
        )

    # ── Quota / rate limiting ──
    if (
        status == 429
        or exc_name == "RateLimitError"
        or "ratelimit" in lowered.replace("_", "").replace(" ", "")
        or "quota" in lowered
    ):
        return build(
            "RateLimitExceeded",
            "The request was throttled or the deployment is out of quota.",
            "Wait and retry, raise the tokens-per-minute quota on the deployment, or "
            "route to a deployment with more capacity.",
            spoken="I'm sorry, I'm a little overloaded right now. Could you try again?",
        )

    # ── Content filtering ──
    content_filter_markers = (
        "content_filter",
        "contentfilter",
        "responsibleaipolicy",
        "responsible ai policy",
        "content management policy",
        "content filtering policy",
    )
    if any(marker in lowered for marker in content_filter_markers):
        return build(
            "ContentFiltered",
            "The request was blocked by the content filter.",
            "Rephrase the request, or adjust the content filter policy on the "
            "deployment if the block is a false positive.",
            spoken="I'm sorry, I can't help with that request.",
        )

    # ── Context window ──
    if "context_length_exceeded" in lowered or "maximum context length" in lowered:
        return build(
            "ContextLengthExceeded",
            "The conversation exceeded the model's context window.",
            "Start a new session, or lower the retained history / enable context "
            "compaction for this agent.",
            spoken="I'm sorry, this conversation has gotten too long for me to follow.",
        )

    # ── Unsupported request parameter (common with reasoning models) ──
    if "unsupported_parameter" in lowered or "unsupported_value" in lowered:
        param = _extract_param(error_text)
        if param:
            metadata["param"] = param
        target = f"'{param}'" if param else "a request parameter"
        return build(
            "UnsupportedParameter",
            f"The model rejected {target}.",
            "This model may not accept the parameter the agent is sending (for "
            "example max_tokens vs max_completion_tokens, or a custom temperature). "
            "Adjust the agent's model configuration or endpoint_preference.",
            fatal=True,
            spoken="I'm sorry, I'm not able to answer that right now.",
        )

    # ── Voice not available ──
    if "voice" in lowered and any(
        marker in lowered for marker in ("not found", "not supported", "invalid", "does not exist")
    ):
        resolved_voice = voice or _extract_model_name(error_text)
        if resolved_voice:
            metadata["voice"] = resolved_voice
        target = f"'{resolved_voice}'" if resolved_voice else "the configured voice"
        return build(
            "VoiceNotAvailable",
            f"The speech voice {target} is not available.",
            "Check the voice name against the voices supported by your Speech "
            "resource's region. Custom and HD voices are region-limited.",
            fatal=True,
        )

    # ── Connectivity / timeout ──
    if (
        isinstance(exception, (TimeoutError, ConnectionError))
        or "timeout" in lowered
        or "timed out" in lowered
        or "connection" in lowered
        or "getaddrinfo" in lowered
    ):
        return build(
            "ConnectionError",
            "Could not reach the Azure service.",
            "Check the endpoint URL, network egress, and any private endpoint or "
            "firewall rules on the resource.",
            spoken="I'm sorry, I'm having trouble connecting right now.",
        )

    # ── Bad request that we could not classify further ──
    if status == 400:
        return build(
            "InvalidRequest",
            "The Azure service rejected the request as invalid.",
            "Review the agent's model and voice configuration for values the "
            "service does not accept.",
            fatal=True,
        )

    return build(
        "UnknownError",
        "An unexpected error occurred in the voice pipeline.",
        "Check the backend logs for the full stack trace.",
    )


# ─────────────────────────────────────────────────────────────────────
# Azure Speech SDK cancellation classification
# ─────────────────────────────────────────────────────────────────────


def classify_speech_cancellation(
    error_details: str | None,
    *,
    reason: Any = None,
    voice: str | None = None,
    source: ErrorSource = "tts",
) -> VoiceErrorInfo:
    """Classify an Azure Speech SDK cancellation into a presentable error.

    The Speech SDK does not raise for a bad voice name or a bad key; it returns
    a result whose ``reason`` is ``Canceled`` and stashes the real cause in
    ``cancellation_details.error_details``. This turns that string into the same
    shape as :func:`classify_voice_error`.

    Args:
        error_details: ``cancellation_details.error_details`` from the SDK.

    Keyword Args:
        reason: The SDK ``ResultReason``, included in the details when present.
        voice: The voice name that was requested.
        source: ``tts`` or ``stt``.

    Returns:
        A populated :class:`VoiceErrorInfo`.
    """
    detail_text = _coerce_error_text(error_details)
    lowered = detail_text.lower()
    metadata: dict[str, Any] = {}
    if voice:
        metadata["voice"] = voice
    if reason is not None:
        metadata["reason"] = str(reason)

    if not detail_text and reason is not None:
        detail_text = f"Speech synthesis result reason: {reason}"
        lowered = detail_text.lower()

    voice_markers = (
        "voice does not exist",
        "unsupported voice",
        "voice not found",
        "synthesisvoicenotfound",
        "invalid voice",
        "no voice",
    )
    if any(marker in lowered for marker in voice_markers) or (
        "voice" in lowered and "400" in lowered
    ):
        target = f"'{voice}'" if voice else "the configured voice"
        return VoiceErrorInfo(
            code="VoiceNotAvailable",
            message=f"The speech voice {target} is not available.",
            details=_truncate(detail_text),
            remediation=(
                "Check the voice name against the voices supported by your Speech "
                "resource's region. Custom and HD voices are region-limited."
            ),
            source=source,
            fatal=True,
            metadata=metadata,
        )

    auth_markers = (
        "401",
        "403",
        "authentication error",
        "unauthorized",
        "forbidden",
        "please check subscription information",
    )
    if any(marker in lowered for marker in auth_markers):
        return VoiceErrorInfo(
            code="AuthenticationError",
            message="Authentication with the Azure Speech service failed.",
            details=_truncate(detail_text),
            remediation=(
                "Verify the Speech key/region, or that the app's managed identity has "
                "the Cognitive Services Speech User role on the Speech resource."
            ),
            source=source,
            fatal=True,
            metadata=metadata,
        )

    if "429" in lowered or "too many requests" in lowered or "quota" in lowered:
        return VoiceErrorInfo(
            code="RateLimitExceeded",
            message="The Azure Speech service throttled the request.",
            details=_truncate(detail_text),
            remediation="Retry, or increase the concurrency limit on the Speech resource.",
            source=source,
            metadata=metadata,
        )

    if "connection" in lowered or "timeout" in lowered or "timed out" in lowered:
        return VoiceErrorInfo(
            code="ConnectionError",
            message="Could not reach the Azure Speech service.",
            details=_truncate(detail_text),
            remediation=(
                "Check the Speech endpoint/region, network egress, and any private "
                "endpoint or firewall rules."
            ),
            source=source,
            metadata=metadata,
        )

    return VoiceErrorInfo(
        code="SpeechSynthesisFailed" if source == "tts" else "SpeechRecognitionFailed",
        message=("Speech synthesis failed." if source == "tts" else "Speech recognition failed."),
        details=_truncate(detail_text),
        remediation="Check the backend logs and the Speech resource health.",
        source=source,
        metadata=metadata,
    )


# ─────────────────────────────────────────────────────────────────────
# VoiceLive server event classification
# ─────────────────────────────────────────────────────────────────────


def classify_voicelive_server_error(
    code: str | None,
    message: str | None,
    *,
    details: Any = None,
    model: str | None = None,
    agent: str | None = None,
) -> VoiceErrorInfo | None:
    """Classify a VoiceLive ``error`` server event.

    Args:
        code: The ``error.code`` field from the event.
        message: The ``error.message`` field from the event.

    Keyword Args:
        details: The ``error.details`` field, if the service supplied one.
        model: The model the session connected with.
        agent: The active agent name.

    Returns:
        A :class:`VoiceErrorInfo`, or ``None`` when the code is a benign
        cancel-race that should not be surfaced.
    """
    if code and code in BENIGN_VOICELIVE_ERROR_CODES:
        return None

    combined = " ".join(str(part) for part in (code, message, details) if part)
    info = classify_voice_error(
        RuntimeError(combined or "Unknown VoiceLive error"),
        source="voicelive",
        model=model,
        agent=agent,
    )

    if info.code != "UnknownError":
        return info

    metadata: dict[str, Any] = {}
    if model:
        metadata["model"] = model
    if agent:
        metadata["agent"] = agent
    if code:
        metadata["voicelive_code"] = code

    return VoiceErrorInfo(
        code=code or "VoiceLiveError",
        message=message or "The Voice Live service reported an error.",
        details=_truncate(str(details) if details else ""),
        remediation="Check the backend logs and the Voice Live session configuration.",
        source="voicelive",
        metadata=metadata,
    )


# ─────────────────────────────────────────────────────────────────────
# Delivery
# ─────────────────────────────────────────────────────────────────────


async def emit_voice_error(
    websocket: WebSocket | None,
    info: VoiceErrorInfo,
    *,
    session_id: str | None = None,
    call_id: str | None = None,
    conn_id: str | None = None,
    broadcast_only: bool = True,
) -> bool:
    """Send a classified error to the client and any attached dashboards.

    Delivery is best effort: a failure to reach the client must never mask the
    original error, so every failure path here is logged and swallowed.

    Args:
        websocket: The session WebSocket. ``None`` is tolerated (no-op).
        info: The classified error to surface.

    Keyword Args:
        session_id: Session correlation id (falls back to ``websocket.state``).
        call_id: Call correlation id.
        conn_id: Connection id for direct delivery.
        broadcast_only: Broadcast to all session subscribers rather than
            targeting a single connection. Defaults to ``True`` so dashboards
            observe the failure even when the caller is on a phone.

    Returns:
        ``True`` when the envelope was handed to a delivery path.
    """
    # A fatal error is often reported by the component that failed *and* by the
    # endpoint that unwinds the session, and a retrying SDK can report the same
    # cause dozens of times a second. Recognise an exact repeat on this socket so
    # the user sees one card and the log keeps one actionable ERROR line.
    fingerprint = (info.code, info.message, info.source)
    repeat = websocket is not None and getattr(websocket, "_last_voice_error", None) == fingerprint

    if repeat:
        logger.debug(
            "Repeat voice pipeline error suppressed | session=%s %s", session_id, info.code
        )
    else:
        logger.error(
            "Voice pipeline error | session=%s call=%s %s",
            session_id,
            call_id,
            info.log_summary(),
            extra={"error_code": info.code, "error_source": info.source, "fatal": info.fatal},
        )

    if websocket is None:
        return False

    if repeat:
        return True

    try:
        websocket._last_voice_error = fingerprint
    except Exception:  # noqa: BLE001 - transport may forbid attribute assignment
        pass

    # Imported lazily: ws_helpers pulls in FastAPI/app state and importing it at
    # module scope would create a cycle with the voice package.
    from apps.artagent.backend.src.ws_helpers.envelopes import make_error_envelope
    from apps.artagent.backend.src.ws_helpers.shared_ws import send_session_envelope

    ws_state = getattr(websocket, "state", None)
    resolved_session_id = session_id or getattr(ws_state, "session_id", None)
    resolved_call_id = call_id or getattr(ws_state, "call_connection_id", None)

    envelope = make_error_envelope(
        info.message,
        info.code,
        topic="session",
        session_id=resolved_session_id,
        call_id=resolved_call_id,
        code=info.code,
        details=info.details,
        remediation=info.remediation,
        source=info.source,
        fatal=info.fatal,
    )

    delivered = False
    try:
        delivered = await send_session_envelope(
            websocket,
            envelope,
            session_id=resolved_session_id,
            conn_id=conn_id,
            event_label=f"voice_error_{info.source}",
            broadcast_only=broadcast_only,
        )
    except Exception:  # noqa: BLE001 - never let delivery mask the real error
        logger.debug("Session envelope delivery failed for voice error", exc_info=True)

    if delivered:
        return True

    # Last resort: write straight to the socket. A startup failure happens before
    # the connection is registered with the connection manager, so the broadcast
    # path has no subscribers and would silently drop the very error the user
    # needs to see.
    send_json = getattr(websocket, "send_json", None)
    if send_json is None:
        return False
    try:
        await send_json(envelope)
        return True
    except Exception:  # noqa: BLE001 - socket may already be closed
        logger.debug("Direct voice error delivery failed", exc_info=True)
        return False


async def emit_exception(
    websocket: WebSocket | None,
    exception: BaseException,
    *,
    source: ErrorSource = "unknown",
    session_id: str | None = None,
    call_id: str | None = None,
    model: str | None = None,
    voice: str | None = None,
    agent: str | None = None,
) -> VoiceErrorInfo:
    """Classify ``exception`` and surface it in one call.

    Args:
        websocket: The session WebSocket (``None`` is tolerated).
        exception: The exception to classify and report.

    Keyword Args:
        source: Pipeline stage that raised.
        session_id: Session correlation id.
        call_id: Call correlation id.
        model: Model/deployment name in play.
        voice: Voice name in play.
        agent: Active agent name.

    Returns:
        The :class:`VoiceErrorInfo` that was surfaced, so callers can reuse it
        for a spoken fallback or a WebSocket close reason.
    """
    info = classify_voice_error(exception, source=source, model=model, voice=voice, agent=agent)
    await emit_voice_error(websocket, info, session_id=session_id, call_id=call_id)
    return info


def close_reason_for(info: VoiceErrorInfo) -> str:
    """Build a WebSocket close reason string, truncated to the frame limit.

    WebSocket close reasons must fit in 123 UTF-8 bytes.
    """
    reason = f"{info.code}: {info.message}"
    encoded = reason.encode("utf-8")
    if len(encoded) <= 123:
        return reason
    return encoded[:120].decode("utf-8", errors="ignore") + "..."


async def fail_websocket_session(
    websocket: Any,
    exception: BaseException,
    *,
    session_id: str | None = None,
    call_id: str | None = None,
    conn_id: str | None = None,
    source: ErrorSource = "connection",
    model: str | None = None,
    preclassified: VoiceErrorInfo | None = None,
) -> VoiceErrorInfo:
    """Surface a fatal session failure to the client, then close the socket.

    Terminating a voice WebSocket with a bare re-raise gives the browser an
    opaque 1006/1011 close and leaves the user staring at a dead session. This
    sends the structured error envelope first (so the UI can render the cause and
    remediation) and only then closes with a descriptive reason.

    Args:
        websocket: The client WebSocket. May already be disconnected.
        exception: The exception that ended the session.
        session_id: Session identifier for routing and logging.
        call_id: ACS call connection id, when telephony-backed.
        conn_id: Connection identifier for logging.
        source: Which subsystem failed, used when classifying.
        model: Model or deployment name in play, used when classifying.
        preclassified: An already-classified error (for example a handler's
            recorded startup error) to use instead of re-classifying.

    Returns:
        The :class:`VoiceErrorInfo` that was delivered.
    """
    info = preclassified or classify_voice_error(exception, source=source, model=model)

    await emit_voice_error(
        websocket,
        info,
        session_id=session_id,
        call_id=call_id,
        conn_id=conn_id,
    )

    try:
        from fastapi.websockets import WebSocketState

        client_state = getattr(websocket, "client_state", None)
        # Close when the socket is connected, or when the transport does not
        # expose a state at all. Only skip when it is positively known to be
        # disconnected, so a non-Starlette transport still gets a close frame
        # carrying the reason.
        if client_state is None or client_state is WebSocketState.CONNECTED:
            close = getattr(websocket, "close", None)
            if close is not None:
                # 4500 tells the client "do not retry, the config is broken".
                # Reserve it for genuinely fatal errors: a transient blip or a
                # rate limit should still get the client's normal backoff.
                code = (
                    WS_CLOSE_CODE_VOICE_ERROR if info.fatal else WS_CLOSE_CODE_VOICE_ERROR_RETRYABLE
                )
                await close(code=code, reason=close_reason_for(info))
    except Exception:  # pragma: no cover - socket may already be torn down
        logger.debug("Failed to close websocket after voice error", exc_info=True)

    return info


__all__ = [
    "BENIGN_VOICELIVE_ERROR_CODES",
    "WS_CLOSE_CODE_VOICE_ERROR",
    "WS_CLOSE_CODE_VOICE_ERROR_RETRYABLE",
    "ErrorSource",
    "VoiceErrorInfo",
    "classify_speech_cancellation",
    "classify_voice_error",
    "classify_voicelive_server_error",
    "close_reason_for",
    "emit_exception",
    "emit_voice_error",
    "fail_websocket_session",
]
