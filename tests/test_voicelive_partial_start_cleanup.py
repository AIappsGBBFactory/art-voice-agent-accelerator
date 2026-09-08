"""
VoiceLive partial-start cleanup coverage (F5)
=============================================

``VoiceLiveSDKHandler.start()`` adopts/opens the VoiceLive connection, registers
the orchestrator, and spawns tasks *before* it flips ``_running = True``. A
failure anywhere in that window used to leak the connection and the orchestrator
registry entry, because ``stop()`` short-circuited on ``not self._running``.

These tests pin the invariant: ``stop()`` unwinds every resource that was
actually acquired, regardless of ``_running``, is idempotent, and still tears a
fully-running session down. They drive the real production ``stop()`` path — the
same method ``start()``'s failure handler invokes — rather than a reimplementation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.artagent.backend.voice.voicelive.handler import VoiceLiveSDKHandler
from apps.artagent.backend.voice.voicelive.orchestrator import (
    get_orchestrator_registry_size,
    get_voicelive_orchestrator,
    register_voicelive_orchestrator,
)
from fastapi.websockets import WebSocketState


class FakeWebSocket:
    """Minimal websocket with app/state surfaces used by stop()."""

    def __init__(self) -> None:
        self.application_state = WebSocketState.CONNECTED
        self.client_state = WebSocketState.CONNECTED
        self.state = SimpleNamespace()
        self.app = SimpleNamespace(state=SimpleNamespace())
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def _make_handler(session_id: str = "sess-partial") -> tuple[VoiceLiveSDKHandler, FakeWebSocket]:
    ws = FakeWebSocket()
    handler = VoiceLiveSDKHandler(websocket=ws, session_id=session_id, transport="acs")
    return handler, ws


def _fake_connection_cm() -> MagicMock:
    cm = MagicMock()
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_stop_unwinds_connection_and_registration_after_partial_start():
    """Connection adopted + orchestrator registered, but _running never set."""
    handler, _ = _make_handler("sess-partial-1")
    cm = _fake_connection_cm()
    handler._connection_cm = cm
    handler._connection = object()

    orch = MagicMock()
    orch.cleanup = MagicMock()
    handler._orchestrator = orch
    register_voicelive_orchestrator(handler.session_id, orch)

    # Precondition: this is the exact partial state start() leaves on failure.
    assert handler._running is False
    assert get_voicelive_orchestrator(handler.session_id) is orch

    await handler.stop()

    # Connection closed exactly once, registry entry gone, orchestrator cleaned.
    cm.__aexit__.assert_awaited_once_with(None, None, None)
    assert handler._connection_cm is None
    assert handler._connection is None
    assert get_voicelive_orchestrator(handler.session_id) is None
    orch.cleanup.assert_called_once()
    assert handler._orchestrator is None
    assert handler._stopping is True


@pytest.mark.asyncio
async def test_stop_closes_unclaimed_prepared_connection():
    """A warm connection start() never adopted must be closed, not leaked."""
    handler, _ = _make_handler("sess-partial-2")
    prepared = MagicMock()
    prepared.close = AsyncMock()
    handler._prepared_connection = prepared

    await handler.stop()

    prepared.close.assert_awaited_once()
    assert handler._prepared_connection is None


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    """A second stop() is a no-op; resources are not double-released."""
    handler, _ = _make_handler("sess-partial-3")
    cm = _fake_connection_cm()
    handler._connection_cm = cm
    handler._connection = object()

    await handler.stop()
    await handler.stop()

    cm.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_running_session_still_tears_down():
    """Regression: the fully-running teardown path is preserved."""
    handler, _ = _make_handler("sess-running")
    cm = _fake_connection_cm()
    handler._connection_cm = cm
    handler._connection = object()
    handler._running = True

    # A live event loop task, as start() would have spawned.
    async def _idle() -> None:
        await asyncio.sleep(3600)

    handler._event_task = asyncio.create_task(_idle())
    await asyncio.sleep(0)

    await handler.stop()

    assert handler._running is False
    assert handler._event_task is None
    cm.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_does_not_leak_registry_entries_across_sessions():
    """Each partial-start session removes exactly its own registry entry."""
    baseline = get_orchestrator_registry_size()
    handler_a, _ = _make_handler("sess-reg-a")
    handler_b, _ = _make_handler("sess-reg-b")
    register_voicelive_orchestrator("sess-reg-a", MagicMock(cleanup=MagicMock()))
    register_voicelive_orchestrator("sess-reg-b", MagicMock(cleanup=MagicMock()))
    handler_a._orchestrator = get_voicelive_orchestrator("sess-reg-a")
    handler_b._orchestrator = get_voicelive_orchestrator("sess-reg-b")

    await handler_a.stop()

    assert get_voicelive_orchestrator("sess-reg-a") is None
    assert get_voicelive_orchestrator("sess-reg-b") is not None

    await handler_b.stop()
    assert get_voicelive_orchestrator("sess-reg-b") is None
    assert get_orchestrator_registry_size() == baseline


@pytest.mark.asyncio
async def test_stop_persists_final_snapshot_after_producers_quiesced():
    """The strict persist snapshot runs only after producers are cancel-joined.

    Storage close contract: stop producers → capture the final strict snapshot →
    (later) flush pending persistence. Persisting while an owned tool finalizer is
    still writing corememory would race the snapshot, so persist must follow
    cancel_and_join_tasks and the event-reader cancel.
    """
    handler, ws = _make_handler("sess-persist-order")
    handler._running = True
    cm = _fake_connection_cm()
    handler._connection_cm = cm
    handler._connection = object()

    order: list[str] = []

    memo_manager = MagicMock()
    memo_manager.persist_to_redis_async = AsyncMock(
        side_effect=lambda *a, **k: order.append("persist")
    )
    ws.state.cm = memo_manager
    ws.app.state.redis = MagicMock()

    orch = MagicMock()
    orch.cleanup = MagicMock()
    orch._sync_to_memo_manager = MagicMock(side_effect=lambda: order.append("sync"))
    orch.cancel_and_join_tasks = AsyncMock(side_effect=lambda *a, **k: order.append("cancel_tasks"))
    handler._orchestrator = orch

    async def _idle() -> None:
        order.append("reader_running")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            order.append("reader_cancelled")
            raise

    handler._event_task = asyncio.create_task(_idle())
    await asyncio.sleep(0)

    await handler.stop()

    # Producers are stopped before the strict snapshot is captured.
    assert order.index("cancel_tasks") < order.index("persist")
    assert order.index("reader_cancelled") < order.index("persist")
    # Orchestrator state is synced into the memo immediately before the barrier.
    assert order.index("sync") < order.index("persist")
    memo_manager.persist_to_redis_async.assert_awaited_once()
