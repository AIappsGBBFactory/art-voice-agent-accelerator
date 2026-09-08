"""Native loops share tool effects, but retain their own continuation contracts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
from apps.artagent.backend.voice.speech_cascade.orchestrator import (
    CascadeConfig,
    CascadeOrchestratorAdapter,
)
from azure.ai.voicelive.models import ResponseStatus, ServerEventType
from src.stateful.state_managment import MemoManager

from tests.test_cascade_llm_processing import AsyncStream, text_chunk
from tests.test_voicelive_tool_offload import (
    _drain,
    _fn_args_done,
    _make_orchestrator,
    _response_done,
)


def tool_chunk(*names):
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=index,
                            id=f"call-{index}",
                            function=SimpleNamespace(name=name, arguments="{}"),
                        )
                        for index, name in enumerate(names)
                    ],
                )
            )
        ],
    )


def cascade_for(memo, execute, *names):
    agent = UnifiedAgent(name="Agent", prompt_template="Help the customer.")
    agent.execute_tool = execute
    create = AsyncMock(
        side_effect=[AsyncStream([tool_chunk(*names)]), AsyncStream([text_chunk("Done.")])]
    )
    adapter = CascadeOrchestratorAdapter(
        config=CascadeConfig(start_agent="Agent", session_id=memo.session_id, streaming=True),
        agents={"Agent": agent},
        async_client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    return adapter, create


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["cascade", "voicelive"])
@pytest.mark.parametrize(
    "outcome",
    [
        {"authenticated": True, "client_id": "verified", "caller_name": "Maya"},
        {
            "success": True,
            "profile": {
                "client_id": "verified",
                "full_name": "Maya",
                "institution_name": "Example",
                "customer_intelligence": {"tier": "gold"},
            },
        },
        {"success": False, "slots": {"attempts": 2}},
    ],
)
async def test_both_native_loops_commit_the_same_result_policy(engine, outcome, monkeypatch):
    memo = MemoManager(session_id="tool-contract")
    memo.set_corememory("client_id", "previously-verified")
    memo.set_corememory("session_profile", {"full_name": "Initial"})
    execute = AsyncMock(return_value=outcome)
    if engine == "cascade":
        adapter, _ = cascade_for(memo, execute, "lookup")
        await adapter.process_turn(user_text="Look up my account", memo_manager=memo)
    else:
        adapter, _ = _make_orchestrator()
        adapter._memo_manager = memo
        monkeypatch.setattr(
            "apps.artagent.backend.voice.voicelive.orchestrator.execute_tool", execute
        )
        await adapter.handle_event(_fn_args_done("call", "lookup", {}))
        await adapter.handle_event(_response_done("response", ResponseStatus.COMPLETED))
        await _drain(adapter)
    execute.assert_awaited_once()
    args = execute.call_args.args[1]
    assert args["_client_id"] == "previously-verified"
    assert args["_session_profile"] == {"full_name": "Initial"}
    if outcome.get("success") or outcome.get("authenticated"):
        assert memo.get_value_from_corememory("client_id") == "verified"
        assert memo.get_value_from_corememory("caller_name") == "Maya"
    if "profile" in outcome:
        assert memo.get_value_from_corememory("session_profile") == outcome["profile"]
        assert memo.get_value_from_corememory("institution_name") == "Example"
    if "slots" in outcome:
        assert memo.get_context("slots") == {"attempts": 2}


@pytest.mark.asyncio
async def test_cascade_keeps_business_effect_and_history_when_notification_is_cancelled():
    memo = MemoManager(session_id="tool-cancel")
    adapter, create = cascade_for(
        memo, AsyncMock(return_value={"slots": {"committed": True}}), "lookup"
    )
    notified = asyncio.Event()

    async def notification(*args):
        notified.set()
        await asyncio.Event().wait()

    turn = asyncio.create_task(
        adapter.process_turn(
            user_text="Lookup",
            memo_manager=memo,
            on_tool_end=notification,
        )
    )
    await asyncio.wait_for(notified.wait(), 1)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    assert memo.get_context("slots") == {"committed": True}
    assert any(message.get("role") == "tool" for message in memo.get_history("Agent"))
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_cascade_mixed_batch_commits_business_before_returning_handoff():
    memo = MemoManager(session_id="mixed-tools")
    execute = AsyncMock(return_value={"slots": {"account": "ready"}})
    adapter, create = cascade_for(memo, execute, "lookup", "handoff_to_agent")
    adapter._current_memo_manager = memo
    # The native LLM stage returns routing to process_turn, not to tool-name heuristics.
    _, calls = await adapter._process_llm([{"role": "user", "content": "Transfer"}], [])
    assert [call["name"] for call in calls] == ["lookup", "handoff_to_agent"]
    assert memo.get_context("slots") == {"account": "ready"}
    execute.assert_awaited_once()
    create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["output", "context"])
async def test_voicelive_rechecks_epoch_after_every_notification_await(phase, monkeypatch):
    orch, conn = _make_orchestrator()
    execute = AsyncMock(return_value={"success": True})
    monkeypatch.setattr("apps.artagent.backend.voice.voicelive.orchestrator.execute_tool", execute)

    async def interrupt(*args, **kwargs):
        await orch.handle_event(
            SimpleNamespace(type=ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED)
        )

    if phase == "output":
        conn.conversation.item.create.side_effect = interrupt
    else:
        orch._update_session_context.side_effect = interrupt
    await orch.handle_event(_fn_args_done("call", "lookup", {}))
    await orch.handle_event(_response_done("response", ResponseStatus.COMPLETED))
    await _drain(orch)
    execute.assert_awaited_once()
    conn.response.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_response_done_does_not_finalize_the_new_response_batch(monkeypatch):
    orch, conn = _make_orchestrator()
    release = asyncio.Event()

    async def execute(name, args):
        if name == "slow":
            await release.wait()
        return {"success": True}

    monkeypatch.setattr("apps.artagent.backend.voice.voicelive.orchestrator.execute_tool", execute)
    for response_id, tool_name in (("old", "slow"), ("new", "fast")):
        await orch.handle_event(
            SimpleNamespace(
                type=ServerEventType.RESPONSE_CREATED,
                response=SimpleNamespace(id=response_id),
            )
        )
        event = _fn_args_done(response_id, tool_name, {})
        event.response_id = response_id
        await orch.handle_event(event)
    orch._seen_transcript_delta_ids.add("new-transcript")
    orch._response_had_tool_calls = True
    await orch.handle_event(_response_done("old", ResponseStatus.CANCELLED))
    assert "new" in orch._tool_batches
    assert orch._seen_transcript_delta_ids == {"new-transcript"}
    assert orch._response_had_tool_calls
    await orch.handle_event(_response_done("new", ResponseStatus.COMPLETED))
    release.set()
    await _drain(orch)
    conn.response.create.assert_awaited_once()
    outputs = conn.conversation.item.create.call_args_list
    assert [call.kwargs["item"].call_id for call in outputs] == ["new"]


@pytest.mark.asyncio
async def test_greeting_cancel_transport_failure_does_not_claim_a_sent_response():
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
    from apps.artagent.backend.voice.voicelive.session import trigger_voicelive_response

    conn = SimpleNamespace(
        response=SimpleNamespace(cancel=AsyncMock(side_effect=RuntimeError("transport closed"))),
        send=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="transport closed"):
        await trigger_voicelive_response(UnifiedAgent(name="Agent"), conn, say="Welcome")
    conn.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_scenario_update_is_owned_and_joined_before_close(monkeypatch):
    from apps.artagent.backend.voice.voicelive import session

    orch, _ = _make_orchestrator()
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def apply(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
            await release.wait()

    monkeypatch.setattr(session, "apply_voicelive_session", apply)
    orch._schedule_scenario_session_update()
    await entered.wait()
    assert orch._owned_tasks
    closing = asyncio.create_task(orch.cancel_and_join_tasks())
    await asyncio.wait_for(cancelled.wait(), 1)
    assert not closing.done()
    release.set()
    await asyncio.wait_for(closing, 1)
    assert not orch._owned_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("share_context", [False, True])
async def test_cascade_target_prompt_and_later_turn_use_resolved_handoff_context(share_context):
    from apps.artagent.backend.registries.scenariostore.loader import HandoffConfig, ScenarioConfig
    from apps.artagent.backend.voice.shared.handoff_service import HandoffService

    memo = MemoManager(session_id="handoff-policy")
    memo.set_corememory("session_profile", {"client_id": "source-private-profile"})
    agents = {
        "Source": UnifiedAgent(name="Source"),
        "Target": UnifiedAgent(
            name="Target",
            prompt_template=(
                "{{ session_profile | default('absent') }};"
                "{{ handoff_context | default({}) }};"
                "{{ case_id | default('missing') }};"
                "{{ memo_manager | default('no-transport') }}"
            ),
        ),
    }
    adapter = CascadeOrchestratorAdapter(
        config=CascadeConfig(start_agent="Source", session_id=memo.session_id),
        agents=agents,
        async_client=SimpleNamespace(),
    )
    adapter._handoff_service = HandoffService(
        agents=agents,
        scenario=ScenarioConfig(
            name="policy",
            handoffs=[
                HandoffConfig(
                    from_agent="Source",
                    to_agent="Target",
                    tool="handoff_case",
                    share_context=share_context,
                    context_vars={"case_id": "scenario-case"},
                )
            ],
        ),
    )
    adapter._process_llm = AsyncMock(
        side_effect=[
            (
                "",
                [
                    {
                        "name": "handoff_case",
                        "arguments": json.dumps({"context": {"raw": "raw-secret"}}),
                    }
                ],
            ),
            ("Target response is complete.", []),
            ("The next turn is complete.", []),
        ]
    )
    result = await adapter.process_turn(user_text="source-private-utterance", memo_manager=memo)
    assert result.agent_name == "Target"
    target_messages = adapter._process_llm.call_args_list[1].kwargs["messages"]
    target_prompt = target_messages[0]["content"]
    assert "scenario-case" in target_prompt
    assert "raw-secret" not in target_prompt
    assert "no-transport" in target_prompt
    assert ("source-private-profile" in target_prompt) is share_context
    assert any("source-private-utterance" in m["content"] for m in target_messages) is share_context
    assert adapter._session_vars["case_id"] == "scenario-case"
    assert (
        memo.get_value_from_corememory("session_profile")["client_id"] == "source-private-profile"
    )

    await adapter.process_turn(user_text="Continue this case", memo_manager=memo)
    next_prompt = adapter._process_llm.call_args.kwargs["messages"][0]["content"]
    assert "scenario-case" in next_prompt
    assert ("source-private-profile" in next_prompt) is share_context
