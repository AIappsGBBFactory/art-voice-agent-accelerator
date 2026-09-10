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


def test_shared_schema_serialization_keeps_omitted_modes_and_nested_vad_omitted():
    from apps.artagent.backend.api.v1.endpoints.agent_builder import build_session_agent
    from apps.artagent.backend.api.v1.schemas.agent_builder import DynamicAgentConfig

    original = DynamicAgentConfig(
        name="Agent",
        prompt="Help the customer.",
        session={"turn_detection_threshold": 0.6},
    )
    payload = original.model_dump()
    assert "cascade_model" not in payload
    assert "voicelive_model" not in payload
    assert "turn_detection" not in payload["session"]
    restored = build_session_agent(
        DynamicAgentConfig.model_validate(payload), "draft-roundtrip", created_at=1
    )
    assert restored.cascade_model.deployment_id == "gpt-4o"
    assert restored.voicelive_model.deployment_id == "gpt-realtime"
    assert restored.session["turn_detection"]["threshold"] == 0.6


@pytest.mark.parametrize("turn_detection", [None, {}, {"type": "server_vad", "custom": False}])
def test_builder_preserves_explicit_nested_vad_with_extra_session_settings(turn_detection):
    from apps.artagent.backend.api.v1.endpoints.agent_builder import build_session_agent
    from apps.artagent.backend.api.v1.schemas.agent_builder import DynamicAgentConfig

    parsed = DynamicAgentConfig(
        name="Agent",
        prompt="Help the customer.",
        cascade_model=None,
        voicelive_model=None,
        session={"turn_detection": turn_detection, "custom_provider_setting": None},
    )
    restored = build_session_agent(parsed, "nested-roundtrip", created_at=1)
    assert restored.session["turn_detection"] == turn_detection
    assert restored.session["custom_provider_setting"] is None
    assert restored.cascade_model is None
    assert restored.voicelive_model is None


@pytest.mark.parametrize(
    "field,method",
    [
        ("prompt_template", "render_prompt"),
        ("greeting", "render_greeting"),
        ("return_greeting", "render_return_greeting"),
    ],
)
def test_runtime_templates_remain_sandboxed_and_surface_errors(field, method):
    from jinja2 import TemplateSyntaxError
    from jinja2.sandbox import SecurityError

    agent = UnifiedAgent(name="Agent")
    setattr(agent, field, "{{ ''.__class__.__mro__ }}")
    with pytest.raises(SecurityError):
        getattr(agent, method)({})
    setattr(agent, field, "{% if incomplete")
    with pytest.raises(TemplateSyntaxError):
        getattr(agent, method)({})


def test_runtime_templates_cannot_mutate_the_callers_context():
    from jinja2.sandbox import SecurityError

    agent = UnifiedAgent(name="Agent", prompt_template="{{ records.clear() }}")
    context = {"records": ["original"]}
    with pytest.raises(SecurityError):
        agent.render_prompt(context)
    assert context == {"records": ["original"]}


@pytest.mark.parametrize("trigger", ["", "handoff_copy"])
def test_explicit_handoff_alias_can_clear_or_replace_an_inherited_copy_trigger(trigger):
    from apps.artagent.backend.api.v1.endpoints.agent_builder import build_session_agent
    from apps.artagent.backend.api.v1.schemas.agent_builder import DynamicAgentConfig

    config = DynamicAgentConfig(
        name="Copy",
        prompt="Help the customer independently.",
        handoff={"trigger": "handoff_original", "is_entry_point": True},
        handoff_trigger=trigger,
    )
    rebuilt = build_session_agent(
        DynamicAgentConfig.model_validate(config.model_dump()), "copy", created_at=1
    )
    assert rebuilt.handoff.trigger == trigger
    assert rebuilt.handoff.is_entry_point is True


def test_omitted_handoff_alias_does_not_clear_the_canonical_trigger_on_roundtrip():
    from apps.artagent.backend.api.v1.endpoints.agent_builder import build_session_agent
    from apps.artagent.backend.api.v1.schemas.agent_builder import DynamicAgentConfig

    config = DynamicAgentConfig(
        name="Agent",
        prompt="Help the customer.",
        handoff={"trigger": "handoff_agent"},
    )
    payload = config.model_dump()
    assert "handoff_trigger" not in payload
    rebuilt = build_session_agent(
        DynamicAgentConfig.model_validate(payload), "roundtrip", created_at=1
    )
    assert rebuilt.handoff.trigger == "handoff_agent"


@pytest.mark.parametrize(
    "model",
    [
        "gpt-realtime",
        "gpt-realtime-1.5",
        "gpt-realtime-2025-08-28",
        "gpt-realtime-mini-2025-10-06",
        "gpt-4o-realtime-preview",
        "gpt-4o-mini-realtime-preview-2024-12-17",
    ],
)
def test_known_native_model_ids_and_dated_variants_conflict_with_chat_byom(model):
    from apps.artagent.backend.registries.agentstore.base import byom_profile_model_conflict

    reason = byom_profile_model_conflict("byom-azure-openai-chat-completion", model)
    assert reason is not None
    assert "chat completions" in reason


@pytest.mark.parametrize(
    "deployment",
    [
        "realtime-named-text-deployment",
        "gpt-4o-realtime-customer-alias",
        "customer-realtime-2025-08-28",
    ],
)
def test_unknown_deployment_names_cannot_disprove_an_explicit_chat_profile(deployment):
    from apps.artagent.backend.registries.agentstore.base import byom_profile_model_conflict

    assert byom_profile_model_conflict("byom-azure-openai-chat-completion", deployment) is None
