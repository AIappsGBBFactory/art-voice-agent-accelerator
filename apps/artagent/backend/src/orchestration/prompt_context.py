"""Pure prompt bindings shared by runtime orchestration and read-only preview."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.stateful.state_managment import MemoManager

CASCADE_CONTEXT_KEYS = (
    "session_profile",
    "caller_name",
    "client_id",
    "customer_intelligence",
    "institution_name",
    "active_agent",
    "previous_agent",
    "visited_agents",
    "handoff_context",
)


def cascade_prompt_context(memo: MemoManager, *, agent_name: str | None = None) -> dict[str, Any]:
    """Read Cascade's bindings, without copying the internal MemoManager into Jinja.

    The unified entry point supplies ``agent_name``; the adapter's direct entry
    point historically does not. Callers retain their own internal metadata.
    """
    context = {key: memo.get_value_from_corememory(key) for key in CASCADE_CONTEXT_KEYS}
    if agent_name is not None:
        context["agent_name"] = agent_name
        context["active_agent"] = context["active_agent"] or agent_name
    return context


def refresh_voicelive_prompt_context(system_vars: dict[str, Any], memo: MemoManager) -> None:
    """Refresh VoiceLive's existing bindings in place, preserving their precedence."""
    profile = memo.get_value_from_corememory("session_profile")
    if profile and isinstance(profile, dict):
        system_vars["session_profile"] = profile
        system_vars["client_id"] = profile.get("client_id")
        system_vars["caller_name"] = profile.get("full_name")
        system_vars["customer_intelligence"] = profile.get("customer_intelligence", {})
        if profile.get("institution_name"):
            system_vars["institution_name"] = profile["institution_name"]

    slots = memo.get_context("slots", {})
    if slots:
        system_vars["slots"] = slots
        system_vars["collected_information"] = slots
    tool_outputs = memo.get_context("tool_outputs", {})
    if tool_outputs:
        system_vars["tool_outputs"] = tool_outputs


def voicelive_prompt_context(
    system_vars: dict[str, Any],
    *,
    active_agent: str | None,
    user_messages: Sequence[str],
    last_assistant_response: str | None,
) -> dict[str, Any]:
    """Return exactly the template bindings used by VoiceLive's instruction update."""
    context = dict(system_vars)
    context["active_agent"] = active_agent
    if user_messages:
        context["recent_user_messages"] = list(user_messages)
        if len(user_messages) > 1:
            context["conversation_summary"] = " → ".join(user_messages)
    if last_assistant_response:
        context["last_assistant_response"] = last_assistant_response
    return context
