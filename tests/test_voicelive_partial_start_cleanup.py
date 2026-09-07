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
