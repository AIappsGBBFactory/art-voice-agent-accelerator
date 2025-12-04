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
    # Metrics
    "record_stt_recognition",
    "record_turn_processing",
    "record_barge_in",
]
