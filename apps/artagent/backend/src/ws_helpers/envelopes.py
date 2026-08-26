"""
WebSocket Message Envelopes - Simplified
========================================

Clean, focused message formatting for WebSocket communications.
Provides standardized envelope format with minimal complexity.
"""

from datetime import UTC, datetime
from typing import Any, Literal

EnvelopeType = Literal[
    "event", "status", "assistant", "assistant_streaming", "exit", "error", "debug"
]
TopicType = Literal["dashboard", "session", "call", "user", "system", "media"]
SenderType = Literal["Assistant", "User", "System", "ACS", "STT", "TTS"]


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""

    return datetime.now(UTC).isoformat()


def make_envelope(
    *,
    etype: EnvelopeType,
    sender: SenderType,
    payload: dict[str, Any],
    topic: TopicType,
    session_id: str | None = None,
    call_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Build standard WebSocket message envelope."""
    return {
        "type": etype,
        "topic": topic,
        "session_id": session_id,
        "call_id": call_id,
        "user_id": user_id,
        "sender": sender,
        "ts": _utc_now_iso(),
        "payload": payload,
        "speaker_id": sender,
    }


def make_status_envelope(
    message: str,
    *,
    sender: SenderType = "System",
    topic: TopicType = "system",
    session_id: str | None = None,
    call_id: str | None = None,
    user_id: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Create status message envelope."""
    payload = {"message": message}
    if label:
        payload["label"] = label

    payload.setdefault("timestamp", _utc_now_iso())

    return make_envelope(
        etype="status",
        sender=sender,
        payload=payload,
        topic=topic,
        session_id=session_id,
        call_id=call_id,
        user_id=user_id,
    )


def make_assistant_envelope(
    content: str,
    *,
    sender: SenderType = "Assistant",
    session_id: str | None = None,
    call_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create non-streaming assistant response envelope."""
    return make_envelope(
        etype="assistant",
        sender=sender,
        payload={"content": content, "message": content, "streaming": False},
        topic="session",
        session_id=session_id,
        call_id=call_id,
        user_id=user_id,
    )


def make_assistant_streaming_envelope(
    content: str,
    *,
    sender: SenderType = "Assistant",
    session_id: str | None = None,
    call_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create assistant streaming response envelope."""
    return make_envelope(
        etype="assistant_streaming",
        sender=sender,
        payload={"content": content, "streaming": True},
        topic="session",
        session_id=session_id,
        call_id=call_id,
        user_id=user_id,
    )


def make_event_envelope(
    event_type: str,
    event_data: dict[str, Any],
    *,
    sender: SenderType = "System",
    topic: TopicType = "system",
    session_id: str | None = None,
    call_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    payload_data = dict(event_data or {})
    payload_data.setdefault("timestamp", _utc_now_iso())
    """Create system event envelope."""
    return make_envelope(
        etype="event",
        sender=sender,
        payload={"event_type": event_type, "data": payload_data},
        topic=topic,
        session_id=session_id,
        call_id=call_id,
        user_id=user_id,
    )


def make_error_envelope(
    error_message: str,
    error_type: str = "unknown",
    *,
    sender: SenderType = "System",
    topic: TopicType = "system",
    session_id: str | None = None,
    call_id: str | None = None,
    user_id: str | None = None,
    code: str | None = None,
    details: str | None = None,
    remediation: str | None = None,
    source: str | None = None,
    fatal: bool = False,
) -> dict[str, Any]:
    """Create error message envelope.

    Args:
        error_message: Human-readable description of what went wrong.
        error_type: Coarse category of the failure (kept for backwards compatibility).

    Keyword Args:
        sender: Envelope sender label.
        topic: Routing topic for the connection manager.
        session_id: Session correlation id.
        call_id: Call correlation id.
        user_id: User correlation id.
        code: Machine-readable error code (e.g. ``DeploymentNotFound``).
        details: Technical detail such as the raw provider error text.
        remediation: Actionable guidance the operator can follow to fix it.
        source: Pipeline stage that failed (``llm``, ``tts``, ``stt``, ``voicelive``...).
        fatal: Whether the session cannot continue after this error.

    Returns:
        Envelope dict ready to be sent over the session WebSocket.
    """
    resolved_code = code or error_type
    payload: dict[str, Any] = {
        "error_message": error_message,
        "error_type": error_type,
        "code": resolved_code,
        "fatal": fatal,
        # ``message``/``content`` keep the payload renderable by the generic
        # text-based UI paths that already understand session envelopes.
        "message": error_message,
        "content": error_message,
    }
    if details:
        payload["details"] = details
    if remediation:
        payload["remediation"] = remediation
    if source:
        payload["source"] = source

    payload.setdefault("timestamp", _utc_now_iso())

    return make_envelope(
        etype="error",
        sender=sender,
        payload=payload,
        topic=topic,
        session_id=session_id,
        call_id=call_id,
        user_id=user_id,
    )
