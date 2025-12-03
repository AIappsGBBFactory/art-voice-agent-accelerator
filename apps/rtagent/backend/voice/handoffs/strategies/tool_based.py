"""
Tool-Based Handoff Strategy
============================

Handoff strategy for VoiceLive-style tool-triggered handoffs.

The LLM calls handoff tools (e.g., handoff_fraud_agent), which are
intercepted by the orchestrator to trigger agent switches.

How it works:
    1. Agent YAML defines handoff tools in its tools list
    2. HANDOFF_MAP maps tool names → agent names
    3. When LLM calls a handoff tool, orchestrator intercepts
    4. Strategy validates and returns HandoffResult
    5. Orchestrator calls _switch_to_agent() which calls agent.apply_session()
    6. agent.apply_session() calls conn.session.update()

Example:
    from voice_channels.handoffs import ToolBasedHandoff, HANDOFF_MAP

    strategy = ToolBasedHandoff(handoff_map=HANDOFF_MAP)

    # In event loop when function call is received
    if strategy.is_handoff_tool(tool_name):
        context = strategy.build_context_from_args(
            tool_name=tool_name,
            args=parsed_args,
            source_agent=current_agent,
            user_last_utterance=last_user_message,
        )
        result = await strategy.execute_handoff(tool_name, args, context)
        if result.success:
            await self._switch_to_agent(result.target_agent, context.to_system_vars())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import HandoffStrategy
from ..context import HandoffContext, HandoffResult


@dataclass
class ToolBasedHandoff(HandoffStrategy):
    """
    Handoff strategy for VoiceLive-style tool-triggered handoffs.

    The LLM calls handoff tools (e.g., handoff_fraud_agent), which are
    intercepted by the orchestrator to trigger agent switches.

    Attributes:
        handoff_map: Mapping from tool names to target agent names
            Example: {"handoff_fraud_agent": "FraudAgent"}

    Example:
        strategy = ToolBasedHandoff(
            handoff_map={
                "handoff_fraud_agent": "FraudAgent",
                "handoff_to_trading": "TradingDesk",
            }
        )

        # Check and execute handoff
        if strategy.is_handoff_tool("handoff_fraud_agent"):
            target = strategy.get_target_agent("handoff_fraud_agent")
            # target == "FraudAgent"
    """

    handoff_map: Dict[str, str] = field(default_factory=dict)
    _handoff_tools: Optional[set] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Build handoff tools set from map keys."""
        self._handoff_tools = set(self.handoff_map.keys())

    @property
    def strategy_name(self) -> str:
        """Return strategy identifier."""
        return "tool_based"

    def register_handoff(self, tool_name: str, target_agent: str) -> None:
        """
        Register a new handoff tool mapping dynamically.

        Args:
            tool_name: Name of the handoff tool (e.g., "handoff_new_agent")
            target_agent: Target agent name (e.g., "NewAgent")
        """
        self.handoff_map[tool_name] = target_agent
        self._handoff_tools = set(self.handoff_map.keys())

    def is_handoff_tool(self, tool_name: str) -> bool:
        """Check if tool name is a registered handoff tool."""
        return tool_name in (self._handoff_tools or set())

    def get_target_agent(self, tool_name: str) -> Optional[str]:
        """Get target agent for a handoff tool."""
        return self.handoff_map.get(tool_name)

    async def execute_handoff(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: HandoffContext,
    ) -> HandoffResult:
        """
        Execute tool-based handoff.

        Validates the handoff and prepares the result. The actual switch
        happens via session.update() in the orchestrator/agent.

        Args:
            tool_name: The handoff tool that was called
            args: Arguments passed to the tool
            context: Handoff context with source/target and metadata

        Returns:
            HandoffResult with success=True if valid, or error if not
        """
        target = self.get_target_agent(tool_name)
        if not target:
            return HandoffResult(
                success=False,
                error=f"No target agent mapped for tool '{tool_name}'",
            )

        # Extract optional message from tool args
        message = args.get("message") or args.get("handoff_message")
        should_interrupt = args.get("should_interrupt_playback", True)

        return HandoffResult(
            success=True,
            target_agent=target,
            message=message,
            should_interrupt=should_interrupt,
        )

    def build_context_from_args(
        self,
        tool_name: str,
        args: Dict[str, Any],
        source_agent: str,
        user_last_utterance: Optional[str] = None,
    ) -> HandoffContext:
        """
        Build HandoffContext from VoiceLive handoff tool arguments.

        Extracts common fields from the tool call args:
        - reason/handoff_reason/summary/issue_summary → reason
        - caller_name, account_type, etc. → context_data
        - session_overrides → session_overrides
        - greeting → greeting

        Args:
            tool_name: The handoff tool that was called
            args: Arguments passed to the tool
            source_agent: Current active agent name
            user_last_utterance: Last thing the user said

        Returns:
            HandoffContext populated with extracted data
        """
        target = self.get_target_agent(tool_name) or "Unknown"

        # Extract reason from common field names
        reason = (
            args.get("reason")
            or args.get("handoff_reason")
            or args.get("summary")
            or args.get("issue_summary")
            or ""
        )

        # Build context_data from remaining args (excluding known keys)
        excluded_keys = {
            "reason",
            "handoff_reason",
            "summary",
            "issue_summary",
            "message",
            "handoff_message",
            "should_interrupt_playback",
            "session_overrides",
            "greeting",
            "user_last_utterance",
        }
        context_data = {
            k: v
            for k, v in args.items()
            if k not in excluded_keys and v not in (None, "", [], {})
        }

        session_overrides = args.get("session_overrides") or {}
        greeting = args.get("greeting") or session_overrides.get("greeting")

        return HandoffContext(
            source_agent=source_agent,
            target_agent=target,
            reason=reason,
            user_last_utterance=user_last_utterance or args.get("user_last_utterance", ""),
            context_data=context_data,
            session_overrides=session_overrides,
            greeting=greeting,
        )


def create_tool_based_handoff(handoff_map: Dict[str, str]) -> ToolBasedHandoff:
    """
    Factory function to create a ToolBasedHandoff strategy.

    Args:
        handoff_map: Mapping from tool names to target agent names

    Returns:
        Configured ToolBasedHandoff instance

    Example:
        strategy = create_tool_based_handoff({
            "handoff_fraud_agent": "FraudAgent",
            "handoff_to_trading": "TradingDesk",
        })
    """
    return ToolBasedHandoff(handoff_map=handoff_map)


__all__ = ["ToolBasedHandoff", "create_tool_based_handoff"]
