"""Exercise evaluation adapters against the current voice runtime contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.voice.shared.base import OrchestratorContext
from apps.artagent.backend.voice.shared.metrics import OrchestratorMetrics
from src.stateful.state_managment import MemoManager

from tests.evaluation import scenario_runner
from tests.evaluation.recorder import EventRecorder
from tests.evaluation.schemas import EvalModelConfig, SessionAgentConfig, TurnEvent
from tests.evaluation.scorer import MetricsScorer
from tests.evaluation.validator import ExpectationValidator
from tests.evaluation.wrappers import EvaluationOrchestratorWrapper


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_runner, "_bootstrap_runtime", Mock())
    monkeypatch.setattr(scenario_runner, "_ensure_mcp_initialized", AsyncMock())
    monkeypatch.setenv("EVAL_STRICT_GATE", "0")
    path = tmp_path / "scenario.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "scenario_name": "contract",
                "agent": "Agent",
                "metadata": {"context": {"caller_name": "Ada"}},
                "turns": [{"turn_id": "turn_1", "user_input": "hello"}],
            }
        )
    )
    return scenario_runner.ScenarioRunner(path, tmp_path / "results")


@pytest.mark.asyncio
@pytest.mark.parametrize("with_consumer", [False, True])
async def test_tts_recording_preserves_runtime_keyword_arguments(tmp_path, with_consumer):
    async def process_turn(context, *, on_tts_chunk, **callbacks):
        await on_tts_chunk("spoken one", display_text="**display one**")
        await on_tts_chunk("spoken two", display_text="display two")
        return SimpleNamespace(response_text="display one display two", error=None)

    recorder = EventRecorder(run_id="callbacks", output_dir=tmp_path)
    adapter = SimpleNamespace(_active_agent="Agent", agents={}, process_turn=process_turn)
    wrapper = EvaluationOrchestratorWrapper(adapter, recorder)
    consumer = AsyncMock() if with_consumer else None
    result = await wrapper.process_turn(
        OrchestratorContext(
            session_id="session",
            user_text="hello",
            metadata={"run_id": "turn_1"},
        ),
        on_tts_chunk=consumer,
    )

    events = MetricsScorer().load_events(tmp_path / "callbacks_events.jsonl")
    assert result.error is None
    assert events[0].error is None
    assert events[0].tts_chunk_count == 2
    assert events[0].tts_first_chunk_ms is not None
    if consumer is not None:
        assert consumer.await_count == 2
        assert consumer.await_args_list[0].args == ("spoken one",)
        assert consumer.await_args_list[0].kwargs == {"display_text": "**display one**"}


@pytest.mark.asyncio
async def test_headless_run_uses_real_local_memory_for_tool_effects(runner, monkeypatch):
    orchestrator = scenario_runner._MockOrchestrator("Agent", None)
    original = orchestrator.process_turn
    observed = []

    async def process_turn(context, **callbacks):
        memo = context.metadata["memo_manager"]
        memo.persist_tool_output("effect", {"success": True, "reference": "committed"})
        observed.append(memo)
        return await original(context, **callbacks)

    monkeypatch.setattr(orchestrator, "process_turn", process_turn)
    monkeypatch.setattr(
        runner,
        "_create_orchestrator_with_overrides",
        lambda *args, **kwargs: (orchestrator, "Agent"),
    )

    await runner.run()

    assert len(observed) == 1
    memo = observed[0]
    assert isinstance(memo, MemoManager)
    assert memo.get_value_from_corememory("caller_name") == "Ada"
    assert memo.get_value_from_corememory("tool_outputs")["effect"] == {
        "success": True,
        "reference": "committed",
    }


@pytest.fixture
def adapter_factory(monkeypatch):
    agents = {name: UnifiedAgent(name=name) for name in ("Agent", "Target")}
    factory = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(scenario_runner, "discover_agents", lambda: agents)
    monkeypatch.setattr(scenario_runner.CascadeOrchestratorAdapter, "create", factory)
    monkeypatch.setattr(
        scenario_runner,
        "resolve_orchestrator_config",
        lambda **kwargs: SimpleNamespace(
            agents=agents, start_agent="Agent", handoff_map={}, scenario_name=None
        ),
    )
    return factory


def test_session_scenario_conversion_preserves_route_policy(runner, adapter_factory):
    config = SessionAgentConfig.model_validate(
        {
            "agents": ["Agent", "Target"],
            "start_agent": "Agent",
            "agent_defaults": {"institution_name": "Test Bank"},
            "handoffs": [
                {
                    "from": "Agent",
                    "to": "Target",
                    "tool": "handoff_target",
                    "share_context": False,
                    "handoff_condition": "Only on an explicit request",
                }
            ],
            "generic_handoff": {
                "enabled": True,
                "allowed_targets": ["Target"],
                "require_client_id": True,
                "share_context": False,
            },
        }
    )
    adapter, _ = runner._create_orchestrator_from_session_config(config, "session")
    scenario = adapter._cached_orchestrator_config.scenario

    assert scenario.handoffs[0].handoff_condition == "Only on an explicit request"
    assert scenario.handoffs[0].share_context is False
    assert scenario.generic_handoff.require_client_id is True
    assert scenario.generic_handoff.share_context is False
    assert scenario.agent_defaults.template_vars["institution_name"] == "Test Bank"
    assert adapter_factory.call_args.kwargs["handoff_map"] == scenario.build_handoff_map()


@pytest.mark.parametrize("mode", ["legacy", "overrides", "session"])
def test_headless_adapters_exercise_streaming_dispatch(runner, adapter_factory, mode):
    if mode == "session":
        config = SessionAgentConfig(agents=["Agent"], start_agent="Agent")
        runner._create_orchestrator_from_session_config(config, "session")
    elif mode == "overrides":
        runner._create_orchestrator_with_overrides("Agent", "session")
    else:
        runner._create_orchestrator("Agent", "session")

    assert adapter_factory.call_args.kwargs["streaming"] is True


def test_pipeline_error_cannot_pass_empty_functional_expectations():
    event = TurnEvent(
        session_id="session",
        turn_id="turn_1",
        user_end_ts=0,
        agent_last_output_ts=1,
        e2e_ms=1000,
        agent_name="Agent",
        user_text="hello",
        response_text="I encountered an error.",
        eval_model_config=EvalModelConfig(model_name="model", endpoint_used="chat"),
        error="callback rejected display_text",
    )

    result = ExpectationValidator().validate_turn(event, {})

    assert result.passed is False
    assert "runtime_error" in result.failed_checks


def test_banking_no_context_edge_starts_at_the_active_specialist():
    path = Path(__file__).parent / "scenarios/session_based/banking_context_sharing.yaml"
    data = yaml.safe_load(path.read_text())
    config = SessionAgentConfig.model_validate(data["session_config"])
    edge = next(
        edge
        for edge in config.handoffs
        if edge.from_agent == "DeclineSpecialist" and edge.to_agent == "FraudAgent"
    )
    assert edge.share_context is False


def test_banking_fixture_requires_the_same_condition_for_both_routing_forms():
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig

    path = Path(__file__).parent / "scenarios/session_based/banking_context_sharing.yaml"
    data = yaml.safe_load(path.read_text())
    config = ScenarioConfig.from_dict("banking_eval", data["session_config"])
    assert config.generic_handoff.enabled
    for edge in config.handoffs:
        assert "handoff_to_agent" in edge.handoff_condition
        rendered = config.build_handoff_instructions(edge.from_agent)
        assert " ".join(edge.handoff_condition.split()) in " ".join(rendered.split())
    recall = next(
        turn for turn in data["turns"] if turn["turn_id"] == "turn_3_decline_shared_context"
    )
    assert "05" not in recall["user_input"]
    assert recall["expectations"]["response_constraints"]["must_include"] == ["05"]


@pytest.mark.asyncio
@pytest.mark.parametrize("handoff", [False, True])
async def test_recorded_usage_is_incremental_across_turns_and_agent_resets(tmp_path, handoff):
    metrics = OrchestratorMetrics(agent_name="Agent")
    metrics.set_tokens(input_tokens=100, output_tokens=70)
    adapter = SimpleNamespace(_active_agent="Agent", agents={}, _metrics=metrics)
    adapter.set_on_agent_switch = lambda callback: setattr(adapter, "on_switch", callback)
    calls = 0

    async def process_turn(context, *, on_tool_start, **callbacks):
        nonlocal calls
        calls += 1
        metrics.add_tokens(input_tokens=20, output_tokens=10)
        if handoff and calls == 1:
            # Production emits tool_start before resetting its agent-session
            # counters, then notifies the switch before the target response.
            await on_tool_start("handoff_to_agent", {"target_agent": "Target"})
            metrics.reset_for_agent_switch("Target")
            adapter._active_agent = "Target"
            await adapter.on_switch("Agent", "Target")
            metrics.add_tokens(input_tokens=30, output_tokens=5)
        return SimpleNamespace(
            response_text="Short answer.",
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            error=None,
        )

    adapter.process_turn = process_turn
    wrapper = EvaluationOrchestratorWrapper(
        adapter, EventRecorder(run_id="usage", output_dir=tmp_path)
    )
    results = []
    for number in (1, 2):
        results.append(
            await wrapper.process_turn(
                OrchestratorContext(
                    session_id="session",
                    user_text="hello",
                    metadata={"run_id": f"turn_{number}"},
                )
            )
        )

    events = MetricsScorer().load_events(tmp_path / "usage_events.jsonl")
    assert [event.input_tokens for event in events] == ([50, 20] if handoff else [20, 20])
    assert [event.response_tokens for event in events] == ([15, 10] if handoff else [10, 10])
    assert results[1].output_tokens == (15 if handoff else 90)
