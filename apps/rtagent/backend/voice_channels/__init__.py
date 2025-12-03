"""
Voice Channels - Speech Orchestration Layer
============================================

Protocol-agnostic voice processing handlers that sit between transport layers
(ACS, WebRTC, VoiceLive) and AI orchestrators (gpt_flow, LiveOrchestrator).

Architecture:
    Transport Layer (ACS/WebRTC/VoiceLive SDK)
           │
           ▼
    Voice Channels (this module)
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
  Speech      VoiceLive
  Cascade     SDK Handler
  Handler
    │             │
    ▼             ▼
  gpt_flow    LiveOrchestrator


Structure:
    voice_channels/
    ├── speech_cascade/
    │   ├── handler.py      # SpeechCascadeHandler
    │   └── metrics.py      # STT/turn/barge-in metrics
    ├── voicelive/
    │   ├── handler.py      # VoiceLiveSDKHandler
    │   └── metrics.py      # OTel latency metrics
    └── orchestrators/
        ├── base.py             # VoiceOrchestrator protocol
        ├── gpt_flow_adapter.py # GPTFlowOrchestrator
        └── live_adapter.py     # LiveOrchestratorAdapter
"""

# Speech Cascade (STT→LLM→TTS three-thread architecture)
from .speech_cascade import (
    SpeechCascadeHandler,
    SpeechEvent,
    SpeechEventType,
    ThreadBridge,
    RouteTurnThread,
    SpeechSDKThread,
    BargeInController,
    ResponseSender,
    TranscriptEmitter,
    record_stt_recognition,
    record_turn_processing,
    record_barge_in,
)

# VoiceLive SDK (Azure VoiceLive + multi-agent)
from .voicelive import (
    VoiceLiveSDKHandler,
    record_llm_ttft,
    record_tts_ttfb,
    record_stt_latency,
    record_turn_complete,
)

# Orchestrator protocol and adapters
from .orchestrators import (
    VoiceOrchestrator,
    OrchestratorCapabilities,
    OrchestratorContext,
    OrchestratorResult,
    GPTFlowOrchestrator,
    get_gpt_flow_orchestrator,
    LiveOrchestratorAdapter,
    wrap_live_orchestrator,
)

# Handoff strategies
from .handoffs import (
    HandoffContext,
    HandoffResult,
    HandoffStrategy,
    ToolBasedHandoff,
    StateBasedHandoff,
    create_tool_based_handoff,
    create_state_based_handoff,
    HANDOFF_MAP,
)

__all__ = [
    # Speech Cascade Handler (STT→LLM→TTS)
    "SpeechCascadeHandler",
    "SpeechEvent",
    "SpeechEventType",
    "ThreadBridge",
    "RouteTurnThread",
    "SpeechSDKThread",
    "BargeInController",
    "ResponseSender",
    "TranscriptEmitter",
    # Speech Cascade Metrics
    "record_stt_recognition",
    "record_turn_processing",
    "record_barge_in",
    # VoiceLive SDK Handler
    "VoiceLiveSDKHandler",
    # VoiceLive Metrics
    "record_llm_ttft",
    "record_tts_ttfb",
    "record_stt_latency",
    "record_turn_complete",
    # Orchestrator Protocol
    "VoiceOrchestrator",
    "OrchestratorCapabilities",
    "OrchestratorContext",
    "OrchestratorResult",
    # Orchestrator Adapters
    "GPTFlowOrchestrator",
    "get_gpt_flow_orchestrator",
    "LiveOrchestratorAdapter",
    "wrap_live_orchestrator",
    # Handoff Strategies
    "HandoffContext",
    "HandoffResult",
    "HandoffStrategy",
    "ToolBasedHandoff",
    "StateBasedHandoff",
    "create_tool_based_handoff",
    "create_state_based_handoff",
    "HANDOFF_MAP",
]
