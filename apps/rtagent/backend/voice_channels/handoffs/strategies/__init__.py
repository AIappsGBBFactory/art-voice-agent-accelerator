"""
Handoff Strategies
==================

Pluggable strategies for agent handoff in multi-agent voice systems.

Available Strategies:
    - ToolBasedHandoff: VoiceLive pattern - LLM tool calls trigger handoffs
    - StateBasedHandoff: ART Agent pattern - state changes trigger handoffs

Usage:
    from voice_channels.handoffs.strategies import (
        HandoffStrategy,
        ToolBasedHandoff,
        StateBasedHandoff,
        create_tool_based_handoff,
        create_state_based_handoff,
    )
"""

from __future__ import annotations

from .base import HandoffStrategy
from .tool_based import ToolBasedHandoff, create_tool_based_handoff
from .state_based import StateBasedHandoff, create_state_based_handoff

__all__ = [
    "HandoffStrategy",
    "ToolBasedHandoff",
    "StateBasedHandoff",
    "create_tool_based_handoff",
    "create_state_based_handoff",
]
