"""Engine-neutral tool inputs and committed session effects.

Provider notification, batching, MFA/DTMF and transfer operations stay with the
engine. Apply an outcome synchronously, before awaiting any spoken continuation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from src.stateful.state_managment import MemoManager

if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig


def tool_arguments(raw: str | dict[str, Any] | None, memo: MemoManager | None) -> dict[str, Any]:
    """Decode external arguments and inject verified, session-owned identity."""
    args = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be a JSON object")
    args = dict(args)
    if memo is not None:
        for key, argument in (("session_profile", "_session_profile"), ("client_id", "_client_id")):
            value = memo.get_value_from_corememory(key)
            if value:
                args[argument] = value
    return args


def normalize_tool_result(result: Any) -> dict[str, Any]:
    """Keep dictionary tool schemas intact; wrap legacy scalar outputs."""
    return result if isinstance(result, dict) else {"result": result}


def tool_succeeded(result: dict[str, Any]) -> bool:
    """Interpret explicit business outcome flags consistently across engines."""
    return not result.get("error") and all(
        result[key] for key in ("success", "ok", "authenticated") if key in result
    )


def apply_tool_result(
    memo: MemoManager | None, tool_name: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Commit tool effects to the current memo and return prompt-context updates.

    Slots are collected even on a failed operation (for example an MFA retry).
    Authentication and successful profile loads retain their existing independent
    permissions; this is not a new authorization policy.
    """
    if memo is None:
        return {}
    updates: dict[str, Any] = {}
    memo.persist_tool_output(tool_name, result)
    updates["tool_outputs"] = memo.get_context("tool_outputs", {})
    if isinstance(result.get("slots"), dict):
        memo.update_slots(result["slots"])
        updates["slots"] = memo.get_context("slots", {})
        updates["collected_information"] = updates["slots"]
    if result.get("authenticated") and result.get("client_id"):
        updates["client_id"] = result["client_id"]
        if result.get("caller_name"):
            updates["caller_name"] = result["caller_name"]
    profile = result.get("profile")
    if result.get("success") and isinstance(profile, dict) and profile:
        updates["session_profile"] = profile
        for source, target in (
            ("client_id", "client_id"),
            ("full_name", "caller_name"),
            ("customer_intelligence", "customer_intelligence"),
            ("institution_name", "institution_name"),
        ):
            if profile.get(source):
                updates[target] = profile[source]
    for key, value in updates.items():
        memo.set_corememory(key, value)
    return updates


def agent_tool_schemas(
    agent: UnifiedAgent,
    *,
    scenario: ScenarioConfig | None,
    agents: Mapping[str, UnifiedAgent],
    is_handoff: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Expose declared tools through one scenario-aware handoff projection."""
    declared = agent.get_tools()
    tools = [
        deepcopy(tool)
        for tool in declared
        if (
            tool.get("function", {}).get("name") == "handoff_to_agent"
            or not is_handoff(tool.get("function", {}).get("name", ""))
        )
    ]
    generic_present = any(
        tool.get("function", {}).get("name") == "handoff_to_agent" for tool in tools
    )
    if scenario is not None:
        inject = scenario.generic_handoff.enabled or bool(
            scenario.get_outgoing_handoffs(agent.name)
        )
    else:
        inject = any(is_handoff(tool.get("function", {}).get("name", "")) for tool in declared)
    if inject and not generic_present:
        from apps.artagent.backend.registries.toolstore import get_tools_for_agent, initialize_tools

        initialize_tools()
        tools.extend(deepcopy(get_tools_for_agent(["handoff_to_agent"])))
    targets = sorted(name for name in agents if name != agent.name)
    if targets:
        for tool in tools:
            function = tool.get("function", {})
            if function.get("name") != "handoff_to_agent":
                continue
            function["description"] = (
                f"{function.get('description', '')}\n\nAVAILABLE AGENTS: {', '.join(targets)}"
                "\nYou MUST use one of these exact agent names as the target_agent parameter."
            )
            target = function.get("parameters", {}).get("properties", {}).get("target_agent")
            if target is not None:
                target["enum"] = targets
    return tools
