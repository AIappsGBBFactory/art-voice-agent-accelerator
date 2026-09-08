"""Persistence ordering through the real MemoManager and executor-backed Redis API."""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.redis import manager as redis_module
from src.redis.manager import AzureRedisManager
from src.stateful.state_managment import MemoManager
from src.tools.latency_helpers import PersistentLatency


class ControlledRedis:
    """Block real executor HSET/HGETALL/EXPIRE calls without contacting Redis."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.started: asyncio.Queue[str] = asyncio.Queue()
        self.releases: dict[str, threading.Event] = {}
        self.store: dict[str, dict[str, str]] = {}
        self.completed: list[str] = []
        self.expiries: list[tuple[str, int]] = []
        self.failures: set[str] = set()
        self.read_error: Exception | None = None
        self.block_read = False
        self.block_expiry = False
        self.expiry_success = True
        self.closing = False

    def release(self, operation: str) -> None:
        self.releases.setdefault(operation, threading.Event()).set()

    def _wait(self, operation: str) -> None:
        gate = self.releases.setdefault(operation, threading.Event())
        self.loop.call_soon_threadsafe(self.started.put_nowait, operation)
        if not self.closing and not gate.wait(timeout=5):
            raise TimeoutError(f"Test did not release {operation}")

    async def wait_started(self, operation: str) -> None:
        assert await asyncio.wait_for(self.started.get(), timeout=2) == operation

    def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        revision = json.loads(mapping["corememory"]).get("revision", "write")
        self._wait(revision)
        if revision in self.failures:
            raise ValueError(f"failed {revision}")
        self.store.setdefault(key, {}).update(mapping)
        self.completed.append(revision)
        return 0  # Updating existing Redis fields is a successful HSET.

    def hgetall(self, key: str) -> dict[str, str]:
        if self.block_read:
            self._wait("read")
        if self.read_error is not None:
            raise self.read_error
        return dict(self.store.get(key, {}))

    def expire(self, key: str, ttl: int) -> bool:
        if self.block_expiry:
            self._wait("expiry")
        self.expiries.append((key, ttl))
        return self.expiry_success


@pytest.fixture
async def storage(monkeypatch):
    client = ControlledRedis()
    monkeypatch.setattr(redis_module.redis, "Redis", lambda **kwargs: client)
    redis = AzureRedisManager(
        host="example.redis.local", access_key="test", credential=object(), ssl=False
    )
    memo = MemoManager("ordering", redis_mgr=redis)
    try:
        yield memo, redis, client
    finally:
        client.closing = True
        for gate in tuple(client.releases.values()):
            gate.set()
        await asyncio.wait_for(memo.flush_pending_persist(), timeout=5)


async def submit_background(memo: MemoManager, revision: str, **kwargs) -> None:
    memo.set_context("revision", revision)
    await memo.persist_background(**kwargs)


async def submit_direct(memo: MemoManager, redis: AzureRedisManager, revision: str) -> bool:
    memo.set_context("revision", revision)
    return await memo.persist_to_redis_async(redis, raise_on_failure=True)


async def test_active_executor_write_cannot_be_overtaken(storage):
    memo, _, client = storage
    await submit_background(memo, "old")
    await client.wait_started("old")
    writer = memo._pending_persist_task

    await submit_background(memo, "new")
    client.release("new")  # A concurrent writer would complete new before old.
    await asyncio.sleep(0)
    assert client.started.empty()
    assert client.completed == []
    assert memo._pending_persist_task is writer

    client.release("old")
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["old", "new"]
    assert json.loads(client.store["session:ordering"]["corememory"])["revision"] == "new"


async def test_pending_background_snapshot_is_superseded(storage):
    memo, _, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    await submit_background(memo, "superseded")
    await submit_background(memo, "latest")
    client.release("latest")
    client.release("active")

    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["active", "latest"]


async def test_direct_background_interleaving_preserves_direct_barriers(storage):
    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    await submit_background(memo, "before-direct")
    direct = asyncio.create_task(submit_direct(memo, redis, "direct"))
    await asyncio.sleep(0)
    await submit_background(memo, "after-direct")
    await submit_background(memo, "latest")
    for revision in ("active", "before-direct", "direct", "latest"):
        client.release(revision)

    assert await direct
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["active", "before-direct", "direct", "latest"]


@pytest.mark.parametrize("started", [False, True])
async def test_cancelling_direct_waiter_does_not_cancel_write(storage, started):
    memo, redis, client = storage
    if not started:
        await submit_background(memo, "blocking")
        await client.wait_started("blocking")
    direct = asyncio.create_task(submit_direct(memo, redis, "direct"))
    await asyncio.sleep(0)
    if started:
        await client.wait_started("direct")
    direct.cancel()
    with pytest.raises(asyncio.CancelledError):
        await direct

    await submit_background(memo, "latest")
    assert not memo._pending_persist_task.cancelled()
    for revision in ("blocking", "direct", "latest"):
        client.release(revision)
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == (
        ["direct", "latest"] if started else ["blocking", "direct", "latest"]
    )


async def test_cancel_pending_leaves_started_and_direct_writes_intact(storage):
    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    assert not memo.cancel_pending_persist()
    await submit_background(memo, "withdrawn")
    direct = asyncio.create_task(submit_direct(memo, redis, "direct"))
    await asyncio.sleep(0)
    assert memo.cancel_pending_persist()
    client.release("direct")
    client.release("active")

    assert await direct
    with pytest.raises(RuntimeError, match="withdrawn"):
        await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["active", "direct"]
    assert await memo.flush_pending_persist(raise_on_failure=True)


async def test_cancelled_flush_leaves_writer_and_failure_observation_intact(storage):
    memo, _, client = storage
    client.failures.add("failed")
    await submit_background(memo, "failed")
    await client.wait_started("failed")
    flush = asyncio.create_task(memo.flush_pending_persist(raise_on_failure=True))
    await asyncio.sleep(0)
    flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush
    client.release("failed")
    with pytest.raises(RuntimeError, match="Redis write returned failure"):
        await memo.flush_pending_persist(raise_on_failure=True)


async def test_cancelled_flush_does_not_acknowledge_previously_completed_failure(storage):
    memo, _, client = storage
    client.failures.add("failed")
    await submit_background(memo, "failed")
    client.release("failed")
    await memo._pending_persist_task
    await client.wait_started("failed")
    await submit_background(memo, "active")
    await client.wait_started("active")
    flush = asyncio.create_task(memo.flush_pending_persist(raise_on_failure=True))
    await asyncio.sleep(0)
    flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush
    client.release("active")
    with pytest.raises(RuntimeError, match="Redis write returned failure"):
        await memo.flush_pending_persist(raise_on_failure=True)


@pytest.mark.parametrize("started", [False, True])
async def test_forced_internal_writer_cancellation_fails_closed(storage, started):
    memo, redis, client = storage
    await submit_background(memo, "active")
    if started:
        await client.wait_started("active")
    memo._pending_persist_task.cancel()

    with pytest.raises(RuntimeError, match="write outcome is unconfirmed"):
        await memo.flush_pending_persist(raise_on_failure=True)
    with pytest.raises(RuntimeError, match="cannot submit further writes"):
        await memo.persist_to_redis_async(redis, raise_on_failure=True)
    with pytest.raises(RuntimeError, match="cannot submit further writes"):
        memo.persist_to_redis(redis)
    assert not await memo.flush_pending_persist()
    client.release("active")


async def test_flush_remembers_completed_failure_even_after_later_success(storage):
    memo, _, client = storage
    client.failures.add("failed")
    await submit_background(memo, "failed")
    await client.wait_started("failed")
    client.release("failed")
    await memo._pending_persist_task
    await submit_background(memo, "retry")
    client.release("retry")

    assert not await memo.flush_pending_persist()
    assert client.completed == ["retry"]
    assert await memo.flush_pending_persist(raise_on_failure=True)


async def test_flush_waits_entire_boundary_before_raising_failure(storage):
    memo, _, client = storage
    client.failures.add("failed")
    await submit_background(memo, "failed")
    await client.wait_started("failed")
    await submit_background(memo, "later")
    flush = asyncio.create_task(memo.flush_pending_persist(raise_on_failure=True))
    await asyncio.sleep(0)
    client.release("failed")
    await client.wait_started("later")
    assert not flush.done()
    client.release("later")
    with pytest.raises(RuntimeError, match="Redis write returned failure"):
        await flush
    assert client.completed == ["later"]


async def test_concurrent_flushes_both_observe_inflight_failure(storage):
    memo, _, client = storage
    client.failures.add("failed")
    await submit_background(memo, "failed")
    await client.wait_started("failed")
    first = asyncio.create_task(memo.flush_pending_persist())
    second = asyncio.create_task(memo.flush_pending_persist())
    await asyncio.sleep(0)
    client.release("failed")
    assert await asyncio.gather(first, second) == [False, False]
    assert await memo.flush_pending_persist()


@pytest.mark.parametrize("strict", [False, True])
async def test_direct_write_failure_contract(storage, strict):
    memo, redis, client = storage
    memo.set_context("revision", "failed")
    client.failures.add("failed")
    client.release("failed")
    if strict:
        with pytest.raises(RuntimeError, match="Redis write returned failure"):
            await memo.persist_to_redis_async(redis, raise_on_failure=True)
    else:
        assert not await memo.persist_to_redis_async(redis)
    assert not await memo.flush_pending_persist()


async def test_async_backend_exception_is_propagated_without_killing_writer(storage, monkeypatch):
    memo, redis, _ = storage
    failure = ValueError("backend rejected snapshot")
    monkeypatch.setattr(redis, "store_session_data_async", AsyncMock(side_effect=failure))
    with pytest.raises(ValueError, match="backend rejected snapshot"):
        await memo.persist_to_redis_async(redis, raise_on_failure=True)
    with pytest.raises(ValueError, match="backend rejected snapshot"):
        await memo.flush_pending_persist(raise_on_failure=True)


async def test_snapshot_is_coherent_and_configuration_update_preserves_tool_state(storage):
    memo, _, client = storage
    client.store["session:ordering"] = {"unrelated_field": "preserved"}
    nested = {"enabled": True}
    memo.set_context("configuration", nested)
    memo.persist_tool_output("completed_tool", {"status": "completed"})
    memo.append_to_history("agent", "user", "original")
    await submit_background(memo, "captured")
    nested["enabled"] = False
    memo.append_to_history("agent", "assistant", "later")
    await client.wait_started("captured")
    client.release("captured")
    assert await memo.flush_pending_persist(raise_on_failure=True)

    saved = client.store["session:ordering"]
    assert saved["unrelated_field"] == "preserved"
    assert json.loads(saved["corememory"])["configuration"] == {"enabled": True}
    assert len(json.loads(saved["chat_history"])["agent"]) == 1
    restored = await MemoManager.from_redis_async("ordering", memo._redis_manager)
    tool_output = restored.get_context("tool_outputs")
    assert tool_output == {"completed_tool": {"status": "completed"}}
    restored.set_context("configuration", {"enabled": False})
    restored.set_context("revision", "updated")
    client.release("updated")
    assert await restored.persist_to_redis_async(memo._redis_manager, raise_on_failure=True)
    updated = await MemoManager.from_redis_async("ordering", memo._redis_manager)
    assert updated.get_context("tool_outputs") == tool_output
    assert updated.get_context("configuration") == {"enabled": False}
    assert updated.histories == restored.histories


async def test_final_persist_flushes_latest_unsaved_state(storage):
    memo, redis, client = storage
    await submit_background(memo, "old")
    await client.wait_started("old")
    final = asyncio.create_task(submit_direct(memo, redis, "end-of-call"))
    await asyncio.sleep(0)
    flush = asyncio.create_task(memo.flush_pending_persist(raise_on_failure=True))
    await asyncio.sleep(0)
    assert not final.done()
    assert not flush.done()
    client.release("end-of-call")
    client.release("old")

    assert await final
    assert await flush
    restored = await MemoManager.from_redis_async("ordering", redis)
    assert restored.get_context("revision") == "end-of-call"


async def test_flush_boundary_does_not_wait_for_later_submission(storage):
    memo, _, client = storage
    await submit_background(memo, "first")
    await client.wait_started("first")
    flush = asyncio.create_task(memo.flush_pending_persist(raise_on_failure=True))
    await asyncio.sleep(0)
    await submit_background(memo, "later")
    client.release("first")
    assert await asyncio.wait_for(flush, timeout=2)
    await client.wait_started("later")
    assert client.completed == ["first"]
    client.release("later")
    assert await memo.flush_pending_persist(raise_on_failure=True)


async def test_ttl_is_ordered_before_next_write_and_none_does_not_remove_expiry(storage):
    memo, _, client = storage
    client.block_expiry = True
    client.release("first")
    await submit_background(memo, "first", ttl_seconds=90)
    await client.wait_started("first")
    await client.wait_started("expiry")
    await submit_background(memo, "second")
    client.release("second")
    await asyncio.sleep(0)
    assert client.completed == ["first"]
    client.release("expiry")
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["first", "second"]
    assert client.expiries == [("session:ordering", 90)]


@pytest.mark.parametrize("ttl", [None, 0, 120])
async def test_ttl_compatibility(storage, ttl):
    memo, redis, client = storage
    client.release("write")
    assert await memo.persist_to_redis_async(redis, ttl_seconds=ttl, raise_on_failure=True)
    assert client.expiries == ([("session:ordering", ttl)] if ttl else [])


async def test_background_coalescing_preserves_distinct_ttl_requests(storage):
    memo, _, client = storage
    await submit_background(memo, "first", ttl_seconds=10)
    await submit_background(memo, "second", ttl_seconds=20)
    client.release("first")
    client.release("second")
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["first", "second"]
    assert client.expiries == [("session:ordering", 10), ("session:ordering", 20)]


async def test_expiry_failure_is_not_durable_success(storage):
    memo, redis, client = storage
    client.release("write")
    client.expiry_success = False
    with pytest.raises(RuntimeError, match="Redis expiry returned failure"):
        await memo.persist_to_redis_async(redis, ttl_seconds=10, raise_on_failure=True)
    assert not await memo.flush_pending_persist()


async def test_sync_write_is_rejected_while_async_writer_is_active(storage):
    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    with pytest.raises(RuntimeError, match="Flush pending persistence"):
        memo.persist_to_redis(redis)
    client.release("active")
    assert await memo.flush_pending_persist(raise_on_failure=True)
    memo.set_context("revision", "sync")
    client.release("sync")
    memo.persist_to_redis(redis, ttl_seconds=30)
    assert client.completed == ["active", "sync"]
    assert client.expiries == [("session:ordering", 30)]


async def test_live_context_write_does_not_report_false_success(storage):
    memo, redis, client = storage
    client.failures.add("write")
    client.release("write")
    assert not await memo.set_live_context_value(redis, "config", {"updated": True})


async def test_serialization_failure_is_surfaced_before_submission(storage):
    memo, redis, _ = storage
    memo.set_context("invalid", object())
    assert not await memo.persist_to_redis_async(redis)
    with pytest.raises(TypeError):
        await memo.persist_to_redis_async(redis, raise_on_failure=True)
    with pytest.raises(TypeError):
        await memo.persist_background()
    assert memo._pending_persist_task is None


async def test_background_requires_a_redis_manager():
    with pytest.raises(ValueError, match="No Redis manager"):
        await MemoManager().persist_background()


async def test_independent_instances_are_not_a_distributed_ordering_guarantee(storage):
    memo, redis, client = storage
    independent = MemoManager("ordering", redis_mgr=redis)
    older = asyncio.create_task(submit_direct(memo, redis, "older"))
    await client.wait_started("older")
    newer = asyncio.create_task(submit_direct(independent, redis, "newer"))
    await client.wait_started("newer")
    client.release("newer")
    assert await newer
    client.release("older")
    assert await older
    assert client.completed == ["newer", "older"]
    assert json.loads(client.store["session:ordering"]["corememory"])["revision"] == "older"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"corememory": '{"setting": {"nested": true}}'},
        {"chat_history": '{"agent": [{"role": "user", "content": "hello"}]}'},
        {"corememory": "{}", "chat_history": '[{"role": "user", "content": "legacy"}]'},
    ],
)
async def test_async_restoration_matches_sync_factory(storage, monkeypatch, data):
    _, redis, client = storage
    monkeypatch.setattr("src.stateful.state_managment.time.time", lambda: 1234.0)
    client.store["session:restored"] = data
    sync = MemoManager.from_redis_with_manager("restored", redis)
    restored = await MemoManager.from_redis_async("restored", redis)
    assert restored.to_redis_dict() == sync.to_redis_dict()
    assert restored._redis_manager is redis
    assert MemoManager.from_redis("restored", redis)._redis_manager is None


async def test_async_restoration_does_not_block_event_loop(storage):
    _, redis, client = storage
    client.block_read = True
    restore = asyncio.create_task(MemoManager.from_redis_async("restored", redis))
    await client.wait_started("read")  # Event-loop progress while HGETALL is blocked.
    assert not restore.done()
    client.release("read")
    assert (await restore).session_id == "restored"


async def test_async_restoration_propagates_read_failure(storage):
    _, redis, client = storage
    client.read_error = ValueError("failed read")
    with pytest.raises(ValueError, match="failed read"):
        await MemoManager.from_redis_async("restored", redis)
    assert await redis.get_session_data_async("session:restored") == {}


async def test_async_restoration_propagates_invalid_json(storage):
    _, redis, client = storage
    client.store["session:restored"] = {"corememory": "{"}
    with pytest.raises(json.JSONDecodeError):
        await MemoManager.from_redis_async("restored", redis)


async def test_async_restoration_propagates_cancellation(storage):
    _, redis, client = storage
    client.block_read = True
    restore = asyncio.create_task(MemoManager.from_redis_async("restored", redis))
    await client.wait_started("read")
    restore.cancel()
    with pytest.raises(asyncio.CancelledError):
        await restore
    client.release("read")


def dtmf_context(memo, redis, tone, sequence_id=None):
    from apps.artagent.backend.api.v1.events.types import ACSEventTypes, CallEventContext
    from azure.core.messaging import CloudEvent

    return CallEventContext(
        event=CloudEvent(
            source="test",
            type=ACSEventTypes.DTMF_TONE_RECEIVED,
            data={"tone": tone, "sequenceId": sequence_id},
        ),
        call_connection_id="ordering",
        event_type=ACSEventTypes.DTMF_TONE_RECEIVED,
        memo_manager=memo,
        redis_mgr=redis,
    )


@pytest.mark.parametrize(
    "tone,sequence_id,initial,expected,validated",
    [
        ("5", None, "12", "125", None),
        ("three", 3, "12", "123", None),
        ("star", None, "123", "", None),
        ("pound", None, "1234", "", True),
        ("pound", None, "123", "", False),
    ],
)
async def test_dtmf_handler_orders_persistence_behind_active_write(
    storage, tone, sequence_id, initial, expected, validated
):
    from apps.artagent.backend.api.v1.events.acs_events import CallEventHandlers

    memo, redis, client = storage
    memo.set_context("dtmf_sequence", initial)
    await submit_background(memo, "active")
    await client.wait_started("active")
    memo.set_context("revision", "dtmf")
    handler = asyncio.create_task(
        CallEventHandlers.handle_dtmf_tone_received(dtmf_context(memo, redis, tone, sequence_id))
    )
    await asyncio.sleep(0)
    assert memo.get_context("dtmf_sequence") == expected
    assert not handler.done()
    assert client.completed == []
    client.release("dtmf")
    client.release("active")

    await handler
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["active", "dtmf"]
    persisted = json.loads(client.store["session:ordering"]["corememory"])
    assert persisted["dtmf_sequence"] == expected
    if validated is not None:
        assert persisted["dtmf_validated"] is validated
        assert persisted["entered_pin"] == (initial if validated else None)


async def test_dtmf_handler_preserves_local_only_and_invalid_tone_behavior(storage):
    from apps.artagent.backend.api.v1.events.acs_events import CallEventHandlers

    memo, _, client = storage
    memo.set_context("dtmf_sequence", "12")
    await CallEventHandlers.handle_dtmf_tone_received(dtmf_context(memo, None, "3"))
    assert memo.get_context("dtmf_sequence") == "123"
    await CallEventHandlers.handle_dtmf_tone_received(dtmf_context(memo, None, "invalid"))
    assert memo.get_context("dtmf_sequence") == "123"
    assert client.completed == []


async def test_dtmf_handler_surfaces_persistence_failure(storage):
    from apps.artagent.backend.api.v1.events.acs_events import CallEventHandlers

    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    memo.set_context("revision", "dtmf")
    client.failures.add("dtmf")
    handler = asyncio.create_task(
        CallEventHandlers.handle_dtmf_tone_received(dtmf_context(memo, redis, "5"))
    )
    await asyncio.sleep(0)
    client.release("dtmf")
    client.release("active")
    with pytest.raises(RuntimeError, match="Redis write returned failure"):
        await handler
    assert not await memo.flush_pending_persist()
    assert memo.get_context("dtmf_sequence") == "5"
    assert client.completed == ["active"]


async def test_dtmf_handler_cancellation_does_not_discard_queued_tone(storage):
    from apps.artagent.backend.api.v1.events.acs_events import CallEventHandlers

    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    memo.set_context("revision", "dtmf")
    handler = asyncio.create_task(
        CallEventHandlers.handle_dtmf_tone_received(dtmf_context(memo, redis, "5"))
    )
    await asyncio.sleep(0)
    handler.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler
    client.release("dtmf")
    client.release("active")
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert json.loads(client.store["session:ordering"]["corememory"])["dtmf_sequence"] == "5"


async def test_latency_stop_submits_before_immediate_flush_with_active_write(storage):
    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    memo.set_context("revision", "latency")
    latency = PersistentLatency(memo)
    latency.start("llm")
    sample = latency.stop("llm", redis_mgr=redis, meta={"turn": 1})
    assert sample.stage == "llm"
    assert sample.dur >= 0
    assert client.completed == []
    client.release("latency")
    client.release("active")

    # No scheduling yield is needed for stop's snapshot to join this boundary.
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["active", "latency"]
    restored = await MemoManager.from_redis_async("ordering", redis)
    persisted = restored.get_context("latency")
    samples = persisted["runs"][persisted["current_run_id"]]["samples"]
    assert samples == [
        {
            "stage": sample.stage,
            "start": sample.start,
            "end": sample.end,
            "dur": sample.dur,
            "meta": {"turn": 1},
        }
    ]


async def test_latency_stop_write_failure_is_visible_to_flush(storage):
    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")
    memo.set_context("revision", "latency")
    client.failures.add("latency")
    latency = PersistentLatency(memo)
    latency.start("llm")
    assert latency.stop("llm", redis_mgr=redis) is not None
    client.release("latency")
    client.release("active")
    with pytest.raises(RuntimeError, match="Redis write returned failure"):
        await memo.flush_pending_persist(raise_on_failure=True)


async def test_latency_stop_submission_errors_propagate(storage):
    memo, redis, _ = storage
    memo.set_context("unserializable", object())
    latency = PersistentLatency(memo)
    latency.start("llm")
    with pytest.raises(TypeError):
        latency.stop("llm", redis_mgr=redis)


@pytest.mark.parametrize("failure", [False, True])
def test_latency_stop_retains_synchronous_off_loop_path(monkeypatch, failure):
    client = MagicMock()
    client.hset.return_value = 0
    if failure:
        client.hset.side_effect = ValueError("synchronous write failed")
    monkeypatch.setattr(redis_module.redis, "Redis", lambda **kwargs: client)
    redis = AzureRedisManager(
        host="example.redis.local", access_key="test", credential=object(), ssl=False
    )
    memo = MemoManager("sync-latency")
    latency = PersistentLatency(memo)
    latency.start("llm")
    if failure:
        with pytest.raises(ValueError, match="synchronous write failed"):
            latency.stop("llm", redis_mgr=redis)
    else:
        sample = latency.stop("llm", redis_mgr=redis)
        assert sample.stage == "llm"
        snapshot = client.hset.call_args.kwargs["mapping"]
        assert "latency" in json.loads(snapshot["corememory"])
    client.hset.assert_called_once()
    assert memo._pending_persist_task is None


def test_schedule_persist_requires_running_loop():
    memo = MemoManager("no-loop", redis_mgr=MagicMock())
    with pytest.raises(RuntimeError, match="no running event loop"):
        memo.schedule_persist()
    assert not memo._persist_queue


async def test_schedule_persist_rejects_foreign_loop_during_active_write(storage):
    memo, redis, client = storage
    await submit_background(memo, "active")
    await client.wait_started("active")

    async def submit_from_foreign_loop():
        memo.schedule_persist(redis)

    with pytest.raises(RuntimeError, match="owning event loop"):
        await asyncio.to_thread(asyncio.run, submit_from_foreign_loop())
    client.release("active")
    assert await memo.flush_pending_persist(raise_on_failure=True)
    assert client.completed == ["active"]
