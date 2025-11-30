"""
V1 API Handlers
===============

Business logic handlers for V1 API endpoints.

Handler Architecture:
- speech_cascade_handler: Generic three-thread speech processing (protocol-agnostic)
- media_handler: Unified handler for both ACS and Browser (composing SpeechCascadeHandler)
- voice_live_sdk_handler: VoiceLive SDK handler for alternative transport

The unified MediaHandler supports:
- ACS transport: handle_media_message() for JSON protocol
- Browser transport: run() message loop for raw audio/text

The separation allows:
- Easy testing of each layer independently
- Swapping transport layers without changing speech processing
- Clear separation of protocol-specific vs generic logic
"""

from .speech_cascade_handler import (
    SpeechCascadeHandler,
    SpeechEvent,
    SpeechEventType,
    ThreadBridge,
    RouteTurnThread,
    SpeechSDKThread,
    BargeInController,
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
from .voice_live_sdk_handler import VoiceLiveSDKHandler

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
