"""
Voice Channel Orchestrators
============================

Orchestration layer for voice channel handlers. Provides a common protocol
for different orchestration strategies.

Orchestrators:
    - GPTFlowOrchestrator: STT→LLM→TTS pipeline adapter for SpeechCascadeHandler
    - LiveOrchestratorAdapter: Multi-agent orchestration adapter for VoiceLiveSDKHandler

Handoff Strategies:
    - ToolBasedHandoff: VoiceLive-style tool-triggered agent switches
    - StateBasedHandoff: ART Agent-style state-driven handoffs via MemoManager

Usage:
    from apps.rtagent.backend.voice_channels.orchestrators import (
        VoiceOrchestrator,
        GPTFlowOrchestrator,
        LiveOrchestratorAdapter,
        ToolBasedHandoff,
    )
    
    # Create with tool-based handoffs (VoiceLive pattern)
    adapter = LiveOrchestratorAdapter.create(
        conn=connection,
        agents=agent_registry,
        handoff_map={"handoff_fraud": "FraudAgent"},
    )
    
    # Or wrap existing orchestrator
    adapter = wrap_live_orchestrator(existing_orchestrator)
"""

from .base import (
    VoiceOrchestrator,
    OrchestratorCapabilities,
    OrchestratorContext,
    OrchestratorResult,
    LegacyOrchestratorFunc,
)
from .gpt_flow_adapter import GPTFlowOrchestrator, get_gpt_flow_orchestrator
from .live_adapter import (
    LiveOrchestratorAdapter,
    LiveOrchestratorConfig,
    AgentProvider,
    ToolProvider,
    wrap_live_orchestrator,
    get_live_orchestrator,
)
# Handoff strategies - now in dedicated handoffs module
from ..handoffs import (
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
    # Protocol
    "VoiceOrchestrator",
    "OrchestratorCapabilities",
    "OrchestratorContext",
    "OrchestratorResult",
    "LegacyOrchestratorFunc",
    # GPT Flow (SpeechCascade)
    "GPTFlowOrchestrator",
    "get_gpt_flow_orchestrator",
    # Live Orchestrator (VoiceLive)
    "LiveOrchestratorAdapter",
    "LiveOrchestratorConfig",
    "AgentProvider",
    "ToolProvider",
    "wrap_live_orchestrator",
    "get_live_orchestrator",
    # Handoff Strategies
    "HandoffContext",
    "HandoffResult",
    "HandoffStrategy",
    "ToolBasedHandoff",
    "StateBasedHandoff",
    "create_tool_based_handoff",
    "create_state_based_handoff",
    # Registry
    "HANDOFF_MAP",
]
