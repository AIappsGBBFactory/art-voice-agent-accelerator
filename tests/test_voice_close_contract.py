"""All channel handlers expose the same retained, strict close postcondition."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apps.artagent.backend.src.orchestration.session_memory import (
    bind_session_manager,
    session_memo,
)
from src.pools.session_manager import ThreadSafeSessionManager
from src.stateful.state_managment import MemoManager

from tests.test_cascade_runtime_ownership import app_state, make_handler
from tests.test_genesys_handler import _make_handler as genesys_handler
from tests.test_voicelive_partial_start_cleanup import _make_handler as voicelive_handler


class RecordingMemo(MemoManager):
    def __init__(self):
        super().__init__(session_id="close-contract")
        self.actions = []
        self.fail_snapshot = False

    async def persist_to_redis_async(self, redis_mgr=None, *, raise_on_failure=False):
        assert raise_on_failure
        self.actions.append(("snapshot", self.get_value_from_corememory("last_effect")))
        if self.fail_snapshot:
            raise RuntimeError("snapshot rejected")
        return True

    async def flush_pending_persist(self, *, raise_on_failure=False):
        assert raise_on_failure
        self.actions.append(("flush", None))
        return True


async def build_handler(kind):
    memo = RecordingMemo()
    if kind == "cascade":
        app = app_state()
        handler = await make_handler(app)
        handler._context.memo_manager = memo
    else:
        handler, ws = voicelive_handler() if kind == "voicelive" else genesys_handler()
        ws.state.cm = memo
        ws.app.state.redis = object()
        if kind == "genesys":
            handler._memo_manager = memo
        app = ws.app.state
    return handler, memo, app


def attach_producer(kind, handler, task):
    if kind == "cascade":
        handler._orchestration_tasks.add(task)
    elif kind == "genesys":
        handler._writer_task = task
    else:
        handler._event_task = task


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cascade", "voicelive", "genesys"])
async def test_concurrent_close_waits_for_producer_even_if_first_caller_cancels(kind):
    handler, memo, _ = await build_handler(kind)
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def producer():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
            await release.wait()
            memo.set_corememory("last_effect", "committed before snapshot")

    producer_task = asyncio.create_task(producer())
    attach_producer(kind, handler, producer_task)
    await started.wait()
    first = asyncio.create_task(handler.stop())
    await asyncio.wait_for(cancelled.wait(), 1)
    second = asyncio.create_task(handler.stop())
    await asyncio.sleep(0)
    assert not second.done()
    assert memo.actions == []
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    release.set()
    await asyncio.wait_for(second, 1)
    assert producer_task.done()
    assert memo.actions == [("snapshot", "committed before snapshot"), ("flush", None)]
    await handler.stop()
    assert len(memo.actions) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cascade", "voicelive", "genesys"])
async def test_owned_producer_can_initiate_close_without_self_join(kind):
    handler, memo, _ = await build_handler(kind)
    producer = asyncio.create_task(handler.stop())
    attach_producer(kind, handler, producer)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(producer, 1)
    await asyncio.wait_for(handler.stop(), 1)
    assert memo.actions == [("snapshot", None), ("flush", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cascade", "voicelive", "genesys"])
async def test_strict_snapshot_failure_drains_and_releases_safe_resources(kind):
    handler, memo, app = await build_handler(kind)
    memo.fail_snapshot = True
    socket_close = AsyncMock()
    if kind != "cascade":
        handler._connection_cm = SimpleNamespace(__aexit__=socket_close)
    with pytest.raises(Exception) as first:
        await handler.stop()
    assert memo.actions == [("snapshot", None), ("flush", None)]
    if kind == "cascade":
        assert app.tts_pool.released == app.stt_pool.released == 1
    else:
        socket_close.assert_awaited_once()
    with pytest.raises(Exception) as second:
        await handler.stop()
    assert first.value is second.value


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cascade", "voicelive"])
async def test_stop_cancels_suspended_start_and_prevents_restart(kind, monkeypatch):
    handler, memo, _ = await build_handler(kind)
    entered = asyncio.Event()
    finished = asyncio.Event()

    async def provider_start():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    monkeypatch.setattr(handler, "_start", provider_start)
    starting = asyncio.create_task(handler.start())
    await entered.wait()
    await asyncio.wait_for(handler.stop(), 1)
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert finished.is_set()
    assert memo.actions[-1] == ("flush", None)
    with pytest.raises(RuntimeError, match="restart"):
        await handler.start()


@pytest.mark.asyncio
async def test_live_call_alias_uses_owned_memo_without_rehydration():
    manager = ThreadSafeSessionManager()
    memo = MemoManager(session_id="canonical")
    memo.set_corememory("last_effect", "not persisted yet")
    ws = SimpleNamespace(state=SimpleNamespace(call_connection_id="acs-call"))
    await manager.add_session("canonical", memo, ws)
    bind_session_manager(manager)
    redis = SimpleNamespace(
        get_session_data_async=AsyncMock(side_effect=AssertionError("stale reload"))
    )
    try:
        assert await session_memo("acs-call", redis) is memo
        assert await session_memo("canonical", redis) is memo
        redis.get_session_data_async.assert_not_awaited()
    finally:
        bind_session_manager(None)


@pytest.mark.asyncio
async def test_true_hydration_failure_is_not_an_empty_local_session():
    redis = SimpleNamespace(
        get_session_data_async=AsyncMock(side_effect=RuntimeError("Redis down"))
    )
    with pytest.raises(RuntimeError, match="Redis down"):
        await session_memo("offline-failed", redis)
    local = await session_memo("explicit-local", None)
    assert local.session_id == "explicit-local"


@pytest.mark.asyncio
async def test_route_worker_timeout_drains_persistence_without_recancelling_native_cleanup(
    monkeypatch,
):
    from apps.artagent.backend.voice.shared.close import cancel_and_join
    from apps.artagent.backend.voice.speech_cascade import handler as route_module

    handler, memo, app = await build_handler("cascade")
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    safe_cleanup = AsyncMock()
    monkeypatch.setattr(
        "apps.artagent.backend.src.orchestration.session_memory.release_session_memory",
        safe_cleanup,
    )

    async def bounded_join(tasks, **kwargs):
        await cancel_and_join(tasks, timeout=0.02, **kwargs)

    monkeypatch.setattr(route_module, "cancel_and_join", bounded_join, raising=False)
    cancellation_counts = []

    async def response(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cancellation_counts.append(asyncio.current_task().cancelling())

    route = route_module.RouteTurnThread(
        connection_id="route-close",
        speech_queue=asyncio.Queue(),
        orchestrator_func=response,
        memory_manager=memo,
    )
    handler._route_turn_thread = route
    await route.start()
    await route.speech_queue.put(
        route_module.SpeechEvent(event_type=route_module.SpeechEventType.FINAL, text="Hello")
    )
    await entered.wait()
    closing = asyncio.create_task(handler.stop())
    try:
        await asyncio.wait_for(cleaning.wait(), 1)
        done, _ = await asyncio.wait({closing}, timeout=0.2)
        assert done, "Route cleanup must reach persistence drain despite a held response"
        with pytest.raises(ExceptionGroup, match="quiesced"):
            await closing
        assert memo.actions == [("flush", None)]
        safe_cleanup.assert_awaited_once()
        assert app.tts_pool.released == app.stt_pool.released == 0
        assert route.current_response_task is not None
        assert not route.current_response_task.done()
        assert route.current_response_task.cancelling() == 1
        with pytest.raises(ExceptionGroup):
            await route.stop()
        with pytest.raises(RuntimeError, match="restart"):
            await route.start()
    finally:
        release.set()
        await asyncio.gather(closing, route.processing_task, return_exceptions=True)
    assert cancellation_counts == [1]


@pytest.mark.asyncio
async def test_release_removes_only_matching_session_and_adapter(monkeypatch):
    from apps.artagent.backend.src.orchestration import session_memory, unified

    manager = ThreadSafeSessionManager()
    monkeypatch.setattr(session_memory, "_sessions", manager)
    memo = MemoManager(session_id="release")
    ws = SimpleNamespace(state=SimpleNamespace())
    await manager.add_session("release", memo, ws)
    adapter = SimpleNamespace(memo_manager=memo)
    monkeypatch.setattr(unified, "_adapters", {"release": adapter})
    await session_memory.release_session_memory("release", memo, ws)
    assert await manager.get_session_context("release") is None
    assert unified._adapters == {}
    replacement = MemoManager(session_id="release")
    replacement_ws = SimpleNamespace(state=SimpleNamespace())
    await manager.add_session("release", replacement, replacement_ws)
    new_adapter = SimpleNamespace(memo_manager=replacement)
    unified._adapters["release"] = new_adapter
    await session_memory.release_session_memory("release", memo, ws)
    assert (await manager.get_session_context("release")).memory_manager is replacement
    assert unified._adapters["release"] is new_adapter


@pytest.mark.asyncio
async def test_session_remove_checks_lifetime_after_waiting_for_lock():
    manager = ThreadSafeSessionManager()
    ws = SimpleNamespace(state=SimpleNamespace())
    await manager.add_session("race", MemoManager(session_id="race"), ws)
    old = await manager.get_session_context("race")
    await manager._lock.acquire()
    replacement = asyncio.create_task(
        manager.add_session(
            "race", MemoManager(session_id="race"), SimpleNamespace(state=SimpleNamespace())
        )
    )
    removing = asyncio.create_task(manager.remove_session("race", expected_context=old))
    await asyncio.sleep(0)
    manager._lock.release()
    await replacement
    assert not await removing
    assert await manager.get_session_context("race") is not old


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["voicelive", "genesys"])
async def test_state_projection_failure_still_flushes_and_closes(kind):
    handler, memo, _ = await build_handler(kind)
    handler._orchestrator = SimpleNamespace(
        cancel_and_join_tasks=AsyncMock(),
        _sync_to_memo_manager=Mock(side_effect=ValueError("invalid state projection")),
        cleanup=Mock(),
    )
    socket_close = AsyncMock()
    handler._connection_cm = SimpleNamespace(__aexit__=socket_close)
    with pytest.raises(ExceptionGroup):
        await handler.stop()
    assert memo.actions == [("flush", None)]
    socket_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_genesys_close_joins_suspended_open(monkeypatch):
    handler, memo, _ = await build_handler("genesys")
    entered, finished = asyncio.Event(), asyncio.Event()

    async def connect():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    monkeypatch.setattr(handler, "_connect_voicelive", connect)
    monkeypatch.setattr(handler._protocol, "process_open", Mock(return_value=["media"]))
    opening = asyncio.create_task(handler._handle_open({}))
    await entered.wait()
    await asyncio.wait_for(handler.stop(), 1)
    with pytest.raises(asyncio.CancelledError):
        await opening
    assert finished.is_set()
    assert memo.actions == [("snapshot", None), ("flush", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["voicelive", "genesys"])
async def test_partial_close_does_not_unregister_a_replacement_lifetime(kind, monkeypatch):
    from apps.artagent.backend.voice.voicelive import orchestrator

    handler, _, _ = await build_handler(kind)
    replacement = object()
    monkeypatch.setattr(orchestrator, "_voicelive_orchestrators", {handler.session_id: replacement})
    await handler.stop()
    assert orchestrator.get_voicelive_orchestrator(handler.session_id) is replacement


@pytest.mark.asyncio
@pytest.mark.parametrize("abandonment", ["timeout", "cancelled"])
async def test_abandoned_warmup_remains_owned_until_prepared_socket_closes(abandonment):
    from apps.artagent.backend.voice.voicelive.handler import (
        VoiceLivePreparedConnection,
        consume_voicelive_call_warmup,
    )

    handler, memo, app = await build_handler("voicelive")
    prepared_ready, close_entered, close_release = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def exit_connection(*args):
        close_entered.set()
        await close_release.wait()

    close = AsyncMock(side_effect=exit_connection)
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=SimpleNamespace(__aexit__=close),
        credential=object(),
        settings=object(),
        model="gpt-realtime",
    )

    async def prepare():
        await prepared_ready.wait()
        return prepared

    warmup = asyncio.create_task(prepare())
    app.voicelive_warmups = {"call": warmup}
    consuming = asyncio.create_task(
        consume_voicelive_call_warmup(
            app,
            call_connection_id="call",
            cleanup_tasks=handler._warmup_cleanup_tasks,
            timeout_sec=0.001 if abandonment == "timeout" else 1,
        )
    )
    if abandonment == "cancelled":
        await asyncio.sleep(0)
        consuming.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consuming
    else:
        assert await consuming is None
    assert len(handler._warmup_cleanup_tasks) == 1
    closing = asyncio.create_task(handler.stop())
    await asyncio.sleep(0)
    assert not closing.done()
    assert memo.actions == []
    prepared_ready.set()
    await asyncio.wait_for(close_entered.wait(), 1)
    assert not closing.done()
    assert memo.actions == []
    close_release.set()
    await asyncio.wait_for(closing, 1)
    assert memo.actions == [("snapshot", None), ("flush", None)]
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_completed_warmup_close_failure_is_not_forgotten():
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    handler, memo, _ = await build_handler("voicelive")
    close = AsyncMock(side_effect=RuntimeError("prepared close failed"))
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=SimpleNamespace(__aexit__=close),
        credential=object(),
        settings=object(),
        model="gpt-realtime",
    )
    disposing = asyncio.create_task(prepared.close())
    handler._warmup_cleanup_tasks.add(disposing)
    with pytest.raises(RuntimeError, match="prepared close failed") as original:
        await disposing
    with pytest.raises(ExceptionGroup):
        await handler.stop()
    assert memo.actions == [("flush", None)]
    with pytest.raises(RuntimeError) as repeated:
        await prepared.close()
    assert repeated.value is original.value
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepared_close_waits_for_same_result_after_caller_cancellation():
    from apps.artagent.backend.voice.voicelive.handler import VoiceLivePreparedConnection

    entered, release = asyncio.Event(), asyncio.Event()

    async def exit_connection(*args):
        entered.set()
        await release.wait()

    close = AsyncMock(side_effect=exit_connection)
    prepared = VoiceLivePreparedConnection(
        connection=object(),
        connection_cm=SimpleNamespace(__aexit__=close),
        credential=object(),
        settings=object(),
        model="gpt-realtime",
    )
    first = asyncio.create_task(prepared.close())
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(RuntimeError, match="closing"):
        prepared.claim()
    second = asyncio.create_task(prepared.close())
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    await asyncio.wait_for(second, 1)
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_unacknowledged_warmup_cleanup_is_retained_without_cancellation(monkeypatch):
    from functools import partial

    from apps.artagent.backend.voice.voicelive import handler as voicelive

    handler, memo, _ = await build_handler("voicelive")
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    handler._warmup_cleanup_tasks.add(task)
    monkeypatch.setattr(
        voicelive, "cancel_and_join", partial(voicelive.cancel_and_join, timeout=0.01)
    )
    try:
        with pytest.raises(ExceptionGroup):
            await handler.stop()
        assert not task.done()
        assert task.cancelling() == 0
        assert task in handler._warmup_cleanup_tasks
        assert memo.actions == [("flush", None)]
    finally:
        release.set()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cascade", "voicelive", "genesys"])
async def test_unacknowledged_producer_skips_snapshot_but_drains_and_closes_socket(
    kind, monkeypatch
):
    from functools import partial

    from apps.artagent.backend.voice.genesys import handler as genesys_module
    from apps.artagent.backend.voice.shared import close
    from apps.artagent.backend.voice.voicelive import handler as voicelive_module

    bounded_join = partial(close.cancel_and_join, timeout=0.01)
    monkeypatch.setattr(close, "cancel_and_join", bounded_join)
    monkeypatch.setattr(genesys_module, "cancel_and_join", bounded_join)
    monkeypatch.setattr(voicelive_module, "cancel_and_join", bounded_join)
    handler, memo, app = await build_handler(kind)
    from apps.artagent.backend.src.orchestration import session_memory

    sessions = ThreadSafeSessionManager()
    await sessions.add_session(handler.session_id, memo, handler.websocket)
    monkeypatch.setattr(session_memory, "_sessions", sessions)
    entered, release = asyncio.Event(), asyncio.Event()

    async def native_work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await release.wait()

    task = asyncio.create_task(native_work())
    attach_producer(kind, handler, task)
    await entered.wait()
    socket_close = AsyncMock()
    if kind != "cascade":
        handler._connection_cm = SimpleNamespace(__aexit__=socket_close)
    try:
        with pytest.raises(ExceptionGroup):
            await handler.stop()
        assert not task.done()
        assert memo.actions == [("flush", None)]
        assert await sessions.get_session_count() == 0
        if kind == "cascade":
            assert app.tts_pool.released == app.stt_pool.released == 0
        else:
            socket_close.assert_awaited_once()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
