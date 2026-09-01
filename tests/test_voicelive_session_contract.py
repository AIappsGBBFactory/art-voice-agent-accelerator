"""
Voice Live Session Contract
===========================

End-to-end contract tests for the two settings that were previously only
asserted at the *persistence* layer — never at the layer that actually talks to
Azure — and therefore could silently regress:

  * **TTS voice** — the agent's ``voice`` must reach ``session.update(voice=...)``
    with the exact name/type/style/rate/pitch that was configured, both on the
    initial session apply and on the Quick Tune instant push.
  * **Model / BYOM** — the start agent's ``voicelive_model`` must reach
    ``connect(model=...)`` and its BYOM profile must reach ``connect(query=...)``.
    Voice Live binds both at connect() time, so a drop here means the session
    runs on the wrong model with no error.

Also covers ``verify_voicelive_session_contract``, which diffs what we requested
against the ``session.updated`` echo so a service-side substitution is visible
instead of silent.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
    VoiceLiveBYOMConfig,
)
from apps.artagent.backend.voice.voicelive.orchestrator import (
    LiveOrchestrator,
    verify_voicelive_session_contract,
)


# =============================================================================
# Fakes
# =============================================================================


class _FakeSessionNamespace:
    """Captures the RequestSession handed to ``conn.session.update``."""

    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def update(self, session=None, **_kwargs):
        self.updates.append(session)


class _FakeConnection:
    def __init__(self) -> None:
        self.session = _FakeSessionNamespace()

    @property
    def last_update(self) -> Any:
        assert self.session.updates, "no session.update() was issued"
        return self.session.updates[-1]


class _EchoSession:
    """Stand-in for the ``session`` object on a ``session.updated`` event."""

    def __init__(self, voice: Any = None, model: str | None = None) -> None:
        self.id = "sess-1"
        self.voice = voice
        self.model = model


def _make_agent(
    *,
    voice: VoiceConfig | None = None,
    voicelive_model: ModelConfig | None = None,
    byom: VoiceLiveBYOMConfig | None = None,
) -> UnifiedAgent:
    return UnifiedAgent(
        name="ContractAgent",
        description="session contract test agent",
        handoff=HandoffConfig(trigger="handoff_contractagent"),
        model=ModelConfig(deployment_id="gpt-realtime"),
        voicelive_model=voicelive_model,
        voice=voice or VoiceConfig(),
        byom=byom,
        prompt_template="You are a test agent.",
    )


# =============================================================================
# build_voicelive_voice — the payload that gets sent
# =============================================================================


def test_voice_payload_carries_name_type_and_customizations():
    agent = _make_agent(
        voice=VoiceConfig(
            name="en-US-EmmaMultilingualNeural",
            type="azure-standard",
            style="cheerful",
            rate="-8%",
            pitch="+3%",
        )
    )

    payload = agent.build_voicelive_voice()

    assert payload is not None
    assert payload.name == "en-US-EmmaMultilingualNeural"
    assert payload.type == "azure-standard"
    assert payload.style == "cheerful"
    assert payload.rate == "-8%"
    assert payload.pitch == "+3%"


def test_voice_payload_omits_neutral_rate_and_pitch():
    """``+0%`` is the "unset" sentinel and must not be sent as a customization."""
    agent = _make_agent(
        voice=VoiceConfig(name="en-US-AvaMultilingualNeural", rate="+0%", pitch="+0%")
    )

    payload = agent.build_voicelive_voice()

    assert payload.rate is None
    assert payload.pitch is None


def test_voice_payload_is_none_when_name_missing():
    agent = _make_agent(voice=VoiceConfig(name=""))
    assert agent.build_voicelive_voice() is None


# =============================================================================
# apply_voicelive_session — voice actually reaches the SDK
# =============================================================================


@pytest.mark.asyncio
async def test_configured_voice_reaches_session_update():
    """The regression this suite exists for: voice must land on the wire."""
    agent = _make_agent(
        voice=VoiceConfig(
            name="en-US-OnyxTurboMultilingualNeural",
            type="azure-standard",
            style="chat",
            rate="-4%",
        )
    )
    conn = _FakeConnection()

    await agent.apply_voicelive_session(conn, session_id="sess-1")

    sent = conn.last_update
    assert sent.voice is not None, "session.update() was issued without a voice"
    assert sent.voice.name == "en-US-OnyxTurboMultilingualNeural"
    assert sent.voice.style == "chat"
    assert sent.voice.rate == "-4%"


@pytest.mark.asyncio
async def test_session_update_omits_voice_when_agent_has_none():
    agent = _make_agent(voice=VoiceConfig(name=""))
    conn = _FakeConnection()

    await agent.apply_voicelive_session(conn, session_id="sess-1")

    assert getattr(conn.last_update, "voice", None) is None


# =============================================================================
# Quick Tune instant push — apply_live_session_settings
# =============================================================================


def _make_orchestrator(agent: UnifiedAgent, conn: _FakeConnection) -> LiveOrchestrator:
    return LiveOrchestrator(
        conn=conn,
        agents={agent.name: agent},
        start_agent=agent.name,
        model_name="gpt-realtime",
    )


@pytest.mark.asyncio
async def test_live_push_sends_new_voice_name():
    agent = _make_agent(voice=VoiceConfig(name="en-US-AvaMultilingualNeural"))
    conn = _FakeConnection()
    orch = _make_orchestrator(agent, conn)

    pushed = await orch.apply_live_session_settings(
        voice={"name": "en-US-EmmaMultilingualNeural"}
    )

    assert pushed is True
    assert conn.last_update.voice.name == "en-US-EmmaMultilingualNeural"
    # And it persists on the agent so the next full session update keeps it.
    assert agent.voice.name == "en-US-EmmaMultilingualNeural"


@pytest.mark.asyncio
async def test_live_push_applies_style_and_pitch():
    """Style/pitch used to be dropped, making those Quick Tune controls no-ops."""
    agent = _make_agent(
        voice=VoiceConfig(name="en-US-AvaMultilingualNeural", style="chat", pitch="+0%")
    )
    conn = _FakeConnection()
    orch = _make_orchestrator(agent, conn)

    pushed = await orch.apply_live_session_settings(
        voice={"style": "cheerful", "pitch": "+6%", "rate": "-2%"}
    )

    assert pushed is True
    sent = conn.last_update.voice
    assert sent.style == "cheerful"
    assert sent.pitch == "+6%"
    assert sent.rate == "-2%"
    assert agent.voice.style == "cheerful"
    assert agent.voice.pitch == "+6%"


@pytest.mark.asyncio
async def test_live_push_noop_without_changes():
    agent = _make_agent()
    conn = _FakeConnection()
    orch = _make_orchestrator(agent, conn)

    assert await orch.apply_live_session_settings() is False
    assert conn.session.updates == []


# =============================================================================
# verify_voicelive_session_contract — did the service accept what we asked for?
# =============================================================================


def test_contract_ok_when_echo_matches():
    agent = _make_agent(voice=VoiceConfig(name="en-US-AvaMultilingualNeural"))
    result = verify_voicelive_session_contract(
        requested_voice=agent.build_voicelive_voice(),
        requested_model="gpt-realtime",
        session_obj=_EchoSession(
            voice=agent.build_voicelive_voice(), model="gpt-realtime"
        ),
    )

    assert result["ok"] is True
    assert result["voice_ok"] is True
    assert result["model_ok"] is True


def test_contract_detects_voice_substitution():
    agent = _make_agent(voice=VoiceConfig(name="en-US-AvaMultilingualNeural"))
    other = _make_agent(voice=VoiceConfig(name="en-US-EmmaMultilingualNeural"))

    result = verify_voicelive_session_contract(
        requested_voice=agent.build_voicelive_voice(),
        requested_model="gpt-realtime",
        session_obj=_EchoSession(voice=other.build_voicelive_voice()),
    )

    assert result["voice_ok"] is False
    assert result["ok"] is False
    assert result["voice_requested"] == "en-us-avamultilingualneural"
    assert result["voice_applied"] == "en-us-emmamultilingualneural"


def test_contract_detects_model_substitution():
    result = verify_voicelive_session_contract(
        requested_voice=None,
        requested_model="my-finetuned-realtime",
        session_obj=_EchoSession(model="gpt-4o-realtime-preview"),
    )

    assert result["model_ok"] is False
    assert result["ok"] is False


def test_contract_handles_string_voice_echo():
    """OpenAI-style voices come back as a bare string, not an object."""
    result = verify_voicelive_session_contract(
        requested_voice="alloy",
        requested_model=None,
        session_obj=_EchoSession(voice="Alloy"),
    )

    assert result["voice_ok"] is True


def test_contract_is_not_a_mismatch_when_echo_is_silent():
    """A service that doesn't echo a field must not raise a false alarm."""
    result = verify_voicelive_session_contract(
        requested_voice="alloy",
        requested_model="gpt-realtime",
        session_obj=_EchoSession(voice=None, model=None),
    )

    assert result["voice_ok"] is None
    assert result["model_ok"] is None
    assert result["ok"] is True


# -----------------------------------------------------------------------------
# Deployment SKU tolerance — Azure echoes the *deployment* name, not the model
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "applied, expected_sku",
    [
        ("gpt-realtime", None),
        ("gpt-realtime-datazone-standard", "datazone-standard"),
        ("gpt-realtime-globalstandard", "globalstandard"),
        ("gpt-realtime-global-standard", "global-standard"),
        ("gpt-realtime-standard", "standard"),
        ("gpt-realtime-provisioned-managed", "provisioned-managed"),
        ("GPT-Realtime-DataZone-Standard", "datazone-standard"),
    ],
)
def test_contract_tolerates_deployment_sku_suffix(applied: str, expected_sku: str | None):
    """The tier suffix on a deployment name is not a model substitution.

    Production requests ``gpt-realtime`` and Azure echoes
    ``gpt-realtime-datazone-standard`` — the same model on a data-zone
    deployment. Flagging that fired a WARNING on 100% of ``session.updated``
    events and pinned ``voicelive.session_contract_ok`` to False.
    """
    result = verify_voicelive_session_contract(
        requested_voice=None,
        requested_model="gpt-realtime",
        session_obj=_EchoSession(model=applied),
    )

    assert result["model_ok"] is True
    assert result["ok"] is True
    # The raw echo is preserved so operators can still see which tier applied.
    assert result["model_applied"] == applied.lower()
    assert result["model_applied_base"] == "gpt-realtime"
    assert result["model_applied_sku"] == expected_sku


@pytest.mark.parametrize(
    "applied",
    [
        "gpt-4o-realtime-preview",
        "gpt-realtime-mini",
        "gpt-realtime-preview",
        "gpt-4o-mini-realtime-preview",
    ],
)
def test_contract_still_detects_genuine_model_substitution(applied: str):
    """SKU tolerance must not degrade into a prefix/substring match.

    ``gpt-realtime-mini`` shares the requested model's prefix but is a different,
    cheaper model — exactly the substitution this check exists to catch. Only
    suffixes on the recognized deployment-tier allowlist are forgiven.
    """
    result = verify_voicelive_session_contract(
        requested_voice=None,
        requested_model="gpt-realtime",
        session_obj=_EchoSession(model=applied),
    )

    assert result["model_ok"] is False
    assert result["ok"] is False


def test_contract_sku_normalization_is_symmetric():
    """Our own configured deployment name may be the SKU-qualified one."""
    result = verify_voicelive_session_contract(
        requested_voice=None,
        requested_model="gpt-realtime-datazone-standard",
        session_obj=_EchoSession(model="gpt-realtime"),
    )

    assert result["model_ok"] is True
    assert result["model_requested"] == "gpt-realtime-datazone-standard"
    assert result["model_requested_base"] == "gpt-realtime"
    assert result["model_requested_sku"] == "datazone-standard"


def test_contract_sku_fields_are_none_when_model_is_absent():
    """Absent echo stays 'not verifiable', and the added fields follow suit."""
    result = verify_voicelive_session_contract(
        requested_voice=None,
        requested_model=None,
        session_obj=_EchoSession(model=None),
    )

    assert result["model_ok"] is None
    assert result["model_applied"] is None
    assert result["model_applied_base"] is None
    assert result["model_applied_sku"] is None
    assert result["model_requested_base"] is None
    assert result["model_requested_sku"] is None
    assert result["ok"] is True


def test_contract_preserves_public_result_keys():
    """Callers depend on these exact keys; new fields are additive only."""
    result = verify_voicelive_session_contract(
        requested_voice="alloy",
        requested_model="gpt-realtime",
        session_obj=_EchoSession(voice="alloy", model="gpt-realtime-datazone-standard"),
    )

    assert {
        "voice_requested",
        "voice_applied",
        "voice_ok",
        "model_requested",
        "model_applied",
        "model_ok",
        "ok",
    } <= set(result)


def test_contract_still_fails_when_voice_is_wrong_despite_sku_match():
    """SKU tolerance on the model must not rescue a genuine voice mismatch."""
    result = verify_voicelive_session_contract(
        requested_voice="alloy",
        requested_model="gpt-realtime",
        session_obj=_EchoSession(voice="echo", model="gpt-realtime-datazone-standard"),
    )

    assert result["model_ok"] is True
    assert result["voice_ok"] is False
    assert result["ok"] is False


def test_orchestrator_does_not_warn_on_sku_suffixed_model():
    """The production regression, end-to-end through the orchestrator."""
    agent = _make_agent(voice=VoiceConfig(name="en-US-AlloyTurboMultilingualNeural"))
    orch = _make_orchestrator(agent, _FakeConnection())

    result = orch._verify_session_contract(
        _EchoSession(
            voice=agent.build_voicelive_voice(),
            model="gpt-realtime-datazone-standard",
        )
    )

    assert result is not None
    assert result["ok"] is True
    assert result["model_ok"] is True


def test_orchestrator_verifies_against_active_agent_voice():
    agent = _make_agent(voice=VoiceConfig(name="en-US-AvaMultilingualNeural"))
    orch = _make_orchestrator(agent, _FakeConnection())

    result = orch._verify_session_contract(
        _EchoSession(voice=agent.build_voicelive_voice(), model="gpt-realtime")
    )

    assert result is not None and result["ok"] is True


def test_orchestrator_flags_mismatch_against_active_agent_voice():
    agent = _make_agent(voice=VoiceConfig(name="en-US-AvaMultilingualNeural"))
    orch = _make_orchestrator(agent, _FakeConnection())

    result = orch._verify_session_contract(_EchoSession(voice="alloy"))

    assert result is not None and result["ok"] is False


# =============================================================================
# Model + BYOM reach connect()
# =============================================================================


class _StubSettings:
    azure_voicelive_endpoint = "wss://contoso-avl.cognitiveservices.azure.com"
    azure_voicelive_model = "gpt-realtime"
    ws_max_msg_size = 1024
    ws_heartbeat = 10
    ws_timeout = 30
    start_agent = "ContractAgent"


class _StubConnectionCM:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_exc):
        return False


@pytest.fixture
def warmup_env(monkeypatch):
    """Patch the warmup seam so only model/BYOM/voice resolution is under test.

    Yields ``(handler_module, connect_kwargs, fake_connection)`` so a test can
    assert on both what was passed to ``connect()`` and what was pushed to
    ``session.update()`` on the resulting connection.
    """
    from apps.artagent.backend.voice.voicelive import handler as vh

    captured: dict[str, Any] = {}
    conn = _FakeConnection()

    def _fake_connect(**kwargs):
        captured.update(kwargs)
        return _StubConnectionCM(conn)

    async def _fake_credential(_settings):
        return object()

    monkeypatch.setattr(vh, "connect", _fake_connect)
    monkeypatch.setattr(vh, "get_settings", lambda: _StubSettings())
    monkeypatch.setattr(vh, "resolve_orchestrator_config", lambda **_kw: None)
    monkeypatch.setattr(vh, "discover_agents", dict)
    monkeypatch.setattr(
        vh.VoiceLiveSDKHandler, "_build_credential", staticmethod(_fake_credential)
    )
    return vh, captured, conn


@pytest.mark.asyncio
async def test_start_agent_model_and_byom_reach_connect(warmup_env, monkeypatch):
    vh, captured, _conn = warmup_env
    agent = _make_agent(
        voicelive_model=ModelConfig(deployment_id="my-finetuned-realtime"),
        byom=VoiceLiveBYOMConfig(mode="byom-azure-openai-realtime"),
    )
    monkeypatch.setattr(vh, "get_session_agent", lambda _sid: agent)

    prepared = await vh._prepare_voicelive_call_warmup(
        app_state=None,
        call_connection_id="call-1",
        session_id="sess-1",
        scenario_name=None,
        user_email=None,
    )

    assert captured["model"] == "my-finetuned-realtime"
    assert captured["query"] == {"profile": "byom-azure-openai-realtime"}
    assert prepared is not None
    assert prepared.model == "my-finetuned-realtime"
    assert prepared.session_prepared is True


@pytest.mark.asyncio
async def test_managed_start_agent_sends_no_byom_profile(warmup_env, monkeypatch):
    vh, captured, _conn = warmup_env
    agent = _make_agent(voicelive_model=ModelConfig(deployment_id="gpt-realtime"))
    monkeypatch.setattr(vh, "get_session_agent", lambda _sid: agent)

    await vh._prepare_voicelive_call_warmup(
        app_state=None,
        call_connection_id="call-1",
        session_id="sess-1",
        scenario_name=None,
        user_email=None,
    )

    assert captured["model"] == "gpt-realtime"
    assert "query" not in captured


@pytest.mark.asyncio
async def test_warmup_applies_start_agent_voice_to_prepared_session(
    warmup_env, monkeypatch
):
    """A warm connection must be primed with the agent's voice, not a default."""
    vh, _captured, conn = warmup_env
    agent = _make_agent(voice=VoiceConfig(name="en-US-EmmaMultilingualNeural"))
    monkeypatch.setattr(vh, "get_session_agent", lambda _sid: agent)

    await vh._prepare_voicelive_call_warmup(
        app_state=None,
        call_connection_id="call-1",
        session_id="sess-1",
        scenario_name=None,
        user_email=None,
    )

    assert conn.last_update.voice.name == "en-US-EmmaMultilingualNeural"


# =============================================================================
# Warmup connection reuse must not serve a stale model/BYOM combination
# =============================================================================


def _prepared(model: str, byom_query: dict[str, str] | None):
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    return VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=object(),
        credential=object(),  # type: ignore[arg-type]
        settings=_StubSettings(),
        model=model,
        byom_query=byom_query,
    )


def test_prepared_connection_rejects_different_model():
    assert _prepared("gpt-realtime", None).matches("my-finetuned-realtime", None) is False


def test_prepared_connection_rejects_different_byom_profile():
    warm = _prepared("gpt-realtime", {"profile": "byom-azure-openai-realtime"})
    assert warm.matches("gpt-realtime", None) is False
    assert warm.matches("gpt-realtime", {"profile": "byom-azure-openai-chat-completion"}) is False
    assert warm.matches("gpt-realtime", {"profile": "byom-azure-openai-realtime"}) is True
