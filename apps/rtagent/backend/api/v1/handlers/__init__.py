"""
V1 API Handlers
===============

Business logic handlers for V1 API endpoints.

Handler Architecture:
- speech_cascade_handler: Generic three-thread speech processing (protocol-agnostic)
- acs_media_handler: ACS-specific handler combining protocol + speech processing
- voice_live_sdk_handler: VoiceLive SDK handler for alternative transport
- media_handler: Unified browser audio processing (Voice Live + Speech Cascade)

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
from .acs_media_handler import ACSMediaHandler, ACSMessageKind
from .voice_live_sdk_handler import VoiceLiveSDKHandler
from .media_handler import (
    MediaHandler,
    MediaHandlerConfig,
    MediaHandlerMode,
    pcm16le_rms,
    RMS_SILENCE_THRESHOLD,
    SILENCE_GAP_MS,
    VOICE_LIVE_SPEECH_RMS_THRESHOLD,
    VOICE_LIVE_SILENCE_GAP_SECONDS,
    VOICE_LIVE_PCM_SAMPLE_RATE,
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
    # ACS-specific
    "ACSMediaHandler",
    "ACSMessageKind",
    # VoiceLive
    "VoiceLiveSDKHandler",
    # Browser media handler
    "MediaHandler",
    "MediaHandlerConfig",
    "MediaHandlerMode",
    "pcm16le_rms",
    "RMS_SILENCE_THRESHOLD",
    "SILENCE_GAP_MS",
    "VOICE_LIVE_SPEECH_RMS_THRESHOLD",
    "VOICE_LIVE_SILENCE_GAP_SECONDS",
    "VOICE_LIVE_PCM_SAMPLE_RATE",
]
