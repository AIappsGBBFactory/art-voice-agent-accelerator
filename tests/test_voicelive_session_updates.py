"""VoiceLive context refreshes must not masquerade as agent transitions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.voice.voicelive import handler as handler_module
from apps.artagent.backend.voice.voicelive import session as voicelive_session
from apps.artagent.backend.voice.voicelive.handler import _SessionMessenger
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator


@pytest_asyncio.fixture
async def session_updates(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SimpleNamespace]:
    """Use real orchestration and messaging with mocked network boundaries."""
    tasks = []

    def schedule(coro, label):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    send = AsyncMock()
    monkeypatch.setattr(handler_module, "send_session_envelope", send)
    ws = SimpleNamespace(state=SimpleNamespace(session_id="session-1", call_connection_id="call-1"))
    messenger = _SessionMessenger(ws, background_task_fn=schedule)
    conn = SimpleNamespace(
        session=SimpleNamespace(update=AsyncMock()),
        response=SimpleNamespace(cancel=AsyncMock(), create=AsyncMock()),
        conversation=SimpleNamespace(item=SimpleNamespace(create=AsyncMock())),
    )
    agents = {name: UnifiedAgent(name=name) for name in ("Concierge", "Advisor")}
    for agent in agents.values():
        monkeypatch.setattr(agent, "render_prompt", Mock(return_value="Help the caller."))
    apply_session = AsyncMock()
    trigger_response = AsyncMock()
    monkeypatch.setattr(voicelive_session, "apply_voicelive_session", apply_session)
    monkeypatch.setattr(voicelive_session, "trigger_voicelive_response", trigger_response)
    audio = SimpleNamespace(stop_playback=AsyncMock(), start_capture=AsyncMock())
    orchestrator = LiveOrchestrator(
        conn=conn,
        agents=agents,
        start_agent="Concierge",
        messenger=messenger,
        audio_processor=audio,
    )
    orchestrator._cached_orchestrator_config = SimpleNamespace(scenario=None, scenario_name=None)
    monkeypatch.setattr(orchestrator, "_select_pending_greeting", Mock(return_value=None))
    monkeypatch.setattr(orchestrator, "_verify_session_contract", Mock(return_value=None))
    event = SimpleNamespace(
        session=SimpleNamespace(id="live-1", instructions="Help the caller.", voice=None)
    )
    yield SimpleNamespace(
        orchestrator=orchestrator,
        messenger=messenger,
        conn=conn,
        agents=agents,
        audio=audio,
        event=event,
        send=send,
        tasks=tasks,
        ws=ws,
        apply_session=apply_session,
        trigger_response=trigger_response,
    )
    await asyncio.gather(*tasks)
    await orchestrator.cancel_and_join_tasks()
    orchestrator.cleanup()


@pytest.mark.asyncio
async def test_context_acknowledgements_do_not_repeat_readiness(session_updates) -> None:
    state = session_updates
    orchestrator = state.orchestrator
    orchestrator._pending_greeting = "Hello!"
    orchestrator._pending_greeting_agent = "Concierge"
    orchestrator._active_response_id = "initial-response"

    await orchestrator._handle_session_updated(state.event)
    for turn in range(3):
        orchestrator._system_vars["slots"] = {"turn": turn}
        await orchestrator._update_session_context()
        await orchestrator._handle_session_updated(state.event)
    await asyncio.gather(*state.tasks)

    state.send.assert_awaited_once()
    assert state.send.call_args.args[1]["payload"]["message"] == "Active agent: Concierge"
    state.conn.response.cancel.assert_awaited_once()
    state.audio.stop_playback.assert_awaited_once()
    state.audio.start_capture.assert_awaited_once()
    state.trigger_response.assert_awaited_once_with(
        state.agents["Concierge"], state.conn, say="Hello!", cancel_active=False
    )


@pytest.mark.asyncio
async def test_each_handoff_is_announced_once_including_return_visits(session_updates) -> None:
    state = session_updates
    await state.orchestrator._handle_session_updated(state.event)

    for agent_name in ("Advisor", "Concierge"):
        await state.orchestrator._switch_to(agent_name, {})
        await state.orchestrator._handle_session_updated(state.event)
        await state.orchestrator._update_session_context()
        await state.orchestrator._handle_session_updated(state.event)
    await asyncio.gather(*state.tasks)

    payloads = [call.args[1]["payload"] for call in state.send.call_args_list]
    assert [payload["event_type"] for payload in payloads] == [
        "session_updated",
        "agent_change",
        "agent_change",
    ]
    assert [payload["agent_name"] for payload in payloads] == [
        "Concierge",
        "Advisor",
        "Concierge",
    ]
    state.conn.response.cancel.assert_not_awaited()
    assert state.audio.stop_playback.await_count == 3
    assert state.audio.start_capture.await_count == 3


@pytest.mark.asyncio
async def test_messenger_suppresses_duplicate_announcements_before_serialization(
    session_updates, monkeypatch
) -> None:
    state = session_updates
    serialize = Mock(return_value={})
    monkeypatch.setattr(handler_module, "_serialize_session_config", serialize)

    for agent_name in ("Concierge", "Concierge", "Advisor", "Advisor", "Concierge"):
        state.messenger.set_active_agent(agent_name)
        await state.messenger.send_session_update(
            agent_name=agent_name, session_obj=state.event.session, transport="acs"
        )
    await asyncio.gather(*state.tasks)

    assert state.send.await_count == 3
    serialize.assert_called_once()


@pytest.mark.asyncio
async def test_missing_session_does_not_mark_agent_announced(session_updates) -> None:
    state = session_updates
    state.ws.state.session_id = None
    await state.messenger.send_session_update(
        agent_name="Concierge", session_obj=state.event.session
    )
    state.ws.state.session_id = "session-1"
    await state.messenger.send_session_update(
        agent_name="Concierge", session_obj=state.event.session
    )
    await asyncio.gather(*state.tasks)

    state.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_unchanged_instructions_are_sent_once_even_when_concurrent(session_updates) -> None:
    state = session_updates
    entered = asyncio.Event()
    release = asyncio.Event()

    async def update(**kwargs) -> None:
        entered.set()
        await release.wait()

    state.conn.session.update.side_effect = update
    first = asyncio.create_task(state.orchestrator._update_session_context())
    await asyncio.wait_for(entered.wait(), timeout=1)
    second = asyncio.create_task(state.orchestrator._update_session_context())
    release.set()
    await asyncio.gather(first, second)
    await state.orchestrator._update_session_context()

    state.conn.session.update.assert_awaited_once()
    assert state.conn.session.update.call_args.kwargs["session"].instructions == "Help the caller."


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_context", ["user", "assistant", "slots", "tool_outputs"])
async def test_changed_context_still_updates_instructions(session_updates, changed_context) -> None:
    state = session_updates
    await state.orchestrator._update_session_context()
    if changed_context == "user":
        state.orchestrator._user_message_history.append("My card is missing.")
    elif changed_context == "assistant":
        state.orchestrator._last_assistant_message = "I can help replace your card."
    elif changed_context == "slots":
        state.orchestrator._system_vars["slots"] = {"card_type": "debit"}
    else:
        state.orchestrator._system_vars["tool_outputs"] = {"lookup": "found"}
        state.agents["Concierge"].render_prompt.side_effect = (
            lambda context: f"Help the caller. {context['tool_outputs']}"
        )
    await state.orchestrator._update_session_context()
    await state.orchestrator._update_session_context()

    expected_updates = 1 if changed_context in ("user", "assistant") else 2
    assert state.conn.session.update.await_count == expected_updates
    instructions = [
        call.kwargs["session"].instructions for call in state.conn.session.update.call_args_list
    ]
    if expected_updates == 2:
        assert instructions[0] != instructions[1]


@pytest.mark.asyncio
async def test_failed_instruction_send_can_be_retried(session_updates) -> None:
    state = session_updates
    state.conn.session.update.side_effect = [ConnectionError("disconnected"), None]

    await state.orchestrator._update_session_context()
    await state.orchestrator._update_session_context()
    await state.orchestrator._update_session_context()

    assert state.conn.session.update.await_count == 2


@pytest.mark.asyncio
async def test_full_agent_application_invalidates_instruction_cache(session_updates) -> None:
    state = session_updates
    await state.orchestrator._update_session_context()
    await state.orchestrator._switch_to("Concierge", {})
    await state.orchestrator._update_session_context()

    state.apply_session.assert_awaited_once()
    assert state.conn.session.update.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("target_agent", ["Concierge", "Advisor"])
async def test_scenario_refresh_preserves_config_without_duplicate_announcements(
    session_updates, target_agent: str
) -> None:
    state = session_updates
    await state.orchestrator._handle_session_updated(state.event)
    await state.orchestrator._update_session_context()

    state.orchestrator.update_scenario(
        agents=state.agents,
        handoff_map={},
        start_agent=target_agent,
        scenario_name="updated-scenario",
    )
    await asyncio.gather(*state.orchestrator._owned_tasks)
    await asyncio.gather(*state.tasks)
    await state.orchestrator._handle_session_updated(state.event)
    state.orchestrator._cached_orchestrator_config = SimpleNamespace(
        scenario=None, scenario_name="updated-scenario"
    )
    await state.orchestrator._update_session_context()
    await asyncio.gather(*state.tasks)

    state.apply_session.assert_awaited_once()
    assert state.conn.session.update.await_count == 2
    event_types = [call.args[1]["payload"]["event_type"] for call in state.send.call_args_list]
    assert event_types == (
        ["session_updated"] if target_agent == "Concierge" else ["session_updated", "agent_change"]
    )


@pytest.mark.asyncio
async def test_changed_contract_reaches_ui_without_another_agent_notice(session_updates) -> None:
    state = session_updates
    for agent_name, voice in (
        ("Concierge", "voice-a"),
        ("Advisor", "voice-b"),
        ("Advisor", "voice-c"),
        ("Advisor", "voice-c"),
    ):
        state.messenger.set_active_agent(agent_name)
        await state.messenger.send_session_update(
            agent_name=agent_name,
            session_obj=state.event.session,
            contract={"active_agent": agent_name, "voice_applied": voice},
        )
    await asyncio.gather(*state.tasks)

    payloads = [call.args[1]["payload"] for call in state.send.call_args_list]
    assert [payload["event_type"] for payload in payloads] == [
        "session_updated",
        "agent_change",
        "session_updated",
        "session_updated",
    ]
    updates = [payload for payload in payloads if payload["event_type"] == "session_updated"]
    assert [payload["announce_agent"] for payload in updates] == [True, False, False]
    assert [payload["contract"]["voice_applied"] for payload in updates] == [
        "voice-a",
        "voice-b",
        "voice-c",
    ]


@pytest.mark.asyncio
async def test_superseded_switch_waiting_for_context_send_does_not_apply(session_updates) -> None:
    state = session_updates
    entered = asyncio.Event()
    release = asyncio.Event()

    async def update(**kwargs) -> None:
        entered.set()
        await release.wait()

    state.conn.session.update.side_effect = update
    context = asyncio.create_task(state.orchestrator._update_session_context())
    await asyncio.wait_for(entered.wait(), timeout=1)
    stale_switch = asyncio.create_task(state.orchestrator._switch_to("Advisor", {}))
    await asyncio.sleep(0)
    current_switch = asyncio.create_task(state.orchestrator._switch_to("Concierge", {}))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(context, stale_switch, current_switch)

    state.apply_session.assert_awaited_once()
    assert state.apply_session.call_args.args[0] is state.agents["Concierge"]
