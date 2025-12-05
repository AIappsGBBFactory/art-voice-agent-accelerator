"""
V1 API Handlers
===============

Business logic handlers for V1 API endpoints.

Handler Architecture:
- media_handler: Unified handler for both ACS and Browser (composing SpeechCascadeHandler)
- acs_call_lifecycle: ACS call lifecycle management
- dtmf_validation_lifecycle: DTMF validation handling

Voice channel handlers have moved to:
    apps/artagent/backend/voice_channels/

Re-exports are provided here for backward compatibility.
"""

# Voice channel re-exports (moved to apps/artagent/backend/voice_channels/)
from apps.artagent.backend.voice import (
    SpeechCascadeHandler,
    SpeechEvent,
    SpeechEventType,
    ThreadBridge,
    RouteTurnThread,
    SpeechSDKThread,
    BargeInController,
    VoiceLiveSDKHandler,
)

from .media_handler import (
    MediaHandler,
    MediaHandlerConfig,
    TransportType,
    ACSMessageKind,
    ACSMediaHandler,  # Backward compat alias
    pcm16le_rms,
    RMS_SILENCE_THRESHOLD,
    SILENCE_GAP_MS,
    BROWSER_PCM_SAMPLE_RATE,
    BROWSER_SPEECH_RMS_THRESHOLD,
    BROWSER_SILENCE_GAP_SECONDS,
    VOICE_LIVE_PCM_SAMPLE_RATE,
    VOICE_LIVE_SPEECH_RMS_THRESHOLD,
    VOICE_LIVE_SILENCE_GAP_SECONDS,
)

__all__ = [
    # Speech processing (generic)
    "SpeechCascadeHandler",
    "SpeechEvent",
    "SpeechEventType",
    "ThreadBridge",
    "RouteTurnThread",
    "SpeechSDKThread",
    "BargeInController",
    # Unified media handler
    "MediaHandler",
    "MediaHandlerConfig",
    "TransportType",
    "ACSMessageKind",
    "ACSMediaHandler",  # Backward compat alias
    # VoiceLive
    "VoiceLiveSDKHandler",
    # Audio utilities
    "pcm16le_rms",
    "RMS_SILENCE_THRESHOLD",
    "SILENCE_GAP_MS",
    "BROWSER_PCM_SAMPLE_RATE",
    "BROWSER_SPEECH_RMS_THRESHOLD",
    "BROWSER_SILENCE_GAP_SECONDS",
    "VOICE_LIVE_PCM_SAMPLE_RATE",
    "VOICE_LIVE_SPEECH_RMS_THRESHOLD",
    "VOICE_LIVE_SILENCE_GAP_SECONDS",
]
