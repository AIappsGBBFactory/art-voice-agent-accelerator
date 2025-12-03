"""
Voice Channels - Speech Orchestration Layer
============================================

Protocol-agnostic voice processing handlers that sit between transport layers
(ACS, WebRTC, VoiceLive) and AI orchestrators.

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
  Cascade     Live
  Adapter     Orchestrator


Structure:
    voice_channels/
    ├── speech_cascade/
    │   ├── handler.py      # SpeechCascadeHandler (three-thread architecture)
    │   └── metrics.py      # STT/turn/barge-in metrics
    ├── voicelive/
    │   ├── handler.py      # VoiceLiveSDKHandler
    │   ├── agent_adapter.py # VoiceLiveAgentAdapter (UnifiedAgent → VoiceLive SDK)
    │   └── metrics.py      # OTel latency metrics
    ├── orchestrators/
    │   ├── base.py             # OrchestratorContext/Result data classes
    │   ├── cascade_adapter.py  # CascadeOrchestratorAdapter (unified agents)
    │   ├── live_orchestrator.py # LiveOrchestrator (VoiceLive SDK)
    │   └── config_resolver.py  # Scenario-aware config resolution
    └── handoffs/
        ├── strategies/     # ToolBasedHandoff, StateBasedHandoff
        └── registry.py     # HANDOFF_MAP
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

# Orchestrator data classes and adapters
from .orchestrators import (
    OrchestratorContext,
    OrchestratorResult,
    CascadeOrchestratorAdapter,
    CascadeConfig,
    get_cascade_orchestrator,
    create_cascade_orchestrator_func,
    LiveOrchestrator,
    TRANSFER_TOOL_NAMES,
    CALL_CENTER_TRIGGER_PHRASES,
    DEFAULT_START_AGENT,
    resolve_orchestrator_config,
    resolve_from_app_state,
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

# Messaging (WebSocket helpers for voice transports)
from .messaging import (
    send_tts_audio,
    send_response_to_acs,
    send_user_transcript,
    send_user_partial_transcript,
    send_session_envelope,
    broadcast_session_envelope,
    make_envelope,
    make_status_envelope,
    make_assistant_streaming_envelope,
    make_event_envelope,
    BrowserBargeInController,
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
    # Orchestrator Data Classes
    "OrchestratorContext",
    "OrchestratorResult",
    # Cascade Orchestrator (unified agents)
    "CascadeOrchestratorAdapter",
    "CascadeConfig",
    "get_cascade_orchestrator",
    "create_cascade_orchestrator_func",
    # VoiceLive Orchestrator
    "LiveOrchestrator",
    "TRANSFER_TOOL_NAMES",
    "CALL_CENTER_TRIGGER_PHRASES",
    # Config Resolution
    "DEFAULT_START_AGENT",
    "resolve_orchestrator_config",
    "resolve_from_app_state",
    # Handoff Strategies
    "HandoffContext",
    "HandoffResult",
    "HandoffStrategy",
    "ToolBasedHandoff",
    "StateBasedHandoff",
    "create_tool_based_handoff",
    "create_state_based_handoff",
    "HANDOFF_MAP",
    # Messaging (WebSocket helpers)
    "send_tts_audio",
    "send_response_to_acs",
    "send_user_transcript",
    "send_user_partial_transcript",
    "send_session_envelope",
    "broadcast_session_envelope",
    "make_envelope",
    "make_status_envelope",
    "make_assistant_streaming_envelope",
    "make_event_envelope",
    "BrowserBargeInController",
]
