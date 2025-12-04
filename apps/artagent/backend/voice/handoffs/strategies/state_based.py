"""
State-Based Handoff Strategy
=============================

Handoff strategy for ART Agent-style state-driven handoffs.

Agent switches are managed through MemoManager/Redis state changes,
with context passed through the shared memory system. This enables:
- In-session memory persistence across handoffs
- Redis-based state sharing for distributed agents
- Code-driven handoff decisions (not just LLM tool calls)

How it works:
    1. Code detects handoff need (e.g., based on user input analysis)
    2. Updates MemoManager state: cm.update_corememory("pending_handoff", {...})
    3. Handler observes state change
    4. Handler calls _switch_to_agent() with context from state

This differs from ToolBasedHandoff where the LLM explicitly calls a
handoff tool - here, handoffs are triggered by application logic.

Example:
    # In route_turn when handoff is needed
    if should_escalate_to_fraud(transcript):
        cm.update_corememory("pending_handoff", {
            "target_agent": "FraudAgent",
            "reason": "Suspicious activity detected",
            "context": {"user_query": transcript}
        })

    # In handler's event loop
    strategy = StateBasedHandoff()
    pending = cm.get_value_from_corememory("pending_handoff")
    if pending:
        context = strategy.build_context_from_args(
            tool_name="switch_agent",
            args=pending,
            source_agent=current_agent,
        )
        result = await strategy.execute_handoff("switch_agent", pending, context)
        if result.success:
            await self._switch_to_agent(result.target_agent, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import HandoffStrategy
from ..context import HandoffContext, HandoffResult


@dataclass
class StateBasedHandoff(HandoffStrategy):
    """
    Handoff strategy for ART Agent-style state-driven handoffs.

    Agent switches are managed through MemoManager/Redis state changes,
    with context passed through the shared memory system.

    Attributes:
        agent_key: Key in MemoManager for active agent name
        handoff_key: Key in MemoManager for pending handoff request

    Unlike ToolBasedHandoff:
        - Target agent comes from tool args, not a static map
        - Handoffs are triggered by code, not LLM tool calls
        - Context is stored in MemoManager, not tool arguments

    Example:
        strategy = StateBasedHandoff(
            agent_key="active_agent",
            handoff_key="pending_handoff",
        )

        # These generic tool names are recognized
        strategy.is_handoff_tool("switch_agent")        # True
        strategy.is_handoff_tool("handoff_to_agent")    # True
        strategy.is_handoff_tool("escalate_to_human")   # True
    """

    agent_key: str = "active_agent"
    handoff_key: str = "pending_handoff"
    _handoff_tools: set = field(
        default_factory=lambda: {
            "switch_agent",
            "handoff_to_agent",
            "escalate_to_human",
            "transfer_to_agent",
        },
        repr=False,
    )

    @property
    def strategy_name(self) -> str:
        """Return strategy identifier."""
        return "state_based"

    def is_handoff_tool(self, tool_name: str) -> bool:
        """
        Check if tool name is a recognized state-based handoff.

        These are generic handoff tool names that state-based systems
        might use. The actual target comes from the tool args.
        """
        return tool_name in self._handoff_tools

    def get_target_agent(self, tool_name: str) -> Optional[str]:
        """
        State-based handoffs get target from tool args, not static map.

        Returns None because the target must be extracted from args
        in build_context_from_args() or execute_handoff().
        """
        return None

    async def execute_handoff(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: HandoffContext,
    ) -> HandoffResult:
        """
        Execute state-based handoff.

        Validates that a target agent is specified in the args and
        returns a HandoffResult. The actual state update (MemoManager)
        should be done by the calling code before or after this.

        Args:
            tool_name: The handoff tool name (e.g., "switch_agent")
            args: Arguments containing target_agent and context
            context: Handoff context with source/target and metadata

        Returns:
            HandoffResult with success=True if target specified
        """
        target = args.get("target_agent") or args.get("agent_name")
        if not target:
            return HandoffResult(
                success=False,
                error="No target_agent specified in handoff arguments",
            )

        return HandoffResult(
            success=True,
            target_agent=target,
            message=args.get("message"),
            should_interrupt=args.get("should_interrupt_playback", True),
        )

    def build_context_from_args(
        self,
        tool_name: str,
        args: Dict[str, Any],
        source_agent: str,
        user_last_utterance: Optional[str] = None,
    ) -> HandoffContext:
        """
        Build HandoffContext from state-based handoff arguments.

        For state-based handoffs, args typically come from MemoManager
        state rather than LLM tool calls.

        Args:
            tool_name: The handoff tool name
            args: Arguments from MemoManager state
            source_agent: Current active agent name
            user_last_utterance: Last thing the user said

        Returns:
            HandoffContext populated with state data
        """
        target = args.get("target_agent") or args.get("agent_name") or "Unknown"

        return HandoffContext(
            source_agent=source_agent,
            target_agent=target,
            reason=args.get("reason", ""),
            user_last_utterance=user_last_utterance or "",
            context_data=args.get("context", {}),
            session_overrides=args.get("session_overrides", {}),
            greeting=args.get("greeting"),
        )


def create_state_based_handoff(
    agent_key: str = "active_agent",
    handoff_key: str = "pending_handoff",
) -> StateBasedHandoff:
    """
    Factory function to create a StateBasedHandoff strategy.

    Args:
        agent_key: MemoManager key for active agent name
        handoff_key: MemoManager key for pending handoff request

    Returns:
        Configured StateBasedHandoff instance

    Example:
        strategy = create_state_based_handoff()
        # or with custom keys:
        strategy = create_state_based_handoff(
            agent_key="current_agent",
            handoff_key="handoff_request",
        )
    """
    return StateBasedHandoff(agent_key=agent_key, handoff_key=handoff_key)


__all__ = ["StateBasedHandoff", "create_state_based_handoff"]
