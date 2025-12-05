"""
Unified Agent Configuration Module
===================================

Modular, orchestrator-agnostic agent configuration with auto-discovery.
Agents define a handoff.trigger (how to reach them) for routing.

Architecture:
- Agents define handoff.trigger (how to reach them)
- Orchestrators (VoiceLive, SpeechCascade) use build_handoff_map() for routing
- All tools are referenced by name from the shared tool registry

Usage:
    from apps.artagent.backend.agents import discover_agents, build_handoff_map, UnifiedAgent

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
"""

from apps.artagent.backend.agents.base import (
    UnifiedAgent,
    HandoffConfig,
    VoiceConfig,
    ModelConfig,
    build_handoff_map,
)

from apps.artagent.backend.agents.loader import (
    AgentConfig,
    discover_agents,
    get_agent,
    list_agent_names,
    load_defaults,
    render_prompt,
    AGENTS_DIR,
)

from apps.artagent.backend.agents.session_manager import (
    SessionAgentConfig,
    SessionAgentRegistry,
    SessionAgentManager,
    AgentProvider,
    HandoffProvider,
    create_session_agent_manager,
)

__all__ = [
    # Core types
    "UnifiedAgent",
    "HandoffConfig",
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
    # Loader functions
    "AgentConfig",
    "discover_agents",
    "get_agent",
    "list_agent_names",
    "load_defaults",
    "render_prompt",
    "AGENTS_DIR",
]
