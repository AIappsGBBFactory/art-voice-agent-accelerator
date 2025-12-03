"""
Voice Channel Orchestrators
============================

Orchestration layer for voice channel handlers.

Orchestrators:
    - CascadeOrchestratorAdapter: Multi-agent orchestration with unified agents (SpeechCascade)
    - LiveOrchestrator: VoiceLive SDK multi-agent orchestration

Handoff Strategies:
    - ToolBasedHandoff: Tool-triggered agent switches
    - StateBasedHandoff: State-driven handoffs via MemoManager

Usage:
    from apps.rtagent.backend.voice.orchestrators import (
        CascadeOrchestratorAdapter,
        LiveOrchestrator,
        get_cascade_orchestrator,
        ToolBasedHandoff,
    )
    
    # SpeechCascade pattern
    adapter = get_cascade_orchestrator(
        start_agent="Concierge",
        call_connection_id="call_123",
    )
    
    # VoiceLive pattern
    orchestrator = LiveOrchestrator(
        conn=voicelive_connection,
        agents=adapted_agents,
        handoff_map=handoff_map,
        start_agent="Concierge",
    )
"""

from .base import (
    OrchestratorContext,
    OrchestratorResult,
)
from .cascade_adapter import (
    CascadeOrchestratorAdapter,
    CascadeConfig,
    CascadeHandoffContext,
    StateKeys,
    get_cascade_orchestrator,
    create_cascade_orchestrator_func,
)
from .live_orchestrator import (
    LiveOrchestrator,
    TRANSFER_TOOL_NAMES,
    CALL_CENTER_TRIGGER_PHRASES,
)
from .config_resolver import (
    DEFAULT_START_AGENT,
    OrchestratorConfigResult,
    resolve_orchestrator_config,
    resolve_from_app_state,
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
    # Context/Result (shared data classes)
    "OrchestratorContext",
    "OrchestratorResult",
    # Cascade (SpeechCascade - unified agents)
    "CascadeOrchestratorAdapter",
    "CascadeConfig",
    "CascadeHandoffContext",
    "StateKeys",
    "get_cascade_orchestrator",
    "create_cascade_orchestrator_func",
    # VoiceLive Orchestrator
    "LiveOrchestrator",
    "TRANSFER_TOOL_NAMES",
    "CALL_CENTER_TRIGGER_PHRASES",
    # Config Resolution
    "DEFAULT_START_AGENT",
    "OrchestratorConfigResult",
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
    # Registry
    "HANDOFF_MAP",
]
