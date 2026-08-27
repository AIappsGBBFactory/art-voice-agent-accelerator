"""
VoiceLive opening-greeting delivery race
========================================

On a cold-start VoiceLive session two mechanisms can deliver the agent's opening
greeting:

  1. the ``session.updated`` bootstrap echo handled by ``_handle_session_updated``,
  2. the timer scheduled by ``_schedule_greeting_fallback``.

They used to race and the loser was destroyed. ``_switch_to()`` scheduled the
fallback at 0.35s, but the bootstrap echo for the very same
``apply_voicelive_session()`` only lands ~550-600ms later (observed on
production calls). So the fallback always won, and the echo that arrived ~200ms
afterwards was classified as a bootstrap and ran ``audio.stop_playback()`` +
``conn.response.cancel()``. Because a greeting response genuinely *was* in
flight, ``_active_response_id`` was set and the existing guard did not stop the
cancel — every call opened with a greeting cut off mid-word
("Hi, welcome to Contoso Bank. I'm BankingConc").

These tests pin both halves of the fix:

  * ``_greeting_response_pending`` — the echo must never tear down a greeting the
    fallback deliberately put on the wire,
  * ``GREETING_FALLBACK_DELAY_S`` — the echo is the reliable trigger, so the
    timer must sit above the echo latency instead of pre-empting it.

and the invariants that must survive it: the handoff shortcut, and a genuine
agent-switch echo still performing its audio reset.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest

from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.voice.voicelive import orchestrator as orchestrator_module
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator

# Worst observed latency between apply_voicelive_session() returning and its
# `session.updated` echo arriving, from two independent production calls:
# 06.896 -> 07.450 (554ms) and 00.252 -> 00.835 (583ms).
OBSERVED_ECHO_LATENCY_S = 0.6


# =============================================================================
# Fakes
# =============================================================================


class _FakeResponseNamespace:
    def __init__(self) -> None:
        self.cancels = 0
        self.creates = 0

    async def cancel(self):
        self.cancels += 1

    async def create(self, **_kwargs):
        self.creates += 1


class _FakeSessionNamespace:
    def __init__(self) -> None:
        self.updates: list = []

    async def update(self, session=None, **_kwargs):
        self.updates.append(session)


class _FakeConnection:
    def __init__(self) -> None:
        self.session = _FakeSessionNamespace()
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
    session_id = "sess-greeting"

    def __init__(self) -> None:
        self.session_updates: list[dict] = []

    def set_active_agent(self, name):
        self.active_agent = name

    async def send_session_update(self, **kwargs):
        self.session_updates.append(kwargs)


class _EchoSession:
    def __init__(self) -> None:
        self.id = "sess-greeting-1"
        self.voice = None
        self.model = None


def _event():
    return SimpleNamespace(session=_EchoSession())


# =============================================================================
# Fixtures
# =============================================================================


def _make_agent(name: str = "BankingConcierge") -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description="greeting race test agent",
        handoff=HandoffConfig(trigger=f"handoff_{name.lower()}"),
        model=ModelConfig(deployment_id="gpt-realtime"),
        voice=VoiceConfig(name="en-US-AvaMultilingualNeural"),
        prompt_template="You are a test agent.",
    )


def _make_orchestrator():
    """Real constructor so every guard is initialized exactly as in prod."""
    agent = _make_agent()
    conn = _FakeConnection()
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
    orch._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    orch._websocket_for_errors = lambda: None
    return orch, conn, audio, messenger


def _arm_greeting(orch, greeting: str = "Hi, welcome to Contoso Bank. I'm BankingConcierge."):
    """Reproduce the state `_switch_to()` leaves behind before it schedules."""
    orch._pending_greeting = greeting
    orch._pending_greeting_agent = orch.active
    # A genuine bootstrap: the apply site drops any context-only credits.
    orch._pending_context_session_updates = 0
    return greeting


def _record_triggers(orch, *, fail: bool = False) -> list[str | None]:
    said: list[str | None] = []

    async def _trigger(_conn, say=None, **_kwargs):
        said.append(say)
        if fail:
            raise RuntimeError("trigger_voicelive_response rejected")
        # Whatever mechanism wins, a response is now genuinely in flight.
        orch._active_response_id = f"resp-{len(said)}"

    orch.agents[orch.active].trigger_voicelive_response = _trigger
    return said


async def _drain_greeting_tasks(orch) -> None:
    tasks = list(orch._greeting_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def fast_fallback(monkeypatch):
    """Shrink the timer so the ordering under test runs in milliseconds."""
    monkeypatch.setattr(orchestrator_module, "GREETING_FALLBACK_DELAY_S", 0.01)


# =============================================================================
# (a) Fallback wins the race — the arriving echo must not truncate the greeting
# =============================================================================


@pytest.mark.asyncio
async def test_echo_after_fallback_does_not_cancel_the_greeting(fast_fallback):
    """The exact production failure: greeting on the wire, then the echo lands."""
    orch, conn, audio, _messenger = _make_orchestrator()
    greeting = _arm_greeting(orch)
    said = _record_triggers(orch)

    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)

    assert said == [greeting], "fallback never delivered the greeting"
    assert orch._greeting_response_pending is True, "fallback did not claim the guard"
    assert orch._active_response_id, "precondition: a greeting response is in flight"

    audio.calls.clear()
    await orch._handle_session_updated(_event())

    assert conn.response.cancels == 0, "bootstrap echo cancelled the greeting mid-generation"
    assert "stop_playback" not in audio.calls, "bootstrap echo tore down greeting playback"
    assert audio.calls == ["start_capture"], "capture must still be re-armed"
    assert said == [greeting], "greeting must be delivered exactly once"
    assert orch._greeting_response_pending is False, "guard must be consumed exactly once"


@pytest.mark.asyncio
async def test_guard_is_consumed_so_a_later_bootstrap_still_resets(fast_fallback):
    """The guard is one-shot: the *next* genuine bootstrap must not be skipped."""
    orch, conn, audio, _messenger = _make_orchestrator()
    _arm_greeting(orch)
    _record_triggers(orch)

    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)

    await orch._handle_session_updated(_event())  # greeting echo, skipped
    audio.calls.clear()
    await orch._handle_session_updated(_event())  # a real later bootstrap

    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1


@pytest.mark.asyncio
async def test_switching_agents_clears_a_stale_greeting_guard(fast_fallback):
    """`_switch_to()` cancels greeting delivery, so the guard must not survive it."""
    orch, conn, audio, _messenger = _make_orchestrator()
    _arm_greeting(orch)
    _record_triggers(orch)

    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)
    assert orch._greeting_response_pending is True

    # What _switch_to() / the handoff branch / cleanup() all do first.
    orch._cancel_pending_greeting_tasks()
    assert orch._greeting_response_pending is False

    audio.calls.clear()
    await orch._handle_session_updated(_event())

    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1


@pytest.mark.asyncio
async def test_failed_fallback_trigger_releases_the_guard(fast_fallback):
    """No response reached the service, so the next echo must reset audio."""
    orch, conn, audio, _messenger = _make_orchestrator()
    _arm_greeting(orch)
    said = _record_triggers(orch, fail=True)

    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)

    assert said, "fallback should have attempted delivery"
    assert orch._greeting_response_pending is False, "guard leaked after a failed trigger"

    orch._active_response_id = "resp-unrelated"
    await orch._handle_session_updated(_event())
    assert audio.calls[:1] == ["stop_playback"]
    assert conn.response.cancels == 1


# =============================================================================
# (b) Echo wins the race — the fallback must not fire a duplicate response
# =============================================================================


@pytest.mark.asyncio
async def test_echo_before_fallback_greets_exactly_once(monkeypatch):
    """Echo at ~0.6s, fallback armed above it: one greeting, one response."""
    monkeypatch.setattr(orchestrator_module, "GREETING_FALLBACK_DELAY_S", 0.05)
    orch, conn, audio, _messenger = _make_orchestrator()
    greeting = _arm_greeting(orch)
    said = _record_triggers(orch)

    orch._schedule_greeting_fallback(orch.active)
    await asyncio.sleep(0)  # let the fallback task reach its sleep
    await orch._handle_session_updated(_event())

    assert said == [greeting], "echo path did not deliver the greeting"
    assert orch._pending_greeting is None
    assert audio.calls == ["stop_playback", "start_capture"], "cold-start echo must reset audio"
    assert conn.response.cancels == 0, "nothing was in flight when the echo arrived"

    # Whatever is left of the timer must not produce a second response
    # ("Conversation already has an active response").
    with suppress(asyncio.CancelledError):
        await _drain_greeting_tasks(orch)
    await asyncio.sleep(0.08)
    assert said == [greeting], "fallback fired a duplicate greeting response"


@pytest.mark.asyncio
async def test_fallback_is_a_noop_once_the_echo_has_greeted(fast_fallback):
    """Even if the timer survives cancellation it must find nothing to do."""
    orch, _conn, _audio, _messenger = _make_orchestrator()
    greeting = _arm_greeting(orch)
    said = _record_triggers(orch)

    await orch._handle_session_updated(_event())
    assert said == [greeting]

    # Re-arm the timer explicitly, bypassing the cancellation the echo performed.
    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)

    assert said == [greeting]
    assert orch._greeting_response_pending is False


# =============================================================================
# (c) The handoff path must be untouched
# =============================================================================


@pytest.mark.asyncio
async def test_handoff_response_pending_still_skips_the_reset():
    orch, conn, audio, messenger = _make_orchestrator()
    orch._handoff_response_pending = True
    orch._active_response_id = "resp-handoff"

    await orch._handle_session_updated(_event())

    assert orch._handoff_response_pending is False
    assert audio.calls == ["start_capture"], "handoff response must not be torn down"
    assert conn.response.cancels == 0
    assert len(messenger.session_updates) == 1


@pytest.mark.asyncio
async def test_handoff_branch_clears_greeting_state_and_guard(fast_fallback):
    """The handoff owns delivery; the greeting guard must hand over cleanly."""
    orch, _conn, _audio, _messenger = _make_orchestrator()
    _arm_greeting(orch)
    _record_triggers(orch)

    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)
    assert orch._greeting_response_pending is True

    # The sequence _execute_tool_call() runs before conn.response.create().
    orch._cancel_pending_greeting_tasks()
    orch._pending_greeting = None
    orch._pending_greeting_agent = None
    orch._handoff_response_pending = True

    assert orch._greeting_response_pending is False, "stale greeting guard would mask the handoff"

    await orch._handle_session_updated(_event())
    assert orch._handoff_response_pending is False


# =============================================================================
# (d) A genuine agent-switch echo still re-arms the session
# =============================================================================


@pytest.mark.asyncio
async def test_agent_switch_echo_without_a_greeting_still_resets_audio():
    orch, conn, audio, messenger = _make_orchestrator()
    orch._active_response_id = "resp-outgoing-agent"

    await orch._handle_session_updated(_event())

    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1
    assert len(messenger.session_updates) == 1


# =============================================================================
# Timer sizing
# =============================================================================


def test_fallback_delay_sits_above_the_observed_echo_latency():
    """A "fallback" that always wins is not a fallback — it is the primary path.

    Below the echo latency the timer greets against a session the service has
    not acknowledged yet, and the echo then races the half-spoken greeting.
    """
    assert orchestrator_module.GREETING_FALLBACK_DELAY_S > OBSERVED_ECHO_LATENCY_S


@pytest.mark.asyncio
async def test_greeting_is_still_delivered_when_no_echo_ever_arrives(fast_fallback):
    """The timer's real job: cover a session.updated echo that never lands."""
    orch, _conn, _audio, _messenger = _make_orchestrator()
    greeting = _arm_greeting(orch)
    said = _record_triggers(orch)

    orch._schedule_greeting_fallback(orch.active)
    await _drain_greeting_tasks(orch)

    assert said == [greeting]
    assert orch._pending_greeting is None
