"""Quick Tune must read and edit the selected agent, never another session override."""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apps.artagent.backend.api.v1.endpoints import agent_builder as api
from apps.artagent.backend.api.v1.schemas.scenario_builder import ScenarioDraft
from apps.artagent.backend.registries.agentstore.base import (
    ModelConfig,
    SpeechConfig,
    UnifiedAgent,
    VoiceConfig,
    VoiceLiveBYOMConfig,
)
from apps.artagent.backend.src.orchestration import session_agents as sa
from apps.artagent.backend.src.orchestration import session_scenarios as ss
from apps.artagent.backend.voice.handler import VoiceHandler
from apps.artagent.backend.voice.voicelive import orchestrator as voicelive
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from tests.test_scenario_draft_authoring import FakeRedis

SID = "multi-agent-quick-tune"


def agent(name: str, created_at: int) -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description=f"{name} original description",
        greeting=f"Hello from {name}",
        return_greeting=f"Welcome back to {name}",
        prompt_template=f"You are {name}. Preserve this original prompt.",
        tool_names=[],
        model=ModelConfig(deployment_id=f"{name}-model"),
        cascade_model=ModelConfig(deployment_id=f"{name}-cascade", temperature=0.3),
        voicelive_model=ModelConfig(deployment_id=f"{name}-live", temperature=0.6),
        byom=VoiceLiveBYOMConfig(mode="byom-azure-openai-chat-completion"),
        voice=VoiceConfig(name="en-US-JennyNeural", rate="-2%", pitch="+3%", style="serious"),
        speech=SpeechConfig(vad_silence_timeout_ms=1234, candidate_languages=["es-ES"]),
        session={
            "turn_detection": {
                "type": "azure_semantic_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
            },
            "tool_choice": "required",
            "input_audio_transcription_settings": {"model": "whisper-1", "language": "es"},
        },
        template_vars={"brand": "Example"},
        metadata={"created_at": created_at},
    )


@pytest.fixture
def env(monkeypatch):
    first, second = agent("First", 100), agent("Second", 200)
    monkeypatch.setattr(sa, "_session_agents", {SID: {"First": first, "Second": second}})
    monkeypatch.setattr(sa, "_session_load_times", {})
    monkeypatch.setattr(sa, "_redis_manager", None)
    monkeypatch.setattr(sa, "_adapter_update_callback", Mock())
    orch = SimpleNamespace(
        active="First",
        agents={"First": first, "Second": second},
        conn=object(),
        apply_live_session_settings=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(voicelive, "get_voicelive_orchestrator", lambda sid: orch)
    state = SimpleNamespace(redis=None, redis_manager=None, start_agent=None, unified_agents={})
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    return SimpleNamespace(first=first, second=second, orch=orch, state=state, request=request)


@pytest.fixture
def atomic_env(env, monkeypatch):
    redis = FakeRedis()
    redis.store[f"session:{SID}"] = {
        "corememory": json.dumps(
            {
                "active_agent": "First",
                "active_scenario_name": "original",
                "unrelated_setting": "preserve me",
                sa.AGENTS_KEY_ALL: {
                    name: sa._serialize_agent(value)
                    for name, value in sa._session_agents[SID].items()
                },
            }
        ),
        "chat_history": "{}",
    }
    env.state.redis = redis
    env.redis = redis
    monkeypatch.setattr(ss, "_redis_manager", None)
    monkeypatch.setattr(ss, "_session_scenarios", {})
    monkeypatch.setattr(ss, "_active_scenario", {SID: "original"})
    monkeypatch.setattr(api, "discover_agents", lambda: {"Builtin": agent("Builtin", 1)})
    return env


@pytest.mark.asyncio
async def test_named_get_returns_only_exact_override_and_unqualified_get_stays_compatible(env):
    named = await api.get_session_agent_config(SID, env.request, agent_name="second")
    assert named.agent_name == "Second"
    assert named.created_at == 200
    assert named.config["byom"] == {"mode": "byom-azure-openai-chat-completion"}
    assert named.config["prompt_full"] == env.second.prompt_template
    assert (await api.get_session_agent_config(SID, env.request)).agent_name == "First"
    with pytest.raises(HTTPException) as error:
        await api.get_session_agent_config(SID, env.request, agent_name="Missing")
    assert error.value.status_code == 404
    assert sa.get_session_agent(SID, "First") is env.first


@pytest.mark.asyncio
async def test_static_template_returns_full_config_with_legacy_template_alias():
    response = await api.get_agent_template("banking_concierge")
    expected = api.load_agent(
        api.AGENTS_DIR / "banking_concierge" / "agent.yaml",
        api.load_defaults(api.AGENTS_DIR),
    )
    config = response["config"]
    assert config["name"] == expected.name
    assert config["prompt_full"] == expected.prompt_template
    assert response["template"]["prompt"] == config["prompt_full"]
    assert response["template"]["id"] == "banking_concierge"
    assert config["session"] == expected.session
    assert config["speech"] == expected.speech.to_dict()
    assert config["voice"] == expected.voice.to_dict()
    assert config["cascade_model"] == expected.get_model_for_mode("cascade").to_dict()
    assert config["voicelive_model"] == expected.get_model_for_mode("voicelive").to_dict()
    assert config["handoff_trigger"] == expected.handoff.trigger


def test_read_models_are_accepted_in_a_copy_draft_without_losing_settings():
    original = agent("Original", 100)
    original.cascade_model = ModelConfig(
        deployment_id="reasoning-model",
        name="reasoning-model",
        temperature=None,
        top_p=None,
        max_tokens=None,
        api_version="2026-01-01-preview",
        model_family="o3",
        max_completion_tokens=2048,
        metadata={"purpose": "example"},
    )
    original.session["input_audio_transcription_settings"]["phrase_list"] = ["Contoso"]
    readable = api._agent_editor_config(original)
    payload = {
        key: copy.deepcopy(value)
        for key, value in readable.items()
        if key in api.DynamicAgentConfig.model_fields and key != "model"
    }
    payload["name"] = "IndependentCopy"
    payload["prompt"] = readable["prompt_full"]
    detection = payload["session"].pop("turn_detection")
    payload["session"].update(
        turn_detection_type=detection["type"],
        turn_detection_threshold=detection["threshold"],
        prefix_padding_ms=detection["prefix_padding_ms"],
    )
    draft = ScenarioDraft.model_validate(
        {
            "summary": "An independent copy.",
            "scenario": {
                "name": "CopyScenario",
                "agents": ["IndependentCopy"],
                "start_agent": "IndependentCopy",
            },
            "agents": [payload],
        }
    )
    rebuilt = api.build_session_agent(draft.agents[0], SID, created_at=100)
    assert rebuilt.cascade_model.to_dict() == original.cascade_model.to_dict()
    assert rebuilt.voicelive_model.to_dict() == original.voicelive_model.to_dict()
    assert (
        rebuilt.session["input_audio_transcription_settings"]
        == original.session["input_audio_transcription_settings"]
    )
    assert rebuilt.voice.to_dict() == original.voice.to_dict()
    assert rebuilt.speech.to_dict() == original.speech.to_dict()
    assert rebuilt.byom == original.byom


@pytest.mark.asyncio
@pytest.mark.parametrize("activate", [False, True])
async def test_full_put_uses_named_created_at_and_explicit_activation_flag(env, activate):
    config = api.DynamicAgentConfig(
        name="Second",
        description="Updated selected agent",
        prompt="You are the selected agent with an updated prompt.",
        voice={"name": "en-US-GuyNeural"},
    )
    response = await api.update_session_agent(SID, config, env.request, activate=activate)
    assert response.created_at == 200
    assert response.agent_name == "Second"
    assert sa.get_session_agent(SID, "First") is env.first
    assert env.first.metadata["created_at"] == 100
    sa._adapter_update_callback.assert_called_once()
    assert sa._adapter_update_callback.call_args.args[2] is activate


@pytest.mark.asyncio
async def test_put_case_insensitive_update_does_not_create_duplicate_override(env):
    config = api.DynamicAgentConfig(name="second", prompt="An updated case-insensitive prompt.")
    response = await api.update_session_agent(SID, config, env.request)
    assert response.created_at == 200
    assert len(sa.get_session_agents(SID)) == 2
    assert sa.get_session_agent(SID, "SECOND").prompt_template == config.prompt

    first = api.DynamicAgentConfig(name="first", prompt="A revised default agent prompt.")
    await api.update_session_agent(SID, first, env.request)
    assert sa.get_session_agent(SID).name == "First"
    assert sa.get_session_agent(SID).metadata["created_at"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["First", " fIRst (session) ", "Builtin", "builtin"])
async def test_create_only_rejects_session_and_builtin_collisions_before_writes(atomic_env, name):
    before = copy.deepcopy(sa._session_agents)
    with pytest.raises(HTTPException) as error:
        await api.update_session_agent(
            SID,
            api.DynamicAgentConfig(name=name, prompt="A proposed duplicate agent prompt."),
            atomic_env.request,
            activate=False,
            create_only=True,
        )
    assert error.value.status_code == 409
    assert "unused name" in error.value.detail
    assert sa._session_agents == before
    assert atomic_env.redis.write_count == 0
    sa._adapter_update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_create_only_checks_redis_only_agent_names(atomic_env):
    raw = atomic_env.redis.store[f"session:{SID}"]
    core = json.loads(raw["corememory"])
    core[sa.AGENTS_KEY_ALL]["RemoteOnly"] = sa._serialize_agent(agent("RemoteOnly", 10))
    raw["corememory"] = json.dumps(core)
    with pytest.raises(HTTPException) as error:
        await api.update_session_agent(
            SID,
            api.DynamicAgentConfig(name="remoteonly", prompt="Do not overwrite remote state."),
            atomic_env.request,
            create_only=True,
        )
    assert error.value.status_code == 409
    assert atomic_env.redis.write_count == 0
    assert set(sa._session_agents[SID]) == {"First", "Second"}


@pytest.mark.asyncio
async def test_create_only_persists_before_notification_without_activation(atomic_env):
    atomic_env.redis.before_write = lambda: sa._adapter_update_callback.assert_not_called()
    response = await api.update_session_agent(
        SID,
        api.DynamicAgentConfig(
            name="  Duplicate  ",
            prompt="The new duplicate agent prompt is independent.",
            voice={"name": "en-US-GuyNeural", "rate": "-8%", "pitch": "+2%"},
        ),
        atomic_env.request,
        activate=False,
        create_only=True,
    )
    assert response.status == "created" and response.agent_name == "Duplicate"
    assert atomic_env.redis.write_count == 1
    core = json.loads(atomic_env.redis.store[f"session:{SID}"]["corememory"])
    assert core["active_agent"] == "First"
    assert core["active_scenario_name"] == "original"
    assert core["unrelated_setting"] == "preserve me"
    assert set(core[sa.AGENTS_KEY_ALL]) == {"First", "Second", "Duplicate"}
    assert core[sa.AGENTS_KEY_ALL]["Duplicate"]["voice"]["pitch"] == "+2%"
    sa._adapter_update_callback.assert_called_once()
    assert sa._adapter_update_callback.call_args.args[2] is False
    assert atomic_env.orch.active == "First"
    atomic_env.orch.apply_live_session_settings.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_create_only_requests_cannot_overwrite_each_other(atomic_env, monkeypatch):
    read_snapshot = api.read_authoring_snapshot
    snapshots_ready = asyncio.Event()
    reads = 0

    async def simultaneous_snapshot(*args, **kwargs):
        nonlocal reads
        snapshot = await read_snapshot(*args, **kwargs)
        reads += 1
        if reads == 2:
            snapshots_ready.set()
        await asyncio.wait_for(snapshots_ready.wait(), timeout=2)
        return snapshot

    monkeypatch.setattr(api, "read_authoring_snapshot", simultaneous_snapshot)
    results = await asyncio.gather(
        *(
            api.update_session_agent(
                SID,
                api.DynamicAgentConfig(
                    name="Concurrent Copy", prompt=f"Independent copy number {number}."
                ),
                atomic_env.request,
                activate=False,
                create_only=True,
            )
            for number in (1, 2)
        ),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, api.SessionAgentResponse)]
    errors = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == len(errors) == 1
    assert errors[0].status_code == 409
    assert atomic_env.redis.write_count == 1
    stored = sa.get_session_agent(SID, "Concurrent Copy")
    assert stored.prompt_template == successes[0].config["prompt_preview"]
    core = json.loads(atomic_env.redis.store[f"session:{SID}"]["corememory"])
    assert core[sa.AGENTS_KEY_ALL]["Concurrent Copy"]["prompt_template"] == stored.prompt_template
    sa._adapter_update_callback.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnected", "no_redis"])
async def test_create_only_persistence_failures_do_not_publish_agent(atomic_env, failure):
    before = copy.deepcopy(sa._session_agents)
    if failure == "no_redis":
        atomic_env.state.redis = None
    else:
        atomic_env.redis.failure = RedisError("unavailable")
    with pytest.raises(HTTPException) as error:
        await api.update_session_agent(
            SID,
            api.DynamicAgentConfig(name="Unsaved Copy", prompt="Must not be published on failure."),
            atomic_env.request,
            create_only=True,
        )
    assert error.value.status_code == 503
    assert "Redis" in error.value.detail
    assert sa._session_agents == before
    assert atomic_env.redis.write_count == 0
    assert ss._active_scenario[SID] == "original"
    sa._adapter_update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_live_edit_of_nonactive_selected_agent_never_pushes_or_switches(env):
    before_first = sa._serialize_agent(env.first)
    before_second = sa._serialize_agent(env.second)
    payload = api.LiveSettingsRequest(
        voice={"name": "en-US-GuyNeural", "rate": "+4%"},
        turn_detection={"threshold": 0.7},
    )
    response = await api.apply_live_session_settings(SID, payload, env.request, agent_name="Second")
    assert response["applied"] is True and response["live"] is False
    assert env.orch.active == "First"
    env.orch.apply_live_session_settings.assert_not_called()
    assert sa._serialize_agent(sa.get_session_agent(SID, "First")) == before_first
    updated = sa._serialize_agent(sa.get_session_agent(SID, "Second"))
    before_second["voice"].update(name="en-US-GuyNeural", rate="+4%")
    before_second["session"]["turn_detection"]["threshold"] = 0.7
    assert updated == before_second
    assert sa._adapter_update_callback.call_args.args[2] is False


@pytest.mark.asyncio
async def test_unqualified_live_edit_uses_current_agent_not_first_created(env):
    env.orch.active = "Second"
    payload = api.LiveSettingsRequest(voice={"rate": "-6%"})
    response = await api.apply_live_session_settings(SID, payload, env.request)
    assert response["live"] is True
    assert sa.get_session_agent(SID, "First").voice.rate == "-2%"
    assert sa.get_session_agent(SID, "Second").voice.rate == "-6%"
    assert env.orch.active == "Second"
    env.orch.apply_live_session_settings.assert_awaited_once()
    assert sa._adapter_update_callback.call_args.args[1].name == "Second"


@pytest.mark.asyncio
async def test_live_push_contains_only_supplied_voice_fields(env):
    await api.apply_live_session_settings(
        SID,
        api.LiveSettingsRequest(voice={"rate": "-9%"}),
        env.request,
        agent_name="First",
    )
    env.orch.apply_live_session_settings.assert_awaited_once_with(
        turn_detection=None, voice={"rate": "-9%"}
    )
    stored = sa.get_session_agent(SID, "First")
    assert stored.voice.name == "en-US-JennyNeural"
    assert stored.voice.style == "serious" and stored.voice.pitch == "+3%"


@pytest.mark.asyncio
async def test_live_detection_patch_preserves_unsupplied_threshold_and_timing(env):
    env.first.session["turn_detection"]["silence_duration_ms"] = 1350
    await api.apply_live_session_settings(
        SID,
        api.LiveSettingsRequest(turn_detection={"type": "server_vad", "prefix_padding_ms": 0}),
        env.request,
        agent_name="First",
    )
    env.orch.apply_live_session_settings.assert_awaited_once_with(
        turn_detection={"type": "server_vad", "prefix_padding_ms": 0}, voice=None
    )
    assert sa.get_session_agent(SID, "First").session["turn_detection"] == {
        "type": "server_vad",
        "prefix_padding_ms": 0,
        "threshold": 0.5,
        "silence_duration_ms": 1350,
    }


@pytest.mark.asyncio
async def test_materialized_but_unset_pydantic_fields_do_not_clobber_live_config(env):
    before_session = copy.deepcopy(env.first.session)
    voice_patch = api.LiveVoicePatch.model_construct(
        _fields_set={"name"}, name="en-US-GuyNeural", rate="+0%"
    )
    payload = api.LiveSettingsRequest.model_construct(
        _fields_set={"voice"},
        voice=voice_patch,
        turn_detection=api.LiveTurnDetectionPatch(type="server_vad", threshold=0.1),
    )
    await api.apply_live_session_settings(SID, payload, env.request, agent_name="First")
    env.orch.apply_live_session_settings.assert_awaited_once_with(
        turn_detection=None, voice={"name": "en-US-GuyNeural"}
    )
    stored = sa.get_session_agent(SID, "First")
    assert stored.voice.rate == "-2%"
    assert stored.session == before_session


@pytest.mark.asyncio
async def test_empty_live_patch_is_noop_without_persistence_or_push(env, monkeypatch):
    persist = AsyncMock()
    monkeypatch.setattr(api, "persist_session_agents_to_redis", persist)
    result = await api.apply_live_session_settings(
        SID,
        api.LiveSettingsRequest.model_validate({"voice": {}, "turn_detection": {}}),
        env.request,
        agent_name="First",
    )
    assert result["status"] == "noop"
    assert result["applied"] is False and result["live"] is False
    persist.assert_not_called()
    env.orch.apply_live_session_settings.assert_not_called()
    sa._adapter_update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_live_target_change_during_persistence_cannot_patch_new_active_agent(
    env, monkeypatch
):
    async def persist(*args, **kwargs):
        env.orch.active = "Second"

    monkeypatch.setattr(api, "persist_session_agents_to_redis", persist)
    response = await api.apply_live_session_settings(
        SID, api.LiveSettingsRequest(voice={"rate": "-6%"}), env.request, agent_name="First"
    )
    assert response["live"] is False
    env.orch.apply_live_session_settings.assert_not_called()
    assert sa.get_session_agent(SID, "Second").voice.rate == "-2%"


@pytest.mark.asyncio
async def test_live_named_base_agent_clones_its_config_not_another_session_override(env):
    base = agent("BaseAgent", 10)
    env.state.unified_agents = {"BaseAgent": base}
    env.orch.agents["BaseAgent"] = base
    env.orch.active = "BaseAgent"
    payload = api.LiveSettingsRequest(voice={"rate": "-8%"}, turn_detection={"threshold": 0.8})
    response = await api.apply_live_session_settings(
        SID, payload, env.request, agent_name="baseagent"
    )
    assert response["live"] is True
    saved = sa.get_session_agent(SID, "BaseAgent")
    assert saved.metadata["cloned_from"] == "BaseAgent"
    assert saved.voice.rate == "-8%"
    assert saved.voice.pitch == "+3%" and saved.voice.style == "serious"
    assert saved.session["input_audio_transcription_settings"]["language"] == "es"
    assert saved.byom.mode == base.byom.mode
    assert base.voice.rate == "-2%"
    assert env.first.voice.rate == env.second.voice.rate == "-2%"


@pytest.mark.asyncio
async def test_live_unknown_named_agent_is_404_not_fallback_to_existing_override(env):
    before = copy.deepcopy(sa._session_agents)
    with pytest.raises(HTTPException) as error:
        await api.apply_live_session_settings(
            SID, api.LiveSettingsRequest(voice={"rate": "-5%"}), env.request, agent_name="Missing"
        )
    assert error.value.status_code == 404
    assert sa._session_agents == before
    env.orch.apply_live_session_settings.assert_not_called()
    sa._adapter_update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_live_settings_persistence_failure_is_actionable_and_never_pushed(env, monkeypatch):
    persist = AsyncMock(side_effect=RedisError("unavailable"))
    monkeypatch.setattr(api, "persist_session_agents_to_redis", persist)
    with pytest.raises(HTTPException) as error:
        await api.apply_live_session_settings(
            SID,
            api.LiveSettingsRequest(voice={"rate": "-5%"}),
            env.request,
            agent_name="First",
        )
    assert error.value.status_code == 503
    assert "Redis" in error.value.detail
    persist.assert_awaited_once_with(SID, raise_on_failure=True)
    env.orch.apply_live_session_settings.assert_not_called()


@pytest.mark.asyncio
async def test_full_put_does_not_return_success_after_persistence_failure(env, monkeypatch):
    persist = AsyncMock(side_effect=RuntimeError("Redis write returned failure"))
    monkeypatch.setattr(api, "persist_session_agents_to_redis", persist)
    with pytest.raises(HTTPException) as error:
        await api.update_session_agent(
            SID,
            api.DynamicAgentConfig(name="Second", prompt="An updated selected agent prompt."),
            env.request,
            activate=False,
        )
    assert error.value.status_code == 503
    persist.assert_awaited_once_with(SID, raise_on_failure=True)


@pytest.mark.asyncio
async def test_cascade_named_edit_persists_only_selected_agent_and_requests_reconnect(env):
    response = await api.apply_live_session_settings(
        SID,
        api.LiveSettingsRequest(mode="cascade", speech={"vad_silence_timeout_ms": 1700}),
        env.request,
        agent_name="Second",
    )
    assert response["needs_reconnect"] is True
    assert response["live"] is False
    assert sa.get_session_agent(SID, "Second").speech.vad_silence_timeout_ms == 1700
    assert env.first.speech.vad_silence_timeout_ms == 1234
    env.orch.apply_live_session_settings.assert_not_called()


def test_cascade_active_base_agent_does_not_inherit_unrelated_specialist_speech(env):
    stt = SimpleNamespace(
        vad_silence_timeout_ms=800, use_semantic=False, candidate_languages=["en-US"]
    )
    memo = SimpleNamespace(get_value_from_corememory=lambda *args: "BaseAgent")
    handler = SimpleNamespace(
        _context=SimpleNamespace(stt_client=stt, memo_manager=memo),
        _session_id=SID,
        _session_short=SID,
    )
    VoiceHandler._apply_session_speech_settings(handler)
    assert stt.vad_silence_timeout_ms == 800
    assert stt.candidate_languages == ["en-US"]


@pytest.mark.asyncio
async def test_real_live_fast_path_preserves_shared_registry_and_unedited_settings(
    env, monkeypatch
):
    shared = agent("BaseAgent", 10)
    registry = {"BaseAgent": shared}
    update = AsyncMock()
    orch = voicelive.LiveOrchestrator(
        conn=SimpleNamespace(session=SimpleNamespace(update=update)),
        agents=registry,
        start_agent="BaseAgent",
    )
    monkeypatch.setattr(voicelive, "get_voicelive_orchestrator", lambda sid: orch)
    env.state.unified_agents = registry
    before = sa._serialize_agent(shared)

    response = await api.apply_live_session_settings(
        SID,
        api.LiveSettingsRequest(voice={"rate": "-7%"}, turn_detection={"threshold": 0.65}),
        env.request,
        agent_name="BaseAgent",
    )

    assert response["live"] is True
    update.assert_awaited_once()
    assert sa._serialize_agent(shared) == before
    assert registry["BaseAgent"] is shared
    live = orch.agents["BaseAgent"]
    assert live.voice.rate == "-7%"
    assert live.voice.pitch == "+3%" and live.voice.style == "serious"
    assert live.byom == shared.byom
    assert live.session["turn_detection"]["threshold"] == 0.65
    assert live.session["input_audio_transcription_settings"]["language"] == "es"


@pytest.mark.asyncio
async def test_real_live_push_failure_does_not_mutate_current_live_agent(env):
    before = sa._serialize_agent(env.first)
    orch = voicelive.LiveOrchestrator(
        conn=SimpleNamespace(
            session=SimpleNamespace(update=AsyncMock(side_effect=RuntimeError("disconnected")))
        ),
        agents={"First": env.first},
        start_agent="First",
    )
    with pytest.raises(RuntimeError, match="disconnected"):
        await orch.apply_live_session_settings(voice={"rate": "-7%"})
    assert sa._serialize_agent(orch.agents["First"]) == before


def test_create_only_query_is_wired_and_rejects_repeated_duplicate(atomic_env):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/agent-builder")
    app.state.redis = atomic_env.redis
    app.state.unified_agents = {}
    payload = {"name": "HTTP Duplicate", "prompt": "A new agent created through HTTP."}
    with TestClient(app) as client:
        url = f"/api/v1/agent-builder/session/{SID}?create_only=true&activate=false"
        first = client.put(url, json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "created"
        second = client.put(url, json={**payload, "prompt": "Must not replace the first copy."})
        assert second.status_code == 409
    assert sa.get_session_agent(SID, "HTTP Duplicate").prompt_template == payload["prompt"]
    assert atomic_env.redis.write_count == 1


def test_named_query_parameters_are_wired_in_http_routes(env):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/agent-builder")
    app.state.redis = None
    app.state.start_agent = None
    app.state.unified_agents = {}
    with TestClient(app) as client:
        response = client.get(f"/api/v1/agent-builder/session/{SID}?agent_name=Second")
        assert response.status_code == 200
        assert response.json()["agent_name"] == "Second"
        assert (
            client.get(f"/api/v1/agent-builder/session/{SID}?agent_name=Missing").status_code == 404
        )
        response = client.put(
            f"/api/v1/agent-builder/session/{SID}?activate=false",
            json={"name": "Second", "prompt": "Updated through the HTTP interface."},
        )
        assert response.status_code == 200
        assert response.json()["created_at"] == 200
        assert sa._adapter_update_callback.call_args.args[2] is False
        response = client.post(
            f"/api/v1/agent-builder/session/{SID}/live-settings?agent_name=Second",
            json={"voice": {"rate": "-9%"}},
        )
        assert response.status_code == 200
        assert response.json()["live"] is False
        env.orch.apply_live_session_settings.assert_not_called()
