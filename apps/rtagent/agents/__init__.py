"""
Unified Agent Configuration Module
===================================

Modular, orchestrator-agnostic agent configuration with auto-discovery.
Agents are handoff-strategy-aware but don't care about orchestration type.

Architecture:
- Agents define handoff.trigger (how to reach them) and handoff.strategy (auto/tool_based/state_based)
- Orchestrators (VoiceLive, SpeechCascade) use the appropriate handoff strategy implementation
- All tools are referenced by name from the shared tool registry

Usage:
    from apps.rtagent.agents import discover_agents, build_handoff_map, UnifiedAgent

    # Load all agents
    agents = discover_agents()
    handoffs = build_handoff_map(agents)

    # Get single agent
    fraud_agent = agents["FraudAgent"]
    
    # Get tools for agent (from shared registry)
    tools = fraud_agent.get_tools()
    
    # Execute a tool
    result = await fraud_agent.execute_tool("analyze_recent_transactions", {...})
    
    # Check handoff configuration
    print(fraud_agent.handoff.trigger)    # "handoff_fraud_agent"
    print(fraud_agent.handoff.strategy)   # HandoffStrategy.AUTO
"""

from apps.rtagent.agents.base import (
    UnifiedAgent,
    HandoffConfig,
    HandoffStrategy,
    VoiceConfig,
    ModelConfig,
    build_handoff_map,
)

from apps.rtagent.agents.loader import (
    AgentConfig,
    discover_agents,
    get_agent,
    list_agent_names,
    load_defaults,
    render_prompt,
)

from apps.rtagent.agents.session_manager import (
    SessionAgentConfig,
    SessionAgentRegistry,
    SessionAgentManager,
    AgentProvider,
    HandoffProvider,
    create_session_agent_manager,
)

__all__ = [
    # New unified types
    "UnifiedAgent",
    "HandoffConfig",
    "HandoffStrategy",
    "VoiceConfig",
    "ModelConfig",
    "build_handoff_map",
    # Session management
    "SessionAgentConfig",
    "SessionAgentRegistry",
    "SessionAgentManager",
    "AgentProvider",
    "HandoffProvider",
    "create_session_agent_manager",
    # Legacy/loader functions
    "AgentConfig",
    "discover_agents",
    "get_agent",
    "list_agent_names",
    "load_defaults",
    "render_prompt",
]
