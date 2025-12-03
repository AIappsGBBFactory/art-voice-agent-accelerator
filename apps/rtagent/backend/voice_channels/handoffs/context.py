"""
Handoff Context and Result Dataclasses
======================================

These dataclasses carry information through the handoff lifecycle:

1. **HandoffContext**: Built when a handoff is detected, contains all
   information needed to switch agents (source, target, reason, user context).

2. **HandoffResult**: Returned by execute_handoff(), signals success/failure
   and provides data for the orchestrator to complete the switch.

The separation allows strategies to make decisions without coupling to
the actual transport mechanism (VoiceLive session.update, ACS media, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class HandoffContext:
    """
    Context passed during agent handoffs.

    Captures all relevant information for smooth agent transitions:
    - Source and target agent identifiers
    - User's last utterance for context continuity
    - Session variables and overrides
    - Custom handoff metadata

    Attributes:
        source_agent: Name of the agent initiating the handoff
        target_agent: Name of the agent receiving the handoff
        reason: Why the handoff is occurring
        user_last_utterance: User's most recent speech (for context)
        context_data: Additional structured context (caller info, etc.)
        session_overrides: Configuration to apply to the new agent
        greeting: Optional greeting for the new agent to speak

    Example:
        context = HandoffContext(
            source_agent="EricaConcierge",
            target_agent="FraudAgent",
            reason="User reported suspicious card activity",
            user_last_utterance="I think my card was stolen",
            context_data={"caller_name": "John", "account_type": "Premium"},
        )

        # Convert to system_vars for agent.apply_session()
        vars = context.to_system_vars()
    """

    source_agent: str
    target_agent: str
    reason: str = ""
    user_last_utterance: str = ""
    context_data: Dict[str, Any] = field(default_factory=dict)
    session_overrides: Dict[str, Any] = field(default_factory=dict)
    greeting: Optional[str] = None

    def to_system_vars(self) -> Dict[str, Any]:
        """
        Convert to system_vars dict for agent session application.

        The resulting dict is passed to agent.apply_session() which uses
        these values to render the system prompt (via Handlebars) and
        configure the session.

        Returns:
            Dict with keys like 'previous_agent', 'active_agent',
            'handoff_reason', 'handoff_context', etc.
        """
        vars_dict: Dict[str, Any] = {
            "previous_agent": self.source_agent,
            "active_agent": self.target_agent,
            "handoff_reason": self.reason,
        }
        if self.user_last_utterance:
            vars_dict["user_last_utterance"] = self.user_last_utterance
            vars_dict["details"] = self.user_last_utterance
        if self.context_data:
            vars_dict["handoff_context"] = self.context_data
        if self.session_overrides:
            vars_dict["session_overrides"] = self.session_overrides
        if self.greeting:
            vars_dict["greeting"] = self.greeting
        return vars_dict


@dataclass
class HandoffResult:
    """
    Result from a handoff operation.

    This is a **signal** returned by execute_handoff() that tells the
    orchestrator what to do next. The actual agent switch (session.update)
    happens in the orchestrator based on this result.

    Attributes:
        success: Whether the handoff completed successfully
        target_agent: The agent to switch to (if success=True)
        message: Optional message to speak after handoff
        error: Error message if handoff failed
        should_interrupt: Whether to cancel current TTS playback

    Flow:
        HandoffResult(success=True, target="FraudAgent")
               ↓
        Orchestrator._switch_to_agent("FraudAgent", system_vars)
               ↓
        Agent.apply_session(conn, system_vars)
               ↓
        conn.session.update(session=RequestSession(...))

    Example:
        result = await strategy.execute_handoff(tool_name, args, context)
        if result.success and result.target_agent:
            await self._switch_to_agent(result.target_agent, context.to_system_vars())
        else:
            logger.warning("Handoff failed: %s", result.error)
    """

    success: bool
    target_agent: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    should_interrupt: bool = True


__all__ = ["HandoffContext", "HandoffResult"]
