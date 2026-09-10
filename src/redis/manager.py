import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from redis.cluster import RedisCluster
from redis.exceptions import (
    AuthenticationError,
    MovedError,
    RedisClusterException,
    RedisError,
    TimeoutError,
)
from redis.exceptions import ConnectionError as RedisConnectionError
from utils.azure_auth import get_credential
from utils.ml_logging import get_logger

import redis
from src.enums.monitoring import PeerService, SpanAttr

T = TypeVar("T")

AUTHORING_FIELDS = frozenset(
    {
        "session_agents_all",
        "active_session_agent",
        "session_scenarios_all",
        "session_scenario_config",
        "active_scenario_name",
        "scenario_name",
    }
)
ACTIVATION_FIELDS = frozenset(
    {
        "active_agent",
        "pending_handoff",
        "handoff_context",
        "visited_agents",
    }
)
AUTHORING_REVISION_KEY = "__authoring_revision"
_CAS_RECEIPTS_FIELD = "__session_write_receipts"
_CAS_RETRY_BUDGET_SECONDS = 30
_CAS_RECEIPT_TTL_SECONDS = 120


def merge_session_snapshot(
    current: Mapping[str, str],
    submitted: Mapping[str, str],
    *,
    authoring_fields: Collection[str] = (),
    registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
    runtime_changes: Collection[str] | None = None,
    revision: str | None = None,
) -> dict[str, str]:
    """Merge owned fields without changing the existing JSON session representation.

    Conversation writes cannot change committed authoring fields. Authoring
    writes only change explicitly named fields/registry entries, not histories
    or conversation state from the author's possibly stale snapshot.
    """
    previous = json.loads(current.get("corememory", "{}"))
    incoming = json.loads(submitted.get("corememory", "{}"))
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        raise ValueError("Session corememory must contain a JSON object")
    updates = registry_updates or {}
    authored = set(authoring_fields) | set(updates)
    if authored - (AUTHORING_FIELDS | {"active_agent"}):
        raise ValueError("Unsupported authoring field")
    if set(updates) - {"session_agents_all", "session_scenarios_all"}:
        raise ValueError("Unsupported authoring registry")

    if authored:
        result = {**submitted, **current}
        merged = dict(previous) if "corememory" in current else dict(incoming)
        for key in authoring_fields:
            if key in incoming:
                merged[key] = incoming[key]
            else:
                merged.pop(key, None)
        for key, changes in updates.items():
            registry = dict(merged.get(key) or {})
            for name, value in changes.items():
                for existing_name in list(registry):
                    if existing_name.lower() == name.lower():
                        del registry[existing_name]
                if value is not None:
                    registry[name] = value
            merged[key] = registry
        if "session_agents_all" in updates and "active_session_agent" not in authored:
            registry = merged.get("session_agents_all") or {}
            selected = previous.get("active_session_agent")
            actual = next(
                (name for name in registry if name.lower() == (selected or "").lower()), None
            )
            if actual is None:
                selected = incoming.get("active_session_agent")
                actual = next(
                    (name for name in registry if name.lower() == (selected or "").lower()), None
                )
                if actual is None:
                    actual = next(iter(sorted(registry)), None)
            merged["active_session_agent"] = actual
        deleted_scenarios = {
            name.lower()
            for name, value in updates.get("session_scenarios_all", {}).items()
            if value is None
        }
        if (
            previous.get("active_scenario_name") or previous.get("scenario_name") or ""
        ).lower() in deleted_scenarios and not {
            "active_scenario_name",
            "scenario_name",
            "session_scenario_config",
        } & authored:
            remaining = merged.get("session_scenarios_all") or {}
            next_name = next(iter(sorted(remaining)), None)
            next_config = remaining.get(next_name) if next_name else None
            merged["active_scenario_name"] = next_name
            merged["scenario_name"] = next_name
            merged["session_scenario_config"] = next_config
            if next_config and next_config.get("start_agent"):
                merged["active_agent"] = next_config["start_agent"]
        if any(
            previous.get(key) != merged.get(key)
            for key in ("active_scenario_name", "scenario_name", "session_scenario_config")
        ) or (
            "active_agent" in authoring_fields
            and previous.get("active_agent") != merged.get("active_agent")
        ):
            merged["pending_handoff"] = None
            merged["handoff_context"] = {}
            merged["visited_agents"] = []
        if AUTHORING_REVISION_KEY not in previous or any(
            previous.get(key) != merged.get(key) for key in authored
        ):
            merged[AUTHORING_REVISION_KEY] = revision or uuid.uuid4().hex
    else:
        result = {**current, **submitted}
        merged = dict(incoming)
        ownership_established = (
            AUTHORING_REVISION_KEY in previous
            or AUTHORING_REVISION_KEY in incoming
            or bool(AUTHORING_FIELDS & previous.keys())
        )
        if ownership_established:
            for key in AUTHORING_FIELDS:
                if key in previous:
                    merged[key] = previous[key]
                else:
                    merged.pop(key, None)
        changed_runtime = set(ACTIVATION_FIELDS if runtime_changes is None else runtime_changes)
        if runtime_changes is None and (
            incoming.get(AUTHORING_REVISION_KEY) != previous.get(AUTHORING_REVISION_KEY)
        ):
            changed_runtime.clear()
        if "active_agent" not in changed_runtime and (
            incoming.get("active_agent") != previous.get("active_agent")
        ):
            changed_runtime.clear()
        for key in ACTIVATION_FIELDS - changed_runtime:
            if key in previous:
                merged[key] = previous[key]
            else:
                merged.pop(key, None)
        if AUTHORING_REVISION_KEY in previous:
            merged[AUTHORING_REVISION_KEY] = previous[AUTHORING_REVISION_KEY]
        else:
            merged.pop(AUTHORING_REVISION_KEY, None)
    result.pop(_CAS_RECEIPTS_FIELD, None)
    result["corememory"] = json.dumps(merged)
    return result


class AzureRedisManager:
    """
    AzureRedisManager provides a simplified interface to connect, store,
    retrieve, and manage session data using Azure Cache for Redis.
    """

    @property
    def is_connected(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            return self.ping()
        except Exception as e:
            self.logger.error("Redis connection check failed: %s", e)
            return False

    def __init__(
        self,
        host: str | None = None,
        access_key: str | None = None,
        port: int | None = None,
        db: int = 0,
        ssl: bool = True,
        credential: object | None = None,  # For DefaultAzureCredential
        user_name: str | None = None,
        scope: str | None = None,
        use_cluster: bool | None = None,
    ):
        """
        Initialize the Redis connection.
        """
        self.logger = get_logger(__name__)
        self.host = host or os.getenv("REDIS_HOST")
        self.access_key = access_key or os.getenv("REDIS_ACCESS_KEY")

        # Handle port with better error message
        if port is not None and isinstance(port, int):
            self.port = port
        else:
            port_env = os.getenv("REDIS_PORT")
            if port_env:
                self.port = int(port_env)
            elif port is not None:
                self.port = int(port)
            else:
                # Default to 10000 for Azure Redis Enterprise
                self.port = 10000
                self.logger.warning("REDIS_PORT not set, defaulting to 10000")

        self.db = db
        self.ssl = ssl
        self.tracer = trace.get_tracer(__name__)
        use_cluster_env = os.getenv("REDIS_USE_CLUSTER") or os.getenv("REDIS_CLUSTER_MODE")
        if use_cluster is not None:
            self.use_cluster = use_cluster
        elif use_cluster_env is not None:
            self.use_cluster = str(use_cluster_env).lower() in {"1", "true", "yes", "on"}
        else:
            self.use_cluster = False
        # Set once a MOVED reply proves the endpoint is a cluster. When True we must
        # never silently fall back to a standalone client (doing so re-triggers MOVED
        # in an endless ping-pong), so cluster construction failures surface instead.
        self._cluster_required = False
        if not self.host:
            raise ValueError(
                "Redis host must be provided either as argument or environment variable."
            )
        if ":" in self.host:
            host_parts = self.host.rsplit(":", 1)
            if host_parts[1].isdigit():
                self.host = host_parts[0]
                self.port = int(host_parts[1])

        # AAD credential details
        self.credential = credential or get_credential()
        self.scope = scope or os.getenv("REDIS_SCOPE") or "https://redis.azure.com/.default"
        self.user_name = user_name or os.getenv("REDIS_USER_NAME") or "user"
        self._auth_expires_at = 0  # For AAD token refresh tracking

        # Build initial client and, if using AAD, start a refresh thread
        self.logger.debug("Redis cluster mode enabled: %s", self.use_cluster)
        self._create_client()
        if not self.access_key:
            t = threading.Thread(target=self._refresh_loop, daemon=True)
            t.start()

    async def initialize(self) -> None:
        """
        Async initialization method for FastAPI lifespan compatibility.

        Validates Redis connectivity and ensures proper initialization.
        This method is idempotent and can be called multiple times safely.
        """
        try:
            self.logger.debug(f"Validating Redis connection to {self.host}:{self.port}")

            # Validate connection with health check
            loop = asyncio.get_event_loop()
            ping_result = await loop.run_in_executor(None, self._health_check)

            if ping_result:
                self.logger.debug("✅ Redis connection validated successfully")
            else:
                raise ConnectionError("Redis health check failed")

        except Exception as e:
            self.logger.error(f"Redis initialization failed: {e}")
            raise ConnectionError(f"Failed to initialize Redis: {e}")

    def _health_check(self) -> bool:
        """
        Perform comprehensive health check on Redis connection.
        """
        try:
            if not self._execute_with_retry("PING", lambda: self.redis_client.ping()):
                return False

            test_key = "health_check_test"

            def _set():
                return self.redis_client.set(test_key, "test_value", ex=5)

            def _get():
                return self.redis_client.get(test_key)

            def _delete():
                return self.redis_client.delete(test_key)

            self._execute_with_retry("SET", _set)
            result = self._execute_with_retry("GET", _get)
            self._execute_with_retry("DEL", _delete)

            return result == "test_value"

        except Exception as e:
            self.logger.error(f"Redis health check failed: {e}")
            return False

    def _redis_span(self, name: str, op: str | None = None):
        host = (self.host or "").split(":")[0]
        return self.tracer.start_as_current_span(
            name,
            kind=SpanKind.CLIENT,
            attributes={
                SpanAttr.PEER_SERVICE: PeerService.AZURE_MANAGED_REDIS,
                SpanAttr.SERVER_ADDRESS: host,
                SpanAttr.SERVER_PORT: self.port or 6380,
                SpanAttr.DB_SYSTEM: "redis",
                **({"db.operation": op} if op else {}),
            },
        )

    def _execute_with_retry(
        self, command_name: str, operation: Callable[[], T], retries: int = 2
    ) -> T:
        """Execute a Redis operation with retry and intelligent reconfiguration."""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return operation()
            except AuthenticationError as auth_err:
                last_exc = auth_err
                self.logger.info(
                    "Redis authentication error on %s, refreshing credentials",
                    command_name,
                )
                self._create_client()
            except MovedError as moved_err:
                last_exc = moved_err
                self.logger.warning(
                    "Redis MOVED error on %s: %s. Enabling cluster mode and reconnecting.",
                    command_name,
                    moved_err,
                )
                # A MOVED reply is authoritative: the endpoint is an OSS-cluster.
                # Latch cluster mode so a transient build failure can't drop us back
                # to a standalone client that would just raise MOVED again.
                self.use_cluster = True
                self._cluster_required = True
                try:
                    self._create_client()
                except Exception as create_err:
                    # Cluster client couldn't be built (e.g. topology unreachable).
                    # Stop retrying and surface the original MOVED to the caller.
                    self.logger.error(
                        "Failed to switch to Redis cluster mode after MOVED on %s: %s",
                        command_name,
                        create_err,
                    )
                    break
            except (RedisConnectionError, TimeoutError, RedisError) as redis_err:
                last_exc = redis_err
                self.logger.warning(
                    "Redis error on %s (attempt %d/%d): %s",
                    command_name,
                    attempt + 1,
                    retries + 1,
                    redis_err,
                )
                if attempt >= retries:
                    break
                self._create_client()
            except RedisClusterException as cluster_err:
                # Handle cluster connection failures (e.g., "Redis Cluster cannot be connected")
                last_exc = cluster_err
                self.logger.warning(
                    "Redis cluster error on %s (attempt %d/%d): %s",
                    command_name,
                    attempt + 1,
                    retries + 1,
                    cluster_err,
                )
                if attempt >= retries:
                    break
                self._create_client()
            except OSError as os_err:
                # Handle "I/O operation on closed file" and similar socket errors
                last_exc = os_err
                self.logger.warning(
                    "Redis I/O error on %s (attempt %d/%d): %s",
                    command_name,
                    attempt + 1,
                    retries + 1,
                    os_err,
                )
                if attempt >= retries:
                    break
                self._create_client()
            except Exception as exc:  # pragma: no cover - safeguard
                last_exc = exc
                self.logger.error("Unexpected Redis error on %s: %s", command_name, exc)
                break

        if last_exc:
            raise last_exc
        raise RedisError(f"Redis command {command_name} failed without exception")

    def _create_client(self):
        """(Re)create Redis client and record expiry for AAD if needed."""
        common_kwargs = {
            "host": self.host,
            "port": self.port,
            "ssl": self.ssl,
            "decode_responses": True,
            "socket_keepalive": True,
            "health_check_interval": 30,
            "socket_connect_timeout": 0.2,
            "socket_timeout": 1.0,
            "max_connections": 200,
            "client_name": "artagent-api",
        }

        cluster_kwargs = {
            **common_kwargs,
            "require_full_coverage": False,
            "reinitialize_steps": 1,
            "read_from_replicas": os.getenv("REDIS_READ_FROM_REPLICAS", "false").lower()
            in {"1", "true", "yes", "on"},
            # Topology discovery has to reach every shard node during CLUSTER
            # SLOTS/NODES; the standalone 0.2s connect budget is too tight and makes
            # cluster init flap on transient latency. Give discovery more headroom.
            "socket_connect_timeout": float(os.getenv("REDIS_CLUSTER_CONNECT_TIMEOUT", "5.0")),
            "socket_timeout": float(os.getenv("REDIS_CLUSTER_SOCKET_TIMEOUT", "5.0")),
        }

        if self.access_key:
            auth_kwargs = {"password": self.access_key}
        else:
            token = self.credential.get_token(self.scope)
            self.token_expiry = token.expires_on
            auth_kwargs = {"username": self.user_name, "password": token.token}

        try:
            if self.use_cluster:
                cluster_kwargs.update(auth_kwargs)
                cluster_kwargs.pop("db", None)
                cluster_kwargs.setdefault("ssl_cert_reqs", None)
                cluster_kwargs.setdefault("ssl_check_hostname", False)
                self.redis_client = RedisCluster(**cluster_kwargs)
                self.logger.debug(
                    "Azure Redis connection initialized in cluster mode (use_cluster=%s).",
                    self.use_cluster,
                )
            else:
                standalone_kwargs = {**common_kwargs, "db": self.db, **auth_kwargs}
                self.redis_client = redis.Redis(**standalone_kwargs)
                self.logger.debug("Azure Redis connection initialized in standalone mode.")
        except RedisClusterException as exc:
            if self._cluster_required:
                # A prior MOVED proved this endpoint requires cluster mode; falling
                # back to standalone would just loop on MOVED. Surface the error.
                self.logger.error(
                    "Redis cluster initialization failed and cluster mode is required "
                    "(endpoint returned MOVED); not falling back to standalone: %s",
                    exc,
                )
                raise
            self.logger.warning(
                "Redis cluster initialization failed (will try standalone): %s", exc
            )
            self.logger.debug("Falling back to standalone Redis client.")
            standalone_kwargs = {**common_kwargs, "db": self.db, **auth_kwargs}
            self.redis_client = redis.Redis(**standalone_kwargs)
            self.use_cluster = False
        except Exception as exc:
            self.logger.error("Redis client initialization error: %s", exc)
            raise

        if not self.access_key:
            self.logger.debug(
                "Azure Redis connection initialized with AAD token (expires at %s).",
                getattr(self, "token_expiry", "unknown"),
            )

    def _refresh_loop(self):
        """Background thread: sleep until just before expiry, then refresh token."""
        while True:
            now = int(time.time())
            # sleep until 60s before expiry
            wait = max(self.token_expiry - now - 60, 1)
            time.sleep(wait)
            try:
                self.logger.debug("Refreshing Azure Redis AAD token in background...")
                self._create_client()
            except Exception as e:
                self.logger.error("Failed to refresh Redis token: %s", e)
                # retry sooner if something goes wrong
                time.sleep(5)

    def publish_event(self, stream_key: str, event_data: dict[str, Any]) -> str:
        """Append an event to a Redis stream."""

        def _xadd():
            with self._redis_span("Redis.XADD"):
                return self.redis_client.xadd(stream_key, event_data)

        return self._execute_with_retry("XADD", _xadd)

    def read_events_blocking(
        self,
        stream_key: str,
        last_id: str = "$",
        block_ms: int = 30000,
        count: int = 1,
    ) -> list[dict[str, Any]] | None:
        """
        Block and read new events from a Redis stream starting after `last_id`.
        Returns list of new events (or None on timeout).
        """

        def _xread():
            with self._redis_span("Redis.XREAD"):
                streams = self.redis_client.xread(
                    {stream_key: last_id}, block=block_ms, count=count
                )
                return streams if streams else None

        return self._execute_with_retry("XREAD", _xread)

    async def publish_event_async(self, stream_key: str, event_data: dict[str, Any]) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.publish_event, stream_key, event_data)

    async def read_events_blocking_async(
        self,
        stream_key: str,
        last_id: str = "$",
        block_ms: int = 30000,
        count: int = 1,
    ) -> list[dict[str, Any]] | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.read_events_blocking, stream_key, last_id, block_ms, count
        )

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            with self._redis_span("Redis.PING"):
                return self.redis_client.ping()
        except AuthenticationError:
            # token might have expired early: rebuild & retry once
            self.logger.info("Redis auth error on ping, refreshing token")
            self._create_client()
            with self._redis_span("Redis.PING"):
                return self.redis_client.ping()

    def set_value(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """Set a string value in Redis (optionally with TTL)."""

        def _set_operation():
            with self._redis_span("Redis.SET"):
                if ttl_seconds is not None:
                    return self.redis_client.setex(key, ttl_seconds, str(value))
                return self.redis_client.set(key, str(value))

        return self._execute_with_retry("SET", _set_operation)

    def get_value(self, key: str) -> str | None:
        """Get a string value from Redis."""

        def _get_operation():
            with self._redis_span("Redis.GET"):
                value = self.redis_client.get(key)
                return value.decode() if isinstance(value, bytes) else value

        return self._execute_with_retry("GET", _get_operation)

    def publish_channel(self, channel: str, message: str) -> int:
        """Publish a message to a Redis channel."""

        def _publish_operation():
            with self._redis_span("Redis.PUBLISH"):
                return self.redis_client.publish(channel, str(message))

        return self._execute_with_retry("PUBLISH", _publish_operation)

    async def publish_channel_async(self, channel: str, message: str) -> int:
        """Async helper for publishing to a Redis channel."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.publish_channel,
            channel,
            message,
        )

    def store_session_data(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        authoring_fields: Collection[str] = (),
        registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
        runtime_changes: Collection[str] | None = None,
    ) -> bool:
        """Store a session with atomic field ownership and optimistic conflict detection.

        On success, ``data`` contains the persisted/acknowledged snapshot so
        MemoManager can learn current authoring state without replacing live
        conversation changes made while the write was in flight.
        """
        if "corememory" in data:
            submitted = dict(data)
            revision = uuid.uuid4().hex
            for _ in range(4):
                current = self.get_session_data(session_id)
                merged = merge_session_snapshot(
                    current,
                    submitted,
                    authoring_fields=authoring_fields,
                    registry_updates=registry_updates,
                    runtime_changes=runtime_changes,
                    revision=revision,
                )
                if self._compare_and_store_session_data(session_id, merged, expected_data=current):
                    data.clear()
                    data.update(merged)
                    return True
            raise RedisError("Session changed repeatedly during persistence; retry the write")

        def _hset_operation():
            with self._redis_span("Redis.HSET"):
                # HSET returns the number of *new* fields added, not a
                # success indicator.  Updating existing fields returns 0,
                # which is perfectly normal.  If the call raises, the retry
                # wrapper handles it; reaching this point means success.
                self.redis_client.hset(session_id, mapping=data)
                return True

        return self._execute_with_retry("HSET", _hset_operation)

    def get_session_data(self, session_id: str) -> dict[str, str]:
        """Retrieve all session data for a given session ID."""

        def _hgetall_operation():
            with self._redis_span("Redis.HGETALL"):
                raw = self.redis_client.hgetall(session_id)
                return {key: value for key, value in raw.items() if key != _CAS_RECEIPTS_FIELD}

        return self._execute_with_retry("HGETALL", _hgetall_operation)

    def update_session_field(self, session_id: str, field: str, value: str) -> bool:
        """Update a single field in the session hash."""
        if field == "corememory":
            return self.store_session_data(session_id, {field: value})

        def _hset_field_operation():
            with self._redis_span("Redis.HSET"):
                return bool(self.redis_client.hset(session_id, field, value))

        return self._execute_with_retry("HSET_FIELD", _hset_field_operation)

    def delete_session(self, session_id: str) -> int:
        """Delete a session from Redis."""

        def _delete_operation():
            with self._redis_span("Redis.DEL"):
                return self.redis_client.delete(session_id)

        return self._execute_with_retry("DEL", _delete_operation)

    def list_connected_clients(self) -> list[dict[str, str]]:
        """List currently connected clients."""

        def _client_list_operation():
            with self._redis_span("Redis.CLIENTLIST"):
                return self.redis_client.client_list()

        return self._execute_with_retry("CLIENT_LIST", _client_list_operation)

    async def store_session_data_async(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        authoring_fields: Collection[str] = (),
        registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
        runtime_changes: Collection[str] | None = None,
    ) -> bool:
        """Async version using thread pool executor."""
        try:
            return await asyncio.to_thread(
                self.store_session_data,
                session_id,
                data,
                authoring_fields=authoring_fields,
                registry_updates=registry_updates,
                runtime_changes=runtime_changes,
            )
        except asyncio.CancelledError:
            self.logger.debug(f"store_session_data_async cancelled for session {session_id}")
            # Don't log as warning - cancellation is normal during shutdown
            raise
        except Exception as e:
            self.logger.error(f"Error in store_session_data_async for session {session_id}: {e}")
            return False

    async def compare_and_store_session_data_async(
        self,
        session_id: str,
        data: dict[str, str],
        *,
        expected_data: dict[str, str],
    ) -> bool:
        """Commit a validated authoring snapshot, with idempotent acknowledgement retries."""
        if "corememory" in data:
            prepared = merge_session_snapshot(
                expected_data,
                data,
                authoring_fields=AUTHORING_FIELDS | {"active_agent"},
            )
            data.clear()
            data.update(prepared)
        return await asyncio.to_thread(
            self._compare_and_store_session_data, session_id, data, expected_data=expected_data
        )

    def _compare_and_store_session_data(
        self,
        session_id: str,
        data: dict[str, str],
        *,
        expected_data: Mapping[str, str],
    ) -> bool:
        """One linearizable write; retries acknowledge the same operation, never reapply it."""
        operation_id = uuid.uuid4().hex
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        started = time.monotonic()
        script = """
local receipts_field = ARGV[1]
local operation_id = ARGV[2]
local digest = ARGV[3]
local now = tonumber(redis.call('TIME')[1])
local encoded_receipts = redis.call('HGET', KEYS[1], receipts_field)
local receipts = cjson.decode(encoded_receipts or '{}')
local receipt = receipts[operation_id]
if receipt and receipt.expires >= now then
    if receipt.digest ~= digest then
        return redis.error_reply('Session operation identifier reused with different data')
    end
    return {1, redis.call('HGET', KEYS[1], 'corememory') or '',
               redis.call('HGET', KEYS[1], 'chat_history') or ''}
end
local count = tonumber(ARGV[5])
local internal_count = encoded_receipts and 1 or 0
if redis.call('HLEN', KEYS[1]) - internal_count ~= count then return {0} end
for i = 1, count do
    local offset = 6 + (i - 1) * 2
    if redis.call('HGET', KEYS[1], ARGV[offset]) ~= ARGV[offset + 1] then
        return {0}
    end
end
for id, value in pairs(receipts) do
    if value.expires < now then receipts[id] = nil end
end
receipts[operation_id] = {digest = digest, expires = now + tonumber(ARGV[4])}
local updates = {}
for i = 6 + count * 2, #ARGV do
    updates[#updates + 1] = ARGV[i]
end
updates[#updates + 1] = receipts_field
updates[#updates + 1] = cjson.encode(receipts)
redis.call('HSET', KEYS[1], unpack(updates))
return {1, redis.call('HGET', KEYS[1], 'corememory') or '',
           redis.call('HGET', KEYS[1], 'chat_history') or ''}
"""
        expected_data = {
            key: value for key, value in expected_data.items() if key != _CAS_RECEIPTS_FIELD
        }
        args: list[str | int] = [
            _CAS_RECEIPTS_FIELD,
            operation_id,
            digest,
            _CAS_RECEIPT_TTL_SECONDS,
            len(expected_data),
        ]
        for name, value in expected_data.items():
            args.extend((name, value))
        for name, value in data.items():
            args.extend((name, value))

        def compare_and_store() -> bool:
            # Never retry beyond the server's receipt retention window.
            if time.monotonic() - started > _CAS_RETRY_BUDGET_SECONDS:
                raise TimeoutError("Session commit acknowledgement timed out")
            with self._redis_span("Redis.CAS"):
                result = self.redis_client.eval(script, 1, session_id, *args)
            if not result[0]:
                return False
            for field, value in zip(("corememory", "chat_history"), result[1:], strict=True):
                if value:
                    data[field] = value
            return True

        return self._execute_with_retry("SESSION_CAS", compare_and_store)

    async def get_session_data_async(
        self, session_id: str, *, raise_on_failure: bool = False
    ) -> dict[str, str]:
        """Read through the executor, optionally distinguishing failure from an empty hash."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_session_data, session_id)
        except asyncio.CancelledError:
            self.logger.debug(f"get_session_data_async cancelled for session {session_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error in get_session_data_async for session {session_id}: {e}")
            if raise_on_failure:
                raise
            return {}

    async def update_session_field_async(self, session_id: str, field: str, value: str) -> bool:
        """Async version of update_session_field using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.update_session_field, session_id, field, value
            )
        except asyncio.CancelledError:
            self.logger.debug(f"update_session_field_async cancelled for session {session_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error in update_session_field_async for session {session_id}: {e}")
            return False

    async def delete_session_async(self, session_id: str) -> int:
        """Async version of delete_session using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.delete_session, session_id)
        except asyncio.CancelledError:
            self.logger.debug(f"delete_session_async cancelled for session {session_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error in delete_session_async for session {session_id}: {e}")
            return 0

    async def get_value_async(self, key: str) -> str | None:
        """Async version of get_value using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.get_value, key)
        except asyncio.CancelledError:
            self.logger.debug(f"get_value_async cancelled for key {key}")
            raise
        except Exception as e:
            self.logger.error(f"Error in get_value_async for key {key}: {e}")
            return None

    async def set_value_async(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """Async version of set_value using thread pool executor."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.set_value, key, value, ttl_seconds)
        except asyncio.CancelledError:
            self.logger.debug(f"set_value_async cancelled for key {key}")
            raise
        except Exception as e:
            self.logger.error(f"Error in set_value_async for key {key}: {e}")
            return False
