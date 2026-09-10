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

import asyncio
import copy
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.src.orchestration.naming import agent_key, find_agent_by_name
from src.redis.manager import AUTHORING_REVISION_KEY
from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent

logger = get_logger(__name__)

# Session-scoped dynamic agents: session_id -> {agent_name -> UnifiedAgent}
_session_agents: dict[str, dict[str, UnifiedAgent]] = {}
_persisted_agent_data: dict[str, dict[str, dict[str, Any]]] = {}
_pending_agent_edits: dict[str, dict[str, tuple[str, dict[str, Any] | None]]] = {}
_agent_persist_tasks: dict[str, asyncio.Task] = {}

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

# Time-based cooldown for Redis reads — avoids hammering Redis on rapid
# successive reads (e.g., repeated lookups during call setup).
_session_load_times: dict[str, float] = {}
_REDIS_LOAD_COOLDOWN_S: float = 2.0


def set_redis_manager(redis_mgr: Any) -> None:
    """Set the Redis manager reference for persistence operations."""
    global _redis_manager
    if redis_mgr is not _redis_manager:
        _persisted_agent_data.clear()
        _pending_agent_edits.clear()
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


def _serialize_agent(agent: UnifiedAgent) -> dict[str, Any]:
    """Serialize a UnifiedAgent into a JSON-safe dict for Redis storage."""
    return {
        "name": agent.name,
        "description": agent.description,
        "greeting": agent.greeting,
        "return_greeting": agent.return_greeting,
        "handoff": {
            "trigger": agent.handoff.trigger if agent.handoff else "",
            "is_entry_point": agent.handoff.is_entry_point if agent.handoff else False,
        },
        "model": agent.model.to_dict() if agent.model else None,
        "cascade_model": agent.cascade_model.to_dict() if agent.cascade_model else None,
        "voicelive_model": agent.voicelive_model.to_dict() if agent.voicelive_model else None,
        "byom": agent.byom.to_dict() if agent.byom else None,
        "voice": agent.voice.to_dict() if agent.voice else None,
        "speech": agent.speech.to_dict() if agent.speech else None,
        "session": agent.session or {},
        "prompt_template": agent.prompt_template,
        "tool_names": list(agent.tool_names or []),
        "mcp_servers": list(agent.mcp_servers or []),
        "template_vars": agent.template_vars or {},
        "metadata": agent.metadata or {},
    }


def _deserialize_agent(data: dict[str, Any]) -> UnifiedAgent:
    """Reconstruct a UnifiedAgent from a Redis-stored dict."""
    from apps.artagent.backend.registries.agentstore.base import (
        HandoffConfig,
        ModelConfig,
        SpeechConfig,
        UnifiedAgent,
        VoiceConfig,
        VoiceLiveBYOMConfig,
    )

    model = ModelConfig.from_dict(data["model"]) if data.get("model") else ModelConfig()
    cascade_model = ModelConfig.from_dict(data["cascade_model"]) if data.get("cascade_model") else None
    voicelive_model = (
        ModelConfig.from_dict(data["voicelive_model"]) if data.get("voicelive_model") else None
    )
    voice = VoiceConfig.from_dict(data["voice"]) if data.get("voice") else VoiceConfig()
    speech = SpeechConfig.from_dict(data["speech"]) if data.get("speech") else SpeechConfig()
    handoff = HandoffConfig.from_dict(data.get("handoff") or {})

    return UnifiedAgent(
        name=data["name"],
        description=data.get("description", ""),
        greeting=data.get("greeting", ""),
        return_greeting=data.get("return_greeting", ""),
        handoff=handoff,
        model=model,
        cascade_model=cascade_model,
        voicelive_model=voicelive_model,
        byom=VoiceLiveBYOMConfig.from_dict(data["byom"]) if data.get("byom") else None,
        voice=voice,
        speech=speech,
        session=data.get("session") or {},
        prompt_template=data.get("prompt_template", ""),
        tool_names=list(data.get("tool_names") or []),
        mcp_servers=list(data.get("mcp_servers") or []),
        template_vars=data.get("template_vars") or {},
        metadata=data.get("metadata") or {},
    )


def _agent_data_changes(
    baseline: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any] | None]:
    before = {agent_key(name): (name, value) for name, value in baseline.items()}
    after = {agent_key(name): (name, value) for name, value in current.items()}
    changes = {}
    for key in before.keys() | after.keys():
        if key not in after:
            changes[before[key][0]] = None
        elif key not in before or before[key] != after[key]:
            name, value = after[key]
            changes[name] = value
    return changes


def cache_persisted_agents(
    session_id: str,
    persisted: dict[str, dict[str, Any]],
    *,
    submitted: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Refresh authoritative agents while retaining edits made during an in-flight write."""
    current = {
        name: _serialize_agent(agent) for name, agent in _session_agents.get(session_id, {}).items()
    }
    baseline = submitted if submitted is not None else _persisted_agent_data.get(session_id, {})
    local_changes = {
        name: value
        for name, value in _agent_data_changes(baseline, current).items()
        if value is not None
    }
    for name, (_, value) in _pending_agent_edits.get(session_id, {}).items():
        local_changes[name] = value
    merged = copy.deepcopy(persisted)
    for name, value in local_changes.items():
        actual_name, _ = find_agent_by_name(merged, name)
        if actual_name:
            merged.pop(actual_name)
        if value is not None:
            merged[name] = value
    _persisted_agent_data[session_id] = copy.deepcopy(persisted)
    _session_agents[session_id] = {
        name: _deserialize_agent(value) for name, value in merged.items()
    }


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
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                persist_session_agents_to_redis(session_id, raise_on_failure=True)
            )
            task.add_done_callback(_log_persistence_result)
        except RuntimeError:
            logger.debug("No event loop, skipping async session agent persistence")

        logger.debug(
            "Session agents queued for Redis persistence | session=%s count=%d",
            session_id,
            len(_session_agents.get(session_id, {})),
        )
    except Exception as e:
        logger.warning("Failed to persist session agents to Redis: %s", e)


async def persist_session_agents_to_redis(
    session_id: str, *, raise_on_failure: bool = False
) -> None:
    """Flush agent edits, sharing the same durable write with fire-and-forget callers."""
    if not _redis_manager:
        return
    try:
        while _redis_manager is not None:
            task = _agent_persist_tasks.get(session_id)
            if task is None:
                task = asyncio.create_task(
                    _persist_agent_edits_once(session_id, raise_on_failure=True)
                )
                _agent_persist_tasks[session_id] = task
                task.add_done_callback(_log_persistence_result)
            try:
                await asyncio.shield(task)
            finally:
                if task.done() and _agent_persist_tasks.get(session_id) is task:
                    _agent_persist_tasks.pop(session_id, None)
            current = {
                name: _serialize_agent(agent)
                for name, agent in _session_agents.get(session_id, {}).items()
            }
            changed = _agent_data_changes(_persisted_agent_data.get(session_id, {}), current)
            if not _pending_agent_edits.get(session_id) and not any(
                value is not None for value in changed.values()
            ):
                return
    except Exception as exc:
        if raise_on_failure:
            raise
        logger.warning("Failed to persist session agent edits: %s", exc)


async def _persist_agent_edits_once(session_id: str, *, raise_on_failure: bool = False) -> None:
    """
    Persist all in-memory session agents for a session to Redis, awaiting the write.

    Set raise_on_failure=True to report configured Redis write failures. Without
    a Redis manager, legacy memory-only operation is unchanged; draft Apply
    separately requires Redis. The default preserves best-effort callers.
    """
    if not _redis_manager:
        return

    try:
        from src.stateful.state_managment import MemoManager

        submitted = copy.deepcopy(
            {
                name: _serialize_agent(agent)
                for name, agent in _session_agents.get(session_id, {}).items()
            }
        )
        edits = dict(_pending_agent_edits.get(session_id, {}))
        changes = {
            name: value
            for name, value in _agent_data_changes(
                _persisted_agent_data.get(session_id, {}), submitted
            ).items()
            if value is not None
        }
        changes.update({name: value for name, (_, value) in edits.items()})
        if not changes:
            return
        memo = await asyncio.wait_for(
            asyncio.to_thread(MemoManager.from_redis, session_id, _redis_manager), timeout=5
        )
        preview = dict(memo.get_value_from_corememory(AGENTS_KEY_ALL) or {})
        for name, value in changes.items():
            actual_name, _ = find_agent_by_name(preview, name)
            if actual_name:
                preview.pop(actual_name)
            if value is not None:
                preview[name] = value
        memo.set_corememory(AGENTS_KEY_ALL, preview)
        success = await memo.persist_to_redis_async(
            _redis_manager,
            raise_on_failure=raise_on_failure,
            registry_updates={AGENTS_KEY_ALL: changes},
        )
        if not success:
            return
        pending = _pending_agent_edits.get(session_id, {})
        for name, edit in edits.items():
            if pending.get(name) == edit:
                pending.pop(name)
        cache_persisted_agents(
            session_id, memo.get_value_from_corememory(AGENTS_KEY_ALL) or {}, submitted=submitted
        )
        _session_load_times[session_id] = time.monotonic()
        logger.info(
            "session.agents.sync session=%s agents=%d -> redis",
            session_id,
            len(submitted),
        )
    except Exception as e:
        if raise_on_failure:
            raise
        logger.warning("Failed to persist session agents to Redis (sync): %s", e)


def _log_persistence_result(task) -> None:
    """Callback to log persistence task result."""
    if task.cancelled():
        logger.warning("Session agent persistence task was cancelled")
    elif task.exception():
        logger.error("Session agent persistence failed: %s", task.exception())


def _load_agents_from_redis(session_id: str) -> dict[str, UnifiedAgent]:
    """Load all session agents for a session from Redis. Merges Redis → in-memory."""
    if not _redis_manager:
        return {}

    try:
        from src.stateful.state_managment import MemoManager

        memo = MemoManager.from_redis(session_id, _redis_manager)
        all_agents_data = memo.get_value_from_corememory(AGENTS_KEY_ALL)

        if all_agents_data is None and AUTHORING_REVISION_KEY in memo.context:
            cache_persisted_agents(session_id, {})
            return {}
        if not isinstance(all_agents_data, dict):
            return {}

        loaded: dict[str, UnifiedAgent] = {}
        for agent_name, agent_data in all_agents_data.items():
            try:
                loaded[agent_name] = _deserialize_agent(agent_data)
            except Exception as e:
                logger.warning("Failed to parse session agent '%s': %s", agent_name, e)

        if AUTHORING_REVISION_KEY in memo.context:
            cache_persisted_agents(session_id, all_agents_data)
        elif loaded:
            # In-memory wins over Redis (more recent on this worker); Redis fills gaps.
            existing = _session_agents.get(session_id, {})
            _session_agents[session_id] = {**loaded, **existing}
            _persisted_agent_data[session_id] = copy.deepcopy(all_agents_data)
            logger.info(
                "Loaded %d session agent(s) from Redis | session=%s",
                len(loaded),
                session_id,
            )
        return loaded
    except Exception as e:
        logger.warning("Failed to load session agents from Redis: %s", e)
        return {}


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

        async def clear() -> None:
            pending = _agent_persist_tasks.get(session_id)
            if pending is not None:
                try:
                    await asyncio.shield(pending)
                except Exception as exc:
                    logger.warning("Prior agent write failed before reset: %s", exc)
            memo = await asyncio.wait_for(
                asyncio.to_thread(MemoManager.from_redis, session_id, _redis_manager), timeout=5
            )
            memo.set_corememory(AGENTS_KEY_ALL, None)
            await memo.persist_to_redis_async(
                _redis_manager,
                authoring_fields=(AGENTS_KEY_ALL,),
                raise_on_failure=True,
            )
            cache_persisted_agents(
                session_id,
                {},
                submitted={
                    name: _serialize_agent(agent)
                    for name, agent in _session_agents.get(session_id, {}).items()
                },
            )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(clear())
            task.add_done_callback(_log_persistence_result)
        except RuntimeError:
            logger.debug("No event loop, skipping async session agent clear")

        logger.debug("Session agents cleared from Redis | session=%s", session_id)
    except Exception as e:
        logger.warning("Failed to clear session agents from Redis: %s", e)


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
    
    # Return first agent if no name specified (backwards compatibility)
    return next(iter(session_agents.values()), None)


def get_session_agents(session_id: str) -> dict[str, UnifiedAgent]:
    """Get all dynamic agents for a session."""
    _ensure_session_loaded(session_id)
    return dict(_session_agents.get(session_id, {}))


def set_session_agent(session_id: str, agent: UnifiedAgent, set_active: bool = False) -> None:
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
        _session_agents[session_id] = {
            (agent.name if key == existing_key else key): (agent if key == existing_key else value)
            for key, value in _session_agents[session_id].items()
        }
    else:
        _session_agents[session_id][agent.name] = agent

    pending = _pending_agent_edits.setdefault(session_id, {})
    for pending_name in list(pending):
        if agent_key(pending_name) == agent_key(agent.name):
            pending.pop(pending_name)
    pending[agent.name] = (uuid.uuid4().hex, copy.deepcopy(_serialize_agent(agent)))

    # Persist to Redis so the override survives process reloads and is visible
    # to other workers (mirrors session_scenarios persistence).
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


def remove_session_agent(session_id: str, agent_name: str | None = None) -> bool:
    """
    Remove dynamic agent(s) for a session.
    
    Args:
        session_id: The session ID
        agent_name: Optional agent name. If not provided, removes ALL agents for the session.
    
    Returns:
        True if removed, False if not found.
    """
    if session_id not in _session_agents:
        return False
    
    if agent_name:
        agent_name, _ = find_agent_by_name(_session_agents[session_id], agent_name)
        # Remove specific agent
        if agent_name in _session_agents[session_id]:
            del _session_agents[session_id][agent_name]
            _pending_agent_edits.setdefault(session_id, {})[agent_name] = (uuid.uuid4().hex, None)
            logger.info("Session agent removed | session=%s agent=%s", session_id, agent_name)
            # Clean up empty session
            if not _session_agents[session_id]:
                del _session_agents[session_id]
            # Sync the change to Redis (writes remaining agents, or clears the key)
            _persist_agents_to_redis(session_id)
            return True
        return False
    else:
        # Remove all agents for session
        del _session_agents[session_id]
        _persisted_agent_data.pop(session_id, None)
        _pending_agent_edits.pop(session_id, None)
        _session_load_times.pop(session_id, None)
        # Clear the persisted set in Redis as well
        _clear_agents_from_redis(session_id)
        logger.info("All session agents removed | session=%s", session_id)
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
    "list_session_agents",
    "list_session_agents_by_session",
    "persist_session_agents_to_redis",
]
