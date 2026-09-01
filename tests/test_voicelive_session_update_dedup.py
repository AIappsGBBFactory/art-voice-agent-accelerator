"""
VoiceLive per-turn ``session.update()`` elimination
===================================================

``_update_session_context()`` used to re-upload the active agent's fully rendered
instructions after *every* assistant turn. For a typical banking agent that blob
is ~24KB, of which over 99% was byte-for-byte identical to the previous turn's —
the only moving part was a prose recap of the conversation that the service
already holds itself.

Two changes make the per-turn push disappear:

1. **Change detection.** The push is gated on a fingerprint of the rendered
   instructions, so an unchanged blob never reaches the wire.
2. **A narrowed recap.** ``_build_conversation_recap()`` no longer re-lists turns
   spoken on this connection, nor the last assistant response — VoiceLive keeps
   those as conversation items server-side (the orchestrator handles
   ``conversation.item.input_audio_transcription.completed``, and the tool path
   relies on that same conversation state for ``FunctionCallOutputItem``). What
   remains is turns restored from a *previous* connection, plus slots collected
   by tools.

   The restored turns are retained as defence in depth rather than necessity:
   ``start()`` -> ``_switch_to()`` -> ``_inject_conversation_history()`` already
   injects them as native conversation items at bootstrap. That injection is
   best-effort and has exactly one call site (it never runs mid-call), and the
   block is frozen for the connection so it costs nothing in steady state.
   Slots are different — nothing re-injects those, and no prompt template
   renders them, so the recap really is their only channel.

The interaction with the ``_pending_context_session_updates`` counter is the
subtle part and the reason this suite exists. That counter tells
``_handle_session_updated`` whether an echo is a cheap context refresh (leave the
turn alone) or a genuine bootstrap (tear down and re-arm audio). A skipped update
produces **no echo**, so crediting the counter on a skip would leave a dangling
credit that the next real bootstrap echo would consume — silently skipping the
audio reset it needs.
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
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stop_playback(self):
        self.calls.append("stop_playback")

    async def start_capture(self):
        self.calls.append("start_capture")

    async def start_playback(self):
        self.calls.append("start_playback")


class _FakeMessenger:
    session_id = "sess-dedup"

    def __init__(self) -> None:
        self.session_updates: list[dict] = []
        self.active_agent: str | None = None

    def set_active_agent(self, name):
        self.active_agent = name

    async def send_session_update(self, **kwargs):
        self.session_updates.append(kwargs)


class _EchoSession:
    def __init__(self) -> None:
        self.id = "sess-echo-1"
        self.voice = None
        self.model = None


def _event():
    return SimpleNamespace(session=_EchoSession())


# =============================================================================
# Fixtures
# =============================================================================


def _make_agent(name: str = "DedupAgent") -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description="session update dedup test agent",
        handoff=HandoffConfig(trigger=f"handoff_{name.lower()}"),
        model=ModelConfig(deployment_id="gpt-realtime"),
        voice=VoiceConfig(name="en-US-AvaMultilingualNeural"),
        prompt_template=f"You are {name}. " + "Filler instruction text. " * 200,
    )


def _make_orchestrator(*, fail_update: bool = False, agents: list[UnifiedAgent] | None = None):
    """Real constructor so the counter and fingerprint init exactly as in prod."""
    agents = agents or [_make_agent()]
    conn = _FakeConnection(fail_update=fail_update)
    audio = _FakeAudio()
    messenger = _FakeMessenger()

    orch = LiveOrchestrator(
        conn=conn,
        agents={a.name: a for a in agents},
        start_agent=agents[0].name,
        audio_processor=audio,
        messenger=messenger,
        model_name="gpt-realtime",
    )
    # Keep _update_session_context() off the scenario/config resolution path.
    orch._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    orch._websocket_for_errors = lambda: None
    return orch, conn, audio, messenger


def _legacy_recap(orch: LiveOrchestrator) -> str:
    """The pre-change recap body, used to model the old per-turn churn."""
    parts: list[str] = []
    if orch._user_message_history:
        parts.append("## CONVERSATION CONTEXT (DO NOT FORGET)")
        for i, msg in enumerate(orch._user_message_history, 1):
            parts.append(f'  {i}. "{msg}"')
    if orch._last_assistant_message:
        parts.append("## YOUR LAST RESPONSE")
        parts.append(f'You last said: "{orch._last_assistant_message}"')
    return "\n".join(parts)


# =============================================================================
# (a) An unchanged context must not reach the wire
# =============================================================================


@pytest.mark.asyncio
async def test_unchanged_context_skips_the_session_update():
    orch, conn, _audio, _messenger = _make_orchestrator()

    await orch._update_session_context()
    assert len(conn.session.updates) == 1, "the first push must happen"

    await orch._update_session_context()
    await orch._update_session_context()

    assert len(conn.session.updates) == 1, "an unchanged blob was re-uploaded"


@pytest.mark.asyncio
async def test_new_user_turns_alone_do_not_trigger_an_update():
    """Turns spoken on this connection are already conversation items."""
    orch, conn, _audio, _messenger = _make_orchestrator()

    await orch._update_session_context()
    assert len(conn.session.updates) == 1

    for text in ("my card is lost", "yes please", "the last four are 4321"):
        orch._user_message_history.append(text)
        orch._last_assistant_message = f"Understood: {text}"
        await orch._update_session_context()

    assert len(conn.session.updates) == 1, "conversation turns churned the instructions"


# =============================================================================
# (b) A skipped update must NOT consume a counter credit
# =============================================================================


@pytest.mark.asyncio
async def test_skipped_update_does_not_increment_the_pending_counter():
    orch, _conn, _audio, _messenger = _make_orchestrator()

    await orch._update_session_context()
    assert orch._pending_context_session_updates == 1

    # Consume the credit with the echo the first push really does produce.
    await orch._handle_session_updated(_event())
    assert orch._pending_context_session_updates == 0

    # Every subsequent no-op refresh must leave the counter alone.
    for _ in range(5):
        await orch._update_session_context()
    assert orch._pending_context_session_updates == 0, "a skipped update credited the counter"


@pytest.mark.asyncio
async def test_skipped_updates_leave_a_later_bootstrap_echo_classified_correctly():
    """The failure this guards: a dangling credit eats a bootstrap's audio reset."""
    orch, conn, audio, messenger = _make_orchestrator()
    orch._active_response_id = "resp-1"

    await orch._update_session_context()
    await orch._handle_session_updated(_event())  # context echo, consumes the credit
    assert audio.calls == []

    # A run of no-op refreshes must not bank credits...
    for _ in range(3):
        await orch._update_session_context()

    # ...so this genuine bootstrap echo still runs the full reset.
    await orch._handle_session_updated(_event())

    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1
    assert len(messenger.session_updates) == 1


# =============================================================================
# (c) A genuinely changed context must still push, exactly once
# =============================================================================


@pytest.mark.asyncio
async def test_changed_slots_push_exactly_once():
    orch, conn, _audio, _messenger = _make_orchestrator()

    await orch._update_session_context()
    baseline = len(conn.session.updates)

    orch._system_vars["slots"] = {"account_last4": "4321"}
    await orch._update_session_context()
    assert len(conn.session.updates) == baseline + 1
    assert orch._pending_context_session_updates == 2

    # Re-rendering the same slots must not push again.
    await orch._update_session_context()
    assert len(conn.session.updates) == baseline + 1
    assert orch._pending_context_session_updates == 2

    assert "account_last4: 4321" in conn.session.updates[-1].instructions


@pytest.mark.asyncio
async def test_restored_history_is_pushed_but_only_once():
    """Restored turns ride along in the instructions, frozen for the connection."""
    orch, conn, _audio, _messenger = _make_orchestrator()
    orch._restored_user_messages = ("I called yesterday about a refund",)

    await orch._update_session_context()
    assert "I called yesterday about a refund" in conn.session.updates[0].instructions

    await orch._update_session_context()
    assert len(conn.session.updates) == 1, "a frozen restored block must not churn"


def test_recap_carries_restored_turns_but_not_live_ones():
    orch, _conn, _audio, _messenger = _make_orchestrator()
    orch._restored_user_messages = ("earlier turn",)
    orch._user_message_history.append("live turn")
    orch._last_assistant_message = "my last reply"

    recap = orch._build_conversation_recap()

    assert "earlier turn" in recap
    assert "live turn" not in recap, "live turns duplicate VoiceLive conversation state"
    assert "my last reply" not in recap, "the last response duplicates conversation state"


# =============================================================================
# (d) An agent switch must still push the full session and bootstrap its echo
# =============================================================================


@pytest.mark.asyncio
async def test_agent_switch_pushes_full_session_and_keeps_bootstrap_semantics():
    first, second = _make_agent("DedupAgent"), _make_agent("SecondAgent")
    orch, conn, audio, messenger = _make_orchestrator(agents=[first, second])
    orch._active_response_id = "resp-1"

    applied: list[str] = []

    async def _apply(_conn, **kwargs):
        applied.append(second.name)

    second.apply_voicelive_session = _apply

    # A context refresh is outstanding when the switch happens.
    await orch._update_session_context()
    assert orch._pending_context_session_updates == 1

    await orch._switch_to(second.name, {})

    assert applied == [second.name], "the switch must apply the full session config"
    assert orch._pending_context_session_updates == 0, "stale credits survived the switch"
    assert orch._last_pushed_instructions is None, "the instruction cache survived the switch"

    # The switch's echo must still be treated as a bootstrap.
    await orch._handle_session_updated(_event())
    assert audio.calls == ["stop_playback", "start_capture"]
    assert conn.response.cancels == 1
    assert len(messenger.session_updates) == 1


@pytest.mark.asyncio
async def test_switch_back_to_the_same_agent_re_pushes_instructions():
    """Cache invalidation must not let a returning agent run on stale state."""
    orch, conn, _audio, _messenger = _make_orchestrator()

    await orch._update_session_context()
    assert len(conn.session.updates) == 1

    orch._last_pushed_instructions = None  # what _switch_to does
    await orch._update_session_context()

    assert len(conn.session.updates) == 2


# =============================================================================
# (e) A rejected push must not poison the cache
# =============================================================================


@pytest.mark.asyncio
async def test_failed_push_is_retried_on_the_next_turn():
    orch, conn, _audio, _messenger = _make_orchestrator(fail_update=True)

    await orch._update_session_context()  # swallowed by the handler's except
    assert orch._pending_context_session_updates == 0
    assert orch._last_pushed_instructions is None, "a failed push was cached"

    conn.session.fail = False
    await orch._update_session_context()

    assert len(conn.session.updates) == 1, "the retry never happened"
    assert orch._pending_context_session_updates == 1


# =============================================================================
# (f) Measured before/after across a 5-turn conversation
# =============================================================================


async def _run_five_turns(orch) -> int:
    """Drive five user/assistant turns, returning the session.update() count."""
    for i in range(5):
        orch._user_message_history.append(f"user turn {i}")
        orch._last_assistant_message = f"assistant turn {i}"
        await orch._update_session_context()
    return len(orch.conn.session.updates)


@pytest.mark.asyncio
async def test_five_turn_conversation_pushes_once_instead_of_every_turn():
    # Before: the legacy recap re-listed every turn, so the blob differed each
    # time and change detection could never short-circuit.
    legacy, _c, _a, _m = _make_orchestrator()
    legacy._build_conversation_recap = lambda: _legacy_recap(legacy)
    before = await _run_five_turns(legacy)

    # After: instructions are constant, so only the first turn reaches the wire.
    current, _c2, _a2, _m2 = _make_orchestrator()
    after = await _run_five_turns(current)

    assert before == 5, "baseline model should push on every turn"
    assert after == 1, f"expected a single push across 5 turns, got {after}"
