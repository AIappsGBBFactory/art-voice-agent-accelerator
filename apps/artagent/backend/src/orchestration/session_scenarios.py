"""
Session Scenario Registry
=========================

Centralized storage for session-scoped dynamic scenarios created via Scenario Builder.
This module is the single source of truth for session scenario state.

Session scenarios allow runtime customization of:
- Agent orchestration graph (handoffs between agents)
- Agent overrides (greetings, template vars)
- Starting agent
- Handoff behavior (announced vs discrete)

Storage Structure:
- _session_scenarios: dict[session_id, dict[scenario_key, ScenarioConfig]]
  In-memory cache for fast access. Keys are lowercase for case-insensitive lookup.
  Also persisted to Redis via MemoManager.
- _active_scenario: dict[session_id, scenario_key]
  Tracks which scenario is currently active for each session (lowercase key).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.registries.definitions import definition_payload as _serialize_scenario
from apps.artagent.backend.src.orchestration.naming import (
    SCENARIO_KEY_ACTIVE,
    SCENARIO_KEY_ALL,
    SCENARIO_KEY_CONFIG,
    SCENARIO_KEY_LEGACY,
    find_scenario_by_name,
    scenario_key,
)
from apps.artagent.backend.src.orchestration.session_memory import session_memo
from src.redis.manager import AUTHORING_REVISION_KEY
from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig

logger = get_logger(__name__)

# Session-scoped dynamic scenarios: session_id -> {scenario_key (lowercase) -> ScenarioConfig}
_session_scenarios: dict[str, dict[str, ScenarioConfig]] = {}

# Track the active scenario for each session: session_id -> scenario_key (lowercase)
_active_scenario: dict[str, str] = {}

# Callback for notifying the orchestrator adapter of scenario updates
_scenario_update_callback: Callable[[str, ScenarioConfig], bool] | None = None

# Redis manager reference (set by main.py startup)
_redis_manager: Any = None

# Time-based cooldown for Redis reads — avoids hammering Redis when rapid
# successive reads hit _ensure_session_loaded (e.g., frontend polling).
_session_load_times: dict[str, float] = {}
_REDIS_LOAD_COOLDOWN_S: float = 2.0
_SCENARIO_WRITE_FIELDS = (
    SCENARIO_KEY_ACTIVE,
    SCENARIO_KEY_CONFIG,
    SCENARIO_KEY_LEGACY,
)


def set_redis_manager(redis_mgr: Any) -> None:
    """Set the Redis manager reference for persistence operations."""
    global _redis_manager
    _redis_manager = redis_mgr
    logger.debug("Redis manager set for session_scenarios")


def register_scenario_update_callback(callback: Callable[[str, ScenarioConfig], bool]) -> None:
    """
    Register a callback to be invoked when a session scenario is updated.

    This is called by the unified orchestrator to inject updates into live adapters.
    """
    global _scenario_update_callback
    _scenario_update_callback = callback
    logger.debug("Scenario update callback registered")


def _parse_scenario_data(scenario_data: dict) -> ScenarioConfig:
    """Decode persisted records through the same definition contract as YAML."""
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig

    return ScenarioConfig.from_dict(scenario_data.get("name", "custom"), scenario_data)


def _load_scenarios_from_redis(session_id: str, *, memo=None) -> dict[str, ScenarioConfig]:
    """
    Load ALL scenarios for a session from Redis via MemoManager.

    Supports both new format (session_scenarios_all) and legacy format (session_scenario_config).

    Returns dict of scenario_name -> ScenarioConfig.
    """
    if memo is None and not _redis_manager:
        return {}

    try:
        from src.stateful.state_managment import MemoManager

        if memo is None:
            from apps.artagent.backend.src.orchestration.session_memory import live_memo

            memo = live_memo(session_id) or MemoManager.from_redis(session_id, _redis_manager)

        # Try new multi-scenario format first
        all_scenarios_data = memo.get_value_from_corememory(SCENARIO_KEY_ALL)
        active_name = memo.get_value_from_corememory(SCENARIO_KEY_ACTIVE)
        if AUTHORING_REVISION_KEY in memo.context and (
            SCENARIO_KEY_ALL in memo.context
            or not memo.get_value_from_corememory(SCENARIO_KEY_CONFIG)
        ):
            loaded = {
                scenario_key(name): _parse_scenario_data(data)
                for name, data in (all_scenarios_data or {}).items()
            }
            _session_scenarios[session_id] = loaded
            active_key = scenario_key(active_name)
            if active_key in loaded:
                _active_scenario[session_id] = active_key
            else:
                _active_scenario.pop(session_id, None)
            return loaded
        if all_scenarios_data and isinstance(all_scenarios_data, dict):
            # New format: dict of {scenario_name: scenario_data}
            loaded_scenarios: dict[str, ScenarioConfig] = {}
            for scenario_name, scenario_data in all_scenarios_data.items():
                try:
                    scenario = _parse_scenario_data(scenario_data)
                    loaded_scenarios[scenario_key(scenario_name)] = scenario
                except Exception as e:
                    logger.warning("Failed to parse scenario '%s': %s", scenario_name, e)

            if loaded_scenarios:
                # Merge with existing in-memory cache, but let Redis win.
                # In a multi-worker deployment, Redis is the shared source of
                # truth and this worker's in-memory cache may be stale.
                existing = _session_scenarios.get(session_id, {})
                merged = {**existing, **loaded_scenarios}
                _session_scenarios[session_id] = merged

                # Set active scenario — normalize to lowercase for matching
                active_key = (active_name or "").lower()
                if active_key and active_key in merged:
                    _active_scenario[session_id] = active_key
                elif merged:
                    # Keep cached active only if it still exists; otherwise
                    # choose a deterministic fallback from the merged set.
                    cached_active = _active_scenario.get(session_id)
                    if not cached_active or cached_active not in merged:
                        _active_scenario[session_id] = next(iter(merged.keys()))

                logger.info(
                    "Loaded %d scenarios from Redis | session=%s active=%s",
                    len(loaded_scenarios),
                    session_id,
                    _active_scenario.get(session_id),
                )
                return loaded_scenarios

        # Fall back to legacy single-scenario format
        legacy_data = memo.get_value_from_corememory(SCENARIO_KEY_CONFIG)
        if legacy_data:
            scenario = _parse_scenario_data(legacy_data)
            normalized_name = scenario_key(scenario.name)

            # Cache in memory
            if session_id not in _session_scenarios:
                _session_scenarios[session_id] = {}
            _session_scenarios[session_id][normalized_name] = scenario
            _active_scenario[session_id] = normalized_name

            logger.info(
                "Loaded scenario from Redis (legacy format) | session=%s scenario=%s",
                session_id,
                normalized_name,
            )
            return {normalized_name: scenario}

        return {}
    except Exception as e:
        logger.warning("Failed to load scenarios from Redis: %s", e)
        raise


def _ensure_session_loaded(session_id: str, *, force: bool = False) -> None:
    """
    Ensure all scenarios for a session are merged from Redis into memory.

    Skips the Redis round-trip when the session was loaded within the last
    ``_REDIS_LOAD_COOLDOWN_S`` seconds (default 2 s) unless *force* is True.
    This prevents hammering Redis during rapid successive reads (e.g.,
    frontend polling or repeated GET /scenarios calls).

    Committed authoring registries replace stale views, including deletions.
    Legacy records merge with Redis winning over cached definitions.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return

    if not force:
        last_load = _session_load_times.get(session_id)
        if last_load is not None and (time.monotonic() - last_load) < _REDIS_LOAD_COOLDOWN_S:
            return

    loaded = _load_scenarios_from_redis(session_id)
    _session_load_times[session_id] = time.monotonic()
    # _load_scenarios_from_redis normally updates _session_scenarios as a
    # side effect.  But if it returned data without updating the dict
    # (e.g., Redis unavailable, or the function was mocked), merge the
    # returned data explicitly so callers always see a complete picture.
    if session_id not in _session_scenarios:
        _session_scenarios[session_id] = loaded if loaded else {}
    elif loaded:
        for key, sc in loaded.items():
            if key not in _session_scenarios[session_id]:
                _session_scenarios[session_id][key] = sc


def get_session_scenario(
    session_id: str, scenario_name: str | None = None
) -> ScenarioConfig | None:
    """
    Get dynamic scenario for a session.

    Read-through with cooldown caching: the first lookup merges Redis state into
    memory, then serves from memory for the cooldown window (negative results are
    cached, so a session with no custom scenarios does not re-hit Redis on every
    call). Uses case-insensitive lookup for scenario_name; returns the active
    scenario when no name is given.

    Args:
        session_id: The session ID
        scenario_name: Optional scenario name. If not provided, returns the active scenario.

    Returns:
        The ScenarioConfig if found, None otherwise.
    """
    _ensure_session_loaded(session_id)
    session_scenarios = _session_scenarios.get(session_id, {})
    if not session_scenarios:
        return None

    if scenario_name:
        # Case-insensitive lookup
        _, result = find_scenario_by_name(session_scenarios, scenario_name)
        return result

    # Return active scenario if set, otherwise first scenario
    active_key = _active_scenario.get(session_id)
    if active_key and active_key in session_scenarios:
        return session_scenarios[active_key]
    return next(iter(session_scenarios.values()), None)


def get_session_scenarios(session_id: str) -> dict[str, ScenarioConfig]:
    """
    Get all dynamic scenarios for a session (read-through, cooldown-cached).
    """
    _ensure_session_loaded(session_id)
    return dict(_session_scenarios.get(session_id, {}))


def get_active_scenario_name(session_id: str) -> str | None:
    """
    Get the name of the currently active scenario for a session.

    Falls back to Redis if not found in memory cache.
    """
    active_name = _active_scenario.get(session_id)

    # If we have a cached active and the session scenarios are present,
    # trust it only while it still points to an existing key.
    session_scenarios = _session_scenarios.get(session_id)
    if active_name and session_scenarios and active_name in session_scenarios:
        return active_name

    # Otherwise refresh (cooldown-cached) from Redis and return the reconciled key.
    _ensure_session_loaded(session_id)
    return _active_scenario.get(session_id)


def _persist_scenario_to_redis(session_id: str, scenario: ScenarioConfig) -> None:
    """Schedule the same checked async scenario write used by API callers."""
    if not _redis_manager:
        logger.debug("No Redis manager available, skipping persistence")
        return

    try:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_persist_scenario_to_redis_async(session_id, scenario))
            task.add_done_callback(_log_persistence_result)
        except RuntimeError:
            logger.debug("No event loop, skipping async Redis persistence")

        logger.debug(
            "All scenarios queued for Redis persistence | session=%s count=%d active=%s",
            session_id,
            len(_session_scenarios.get(session_id, {})),
            scenario.name,
        )
    except Exception as e:
        logger.warning("Failed to persist scenarios to Redis: %s", e)


def _log_persistence_result(task) -> None:
    """Callback to log persistence task result."""
    if task.cancelled():
        logger.warning("Scenario persistence task was cancelled")
    elif task.exception():
        logger.error("Scenario persistence failed: %s", task.exception())


def _clear_scenario_from_redis(session_id: str) -> None:
    """Clear ALL scenario config from Redis via MemoManager."""
    if not _redis_manager:
        return

    try:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                clear_session_scenarios_from_redis(session_id, raise_on_failure=True)
            )
            task.add_done_callback(_log_persistence_result)
        except RuntimeError:
            logger.debug("No event loop, skipping async Redis clear")

        logger.debug("All scenarios cleared from Redis | session=%s", session_id)
    except Exception as e:
        logger.warning("Failed to clear scenarios from Redis: %s", e)


async def clear_session_scenarios_from_redis(
    session_id: str, *, raise_on_failure: bool = False
) -> None:
    """Clear persisted scenario state for a session, awaiting Redis."""
    if not _redis_manager:
        return

    try:
        memo = await session_memo(session_id, _redis_manager)
        memo.set_corememory(SCENARIO_KEY_ALL, None)
        memo.set_corememory(SCENARIO_KEY_CONFIG, None)
        memo.set_corememory(SCENARIO_KEY_ACTIVE, None)
        memo.set_corememory(SCENARIO_KEY_LEGACY, None)
        if not await memo.persist_to_redis_async(
            _redis_manager,
            raise_on_failure=raise_on_failure,
            authoring_fields=(SCENARIO_KEY_ALL,) + _SCENARIO_WRITE_FIELDS,
        ):
            return
        _session_load_times.pop(session_id, None)
    except Exception as e:
        logger.warning("Failed to clear scenarios from Redis (async): %s", e)
        if raise_on_failure:
            raise


def _activate_scenario_core(
    session_id: str, scenario_name: str
) -> tuple[str, ScenarioConfig] | None:
    """Lookup, set active in-memory, notify callback. Returns (key, scenario) or None."""
    # Check in-memory first to avoid a Redis round-trip when the scenario
    # is already cached (common case for single-worker and rapid switches).
    session_scenarios = _session_scenarios.get(session_id, {})
    actual_key, scenario = find_scenario_by_name(session_scenarios, scenario_name)
    if not scenario:
        # Fall back to Redis — scenario may have been created on another worker
        _ensure_session_loaded(session_id, force=True)
        session_scenarios = _session_scenarios.get(session_id, {})
        actual_key, scenario = find_scenario_by_name(session_scenarios, scenario_name)
        if not scenario:
            return None

    _active_scenario[session_id] = actual_key

    if _scenario_update_callback:
        try:
            _scenario_update_callback(session_id, scenario)
        except Exception as e:
            logger.warning("Failed to update adapter with scenario: %s", e)

    return actual_key, scenario


def set_active_scenario(session_id: str, scenario_name: str) -> bool:
    """
    Set the active scenario for a session.

    Uses case-insensitive lookup for scenario_name.

    Returns True if the scenario exists and was set as active.
    """
    result = _activate_scenario_core(session_id, scenario_name)
    if not result:
        return False

    actual_key, scenario = result

    _persist_scenario_to_redis(session_id, scenario)

    logger.info(
        "Active scenario set | session=%s scenario=%s start_agent=%s",
        session_id,
        actual_key,
        scenario.start_agent,
    )
    return True


async def set_active_scenario_async(session_id: str, scenario_name: str) -> bool:
    """
    Set the active scenario for a session (async version with guaranteed persistence).

    Same as set_active_scenario() but awaits Redis persistence instead of
    fire-and-forget.  Use this in async FastAPI endpoints.

    Returns True if the scenario exists and was set as active.
    """
    from apps.artagent.backend.src.orchestration.session_memory import prime_session_definitions

    await prime_session_definitions(session_id)
    result = _activate_scenario_core(session_id, scenario_name)
    if not result:
        return False

    actual_key, scenario = result

    if _redis_manager:
        try:
            memo = await session_memo(session_id, _redis_manager)
            memo.set_corememory(SCENARIO_KEY_ACTIVE, actual_key)
            memo.set_corememory(SCENARIO_KEY_LEGACY, actual_key)
            memo.set_corememory(SCENARIO_KEY_CONFIG, _serialize_scenario(scenario))
            if scenario.start_agent:
                memo.set_corememory("active_agent", scenario.start_agent)
            await memo.persist_to_redis_async(
                _redis_manager,
                raise_on_failure=True,
                authoring_fields=_SCENARIO_WRITE_FIELDS
                + (("active_agent",) if scenario.start_agent else ()),
            )
            # Mark session as fresh — the in-memory state IS Redis state now,
            # so subsequent reads within the cooldown window can skip HGETALL.
            _session_load_times[session_id] = time.monotonic()
        except Exception as e:
            logger.warning("Failed to persist active scenario to Redis: %s", e)
            raise

    logger.info(
        "Active scenario set (async) | session=%s scenario=%s start_agent=%s",
        session_id,
        actual_key,
        scenario.start_agent,
    )
    return True


def _store_session_scenario(session_id: str, scenario: ScenarioConfig) -> bool:
    """Update the primed definition view and notify native runtime consumers once."""
    _session_scenarios.setdefault(session_id, {})

    # Normalize scenario key to lowercase for case-insensitive storage
    normalized_key = scenario_key(scenario.name)
    if not normalized_key:
        logger.warning(
            "Skipping session scenario set: empty scenario name | session=%s", session_id
        )
        return False

    # Remove any existing scenario with different casing (to avoid duplicates)
    keys_to_remove = [
        k
        for k in _session_scenarios[session_id]
        if k.lower() == normalized_key and k != normalized_key
    ]
    for old_key in keys_to_remove:
        del _session_scenarios[session_id][old_key]
        logger.debug(
            "Removed duplicate scenario key | session=%s old_key=%s new_key=%s",
            session_id,
            old_key,
            normalized_key,
        )

    _session_scenarios[session_id][normalized_key] = scenario
    _active_scenario[session_id] = normalized_key

    # Notify the orchestrator adapter if callback is registered
    adapter_updated = False
    if _scenario_update_callback:
        try:
            adapter_updated = _scenario_update_callback(session_id, scenario)
        except Exception as e:
            logger.warning("Failed to update adapter with scenario: %s", e)

    logger.info(
        "session.scenario.set session=%s scenario=%s start_agent=%s agents=%d handoffs=%d adapter=%s",
        session_id,
        scenario.name,
        scenario.start_agent,
        len(scenario.agents),
        len(scenario.handoffs),
        "updated" if adapter_updated else "unchanged",
    )
    return True


def set_session_scenario(session_id: str, scenario: ScenarioConfig) -> None:
    """Synchronous compatibility entry point; async users must await the async setter."""
    _ensure_session_loaded(session_id)
    if _store_session_scenario(session_id, scenario):
        _persist_scenario_to_redis(session_id, scenario)


async def set_session_scenario_async(session_id: str, scenario: ScenarioConfig) -> None:
    """Prime, update and strictly persist the scenario through the current memo."""
    from apps.artagent.backend.src.orchestration.session_memory import prime_session_definitions

    await prime_session_definitions(session_id)
    if _store_session_scenario(session_id, scenario):
        await _persist_scenario_to_redis_async(session_id, scenario)


async def _persist_scenario_to_redis_async(session_id: str, scenario: ScenarioConfig) -> None:
    """
    Async version of scenario persistence to Redis.

    Updates only this named definition and activation, preserving other
    workers' scenarios and the current conversation atomically.
    """
    if not _redis_manager:
        logger.debug("No Redis manager available, skipping persistence")
        return

    try:
        memo = await session_memo(session_id, _redis_manager)

        # _ensure_session_loaded already merges Redis → in-memory, so we
        # just serialize whatever is in _session_scenarios right now.
        all_scenarios_data = {
            name: _serialize_scenario(sc)
            for name, sc in _session_scenarios.get(session_id, {}).items()
        }

        memo.set_corememory(SCENARIO_KEY_ALL, all_scenarios_data)
        memo.set_corememory(SCENARIO_KEY_ACTIVE, scenario_key(scenario.name))
        memo.set_corememory(SCENARIO_KEY_LEGACY, scenario_key(scenario.name))
        memo.set_corememory(SCENARIO_KEY_CONFIG, _serialize_scenario(scenario))

        if scenario.start_agent:
            memo.set_corememory("active_agent", scenario.start_agent)

        # Await persistence with raise_on_failure to detect silent Redis
        # write failures.  Without this, store_session_data_async may return
        # False (write failed) yet the caller would never know, leading to
        # /create returning 200 while the data never reaches Redis — and a
        # subsequent /active on another worker would 404.
        await memo.persist_to_redis_async(
            _redis_manager,
            raise_on_failure=True,
            authoring_fields=_SCENARIO_WRITE_FIELDS
            + (("active_agent",) if scenario.start_agent else ()),
            registry_updates={
                SCENARIO_KEY_ALL: {scenario_key(scenario.name): _serialize_scenario(scenario)}
            },
        )
        # Mark session as fresh so reads within the cooldown skip HGETALL.
        _session_load_times[session_id] = time.monotonic()

        logger.debug(
            "All scenarios persisted to Redis (async) | session=%s count=%d active=%s",
            session_id,
            len(all_scenarios_data),
            scenario.name,
        )
    except Exception as e:
        logger.error("Failed to persist scenario to Redis: %s", e)
        raise


def _delete_scenario_from_redis(session_id: str, deleted_name: str) -> None:
    if not _redis_manager:
        return

    try:
        task = asyncio.get_running_loop().create_task(
            _delete_scenario_from_redis_async(session_id, deleted_name, raise_on_failure=True)
        )
        task.add_done_callback(_log_persistence_result)
    except RuntimeError:
        logger.debug("No event loop, skipping async scenario deletion")


async def _delete_scenario_from_redis_async(
    session_id: str, deleted_name: str, *, raise_on_failure: bool = False
) -> None:
    """Delete one definition; Redis reconciles activation against the committed registry."""
    if not _redis_manager:
        return
    try:
        memo = await session_memo(session_id, _redis_manager)
        remaining = dict(memo.get_value_from_corememory(SCENARIO_KEY_ALL) or {})
        actual_key, _ = find_scenario_by_name(remaining, deleted_name)
        if actual_key is not None:
            remaining.pop(actual_key)
        memo.set_corememory(SCENARIO_KEY_ALL, remaining)
        if not await memo.persist_to_redis_async(
            _redis_manager,
            raise_on_failure=raise_on_failure,
            registry_updates={SCENARIO_KEY_ALL: {scenario_key(deleted_name): None}},
        ):
            return
        _session_scenarios[session_id] = {
            scenario_key(name): _parse_scenario_data(data)
            for name, data in (memo.get_value_from_corememory(SCENARIO_KEY_ALL) or {}).items()
        }
        active = memo.get_value_from_corememory(SCENARIO_KEY_ACTIVE)
        if active:
            _active_scenario[session_id] = scenario_key(active)
        else:
            _active_scenario.pop(session_id, None)
        _session_load_times[session_id] = time.monotonic()
    except Exception as exc:
        logger.warning("Failed to delete session scenario: %s", exc)
        if raise_on_failure:
            raise


def remove_session_scenario(
    session_id: str, scenario_name: str | None = None, *, persist: bool = True
) -> bool:
    """
    Remove dynamic scenario(s) for a session.

    Args:
        session_id: The session ID
        scenario_name: Optional scenario name. If not provided, removes ALL scenarios for the session.

    Returns:
        True if removed, False if not found.
    """
    _ensure_session_loaded(session_id, force=True)

    if session_id not in _session_scenarios:
        return False

    if scenario_name:
        # Remove specific scenario
        actual_key, _ = find_scenario_by_name(_session_scenarios[session_id], scenario_name)
        if actual_key is not None:
            del _session_scenarios[session_id][actual_key]
            logger.info("Session scenario removed | session=%s scenario=%s", session_id, actual_key)

            # Update active scenario if needed
            if _active_scenario.get(session_id) == actual_key:
                remaining = _session_scenarios[session_id]
                if remaining:
                    _active_scenario[session_id] = sorted(remaining.keys())[0]
                else:
                    _active_scenario.pop(session_id, None)

            # Clean up empty session
            if not _session_scenarios[session_id]:
                del _session_scenarios[session_id]
            if persist:
                _delete_scenario_from_redis(session_id, actual_key)
            return True
        return False
    else:
        # Remove all scenarios for session
        del _session_scenarios[session_id]
        if session_id in _active_scenario:
            del _active_scenario[session_id]
        # Clear from Redis
        if persist:
            _clear_scenario_from_redis(session_id)
        logger.info("All session scenarios removed | session=%s", session_id)
        return True


async def remove_session_scenario_async(
    session_id: str,
    scenario_name: str | None = None,
    *,
    raise_on_failure: bool = False,
) -> bool:
    """Remove session scenario config and await durable Redis persistence."""
    from apps.artagent.backend.src.orchestration.session_memory import prime_session_definitions

    await prime_session_definitions(session_id)
    removed = remove_session_scenario(session_id, scenario_name, persist=False)
    if not removed:
        return False
    if scenario_name:
        await _delete_scenario_from_redis_async(
            session_id, scenario_name, raise_on_failure=raise_on_failure
        )
    else:
        await clear_session_scenarios_from_redis(session_id, raise_on_failure=raise_on_failure)
    return True


def list_session_scenarios() -> dict[str, ScenarioConfig]:
    """
    Return a flat dict of all session scenarios across all sessions.

    Key format: "{session_id}:{scenario_name}" to ensure uniqueness.
    """
    result: dict[str, ScenarioConfig] = {}
    for session_id, scenarios in _session_scenarios.items():
        for scenario_name, scenario in scenarios.items():
            result[f"{session_id}:{scenario_name}"] = scenario
    return result


def list_session_scenarios_by_session(session_id: str) -> dict[str, ScenarioConfig]:
    """
    Return all scenarios for a specific session (deduplicated by name, case-insensitive).

    Always merges Redis state before returning so a worker with a non-empty but
    stale/partial in-memory cache does not hide scenarios created elsewhere.
    """
    # Always refresh/merge from Redis first. This prevents returning stale
    # empty/partial scenario lists when this worker has outdated in-memory data.
    _ensure_session_loaded(session_id)
    scenarios = _session_scenarios.get(session_id, {})

    logger.debug(
        "Listing session scenarios | session=%s count=%d",
        session_id,
        len(scenarios),
    )

    # Deduplicate by lowercase name (keep latest)
    deduplicated: dict[str, ScenarioConfig] = {}
    for key, scenario in scenarios.items():
        normalized_key = key.lower()
        deduplicated[normalized_key] = scenario

    return deduplicated


__all__ = [
    "get_session_scenario",
    "get_session_scenarios",
    "get_active_scenario_name",
    "set_active_scenario",
    "set_active_scenario_async",
    "set_session_scenario",
    "set_session_scenario_async",
    "set_redis_manager",
    "remove_session_scenario",
    "remove_session_scenario_async",
    "list_session_scenarios",
    "list_session_scenarios_by_session",
    "register_scenario_update_callback",
    "clear_session_scenarios_from_redis",
]
