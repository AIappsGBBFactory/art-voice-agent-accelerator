"""Read-only authoring snapshots and atomic publication into the existing registries."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig
from apps.artagent.backend.src.orchestration import session_agents, session_scenarios
from apps.artagent.backend.src.orchestration.naming import (
    SCENARIO_KEY_ALL,
    SCENARIO_KEY_CONFIG,
    agent_key,
    scenario_key,
    set_scenario_in_corememory,
)
from src.redis.manager import AUTHORING_FIELDS, AUTHORING_REVISION_KEY
from src.stateful.state_managment import MemoManager

MAX_SESSION_AGENTS = 32
MAX_SESSION_SCENARIOS = 16


class DraftStateConflict(ValueError):
    """The session changed after draft validation, or a new name is already used."""


class DraftPersistenceError(RuntimeError):
    """Session persistence is unavailable or returned invalid data."""


class DraftActivationError(RuntimeError):
    """The draft was saved, but a live adapter could not be notified."""


@dataclass
class SessionAuthoringSnapshot:
    """A private snapshot, never serialized into model input."""

    memo: MemoManager
    redis_data: dict[str, str]
    agents: dict[str, UnifiedAgent]
    scenarios: dict[str, ScenarioConfig]


def get_authoring_redis(app_state: Any) -> Any:
    """Use the same Redis manager as the session registries."""
    return (
        getattr(app_state, "redis", None)
        or getattr(app_state, "redis_manager", None)
        or session_scenarios._redis_manager
        or session_agents._redis_manager
    )


async def read_authoring_snapshot(
    session_id: str, redis_manager: Any | None
) -> SessionAuthoringSnapshot:
    """Read only this session, without loading or changing either registry cache."""
    memo = MemoManager(session_id=session_id)
    redis_data: dict[str, str] = {}
    if redis_manager is not None:
        redis_data = await asyncio.wait_for(
            asyncio.to_thread(
                redis_manager.get_session_data, MemoManager.build_redis_key(session_id)
            ),
            timeout=5,
        )
        if not isinstance(redis_data, dict):
            raise DraftPersistenceError("Redis did not return a valid session snapshot.")
        if "corememory" in redis_data:
            memo.corememory.from_json(redis_data["corememory"])
        if "chat_history" in redis_data:
            memo.chatHistory.from_json(redis_data["chat_history"])

    authoritative = AUTHORING_REVISION_KEY in memo.context
    agents = (
        {}
        if authoritative or session_agents.AGENTS_KEY_ALL in memo.context
        else dict(session_agents._session_agents.get(session_id, {}))
    )
    stored_agents = memo.get_value_from_corememory(session_agents.AGENTS_KEY_ALL) or {}
    if not isinstance(stored_agents, dict):
        raise DraftPersistenceError("Stored session agents are invalid.")
    for data in stored_agents.values():
        agent = session_agents._deserialize_agent(data)
        agents = {
            key: value for key, value in agents.items() if agent_key(key) != agent_key(agent.name)
        }
        agents[agent.name] = agent

    scenarios = (
        {}
        if authoritative or SCENARIO_KEY_ALL in memo.context or SCENARIO_KEY_CONFIG in memo.context
        else dict(session_scenarios._session_scenarios.get(session_id, {}))
    )
    stored_scenarios = memo.get_value_from_corememory(SCENARIO_KEY_ALL) or {}
    if not isinstance(stored_scenarios, dict):
        raise DraftPersistenceError("Stored session scenarios are invalid.")
    if not stored_scenarios:
        legacy = memo.get_value_from_corememory(SCENARIO_KEY_CONFIG)
        if legacy:
            stored_scenarios = {legacy["name"]: legacy}
    for name, data in stored_scenarios.items():
        scenarios[scenario_key(name)] = session_scenarios._parse_scenario_data(data)

    return SessionAuthoringSnapshot(memo, redis_data, agents, scenarios)


async def _commit_snapshot(
    session_id: str,
    snapshot: SessionAuthoringSnapshot,
    redis_manager: Any,
    *,
    publish: Callable[[], None],
    conflict_detail: str,
) -> None:
    async def commit_and_publish() -> None:
        data = snapshot.memo.to_redis_dict()
        intended = json.loads(data["corememory"])
        saved = await redis_manager.compare_and_store_session_data_async(
            MemoManager.build_redis_key(session_id),
            data,
            expected_data=snapshot.redis_data,
        )
        if not saved:
            raise DraftStateConflict(conflict_detail)
        persisted = json.loads(data["corememory"])
        if any(
            intended.get(key) != persisted.get(key) for key in AUTHORING_FIELDS | {"active_agent"}
        ):
            # The receipt can acknowledge our commit after a later edit/handoff.
            # Refresh caches, but never replay its now-superseded activation.
            agent_data = persisted.get(session_agents.AGENTS_KEY_ALL) or {}
            session_agents._session_agents[session_id] = {
                name: session_agents._deserialize_agent(value) for name, value in agent_data.items()
            }
            session_agents._persisted_agent_data[session_id] = copy.deepcopy(agent_data)
            session_scenarios._session_scenarios[session_id] = {
                scenario_key(name): session_scenarios._parse_scenario_data(value)
                for name, value in (persisted.get(SCENARIO_KEY_ALL) or {}).items()
            }
            active = persisted.get("active_scenario_name")
            if active:
                session_scenarios._active_scenario[session_id] = scenario_key(active)
            else:
                session_scenarios._active_scenario.pop(session_id, None)
            session_agents._session_load_times[session_id] = time.monotonic()
            session_scenarios._session_load_times[session_id] = time.monotonic()
        else:
            publish()

    task = asyncio.create_task(commit_and_publish())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def publish_new_session_agent(
    session_id: str,
    agent: UnifiedAgent,
    *,
    snapshot: SessionAuthoringSnapshot,
    redis_manager: Any,
    activate: bool = False,
) -> None:
    """Create a session agent atomically, never replacing an existing session name."""
    if redis_manager is None:
        raise DraftPersistenceError("Redis is required for atomic create-only agent saves.")
    if agent_key(agent.name) in {agent_key(name) for name in snapshot.agents}:
        raise DraftStateConflict(f"Agent '{agent.name}' already exists. Choose an unused name.")
    if len(snapshot.agents) >= MAX_SESSION_AGENTS:
        raise DraftStateConflict(
            f"A session may contain at most {MAX_SESSION_AGENTS} custom agents."
        )

    all_agents = {**snapshot.agents, agent.name: agent}
    snapshot.memo.set_corememory(
        session_agents.AGENTS_KEY_ALL,
        {name: session_agents._serialize_agent(item) for name, item in all_agents.items()},
    )
    if activate:
        snapshot.memo.set_corememory("active_agent", agent.name)

    def publish() -> None:
        session_agents._session_agents[session_id] = all_agents
        session_agents._persisted_agent_data[session_id] = copy.deepcopy(
            {name: session_agents._serialize_agent(item) for name, item in all_agents.items()}
        )
        session_agents._session_load_times[session_id] = time.monotonic()
        if session_agents._adapter_update_callback:
            try:
                session_agents._adapter_update_callback(session_id, agent, activate)
            except Exception as exc:
                raise DraftActivationError(
                    "Agent saved, but the live configuration could not be refreshed. Reconnect the call."
                ) from exc

    await _commit_snapshot(
        session_id,
        snapshot,
        redis_manager,
        publish=publish,
        conflict_detail="The session changed while creating the agent. Refresh and retry with an unused name.",
    )


async def publish_draft(
    session_id: str,
    scenario: ScenarioConfig,
    agents: list[UnifiedAgent],
    *,
    snapshot: SessionAuthoringSnapshot,
    redis_manager: Any,
) -> None:
    """Persist every draft component in one CAS before any cache or live activation.

    The compare-and-set rejects concurrent edits (including other workers and
    live conversation writes) instead of overwriting a stale session snapshot.
    Cancellation waits for that bounded Redis operation to settle so a committed
    configuration is always published consistently to both local registries.
    """
    if redis_manager is None:
        raise DraftPersistenceError("Redis is required to apply a draft durably.")

    all_agents = dict(snapshot.agents)
    used_names = {agent_key(name) for name in all_agents}
    for agent in agents:
        key = agent_key(agent.name)
        if key in used_names:
            raise DraftStateConflict(f"Agent '{agent.name}' already exists; reuse it or rename it.")
        used_names.add(key)
        all_agents[agent.name] = agent
    if len(all_agents) > MAX_SESSION_AGENTS:
        raise DraftStateConflict(
            f"A session may contain at most {MAX_SESSION_AGENTS} custom agents."
        )

    all_scenarios = {**snapshot.scenarios, scenario_key(scenario.name): scenario}
    if len(all_scenarios) > MAX_SESSION_SCENARIOS:
        raise DraftStateConflict(
            f"A session may contain at most {MAX_SESSION_SCENARIOS} custom scenarios."
        )

    memo = snapshot.memo
    memo.set_corememory(
        session_agents.AGENTS_KEY_ALL,
        {name: session_agents._serialize_agent(agent) for name, agent in all_agents.items()},
    )
    memo.set_corememory(
        SCENARIO_KEY_ALL,
        {name: session_scenarios._serialize_scenario(item) for name, item in all_scenarios.items()},
    )
    memo.set_corememory(SCENARIO_KEY_CONFIG, session_scenarios._serialize_scenario(scenario))
    set_scenario_in_corememory(memo, scenario_key(scenario.name))
    memo.set_corememory("active_agent", scenario.start_agent)

    def publish() -> None:
        # No awaits between publication of agents and scenario activation.
        session_agents._session_agents[session_id] = all_agents
        session_agents._persisted_agent_data[session_id] = copy.deepcopy(
            {name: session_agents._serialize_agent(item) for name, item in all_agents.items()}
        )
        session_scenarios._session_scenarios[session_id] = all_scenarios
        session_scenarios._active_scenario[session_id] = scenario_key(scenario.name)
        now = time.monotonic()
        session_agents._session_load_times[session_id] = now
        session_scenarios._session_load_times[session_id] = now

        # Existing scenario notification resolves all agents and updates both orchestrators.
        if session_scenarios._scenario_update_callback:
            try:
                session_scenarios._scenario_update_callback(session_id, scenario)
            except Exception as exc:
                raise DraftActivationError(
                    "Draft saved, but the live scenario could not be refreshed. Reconnect the call."
                ) from exc

    await _commit_snapshot(
        session_id,
        snapshot,
        redis_manager,
        publish=publish,
        conflict_detail="The session changed during Apply. Review the draft and retry.",
    )
