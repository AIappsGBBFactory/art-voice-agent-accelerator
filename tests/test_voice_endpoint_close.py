"""Outer channel teardown must not turn native close failures into success."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apps.artagent.backend.api.v1.endpoints.genesys import _cleanup_genesys_websocket
from apps.artagent.backend.api.v1.endpoints.media import _cleanup_websocket_resources
from fastapi.websockets import WebSocketState
from src.pools.session_manager import ThreadSafeSessionManager
from src.stateful.state_managment import MemoManager


async def endpoint(kind, stop):
    manager = ThreadSafeSessionManager()
    app = SimpleNamespace(
        session_manager=manager,
        conn_manager=SimpleNamespace(unregister=AsyncMock()),
        session_metrics=SimpleNamespace(increment_disconnected=AsyncMock()),
    )
    ws = SimpleNamespace(
        state=SimpleNamespace(conn_id="connection"),
        app=SimpleNamespace(state=app),
        client_state=WebSocketState.CONNECTED,
        application_state=WebSocketState.CONNECTED,
        close=AsyncMock(),
    )
    await manager.add_session("endpoint", MemoManager(session_id="endpoint"), ws)
    handler = SimpleNamespace(session_id="endpoint", stop=stop)

    def close():
        if kind == "media":
            return _cleanup_websocket_resources(ws, handler, "call", "endpoint")
        return _cleanup_genesys_websocket(ws, handler)

    return ws, app, close


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["media", "genesys"])
async def test_endpoint_reports_all_failures_after_safe_cleanup(kind):
    native_error, socket_error = RuntimeError("native stop failed"), RuntimeError("socket failed")
    stop = AsyncMock(side_effect=native_error)
    ws, app, close = await endpoint(kind, stop)
    ws.close.side_effect = socket_error
    with pytest.raises(ExceptionGroup) as first:
        await close()
    assert first.value.exceptions == (native_error, socket_error)
    assert await app.session_manager.get_session_count() == 0
    if kind == "media":
        app.conn_manager.unregister.assert_awaited_once_with("connection")
        app.session_metrics.increment_disconnected.assert_awaited_once()
    with pytest.raises(ExceptionGroup) as repeated:
        await close()
    assert repeated.value is first.value
    stop.assert_awaited_once()
    ws.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["media", "genesys"])
async def test_endpoint_cleanup_survives_cancelled_and_concurrent_callers(kind):
    entered, release = asyncio.Event(), asyncio.Event()

    async def stop_handler():
        entered.set()
        await release.wait()

    stop = AsyncMock(side_effect=stop_handler)
    ws, app, close = await endpoint(kind, stop)
    first = asyncio.create_task(close())
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(close())
    await asyncio.sleep(0)
    assert not second.done()
    ws.close.assert_not_awaited()
    release.set()
    await asyncio.wait_for(second, 1)
    await close()
    stop.assert_awaited_once()
    ws.close.assert_awaited_once()
    assert await app.session_manager.get_session_count() == 0
