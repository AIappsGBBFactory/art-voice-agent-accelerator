"""
Scenario Builder Configuration Contract Tests
=============================================

Exercises the API-level save/load/update paths that serialize scenario
configuration into session state. The key contract is lossless preservation of
``generic_handoff`` and related routing fields across builder payloads, session
storage, and editable responses.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import apps.artagent.backend.src.orchestration.session_scenarios as ss
import pytest
from apps.artagent.backend.api.v1.endpoints.scenario_builder import (
    DynamicScenarioConfig,
    create_dynamic_scenario,
    get_session_scenario_config,
    list_scenarios_for_session,
    reset_session_scenario,
    update_session_scenario,
)
from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
)
from apps.artagent.backend.src.orchestration.session_scenarios import (
    remove_session_scenario,
)


class CountingRedisManager:
    """Dict-backed Redis fake that counts awaited writes."""

    def __init__(self, *, fail_writes: bool = False) -> None:
        self.store: dict[str, dict] = {}
        self.write_count = 0
        self.fail_writes = fail_writes

    def get_session_data(self, key: str) -> dict:
        return dict(self.store.get(key, {}))

    async def store_session_data_async(self, key: str, data: dict) -> bool:
        self.write_count += 1
        if self.fail_writes:
            return False
        self.store[key] = dict(data)
        return True


def stub_request():
    """Minimal Request stand-in for direct endpoint calls."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def agent_registry() -> dict[str, UnifiedAgent]:
    """Small static registry used by validation in endpoint tests."""
    return {
        "Concierge": UnifiedAgent(
            name="Concierge",
            description="Front door",
            handoff=HandoffConfig(trigger="handoff_concierge"),
            model=ModelConfig(deployment_id="gpt-4o"),
        ),
        "FraudAgent": UnifiedAgent(
            name="FraudAgent",
            description="Fraud specialist",
            handoff=HandoffConfig(trigger="handoff_fraud_agent"),
            model=ModelConfig(deployment_id="gpt-4o"),
        ),
    }


def scenario_payload(
    *,
    name: str = "Fraud Flow",
    generic_handoff: dict | None = None,
) -> dict:
    """Payload shape submitted by the Scenario Builder."""
    return {
        "name": name,
        "description": "Fraud support flow",
        "icon": "F",
        "agents": ["Concierge", "FraudAgent"],
        "start_agent": "Concierge",
        "handoff_type": "announced",
        "handoffs": [
            {
                "from_agent": "Concierge",
                "to_agent": "FraudAgent",
                "tool": "handoff_fraud_agent",
                "type": "discrete",
                "share_context": False,
                "handoff_condition": "When fraud is suspected.",
                "context_vars": {"risk": "high"},
            }
        ],
        "generic_handoff": (
            generic_handoff
            if generic_handoff is not None
            else {
                "enabled": True,
                "allowed_targets": [" FraudAgent ", "fraudagent"],
                "require_client_id": True,
                "default_type": "discrete",
                "share_context": False,
            }
        ),
        "global_template_vars": {"institution_name": "Contoso"},
        "tools": [],
    }


@pytest.fixture
def session_id() -> str:
    return "scenario_builder_contract"


@pytest.fixture(autouse=True)
def _clean_session(session_id):
    ss.set_redis_manager(None)
    remove_session_scenario(session_id)
    yield
    ss.set_redis_manager(None)
    remove_session_scenario(session_id)
    ss.set_redis_manager(None)


class TestScenarioBuilderGenericHandoff:
    """API responses preserve the editable generic_handoff document."""

    @pytest.mark.asyncio
    async def test_create_get_and_list_preserve_generic_handoff(self, session_id) -> None:
        with patch(
            "apps.artagent.backend.api.v1.endpoints.scenario_builder.discover_agents",
            return_value=agent_registry(),
        ):
            config = DynamicScenarioConfig.model_validate(scenario_payload())

            created = await create_dynamic_scenario(config, session_id, stub_request())
            got = await get_session_scenario_config(session_id, stub_request())
            listed = await list_scenarios_for_session(session_id, stub_request())

        expected_generic = {
            "enabled": True,
            "allowed_targets": ["FraudAgent"],
            "require_client_id": True,
            "default_type": "discrete",
            "share_context": False,
        }
        assert created.config["generic_handoff"] == expected_generic
        assert got.config["generic_handoff"] == expected_generic
        assert got.config["handoffs"][0]["context_vars"] == {"risk": "high"}

        custom = next(s for s in listed["custom_scenarios"] if s["name"] == "Fraud Flow")
        assert custom["generic_handoff"] == expected_generic

    @pytest.mark.asyncio
    async def test_update_without_generic_handoff_preserves_existing_policy(
        self, session_id
    ) -> None:
        with patch(
            "apps.artagent.backend.api.v1.endpoints.scenario_builder.discover_agents",
            return_value=agent_registry(),
        ):
            await create_dynamic_scenario(
                DynamicScenarioConfig.model_validate(scenario_payload()),
                session_id,
                stub_request(),
            )

            update_payload = scenario_payload(name="Fraud Flow", generic_handoff=None)
            update_payload.pop("generic_handoff")
            updated = await update_session_scenario(
                session_id,
                DynamicScenarioConfig.model_validate(update_payload),
                stub_request(),
            )

        assert updated.config["generic_handoff"] == {
            "enabled": True,
            "allowed_targets": ["FraudAgent"],
            "require_client_id": True,
            "default_type": "discrete",
            "share_context": False,
        }

    @pytest.mark.asyncio
    async def test_create_without_generic_handoff_uses_builder_default(self, session_id) -> None:
        payload = scenario_payload(name="Default Generic", generic_handoff=None)
        payload.pop("generic_handoff")
        payload["handoff_type"] = "discrete"

        with patch(
            "apps.artagent.backend.api.v1.endpoints.scenario_builder.discover_agents",
            return_value=agent_registry(),
        ):
            created = await create_dynamic_scenario(
                DynamicScenarioConfig.model_validate(payload),
                session_id,
                stub_request(),
            )

        assert created.config["generic_handoff"] == {
            "enabled": True,
            "allowed_targets": [],
            "require_client_id": False,
            "default_type": "discrete",
            "share_context": True,
        }

    @pytest.mark.asyncio
    async def test_update_surfaces_redis_write_failure(self, session_id) -> None:
        from fastapi import HTTPException

        redis = CountingRedisManager(fail_writes=True)
        ss.set_redis_manager(redis)

        with patch(
            "apps.artagent.backend.api.v1.endpoints.scenario_builder.discover_agents",
            return_value=agent_registry(),
        ):
            config = DynamicScenarioConfig.model_validate(scenario_payload())
            with pytest.raises(HTTPException) as exc:
                await update_session_scenario(session_id, config, stub_request())

        assert exc.value.status_code == 503
        assert redis.write_count == 1

    @pytest.mark.asyncio
    async def test_reset_surfaces_redis_clear_failure(self, session_id) -> None:
        from fastapi import HTTPException

        with patch(
            "apps.artagent.backend.api.v1.endpoints.scenario_builder.discover_agents",
            return_value=agent_registry(),
        ):
            await create_dynamic_scenario(
                DynamicScenarioConfig.model_validate(scenario_payload()),
                session_id,
                stub_request(),
            )

        redis = CountingRedisManager(fail_writes=True)
        ss.set_redis_manager(redis)

        with pytest.raises(HTTPException) as exc:
            await reset_session_scenario(session_id, stub_request())

        assert exc.value.status_code == 503
