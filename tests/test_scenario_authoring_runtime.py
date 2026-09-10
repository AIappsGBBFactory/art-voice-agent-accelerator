"""Exercise authored scenarios through real rendering, routing, and startup paths."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apps.artagent.backend.api.v1.endpoints import agent_builder
from apps.artagent.backend.api.v1.endpoints import scenario_drafts as api
from apps.artagent.backend.api.v1.schemas.scenario_builder import ScenarioDraft
from apps.artagent.backend.registries.agentstore.base import ModelConfig, UnifiedAgent
from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig
from apps.artagent.backend.registries.toolstore import registry as tool_registry
from apps.artagent.backend.registries.toolstore.registry import ToolDefinition
from apps.artagent.backend.src.orchestration import session_agents as sa
from apps.artagent.backend.src.orchestration import session_scenarios as ss
from apps.artagent.backend.src.orchestration import unified
from apps.artagent.backend.src.orchestration.session_drafts import read_authoring_snapshot
from apps.artagent.backend.voice.shared.config_resolver import resolve_orchestrator_config
from apps.artagent.backend.voice.speech_cascade.orchestrator import (
    CascadeConfig,
    CascadeOrchestratorAdapter,
)
from apps.artagent.backend.voice.voicelive import handler as live_handler
from apps.artagent.backend.voice.voicelive import orchestrator as live_module
from apps.artagent.backend.voice.voicelive import session as voicelive_session
from fastapi import HTTPException

from tests import test_scenario_draft_authoring as authoring_tests
from tests.test_scenario_draft_authoring import SID, draft_data

env = authoring_tests.env


def _copy_payload(readable, name, tools):
    """Mirror the editor's read-to-write shape, including scenario-owned routing."""
    payload = {
        key: copy.deepcopy(value)
        for key, value in readable.items()
        if key in agent_builder.DynamicAgentConfig.model_fields and key != "model"
    }
    payload["name"] = name
    payload["prompt"] = readable["prompt_full"]
    payload["handoff_trigger"] = ""
    payload["tools"] = [tool for tool in payload["tools"] if not tools[tool].is_handoff]
    detection = payload["session"].pop("turn_detection", {})
    for source, target in (
        ("type", "turn_detection_type"),
        ("threshold", "turn_detection_threshold"),
        ("prefix_padding_ms", "prefix_padding_ms"),
        ("silence_duration_ms", "silence_duration_ms"),
    ):
        if source in detection:
            payload["session"][target] = detection[source]
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template_id", ["compliance_desk", "banking_concierge", "investment_advisor", "fraud_agent"]
)
async def test_full_builtin_copy_allows_prose_edits_without_truncation(env, template_id):
    original = agent_builder.load_agent(
        agent_builder.AGENTS_DIR / template_id / "agent.yaml",
        agent_builder.load_defaults(agent_builder.AGENTS_DIR),
    )
    env.registry[original.name] = original
    for name in original.tool_names:
        env.tools.setdefault(
            name,
            ToolDefinition(
                name=name,
                schema={"name": name, "parameters": {"type": "object", "properties": {}}},
                executor=env.executor,
                is_handoff=name.startswith("handoff_"),
            ),
        )
    readable = (await agent_builder.get_agent_template(template_id))["config"]
    new_name = f"{original.name}Copy"
    payload = _copy_payload(readable, new_name, env.tools)
    payload["prompt"] = "Keep explanations concise.\n" + payload["prompt"]
    draft = ScenarioDraft.model_validate(
        {
            "summary": "Customize an independent copy.",
            "scenario": {"name": "Independent", "agents": [new_name], "start_agent": new_name},
            "agents": [payload],
        }
    )
    await api.apply_scenario_draft(draft, env.request, SID)
    copied = sa.get_session_agent(SID, new_name)
    assert copied.prompt_template == "Keep explanations concise.\n" + original.prompt_template
    assert len(copied.prompt_template) > len(original.prompt_template)
    assert copied.voice.to_dict() == original.voice.to_dict()
    assert copied.speech.to_dict() == original.speech.to_dict()
    assert copied.cascade_model.to_dict() == original.get_model_for_mode("cascade").to_dict()
    assert copied.template_vars == original.template_vars
    assert not any(env.tools[name].is_handoff for name in copied.tool_names)
    env.executor.assert_not_called()


@pytest.mark.asyncio
async def test_copy_verification_cannot_authorize_added_template_code(env):
    original = agent_builder.load_agent(
        agent_builder.AGENTS_DIR / "compliance_desk" / "agent.yaml",
        agent_builder.load_defaults(agent_builder.AGENTS_DIR),
    )
    env.registry[original.name] = original
    data = draft_data(specialist=True)
    data["agents"][0]["prompt"] = original.prompt_template + "\n{{ cycler.__init__.__globals__ }}"
    with pytest.raises(HTTPException) as error:
        await api.apply_scenario_draft(ScenarioDraft.model_validate(data), env.request, SID)
    assert error.value.status_code == 422
    assert env.redis.write_count == 0


@pytest.mark.asyncio
async def test_pure_prose_copy_does_not_remove_freeform_length_limit(env):
    shipped = agent_builder.load_agent(
        agent_builder.AGENTS_DIR / "compliance_desk" / "agent.yaml",
        agent_builder.load_defaults(agent_builder.AGENTS_DIR),
    )
    shipped.prompt_template = "A simple shipped prompt."
    env.registry[shipped.name] = shipped
    data = draft_data(specialist=True)
    data["agents"][0]["prompt"] = "x" * 16_001
    with pytest.raises(HTTPException) as error:
        await api.apply_scenario_draft(ScenarioDraft.model_validate(data), env.request, SID)
    assert "16000" in error.value.detail
    assert env.redis.write_count == 0


@pytest.mark.asyncio
async def test_reused_agent_honors_supplied_scenario_inputs_without_mutating_source(env):
    original = env.registry["Concierge"]
    original.template_vars = {"company_name": "Old Company", "other": "preserved"}
    original.prompt_template = "You provide support for {{ company_name }}."
    data = draft_data()
    data["scenario"]["global_template_vars"] = {"company_name": "New Company"}
    data["required_inputs"] = ["company_name"]
    await api.apply_scenario_draft(ScenarioDraft.model_validate(data), env.request, SID)
    configured = resolve_orchestrator_config(session_id=SID).agents["Concierge"]
    assert configured.render_prompt({}) == "You provide support for New Company."
    assert configured.template_vars["other"] == "preserved"
    assert original.template_vars["company_name"] == "Old Company"
    assert configured.render_prompt({"company_name": "Runtime Company"}) == (
        "You provide support for Runtime Company."
    )


@pytest.mark.asyncio
async def test_apply_replaces_cached_cascade_routing_even_with_an_old_memo(env, monkeypatch):
    original = ScenarioConfig(name="original", agents=["Concierge"], start_agent="Concierge")
    ss._session_scenarios[SID] = {"original": original}
    ss._active_scenario[SID] = "original"
    snapshot = await read_authoring_snapshot(SID, env.redis)
    snapshot.memo.set_corememory("active_scenario_name", "original")
    adapter = CascadeOrchestratorAdapter(
        config=CascadeConfig(session_id=SID, start_agent="Concierge"),
        agents=dict(env.registry),
    )
    adapter._current_memo_manager = snapshot.memo
    assert adapter._orchestrator_config.scenario_name == "original"
    original_handoff_service = adapter.handoff_service
    monkeypatch.setattr(unified, "_adapters", {SID: adapter})
    monkeypatch.setattr(ss, "_scenario_update_callback", unified.update_session_scenario)
    monkeypatch.setattr(live_module, "get_voicelive_orchestrator", lambda sid: None)
    monkeypatch.setattr(tool_registry, "_TOOL_DEFINITIONS", env.tools)
    monkeypatch.setattr(tool_registry, "initialize_tools", lambda: None)
    await api.apply_scenario_draft(
        ScenarioDraft.model_validate(draft_data(specialist=True)), env.request, SID
    )
    assert adapter._orchestrator_config.scenario_name == "Account Support"
    assert adapter.handoff_service is not original_handoff_service
    tools = adapter._get_tools_with_handoffs(adapter.agents["Concierge"])
    assert "handoff_to_agent" in [tool["function"]["name"] for tool in tools]


@pytest.mark.asyncio
async def test_voicelive_full_and_context_updates_include_authored_handoff_instructions(
    env, monkeypatch
):
    await api.apply_scenario_draft(
        ScenarioDraft.model_validate(draft_data(specialist=True)), env.request, SID
    )
    resolved = resolve_orchestrator_config(session_id=SID)
    snapshot = await read_authoring_snapshot(SID, env.redis)
    monkeypatch.setattr(tool_registry, "_TOOL_DEFINITIONS", env.tools)
    monkeypatch.setattr(tool_registry, "initialize_tools", lambda: None)
    connection = SimpleNamespace(session=SimpleNamespace(update=AsyncMock()))
    live = live_module.LiveOrchestrator(
        conn=connection,
        agents=resolved.agents,
        start_agent="Concierge",
        memo_manager=snapshot.memo,
    )
    try:
        await voicelive_session.apply_voicelive_session(
            resolved.agents["Concierge"], connection, session_id=SID
        )
        await live._update_session_context()
        assert connection.session.update.await_count == 2
        for call in connection.session.update.await_args_list:
            instructions = call.kwargs["session"].instructions
            assert "You are an account concierge." in instructions
            assert "OrderSpecialist" in instructions
            assert "investigating an order" in instructions
    finally:
        live.cleanup()


@pytest.mark.asyncio
async def test_voicelive_warmup_and_startup_share_the_scenario_start_model(env):
    env.registry["Concierge"].voicelive_model = ModelConfig(deployment_id="entry-live-model")
    env.registry["OutsideScenario"] = UnifiedAgent(name="OutsideScenario")
    env.state.unified_agents = env.registry
    await api.apply_scenario_draft(
        ScenarioDraft.model_validate(draft_data(specialist=True)), env.request, SID
    )
    settings = SimpleNamespace(azure_voicelive_model="global-model", start_agent="OutsideScenario")
    agents, start, model, byom, _ = await live_handler._resolve_voicelive_warmup_config(
        app_state=env.state,
        session_id=SID,
        scenario_name=None,
        settings=settings,
        user_email=None,
    )
    assert set(agents) == {"Concierge", "OrderSpecialist"}
    assert start == "Concierge"
    assert model == "entry-live-model"
    assert byom is None
    startup_agents, legacy, startup_name = live_handler._select_voicelive_agents(
        env.registry,
        resolve_orchestrator_config(session_id=SID),
        session_id=SID,
        configured_start_agent=settings.start_agent,
    )
    assert startup_name == start
    assert set(startup_agents) == set(agents)
    assert legacy is None


@pytest.mark.asyncio
async def test_case_insensitive_update_retains_canonical_runtime_key(env, monkeypatch):
    monkeypatch.setattr(agent_builder, "discover_agents", lambda: env.registry)
    original = UnifiedAgent(
        name="CaseAgent",
        prompt_template="Keep this agent's canonical name.",
        metadata={"created_at": 1},
    )
    sa._session_agents[SID] = {"CaseAgent": original}
    config = agent_builder.DynamicAgentConfig(
        name="caseagent", prompt="Use the revised instructions without changing identity."
    )
    result = await agent_builder.update_session_agent(SID, config, env.request, activate=False)
    assert result.agent_name == "CaseAgent"
    assert list(sa._session_agents[SID]) == ["CaseAgent"]
    assert sa._adapter_update_callback.call_args.args[1].name == "CaseAgent"
    assert sa._adapter_update_callback.call_args.args[2] is False
