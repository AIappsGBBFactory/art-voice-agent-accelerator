"""Handoff ownership at real SDK await and acknowledgement boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.artagent.backend.voice.shared.handoff_service import HandoffResolution
from apps.artagent.backend.voice.voicelive import session
from azure.ai.voicelive.models import ResponseStatus, ServerEventType

from tests.test_handoff_orchestrator_states import _make_voicelive_orchestrator
from tests.test_voicelive_tool_offload import _drain, _fn_args_done, _response_done


def handoff_runtime(monkeypatch):
    resolution = HandoffResolution(
        success=True,
        target_agent="Advisor",
        source_agent="Concierge",
        tool_name="handoff_to_agent",
        system_vars={"handoff_context": {"question": "Help"}, "greet_on_switch": True},
        greet_on_switch=True,
        handoff_type="announced",
    )
    orch, conn = _make_voicelive_orchestrator(resolution)
    orch._handoff_service._greeting = "Hello from Advisor"
    orch.messenger = MagicMock()
    for method in ("notify_tool_start", "notify_tool_end", "send_session_update"):
        setattr(orch.messenger, method, AsyncMock())
    orch.messenger.session_id = "handoff-awaits"
    orch.audio = SimpleNamespace(stop_playback=AsyncMock(), start_capture=AsyncMock())
    conn.send = AsyncMock()
    execute = AsyncMock(return_value={"success": True, "receipt": "committed"})
    monkeypatch.setattr("apps.artagent.backend.voice.voicelive.orchestrator.execute_tool", execute)
    monkeypatch.setattr(session, "apply_voicelive_session", AsyncMock())
    monkeypatch.setattr(orch, "_schedule_scenario_session_update", lambda: None)
    monkeypatch.setattr(orch, "_verify_session_contract", lambda value: {})
    return orch, conn, execute


async def dispatch_handoff(orch, call_id="handoff", *, tool_name="handoff_to_agent"):
    before = set(orch._owned_tasks)
    response_id = orch._active_response_id or call_id
    event = _fn_args_done(call_id, tool_name, {})
    event.response_id = response_id
    await orch.handle_event(event)
    await orch.handle_event(_response_done(response_id, ResponseStatus.COMPLETED))
    return set(orch._owned_tasks) - before


async def session_ack(orch):
    await orch.handle_event(
        SimpleNamespace(
            type=ServerEventType.SESSION_UPDATED,
            session=SimpleNamespace(id="session", model=None, voice=None),
        )
    )


def replace_scenario(orch):
    service = orch._handoff_service
    orch.update_scenario(
        orch.agents, {"handoff_to_agent": "Advisor"}, start_agent="Concierge", scenario_name="new"
    )
    orch._handoff_service = service


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["session", "history", "response"])
async def test_announced_handoff_ack_during_history_has_one_response(boundary, monkeypatch):
    orch, conn, execute = handoff_runtime(monkeypatch)
    orch._user_message_history.append("Original question")
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(*args, **kwargs):
        entered.set()
        await release.wait()

    if boundary == "session":
        monkeypatch.setattr(session, "apply_voicelive_session", hold)
    elif boundary == "history":
        conn.conversation.item.create.side_effect = hold
    else:
        conn.response.create.side_effect = hold
    try:
        await dispatch_handoff(orch)
        await asyncio.wait_for(entered.wait(), 1)
        await session_ack(orch)
        await session_ack(orch)
        release.set()
        await _drain(orch)
        assert conn.send.await_count + conn.response.create.await_count == 1
        conn.response.create.assert_awaited_once()
        execute.assert_awaited_once()
    finally:
        release.set()
        await _drain(orch)
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_handoff", [False, True])
async def test_suspended_ack_cannot_consume_replacement_transition(old_handoff, monkeypatch):
    orch, conn, _ = handoff_runtime(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    if old_handoff:
        await asyncio.gather(*(await dispatch_handoff(orch, "old")))

    async def hold(**kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()

    orch.messenger.send_session_update.side_effect = hold
    ack = asyncio.create_task(session_ack(orch))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        replace_scenario(orch)
        await asyncio.gather(*(await dispatch_handoff(orch, "new")))
        await orch.handle_event(
            SimpleNamespace(
                type=ServerEventType.RESPONSE_CREATED, response=SimpleNamespace(id="replacement")
            )
        )
        cancels = conn.response.cancel.await_count
        stops = orch.audio.stop_playback.await_count
        release.set()
        await ack
        await session_ack(orch)
        assert conn.response.cancel.await_count == cancels
        assert orch.audio.stop_playback.await_count == stops
    finally:
        release.set()
        await ack
        await _drain(orch)
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["session", "response", "rejected", "tool"])
async def test_current_transition_failure_reports_outcome_once_and_releases_protection(
    failure, monkeypatch
):
    orch, conn, execute = handoff_runtime(monkeypatch)
    if failure == "session":
        monkeypatch.setattr(
            session, "apply_voicelive_session", AsyncMock(side_effect=RuntimeError("apply failed"))
        )
    elif failure == "response":
        conn.response.create.side_effect = RuntimeError("response rejected")
    else:
        orch._handoff_service._resolution.success = False
        orch._handoff_service._resolution.error = "route rejected"
        if failure == "tool":
            execute.side_effect = RuntimeError("execution failed")
    try:
        await dispatch_handoff(orch)
        await _drain(orch)
        execute.assert_awaited_once()
        orch.messenger.notify_tool_start.assert_awaited_once()
        orch.messenger.notify_tool_end.assert_awaited_once()
        completed = orch.messenger.notify_tool_end.call_args.kwargs
        assert completed["status"] == ("error" if failure == "tool" else "success")
        if failure != "tool":
            assert completed["result"]["receipt"] == "committed"
        assert (
            completed["result"]["handoff_transition"]["status"]
            == {
                "session": "failed",
                "response": "response_failed",
                "rejected": "rejected",
                "tool": "rejected",
            }[failure]
        )
        orch._active_response_id = "unrelated"
        cancels = conn.response.cancel.await_count
        await session_ack(orch)
        assert conn.response.cancel.await_count == cancels + 1
    finally:
        await _drain(orch)
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("effect_before_suspend", [False, True])
@pytest.mark.parametrize("notification_failure", [None, "error", "cancel"])
@pytest.mark.parametrize(
    "tool_name", ["handoff_to_agent", "lookup", "transfer_call_to_destination"]
)
async def test_close_during_invocation_reports_unknown_and_propagates_cancellation(
    effect_before_suspend, notification_failure, tool_name, monkeypatch
):
    from apps.artagent.backend.voice.voicelive.tool_helpers import _derive_tool_status

    orch, conn, execute = handoff_runtime(monkeypatch)
    monkeypatch.setattr(
        orch._handoff_service, "is_handoff", lambda name: name == "handoff_to_agent"
    )
    entered = asyncio.Event()
    effects = []
    executing = []

    async def hold(*args, **kwargs):
        executing.append(asyncio.current_task())
        if effect_before_suspend:
            effects.append("effect already performed")
        entered.set()
        await asyncio.Event().wait()

    execute.side_effect = hold
    if notification_failure == "error":
        orch.messenger.notify_tool_end.side_effect = RuntimeError("notification unavailable")
    elif notification_failure == "cancel":
        orch.messenger.notify_tool_end.side_effect = asyncio.CancelledError(
            "notification cancelled"
        )
    tasks = await dispatch_handoff(orch, tool_name=tool_name)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await orch.cancel_and_join_tasks()
        finalizer = executing[0]
        assert finalizer in tasks
        assert finalizer.cancelled()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await finalizer
        assert cancelled.value.args == ()
        execute.assert_awaited_once()
        orch.messenger.notify_tool_start.assert_awaited_once()
        orch.messenger.notify_tool_end.assert_awaited_once()
        terminal = orch.messenger.notify_tool_end.call_args.kwargs
        assert terminal["status"] == "cancelled"
        assert terminal["result"]["outcome"] == "unknown"
        assert terminal["result"].get("success") is not True
        assert _derive_tool_status(terminal["result"]) != "success"
        assert "effects may have occurred" in terminal["error"].lower()
        assert "do not retry automatically" in terminal["error"].lower()
        if tool_name == "handoff_to_agent":
            assert terminal["result"]["handoff_transition"]["status"] == "superseded"
        assert effects == (["effect already performed"] if effect_before_suspend else [])
        assert orch.active == "Concierge"
        assert orch._handoff_transition is None
        conn.response.create.assert_not_awaited()
        conn.response.cancel.assert_not_awaited()
        conn.conversation.item.create.assert_not_awaited()
    finally:
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
async def test_notification_failure_preserves_settled_execution_error(monkeypatch):
    orch, _, execute = handoff_runtime(monkeypatch)
    execute.side_effect = RuntimeError("original execution error")
    orch.messenger.notify_tool_end.side_effect = RuntimeError("notification unavailable")
    orch._handoff_service._resolution.success = False
    orch._handoff_service._resolution.error = "route rejected"
    try:
        tasks = await dispatch_handoff(orch)
        await asyncio.gather(*tasks)
        execute.assert_awaited_once()
        orch.messenger.notify_tool_end.assert_awaited_once()
        terminal = orch.messenger.notify_tool_end.call_args.kwargs
        assert terminal["status"] == "error"
        assert terminal["result"]["error"] == "original execution error"
        assert terminal["error"] == "original execution error"
        assert not any(task.cancelled() for task in tasks)
    finally:
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_fails", [False, True])
async def test_close_during_handoff_application_preserves_executed_completion(
    notification_fails, monkeypatch
):
    orch, conn, execute = handoff_runtime(monkeypatch)
    entered = asyncio.Event()

    async def hold(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "apply_voicelive_session", hold)
    if notification_fails:
        orch.messenger.notify_tool_end.side_effect = RuntimeError("notification unavailable")
    await dispatch_handoff(orch)
    await asyncio.wait_for(entered.wait(), 1)
    await orch.cancel_and_join_tasks()
    execute.assert_awaited_once()
    orch.messenger.notify_tool_start.assert_awaited_once()
    orch.messenger.notify_tool_end.assert_awaited_once()
    completed = orch.messenger.notify_tool_end.call_args.kwargs
    assert completed["status"] == "success"
    assert completed["result"]["receipt"] == "committed"
    assert completed["result"]["handoff_transition"]["status"] == "superseded"
    conn.response.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_fails", [False, True])
async def test_old_response_failure_cannot_remove_new_handoff_ack_protection(
    old_fails, monkeypatch
):
    orch, conn, _ = handoff_runtime(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def create(**kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()
            if old_fails:
                raise RuntimeError("old response rejected")

    conn.response.create.side_effect = create
    try:
        await dispatch_handoff(orch, "old")
        await asyncio.wait_for(entered.wait(), 1)
        replace_scenario(orch)
        new_tasks = await dispatch_handoff(orch, "new")
        await asyncio.gather(*new_tasks)
        await orch.handle_event(
            SimpleNamespace(
                type=ServerEventType.RESPONSE_CREATED,
                response=SimpleNamespace(id="new-response"),
            )
        )
        release.set()
        await _drain(orch)
        cancels = conn.response.cancel.await_count
        stops = orch.audio.stop_playback.await_count
        await session_ack(orch)
        assert conn.response.cancel.await_count == cancels
        assert orch.audio.stop_playback.await_count == stops
        assert orch.active == "Advisor"
    finally:
        release.set()
        await _drain(orch)
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("replace", [False, True])
async def test_replay_stops_submitting_snapshot_after_replacement(replace, monkeypatch):
    orch, conn, _ = handoff_runtime(monkeypatch)
    orch._user_message_history.extend(["old first", "old second"])
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []

    async def hold(*, item):
        sent.extend(part.text for part in item.content)
        if not entered.is_set():
            entered.set()
            await release.wait()

    conn.conversation.item.create.side_effect = hold
    try:
        await dispatch_handoff(orch)
        await asyncio.wait_for(entered.wait(), 1)
        if replace:
            replace_scenario(orch)
        else:
            orch._user_message_history.append("late user message")
        orch._last_assistant_message = "replacement assistant"
        release.set()
        await _drain(orch)
        assert sent == (["old first"] if replace else ["old first", "old second"])
        assert conn.response.create.await_count == (0 if replace else 1)
    finally:
        release.set()
        await _drain(orch)
        await orch.cancel_and_join_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary", ["tool", "cancel", "playback", "session", "history", "question", "response"]
)
async def test_executed_handoff_always_notifies_once_when_route_superseded(boundary, monkeypatch):
    orch, conn, execute = handoff_runtime(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"success": True, "receipt": "committed"}

    if boundary == "tool":
        execute.side_effect = hold
    elif boundary == "cancel":
        conn.response.cancel.side_effect = hold
    elif boundary == "playback":
        orch.audio.stop_playback.side_effect = hold
    elif boundary == "session":
        monkeypatch.setattr(session, "apply_voicelive_session", hold)
    elif boundary in ("history", "question"):
        if boundary == "history":
            orch._user_message_history.append("original question")
        else:
            orch._handoff_service._resolution.system_vars["greet_on_switch"] = False
        conn.conversation.item.create.side_effect = hold
    else:
        conn.response.create.side_effect = hold
    try:
        await dispatch_handoff(orch)
        await asyncio.wait_for(entered.wait(), 1)
        replace_scenario(orch)
        release.set()
        await _drain(orch)
        execute.assert_awaited_once()
        orch.messenger.notify_tool_start.assert_awaited_once()
        orch.messenger.notify_tool_end.assert_awaited_once()
        completed = orch.messenger.notify_tool_end.call_args.kwargs
        assert completed["status"] == "success"
        assert completed["result"]["receipt"] == "committed"
        assert completed["result"]["handoff_transition"]["status"] == "superseded"
        assert orch.active == "Concierge"
        assert conn.response.create.await_count == (1 if boundary == "response" else 0)
    finally:
        release.set()
        await _drain(orch)
        await orch.cancel_and_join_tasks()
