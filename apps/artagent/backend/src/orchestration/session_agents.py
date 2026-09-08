"""
Session Agent Registry
======================

Centralized storage for session-scoped dynamic agents created via Agent Builder.
This module is the single source of truth for session agent state.

Both the agent_builder endpoints and the unified orchestrator import from here,
avoiding circular import issues.

Storage Structure:
- _session_agents: dict[session_id, dict[agent_name, UnifiedAgent]]
  Allows multiple custom agents per session.
"""

from __future__ import annotations

import time
from copy import deepcopy
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.registries.definitions import (
    agent_from_payload as _deserialize_agent,
)
from apps.artagent.backend.registries.definitions import (
    definition_payload as _serialize_agent,
)
from apps.artagent.backend.src.orchestration.naming import (
    agent_key,
    find_agent_by_name,
)
from apps.artagent.backend.src.orchestration.session_memory import live_memo, session_memo
from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent

logger = get_logger(__name__)

# Session-scoped dynamic agents: session_id -> {agent_name -> UnifiedAgent}
_session_agents: dict[str, dict[str, UnifiedAgent]] = {}

# Active session-scoped agent: session_id -> agent_name.
_active_session_agents: dict[str, str] = {}

# Callback for notifying the orchestrator adapter of updates
# Set by the unified orchestrator module at import time
# Signature: (session_id: str, agent: UnifiedAgent, set_active: bool) -> bool
_adapter_update_callback: Callable[[str, UnifiedAgent, bool], bool] | None = None

# Redis manager reference (set by lifecycle startup). Enables session agents to
# survive process reloads and to be shared across multiple workers — mirroring
# the session_scenarios persistence model.
_redis_manager: Any = None

# Redis corememory key holding all session agents for a session, indexed by name.
AGENTS_KEY_ALL = "session_agents_all"
AGENTS_KEY_ACTIVE = "active_session_agent"

# Time-based cooldown for Redis reads — avoids hammering Redis on rapid
# successive reads (e.g., repeated lookups during call setup).
_session_load_times: dict[str, float] = {}
_REDIS_LOAD_COOLDOWN_S: float = 2.0


def set_redis_manager(redis_mgr: Any) -> None:
    """Set the Redis manager reference for persistence operations."""
    global _redis_manager
    _redis_manager = redis_mgr
    logger.debug("Redis manager set for session_agents")


def register_adapter_update_callback(callback: Callable[[str, UnifiedAgent, bool], bool]) -> None:
    """
    Register a callback to be invoked when a session agent is updated.

    This is called by the unified orchestrator to inject updates into live adapters.
    The callback signature is: (session_id, agent, set_active) -> bool
    """
    global _adapter_update_callback
    _adapter_update_callback = callback
    logger.debug("Adapter update callback registered")


# ═══════════════════════════════════════════════════════════════════════════════
# SERIALIZATION (Redis persistence)
# ═══════════════════════════════════════════════════════════════════════════════


def _persist_agents_to_redis(session_id: str) -> None:
    """
    Persist all in-memory session agents for a session to Redis.

    Schedules an async write via the running event loop (fire-and-forget),
    mirroring the session_scenarios persistence pattern.
    """
    if not _redis_manager:
        logger.debug("No Redis manager available, skipping session agent persistence")
        return

    try:
        from src.stateful.state_managment import MemoManager

        memo = MemoManager.from_redis(session_id, _redis_manager)
        all_agents_data = {
            name: _serialize_agent(agent)
            for name, agent in _session_agents.get(session_id, {}).items()
        }
        active_agent = _active_session_agents.get(session_id)
        memo.set_corememory(AGENTS_KEY_ALL, all_agents_data)
        memo.set_corememory(AGENTS_KEY_ACTIVE, active_agent)
        if active_agent:
            memo.set_corememory("active_agent", active_agent)

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(memo.persist_to_redis_async(_redis_manager))
            task.add_done_callback(_log_persistence_result)
            _session_load_times[session_id] = time.monotonic()
        except RuntimeError:
            logger.debug("No event loop, skipping async session agent persistence")

        logger.debug(
            "Session agents queued for Redis persistence | session=%s count=%d",
            session_id,
            len(all_agents_data),
        )
    except Exception as e:
        logger.warning("Failed to persist session agents to Redis: %s", e)


async def persist_session_agents_to_redis(
    session_id: str, *, raise_on_failure: bool = False
) -> None:
    """
    Persist all in-memory session agents for a session to Redis, awaiting the write.

    Use this from async contexts (e.g., FastAPI endpoints) to guarantee the
    session agent is durable in Redis before returning a response. This prevents
    data loss if the process restarts between the write and the next VoiceLive
    WebSocket connection.
    """
    if not _redis_manager:
        return

    try:
        memo = await session_memo(session_id, _redis_manager)
        all_agents_data = {
            name: _serialize_agent(agent)
            for name, agent in _session_agents.get(session_id, {}).items()
        }
        active_agent = _active_session_agents.get(session_id)
        memo.set_corememory(AGENTS_KEY_ALL, all_agents_data)
        memo.set_corememory(AGENTS_KEY_ACTIVE, active_agent)
        if active_agent:
            memo.set_corememory("active_agent", active_agent)
        await memo.persist_to_redis_async(_redis_manager, raise_on_failure=raise_on_failure)
        _session_load_times[session_id] = time.monotonic()
        logger.info(
            "session.agents.sync session=%s agents=%d -> redis",
            session_id,
            len(all_agents_data),
        )
    except Exception as e:
        logger.warning("Failed to persist session agents to Redis (sync): %s", e)
        if raise_on_failure:
            raise


def _log_persistence_result(task) -> None:
    """Callback to log persistence task result."""
    if task.cancelled():
        logger.warning("Session agent persistence task was cancelled")
    elif task.exception():
        logger.error("Session agent persistence failed: %s", task.exception())


def _load_agents_from_redis(session_id: str, *, memo=None) -> dict[str, UnifiedAgent]:
    """Load all session agents for a session from Redis. Merges Redis → in-memory."""
    if memo is None and not _redis_manager:
        return {}

    try:
        from src.stateful.state_managment import MemoManager

        if memo is None:
            memo = live_memo(session_id) or MemoManager.from_redis(session_id, _redis_manager)
        all_agents_data = memo.get_value_from_corememory(AGENTS_KEY_ALL)
        active_agent = memo.get_value_from_corememory(AGENTS_KEY_ACTIVE)

        if not all_agents_data or not isinstance(all_agents_data, dict):
            if active_agent:
                _active_session_agents[session_id] = active_agent
            return {}

        loaded: dict[str, UnifiedAgent] = {}
        for agent_name, agent_data in all_agents_data.items():
            try:
                agent = _deserialize_agent(agent_data)
                loaded[agent.name or agent_name] = agent
            except Exception as e:
                logger.warning("Failed to parse session agent '%s': %s", agent_name, e)

        if loaded:
            # Redis is the shared source of truth; local memory only fills gaps
            # that have not yet been seen by Redis on this worker.
            existing = _session_agents.get(session_id, {})
            merged = {**existing, **loaded}
            _session_agents[session_id] = merged
            active_key = agent_key(active_agent)
            if active_key:
                actual_key, _ = find_agent_by_name(merged, active_agent)
                if actual_key is not None:
                    _active_session_agents[session_id] = actual_key
            elif len(loaded) == 1:
                _active_session_agents[session_id] = next(iter(loaded.keys()))
            logger.info(
                "Loaded %d session agent(s) from Redis | session=%s",
                len(loaded),
                session_id,
            )
        return loaded
    except Exception as e:
        logger.warning("Failed to load session agents from Redis: %s", e)
        raise


def _ensure_session_loaded(session_id: str, *, force: bool = False) -> None:
    """
    Ensure session agents are merged from Redis into memory.

    Read-through cache with NEGATIVE caching: after one load the result is cached
    regardless of whether any agents were found, and the Redis round-trip is
    skipped for ``_REDIS_LOAD_COOLDOWN_S`` seconds. This stops a session with no
    custom agents (the common case) from re-hitting Redis on every lookup. A
    worker re-syncs after the cooldown to pick up agents created on other workers.
    """
    if not _redis_manager:
        return

    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        # Async boundaries prime the view; native turns never perform sync I/O.
        return

    if not force:
        last_load = _session_load_times.get(session_id)
        if last_load is not None and (time.monotonic() - last_load) < _REDIS_LOAD_COOLDOWN_S:
            return

    _load_agents_from_redis(session_id)
    _session_load_times[session_id] = time.monotonic()
    # Cache the (possibly empty) result so negative lookups are not re-read.
    _session_agents.setdefault(session_id, {})


def _clear_agents_from_redis(session_id: str) -> None:
    """Clear all persisted session agents for a session from Redis."""
    if not _redis_manager:
        return

    try:
        from src.stateful.state_managment import MemoManager

        memo = MemoManager.from_redis(session_id, _redis_manager)
        memo.set_corememory(AGENTS_KEY_ALL, None)
        memo.set_corememory(AGENTS_KEY_ACTIVE, None)

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(memo.persist_to_redis_async(_redis_manager))
        except RuntimeError:
            logger.debug("No event loop, skipping async session agent clear")

        logger.debug("Session agents cleared from Redis | session=%s", session_id)
    except Exception as e:
        logger.warning("Failed to clear session agents from Redis: %s", e)


async def clear_session_agents_from_redis(
    session_id: str, *, raise_on_failure: bool = False
) -> None:
    """Clear all persisted session agents for a session, awaiting Redis."""
    if not _redis_manager:
        return

    try:
        memo = await session_memo(session_id, _redis_manager)
        memo.set_corememory(AGENTS_KEY_ALL, None)
        memo.set_corememory(AGENTS_KEY_ACTIVE, None)
        await memo.persist_to_redis_async(_redis_manager, raise_on_failure=raise_on_failure)
        _session_load_times.pop(session_id, None)
    except Exception as e:
        logger.warning("Failed to clear session agents from Redis (async): %s", e)
        if raise_on_failure:
            raise


def get_session_agent(session_id: str, agent_name: str | None = None) -> UnifiedAgent | None:
    """
    Get dynamic agent for a session.

    Args:
        session_id: The session ID
        agent_name: Optional agent name. If not provided, returns the first/default agent.
                    Lookup is case-insensitive.

    Returns:
        The UnifiedAgent if found, None otherwise.
    """
    # Read-through (cooldown-cached, negative results cached) merge of any
    # Redis-persisted agents into memory — survives reloads / multi-worker.
    _ensure_session_loaded(session_id)

    session_agents = _session_agents.get(session_id, {})
    if not session_agents:
        return None

    if agent_name:
        # Use case-insensitive lookup
        _, agent = find_agent_by_name(session_agents, agent_name)
        return agent

    active_agent = _active_session_agents.get(session_id)
    if active_agent:
        _, agent = find_agent_by_name(session_agents, active_agent)
        if agent is not None:
            return agent

    if len(session_agents) == 1:
        return next(iter(session_agents.values()))

    logger.warning(
        "Session has multiple agents but no active_session_agent | session=%s agents=%s",
        session_id,
        list(session_agents.keys()),
    )
    return None


def get_session_agents(session_id: str) -> dict[str, UnifiedAgent]:
    """Get all dynamic agents for a session."""
    _ensure_session_loaded(session_id)
    return dict(_session_agents.get(session_id, {}))


def session_agent_for_edit(
    session_id: str | None,
    agents: dict[str, UnifiedAgent],
    agent_name: str,
) -> UnifiedAgent | None:
    """Install a matching session-owned definition before any mutable live edit.

    Catalog/scenario definitions are borrowed until edited. Deep-copy their entire
    definition, not a field list, so future nested configuration stays isolated.
    """
    key, base = find_agent_by_name(agents, agent_name)
    owned = get_session_agent(session_id, agent_name) if session_id else None
    if owned is None:
        if base is None:
            logger.warning(
                "Cannot tune missing agent | session=%s agent=%s", session_id, agent_name
            )
            return None
        owned = deepcopy(base)
        owned.metadata = {
            **owned.metadata,
            "source": "dynamic",
            "session_id": session_id,
            "created_at": time.time(),
            "cloned_from": base.name,
        }
    agents[key or owned.name] = owned
    if session_id:
        set_session_agent(session_id, owned, persist=False)
    return owned


def set_session_agent(
    session_id: str,
    agent: UnifiedAgent,
    set_active: bool = False,
    *,
    persist: bool = True,
) -> None:
    """
    Set dynamic agent for a session.

    This is the single integration point - it both:
    1. Stores the agent in the local cache (by name within the session)
    2. Notifies the orchestrator adapter (if callback registered)

    All downstream components (voice, model, prompt) will automatically
    use the updated configuration.

    Args:
        session_id: The session ID
        agent: The UnifiedAgent to store
        set_active: If True, also set this agent as the active agent in the orchestrator.
                    Default False to prevent unintended scenario state changes.
    """
    if session_id not in _session_agents:
        _session_agents[session_id] = {}

    existing_key, _ = find_agent_by_name(_session_agents[session_id], agent.name)
    if existing_key and existing_key != agent.name:
        del _session_agents[session_id][existing_key]

    _session_agents[session_id][agent.name] = agent

    if set_active or session_id not in _active_session_agents:
        _active_session_agents[session_id] = agent.name

    # Persist to Redis so the override survives process reloads and is visible
    # to other workers (mirrors session_scenarios persistence).
    if persist:
        _persist_agents_to_redis(session_id)

    # Notify the orchestrator adapter if callback is registered
    adapter_updated = False
    if _adapter_update_callback:
        try:
            adapter_updated = _adapter_update_callback(session_id, agent, set_active)
        except Exception as e:
            logger.warning("Failed to update adapter: %s", e)

    logger.info(
        "session.agent.set session=%s agent=%s active=%s voice=%s adapter=%s",
        session_id,
        agent.name,
        set_active,
        agent.voice.name if agent.voice else "—",
        "updated" if adapter_updated else "unchanged",
    )


def remove_session_agent(
    session_id: str, agent_name: str | None = None, *, persist: bool = True
) -> bool:
    """
    Remove dynamic agent(s) for a session.

    Args:
        session_id: The session ID
        agent_name: Optional agent name. If not provided, removes ALL agents for the session.

    Returns:
        True if removed, False if not found.
    """
    _ensure_session_loaded(session_id, force=True)

    if session_id not in _session_agents:
        return False

    if agent_name:
        # Remove specific agent
        actual_key, _ = find_agent_by_name(_session_agents[session_id], agent_name)
        if actual_key is not None:
            del _session_agents[session_id][actual_key]
            logger.info("Session agent removed | session=%s agent=%s", session_id, actual_key)
            if _active_session_agents.get(session_id) == actual_key:
                remaining = _session_agents[session_id]
                if remaining:
                    _active_session_agents[session_id] = sorted(remaining.keys())[0]
                else:
                    _active_session_agents.pop(session_id, None)
            # Clean up empty session
            if not _session_agents[session_id]:
                del _session_agents[session_id]
            # Sync the change to Redis (writes remaining agents, or clears the key)
            if persist:
                _persist_agents_to_redis(session_id)
            return True
        return False
    else:
        # Remove all agents for session
        del _session_agents[session_id]
        _active_session_agents.pop(session_id, None)
        _session_load_times.pop(session_id, None)
        # Clear the persisted set in Redis as well
        if persist:
            _clear_agents_from_redis(session_id)
        logger.info("All session agents removed | session=%s", session_id)
        return True


async def remove_session_agent_async(
    session_id: str,
    agent_name: str | None = None,
    *,
    raise_on_failure: bool = False,
) -> bool:
    """Remove session agent config and await durable Redis persistence."""
    from apps.artagent.backend.src.orchestration.session_memory import prime_session_definitions

    await prime_session_definitions(session_id)
    removed = remove_session_agent(session_id, agent_name, persist=False)
    if not removed:
        return False
    if agent_name and session_id in _session_agents:
        await persist_session_agents_to_redis(session_id, raise_on_failure=raise_on_failure)
    else:
        await clear_session_agents_from_redis(session_id, raise_on_failure=raise_on_failure)
    return True


def list_session_agents() -> dict[str, UnifiedAgent]:
    """
    Return a flat dict of all session agents across all sessions.

    Key format: "{session_id}:{agent_name}" to ensure uniqueness.
    """
    result: dict[str, UnifiedAgent] = {}
    for session_id, agents in _session_agents.items():
        for agent_name, agent in agents.items():
            result[f"{session_id}:{agent_name}"] = agent
    return result


def list_session_agents_by_session(session_id: str) -> dict[str, UnifiedAgent]:
    """Return all agents for a specific session."""
    return dict(_session_agents.get(session_id, {}))


__all__ = [
    "register_adapter_update_callback",
    "set_redis_manager",
    "get_session_agent",
    "get_session_agents",
    "set_session_agent",
    "remove_session_agent",
    "remove_session_agent_async",
    "list_session_agents",
    "list_session_agents_by_session",
    "persist_session_agents_to_redis",
    "clear_session_agents_from_redis",
]
