"""Former session-manager behaviors exercised through the production contracts."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.registries.definitions import (
    agent_api_payload,
    agent_from_payload,
    definition_payload,
)
from apps.artagent.backend.src.orchestration import session_agents as registry


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(registry, "_session_agents", {})
    monkeypatch.setattr(registry, "_active_session_agents", {})
    monkeypatch.setattr(registry, "_redis_manager", None)
    callback = Mock(return_value=True)
    monkeypatch.setattr(registry, "_adapter_update_callback", callback)
    return "contract-session", callback


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_template", "Custom {{customer_name}}"),
        ("greeting", ""),
        ("return_greeting", ""),
        ("tool_names", []),
        ("template_vars", {"bank": "Example", "customer_name": "Maya"}),
        ("metadata", {"source": "api", "experiment_id": "exp-1", "variant": "treatment"}),
        ("source_dir", "/configured/agents/banking"),
        ("model", {"deployment_id": "gpt-4o-mini", "temperature": None, "max_tokens": 2048}),
        ("cascade_model", {"deployment_id": "gpt-4o", "temperature": 0.2}),
        ("voicelive_model", {"deployment_id": "gpt-realtime"}),
        ("voice", {"name": "en-US-AvaNeural", "rate": "+20%", "style": "excited"}),
        ("speech", {"candidate_languages": [], "enable_diarization": False}),
        ("session", {"turn_detection": {}, "custom_provider_setting": None}),
        ("handoff", {"trigger": "handoff_agent", "is_entry_point": True}),
    ],
)
def test_lossless_overrides_survive_storage_and_api(field, value):
    original = agent_from_payload({"name": "Agent", field: value})
    persisted = definition_payload(original)
    restored = agent_from_payload(persisted)
    assert definition_payload(restored) == persisted
    assert definition_payload(agent_from_payload(agent_api_payload(original))) == persisted
    if field == "source_dir":
        assert restored.source_dir == Path(value)


def test_multiple_agents_lookup_activation_and_live_notification(session):
    session_id, callback = session
    first = UnifiedAgent(name="Concierge", prompt_template="Base prompt")
    second = UnifiedAgent(name="Fraud", prompt_template="Investigate fraud")
    registry.set_session_agent(session_id, first, set_active=True, persist=False)
    registry.set_session_agent(session_id, second, persist=False)
    assert registry.get_session_agent(session_id) is first
    assert registry.get_session_agent(session_id, "fRaUd") is second
    assert registry.get_session_agent(session_id, "missing") is None
    registry.set_session_agent(session_id, second, set_active=True, persist=False)
    assert registry.get_session_agent(session_id) is second
    callback.assert_called_with(session_id, second, True)
    assert set(registry.get_session_agents(session_id)) == {"Concierge", "Fraud"}


def test_session_edits_do_not_mutate_base_or_other_sessions(session):
    session_id, _ = session
    base = UnifiedAgent(name="Agent", template_vars={"bank": "Example"})
    tuned = deepcopy(base)
    tuned.prompt_template = "Tuned"
    tuned.template_vars.update(customer="Maya")
    registry.set_session_agent(session_id, tuned, persist=False)
    registry.set_session_agent("other", deepcopy(base), persist=False)
    assert base.prompt_template != tuned.prompt_template
    assert base.template_vars == {"bank": "Example"}
    assert registry.get_session_agent("other").template_vars == base.template_vars
    tuned.template_vars = {"replacement": True}
    registry.set_session_agent(session_id, tuned, persist=False)
    assert registry.get_session_agent(session_id).template_vars == {"replacement": True}


def test_reset_one_or_all_preserves_unrelated_session(session):
    session_id, _ = session
    for name in ("Concierge", "Fraud"):
        registry.set_session_agent(session_id, UnifiedAgent(name=name), persist=False)
    registry.set_session_agent("other", UnifiedAgent(name="Other"), persist=False)
    assert registry.remove_session_agent(session_id, "fraud", persist=False)
    assert registry.get_session_agent(session_id).name == "Concierge"
    assert not registry.remove_session_agent(session_id, "missing", persist=False)
    assert registry.remove_session_agent(session_id, persist=False)
    assert registry.get_session_agents(session_id) == {}
    assert registry.get_session_agent("other").name == "Other"


@pytest.mark.parametrize("mode", ["cascade", "voicelive"])
def test_builder_roundtrip_preserves_explicit_null_mode_override(mode):
    from apps.artagent.backend.api.v1.endpoints.agent_builder import (
        DynamicAgentConfig,
        build_session_agent,
    )

    original = agent_from_payload(
        {
            "name": "Agent",
            "prompt_template": "Help the customer.",
            "model": {"deployment_id": "gpt-4o"},
            f"{mode}_model": None,
        }
    )
    parsed = DynamicAgentConfig.model_validate(agent_api_payload(original))
    restored = build_session_agent(parsed, "roundtrip", created_at=1)
    assert getattr(restored, f"{mode}_model") is None
    assert restored.get_model_for_mode(mode).deployment_id == "gpt-4o"


def test_builder_omitted_mode_overrides_still_receive_creation_presets():
    from apps.artagent.backend.api.v1.endpoints.agent_builder import (
        DynamicAgentConfig,
        build_session_agent,
    )

    config = DynamicAgentConfig(
        name="Agent", prompt="Help the customer.", model={"deployment_id": "gpt-4o"}
    )
    created = build_session_agent(config, "creation", created_at=1)
    assert created.cascade_model.deployment_id == "gpt-4o"
    assert created.voicelive_model.deployment_id == "gpt-realtime"
