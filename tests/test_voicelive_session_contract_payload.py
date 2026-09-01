"""
Voice Live session contract → UI payload
========================================

``verify_voicelive_session_contract()`` has always known whether the live
session is the one that was configured, but the answer never left the log. The
production incident this pins down was only diagnosable by cross-reading App
Insights:

    Session agent found (Agent Builder) | name=Concierge voice=en-US-EmmaMultilingualNeural
    model_resolved | agent=Concierge model=gpt-4o-mini source=agent_override
    [Orchestrator] Starting with agent: BankingConcierge        <-- different agent
    [Agent Switch] Agent 'BankingConcierge' requests voicelive_model='gpt-realtime'
                   but the VoiceLive connection is bound to 'gpt-4o-mini'
    [BankingConcierge] voice_requested | name=en-US-AlloyTurboMultilingualNeural

From the caller's seat that looked like "I picked a different voice and only the
default persisted". These tests assert the UI-facing payload now *says so*:

  * the contract rides the bootstrap / agent-switch ``session_updated`` envelope,
  * a context-only echo still emits **no** envelope (the per-turn UI spam that
    was deliberately removed must not come back through this door),
  * a genuine voice substitution, an agent restored from a previous connection,
    and an ignored per-agent ``voicelive_model`` each report a mismatch,
  * a deployment-tier echo (``gpt-realtime`` → ``gpt-realtime-datazone-standard``)
    stays a match, so the panel does not cry wolf on every call.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator


# =============================================================================
# Fakes
# =============================================================================


class _FakeSessionNamespace:
    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def update(self, session=None, **_kwargs):
        self.updates.append(session)


class _FakeResponseNamespace:
    def __init__(self) -> None:
        self.cancels = 0
        self.creates = 0

    async def cancel(self):
        self.cancels += 1

    async def create(self, **_kwargs):
        self.creates += 1


class _FakeConnection:
    def __init__(self) -> None:
        self.session = _FakeSessionNamespace()
        self.response = _FakeResponseNamespace()


class _FakeAudio:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stop_playback(self):
        self.calls.append("stop_playback")

    async def start_capture(self):
        self.calls.append("start_capture")

    async def start_playback(self):
        self.calls.append("start_playback")


class _FakeMessenger:
    session_id = "sess-contract-payload"

    def __init__(self) -> None:
        self.session_updates: list[dict[str, Any]] = []

    def set_active_agent(self, name):  # pragma: no cover - trivial
        self.active_agent = name

    async def send_session_update(self, **kwargs):
        self.session_updates.append(kwargs)


class _EchoSession:
    """Stand-in for the ``session`` object on a ``session.updated`` event."""

    def __init__(self, *, voice: Any = None, model: str | None = None) -> None:
        self.id = "sess-echo-1"
        self.voice = voice
        self.model = model


def _event(session: _EchoSession) -> SimpleNamespace:
    return SimpleNamespace(session=session)


# =============================================================================
# Fixtures
# =============================================================================


def _make_agent(
    name: str,
    *,
    voice_name: str = "en-US-EmmaMultilingualNeural",
    voicelive_model: str | None = None,
) -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description=f"{name} contract payload test agent",
        handoff=HandoffConfig(trigger=f"handoff_{name.lower()}"),
        model=ModelConfig(deployment_id="gpt-4o-mini"),
        voicelive_model=(ModelConfig(deployment_id=voicelive_model) if voicelive_model else None),
        voice=VoiceConfig(name=voice_name),
        prompt_template=f"You are {name}.",
    )


def _make_orchestrator(
    agents: list[UnifiedAgent],
    *,
    start_agent: str | None = None,
    model_name: str = "gpt-4o-mini",
) -> tuple[LiveOrchestrator, _FakeConnection, _FakeAudio, _FakeMessenger]:
    conn = _FakeConnection()
    audio = _FakeAudio()
    messenger = _FakeMessenger()

    orch = LiveOrchestrator(
        conn=conn,
        agents={a.name: a for a in agents},
        start_agent=start_agent or agents[0].name,
        audio_processor=audio,
        messenger=messenger,
        model_name=model_name,
    )
    orch._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    orch._websocket_for_errors = lambda: None
    return orch, conn, audio, messenger


def _contract_of(messenger: _FakeMessenger) -> dict[str, Any]:
    assert messenger.session_updates, "no session_updated envelope was emitted"
    contract = messenger.session_updates[-1].get("contract")
    assert contract is not None, "the envelope carried no contract"
    return contract


# =============================================================================
# The contract reaches the UI
# =============================================================================


@pytest.mark.asyncio
async def test_bootstrap_echo_carries_the_contract():
    agent = _make_agent("Concierge")
    orch, _conn, _audio, messenger = _make_orchestrator([agent])

    await orch._handle_session_updated(
        _event(_EchoSession(voice=agent.build_voicelive_voice(), model="gpt-4o-mini"))
    )

    contract = _contract_of(messenger)
    assert contract["overall_ok"] is True
    assert contract["voice_ok"] is True
    assert contract["model_ok"] is True
    assert contract["active_agent"] == "Concierge"
    assert contract["bound_agent"] == "Concierge"
    assert contract["connection_model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_context_only_echo_still_emits_no_envelope():
    """The per-turn UI spam must not come back through the contract."""
    agent = _make_agent("Concierge")
    orch, _conn, _audio, messenger = _make_orchestrator([agent])
    orch._pending_context_session_updates = 1

    await orch._handle_session_updated(
        _event(_EchoSession(voice=agent.build_voicelive_voice(), model="gpt-4o-mini"))
    )

    assert messenger.session_updates == []


# =============================================================================
# Mismatches are visible
# =============================================================================


@pytest.mark.asyncio
async def test_service_substituted_voice_is_reported_as_a_mismatch():
    """Requested Emma, the service echoes Alloy — the payload must say so."""
    agent = _make_agent("Concierge", voice_name="en-US-EmmaMultilingualNeural")
    orch, _conn, _audio, messenger = _make_orchestrator([agent])

    await orch._handle_session_updated(
        _event(_EchoSession(voice="en-US-AlloyTurboMultilingualNeural", model="gpt-4o-mini"))
    )

    contract = _contract_of(messenger)
    assert contract["voice_requested"] == "en-us-emmamultilingualneural"
    assert contract["voice_applied"] == "en-us-alloyturbomultilingualneural"
    assert contract["voice_ok"] is False
    assert contract["ok"] is False
    assert contract["overall_ok"] is False


@pytest.mark.asyncio
async def test_agent_restored_from_a_previous_connection_is_reported():
    """The production split-brain: bound for Concierge, BankingConcierge is live."""
    tuned = _make_agent("Concierge", voice_name="en-US-EmmaMultilingualNeural")
    restored = _make_agent("BankingConcierge", voice_name="en-US-AlloyTurboMultilingualNeural")
    orch, _conn, _audio, messenger = _make_orchestrator([tuned, restored], start_agent="Concierge")

    # What `_sync_from_memo_manager()` does when an earlier connection on the
    # same session_id persisted a different active agent.
    orch.active = "BankingConcierge"

    await orch._handle_session_updated(
        _event(
            _EchoSession(
                voice=restored.build_voicelive_voice(),
                model="gpt-4o-mini",
            )
        )
    )

    contract = _contract_of(messenger)
    # The service honored what we asked for — we simply asked as the wrong agent.
    assert contract["ok"] is True
    assert contract["bound_agent"] == "Concierge"
    assert contract["active_agent"] == "BankingConcierge"
    assert contract["agent_ok"] is False
    assert contract["overall_ok"] is False
    # `voice_ok` cannot express the loss (the service applied exactly the voice
    # we sent), so the displaced voice has to be named explicitly or the UI
    # shows a reassuring "voice MATCH" while the caller hears Alloy.
    assert contract["voice_ok"] is True
    assert contract["tuned_voice"] == "en-us-emmamultilingualneural"


@pytest.mark.asyncio
async def test_tuned_voice_is_absent_when_the_agent_did_not_drift():
    """No drift means nothing was displaced; the key must not invent a loss."""
    agent = _make_agent("Concierge")
    orch, _conn, _audio, messenger = _make_orchestrator([agent])

    await orch._handle_session_updated(
        _event(_EchoSession(voice=agent.build_voicelive_voice(), model="gpt-4o-mini"))
    )

    assert _contract_of(messenger)["tuned_voice"] is None


@pytest.mark.asyncio
async def test_ignored_per_agent_model_override_is_reported():
    """VoiceLive binds the model at connect(); an agent's ask is silently dropped."""
    agent = _make_agent("BankingConcierge", voicelive_model="gpt-realtime")
    orch, _conn, _audio, messenger = _make_orchestrator([agent], model_name="gpt-4o-mini")

    await orch._handle_session_updated(
        _event(_EchoSession(voice=agent.build_voicelive_voice(), model="gpt-4o-mini"))
    )

    contract = _contract_of(messenger)
    assert contract["agent_requested_model"] == "gpt-realtime"
    assert contract["connection_model"] == "gpt-4o-mini"
    assert contract["model_override_ignored"] is True
    assert contract["overall_ok"] is False


# =============================================================================
# The benign case must not cry wolf
# =============================================================================


@pytest.mark.asyncio
async def test_deployment_tier_echo_stays_a_match():
    """``gpt-realtime`` vs ``gpt-realtime-datazone-standard`` is one model."""
    agent = _make_agent("Concierge", voicelive_model="gpt-realtime")
    orch, _conn, _audio, messenger = _make_orchestrator([agent], model_name="gpt-realtime")

    await orch._handle_session_updated(
        _event(
            _EchoSession(
                voice=agent.build_voicelive_voice(),
                model="gpt-realtime-datazone-standard",
            )
        )
    )

    contract = _contract_of(messenger)
    assert contract["model_ok"] is True
    assert contract["model_applied_sku"] == "datazone-standard"
    assert contract["model_override_ignored"] is False
    assert contract["overall_ok"] is True


@pytest.mark.asyncio
async def test_unverifiable_echo_is_not_treated_as_a_mismatch():
    """An echo that reports nothing is unknown, not wrong."""
    agent = _make_agent("Concierge")
    orch, _conn, _audio, messenger = _make_orchestrator([agent])

    await orch._handle_session_updated(_event(_EchoSession()))

    contract = _contract_of(messenger)
    assert contract["voice_ok"] is None
    assert contract["model_ok"] is None
    assert contract["overall_ok"] is True


# =============================================================================
# The messenger really puts it on the wire
# =============================================================================


@pytest.mark.asyncio
async def test_session_messenger_places_contract_on_the_envelope(
    monkeypatch: pytest.MonkeyPatch,
):
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler
    from apps.artagent.backend.voice.voicelive.handler import _SessionMessenger

    emitted: list[dict[str, Any]] = []

    async def capture_envelope(_ws, envelope, **_kwargs) -> None:
        emitted.append(envelope)

    monkeypatch.setattr(voicelive_handler, "send_session_envelope", capture_envelope)

    ws = MagicMock()
    ws.state = SimpleNamespace(session_id="session-1", call_connection_id="call-1")

    tasks: list[asyncio.Task] = []

    def background(coro, label):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    messenger = _SessionMessenger(ws, background_task_fn=background)
    await messenger.send_session_update(
        agent_name="BankingConcierge",
        session_obj=_EchoSession(voice="alloy", model="gpt-4o-mini"),
        transport="acs",
        contract={
            "voice_requested": "en-us-emmamultilingualneural",
            "voice_applied": "alloy",
            "voice_ok": False,
            "overall_ok": False,
            "active_agent": "BankingConcierge",
            "bound_agent": "Concierge",
            "agent_ok": False,
        },
    )
    await asyncio.gather(*tasks)

    assert len(emitted) == 1
    payload = emitted[0]["payload"]
    assert payload["event_type"] == "session_updated"
    assert payload["contract"]["overall_ok"] is False
    assert payload["contract"]["bound_agent"] == "Concierge"
    # Envelope identity is untouched, so the UI deduper keeps working.
    assert emitted[0]["id"]


@pytest.mark.asyncio
async def test_session_messenger_omits_contract_when_absent(
    monkeypatch: pytest.MonkeyPatch,
):
    """A contract-less update must not grow an empty key the UI would render."""
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler
    from apps.artagent.backend.voice.voicelive.handler import _SessionMessenger

    emitted: list[dict[str, Any]] = []

    async def capture_envelope(_ws, envelope, **_kwargs) -> None:
        emitted.append(envelope)

    monkeypatch.setattr(voicelive_handler, "send_session_envelope", capture_envelope)

    ws = MagicMock()
    ws.state = SimpleNamespace(session_id="session-1", call_connection_id="call-1")

    tasks: list[asyncio.Task] = []

    def background(coro, label):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    messenger = _SessionMessenger(ws, background_task_fn=background)
    await messenger.send_session_update(
        agent_name="Concierge",
        session_obj=_EchoSession(voice="alloy"),
        transport="acs",
    )
    await asyncio.gather(*tasks)

    assert "contract" not in emitted[0]["payload"]
