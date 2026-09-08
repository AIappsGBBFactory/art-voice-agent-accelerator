"""Browser teardown continues after real speech-stop and producer-join failures."""

import asyncio
import threading
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apps.artagent.backend.api.v1.endpoints import browser
from apps.artagent.backend.src.orchestration import unified
from apps.artagent.backend.voice.tts import playback as playback_module
from src.enums.stream_modes import StreamMode

from tests.test_cascade_runtime_ownership import Synth, app_state, make_handler
from tests.test_cascade_stop_acknowledgement import PendingStop, production_recognizer


def exception_leaves(error):
    if isinstance(error, ExceptionGroup):
        for child in error.exceptions:
            yield from exception_leaves(child)
    else:
        yield error


async def attach_browser_resources(app, monkeypatch):
    handler = await make_handler(app)
    ws = handler.websocket
    ws.app = SimpleNamespace(state=app)
    ws.close = AsyncMock(wraps=ws.close)
    session_id = handler.session_id
    connections = {"conn": ws}
    sessions = {session_id: handler.memory_manager}

    async def unregister(conn_id):
        del connections[conn_id]

    async def remove_session(key, *, expected_context):
        assert expected_context is ws.state.session_context
        del sessions[key]

    app.conn_manager = SimpleNamespace(unregister=AsyncMock(side_effect=unregister))
    app.session_manager = SimpleNamespace(remove_session=AsyncMock(side_effect=remove_session))
    ws.state.session_context = SimpleNamespace(session_id=session_id)
    app.session_metrics = SimpleNamespace(increment_disconnected=AsyncMock())
    app.cosmos = SimpleNamespace(upsert_document=Mock())
    handler.memory_manager.histories = {}
    handler.memory_manager.context = {}
    monkeypatch.setitem(
        unified._adapters, session_id, SimpleNamespace(memo_manager=handler.memory_manager)
    )
    return handler, connections, sessions


async def cleanup(handler):
    await browser._cleanup_conversation(
        handler.websocket,
        handler.session_id,
        handler,
        handler.memory_manager,
        "conn",
        StreamMode.MEDIA,
    )


def assert_safe_cleanup(handler, connections, sessions):
    app = handler.websocket.app.state
    assert handler.session_id not in unified._adapters
    assert not connections
    assert not sessions
    app.conn_manager.unregister.assert_awaited_once_with("conn")
    app.session_manager.remove_session.assert_awaited_once_with(
        handler.session_id, expected_context=handler.websocket.state.session_context
    )
    app.session_metrics.increment_disconnected.assert_awaited_once()
    handler.websocket.close.assert_awaited_once()
    app.cosmos.upsert_document.assert_called_once()
    assert handler.websocket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_browser_cleanup_finishes_safe_stages_after_native_stop_failure(monkeypatch, timeout):
    future = PendingStop(error=RuntimeError("native stop rejected"))
    app = app_state(stt=production_recognizer(future))
    handler, connections, sessions = await attach_browser_resources(app, monkeypatch)
    handler._stt_thread.stop_async = partial(
        handler._stt_thread.stop_async, timeout_sec=0.03 if timeout else 1
    )
    if not timeout:
        future.acknowledged.set()

    try:
        # Real handler.stop -> SpeechSDKThread -> production recognizer.stop -> SDK get.
        # VoiceHandler.run may already have failed shutdown before endpoint cleanup.
        with pytest.raises(ExceptionGroup) as shutdown:
            await handler.stop()
        results = await asyncio.gather(cleanup(handler), cleanup(handler), return_exceptions=True)
        assert all(isinstance(result, ExceptionGroup) for result in results)
        assert results[0] is results[1]
        assert results[0].exceptions[0] is shutdown.value
        errors = list(exception_leaves(results[0]))
        if timeout:
            assert any(isinstance(error, TimeoutError) for error in errors)
        else:
            assert future.error in errors
        assert_safe_cleanup(handler, connections, sessions)
        assert future.entered.is_set()
        assert future.get_calls == 1
        assert app.stt_pool.released == app.tts_pool.released == 0

        # Retrying neither swallows the cached quiescence error nor repeats safe effects.
        with pytest.raises(ExceptionGroup) as repeated:
            await cleanup(handler)
        assert repeated.value is results[0]
        with pytest.raises(ExceptionGroup, match="could not be quiesced"):
            await handler.stop()
        assert_safe_cleanup(handler, connections, sessions)
    finally:
        future.acknowledged.set()
        await asyncio.gather(handler._stt_thread._stop_task, return_exceptions=True)
    assert app.stt_pool.released == 0


@pytest.mark.asyncio
async def test_browser_cleanup_finishes_safe_stages_after_real_producer_join_timeout(monkeypatch):
    entered = threading.Event()
    finish = threading.Event()

    class UnresponsiveSynth(Synth):
        def warm_connection(self, *, cancel_event, **kwargs):
            self.active = True
            entered.set()
            try:
                assert finish.wait(3), "test did not release native producer"
                return False
            finally:
                self.active = False

    monkeypatch.setattr(playback_module, "_PRODUCER_STOP_TIMEOUT_SECONDS", 0.03)
    app = app_state(tts=UnresponsiveSynth())
    handler, connections, sessions = await attach_browser_resources(app, monkeypatch)
    warming = asyncio.create_task(handler.tts.prepare_voice(voice_name="voice", timeout_sec=1))
    assert await asyncio.to_thread(entered.wait, 1)
    try:
        with pytest.raises(ExceptionGroup) as first:
            await cleanup(handler)
        assert any(isinstance(exc, TimeoutError) for exc in exception_leaves(first.value))
        assert app.tts_pool.client.active
        assert app.tts_pool.released == app.stt_pool.released == 0
        assert_safe_cleanup(handler, connections, sessions)
        with pytest.raises(ExceptionGroup) as repeated:
            await cleanup(handler)
        assert repeated.value is first.value
        assert_safe_cleanup(handler, connections, sessions)
    finally:
        finish.set()
        await warming
        await handler.tts.aclose()
    assert app.tts_pool.released == 0


@pytest.mark.asyncio
async def test_independent_teardown_failures_are_all_reported_after_socket_and_analytics(
    monkeypatch,
):
    app = app_state()
    handler, connections, sessions = await attach_browser_resources(app, monkeypatch)
    app.conn_manager.unregister.side_effect = RuntimeError("unregister failed")
    app.session_manager.remove_session.side_effect = RuntimeError("session removal failed")
    app.session_metrics.increment_disconnected.side_effect = RuntimeError("metric failed")
    monkeypatch.setattr(
        browser, "cleanup_adapter", Mock(side_effect=RuntimeError("adapter failed"))
    )
    with pytest.raises(ExceptionGroup) as failure:
        await cleanup(handler)
    assert len(failure.value.exceptions) == 4
    assert all(
        exc.__notes__[0].startswith("Browser cleanup stage:") for exc in failure.value.exceptions
    )
    handler.websocket.close.assert_awaited_once()
    app.cosmos.upsert_document.assert_called_once()
    assert app.tts_pool.released == app.stt_pool.released == 1


@pytest.mark.asyncio
async def test_cancelled_cleanup_caller_does_not_cancel_independent_finalizer(monkeypatch):
    future = PendingStop()
    app = app_state(stt=production_recognizer(future))
    handler, connections, sessions = await attach_browser_resources(app, monkeypatch)
    caller = asyncio.create_task(cleanup(handler))
    try:
        assert await asyncio.to_thread(future.entered.wait, 1)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not handler.websocket.state._conversation_cleanup_task.done()
        future.acknowledged.set()
        await asyncio.wait_for(cleanup(handler), 1)
        assert_safe_cleanup(handler, connections, sessions)
        assert app.tts_pool.released == app.stt_pool.released == 1
    finally:
        future.acknowledged.set()
        await asyncio.gather(
            handler.websocket.state._conversation_cleanup_task, return_exceptions=True
        )


@pytest.mark.asyncio
async def test_socket_failure_does_not_skip_analytics_and_both_failures_survive_retry(monkeypatch):
    app = app_state()
    handler, _, _ = await attach_browser_resources(app, monkeypatch)
    socket_error = RuntimeError("socket close failed")
    analytics_error = RuntimeError("analytics build failed")
    handler.websocket.close.side_effect = socket_error
    analytics = AsyncMock(side_effect=analytics_error)
    monkeypatch.setattr(browser, "build_and_flush", analytics)
    with pytest.raises(ExceptionGroup) as first:
        await cleanup(handler)
    assert first.value.exceptions == (socket_error, analytics_error)
    with pytest.raises(ExceptionGroup) as repeated:
        await cleanup(handler)
    assert repeated.value is first.value
    handler.websocket.close.assert_awaited_once()
    analytics.assert_awaited_once_with(handler.memory_manager, app.cosmos)
