"""
VoiceLive - Azure VoiceLive SDK Integration
============================================

Handler for Azure VoiceLive SDK with multi-agent orchestration support.
Bridges ACS media streams to the VoiceLive service for real-time
speech-to-speech interactions.

Features:
    - Multi-agent orchestration via LiveOrchestrator
    - DTMF handling and buffering
    - Turn-level latency tracking
    - Session messaging to frontend

Usage:
    from apps.rtagent.backend.voice_channels.voicelive import (
        VoiceLiveSDKHandler,
        record_llm_ttft,
        record_tts_ttfb,
    )
"""

from .handler import VoiceLiveSDKHandler
from .metrics import (
    record_llm_ttft,
    record_tts_ttfb,
    record_stt_latency,
    record_turn_complete,
)

__all__ = [
    "VoiceLiveSDKHandler",
    "record_llm_ttft",
    "record_tts_ttfb",
    "record_stt_latency",
    "record_turn_complete",
]
