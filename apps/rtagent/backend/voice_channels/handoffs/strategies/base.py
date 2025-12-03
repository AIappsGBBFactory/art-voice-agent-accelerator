"""
HandoffStrategy Abstract Base Class
====================================

Defines the interface that all handoff strategies must implement.

Strategies handle the mechanics of how agents are switched:
- Tool-based: LLM calls a handoff tool, orchestrator interprets
- State-based: Session state change triggers handoff
- Event-based: External events (future extension)

The strategy is responsible for:
1. Detecting handoff requests (is_handoff_tool)
2. Building context from tool arguments
3. Executing the handoff logic (validation, preparation)

The actual session switch (session.update) is handled by the orchestrator
based on the HandoffResult returned by execute_handoff().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from ..context import HandoffContext, HandoffResult


class HandoffStrategy(ABC):
    """
    Abstract base for agent handoff strategies.

    Implementations handle the mechanics of how agents are switched:
    - Tool-based: LLM calls a handoff tool, orchestrator interprets
    - State-based: Session state change triggers handoff
    - Event-based: External events (future)

    Example Implementation:
        class CustomHandoff(HandoffStrategy):
            @property
            def strategy_name(self) -> str:
                return "custom"

            def is_handoff_tool(self, tool_name: str) -> bool:
                return tool_name.startswith("transfer_to_")

            def get_target_agent(self, tool_name: str) -> Optional[str]:
                return tool_name.replace("transfer_to_", "")

            async def execute_handoff(self, ...) -> HandoffResult:
                # Custom validation logic
                return HandoffResult(success=True, target_agent=...)

            def build_context_from_args(self, ...) -> HandoffContext:
                return HandoffContext(...)
    """

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """
        Human-readable name for logging/tracing.

        Returns:
            Strategy identifier like "tool_based" or "state_based"
        """
        ...

    @abstractmethod
    def is_handoff_tool(self, tool_name: str) -> bool:
        """
        Check if a tool name represents a handoff operation.

        Args:
            tool_name: Name of the tool called by the LLM

        Returns:
            True if this tool should trigger an agent handoff
        """
        ...

    @abstractmethod
    def get_target_agent(self, tool_name: str) -> Optional[str]:
        """
        Get the target agent for a handoff tool.

        Args:
            tool_name: Name of the handoff tool

        Returns:
            Agent name to switch to, or None if not found
        """
        ...

    @abstractmethod
    async def execute_handoff(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: HandoffContext,
    ) -> HandoffResult:
        """
        Execute a handoff operation.

        This method validates the handoff and prepares the result.
        The actual session switch happens in the orchestrator.

        Args:
            tool_name: The handoff tool that was called
            args: Arguments passed to the tool
            context: Handoff context with source/target and metadata

        Returns:
            HandoffResult indicating success/failure and next steps
        """
        ...

    @abstractmethod
    def build_context_from_args(
        self,
        tool_name: str,
        args: Dict[str, Any],
        source_agent: str,
        user_last_utterance: Optional[str] = None,
    ) -> HandoffContext:
        """
        Build HandoffContext from tool call arguments.

        Different strategies may extract context differently:
        - ToolBasedHandoff: From tool arguments (reason, caller_name, etc.)
        - StateBasedHandoff: From MemoManager state

        Args:
            tool_name: The handoff tool that was called
            args: Arguments passed to the tool
            source_agent: Current active agent name
            user_last_utterance: Last thing the user said (for context)

        Returns:
            HandoffContext ready for execute_handoff()
        """
        ...


__all__ = ["HandoffStrategy"]
