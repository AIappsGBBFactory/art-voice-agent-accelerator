from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from redis.exceptions import MovedError, RedisClusterException, RedisError
from src.redis import manager as redis_manager
from src.redis.manager import AzureRedisManager


class _FakeRedis:
    def __init__(self) -> None:
        self.hgetall_calls = 0

    def hgetall(self, key: str) -> dict[str, str]:
        self.hgetall_calls += 1
        raise MovedError("1234 127.0.0.1:7001")


class _FakeClusterRedis:
    def __init__(self) -> None:
        self.hgetall_calls = 0

    def hgetall(self, key: str) -> dict[str, str]:
        self.hgetall_calls += 1
        return {"foo": "bar"}


def test_get_session_data_switches_to_cluster(monkeypatch):
    single_node_client = _FakeRedis()
    cluster_client = _FakeClusterRedis()

    # Stub the redis client constructors used inside the manager
    monkeypatch.setattr(
        redis_manager.redis,
        "Redis",
        lambda *args, **kwargs: single_node_client,
    )
    monkeypatch.setattr(
        redis_manager,
        "RedisCluster",
        lambda *args, **kwargs: cluster_client,
    )

    mgr = AzureRedisManager(
        host="example.redis.local",
        port=6380,
        access_key="dummy",
        ssl=False,
        credential=object(),
    )

    data = mgr.get_session_data("session-123")

    assert data == {"foo": "bar"}
    assert single_node_client.hgetall_calls == 1
    assert cluster_client.hgetall_calls == 1
    assert mgr.use_cluster is True


def test_get_session_data_raises_without_cluster_support(monkeypatch):
    single_node_client = _FakeRedis()

    monkeypatch.setattr(
        redis_manager.redis,
        "Redis",
        lambda *args, **kwargs: single_node_client,
    )
    monkeypatch.setattr(
        redis_manager,
        "RedisCluster",
        lambda *args, **kwargs: (_ for _ in ()).throw(RedisClusterException("cluster unavailable")),
    )

    mgr = AzureRedisManager(
        host="example.redis.local",
        port=6380,
        access_key="dummy",
        ssl=False,
        credential=object(),
    )

    with pytest.raises(MovedError):
        mgr.get_session_data("session-123")


def test_moved_does_not_flip_flop_back_to_standalone(monkeypatch):
    """A MOVED reply must latch cluster mode.

    Once the endpoint has proven it is an OSS cluster (via MOVED), a failed
    cluster rebuild must NOT silently fall back to a standalone client — that
    reintroduces MOVED in an endless ping-pong. The manager should stop retrying
    on the standalone client and surface the original MOVED instead.
    """
    single_node_client = _FakeRedis()
    cluster_attempts = {"count": 0}

    monkeypatch.setattr(
        redis_manager.redis,
        "Redis",
        lambda *args, **kwargs: single_node_client,
    )

    def _failing_cluster(*args, **kwargs):
        cluster_attempts["count"] += 1
        raise RedisClusterException("topology unreachable")

    monkeypatch.setattr(redis_manager, "RedisCluster", _failing_cluster)

    mgr = AzureRedisManager(
        host="example.redis.local",
        port=6380,
        access_key="dummy",
        ssl=False,
        credential=object(),
    )

    with pytest.raises(MovedError):
        mgr.get_session_data("session-123")

    # Cluster mode stays latched; we never fell back and re-hammered standalone.
    assert mgr.use_cluster is True
    assert mgr._cluster_required is True
    # One standalone HGETALL raised MOVED, then a single failed cluster rebuild
    # aborted the loop — no repeated standalone retries.
    assert single_node_client.hgetall_calls == 1
    assert cluster_attempts["count"] == 1


def test_cluster_initialization_falls_back_to_standalone(monkeypatch):
    standalone_client = _FakeClusterRedis()
    monkeypatch.setattr(
        redis_manager.redis,
        "Redis",
        lambda *args, **kwargs: standalone_client,
    )
    monkeypatch.setattr(
        redis_manager,
        "RedisCluster",
        lambda *args, **kwargs: (_ for _ in ()).throw(RedisClusterException("cluster unavailable")),
    )

    mgr = AzureRedisManager(
        host="example.redis.local",
        port=6380,
        access_key="dummy",
        ssl=False,
        credential=object(),
        use_cluster=True,
    )

    assert mgr.redis_client is standalone_client
    assert mgr.use_cluster is False


@pytest.mark.parametrize("result", [0, 1])
def test_non_snapshot_hash_updates_treat_hset_zero_as_success(result):
    mgr = object.__new__(AzureRedisManager)
    mgr.redis_client = Mock()
    mgr.redis_client.hset.return_value = result
    mgr._redis_span = lambda *args: nullcontext()
    mgr._execute_with_retry = Mock(side_effect=lambda command, fn: fn())
    assert mgr.store_session_data("session:one", {"metadata": "value"})
    mgr.redis_client.hset.assert_called_once_with("session:one", mapping={"metadata": "value"})


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [0, 1])
async def test_atomic_session_compare_and_set_uses_single_key_and_full_expected_snapshot(result):
    mgr = object.__new__(AzureRedisManager)
    mgr.redis_client = Mock()
    mgr._redis_span = lambda *args: nullcontext()
    mgr._execute_with_retry = Mock(side_effect=lambda command, fn: fn())
    expected = {"corememory": '{"active_agent":"Before"}', "chat_history": "{}"}
    updates = {"corememory": '{"active_agent":"After"}', "chat_history": "{}"}
    mgr.redis_client.eval.side_effect = lambda *args: [
        result,
        updates["corememory"],
        updates["chat_history"],
    ]

    stored = await mgr.compare_and_store_session_data_async(
        "session:one", updates, expected_data=expected
    )

    assert stored is bool(result)
    mgr.redis_client.eval.assert_called_once()
    script, key_count, key, receipts, operation_id, digest, ttl, expected_count, *pairs = (
        mgr.redis_client.eval.call_args.args
    )
    assert key_count == 1 and key == "session:one"
    assert expected_count == len(expected)
    assert receipts == "__session_write_receipts"
    assert len(operation_id) == 32 and len(digest) == 64 and ttl >= 60
    assert pairs[:4] == ["corememory", expected["corememory"], "chat_history", "{}"]
    assert pairs[4:] == ["corememory", updates["corememory"], "chat_history", "{}"]
    assert script.count("'HSET'") == 1
    assert script.index("'HGET'") < script.index("'HSET'")
    assert "return {0}" in script


@pytest.mark.asyncio
async def test_atomic_session_compare_and_set_propagates_persistence_failures():
    mgr = object.__new__(AzureRedisManager)
    mgr.redis_client = Mock()
    mgr.redis_client.eval.side_effect = RedisError("unavailable")
    mgr._redis_span = lambda *args: nullcontext()
    mgr._execute_with_retry = Mock(side_effect=lambda command, fn: fn())

    with pytest.raises(RedisError, match="unavailable"):
        await mgr.compare_and_store_session_data_async(
            "session:one", {"corememory": "{}"}, expected_data={}
        )
