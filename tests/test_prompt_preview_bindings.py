"""Compare preview with the real Cascade/VoiceLive prompt consumers, offline."""

from __future__ import annotations

import copy
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apps.artagent.backend.api.v1.schemas.prompt_preview import PromptPreviewRequest
from apps.artagent.backend.api.v1.schemas.scenario_builder import DynamicScenarioConfig
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.registries.scenariostore.loader import (
    AgentOverride,
    ScenarioConfig,
    apply_scenario_overrides,
)
from apps.artagent.backend.src.orchestration.prompt_context import cascade_prompt_context
from apps.artagent.backend.src.orchestration.session_drafts import SessionAuthoringSnapshot
from apps.artagent.backend.src.services import prompt_preview as service
from apps.artagent.backend.voice.shared.base import OrchestratorContext
from apps.artagent.backend.voice.shared.session_state import sync_state_from_memo
from apps.artagent.backend.voice.speech_cascade.orchestrator import CascadeOrchestratorAdapter
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator
from src.stateful.state_managment import MemoManager


def _cascade() -> CascadeOrchestratorAdapter:
    adapter = object.__new__(CascadeOrchestratorAdapter)
    adapter._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    return adapter


def _live(agent, memo, *, variables=None) -> LiveOrchestrator:
    orchestrator = object.__new__(LiveOrchestrator)
    orchestrator._system_vars = (
        sync_state_from_memo(memo).system_vars if variables is None else dict(variables)
    )
    orchestrator._memo_manager = memo
    orchestrator._user_message_history = deque([], maxlen=5)
    orchestrator._last_assistant_message = None
    orchestrator.active = memo.get_value_from_corememory("active_agent") or agent.name
    orchestrator.agents = {orchestrator.active: agent}
    orchestrator.conn = SimpleNamespace(session=SimpleNamespace(update=AsyncMock()))
    orchestrator._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    orchestrator._build_conversation_recap = Mock(return_value="")
    return orchestrator


def test_shared_prompt_merge_preserves_runtime_defaults(monkeypatch):
    monkeypatch.setenv("INSTITUTION_NAME", "Environment institution")
    agent = UnifiedAgent(
        name="Original agent",
        prompt_template="{{ agent_name }}|{{ institution_name }}|{{ unset }}|{{ zero }}|{{ flag }}|{{ literal }}",
        template_vars={"unset": "author fallback", "zero": 1, "flag": True, "literal": None},
    )
    values = {"unset": None, "zero": 0, "flag": False, "institution_name": "None"}
    before = copy.deepcopy(values)
    assert (
        agent.render_prompt(values)
        == "Original agent|Environment institution|author fallback|0|False|None"
    )
    assert agent.get_prompt_context(values) == {
        "agent_name": "Original agent",
        "institution_name": "Environment institution",
        "unset": "author fallback",
        "zero": 0,
        "flag": False,
        "literal": None,
    }
    assert values == before


def test_cascade_direct_and_unified_entry_points_keep_their_existing_difference():
    memo = MemoManager(session_id="cascade-bindings")
    memo.context.update(
        {"caller_name": "Core name", "session_profile": {"full_name": "Profile name"}}
    )
    adapter = _cascade()
    direct = adapter._build_session_context(memo)
    assert direct["memo_manager"] is memo
    assert direct["caller_name"] == "Core name"
    assert "agent_name" not in direct
    unified = cascade_prompt_context(memo, agent_name="Current agent")
    assert unified["agent_name"] == "Current agent"
    assert unified["active_agent"] == "Current agent"
    assert unified["caller_name"] == "Core name"
    assert "memo_manager" not in unified


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cascade", "voicelive"])
async def test_real_orchestrator_precedence_matches_preview(mode):
    memo = MemoManager(session_id=f"bindings-{mode}")
    memo.context.update(
        {
            "active_agent": "Currently active",
            "caller_name": "Core caller",
            "client_id": "core-client",
            "institution_name": "Core institution",
            "session_profile": {
                "full_name": "Profile caller",
                "client_id": "profile-client",
                "institution_name": "Profile institution",
                "preferences": {"nickname": None, "enabled": False, "count": 0},
            },
        }
    )
    variables = {"agent_name": "Author name", "caller_name": "Author caller", "common": "author"}
    scenario_config = DynamicScenarioConfig(
        name="Edited scenario",
        global_template_vars={"common": "global", "caller_name": "Scenario caller"},
        agent_defaults={"template_vars": {"common": "scenario agent default"}},
    )
    scenario = ScenarioConfig(
        name=scenario_config.name,
        global_template_vars=scenario_config.global_template_vars,
        agent_defaults=AgentOverride(template_vars=scenario_config.agent_defaults.template_vars),
    )
    prompt = (
        "{{ agent_name }}|{{ caller_name }}|{{ client_id }}|{{ institution_name }}|{{ common }}|"
        "{{ session_profile.preferences.nickname }}|{{ session_profile.preferences.enabled }}|"
        "{{ session_profile.preferences.count }}"
    )
    raw = UnifiedAgent(name="Edited agent", prompt_template=prompt, template_vars=variables)
    effective = apply_scenario_overrides(scenario, {raw.name: raw})[raw.name]
    body = PromptPreviewRequest(
        prompt=prompt,
        agent_name=raw.name,
        template_vars=variables,
        tools=[],
        scenario=scenario_config,
        mode=mode,
    )
    live = None
    if mode == "cascade":
        adapter = _cascade()
        metadata = cascade_prompt_context(memo, agent_name="Currently active")
        context = OrchestratorContext(
            session_id=memo.session_id,
            websocket=None,
            user_text="",
            conversation_history=[],
            metadata=metadata,
        )
        expected = adapter._build_messages(context, effective)[0]["content"]
        assert expected.startswith("Currently active|Core caller|core-client|Core institution|")
    else:
        live = _live(effective, memo)
        live._refresh_session_context()
        await live._update_session_context()
        expected = live.conn.session.update.call_args.kwargs["session"].instructions
        assert expected.startswith("Author name|Profile caller|profile-client|Profile institution|")
    before = copy.deepcopy(memo.context)
    result = service._render_snapshot(
        body,
        SessionAuthoringSnapshot(memo, {}, {}, {}),
        saved_agent=raw,
        app_state=SimpleNamespace(),
        live=live,
    )
    assert result.errors == []
    assert result.rendered_prompt == expected
    assert memo.context == before
    assert raw.template_vars == variables


@pytest.mark.asyncio
async def test_voicelive_transient_values_are_read_only_and_mode_specific():
    memo = MemoManager(session_id="live-transient")
    memo.context.update({"active_agent": "Actual agent"})
    prompt = (
        "{{ caller_name }}|{{ zero }}|{{ flag }}|{{ previous_agent }}|"
        "{{ recent_user_messages | join(', ') }}|{{ conversation_summary }}|{{ last_assistant_response }}"
    )
    agent = UnifiedAgent(
        name="Edited", prompt_template=prompt, template_vars={"caller_name": "draft"}
    )
    live = _live(
        agent,
        memo,
        variables={
            "caller_name": "Real caller",
            "zero": 0,
            "flag": False,
            "previous_agent": "Other agent",
        },
    )
    live._user_message_history.extend(["Question", "Clarification"])
    live._last_assistant_message = "Last response"
    await live._update_session_context()
    expected = live.conn.session.update.call_args.kwargs["session"].instructions
    live.conn.session.update.reset_mock()
    before = copy.deepcopy(live._system_vars)
    body = PromptPreviewRequest(
        prompt=prompt,
        agent_name=agent.name,
        mode="voicelive",
        template_vars=agent.template_vars,
        tools=[],
    )
    result = service._render_snapshot(
        body,
        SessionAuthoringSnapshot(memo, {}, {}, {}),
        saved_agent=agent,
        app_state=SimpleNamespace(),
        live=live,
    )
    assert result.rendered_prompt == expected
    assert result.errors == []
    assert live._system_vars == before
    live.conn.session.update.assert_not_called()
    assert all(
        row.source == "session context"
        for row in result.variables
        if row.path in {"caller_name", "zero", "flag", "last_assistant_response"}
    )


def test_voicelive_refresh_keeps_profile_and_slots_precedence():
    memo = MemoManager(session_id="refresh")
    memo.context.update(
        {
            "session_profile": {
                "full_name": "Profile name",
                "client_id": 0,
                "institution_name": "",
            },
            "slots": {"case": "new"},
            "tool_outputs": {"lookup_case": {"status": "open"}},
        }
    )
    live = _live(
        UnifiedAgent(name="Agent"),
        memo,
        variables={
            "caller_name": "Old name",
            "institution_name": "Keep institution",
            "slots": {"case": "old"},
            "collected_information": {"case": "old"},
        },
    )
    live._refresh_session_context()
    assert live._system_vars["caller_name"] == "Profile name"
    assert live._system_vars["client_id"] == 0
    assert live._system_vars["institution_name"] == "Keep institution"
    assert (
        live._system_vars["slots"] == live._system_vars["collected_information"] == {"case": "new"}
    )
    assert live._system_vars["tool_outputs"] == {"lookup_case": {"status": "open"}}


def test_preview_never_calls_runtime_render_fallback_tools_or_models(monkeypatch):
    memo = MemoManager(session_id="no-effects")
    memo.context.update({"caller_name": "Avery"})
    for name in (
        "render_prompt",
        "execute_tool",
        "get_tools",
        "_load_custom_tools",
        "apply_voicelive_session",
    ):
        monkeypatch.setattr(
            UnifiedAgent, name, Mock(side_effect=AssertionError(f"{name} is forbidden"))
        )
    saved = UnifiedAgent(name="Saved", template_vars={"removed": "old"}, tool_names=["saved_tool"])
    constructor = Mock(wraps=UnifiedAgent)
    monkeypatch.setattr(service, "UnifiedAgent", constructor)
    result = service._render_snapshot(
        PromptPreviewRequest(
            prompt="{{ caller_name }} {{ removed | default('absent') }}",
            agent_name="New draft",
            template_vars={},
            tools=["new_draft_tool"],
            mode="cascade",
        ),
        SessionAuthoringSnapshot(memo, {}, {}, {}),
        saved_agent=saved,
        app_state=SimpleNamespace(),
        live=None,
    )
    assert result.rendered_prompt == "Avery absent"
    assert constructor.call_args.kwargs["tool_names"] == ["new_draft_tool"]
    assert saved.tool_names == ["saved_tool"]
    assert saved.template_vars == {"removed": "old"}
