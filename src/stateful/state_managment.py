"""
Real-Time Voice Agent State Management Module.

This module provides comprehensive state management for real-time voice agent sessions
through the MemoManager class. It manages conversation state, core memory, and chat
history with Redis persistence and live-refresh capabilities.

Key Features:
- Session-based conversation management with unique session IDs
- Core memory storage for agent context and configuration
- Multi-agent chat history tracking with thread separation
- Redis-based persistence with async/sync operations
- Live data refresh and selective update mechanisms
- TTS interrupt handling and queue management
- Tool output persistence and slot-based state management
- Latency tracking for performance monitoring
- MCP (Model Context Protocol) session management for external tool servers

The MemoManager extends basic memory management with live-refresh helpers that
keep local state synchronized with a shared Redis cache, enabling real-time
collaboration and state sharing across distributed voice agent instances.

Classes:
    MemoManager: Primary class for managing voice agent session state

Example:
    ```python
    # Initialize session manager
    manager = MemoManager(session_id="session_123")

    # Add conversation history
    manager.append_to_history("agent1", "user", "Hello")
    manager.append_to_history("agent1", "assistant", "Hi there!")

    # Persist to Redis
    await manager.persist_to_redis_async(redis_mgr)

    # Refresh from live data
    await manager.refresh_from_redis_async(redis_mgr)
    ```
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from utils.ml_logging import get_logger

from src.agenticmemory.playback_queue import MessageQueue
from src.agenticmemory.types import ChatHistory, CoreMemory
from src.agenticmemory.utils import LatencyTracker

# TODO Fix this area
from src.redis.manager import (
    ACTIVATION_FIELDS,
    AUTHORING_FIELDS,
    AUTHORING_REVISION_KEY,
    AzureRedisManager,
)
from src.tools.latency_helpers import PersistentLatency, StageSample

if TYPE_CHECKING:
    from apps.artagent.backend.registries.toolstore.mcp import (
        MCPServerConfig,
        MCPSessionManager,
    )

logger = get_logger("src.stateful.state_managment")


@dataclass
class _PendingWrite:
    sequence: int
    redis_mgr: AzureRedisManager
    snapshot: dict[str, str]
    ttl_seconds: int | None
    background: bool
    completion: asyncio.Future[Exception | None]
    authoring_fields: tuple[str, ...]
    registry_updates: dict[str, dict[str, Any]] | None
    runtime_changes: tuple[str, ...]


class MemoManager:
    """
    Manages conversation session state for real-time voice agents.

    The MemoManager is the central component for handling voice agent sessions,
    providing comprehensive state management including core memory, chat history,
    message queuing, and Redis persistence with live-refresh capabilities.

    This class maintains session-scoped state that persists across WebSocket
    connections and enables real-time collaboration between distributed agent
    instances through Redis-based synchronization.

    Attributes:
        session_id (str): Unique identifier for the conversation session
        chatHistory (ChatHistory): Multi-agent conversation history manager
        corememory (CoreMemory): Persistent key-value store for agent context
        message_queue (MessageQueue): Sequential message playback queue
        latency (LatencyTracker): Performance monitoring for operation timing

    Redis Keys:
        - corememory: Agent context, slots, tool outputs, and configuration
        - chat_history: Multi-agent conversation threads and message history

    Example:
        ```python
        # Basic session management
        manager = MemoManager("session_123")
        manager.set_context("user_id", "user_456")
        manager.append_to_history("agent1", "user", "Hello")

        # Redis persistence
        await manager.persist_to_redis_async(redis_mgr)
        ```

    Note:
        Session IDs are truncated to 8 characters for readability while
        maintaining sufficient uniqueness for concurrent sessions.
    """

    _CORE_KEY = "corememory"
    _HISTORY_KEY = "chat_history"

    def __init__(
        self,
        session_id: str | None = None,
        redis_mgr: AzureRedisManager | None = None,
    ) -> None:
        """
        Initialize a new MemoManager instance for session state management.

        Creates a new conversation session with unique identification and
        initializes all required state management components including
        chat history, core memory, message queue, and performance tracking.

        Args:
            session_id (Optional[str]): Unique session identifier. If None,
                generates a new UUID4 truncated to 8 characters for readability.
            redis_mgr (Optional[AzureRedisManager]): Redis connection manager
                for persistence operations. Can be set later via method calls.

        Attributes Initialized:
            - session_id: Session identifier (generated if not provided)
            - chatHistory: Empty ChatHistory instance for conversation tracking
            - corememory: Empty CoreMemory instance for persistent context
            - message_queue: MessageQueue for sequential TTS playback
            - latency: LatencyTracker for performance monitoring
            - _is_tts_interrupted: Flag for TTS interruption state
            - _redis_manager: Stored Redis manager for persistence
            - _mcp_manager: MCPSessionManager for MCP server connections

        Example:
            ```python
            # Auto-generate session ID
            manager = MemoManager()

            # Specific session with Redis manager
            manager = MemoManager(
                session_id="custom_session",
                redis_mgr=redis_manager
            )
            )
            ```

        Note:
            Session IDs are limited to 8 characters to balance uniqueness
            with readability in logs and debugging output.
        """
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self.chatHistory: ChatHistory = ChatHistory()
        self.corememory: CoreMemory = CoreMemory()
        self.message_queue = MessageQueue()
        self._is_tts_interrupted: bool = False
        self.latency = LatencyTracker()
        self._redis_manager: AzureRedisManager | None = redis_mgr
        self._pending_persist_task: asyncio.Task[None] | None = None
        self._persist_queue: deque[_PendingWrite] = deque()
        self._active_persist: _PendingWrite | None = None
        self._persist_sequence = 0
        self._persist_failures: deque[tuple[int, Exception]] = deque()
        self._persist_writer_error: RuntimeError | None = None
        self._mcp_manager: MCPSessionManager | None = None
        self._turn_sequence: int = 0  # Track turn segments for tool call boundaries
        self._activation_baseline: dict[str, Any] = {}
        self._authoring_baseline: dict[str, Any] = {}
        now = time.time()
        self.corememory.set("created_at", now)
        self.corememory.set("last_activity", now)
        self.corememory.set(
            "session_info",
            {"created_at": now, "last_activity": now},
        )

    # ------------------------------------------------------------------
    # Compatibility aliases
    # TODO Fix
    # ------------------------------------------------------------------
    @property
    def histories(self) -> dict[str, list[dict[str, str]]]:  # noqa: D401
        return self.chatHistory.get_all()

    @histories.setter
    def histories(self, value: dict[str, list[dict[str, str]]]) -> None:  # noqa: D401
        self.chatHistory._threads = value  # direct assignment

    @property
    def context(self) -> dict[str, Any]:  # noqa: D401
        return self.corememory._store

    @context.setter
    def context(self, value: dict[str, Any]) -> None:  # noqa: D401
        self.corememory._store = value

    # single‑history alias for minimal diff elsewhere
    @property
    def history(self) -> ChatHistory:  # noqa: D401
        return self.chatHistory

    @staticmethod
    def build_redis_key(session_id: str) -> str:
        """
        Construct the Redis key for session data storage.

        Generates a standardized Redis key format for storing session state
        data, ensuring consistent key naming across the application.

        Args:
            session_id (str): Unique session identifier

        Returns:
            str: Formatted Redis key in the format "session:{session_id}"

        Example:
            ```python
            key = MemoManager.build_redis_key("abc12345")
            # Returns: "session:abc12345"
            ```

        Note:
            This method is static to allow key construction without
            instantiating a MemoManager object, useful for Redis
            operations outside of the manager context.
        """
        return f"session:{session_id}"

    def to_redis_dict(self) -> dict[str, str]:
        """
        Serialize session state to Redis-compatible dictionary format.

        Converts the current session state (core memory and chat history)
        into a dictionary with JSON-serialized values suitable for Redis storage.

        Returns:
            Dict[str, str]: Dictionary containing serialized session data with keys:
                - 'corememory': JSON string of core memory state
                - 'chat_history': JSON string of chat history data

        Example:
            ```python
            manager.set_context("user_name", "Alice")
            manager.append_to_history("agent1", "user", "Hello")

            redis_data = manager.to_redis_dict()
            # Returns: {
            #     'corememory': '{"user_name": "Alice"}',
            #     'chat_history': '{"agent1": [{"role": "user", "content": "Hello"}]}'
            # }
            ```

        Note:
            The returned dictionary contains JSON strings as values, ready
            for direct storage in Redis hash fields. Both fields are captured
            without yielding on the owning event loop. State must not be
            mutated from other threads.
        """
        return {
            self._CORE_KEY: self.corememory.to_json(),
            self._HISTORY_KEY: self.chatHistory.to_json(),
        }

    def _capture_activation_baseline(self) -> None:
        self._activation_baseline = {
            key: copy.deepcopy(self.context[key])
            for key in ACTIVATION_FIELDS
            if key in self.context
        }
        self._authoring_baseline = {
            key: copy.deepcopy(self.context[key]) for key in AUTHORING_FIELDS if key in self.context
        }

    def _changed_activation_fields(self, submitted_core: str) -> tuple[str, ...]:
        submitted = json.loads(submitted_core)
        return tuple(
            sorted(
                key
                for key in ACTIVATION_FIELDS
                if (key in submitted) != (key in self._activation_baseline)
                or submitted.get(key) != self._activation_baseline.get(key)
            )
        )

    def _acknowledge_session_write(
        self,
        submitted_core: str,
        persisted_core: str,
        *,
        expected_revision: str | None,
        authoring_fields: Collection[str] = (),
        registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """Learn server-owned config without disguising stale runtime state as a handoff."""
        submitted = json.loads(submitted_core)
        persisted = json.loads(persisted_core)
        authored = set(authoring_fields) | set(registry_updates or {})
        resets_activation = any(
            key in authored
            and ((key in submitted) != (key in baseline) or submitted.get(key) != baseline.get(key))
            for key, baseline in (
                ("active_agent", self._activation_baseline),
                ("active_scenario_name", self._authoring_baseline),
                ("scenario_name", self._authoring_baseline),
                ("session_scenario_config", self._authoring_baseline),
            )
        )
        if self.context.get(AUTHORING_REVISION_KEY) == expected_revision:
            for key in AUTHORING_FIELDS:
                if not any(
                    (key in self.context) == (key in baseline)
                    and self.context.get(key) == baseline.get(key)
                    for baseline in (submitted, self._authoring_baseline)
                ):
                    continue
                if key in persisted:
                    self.corememory.set(key, persisted[key])
                else:
                    self.context.pop(key, None)
            if AUTHORING_REVISION_KEY in persisted:
                self.corememory.set(AUTHORING_REVISION_KEY, persisted[AUTHORING_REVISION_KEY])
            else:
                self.context.pop(AUTHORING_REVISION_KEY, None)
            self._authoring_baseline = {
                key: copy.deepcopy(persisted[key]) for key in AUTHORING_FIELDS if key in persisted
            }
        # Keep this memo's own activation baseline. Adopting the server's active
        # agent here would make the next stale orchestrator sync look like a new
        # handoff. An explicit Redis refresh resets the baseline instead.
        acknowledged = ACTIVATION_FIELDS if not authored else ACTIVATION_FIELDS & authored
        if resets_activation:
            acknowledged |= ACTIVATION_FIELDS - {"active_agent"}
        for key in acknowledged:
            if key in submitted:
                self._activation_baseline[key] = submitted[key]
            else:
                self._activation_baseline.pop(key, None)

    @classmethod
    def from_redis(cls, session_id: str, redis_mgr: AzureRedisManager) -> "MemoManager":
        """
        Create a MemoManager instance from existing Redis session data.

        Factory method that reconstructs a session manager from previously
        persisted Redis data, restoring both core memory and chat history.

        Args:
            session_id (str): Unique session identifier to load
            redis_mgr (AzureRedisManager): Redis connection manager for data retrieval

        Returns:
            MemoManager: New instance with state loaded from Redis

        Example:
            ```python
            # Load existing session
            manager = MemoManager.from_redis("session_123", redis_mgr)

            # Access restored state
            user_name = manager.get_context("user_name")
            history = manager.get_history("agent1")
            ```

        Note:
            If no data exists in Redis for the given session_id, returns
            a new MemoManager with empty state. Missing core memory or
            chat history fields are handled gracefully.
        """
        key = cls.build_redis_key(session_id)
        data = redis_mgr.get_session_data(key)
        mm = cls(session_id=session_id)
        if mm._CORE_KEY in data:
            mm.corememory.from_json(data[mm._CORE_KEY])
        if mm._HISTORY_KEY in data:
            mm.chatHistory.from_json(data[mm._HISTORY_KEY])
        mm._capture_activation_baseline()
        return mm

    @classmethod
    def from_redis_with_manager(
        cls, session_id: str, redis_mgr: AzureRedisManager
    ) -> "MemoManager":
        """
        Create a MemoManager with stored Redis manager reference.

        Factory method that creates a session manager from Redis data while
        storing the Redis manager instance for future operations.

        Args:
            session_id (str): Unique session identifier to load
            redis_mgr (AzureRedisManager): Redis connection manager to store and use

        Returns:
            MemoManager: New instance with state loaded from Redis and manager stored

        Example:
            ```python
            manager = MemoManager.from_redis_with_manager("session_123", redis_mgr)
            await manager.persist()  # Uses stored manager
            ```
        """
        key = cls.build_redis_key(session_id)
        data = redis_mgr.get_session_data(key)
        mm = cls(session_id=session_id, redis_mgr=redis_mgr)
        if data:
            if cls._CORE_KEY in data:
                mm.corememory.from_json(data[cls._CORE_KEY])
            if cls._HISTORY_KEY in data:
                mm.chatHistory.from_json(data[cls._HISTORY_KEY])
        mm._capture_activation_baseline()
        return mm

    @classmethod
    async def from_redis_async(cls, session_id: str, redis_mgr: AzureRedisManager) -> MemoManager:
        """Restore state without blocking the event loop, retaining the Redis manager.

        Uses the same keys, decoding and missing-field defaults as
        ``from_redis_with_manager``. Redis read errors, invalid JSON and
        cancellation propagate; only a genuinely absent hash creates new state.
        """
        data = await redis_mgr.get_session_data_async(
            cls.build_redis_key(session_id), raise_on_failure=True
        )
        mm = cls(session_id=session_id, redis_mgr=redis_mgr)
        if cls._CORE_KEY in data:
            mm.corememory.from_json(data[cls._CORE_KEY])
        if cls._HISTORY_KEY in data:
            mm.chatHistory.from_json(data[cls._HISTORY_KEY])
        mm._capture_activation_baseline()
        return mm

    async def persist(self, redis_mgr: AzureRedisManager | None = None) -> None:
        """
        Persist session state to Redis using stored or provided manager.

        Convenience method that persists current session state to Redis
        using either the provided Redis manager or the stored instance.

        Args:
            redis_mgr (Optional[AzureRedisManager]): Redis manager to use.
                If None, uses the stored manager from initialization.

        Raises:
            ValueError: If no Redis manager is available (neither provided
                nor stored during initialization).

        Example:
            ```python
            # With stored manager
            manager = MemoManager(redis_mgr=redis_mgr)
            await manager.persist()

            # With provided manager
            manager = MemoManager()
            await manager.persist(redis_mgr)
            ```

        Note:
            For a checked durability boundary, use
            ``persist_to_redis_async(..., raise_on_failure=True)`` instead.
        """
        mgr = redis_mgr or self._redis_manager
        if not mgr:
            raise ValueError("No Redis manager available")
        await self.persist_to_redis_async(mgr)

    def persist_to_redis(
        self,
        redis_mgr: AzureRedisManager,
        ttl_seconds: int | None = None,
        *,
        authoring_fields: Collection[str] = (),
        registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """
        Synchronously persist session state to Redis.

        Stores the current session state (core memory and chat history) to Redis
        using synchronous operations. Optionally sets an expiration time for
        automatic cleanup of inactive sessions.

        Args:
            redis_mgr (AzureRedisManager): Redis connection manager for persistence
            ttl_seconds (Optional[int]): Time-to-live in seconds for session data.
                If None, data persists indefinitely until manually deleted.

        Example:
            ```python
            # Persist without expiration
            manager.persist_to_redis(redis_mgr)

            # Persist with 1-hour expiration
            manager.persist_to_redis(redis_mgr, ttl_seconds=3600)
            ```

        Logging:
            Logs successful persistence with session statistics including
            history counts per agent and core memory keys.

        Note:
            Use the async version (persist_to_redis_async) in async contexts
            to avoid blocking the event loop. A synchronous write is rejected
            while this instance has async persistence outstanding.
        """
        if self._pending_persist_task and self._pending_persist_task.done():
            self._check_persist_writer(self._pending_persist_task)
        if self._persist_writer_error is not None:
            raise self._persist_writer_error
        if self._pending_persist_task and not self._pending_persist_task.done():
            raise RuntimeError("Flush pending persistence before a synchronous write")
        key = self.build_redis_key(self.session_id)
        data = self.to_redis_dict()
        submitted_core = data[self._CORE_KEY]
        expected_revision = self.context.get(AUTHORING_REVISION_KEY)
        success = redis_mgr.store_session_data(
            key,
            data,
            authoring_fields=authoring_fields,
            registry_updates=registry_updates,
            runtime_changes=self._changed_activation_fields(submitted_core),
        )
        if not success:
            raise RuntimeError(f"Redis write returned failure for session {self.session_id}")
        self._acknowledge_session_write(
            submitted_core,
            data[self._CORE_KEY],
            expected_revision=expected_revision,
            authoring_fields=authoring_fields,
            registry_updates=registry_updates,
        )
        if ttl_seconds:
            if not redis_mgr.redis_client.expire(key, ttl_seconds):
                raise RuntimeError(f"Redis expiry returned failure for session {self.session_id}")
        logger.info(
            "session.persist session=%s mode=sync history=[%s] ctx=%d",
            self.session_id,
            ", ".join(f"{a}:{len(h)}" for a, h in self.histories.items()),
            len(self.context),
        )

    async def persist_to_redis_async(
        self,
        redis_mgr: AzureRedisManager,
        ttl_seconds: int | None = None,
        *,
        raise_on_failure: bool = False,
        authoring_fields: Collection[str] = (),
        registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> bool:
        """
        Persist a whole-state snapshot through this instance's ordered writer.

        Direct writes are FIFO barriers and are never coalesced. True means this
        snapshot's write and requested expiry completed. Failure is logged and
        returns False, or raises when ``raise_on_failure`` is True. Cancelling
        the caller stops waiting, not the queued or executor-backed Redis write;
        ``flush_pending_persist`` can subsequently wait for its outcome.

        Args:
            redis_mgr (AzureRedisManager): Redis connection manager for persistence
            ttl_seconds (Optional[int]): Time-to-live in seconds for session data.
                If None, data persists indefinitely.
            raise_on_failure (bool): When True, raise on write failure instead of
                silently returning False. Use this in code paths where the caller
                **must** know whether persistence succeeded (e.g. scenario creation).
            authoring_fields: Explicit configuration fields owned by this write.
                Ordinary conversation persistence must leave this empty.
            registry_updates: Per-name replacements/deletions in authoring registries;
                None values delete entries. Other records and conversation history
                are preserved atomically.

        Ordering is per instance on its owning event loop. Redis atomically
        preserves authoring-owned fields across independent conversation
        writers; independent conversation histories remain whole snapshots.
        """
        try:
            request = self._enqueue_persist(
                redis_mgr,
                ttl_seconds,
                background=False,
                authoring_fields=authoring_fields,
                registry_updates=registry_updates,
            )
            error = await asyncio.shield(request.completion)
        except Exception as e:
            logger.error("Error submitting persistence for session %s: %s", self.session_id, e)
            if raise_on_failure:
                raise
            return False
        if error is not None:
            if raise_on_failure:
                raise error
            return False
        return True

    def _enqueue_persist(
        self,
        redis_mgr: AzureRedisManager,
        ttl_seconds: int | None,
        *,
        background: bool,
        authoring_fields: Collection[str] = (),
        registry_updates: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> _PendingWrite:
        loop = asyncio.get_running_loop()
        if (
            self._pending_persist_task
            and not self._pending_persist_task.done()
            and self._pending_persist_task.get_loop() is not loop
        ):
            raise RuntimeError("Persistence submissions must use the owning event loop")
        if self._pending_persist_task and self._pending_persist_task.done():
            self._check_persist_writer(self._pending_persist_task)
        if self._persist_writer_error is not None:
            raise self._persist_writer_error
        # Serialize both fields before yielding, never from the executor.
        snapshot = self.to_redis_dict()
        runtime_changes = self._changed_activation_fields(snapshot[self._CORE_KEY])
        if background and self._persist_queue:
            pending = self._persist_queue[-1]
            if (
                pending.background
                and pending.redis_mgr is redis_mgr
                and pending.ttl_seconds == ttl_seconds
            ):
                pending.snapshot = snapshot
                pending.runtime_changes = runtime_changes
                return pending

        self._persist_sequence += 1
        request = _PendingWrite(
            sequence=self._persist_sequence,
            redis_mgr=redis_mgr,
            snapshot=snapshot,
            ttl_seconds=ttl_seconds,
            background=background,
            completion=loop.create_future(),
            authoring_fields=tuple(authoring_fields),
            registry_updates=(
                copy.deepcopy(registry_updates) if registry_updates is not None else None
            ),
            runtime_changes=runtime_changes,
        )
        self._persist_queue.append(request)
        if self._pending_persist_task is None or self._pending_persist_task.done():
            self._pending_persist_task = asyncio.create_task(
                self._drain_persist_queue(), name=f"persist_session_{self.session_id}"
            )
            self._pending_persist_task.add_done_callback(self._check_persist_writer)
        return request

    def _check_persist_writer(self, task: asyncio.Task[None]) -> None:
        if self._persist_writer_error is not None:
            return
        if not task.cancelled() and task.exception() is None:
            return
        # Forced cancellation (e.g. loop shutdown) cannot retract executor I/O.
        # Fail closed rather than let a replacement writer overtake that I/O.
        error = RuntimeError(
            f"Persistence writer stopped for session {self.session_id}; "
            "write outcome is unconfirmed and this instance cannot submit further writes"
        )
        self._persist_writer_error = error
        logger.error("%s", error)
        requests = list(self._persist_queue)
        if self._active_persist is not None:
            requests.insert(0, self._active_persist)
        for request in requests:
            self._persist_failures.append((request.sequence, error))
            request.completion.set_result(error)
        self._persist_queue.clear()
        self._active_persist = None

    async def _write_snapshot(self, request: _PendingWrite) -> None:
        key = self.build_redis_key(self.session_id)
        submitted_core = request.snapshot[self._CORE_KEY]
        expected_revision = self.context.get(AUTHORING_REVISION_KEY)
        if not await request.redis_mgr.store_session_data_async(
            key,
            request.snapshot,
            authoring_fields=request.authoring_fields,
            registry_updates=request.registry_updates,
            # A pending author's activation must not turn an already-queued
            # stale snapshot into a handoff. Nor may repeated queued snapshots
            # replay a handoff that an earlier request already acknowledged.
            runtime_changes=set(request.runtime_changes)
            & set(self._changed_activation_fields(submitted_core)),
        ):
            raise RuntimeError(f"Redis write returned failure for session {self.session_id}")
        self._acknowledge_session_write(
            submitted_core,
            request.snapshot[self._CORE_KEY],
            expected_revision=expected_revision,
            authoring_fields=request.authoring_fields,
            registry_updates=request.registry_updates,
        )
        if request.ttl_seconds:
            expired = await asyncio.get_running_loop().run_in_executor(
                None, request.redis_mgr.redis_client.expire, key, request.ttl_seconds
            )
            if not expired:
                raise RuntimeError(f"Redis expiry returned failure for session {self.session_id}")
        logger.info("session.persist session=%s mode=async", self.session_id)

    async def _drain_persist_queue(self) -> None:
        while self._persist_queue:
            request = self._persist_queue.popleft()
            self._active_persist = request
            error = None
            try:
                await self._write_snapshot(request)
            except Exception as exc:
                error = exc
                self._persist_failures.append((request.sequence, exc))
                logger.error("Error persisting session %s to Redis: %s", self.session_id, exc)
            request.completion.set_result(error)
            self._active_persist = None

    async def persist_background(
        self,
        redis_mgr: AzureRedisManager | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """
        Capture state now and queue its write without waiting for Redis I/O.

        Only adjacent, not-started background snapshots with the same Redis
        manager and TTL coalesce. Active writes and direct barriers are never
        cancelled or superseded. Missing managers and serialization errors
        raise at submission; write errors are logged and surfaced by
        ``flush_pending_persist``.
        """
        self.schedule_persist(redis_mgr, ttl_seconds)

    def schedule_persist(
        self,
        redis_mgr: AzureRedisManager | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Submit a background snapshot immediately from an owning-loop callback.

        This synchronous submission has the same coalescing/error contract as
        ``persist_background``. A running event loop is required. Capturing and
        enqueueing happen before return, so an immediate flush includes this
        snapshot without needing a separately scheduled submission task.
        """
        mgr = redis_mgr or self._redis_manager
        if not mgr:
            raise ValueError("No Redis manager available")
        self._enqueue_persist(mgr, ttl_seconds, background=True)

    def cancel_pending_persist(self) -> bool:
        """Withdraw only background snapshots whose Redis writes have not started.

        Returns True if any queued snapshot was withdrawn. Active writes and
        direct awaited writes are left intact. Withdrawal is reported as a
        failure by the next flush, not mistaken for durability. For session
        cleanup prefer a final checked persist followed by a checked flush.
        """
        retained: deque[_PendingWrite] = deque()
        cancelled = False
        for request in self._persist_queue:
            if request.background:
                error = RuntimeError(f"Pending persistence withdrawn for session {self.session_id}")
                self._persist_failures.append((request.sequence, error))
                request.completion.set_result(error)
                cancelled = True
            else:
                retained.append(request)
        self._persist_queue = retained
        if cancelled:
            logger.warning(
                "Pending background persistence withdrawn for session %s", self.session_id
            )
        return cancelled

    async def flush_pending_persist(self, *, raise_on_failure: bool = False) -> bool:
        """Wait for submitted writes and acknowledge their recorded failures.

        Captures a boundary at entry; later submissions need a subsequent
        flush. A coalesced pending snapshot may include newer state. All writes
        at the boundary finish before returning False or raising the first
        failure. Previously completed failures are reported once per flush
        boundary, including failures already returned to direct callers.

        Cancellation stops only this waiter and does not acknowledge failures.
        This method does not capture unsaved state or prevent new submissions.
        Stop producers, await a final checked persist, then flush before
        releasing Redis or closing the event loop.
        """
        if self._pending_persist_task and self._pending_persist_task.done():
            self._check_persist_writer(self._pending_persist_task)
        boundary = self._persist_sequence
        requests = list(self._persist_queue)
        if self._active_persist is not None:
            requests.insert(0, self._active_persist)
        errors = [error for sequence, error in self._persist_failures if sequence <= boundary]
        for request in requests:
            error = await asyncio.shield(request.completion)
            if error is not None:
                errors.append(error)
        if self._persist_writer_error is not None:
            errors.append(self._persist_writer_error)
        self._persist_failures = deque(
            (sequence, error) for sequence, error in self._persist_failures if sequence > boundary
        )
        if errors:
            if raise_on_failure:
                raise errors[0]
            return False
        return True

    # --- TTS Interrupt ------------------------------------------------
    def is_tts_interrupted(self) -> bool:
        """
        Check the current TTS interruption state from local memory.

        Returns the in-memory flag indicating whether text-to-speech
        playback has been interrupted by user input or system events.

        Returns:
            bool: True if TTS is currently interrupted, False otherwise

        Example:
            ```python
            if manager.is_tts_interrupted():
                # Skip TTS playback
                logger.info("TTS interrupted, skipping audio")
            else:
                # Proceed with TTS
                await play_audio(response)
            ```

        Note:
            This method returns the local state only. For distributed
            scenarios, use is_tts_interrupted_live() to check Redis state.
        """
        return self._is_tts_interrupted

    def set_tts_interrupted(self, value: bool) -> None:
        """
        Set the TTS interruption state in local memory and context.

        Updates both the in-memory flag and core memory context to reflect
        the current TTS interruption state. This method provides local
        state management without Redis synchronization.

        Args:
            value (bool): True to mark TTS as interrupted, False to clear
                the interruption state

        Example:
            ```python
            # User interrupts during TTS playback
            manager.set_tts_interrupted(True)

            # TTS completion or reset
            manager.set_tts_interrupted(False)
            ```

        Note:
            For distributed scenarios where multiple processes need
            to coordinate TTS state, use set_tts_interrupted_live()
            to synchronize through Redis.
        """
        self.set_context("tts_interrupted", value)
        self._is_tts_interrupted = value

    async def set_tts_interrupted_live(
        self, redis_mgr: AzureRedisManager | None, session_id: str, value: bool
    ) -> None:
        """
        Set TTS interruption state with Redis synchronization.

        Updates the TTS interruption flag in Redis for distributed coordination
        across multiple voice agent processes or WebSocket connections.

        Args:
            redis_mgr (Optional[AzureRedisManager]): Redis manager for persistence.
                Uses stored manager if None provided.
            session_id (str): Session identifier for Redis key construction
            value (bool): True to mark TTS as interrupted, False to clear

        Example:
            ```python
            # Interrupt TTS across all processes
            await manager.set_tts_interrupted_live(redis_mgr, "session_123", True)

            # Clear interruption state
            await manager.set_tts_interrupted_live(redis_mgr, "session_123", False)
            ```

        Note:
            This method enables coordination between distributed voice
            agent instances, ensuring TTS interruptions are recognized
            across all active connections for the same session.
        """
        # Use simple key - corememory is already session-scoped
        await self.set_live_context_value(
            redis_mgr or self._redis_manager, "tts_interrupted", value
        )

    async def is_tts_interrupted_live(
        self,
        redis_mgr: AzureRedisManager | None = None,
        session_id: str | None = None,
    ) -> bool:
        """
        Check TTS interruption state with optional Redis synchronization.

        Checks the TTS interruption status, optionally refreshing from
        Redis for distributed coordination. Falls back to local state
        if Redis parameters are not provided.

        Args:
            redis_mgr (Optional[AzureRedisManager]): Redis manager for live data.
                If None, uses local state only.
            session_id (Optional[str]): Session identifier for Redis lookup.
                If None, uses local state only.

        Returns:
            bool: True if TTS is interrupted, False otherwise

        Example:
            ```python
            # Check with Redis sync
            interrupted = await manager.is_tts_interrupted_live(redis_mgr, "session_123")

            # Check local state only
            interrupted = await manager.is_tts_interrupted_live()
            ```

        Note:
            When both redis_mgr and session_id are provided, this method
            updates local state from Redis before returning the result,
            ensuring consistency across distributed processes.
        """
        if redis_mgr:
            self._is_tts_interrupted = await self.get_live_context_value(
                redis_mgr, "tts_interrupted", False
            )
            return self._is_tts_interrupted
        return self.get_context("tts_interrupted", False)

    # --- SLOTS & TOOL OUTPUTS -----------------------------------------
    def update_slots(self, slots: dict[str, Any]) -> None:
        """
        Update slot values in core memory for agent configuration.

        Merges new slot values into the existing slots dictionary stored
        in core memory. Slots are used for dynamic agent configuration
        and state management during conversations.

        Args:
            slots (Dict[str, Any]): Dictionary of slot names and values to update.
                Existing slots with the same names will be overwritten.

        Example:
            ```python
            # Update agent configuration slots
            manager.update_slots({
                "user_name": "Alice",
                "preferred_language": "en-US",
                "conversation_mode": "casual"
            })

            # Update individual slot
            manager.update_slots({"last_topic": "weather"})
            ```

        Logging:
            Logs the updated slots at debug level for troubleshooting.

        Note:
            Empty or None slots dictionaries are ignored to prevent
            clearing existing slot data accidentally.
        """
        if not slots:
            return
        current_slots = self.corememory.get("slots", {})
        current_slots.update(slots)
        self.corememory.set("slots", current_slots)
        logger.debug(f"Updated slots: {slots}")

    def get_slot(self, slot_name: str, default: Any = None) -> Any:
        """
        Retrieve a specific slot value from core memory.

        Gets a slot value from the slots dictionary stored in core memory,
        returning a default value if the slot doesn't exist.

        Args:
            slot_name (str): Name of the slot to retrieve
            default (Any): Default value to return if slot doesn't exist

        Returns:
            Any: The slot value, or default if not found

        Example:
            ```python
            # Get user preference with default
            language = manager.get_slot("preferred_language", "en-US")

            # Check if slot exists
            user_name = manager.get_slot("user_name")
            if user_name:
                greet_user(user_name)
            ```

        Note:
            Slots are stored under the 'slots' key in core memory and
            are typically used for agent configuration and user preferences.
        """
        return self.corememory.get("slots", {}).get(slot_name, default)

    def persist_tool_output(self, tool_name: str, result: dict[str, Any]) -> None:
        """
        Store the last execution result for a backend tool.

        Persists tool execution results in core memory for later reference,
        debugging, and context preservation across conversation turns.
        Each tool's most recent output overwrites previous results.

        Args:
            tool_name (str): Unique identifier for the tool that was executed
            result (Dict[str, Any]): The result data returned by the tool execution

        Example:
            ```python
            # Store weather API result
            weather_data = {
                "temperature": 72,
                "condition": "sunny",
                "location": "San Francisco"
            }
            manager.persist_tool_output("weather_api", weather_data)

            # Store database query result
            query_result = {"records_found": 5, "data": [...]}
            manager.persist_tool_output("database_query", query_result)
            ```

        Logging:
            Logs the tool name and result at debug level for troubleshooting.

        Note:
            Empty tool names or results are ignored to prevent storing
            invalid data. Only the most recent result per tool is kept.
        """
        if not tool_name or not result:
            return
        tool_outputs = self.corememory.get("tool_outputs", {})
        tool_outputs[tool_name] = result
        self.corememory.set("tool_outputs", tool_outputs)
        logger.debug(f"Persisted tool output for '{tool_name}': {result}")

    def get_tool_output(self, tool_name: str, default: Any = None) -> Any:
        """
        Retrieve the last execution result for a specific tool.

        Gets the most recently stored result for a tool from core memory,
        useful for accessing previous tool outputs in conversation context.

        Args:
            tool_name (str): Unique identifier for the tool whose result to retrieve
            default (Any): Default value to return if no result exists for the tool

        Returns:
            Any: The last tool execution result, or default if not found

        Example:
            ```python
            # Get last weather data
            weather = manager.get_tool_output("weather_api", {})
            if weather:
                temperature = weather.get("temperature")

            # Check if tool has been executed
            db_result = manager.get_tool_output("database_query")
            if db_result is None:
                logger.info("Database tool not yet executed")
            ```

        Note:
            Tool outputs are stored under the 'tool_outputs' key in core
            memory and persist across conversation turns for context.
        """
        return self.corememory.get("tool_outputs", {}).get(tool_name, default)

    # --- TURN SEQUENCE TRACKING ---------------------------------------
    def advance_turn_sequence(self) -> int:
        """
        Increment and return the turn sequence counter.

        Used to generate unique turn segment identifiers after tool calls,
        ensuring post-tool responses appear as new messages rather than
        overwriting pre-tool assistant content.

        Returns:
            int: The new turn sequence number after incrementing.

        Example:
            ```python
            # After tool execution completes
            seq = manager.advance_turn_sequence()
            new_turn_id = f"{base_turn_id}_s{seq}"
            ```
        """
        self._turn_sequence += 1
        logger.debug(f"Advanced turn sequence to {self._turn_sequence}")
        return self._turn_sequence

    def get_turn_sequence(self) -> int:
        """
        Get the current turn sequence counter without incrementing.

        Returns:
            int: The current turn sequence number.
        """
        return self._turn_sequence

    def reset_turn_sequence(self) -> None:
        """
        Reset the turn sequence counter to zero.

        Typically called when starting a new conversation turn
        (e.g., after user speaks).
        """
        self._turn_sequence = 0
        logger.debug("Reset turn sequence to 0")

    # --- LATENCY ------------------------------------------------------
    def note_latency(self, stage: str, start_t: float, end_t: float) -> None:
        """
        Record latency measurement for a specific processing stage.

        Captures timing data for performance monitoring and optimization,
        tracking how long different stages of voice processing take.

        Args:
            stage (str): Descriptive name for the processing stage being measured
            start_t (float): Start timestamp (typically from time.time())
            end_t (float): End timestamp (typically from time.time())

        Example:
            ```python
            # Measure STT processing time
            start_time = time.time()
            text_result = await speech_to_text(audio)
            manager.note_latency("stt", start_time, time.time())

            # Measure TTS generation time
            start_time = time.time()
            audio_data = await text_to_speech(response)
            manager.note_latency("tts", start_time, time.time())
            ```

        Note:
            Latency data is accumulated across multiple measurements
            for the same stage, enabling statistical analysis of
            performance patterns over time.
        """
        # compute and append to CoreMemory["latency"] to preserve behavior
        bucket = self.corememory.get("latency", {"runs": {}, "order": []})
        run_id = bucket.get("current_run_id") or "legacy"
        sample = StageSample(stage=stage, start=start_t, end=end_t, dur=end_t - start_t)
        # append
        runs = bucket.setdefault("runs", {})
        run = runs.setdefault(
            run_id,
            {"run_id": run_id, "label": "legacy", "created_at": start_t, "samples": []},
        )
        run["samples"].append(
            {
                "stage": sample.stage,
                "start": sample.start,
                "end": sample.end,
                "dur": sample.dur,
                "meta": {},
            }
        )
        order = bucket.setdefault("order", [])
        if run_id not in order:
            order.append(run_id)
        self.corememory.set("latency", bucket)

    def latency_summary(self) -> dict[str, dict[str, float]]:
        """
        Get comprehensive latency statistics for all measured stages.

        Returns a summary of performance metrics including average, minimum,
        maximum, and total latency for each processing stage that has been measured.

        Returns:
            Dict[str, Dict[str, float]]: Nested dictionary with stage names as keys
                and statistics dictionaries as values. Each statistics dict contains:
                - 'avg': Average latency in seconds
                - 'min': Minimum latency in seconds
                - 'max': Maximum latency in seconds
                - 'total': Total accumulated latency in seconds
                - 'count': Number of measurements

        Example:
            ```python
            # Get performance summary
            stats = manager.latency_summary()

            # Example return value:
            # {
            #     'stt': {'avg': 0.245, 'min': 0.180, 'max': 0.350, 'count': 12},
            #     'tts': {'avg': 0.890, 'min': 0.650, 'max': 1.200, 'count': 8},
            #     'llm': {'avg': 1.450, 'min': 0.800, 'max': 2.100, 'count': 10}
            # }

            # Check TTS performance
            if stats.get('tts', {}).get('avg', 0) > 1.0:
                logger.warning("TTS latency above threshold")
            ```

        Note:
            Statistics are calculated from all measurements since the
            MemoManager instance was created. Use this for performance
            monitoring and optimization analysis.
        """
        return PersistentLatency(self).session_summary()

    # --- HISTORY ------------------------------------------------------
    def append_to_history(self, agent: str, role: str, content: str) -> None:
        """
        Add a new message to the conversation history for a specific agent.

        Appends a message with the specified role and content to the chat
        history thread for the given agent. Each agent maintains a separate
        conversation thread for independent context management.

        Args:
            agent (str): Unique identifier for the agent (e.g., "main_agent", "tool_agent")
            role (str): Message role ("user", "assistant", "system", "tool")
            content (str): The message content/text

        Example:
            ```python
            # Add user message
            manager.append_to_history("main_agent", "user", "What's the weather?")

            # Add assistant response
            manager.append_to_history("main_agent", "assistant", "It's sunny and 72°F")

            # Add system message
            manager.append_to_history("main_agent", "system", "Tool execution completed")

            # Multiple agents
            manager.append_to_history("weather_agent", "user", "Check forecast")
            manager.append_to_history("calendar_agent", "user", "Schedule meeting")
            ```

        Note:
            Each agent maintains its own conversation thread, allowing
            for specialized agents with different contexts and histories
            within the same session.
        """
        self.history.append(role, content, agent)
        now = time.time()
        history = self.history.get_agent(agent)
        if history:
            history[-1].setdefault("timestamp", now)
        session_info = self.corememory.get("session_info", {})
        if not isinstance(session_info, dict):
            session_info = {}
        session_info.setdefault("created_at", now)
        session_info["last_activity"] = now
        self.corememory.set("session_info", session_info)
        self.corememory.set("created_at", session_info["created_at"])
        self.corememory.set("last_activity", now)

    def get_history(self, agent_name: str) -> list[dict[str, str]]:
        """
        Retrieve the complete conversation history for a specific agent.

        Gets the full message history for the specified agent, creating
        an empty history list if the agent doesn't exist yet.

        Args:
            agent_name (str): Unique identifier for the agent whose history to retrieve

        Returns:
            List[Dict[str, str]]: List of message dictionaries, each containing:
                - 'role': Message role ("user", "assistant", "system", "tool")
                - 'content': Message content/text
                - Other optional fields like timestamps

        Example:
            ```python
            # Get agent's conversation history
            history = manager.get_history("main_agent")

            # Example return value:
            # [
            #     {"role": "system", "content": "You are a helpful assistant"},
            #     {"role": "user", "content": "What's the weather?"},
            #     {"role": "assistant", "content": "It's sunny and 72°F"}
            # ]

            # Check history length
            if len(history) > 50:
                logger.info(f"Long conversation: {len(history)} messages")

            # Get last message
            if history:
                last_msg = history[-1]
                logger.debug(f"Last {last_msg['role']}: {last_msg['content']}")
            ```

        Note:
            If the agent doesn't exist, an empty list is returned and
            the agent is automatically created for future use.
        """
        return self.history.get_agent(agent_name)

    def clear_history(self, agent_name: str | None = None) -> None:
        """
        Clear conversation history for one agent or all agents.

        Removes chat history either for a specific agent or for all agents
        in the session. This is useful for resetting conversation context
        or implementing conversation boundaries.

        Args:
            agent_name (Optional[str]): Name of the agent whose history to clear.
                If None, clears history for ALL agents in the session.

        Example:
            ```python
            # Clear specific agent's history
            manager.clear_history("main_agent")

            # Clear all agents' histories
            manager.clear_history()

            # Reset conversation after error
            if error_occurred:
                manager.clear_history("main_agent")
                manager.append_to_history("main_agent", "system", "Starting fresh conversation")
            ```

        Warning:
            Clearing all agent histories (agent_name=None) will remove
            all conversation context from the session. This action
            cannot be undone unless the session was previously persisted.

        Note:
            System prompts and core memory are not affected by this
            operation - only the conversational message history is cleared.
        """
        self.history.clear(agent_name)

    # --- PROMPT INJECTION ---------------------------------------------
    # TODO this is wrong and needs to be fixed after close refactor [P.S]

    def get_context(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value from core memory by key.

        Gets a stored value from the persistent core memory store,
        returning a default value if the key doesn't exist.

        Args:
            key (str): The key to look up in core memory
            default (Any): Default value to return if key doesn't exist

        Returns:
            Any: The stored value, or default if key not found

        Example:
            ```python
            # Get user preferences
            user_name = manager.get_context("user_name", "Anonymous")
            language = manager.get_context("preferred_language", "en-US")

            # Get configuration
            api_config = manager.get_context("api_settings", {})

            # Check if value exists
            session_start = manager.get_context("session_start_time")
            if session_start:
                duration = time.time() - session_start
            ```

        Note:
            Core memory persists across conversation turns and can
            store any JSON-serializable data including strings, numbers,
            lists, and dictionaries.
        """
        return self.corememory.get(key, default)

    def set_context(self, key: str, value: Any) -> None:
        """
        Store a value in core memory, overwriting any existing value.

        Sets a key-value pair in the persistent core memory store,
        replacing any existing value for the same key.

        Args:
            key (str): The key to store the value under
            value (Any): The value to store (must be JSON-serializable)

        Example:
            ```python
            # Store user information
            manager.set_context("user_name", "Alice")
            manager.set_context("user_id", 12345)

            # Store configuration
            manager.set_context("api_settings", {
                "timeout": 30,
                "retries": 3,
                "endpoint": "https://api.example.com"
            })

            # Store session metadata
            manager.set_context("session_start_time", time.time())
            manager.set_context("conversation_topic", "weather")
            ```

        Note:
            Changes are made to local memory immediately but require
            calling persist() or persist_to_redis_async() to save
            to Redis for persistence across sessions.
        """
        self.corememory.set(key, value)

    def update_context(self, key: str, value: Any) -> None:
        """
        Merge a value into an existing dictionary in core memory.

        If the existing value is a dictionary and the new value is also
        a dictionary, merges them together. Otherwise, replaces the
        existing value entirely.

        Args:
            key (str): The key for the value to update in core memory
            value (Any): The value to merge or set

        Example:
            ```python
            # Initialize settings
            manager.set_context("user_preferences", {"theme": "dark"})

            # Merge additional preferences
            manager.update_context("user_preferences", {"language": "en", "notifications": True})
            # Result: {"theme": "dark", "language": "en", "notifications": True}

            # Update individual preference
            manager.update_context("user_preferences", {"theme": "light"})
            # Result: {"theme": "light", "language": "en", "notifications": True}

            # Replace non-dict value
            manager.set_context("counter", 5)
            manager.update_context("counter", {"value": 10})  # Replaces entirely
            ```

        Note:
            This method is particularly useful for gradually building up
            configuration dictionaries or user preferences without losing
            existing settings.
        """
        current = self.corememory.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            current.update(value)
            self.corememory.set(key, current)
        else:
            # Either no entry yet or not a dict → replace
            self.corememory.set(key, value)

    def ensure_system_prompt(
        self,
        agent_name: str,
        system_prompt: str,
    ) -> None:
        """
        Ensure the system prompt is properly set for an agent's conversation.

        Guarantees that the specified system prompt is the first message
        in the agent's conversation history. If no system message exists,
        adds one. If a system message exists, updates it with the new content.

        Args:
            agent_name (str): Unique identifier for the agent
            system_prompt (str): The system prompt content to set

        Example:
            ```python
            # Set initial system prompt
            prompt = "You are a helpful weather assistant. Always provide accurate forecasts."
            manager.ensure_system_prompt("weather_agent", prompt)

            # Update system prompt with new instructions
            updated_prompt = prompt + " Include temperature in Celsius and Fahrenheit."
            manager.ensure_system_prompt("weather_agent", updated_prompt)

            # Different agents, different prompts
            manager.ensure_system_prompt("calendar_agent", "You help manage schedules and appointments.")
            manager.ensure_system_prompt("email_agent", "You assist with email composition and management.")
            ```

        Behavior:
            - If history is empty: Adds system message as first entry
            - If first message is not system: Inserts system message at beginning
            - If first message is system: Updates content with new prompt

        Note:
            This method always updates the system prompt content on each
            call, ensuring the agent operates with the most current instructions.
        """
        history = self.histories.setdefault(agent_name, [])

        if not history or history[0].get("role") != "system":
            history.insert(0, {"role": "system", "content": system_prompt})
        else:
            history[0]["content"] = system_prompt

    def get_value_from_corememory(self, key: str, default: Any = None) -> Any:
        """
        Get a value from core memory.
        """
        return self.corememory.get(key, default)

    def set_corememory(self, key: str, value: Any) -> None:
        """
        Set a value in core memory.
        """
        self.corememory.set(key, value)

    def update_corememory(self, key: str, value: Any) -> None:
        """
        Update a value in core memory.
        """
        self.corememory.set(key, value)

    # TODO: REVIEW--- MESSAGE QUEUE MANAGEMENT -------------------------------------
    async def enqueue_message(
        self,
        response_text: str,
        use_ssml: bool = False,
        voice_name: str | None = None,
        locale: str = "en-US",
        participants: list[Any] | None = None,
        max_retries: int = 5,
        initial_backoff: float = 0.5,
        transcription_resume_delay: float = 1.0,
    ) -> None:
        """Add a message to the queue for sequential playback."""
        message_data = {
            "response_text": response_text,
            "use_ssml": use_ssml,
            "voice_name": voice_name,
            "locale": locale,
            "participants": participants,
            "max_retries": max_retries,
            "initial_backoff": initial_backoff,
            "transcription_resume_delay": transcription_resume_delay,
            "timestamp": asyncio.get_event_loop().time(),
        }
        await self.message_queue.enqueue(message_data)

    async def get_next_message(self) -> dict[str, Any] | None:
        """Get the next message from the queue."""
        return await self.message_queue.dequeue()

    async def clear_queue(self) -> None:
        """Clear all queued messages."""
        await self.message_queue.clear()

    def get_queue_size(self) -> int:
        """Get the current queue size."""
        return self.message_queue.size()

    async def set_queue_processing_status(self, is_processing: bool) -> None:
        """Set the queue processing status."""
        await self.message_queue.set_processing(is_processing)

    def is_queue_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        return self.message_queue.is_processing_queue()

    async def set_media_cancelled(self, cancelled: bool) -> None:
        """Set the media cancellation flag."""
        await self.message_queue.set_media_cancelled(cancelled)

    def is_media_cancelled(self) -> bool:
        """Check if media was cancelled due to interrupt."""
        return self.message_queue.is_media_cancelled()

    async def reset_queue_on_interrupt(self) -> None:
        """Reset the queue state when an interrupt is detected."""
        await self.message_queue.reset_on_interrupt()

    # --- MCP SESSION MANAGEMENT ---------------------------------------

    @property
    def mcp_manager(self) -> MCPSessionManager | None:
        """Get the MCP session manager for this session."""
        return self._mcp_manager

    async def init_mcp_servers(
        self,
        server_configs: list[MCPServerConfig],
    ) -> dict[str, bool]:
        """
        Initialize MCP server connections for this session.

        Connects to the specified MCP servers and discovers their tools.
        Tools become available immediately after successful connection.

        Args:
            server_configs: List of MCP server configurations to connect to

        Returns:
            Dict mapping server names to connection success status

        Example:
            ```python
            from apps.artagent.backend.registries.toolstore.mcp import MCPServerConfig

            results = await manager.init_mcp_servers([
                MCPServerConfig(name="cardapi", url="http://localhost:80"),
            ])
            # results: {"cardapi": True}
            ```
        """
        if not server_configs:
            return {}

        # Lazy import to avoid circular dependencies
        from apps.artagent.backend.registries.toolstore.mcp import MCPSessionManager

        if self._mcp_manager is None:
            self._mcp_manager = MCPSessionManager(session_id=self.session_id)

        results = await self._mcp_manager.connect_servers(server_configs)

        # Register discovered tools with the global registry
        if self._mcp_manager.available_tools:
            await self._register_mcp_tools_to_global_registry()

        logger.info(
            f"[{self.session_id}] Initialized MCP servers: {results}, "
            f"tools available: {len(self._mcp_manager.available_tools)}"
        )
        return results

    async def _register_mcp_tools_to_global_registry(self) -> None:
        """Register discovered MCP tools with the global tool registry."""
        if not self._mcp_manager:
            return

        from apps.artagent.backend.registries.toolstore import register_mcp_tool

        for tool_name in self._mcp_manager.available_tools:
            tool_info = self._mcp_manager._tools_cache.get(tool_name)
            if not tool_info:
                continue

            # Create executor that proxies to MCP manager.
            # Validation must happen at execution time since manager may be
            # cleaned up between registration and invocation.
            def make_executor(name: str):
                async def executor(args: dict[str, Any]) -> dict[str, Any]:
                    # Validate manager state at execution time, not capture time
                    if self._mcp_manager is None:
                        return {
                            "success": False,
                            "error": "MCP session has been cleaned up",
                        }
                    try:
                        return await self._mcp_manager.execute_tool(name, args)
                    except Exception as e:
                        return {
                            "success": False,
                            "error": f"MCP tool execution failed: {e}",
                        }

                return executor

            executor = make_executor(tool_name)

            schema = {
                "name": tool_name,
                "description": tool_info.description,
                "parameters": tool_info.input_schema,
            }

            mcp_transport = None
            session = self._mcp_manager._sessions.get(tool_info.server_name)
            if session:
                transport = session.config.transport
                mcp_transport = transport.value if hasattr(transport, "value") else str(transport)

            register_mcp_tool(
                name=tool_name,
                schema=schema,
                mcp_server=tool_info.server_name,
                mcp_transport=mcp_transport,
                executor=executor,
                override=True,
            )

            logger.debug(f"[{self.session_id}] Registered MCP tool: {tool_name}")

    def get_mcp_tools(self) -> list[dict[str, Any]]:
        """
        Get OpenAI-compatible tool schemas for all connected MCP servers.

        Returns:
            List of tool schemas in OpenAI format, or empty list if no MCP manager
        """
        if not self._mcp_manager:
            return []
        return self._mcp_manager.get_tool_schemas()

    def get_mcp_tool_names(self) -> list[str]:
        """
        Get list of available MCP tool names.

        Returns:
            List of MCP tool names (with server prefixes)
        """
        if not self._mcp_manager:
            return []
        return self._mcp_manager.available_tools

    async def execute_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute an MCP tool.

        Args:
            tool_name: The prefixed tool name (e.g., "cardapi_lookup_decline_code")
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if not self._mcp_manager:
            return {
                "success": False,
                "error": "MCP manager not initialized",
            }
        return await self._mcp_manager.execute_tool(tool_name, arguments)

    def is_mcp_tool(self, tool_name: str) -> bool:
        """
        Check if a tool name corresponds to an MCP tool.

        Args:
            tool_name: The tool name to check

        Returns:
            True if the tool is from an MCP server
        """
        if not self._mcp_manager:
            return False
        return self._mcp_manager.is_mcp_tool(tool_name)

    async def cleanup_mcp_servers(self) -> None:
        """
        Disconnect from all MCP servers and cleanup resources.

        Should be called when the session ends to release MCP connections.
        """
        if self._mcp_manager:
            # Unregister MCP tools from global registry
            from apps.artagent.backend.registries.toolstore import unregister_mcp_tools

            for server_name in self._mcp_manager.connected_servers:
                unregister_mcp_tools(server_name)

            await self._mcp_manager.disconnect_all()
            self._mcp_manager = None
            logger.info(f"[{self.session_id}] Cleaned up MCP server connections")

    # --- LIVE DATA REFRESH -------------------------------------------
    async def refresh_from_redis_async(self, redis_mgr: AzureRedisManager) -> bool:
        """Refresh the current session with live data from Redis."""
        key = self.build_redis_key(self.session_id)
        try:
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                logger.warning(f"No live data found for session {self.session_id}")
                return False
            if "chat_history" in data:
                new_histories = json.loads(data["chat_history"])
                if new_histories != self.histories:
                    logger.info(f"Refreshed histories for session {self.session_id}")
                    self.histories = new_histories
            if "corememory" in data:
                new_context = json.loads(data["corememory"])
                self.context = new_context
                self._capture_activation_baseline()
            logger.info(f"Successfully refreshed live data for session {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh live data for session {self.session_id}: {e}")
            return False

    def refresh_from_redis(self, redis_mgr: AzureRedisManager) -> bool:
        """Synchronous version of refresh_from_redis_async."""
        key = self.build_redis_key(self.session_id)
        try:
            data = redis_mgr.get_session_data(key)
            if not data:
                logger.warning(f"No live data found for session {self.session_id}")
                return False
            if "chat_history" in data:
                new_histories = json.loads(data["chat_history"])
                if new_histories != self.histories:
                    logger.info(f"Refreshed histories for session {self.session_id}")
                    self.histories = new_histories
            if "corememory" in data:
                new_context = json.loads(data["corememory"])
                self.context = new_context
                self._capture_activation_baseline()
            logger.info(f"Successfully refreshed live data for session {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh live data for session {self.session_id}: {e}")
            return False

    async def get_live_context_value(
        self, redis_mgr: AzureRedisManager, key: str, default: Any = None
    ) -> Any:
        """Get a specific context value from live Redis data without fully refreshing the session."""
        try:
            redis_key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(redis_key)
            if data and "corememory" in data:
                context = json.loads(data["corememory"])
                return context.get(key, default)
            return default
        except Exception as e:
            logger.error(
                f"Failed to get live context value '{key}' for session {self.session_id}: {e}"
            )
            return default

    async def set_live_context_value(
        self, redis_mgr: AzureRedisManager, key: str, value: Any
    ) -> bool:
        """Set a specific context value in both local state and Redis."""
        try:
            self.context[key] = value
            if not await self.persist_to_redis_async(redis_mgr):
                return False
            logger.debug(f"Set live context value '{key}' = {value} for session {self.session_id}")
            return True
        except Exception as e:
            logger.error(
                f"Failed to set live context value '{key}' for session {self.session_id}: {e}"
            )
            return False

    # NOTE: Auto-refresh functionality was removed as it was never used in production.
    # The system syncs state at turn boundaries which is sufficient for voice calls.
    # If polling-based refresh is needed in the future, re-implement with proper
    # task lifecycle management (cancellation on session end, deduplication, etc.)

    async def check_for_changes(self, redis_mgr: AzureRedisManager) -> dict[str, bool]:
        """Check what has changed in Redis compared to local state."""
        changes = {"corememory": False, "chat_history": False, "queue": False}
        try:
            key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                return changes
            if "corememory" in data:
                remote_context = json.loads(data["corememory"])
                local_context_clean = {
                    k: v for k, v in self.context.items() if k != "message_queue"
                }
                remote_context_clean = {
                    k: v for k, v in remote_context.items() if k != "message_queue"
                }
                changes["corememory"] = local_context_clean != remote_context_clean
                if "message_queue" in remote_context:
                    remote_queue = remote_context["message_queue"]
                    local_queue = list(self.message_queue.queue)
                    changes["queue"] = local_queue != remote_queue
            if "chat_history" in data:
                remote_histories = json.loads(data["chat_history"])
                changes["chat_history"] = self.histories != remote_histories
        except Exception as e:
            logger.error(f"Error checking for changes in session {self.session_id}: {e}")
        return changes

    async def selective_refresh(
        self,
        redis_mgr: AzureRedisManager,
        refresh_context: bool = True,
        refresh_histories: bool = True,
        refresh_queue: bool = False,
    ) -> dict[str, bool]:
        """Selectively refresh only specified parts of the session data."""
        updated = {"corememory": False, "chat_history": False, "queue": False}
        try:
            key = self.build_redis_key(self.session_id)
            data = await redis_mgr.get_session_data_async(key)
            if not data:
                return updated
            if refresh_context and "corememory" in data:
                new_context = json.loads(data["corememory"])
                if not refresh_queue:
                    new_context.pop("message_queue", None)
                self.context.update(new_context)
                self._capture_activation_baseline()
                updated["corememory"] = True
                logger.debug(f"Updated context for session {self.session_id}")
            if refresh_histories and "chat_history" in data:
                self.histories = json.loads(data["chat_history"])
                updated["chat_history"] = True
                logger.debug(f"Updated histories for session {self.session_id}")
            if refresh_queue and "corememory" in data:
                context = json.loads(data["corememory"])
                if "message_queue" in context:
                    async with self.message_queue.lock:
                        self.message_queue.queue = deque(context["message_queue"])
                        updated["queue"] = True
                        logger.debug(f"Updated message queue for session {self.session_id}")
        except Exception as e:
            logger.error(f"Error in selective refresh for session {self.session_id}: {e}")
        return updated
