from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _clear_voicelive_credential_cache() -> None:
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler

    voicelive_handler._CACHED_CREDENTIAL = None


def test_shared_credential_helper_treats_local_azd_client_id_as_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils import azure_auth

    captured = {}

    class FakeDefaultAzureCredential:
        def __init__(self, **kwargs):
            captured["default"] = kwargs

    class FakeManagedIdentityCredential:
        def __init__(self, **kwargs):
            captured["managed"] = kwargs

    monkeypatch.setattr(azure_auth, "DefaultAzureCredential", FakeDefaultAzureCredential)
    monkeypatch.setattr(azure_auth, "ManagedIdentityCredential", FakeManagedIdentityCredential)
    monkeypatch.setenv("AZURE_CLIENT_ID", "local-azd-client-id")
    monkeypatch.setenv("ENVIRONMENT", "jinlocal")
    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    monkeypatch.delenv("MSI_ENDPOINT", raising=False)
    monkeypatch.delenv("CONTAINER_APP_NAME", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    azure_auth.get_credential.cache_clear()

    try:
        azure_auth.get_credential()
    finally:
        azure_auth.get_credential.cache_clear()

    assert "managed" not in captured
    assert captured["default"]["exclude_managed_identity_credential"] is True
    assert captured["default"]["exclude_cli_credential"] is False


@pytest.mark.asyncio
async def test_voicelive_credential_skips_managed_identity_in_local_azd_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler
    from apps.artagent.backend.voice.voicelive.handler import VoiceLiveSDKHandler

    captured = {}

    class FakeDefaultAzureCredential:
        def __init__(self, **kwargs):
            captured["default"] = kwargs

    class FakeManagedIdentityCredential:
        def __init__(self, **kwargs):
            captured["managed"] = kwargs

    monkeypatch.setattr(
        voicelive_handler,
        "DefaultAzureCredential",
        FakeDefaultAzureCredential,
    )
    monkeypatch.setattr(
        voicelive_handler,
        "ManagedIdentityCredential",
        FakeManagedIdentityCredential,
    )
    monkeypatch.setenv("AZURE_CLIENT_ID", "local-azd-client-id")
    monkeypatch.setenv("ENVIRONMENT", "jinlocal")
    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    monkeypatch.delenv("MSI_ENDPOINT", raising=False)
    monkeypatch.delenv("CONTAINER_APP_NAME", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    _clear_voicelive_credential_cache()

    try:
        credential = await VoiceLiveSDKHandler._build_credential(
            SimpleNamespace(has_api_key_auth=False, azure_client_id="local-azd-client-id")
        )
    finally:
        _clear_voicelive_credential_cache()

    assert isinstance(credential, FakeDefaultAzureCredential)
    assert "managed" not in captured
    assert captured["default"]["exclude_managed_identity_credential"] is True
    assert captured["default"]["exclude_cli_credential"] is False


@pytest.mark.asyncio
async def test_voicelive_credential_uses_managed_identity_when_hosted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler
    from apps.artagent.backend.voice.voicelive.handler import VoiceLiveSDKHandler

    captured = {}

    class FakeDefaultAzureCredential:
        def __init__(self, **kwargs):
            captured["default"] = kwargs

    class FakeManagedIdentityCredential:
        def __init__(self, **kwargs):
            captured["managed"] = kwargs

    monkeypatch.setattr(
        voicelive_handler,
        "DefaultAzureCredential",
        FakeDefaultAzureCredential,
    )
    monkeypatch.setattr(
        voicelive_handler,
        "ManagedIdentityCredential",
        FakeManagedIdentityCredential,
    )
    monkeypatch.setenv("AZURE_CLIENT_ID", "hosted-client-id")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    _clear_voicelive_credential_cache()

    try:
        credential = await VoiceLiveSDKHandler._build_credential(
            SimpleNamespace(has_api_key_auth=False, azure_client_id="hosted-client-id")
        )
    finally:
        _clear_voicelive_credential_cache()

    assert isinstance(credential, FakeManagedIdentityCredential)
    assert captured["managed"] == {"client_id": "hosted-client-id"}
    assert "default" not in captured


@pytest.mark.asyncio
async def test_prepared_connection_matches_and_closes() -> None:
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    cm = MagicMock()
    cm.__aexit__ = AsyncMock()
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=cm,
        credential=object(),
        settings=object(),
        model="gpt-realtime",
        byom_query={"profile": "byom-azure-openai-realtime"},
    )

    assert prepared.matches("gpt-realtime", {"profile": "byom-azure-openai-realtime"})
    assert not prepared.matches("gpt-4o", {"profile": "byom-azure-openai-realtime"})
    assert not prepared.matches("gpt-realtime", None)

    await prepared.close()
    cm.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.asyncio
async def test_claimed_prepared_connection_is_not_closed_by_helper() -> None:
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    cm = MagicMock()
    cm.__aexit__ = AsyncMock()
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=cm,
        credential=object(),
        settings=object(),
        model="gpt-realtime",
    )

    prepared.claim()
    await prepared.close()

    cm.__aexit__.assert_not_called()


@pytest.mark.asyncio
async def test_start_and_consume_voicelive_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    app_state = SimpleNamespace()
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=MagicMock(),
        credential=object(),
        settings=object(),
        model="gpt-realtime",
    )

    async def fake_prepare(**kwargs):
        assert kwargs["call_connection_id"] == "call-123"
        assert kwargs["session_id"] == "session-123"
        assert kwargs["scenario_name"] == "retail"
        return prepared

    monkeypatch.setattr(voicelive_handler, "_prepare_voicelive_call_warmup", fake_prepare)

    voicelive_handler.start_voicelive_call_warmup(
        app_state,
        call_connection_id="call-123",
        session_id="session-123",
        scenario_name="retail",
    )

    consumed = await voicelive_handler.consume_voicelive_call_warmup(
        app_state,
        call_connection_id="call-123",
        cleanup_tasks=set(),
        timeout_sec=1.0,
    )

    assert consumed is prepared
    assert app_state.voicelive_warmups == {}


@pytest.mark.asyncio
async def test_consume_voicelive_warmup_timeout_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    app_state = SimpleNamespace()
    cm = MagicMock()
    cm.__aexit__ = AsyncMock()
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=cm,
        credential=object(),
        settings=object(),
        model="gpt-realtime",
    )
    release_event = asyncio.Event()

    async def fake_prepare(**kwargs):
        await release_event.wait()
        return prepared

    monkeypatch.setattr(voicelive_handler, "_prepare_voicelive_call_warmup", fake_prepare)

    voicelive_handler.start_voicelive_call_warmup(
        app_state,
        call_connection_id="call-456",
        session_id="session-456",
    )

    cleanup_tasks = set()
    consumed = await voicelive_handler.consume_voicelive_call_warmup(
        app_state,
        call_connection_id="call-456",
        cleanup_tasks=cleanup_tasks,
        timeout_sec=0.001,
    )

    assert consumed is None
    assert len(cleanup_tasks) == 1

    release_event.set()
    await asyncio.gather(*cleanup_tasks)
    cm.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.asyncio
async def test_named_scenario_start_matches_warmup_and_ignores_unrelated_session_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.registries.agentstore.base import (
        ModelConfig,
        UnifiedAgent,
        VoiceLiveBYOMConfig,
    )
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig
    from apps.artagent.backend.src.orchestration import session_memory
    from apps.artagent.backend.voice.shared.config_resolver import OrchestratorConfigResult
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler

    entry = UnifiedAgent(
        name="ScenarioEntry",
        voicelive_model=ModelConfig(deployment_id="my-text-deployment"),
        byom=VoiceLiveBYOMConfig(mode="byom-azure-openai-chat-completion"),
    )
    outside = UnifiedAgent(name="UnrelatedEditedAgent")
    registry = {entry.name: entry, outside.name: outside}
    config = OrchestratorConfigResult(
        start_agent="scenarioentry",
        agents={entry.name: entry},
        scenario=ScenarioConfig(name="Named scenario", start_agent=entry.name, agents=[entry.name]),
        scenario_name="Named scenario",
    )
    monkeypatch.setattr(session_memory, "prime_session_definitions", AsyncMock())
    monkeypatch.setattr(voicelive_handler, "resolve_orchestrator_config", lambda **kwargs: config)
    monkeypatch.setattr(voicelive_handler, "get_session_agent", lambda *args: outside)
    settings = SimpleNamespace(azure_voicelive_model="gpt-realtime", start_agent=outside.name)

    warm_agents, warm_start, model, query, _ = (
        await voicelive_handler._resolve_voicelive_warmup_config(
            app_state=SimpleNamespace(unified_agents=registry),
            session_id="named-start",
            scenario_name="Named scenario",
            settings=settings,
            user_email=None,
        )
    )
    cold_agents, session_agent, cold_start = voicelive_handler._select_voicelive_agents(
        registry,
        config,
        session_id="named-start",
        configured_start_agent=settings.start_agent,
    )

    assert cold_start == warm_start == entry.name
    assert model == entry.voicelive_model.deployment_id
    assert query == {"profile": "byom-azure-openai-chat-completion"}
    assert cold_agents == warm_agents == {entry.name: entry}
    assert session_agent is None
    assert registry[outside.name] is outside


@pytest.mark.asyncio
async def test_warmup_uses_the_same_byom_conflict_recovery_as_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.registries.agentstore.base import (
        ModelConfig,
        UnifiedAgent,
        VoiceLiveBYOMConfig,
    )
    from apps.artagent.backend.src.orchestration import session_memory
    from apps.artagent.backend.voice.shared.config_resolver import OrchestratorConfigResult
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler

    agent = UnifiedAgent(
        name="Start",
        voicelive_model=ModelConfig(deployment_id="gpt-realtime"),
        byom=VoiceLiveBYOMConfig(mode="byom-azure-openai-chat-completion"),
    )
    monkeypatch.setattr(session_memory, "prime_session_definitions", AsyncMock())
    monkeypatch.setattr(
        voicelive_handler,
        "resolve_orchestrator_config",
        lambda **kwargs: OrchestratorConfigResult(start_agent=agent.name),
    )
    monkeypatch.setattr(voicelive_handler, "get_session_agent", lambda *args: None)
    _, _, model, query, _ = await voicelive_handler._resolve_voicelive_warmup_config(
        app_state=SimpleNamespace(unified_agents={agent.name: agent}),
        session_id="profile-recovery",
        scenario_name=None,
        settings=SimpleNamespace(azure_voicelive_model="gpt-4.1", start_agent=agent.name),
        user_email=None,
    )

    assert model == "gpt-realtime"
    assert query is None
    assert (
        voicelive_handler._resolve_voicelive_byom_query(agent, model, session_id="profile-recovery")
        is None
    )
    assert agent.byom.mode == "byom-azure-openai-chat-completion"
