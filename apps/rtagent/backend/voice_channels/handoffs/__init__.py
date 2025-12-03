"""
Handoff System for Multi-Agent Voice Applications
==================================================

This module provides a pluggable handoff abstraction for agent-to-agent
transitions in voice systems. Different transports use different mechanisms:

- **VoiceLive SDK**: Tool-based handoffs via LLM function calls
- **Speech Cascade**: State-based handoffs via MemoManager/Redis

Quick Start:
    from voice_channels.handoffs import (
        HandoffContext,
        HandoffResult,
        ToolBasedHandoff,
        StateBasedHandoff,
        HANDOFF_MAP,
    )

    # VoiceLive style
    strategy = ToolBasedHandoff(handoff_map=HANDOFF_MAP)

    # Check if a tool triggers handoff
    if strategy.is_handoff_tool("handoff_fraud_agent"):
        context = strategy.build_context_from_args(
            tool_name="handoff_fraud_agent",
            args={"reason": "suspicious activity"},
            source_agent="EricaConcierge",
        )
        result = await strategy.execute_handoff("handoff_fraud_agent", args, context)
        if result.success:
            # Orchestrator calls _switch_to_agent(result.target_agent, ...)
            pass

See Also:
    - docs/architecture/handoff-strategies.md for detailed documentation
    - voice_channels/orchestrators/live_adapter.py for integration example
"""

from __future__ import annotations

# Context and result dataclasses
from .context import HandoffContext, HandoffResult

# Strategy base class and implementations
from .strategies import (
    HandoffStrategy,
    ToolBasedHandoff,
    StateBasedHandoff,
    create_tool_based_handoff,
    create_state_based_handoff,
)

# Registry with handoff mappings
from .registry import HANDOFF_MAP

__all__ = [
    # Dataclasses
    "HandoffContext",
    "HandoffResult",
    # Strategy classes
    "HandoffStrategy",
    "ToolBasedHandoff",
    "StateBasedHandoff",
    # Factory functions
    "create_tool_based_handoff",
    "create_state_based_handoff",
    # Registry
    "HANDOFF_MAP",
]
