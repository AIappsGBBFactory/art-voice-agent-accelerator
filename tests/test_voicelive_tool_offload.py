"""
VoiceLive off-reader tool batching + response-epoch coverage (F12)
==================================================================

The VoiceLive SDK delivers every server event on one ``async for`` stream. A
slow *business* tool must not be awaited on that stream, or later speech / audio
/ interrupt events cannot be intaken until it returns (head-of-line blocking on
the whole call). These tests pin the F12 contract on the real production path
(``handle_event`` → ``_dispatch_tool_call`` → owned task → ``_finalize_tool_batch``):

* A blocked business tool does not stall intake — a barge-in that arrives while
  the tool is still running is processed immediately.
* Exactly one continuation (``response.create``) is emitted per multi-tool batch.
* A continuation superseded by a barge-in or a CANCELLED ``response.done`` is
  dropped rather than restarting speech, while the tool's durable effects and
  ``notify_tool_end`` acknowledgement are preserved.
* The context update precedes the continuation (update-ack before response).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator
from azure.ai.voicelive.models import ResponseStatus, ServerEventType


class DummyVoiceLiveConnection:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.update = AsyncMock()
        self.response = MagicMock()
        self.response.cancel = AsyncMock()
        self.response.create = AsyncMock()
        self.conversation = MagicMock()
        self.conversation.item = MagicMock()
        self.conversation.item.create = AsyncMock()


class DummyAgent:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} agent"


class _BusinessOnlyHandoffService:
    """Every tool is a business tool (never a handoff)."""

    def is_handoff(self, tool_name: str) -> bool:
        return False


def _make_orchestrator() -> tuple[LiveOrchestrator, DummyVoiceLiveConnection]:
    conn = DummyVoiceLiveConnection()
    orch = LiveOrchestrator(
        conn=conn,
        agents={"Concierge": DummyAgent("Concierge")},
        handoff_map={},
        start_agent="Concierge",
        messenger=None,
    )
    orch._handoff_service = _BusinessOnlyHandoffService()
    # Keep the finalizer's context refresh inert and observable.
    orch._update_session_context = AsyncMock()
    return orch, conn


def _fn_args_done(call_id: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        type=ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE,
        call_id=call_id,
        name=name,
        arguments=json.dumps(args),
    )


def _response_done(response_id: str, status: ResponseStatus) -> SimpleNamespace:
    return SimpleNamespace(
        type=ServerEventType.RESPONSE_DONE,
        response=SimpleNamespace(id=response_id, status=status, usage=None),
    )


def _speech_started() -> SimpleNamespace:
    return SimpleNamespace(type=ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED)


async def _drain(orch: LiveOrchestrator) -> None:
    for _ in range(100):
        pending = [t for t in list(orch._owned_tasks) if not t.done()]
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_blocked_business_tool_does_not_stall_intake():
    """A barge-in is intaken while a business tool is still blocked."""
    orch, conn = _make_orchestrator()
    gate = asyncio.Event()

    async def _blocking_tool(name, args):
        await gate.wait()
        return {"ok": True}

    with patch(
        "apps.artagent.backend.voice.voicelive.orchestrator.execute_tool",
        new=AsyncMock(side_effect=_blocking_tool),
    ):
        # Tool call is dispatched to an owned task and returns immediately.
        await orch.handle_event(_fn_args_done("call-1", "lookup_account", {"id": 1}))
        assert len(orch._tool_batches) == 1
        assert len(next(iter(orch._tool_batches.values())).tasks) == 1
        await asyncio.sleep(0)  # let the task start and block on the gate

        # response.done schedules the finalizer (which now awaits the blocked tool).
        await orch.handle_event(_response_done("r1", ResponseStatus.COMPLETED))
        assert not orch._tool_batches

        # The reader is still responsive: a barge-in is processed even though the
        # tool has not released. This is the head-of-line-blocking fix.
        epoch_before = orch._response_epoch
        await orch.handle_event(_speech_started())
        assert orch._response_epoch == epoch_before + 1

        # Release the tool and let the finalizer run.
        gate.set()
        await _drain(orch)

    # Continuation was superseded by the barge-in → dropped, no response.create.
    conn.response.create.assert_not_called()


@pytest.mark.asyncio
async def test_multi_tool_batch_emits_exactly_one_continuation():
    """Two business tools in one response → one response.create, ordered after update."""
    orch, conn = _make_orchestrator()
    order: list[str] = []
    conn.response.create.side_effect = lambda *a, **k: order.append("create")
    orch._update_session_context.side_effect = lambda *a, **k: order.append("update")

    with patch(
        "apps.artagent.backend.voice.voicelive.orchestrator.execute_tool",
        new=AsyncMock(return_value={"ok": True}),
    ):
        await orch.handle_event(_fn_args_done("call-1", "lookup_account", {"id": 1}))
        await orch.handle_event(_fn_args_done("call-2", "lookup_balance", {"id": 1}))
        assert len(next(iter(orch._tool_batches.values())).tasks) == 2
        await orch.handle_event(_response_done("r1", ResponseStatus.COMPLETED))
        await _drain(orch)

    assert conn.response.create.call_count == 1
    assert conn.conversation.item.create.call_count == 2
    # Context update precedes the continuation (update-ack before response).
    assert order.count("create") == 1
    assert order[-1] == "create"
    assert "update" in order[:-1]


@pytest.mark.asyncio
async def test_cancelled_response_done_drops_continuation():
    """A CANCELLED response.done bumps the epoch so the continuation is dropped."""
    orch, conn = _make_orchestrator()

    execute = AsyncMock(return_value={"ok": True})
    with patch("apps.artagent.backend.voice.voicelive.orchestrator.execute_tool", new=execute):
        await orch.handle_event(_fn_args_done("call-1", "lookup_account", {"id": 1}))
        await orch.handle_event(_response_done("r1", ResponseStatus.CANCELLED))
        await _drain(orch)

    # Durable effect ran, but no spoken continuation for a cancelled response.
    execute.assert_awaited_once()
    conn.response.create.assert_not_called()


@pytest.mark.asyncio
async def test_late_tool_completion_after_interrupt_is_dropped_but_effect_preserved():
    """Old tool finishing after a barge-in: durable effect + notify kept, speech not restarted."""
    orch, conn = _make_orchestrator()
    messenger = MagicMock()
    messenger.notify_tool_start = AsyncMock()
    messenger.notify_tool_end = AsyncMock()
    messenger.advance_turn_for_tool = MagicMock()
    orch.messenger = messenger

    gate = asyncio.Event()
    durable: list[str] = []

    async def _slow_tool(name, args):
        await gate.wait()
        durable.append(name)
        return {"ok": True}

    with patch(
        "apps.artagent.backend.voice.voicelive.orchestrator.execute_tool",
        new=AsyncMock(side_effect=_slow_tool),
    ):
        await orch.handle_event(_fn_args_done("call-1", "charge_card", {"amt": 10}))
        await asyncio.sleep(0)
        await orch.handle_event(_response_done("r1", ResponseStatus.COMPLETED))
        # User interrupts before the tool releases.
        await orch.handle_event(_speech_started())
        gate.set()
        await _drain(orch)

    assert durable == ["charge_card"]  # side effect completed
    messenger.notify_tool_end.assert_awaited()  # acknowledgement preserved
    conn.response.create.assert_not_called()  # stale continuation dropped


@pytest.mark.asyncio
async def test_happy_path_single_business_tool_continues():
    """No interruption → the batch finalizer emits the continuation."""
    orch, conn = _make_orchestrator()
    with patch(
        "apps.artagent.backend.voice.voicelive.orchestrator.execute_tool",
        new=AsyncMock(return_value={"ok": True}),
    ):
        await orch.handle_event(_fn_args_done("call-1", "lookup_account", {"id": 1}))
        await orch.handle_event(_response_done("r1", ResponseStatus.COMPLETED))
        await _drain(orch)

    conn.response.create.assert_called_once()
    conn.conversation.item.create.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_and_join_tasks_tears_down_inflight_tool():
    """Owned tool tasks in flight are cancelled and joined during teardown."""
    orch, _ = _make_orchestrator()
    gate = asyncio.Event()

    async def _never_returns(name, args):
        await gate.wait()
        return {"ok": True}

    with patch(
        "apps.artagent.backend.voice.voicelive.orchestrator.execute_tool",
        new=AsyncMock(side_effect=_never_returns),
    ):
        await orch.handle_event(_fn_args_done("call-1", "lookup_account", {"id": 1}))
        await asyncio.sleep(0)
        assert orch._owned_tasks  # a task is genuinely in flight

        await orch.cancel_and_join_tasks()

    assert orch._owned_tasks == set()
    assert not orch._tool_batches
