"""
Voice Messaging - WebSocket Communication Layer
================================================

Re-exports WebSocket helpers for voice channel communication.
This module provides a unified interface for messaging across
different voice transports (ACS, Browser, VoiceLive).

Usage:
    from apps.rtagent.backend.voice.messaging import (
        send_tts_audio,
        send_response_to_acs,
        send_user_transcript,
        send_user_partial_transcript,
        send_session_envelope,
        broadcast_session_envelope,
        make_envelope,
        make_status_envelope,
        make_assistant_streaming_envelope,
        BrowserBargeInController,
    )

Migration Note:
    These are re-exported from apps.rtagent.backend.src.ws_helpers
    for now. The goal is to provide a stable import path while
    the underlying implementation may be refactored.
"""

# ─────────────────────────────────────────────────────────────────────────────
# TTS and Audio Playback
# ─────────────────────────────────────────────────────────────────────────────
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
    send_tts_audio,
    send_response_to_acs,
)

# ─────────────────────────────────────────────────────────────────────────────
# Transcript Broadcasting
# ─────────────────────────────────────────────────────────────────────────────
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
    send_user_transcript,
    send_user_partial_transcript,
    send_session_envelope,
    broadcast_session_envelope,
)

# ─────────────────────────────────────────────────────────────────────────────
# Envelope Builders
# ─────────────────────────────────────────────────────────────────────────────
from apps.rtagent.backend.src.ws_helpers.envelopes import (
    make_envelope,
    make_status_envelope,
    make_assistant_envelope,
    make_assistant_streaming_envelope,
    make_event_envelope,
)

# ─────────────────────────────────────────────────────────────────────────────
# Browser Barge-In Controller
# Distinct from speech_cascade.BargeInController - this one manages
# browser-specific metadata and UI control messages.
# ─────────────────────────────────────────────────────────────────────────────
from apps.rtagent.backend.src.ws_helpers.barge_in import (
    BargeInController as BrowserBargeInController,
)

__all__ = [
    # TTS Playback
    "send_tts_audio",
    "send_response_to_acs",
    # Transcript Broadcasting
    "send_user_transcript",
    "send_user_partial_transcript",
    "send_session_envelope",
    "broadcast_session_envelope",
    # Envelope Builders
    "make_envelope",
    "make_status_envelope",
    "make_assistant_envelope",
    "make_assistant_streaming_envelope",
    "make_event_envelope",
    # Browser Barge-In
    "BrowserBargeInController",
]
