"""
Speech Cascade - Three-Thread STT→LLM→TTS Architecture
=======================================================

Protocol-agnostic speech processing implementing the three-thread architecture
for low-latency voice interactions.

Threads:
    🧵 Thread 1: Speech SDK Thread (Never Blocks)
        - Continuous audio recognition
        - Immediate barge-in detection via on_partial callbacks

    🧵 Thread 2: Route Turn Thread (Blocks on Queue Only)
        - AI processing and response generation
        - Orchestrator delegation for TTS and playback

    🧵 Thread 3: Main Event Loop (Never Blocks)
        - Task cancellation for barge-in scenarios
        - Non-blocking coordination with transport layer

Usage:
    from apps.artagent.backend.voice.speech_cascade import (
        SpeechCascadeHandler,
        SpeechEvent,
        SpeechEventType,
        TTSPlayback,
        record_stt_recognition,
    )
"""

from .handler import (
    SpeechCascadeHandler,
    SpeechEvent,
    SpeechEventType,
    ThreadBridge,
    RouteTurnThread,
    SpeechSDKThread,
    BargeInController,
    ResponseSender,
    TranscriptEmitter,
)
from .metrics import (
    record_stt_recognition,
    record_turn_processing,
    record_barge_in,
)
from .orchestrator import CascadeOrchestratorAdapter, StateKeys
from .tts import TTSPlayback, SAMPLE_RATE_BROWSER, SAMPLE_RATE_ACS

# Legacy exports for backward compatibility (deprecated)
from .tts_sender import (
    send_tts_to_browser,
    send_tts_to_acs,
)

__all__ = [
    # Handler components
    "SpeechCascadeHandler",
    "SpeechEvent",
    "SpeechEventType",
    "ThreadBridge",
    "RouteTurnThread",
    "SpeechSDKThread",
    "BargeInController",
    "ResponseSender",
    "TranscriptEmitter",
    # Unified TTS Playback (preferred)
    "TTSPlayback",
    "SAMPLE_RATE_BROWSER",
    "SAMPLE_RATE_ACS",
    # Legacy TTS (deprecated - use TTSPlayback)
    "send_tts_to_browser",
    "send_tts_to_acs",
    # Orchestrator shim
    "CascadeOrchestratorAdapter",
    "StateKeys",  # Re-export of SessionStateKeys for backward compatibility
    # Metrics
    "record_stt_recognition",
    "record_turn_processing",
    "record_barge_in",
]
