"""Complete, session-scoped scenario edits and discovery for Quick Tune."""

import copy
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from apps.artagent.backend.api.v1.endpoints import scenario_builder as api
from apps.artagent.backend.api.v1.schemas.scenario_builder import DynamicScenarioConfig
from apps.artagent.backend.registries.scenariostore.loader import AgentOverride, ScenarioConfig
from apps.artagent.backend.src.orchestration import session_scenarios


@pytest.fixture
def scenario():
    return ScenarioConfig(
        name="Banking",
        description="Original purpose",
        icon="B",
        agents=["Concierge"],
        start_agent="Concierge",
        tools=["check_balance"],
        global_template_vars={"company_name": "Northwind", "enabled": False, "limit": 0},
        agent_defaults=AgentOverride(
            voice_rate="-5%", template_vars={"policy": {"days": 14}}
        ),
    )


@pytest.mark.asyncio
async def test_named_read_is_session_scoped_and_preserves_the_complete_config(monkeypatch, scenario):
    lookup = Mock(return_value=scenario)
    monkeypatch.setattr(api, "get_session_scenario", lookup)
    result = await api.get_session_scenario_config(
        "session-a", Request({"type": "http"}), scenario_name="Banking"
    )
    lookup.assert_called_once_with("session-a", "Banking")
    assert result.config["tools"] == ["check_balance"]
    assert result.config["agent_defaults"]["template_vars"] == {"policy": {"days": 14}}
    assert result.config["global_template_vars"]["enabled"] is False
    assert result.config["global_template_vars"]["limit"] == 0


@pytest.mark.asyncio
async def test_missing_named_scenario_does_not_fall_back_to_the_active_one(monkeypatch):
    monkeypatch.setattr(api, "get_session_scenario", Mock(return_value=None))
    with pytest.raises(HTTPException) as error:
        await api.get_session_scenario_config(
            "session-a", Request({"type": "http"}), scenario_name="NotHere"
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_listing_uses_session_edits_instead_of_reloading_builtin_defaults(monkeypatch, scenario):
    updated = copy.deepcopy(scenario)
    updated.description = "Session-specific purpose"
    updated.global_template_vars["company_name"] = "Contoso"
    monkeypatch.setattr(api, "list_scenarios", lambda: ["banking_pack"])
    monkeypatch.setattr(api, "load_scenario", lambda _: scenario)
    monkeypatch.setattr(api, "list_session_scenarios_by_session", lambda _: {"banking": updated})
    monkeypatch.setattr(session_scenarios, "get_active_scenario_name", lambda _: "banking")
    result = await api.list_scenarios_for_session("session-a", Request({"type": "http"}))
    assert result["total"] == 1
    assert result["custom_scenarios"] == []
    entry = result["builtin_scenarios"][0]
    assert entry["id"] == "banking_pack"
    assert entry["is_session_override"] is True
    assert entry["description"] == "Session-specific purpose"
    assert entry["global_template_vars"]["company_name"] == "Contoso"
    assert entry["tools"] == ["check_balance"]
    assert entry["agent_defaults"]["voice_rate"] == "-5%"
    assert scenario.description == "Original purpose"
    assert scenario.global_template_vars["company_name"] == "Northwind"


@pytest.mark.asyncio
async def test_unedited_builtin_and_custom_listings_include_defaults_and_tools(monkeypatch, scenario):
    custom = copy.deepcopy(scenario)
    custom.name = "CustomScenario"
    monkeypatch.setattr(api, "list_scenarios", lambda: ["banking"])
    monkeypatch.setattr(api, "load_scenario", lambda _: scenario)
    monkeypatch.setattr(api, "list_session_scenarios_by_session", lambda _: {"customscenario": custom})
    monkeypatch.setattr(session_scenarios, "get_active_scenario_name", lambda _: "customscenario")
    result = await api.list_scenarios_for_session("session-a", Request({"type": "http"}))
    assert result["builtin_scenarios"][0]["is_session_override"] is False
    for entry in result["scenarios"]:
        assert entry["tools"] == ["check_balance"]
        assert entry["agent_defaults"]["template_vars"] == {"policy": {"days": 14}}
    assert result["custom_scenarios"][0]["is_active"] is True


@pytest.mark.asyncio
async def test_update_returns_every_persisted_editable_field(monkeypatch, scenario):
    original = api._scenario_response_config(scenario)
    config = DynamicScenarioConfig(**{**original, "description": "Updated in Quick Tune"})
    persist = AsyncMock()
    lookup = Mock(return_value=scenario)
    monkeypatch.setattr(api, "get_session_scenario", lookup)
    monkeypatch.setattr(api, "discover_agents", lambda: {"Concierge": object()})
    monkeypatch.setattr(api, "list_session_agents_by_session", lambda _: {})
    monkeypatch.setattr(api, "set_session_scenario_async", persist)
    result = await api.update_session_scenario("session-a", config, Request({"type": "http"}))
    lookup.assert_called_once_with("session-a", "Banking")
    persisted = persist.await_args.args[1]
    assert result.config == api._scenario_response_config(persisted)
    assert result.config["description"] == "Updated in Quick Tune"
    for field in ("tools", "agent_defaults", "global_template_vars"):
        assert result.config[field] == original[field]
