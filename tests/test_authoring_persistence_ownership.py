"""Exercise authoring ownership and uncertain commits through real Redis and MemoManager."""

from __future__ import annotations

import asyncio
import copy
import json
import shutil
import socket
import subprocess
import time
import uuid
from unittest.mock import Mock

import pytest
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent, VoiceConfig
from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig
from apps.artagent.backend.src.orchestration import session_agents as sa
from apps.artagent.backend.src.orchestration import session_scenarios as ss
from apps.artagent.backend.src.orchestration.session_drafts import (
    DraftStateConflict,
    publish_draft,
    read_authoring_snapshot,
)
from apps.artagent.backend.voice.shared.session_state import sync_state_to_memo
from opentelemetry import trace
from redis.exceptions import TimeoutError as RedisTimeoutError
from src.redis.manager import AUTHORING_REVISION_KEY, AzureRedisManager
from src.stateful.state_managment import MemoManager

import redis


@pytest.fixture(scope="module")
def redis_server(tmp_path_factory):
    """Run non-persistent Redis on loopback with its own temporary data directory."""
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("An existing redis-server executable is required for persistence regressions")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        [
            executable,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--daemonize",
            "no",
            "--pidfile",
            "",
            "--dir",
            str(tmp_path_factory.mktemp("authoring-redis")),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    client = redis.Redis(
        host="127.0.0.1",
        port=port,
        decode_responses=True,
        socket_timeout=1,
        socket_connect_timeout=1,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(process.communicate()[0].decode())
            try:
                if client.ping():
                    assert client.info("server")["process_id"] == process.pid
                    break
            except redis.ConnectionError:
                time.sleep(0.02)
        else:
            raise RuntimeError("Isolated Redis did not become ready")
        yield client, port
    finally:
        client.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


@pytest.fixture
def store(redis_server, monkeypatch):
    client, port = redis_server
    manager = object.__new__(AzureRedisManager)
    manager.redis_client = client
    manager.host = "127.0.0.1"
    manager.port = port
    manager.use_cluster = False
    manager.logger = Mock()
    manager.tracer = trace.get_tracer("tests.authoring.persistence")
    # Retry the same local connection after injected acknowledgement loss.
    manager._create_client = Mock()
    for module, fields in (
        (
            sa,
            (
                "_session_agents",
                "_session_load_times",
                "_persisted_agent_data",
                "_pending_agent_edits",
                "_agent_persist_tasks",
            ),
        ),
        (ss, ("_session_scenarios", "_active_scenario", "_session_load_times")),
    ):
        for field in fields:
            monkeypatch.setattr(module, field, {})
        monkeypatch.setattr(module, "_redis_manager", manager)
    monkeypatch.setattr(sa, "_adapter_update_callback", Mock())
    monkeypatch.setattr(ss, "_scenario_update_callback", Mock())
    return manager, f"ownership-{uuid.uuid4().hex}"


def new_agent(name: str = "OrderSpecialist") -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        prompt_template="You are an order specialist.",
        tool_names=[],
        voice=VoiceConfig(name="en-US-GuyNeural", rate="-4%"),
        template_vars={"examples": [], "attributes": {}},
    )


async def apply_scenario(manager, session_id):
    snapshot = await read_authoring_snapshot(session_id, manager)
    scenario = ScenarioConfig(
        name="Orders",
        agents=["OrderSpecialist"],
        start_agent="OrderSpecialist",
        global_template_vars={"company_name": "Example Co"},
    )
    await publish_draft(
        session_id, scenario, [new_agent()], snapshot=snapshot, redis_manager=manager
    )
    return scenario


@pytest.mark.asyncio
@pytest.mark.parametrize("synchronous", [False, True])
async def test_live_memo_saving_after_apply_cannot_erase_authoring_state(store, synchronous):
    manager, session_id = store
    live_memo = MemoManager(session_id=session_id)
    sync_state_to_memo(live_memo, active_agent="Concierge")
    assert await live_memo.persist_to_redis_async(manager, raise_on_failure=True)
    stale = MemoManager.from_redis(session_id, manager)

    await apply_scenario(manager, session_id)
    for index in range(2):
        sync_state_to_memo(stale, active_agent="Concierge")
        stale.set_context("slots", {"last_question": index})
        stale.append_to_history("Concierge", "user", f"Question {index}")
        if synchronous:
            await asyncio.to_thread(stale.persist_to_redis, manager)
        else:
            assert await stale.persist_to_redis_async(manager, raise_on_failure=True)

    sa._session_agents.clear()
    ss._session_scenarios.clear()
    ss._active_scenario.clear()
    restored = await read_authoring_snapshot(session_id, manager)
    assert "OrderSpecialist" in restored.agents
    assert restored.scenarios["orders"].start_agent == "OrderSpecialist"
    assert restored.memo.get_context("active_scenario_name") == "orders"
    assert restored.memo.get_context("active_agent") == "OrderSpecialist"
    assert restored.memo.get_context("slots") == {"last_question": 1}
    assert len(restored.memo.histories["Concierge"]) == 2
    assert restored.agents["OrderSpecialist"].template_vars == {"examples": [], "attributes": {}}
    assert restored.memo.get_context(AUTHORING_REVISION_KEY)


@pytest.mark.asyncio
async def test_quick_tune_survives_a_stale_conversation_save_and_allows_real_handoffs(store):
    manager, session_id = store
    concierge = new_agent("Concierge")
    sa.set_session_agent(session_id, concierge)
    sa.set_session_agent(session_id, new_agent("Orders"))
    await sa.persist_session_agents_to_redis(session_id, raise_on_failure=True)
    stale = MemoManager.from_redis(session_id, manager)
    sync_state_to_memo(stale, active_agent="Concierge")
    assert await stale.persist_to_redis_async(manager, raise_on_failure=True)
    old_revision = stale.get_context(AUTHORING_REVISION_KEY)

    tuned = copy.deepcopy(concierge)
    tuned.voice.rate = "-12%"
    sa.set_session_agent(session_id, tuned)
    await sa.persist_session_agents_to_redis(session_id, raise_on_failure=True)
    sync_state_to_memo(stale, active_agent="Orders", visited_agents={"Concierge", "Orders"})
    stale.append_to_history("Orders", "user", "Please check this order.")
    assert await stale.persist_to_redis_async(manager, raise_on_failure=True)
    restored = MemoManager.from_redis(session_id, manager)
    assert restored.get_context(sa.AGENTS_KEY_ALL)["Concierge"]["voice"]["rate"] == "-12%"
    assert restored.get_context(AUTHORING_REVISION_KEY) != old_revision
    assert restored.get_context("active_agent") == "Orders"
    assert set(restored.get_context("visited_agents")) == {"Concierge", "Orders"}
    assert restored.histories["Orders"][-1]["content"] == "Please check this order."


@pytest.mark.asyncio
async def test_quick_tune_from_an_older_worker_cache_preserves_new_agents_and_scenarios(store):
    manager, session_id = store
    sa.set_session_agent(session_id, new_agent("Concierge"))
    await sa.persist_session_agents_to_redis(session_id, raise_on_failure=True)
    old_cache = copy.deepcopy(sa._session_agents[session_id])
    old_baseline = copy.deepcopy(sa._persisted_agent_data[session_id])
    await apply_scenario(manager, session_id)
    sa._session_agents[session_id] = old_cache
    sa._persisted_agent_data[session_id] = old_baseline
    old_cache["Concierge"].voice.rate = "-9%"
    sa.set_session_agent(session_id, old_cache["Concierge"])
    await sa.persist_session_agents_to_redis(session_id, raise_on_failure=True)
    restored = await read_authoring_snapshot(session_id, manager)
    assert set(restored.agents) == {"Concierge", "OrderSpecialist"}
    assert restored.agents["Concierge"].voice.rate == "-9%"
    assert restored.memo.get_context("active_scenario_name") == "orders"
    assert restored.memo.get_context("active_agent") == "OrderSpecialist"


@pytest.mark.asyncio
async def test_authoring_write_preserves_newer_conversation_and_history(store):
    manager, session_id = store
    await apply_scenario(manager, session_id)
    old_author = MemoManager.from_redis(session_id, manager)
    live = MemoManager.from_redis(session_id, manager)
    live.set_context("slots", {"order_id": "fresh"})
    live.append_to_history("OrderSpecialist", "user", "Keep this new utterance.")
    assert await live.persist_to_redis_async(manager, raise_on_failure=True)
    old_author.set_corememory(
        "session_scenario_config",
        {**old_author.get_context("session_scenario_config"), "description": "Updated description"},
    )
    assert await old_author.persist_to_redis_async(
        manager, raise_on_failure=True, authoring_fields=("session_scenario_config",)
    )
    restored = MemoManager.from_redis(session_id, manager)
    assert restored.get_context("slots") == {"order_id": "fresh"}
    assert restored.histories["OrderSpecialist"][-1]["content"] == "Keep this new utterance."
    assert restored.get_context("session_scenario_config")["description"] == "Updated description"


async def await_new_tasks(before):
    tasks = asyncio.all_tasks() - before - {asyncio.current_task()}
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


@pytest.mark.asyncio
async def test_explicit_agent_and_scenario_reset_cannot_be_resurrected_by_stale_memo(store):
    manager, session_id = store
    await apply_scenario(manager, session_id)
    stale = MemoManager.from_redis(session_id, manager)
    before = asyncio.all_tasks()
    assert sa.remove_session_agent(session_id)
    assert ss.remove_session_scenario(session_id)
    await await_new_tasks(before)
    stale.append_to_history("OrderSpecialist", "user", "A final conversation event.")
    assert await stale.persist_to_redis_async(manager, raise_on_failure=True)
    restored = await read_authoring_snapshot(session_id, manager)
    assert restored.agents == {}
    assert restored.scenarios == {}
    assert restored.memo.get_context("active_scenario_name") is None
    assert restored.memo.get_context("scenario_name") is None
    assert (
        restored.memo.histories["OrderSpecialist"][-1]["content"] == "A final conversation event."
    )


@pytest.mark.asyncio
async def test_specific_agent_deletion_preserves_other_workers_agents(store):
    manager, session_id = store
    sa.set_session_agent(session_id, new_agent("Concierge"))
    await sa.persist_session_agents_to_redis(session_id, raise_on_failure=True)
    old_cache = copy.deepcopy(sa._session_agents[session_id])
    old_baseline = copy.deepcopy(sa._persisted_agent_data[session_id])
    await apply_scenario(manager, session_id)
    stale = MemoManager.from_redis(session_id, manager)
    sa._session_agents[session_id] = old_cache
    sa._persisted_agent_data[session_id] = old_baseline
    assert sa.remove_session_agent(session_id, "CONCIERGE")
    await sa.persist_session_agents_to_redis(session_id, raise_on_failure=True)
    assert await stale.persist_to_redis_async(manager, raise_on_failure=True)
    restored = await read_authoring_snapshot(session_id, manager)
    assert set(restored.agents) == {"OrderSpecialist"}


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted, remaining", [("first", "second"), ("second", "first")])
async def test_specific_scenario_delete_persists_and_does_not_resurrect(store, deleted, remaining):
    manager, session_id = store
    for name in ("First", "Second"):
        await ss.set_session_scenario_async(
            session_id, ScenarioConfig(name=name, agents=[name], start_agent=name)
        )
    stale = MemoManager.from_redis(session_id, manager)
    before = asyncio.all_tasks()
    assert ss.remove_session_scenario(session_id, deleted)
    await await_new_tasks(before)
    assert await stale.persist_to_redis_async(manager, raise_on_failure=True)
    restored = await read_authoring_snapshot(session_id, manager)
    assert set(restored.scenarios) == {remaining}
    assert restored.memo.get_context("active_scenario_name") == remaining
    assert restored.memo.get_context("active_agent") == remaining.title()


@pytest.mark.asyncio
async def test_scenario_updates_from_an_old_cache_do_not_drop_other_scenarios(store):
    manager, session_id = store
    await ss.set_session_scenario_async(
        session_id, ScenarioConfig(name="First", agents=["Concierge"], start_agent="Concierge")
    )
    old_cache = dict(ss._session_scenarios[session_id])
    await ss.set_session_scenario_async(
        session_id, ScenarioConfig(name="Second", agents=["Concierge"], start_agent="Concierge")
    )
    ss._session_scenarios[session_id] = old_cache
    ss._session_load_times[session_id] = time.monotonic()
    await ss.set_session_scenario_async(
        session_id,
        ScenarioConfig(
            name="First", description="Revised", agents=["Concierge"], start_agent="Concierge"
        ),
    )
    restored = await read_authoring_snapshot(session_id, manager)
    assert set(restored.scenarios) == {"first", "second"}
    assert restored.scenarios["first"].description == "Revised"


class LoseAcknowledgement:
    """Run the real EVAL, then fail once after Redis has committed it."""

    def __init__(self, client, *, after_commit=None):
        self.client = client
        self.eval_calls = 0
        self.after_commit = after_commit

    def __getattr__(self, name):
        return getattr(self.client, name)

    def eval(self, *args):
        result = self.client.eval(*args)
        self.eval_calls += 1
        if self.eval_calls == 1:
            if self.after_commit:
                self.after_commit()
            raise RedisTimeoutError("Acknowledgement lost after successful EVAL")
        return result


@pytest.mark.asyncio
async def test_cas_retry_recognizes_its_committed_write_and_publishes_once(store):
    manager, session_id = store
    uncertain = LoseAcknowledgement(manager.redis_client)
    manager.redis_client = uncertain
    await apply_scenario(manager, session_id)
    assert uncertain.eval_calls == 2
    assert ss._active_scenario[session_id] == "orders"
    assert "OrderSpecialist" in sa._session_agents[session_id]
    ss._scenario_update_callback.assert_called_once()
    persisted = MemoManager.from_redis(session_id, manager)
    assert persisted.get_context("active_scenario_name") == "orders"


@pytest.mark.asyncio
async def test_acknowledgement_retry_does_not_overwrite_a_later_history_write(store):
    manager, session_id = store
    raw_client = manager.redis_client
    history = json.dumps({"OrderSpecialist": [{"role": "user", "content": "Arrived after commit"}]})
    uncertain = LoseAcknowledgement(
        raw_client,
        after_commit=lambda: raw_client.hset(
            MemoManager.build_redis_key(session_id), "chat_history", history
        ),
    )
    manager.redis_client = uncertain
    await apply_scenario(manager, session_id)
    assert uncertain.eval_calls == 2
    assert (
        manager.get_session_data(MemoManager.build_redis_key(session_id))["chat_history"] == history
    )
    ss._scenario_update_callback.assert_called_once()


@pytest.mark.asyncio
async def test_replayed_acknowledgement_does_not_reactivate_a_superseded_scenario(store):
    manager, session_id = store
    raw_client = manager.redis_client
    other_manager = copy.copy(manager)
    other_manager.redis_client = raw_client

    def later_authoring_write():
        memo = MemoManager.from_redis(session_id, other_manager)
        replacement = ScenarioConfig(
            name="Later", agents=["OrderSpecialist"], start_agent="OrderSpecialist"
        )
        config = ss._serialize_scenario(replacement)
        memo.set_corememory("active_scenario_name", "later")
        memo.set_corememory("scenario_name", "later")
        memo.set_corememory("session_scenario_config", config)
        memo.persist_to_redis(
            other_manager,
            authoring_fields=("active_scenario_name", "scenario_name", "session_scenario_config"),
            registry_updates={"session_scenarios_all": {"later": config}},
        )

    manager.redis_client = LoseAcknowledgement(raw_client, after_commit=later_authoring_write)
    await apply_scenario(manager, session_id)
    assert manager.redis_client.eval_calls == 2
    assert ss._active_scenario[session_id] == "later"
    assert set(ss._session_scenarios[session_id]) == {"orders", "later"}
    ss._scenario_update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_real_competing_cas_is_not_misreported_as_a_replayed_success(store):
    manager, session_id = store
    stale = await read_authoring_snapshot(session_id, manager)
    await apply_scenario(manager, session_id)
    before = manager.get_session_data(MemoManager.build_redis_key(session_id))
    ss._scenario_update_callback.reset_mock()
    with pytest.raises(DraftStateConflict):
        await publish_draft(
            session_id,
            ScenarioConfig(name="Conflict", agents=["Other"], start_agent="Other"),
            [new_agent("Other")],
            snapshot=stale,
            redis_manager=manager,
        )
    assert manager.get_session_data(MemoManager.build_redis_key(session_id)) == before
    ss._scenario_update_callback.assert_not_called()
