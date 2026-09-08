"""
Agent Builder Endpoint Path Validation
======================================

Validates the full update path from the frontend payload shape through the
backend API to session state:

    frontend handleSave / Quick Tune
        -> PUT /agent-builder/session/{id}  (DynamicAgentConfig)
        -> _upsert_session_agent -> build_session_agent
        -> set_session_agent  (in-memory store + Redis + adapter callback)
        -> get_session_agent / GET /session/{id}   (reflects the update)

Also proves:
- POST /create and PUT /session are the SAME upsert (no divergence).
- PUT is idempotent: re-saving preserves created_at and overwrites values.
- Quick Tune live-settings persist onto the session agent, including the
  clone-from-base path when no session agent exists yet.

These call the endpoint coroutines directly (no network) with a stub Request,
so they exercise the real server-side processing without standing up the app.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from apps.artagent.backend.api.v1.endpoints.agent_builder import (
    DynamicAgentConfig,
    LiveSettingsRequest,
    apply_live_session_settings,
    create_dynamic_agent,
    get_session_agent_config,
    reset_session_agent,
    update_session_agent,
)
from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.src.orchestration.session_agents import (
    get_session_agent,
    remove_session_agent,
    set_redis_manager,
    set_session_agent,
)

# =============================================================================
# HELPERS
# =============================================================================


def frontend_payload(
    *,
    name: str = "My Bot",
    prompt: str = "You are a helpful voice assistant.",
    voice_name: str = "en-US-AvaMultilingualNeural",
    cascade_deployment: str = "gpt-4o",
    voicelive_deployment: str = "gpt-realtime",
    tools: list[str] | None = None,
    mcp_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Mirror the JSON body that AgentBuilder.jsx / App.jsx Quick Tune POSTs."""
    return {
        "name": name,
        "description": "Test agent",
        "greeting": "Hello!",
        "return_greeting": "Welcome back!",
        "prompt": prompt,
        "tools": tools or [],
        "mcp_servers": mcp_servers or [],
        "cascade_model": {
            "deployment_id": cascade_deployment,
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 4096,
            "endpoint_preference": "auto",
            "api_version": "2025-01-01-preview",
            "model_family": "gpt-4",
        },
        "voicelive_model": {
            "deployment_id": voicelive_deployment,
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 4096,
            "endpoint_preference": "auto",
            "api_version": "2025-04-01-preview",
            "model_family": "gpt-realtime",
        },
        "voice": {
            "name": voice_name,
            "type": "azure-standard",
            "style": "chat",
            "rate": "+0%",
        },
        "speech": {
            "vad_silence_timeout_ms": 800,
            "use_semantic_segmentation": False,
            "candidate_languages": ["en-US"],
        },
        "template_vars": {"brand": "Contoso"},
    }


def stub_request(unified_agents: dict | None = None, start_agent: str | None = None):
    """Minimal Request stand-in exposing app.state for live-settings resolution."""
    state = SimpleNamespace(
        unified_agents=unified_agents or {},
        start_agent=start_agent,
        redis=None,
        redis_manager=None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


class CountingRedisManager:
    """Dict-backed Redis fake that counts awaited writes."""

    def __init__(self, *, fail_writes: bool = False) -> None:
        self.store: dict[str, dict] = {}
        self.write_count = 0
        self.fail_writes = fail_writes

    def get_session_data(self, key: str) -> dict:
        return dict(self.store.get(key, {}))

    async def get_session_data_async(self, key: str, *, raise_on_failure=False) -> dict:
        return self.get_session_data(key)

    async def store_session_data_async(self, key: str, data: dict) -> bool:
        self.write_count += 1
        if self.fail_writes:
            return False
        self.store[key] = dict(data)
        return True


@pytest.fixture
def session_id() -> str:
    return "session_path_test"


@pytest.fixture(autouse=True)
def _clean_session(session_id):
    """Ensure each test starts and ends with no session agent."""
    set_redis_manager(None)
    remove_session_agent(session_id)
    yield
    set_redis_manager(None)
    remove_session_agent(session_id)
    set_redis_manager(None)


# =============================================================================
# FRONTEND PAYLOAD -> PUT -> SESSION STATE
# =============================================================================


@pytest.mark.asyncio
async def test_update_preserves_server_provenance_and_distinct_models(session_id):
    original = UnifiedAgent(name="My Bot", source_dir=Path("/configured/agents/my-bot"))
    set_session_agent(session_id, original, persist=False)
    payload = frontend_payload(cascade_deployment="gpt-4o-mini")
    payload["model"] = {"deployment_id": "gpt-4o", "name": "legacy"}
    payload["source_dir"] = "/untrusted/client/path"
    response = await update_session_agent(
        session_id, DynamicAgentConfig.model_validate(payload), stub_request()
    )
    saved = get_session_agent(session_id)
    assert saved.source_dir == original.source_dir
    assert saved.model.deployment_id == "gpt-4o"
    assert saved.model.name == "legacy"
    assert saved.cascade_model.deployment_id == "gpt-4o-mini"
    assert saved.voicelive_model.deployment_id == "gpt-realtime"
    assert response.config["source_dir"] == str(original.source_dir)


class TestUpdatePathPersists:
    """The exact frontend payload must land in session state via PUT."""

    @pytest.mark.asyncio
    async def test_put_persists_frontend_payload(self, session_id) -> None:
        config = DynamicAgentConfig.model_validate(
            frontend_payload(
                name="My Bot",
                voice_name="en-US-JennyNeural",
                mcp_servers=["crm-mcp", "policy-mcp"],
            )
        )

        resp = await update_session_agent(session_id, config, stub_request())
        assert resp.status == "updated"
        assert resp.agent_name == "My Bot"

        # Update landed in the session-agent store (what the orchestrator reads).
        stored = get_session_agent(session_id)
        assert stored is not None
        assert stored.name == "My Bot"
        assert stored.prompt_template == "You are a helpful voice assistant."
        assert stored.voice.name == "en-US-JennyNeural"
        assert stored.cascade_model.deployment_id == "gpt-4o"
        assert stored.cascade_model.api_version == "2025-01-01-preview"
        assert stored.cascade_model.model_family == "gpt-4"
        assert stored.voicelive_model.deployment_id == "gpt-realtime"
        assert stored.voicelive_model.api_version == "2025-04-01-preview"
        assert stored.voicelive_model.model_family == "gpt-realtime"
        assert stored.mcp_servers == ["crm-mcp", "policy-mcp"]
        assert stored.template_vars == {"brand": "Contoso"}

    @pytest.mark.asyncio
    async def test_get_endpoint_roundtrips_update(self, session_id) -> None:
        config = DynamicAgentConfig.model_validate(frontend_payload(name="RoundTrip"))
        await update_session_agent(session_id, config, stub_request())

        got = await get_session_agent_config(session_id, stub_request())
        assert got.agent_name == "RoundTrip"
        assert got.config["prompt_full"] == "You are a helpful voice assistant."
        assert got.config["voice"]["name"] == "en-US-AvaMultilingualNeural"
        assert got.config["cascade_model"]["deployment_id"] == "gpt-4o"
        assert got.config["cascade_model"]["api_version"] == "2025-01-01-preview"
        assert got.config["cascade_model"]["model_family"] == "gpt-4"
        assert got.config["voicelive_model"]["deployment_id"] == "gpt-realtime"
        assert got.config["voicelive_model"]["api_version"] == "2025-04-01-preview"
        assert got.config["voicelive_model"]["model_family"] == "gpt-realtime"

    @pytest.mark.asyncio
    async def test_nested_persisted_session_payload_roundtrips(self, session_id) -> None:
        payload = frontend_payload(name="Nested Session")
        payload["session"] = {
            "modalities": ["TEXT", "AUDIO"],
            "input_audio_format": "PCM16",
            "output_audio_format": "PCM16",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.61,
                "silence_duration_ms": 910,
                "prefix_padding_ms": 310,
            },
            "tool_choice": "auto",
            "input_audio_transcription_settings": {
                "model": "whisper-1",
                "language": "en-US",
            },
        }
        config = DynamicAgentConfig.model_validate(payload)

        await update_session_agent(session_id, config, stub_request())

        got = await get_session_agent_config(session_id, stub_request())
        turn_detection = got.config["session"]["turn_detection"]
        assert turn_detection["type"] == "server_vad"
        assert turn_detection["threshold"] == 0.61
        assert turn_detection["silence_duration_ms"] == 910
        assert turn_detection["prefix_padding_ms"] == 310
        assert got.config["session"]["input_audio_transcription_settings"] == {
            "model": "whisper-1",
            "language": "en-US",
        }


class TestUpsertSemantics:
    """PUT is an idempotent upsert; create + update share one path."""

    @pytest.mark.asyncio
    async def test_resave_preserves_created_at_and_overwrites(self, session_id) -> None:
        first = DynamicAgentConfig.model_validate(
            frontend_payload(name="Bot", voice_name="en-US-AvaMultilingualNeural")
        )
        r1 = await update_session_agent(session_id, first, stub_request())
        created_at = r1.created_at

        second = DynamicAgentConfig.model_validate(
            frontend_payload(name="Bot", voice_name="en-US-GuyNeural")
        )
        r2 = await update_session_agent(session_id, second, stub_request())

        # created_at preserved across saves; values overwritten.
        assert r2.created_at == created_at
        assert r2.modified_at >= r1.modified_at
        assert get_session_agent(session_id).voice.name == "en-US-GuyNeural"

    @pytest.mark.asyncio
    async def test_create_and_update_produce_identical_agent(self) -> None:
        payload = frontend_payload(name="Parity", tools=[])
        cfg = DynamicAgentConfig.model_validate(payload)

        sid_create = "session_parity_create"
        sid_update = "session_parity_update"
        remove_session_agent(sid_create)
        remove_session_agent(sid_update)
        try:
            await create_dynamic_agent(cfg, sid_create, stub_request())
            await update_session_agent(sid_update, cfg, stub_request())

            a = get_session_agent(sid_create)
            b = get_session_agent(sid_update)

            # Same build path => identical config (ignoring per-session metadata).
            assert a.name == b.name
            assert a.prompt_template == b.prompt_template
            assert a.tool_names == b.tool_names
            assert a.voice.to_dict() == b.voice.to_dict()
            assert a.cascade_model.to_dict() == b.cascade_model.to_dict()
            assert a.voicelive_model.to_dict() == b.voicelive_model.to_dict()
            assert a.handoff.trigger == b.handoff.trigger
        finally:
            remove_session_agent(sid_create)
            remove_session_agent(sid_update)

    @pytest.mark.asyncio
    async def test_upsert_performs_single_awaited_redis_write(self, session_id) -> None:
        redis = CountingRedisManager()
        set_redis_manager(redis)

        cfg = DynamicAgentConfig.model_validate(frontend_payload(name="Durable"))
        await update_session_agent(session_id, cfg, stub_request())

        assert redis.write_count == 1

    @pytest.mark.asyncio
    async def test_upsert_surfaces_redis_write_failure(self, session_id) -> None:
        from fastapi import HTTPException

        redis = CountingRedisManager(fail_writes=True)
        set_redis_manager(redis)

        cfg = DynamicAgentConfig.model_validate(frontend_payload(name="Durable"))
        with pytest.raises(HTTPException) as exc:
            await update_session_agent(session_id, cfg, stub_request())

        assert exc.value.status_code == 503
        assert redis.write_count == 1


class TestInvalidToolsRejected:
    """Tool validation guards both create and update identically."""

    @pytest.mark.asyncio
    async def test_unknown_tool_raises_400(self, session_id) -> None:
        from fastapi import HTTPException

        cfg = DynamicAgentConfig.model_validate(
            frontend_payload(tools=["definitely_not_a_real_tool"])
        )
        with pytest.raises(HTTPException) as exc:
            await update_session_agent(session_id, cfg, stub_request())
        assert exc.value.status_code == 400


# =============================================================================
# QUICK TUNE (live-settings) -> SESSION STATE
# =============================================================================


class TestLiveSettingsPersist:
    """Quick Tune tweaks must be captured in session state."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("customized_auth", [False, True])
    async def test_live_tuning_owns_only_the_current_effective_agent(
        self, session_id, customized_auth, monkeypatch
    ):
        from copy import deepcopy

        from apps.artagent.backend.src.orchestration import session_agents as registry
        from apps.artagent.backend.voice.shared.config_resolver import build_effective_registry
        from apps.artagent.backend.voice.voicelive import orchestrator as live
        from src.stateful.state_managment import MemoManager

        from tests.test_voicelive_tool_offload import DummyVoiceLiveConnection

        monkeypatch.setattr(live, "_voicelive_orchestrators", {})
        monkeypatch.setattr(registry, "_session_agents", {})
        monkeypatch.setattr(registry, "_active_session_agents", {})
        catalog = {
            name: UnifiedAgent(
                name=name,
                voice=VoiceConfig(name="en-US-JennyNeural"),
                session={"turn_detection": {"threshold": 0.5}, "custom": {"nested": []}},
                model=ModelConfig(metadata={"nested": []}),
            )
            for name in ("AuthAgent", "FraudAgent")
        }
        first_agents, _, _ = build_effective_registry(None, base_agents=catalog)
        other_agents, _, _ = build_effective_registry(None, base_agents=catalog)
        first_agents["FraudAgent"] = deepcopy(first_agents["FraudAgent"])
        effective = first_agents["FraudAgent"]
        effective.greeting = "Scenario-specific greeting"
        memo = MemoManager(session_id=session_id)
        first = live.LiveOrchestrator(
            DummyVoiceLiveConnection(), first_agents, start_agent="AuthAgent", memo_manager=memo
        )
        other = live.LiveOrchestrator(
            DummyVoiceLiveConnection(), other_agents, start_agent="FraudAgent"
        )
        live.register_voicelive_orchestrator(session_id, first)
        if customized_auth:
            auth = deepcopy(catalog["AuthAgent"])
            auth.voice.name = "en-US-AvaNeural"
            set_session_agent(session_id, auth, set_active=True, persist=False)
        redis = CountingRedisManager()
        set_redis_manager(redis)
        await registry.persist_session_agents_to_redis(session_id, raise_on_failure=True)
        first.active = "FraudAgent"
        memo.set_corememory("active_agent", "FraudAgent")

        result = await apply_live_session_settings(
            session_id,
            LiveSettingsRequest.model_validate(
                {
                    "voice": {"name": "en-US-GuyNeural", "pitch": "+6%"},
                    "turn_detection": {"threshold": 0.8},
                }
            ),
            stub_request(catalog, "AuthAgent"),
        )
        assert result["live"]
        owned = get_session_agent(session_id, "FraudAgent")
        assert owned is not None
        assert owned is first.agents["FraudAgent"]
        assert owned is not effective
        assert owned.greeting == "Scenario-specific greeting"
        assert owned.voice.name == "en-US-GuyNeural"
        assert owned.session["turn_detection"]["threshold"] == 0.8
        assert first.active == memo.get_value_from_corememory("active_agent") == "FraudAgent"
        assert (
            catalog["FraudAgent"].voice.name
            == other.agents["FraudAgent"].voice.name
            == "en-US-JennyNeural"
        )
        for field in ("voice", "speech", "model", "session"):
            assert getattr(owned, field) is not getattr(effective, field)
        owned.session["custom"]["nested"].append("session-only")
        owned.model.metadata["nested"].append("session-only")
        assert effective.session["custom"]["nested"] == []
        assert effective.model.metadata["nested"] == []
        saved = memo.get_value_from_corememory(registry.AGENTS_KEY_ALL)
        assert saved["FraudAgent"]["voice"]["name"] == "en-US-GuyNeural"
        if customized_auth:
            assert get_session_agent(session_id, "AuthAgent").voice.name == "en-US-AvaNeural"

    @pytest.mark.asyncio
    async def test_direct_live_tuning_does_not_mutate_borrowed_catalog(self):
        from apps.artagent.backend.voice.shared.config_resolver import build_effective_registry
        from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator

        from tests.test_voicelive_tool_offload import DummyVoiceLiveConnection

        base = UnifiedAgent(name="Agent", voice=VoiceConfig(name="en-US-JennyNeural"))
        agents, _, _ = build_effective_registry(None, base_agents={"Agent": base})
        orch = LiveOrchestrator(DummyVoiceLiveConnection(), agents, start_agent="Agent")
        await orch.apply_live_session_settings(voice={"name": "en-US-GuyNeural"})
        assert base.voice.name == "en-US-JennyNeural"
        assert orch.agents["Agent"].voice.name == "en-US-GuyNeural"

    @pytest.mark.asyncio
    async def test_patches_existing_session_agent(self, session_id) -> None:
        # Seed a session agent (as Agent Builder would).
        cfg = DynamicAgentConfig.model_validate(
            frontend_payload(name="Tunable", voice_name="en-US-AvaMultilingualNeural")
        )
        await update_session_agent(session_id, cfg, stub_request())

        payload = LiveSettingsRequest.model_validate(
            {
                "mode": "voicelive",
                "turn_detection": {"threshold": 0.6, "silence_duration_ms": 900},
                "voice": {"name": "en-US-GuyNeural", "rate": "-4%"},
            }
        )
        result = await apply_live_session_settings(session_id, payload, stub_request())

        assert result["applied"] is True
        stored = get_session_agent(session_id)
        assert stored.voice.name == "en-US-GuyNeural"
        assert stored.voice.rate == "-4%"
        assert stored.session["turn_detection"]["threshold"] == 0.6
        assert stored.session["turn_detection"]["silence_duration_ms"] == 900

    @pytest.mark.asyncio
    async def test_patches_voice_style_and_pitch(self, session_id) -> None:
        """Style/pitch were accepted by the UI but dropped by the patch schema,
        so the Quick Tune controls for them were silent no-ops."""
        cfg = DynamicAgentConfig.model_validate(
            frontend_payload(name="Tunable", voice_name="en-US-AvaMultilingualNeural")
        )
        await update_session_agent(session_id, cfg, stub_request())

        payload = LiveSettingsRequest.model_validate(
            {
                "mode": "voicelive",
                "voice": {"style": "cheerful", "pitch": "+6%"},
            }
        )
        result = await apply_live_session_settings(session_id, payload, stub_request())

        assert result["applied"] is True
        stored = get_session_agent(session_id)
        assert stored.voice.style == "cheerful"
        assert stored.voice.pitch == "+6%"
        # Untouched fields survive the partial patch.
        assert stored.voice.name == "en-US-AvaMultilingualNeural"

    @pytest.mark.asyncio
    async def test_clones_base_agent_when_no_session_agent(self, session_id) -> None:
        # No session agent yet; a base agent is "active" for the call.
        base = UnifiedAgent(
            name="Concierge",
            description="base",
            handoff=HandoffConfig(trigger="handoff_concierge"),
            model=ModelConfig(deployment_id="gpt-4o"),
            voice=VoiceConfig(name="en-US-JennyNeural", style="chat"),
            prompt_template="base prompt",
            tool_names=[],
        )
        req = stub_request(unified_agents={"Concierge": base}, start_agent="Concierge")

        assert get_session_agent(session_id) is None

        payload = LiveSettingsRequest.model_validate(
            {"mode": "voicelive", "voice": {"name": "en-US-GuyNeural"}}
        )
        result = await apply_live_session_settings(session_id, payload, req)

        assert result["applied"] is True
        # A session-scoped clone now exists and carries the tweak — not lost on reconnect.
        cloned = get_session_agent(session_id)
        assert cloned is not None
        assert cloned.name == "Concierge"
        assert cloned.voice.name == "en-US-GuyNeural"
        assert cloned.metadata.get("cloned_from") == "Concierge"
        # The shared registry agent must NOT be mutated.
        assert base.voice.name == "en-US-JennyNeural"

    @pytest.mark.asyncio
    async def test_patches_explicit_active_agent_not_insertion_order(self, session_id) -> None:
        await update_session_agent(
            session_id,
            DynamicAgentConfig.model_validate(
                frontend_payload(name="Alpha", voice_name="en-US-AvaMultilingualNeural")
            ),
            stub_request(),
        )
        await update_session_agent(
            session_id,
            DynamicAgentConfig.model_validate(
                frontend_payload(name="Beta", voice_name="en-US-JennyNeural")
            ),
            stub_request(),
        )

        payload = LiveSettingsRequest.model_validate(
            {"mode": "voicelive", "voice": {"name": "en-US-GuyNeural"}}
        )
        result = await apply_live_session_settings(
            session_id, payload, stub_request(start_agent="Alpha")
        )

        assert result["applied"] is True
        assert get_session_agent(session_id, "Alpha").voice.name == "en-US-GuyNeural"
        assert get_session_agent(session_id, "Beta").voice.name == "en-US-JennyNeural"

    @pytest.mark.asyncio
    async def test_live_settings_performs_single_awaited_redis_write(self, session_id) -> None:
        await update_session_agent(
            session_id,
            DynamicAgentConfig.model_validate(frontend_payload(name="Tunable")),
            stub_request(),
        )
        redis = CountingRedisManager()
        set_redis_manager(redis)

        payload = LiveSettingsRequest.model_validate(
            {"mode": "cascade", "voice": {"name": "en-US-GuyNeural"}}
        )
        await apply_live_session_settings(session_id, payload, stub_request())

        assert redis.write_count == 1

    @pytest.mark.asyncio
    async def test_reset_surfaces_redis_clear_failure(self, session_id) -> None:
        from fastapi import HTTPException

        await update_session_agent(
            session_id,
            DynamicAgentConfig.model_validate(frontend_payload(name="Resettable")),
            stub_request(),
        )
        redis = CountingRedisManager(fail_writes=True)
        set_redis_manager(redis)

        with pytest.raises(HTTPException) as exc:
            await reset_session_agent(session_id, stub_request())

        assert exc.value.status_code == 503


# =============================================================================
# QUICK TUNE -> RECONNECT: THE ACTIVE SCENARIO MUST SURVIVE
# =============================================================================


class TestQuickTuneReconnectKeepsScenario:
    """End-to-end: PUT a Quick Tune agent, then re-resolve like a reconnect does.

    A Quick Tune apply persists the session agent and forces the VoiceLive socket
    to reconnect. The reconnect must keep the scenario the caller was in and only
    repoint its start agent at the tuned agent — VoiceLive binds the generative
    model and the BYOM profile at connect() time, so the start agent is the only
    place a per-agent model override can take effect.
    """

    @pytest.mark.asyncio
    async def test_tuned_agent_starts_the_preserved_scenario(self, session_id):
        from apps.artagent.backend.registries.agentstore.loader import (
            build_handoff_map,
            discover_agents,
        )
        from apps.artagent.backend.registries.scenariostore import load_scenario
        from apps.artagent.backend.voice.shared import (
            build_effective_registry,
            resolve_orchestrator_config,
        )

        base_agents = discover_agents()
        app_state_handoff_map = build_handoff_map(base_agents)

        # 1. Quick Tune applies to the agent the caller is talking to.
        payload = frontend_payload(name="BankingConcierge", voice_name="en-US-GuyNeural")
        config = DynamicAgentConfig.model_validate(payload)
        await update_session_agent(session_id, config, stub_request(unified_agents=base_agents))
        session_agent = get_session_agent(session_id)
        assert session_agent is not None

        # 2. Reconnect resolves the scenario, then merges the session agent.
        resolved = resolve_orchestrator_config(session_id=session_id, scenario_name="banking")
        agents, start_agent, handoff_map = build_effective_registry(
            resolved,
            base_agents=base_agents,
            session_agent=session_agent,
            app_state_handoff_map=app_state_handoff_map,
        )

        # Scenario preserved, start agent repointed at the tuned agent.
        assert resolved.scenario_name == "banking"
        assert start_agent == "BankingConcierge"
        assert resolved.scenario.start_agent == "BankingConcierge"
        assert len(resolved.scenario.handoffs) == len(load_scenario("banking").handoffs)

        # Full registry survives and scenario routing wins.
        assert len(agents) == len(base_agents)
        assert handoff_map["handoff_concierge"] == "BankingConcierge"

        # The tuned config is what the connection will bind.
        assert agents[start_agent] is session_agent
        assert agents[start_agent].voice.name == "en-US-GuyNeural"

        # The shared scenario cache is untouched for other sessions.
        assert load_scenario("banking").start_agent == "BankingConcierge"
