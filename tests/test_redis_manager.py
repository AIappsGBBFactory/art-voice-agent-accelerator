import pytest

from redis.exceptions import MovedError

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
    assert mgr._using_cluster is True


def test_get_session_data_raises_without_cluster_support(monkeypatch):
    single_node_client = _FakeRedis()

    monkeypatch.setattr(
        redis_manager.redis,
        "Redis",
        lambda *args, **kwargs: single_node_client,
    )
    monkeypatch.setattr(redis_manager, "RedisCluster", None, raising=False)

    mgr = AzureRedisManager(
        host="example.redis.local",
        port=6380,
        access_key="dummy",
        ssl=False,
        credential=object(),
    )

    with pytest.raises(MovedError):
        mgr.get_session_data("session-123")


def test_remap_cluster_address_to_domain(monkeypatch):
    fake_client = object()
    monkeypatch.setattr(
        redis_manager.redis, "Redis", lambda *args, **kwargs: fake_client
    )
    monkeypatch.setattr(
        redis_manager, "RedisCluster", lambda *args, **kwargs: fake_client
    )

    mgr = AzureRedisManager(
        host="example.redis.local",
        port=6380,
        access_key="dummy",
        ssl=False,
        credential=object(),
    )

    # IP addresses remap to canonical host
    assert mgr._remap_cluster_address(("51.8.10.248", 8501)) == (
        "example.redis.local",
        8501,
    )
    # Hostnames remain unchanged
    assert mgr._remap_cluster_address(("cache.contoso.redis", 8501)) == (
        "cache.contoso.redis",
        8501,
    )
