"""
VoiceLive ``session.updated`` echo classification
=================================================

``_update_session_context()`` re-renders the active agent's prompt after every
assistant turn and pushes it back with ``session.update(instructions=...)``. The
service echoes that back as a ``session.updated`` server event roughly 200ms
later — i.e. while the TTS audio for the turn that just finished is still
draining.

``_handle_session_updated`` used to treat *every* echo as a fresh agent
bootstrap, which on each conversational turn:

  * emitted a ``send_session_update`` envelope (UI spammed with SESSION UPDATED),
  * called ``audio.stop_playback()``, cutting the agent off mid-sentence,
  * called ``conn.response.cancel()`` — and with no response in flight VoiceLive
    answers ``response_cancel_not_active``, which the error path escalates to
    StopAudio + a UI error, breaking the *next* turn.

These tests pin the correlation between a context-only ``session.update`` and
its echo, and the ``_active_response_id`` guard around ``response.cancel()``.
"""

from __future__ import annotations

from types import SimpleNamespace

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
    def __init__(self, *, fail: bool = False) -> None:
        self.updates: list = []
        self.fail = fail

    async def update(self, session=None, **_kwargs):
        if self.fail:
            raise RuntimeError("session.update rejected by service")
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
    def __init__(self, *, fail_update: bool = False) -> None:
        self.session = _FakeSessionNamespace(fail=fail_update)
        self.response = _FakeResponseNamespace()


class _FakeAudio:
    """Records the playback/capture lifecycle calls the handler makes."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stop_playback(self):
        self.calls.append("stop_playback")

    async def start_capture(self):
        self.calls.append("start_capture")

    async def start_playback(self):
        self.calls.append("start_playback")


class _FakeMessenger:
    session_id = "sess-echo"

    def __init__(self) -> None:
        self.session_updates: list[dict] = []

    def set_active_agent(self, name):
        self.active_agent = name

    async def send_session_update(self, **kwargs):
        self.session_updates.append(kwargs)


class _EchoSession:
    """Stand-in for the ``session`` object on a ``session.updated`` event."""

    def __init__(self, voice=None, model: str | None = None) -> None:
        self.id = "sess-echo-1"
        self.voice = voice
        self.model = model


def _event(session=None):
    return SimpleNamespace(session=session or _EchoSession())


# =============================================================================
# Fixtures
# =============================================================================


def _make_agent(name: str = "EchoAgent") -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description="session.updated echo test agent",
        handoff=HandoffConfig(trigger=f"handoff_{name.lower()}"),
        model=ModelConfig(deployment_id="gpt-realtime"),
        voice=VoiceConfig(name="en-US-AvaMultilingualNeural"),
        prompt_template="You are a test agent.",
    )


def _make_orchestrator(*, fail_update: bool = False):
    """Real constructor so the echo counter is initialized exactly as in prod."""
    agent = _make_agent()
    conn = _FakeConnection(fail_update=fail_update)
    audio = _FakeAudio()
    messenger = _FakeMessenger()

    orch = LiveOrchestrator(
        conn=conn,
        agents={agent.name: agent},
        start_agent=agent.name,
        audio_processor=audio,
        messenger=messenger,
        model_name="gpt-realtime",
    )
    # Keep _update_session_context() off the scenario/config resolution path.
    orch._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    orch._websocket_for_errors = lambda: None
    return orch, conn, audio, messenger


# =============================================================================
# Context-only echoes must not disturb the turn
# =============================================================================


@pytest.mark.asyncio
async def test_context_only_echo_leaves_audio_and_ui_alone():
    """The regression this suite exists for: a per-turn refresh is not a bootstrap."""
    orch, conn, audio, messenger = _make_orchestrator()
    orch._active_response_id = "resp-1"  # audio still draining

    await orch._update_session_context()
    assert conn.session.updates, "context update never reached the wire"
    assert orch._pending_context_session_updates == 1

    await orch._handle_session_updated(_event())

    assert audio.calls == [], "context-only echo tore down audio"
    assert conn.response.cancels == 0, "context-only echo cancelled a live response"
    assert messenger.session_updates == [], "context-only echo spammed the UI"
    assert orch._pending_context_session_updates == 0, "credit was not consumed"


@pytest.mark.asyncio
async def test_context_only_echo_still_verifies_the_session_contract():
    """Telemetry must survive the early return — a substitution still matters."""
    orch, _conn, _audio, _messenger = _make_orchestrator()
    seen: list = []
    orch._verify_session_contract = lambda session_obj: seen.append(session_obj)

    await orch._update_session_context()
    session = _EchoSession(voice="en-US-AvaMultilingualNeural")
    await orch._handle_session_updated(_event(session))

    assert seen == [session]


@pytest.mark.asyncio
async def test_context_only_echo_preserves_pending_greeting_and_handoff_flags():
    orch, conn, _audio, _messenger = _make_orchestrator()
    orch._pending_greeting = "Hello there"
    orch._pending_greeting_agent = orch.active
    orch._handoff_response_pending = True

    await orch._update_session_context()
    await orch._handle_session_updated(_event())

    assert orch._pending_greeting == "Hello there"
    assert orch._handoff_response_pending is True
    assert conn.response.creates == 0


@pytest.mark.asyncio
async def test_each_concurrent_context_update_suppresses_one_echo():
    """A bool would collapse these two; the counter must not."""
    orch, _conn, audio, messenger = _make_orchestrator()

    await orch._update_session_context()
    await orch._update_session_context()
    assert orch._pending_context_session_updates == 2

    await orch._handle_session_updated(_event())
    await orch._handle_session_updated(_event())

    assert audio.calls == []
    assert messenger.session_updates == []
    assert orch._pending_context_session_updates == 0


# =============================================================================
# Bootstrap echoes must still fully re-arm the session
# =============================================================================


@pytest.mark.asyncio
async def test_bootstrap_echo_runs_full_reset_and_emits_envelope():
    orch, conn, audio, messenger = _make_orchestrator()
    orch._active_response_id = "resp-1"

    await orch._handle_session_updated(_event())

    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1
    assert len(messenger.session_updates) == 1
    assert messenger.session_updates[0]["agent_name"] == orch.active


@pytest.mark.asyncio
async def test_bootstrap_echo_after_credits_are_dropped_by_an_agent_apply():
    """An agent switch clears stale credits so its echo is never misread."""
    orch, conn, audio, messenger = _make_orchestrator()
    orch._active_response_id = "resp-1"

    await orch._update_session_context()
    assert orch._pending_context_session_updates == 1

    # What _switch_to()/_schedule_scenario_session_update() do before applying.
    orch._pending_context_session_updates = 0
    await orch._handle_session_updated(_event())

    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1
    assert len(messenger.session_updates) == 1


@pytest.mark.asyncio
async def test_bootstrap_echo_keeps_handoff_pending_shortcut():
    orch, conn, audio, messenger = _make_orchestrator()
    orch._handoff_response_pending = True

    await orch._handle_session_updated(_event())

    assert orch._handoff_response_pending is False
    assert audio.calls == ["start_capture"], "handoff response must not be torn down"
    assert conn.response.cancels == 0
    assert len(messenger.session_updates) == 1


@pytest.mark.asyncio
async def test_bootstrap_echo_triggers_pending_greeting():
    orch, conn, _audio, _messenger = _make_orchestrator()
    orch._pending_greeting = "Hi, how can I help?"
    orch._pending_greeting_agent = orch.active

    said: list = []

    async def _trigger(_conn, say=None, **_kwargs):
        said.append(say)

    orch.agents[orch.active].trigger_voicelive_response = _trigger

    await orch._handle_session_updated(_event())

    assert said == ["Hi, how can I help?"]
    assert orch._pending_greeting is None


# =============================================================================
# response.cancel() guard
# =============================================================================


@pytest.mark.asyncio
async def test_cancel_is_skipped_when_no_response_is_active():
    """Cancelling with nothing in flight yields response_cancel_not_active."""
    orch, conn, audio, _messenger = _make_orchestrator()
    orch._active_response_id = None

    await orch._handle_session_updated(_event())

    assert conn.response.cancels == 0
    # The rest of the bootstrap reset still runs.
    assert audio.calls == ["stop_playback", "start_capture"]


@pytest.mark.asyncio
async def test_cancel_is_issued_when_a_response_is_active():
    orch, conn, _audio, _messenger = _make_orchestrator()
    orch._active_response_id = "resp-42"

    await orch._handle_session_updated(_event())

    assert conn.response.cancels == 1


# =============================================================================
# Counter hygiene
# =============================================================================


@pytest.mark.asyncio
async def test_failed_context_update_does_not_leak_a_credit():
    """No echo is coming for a rejected update, so the credit must be returned."""
    orch, conn, audio, messenger = _make_orchestrator(fail_update=True)
    orch._active_response_id = "resp-1"

    await orch._update_session_context()  # swallowed by the handler's except

    assert orch._pending_context_session_updates == 0

    # The next echo is therefore correctly treated as a bootstrap.
    await orch._handle_session_updated(_event())
    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1
    assert len(messenger.session_updates) == 1
