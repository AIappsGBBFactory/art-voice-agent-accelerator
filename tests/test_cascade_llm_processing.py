"""
Cascade Orchestrator LLM Processing Tests
==========================================

Tests for the _process_llm() method to ensure functionality is preserved
during Priority 3 refactoring (breaking down the 537-line method).

These tests capture current behavior before extracting:
- Streaming logic
- Tool execution loop
- Sentence buffering
- Error handling
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

if TYPE_CHECKING:
    from apps.artagent.backend.voice.shared.base import OrchestratorContext


class AsyncStream:
    """Strict async SDK stream: sync iteration is deliberately unsupported."""

    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration

    async def close(self):
        self.closed = True


def text_chunk(text):
    return SimpleNamespace(
        usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))]
    )


class TestAsyncProducerOwnership:
    @pytest.mark.asyncio
    async def test_process_turn_borrows_application_client_across_turns(self, cascade_adapter):
        from apps.artagent.backend.voice.shared.base import OrchestratorContext
        from src.aoai.client_manager import AoaiClientManager

        create = AsyncMock(side_effect=lambda **kwargs: AsyncStream([text_chunk("A response.")]))
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            close=AsyncMock(),
        )
        manager = AoaiClientManager(async_factory=lambda: client)
        context = OrchestratorContext(
            session_id="test-session",
            user_text="hello",
            websocket=SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(aoai_client_manager=manager))
            ),
        )
        first = await cascade_adapter.process_turn(context)
        second = await cascade_adapter.process_turn(context)
        assert first.response_text == second.response_text == "A response."
        assert create.await_count == 2
        client.close.assert_not_awaited()
        assert cascade_adapter.async_client is None
        await manager.aclose()
        client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_turn_closes_standalone_client(self, cascade_adapter, monkeypatch):
        from apps.artagent.backend.voice.shared.base import OrchestratorContext
        from src.aoai import client as client_module

        class Client:
            def __init__(self):
                self.closed = False
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=AsyncMock(
                            return_value=AsyncStream([text_chunk("Offline response.")])
                        )
                    )
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.closed = True

        client = Client()
        monkeypatch.setattr(
            client_module, "create_async_azure_openai_client", lambda: client, raising=False
        )
        result = await cascade_adapter.process_turn(
            OrchestratorContext(session_id="standalone", user_text="hi")
        )
        assert result.response_text == "Offline response."
        assert client.closed
        assert cascade_adapter.async_client is None

    @pytest.mark.asyncio
    async def test_cancel_closes_stream_blocked_waiting_for_provider(self, cascade_adapter):
        entered = asyncio.Event()

        class BlockedStream(AsyncStream):
            async def __anext__(self):
                entered.set()
                await asyncio.Event().wait()

        stream = BlockedStream([])
        cascade_adapter.async_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream)))
        )
        turn = asyncio.create_task(cascade_adapter._process_llm([], []))
        await asyncio.wait_for(entered.wait(), 1)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(turn, 1)
        assert stream.closed
        assert not any(task.get_name() == "cascade-llm-stream" for task in asyncio.all_tasks())

    @pytest.mark.asyncio
    async def test_bounded_backpressure_cancel_joins_producer(self, cascade_adapter):
        consumed = 0
        entered_tts = asyncio.Event()

        class CountingStream(AsyncStream):
            async def __anext__(self):
                nonlocal consumed
                consumed += 1
                return await super().__anext__()

        stream = CountingStream([text_chunk("Another sentence. ") for _ in range(100)])

        async def slow_tts(text, *, display_text):
            entered_tts.set()
            await asyncio.Event().wait()

        cascade_adapter.async_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream)))
        )
        turn = asyncio.create_task(cascade_adapter._process_llm([], [], slow_tts))
        await asyncio.wait_for(entered_tts.wait(), 1)
        await asyncio.sleep(0.01)
        # One dispatched sentence + eight buffered + the put blocked on capacity.
        assert consumed <= 10
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(turn, 1)
        assert stream.closed

    @pytest.mark.asyncio
    async def test_cancel_during_client_request_is_awaited(self, cascade_adapter):
        entered = asyncio.Event()
        stopped = asyncio.Event()

        async def create(**kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        cascade_adapter.async_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        turn = asyncio.create_task(cascade_adapter._process_llm([], []))
        await asyncio.wait_for(entered.wait(), 1)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(turn, 1)
        assert stopped.is_set()


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_memo_manager():
    """Create a mock MemoManager for testing."""
    mm = MagicMock()
    mm.get_history = MagicMock(return_value=[])
    mm.append_to_history = MagicMock()
    mm.get_value_from_corememory = MagicMock(return_value=None)
    mm.history.get_all = MagicMock(return_value={})
    mm.persist_tool_output = MagicMock()
    mm.update_slots = MagicMock()
    mm.get_context = MagicMock(return_value={})
    mm.set_context = MagicMock()
    return mm


@pytest.fixture
def mock_agent():
    """Create a mock UnifiedAgent with tool execution."""
    from apps.artagent.backend.registries.agentstore.base import ModelConfig, UnifiedAgent

    agent = UnifiedAgent(
        name="TestAgent",
        description="Test agent for LLM processing tests",
        greeting="Hello, I'm TestAgent",
        model=ModelConfig(deployment_id="gpt-4o", temperature=0.7),
        prompt_template="You are a test agent.",
        tool_names=["get_weather", "handoff_test"],
    )

    # Mock tool execution
    async def mock_execute_tool(name: str, args: dict):
        if name == "get_weather":
            return {"weather": "sunny", "temperature": 72}
        elif name == "handoff_test":
            return {"success": True}
        return {"error": f"Unknown tool: {name}"}

    agent.execute_tool = AsyncMock(side_effect=mock_execute_tool)

    # Mock get_model_for_mode
    agent.get_model_for_mode = MagicMock(return_value=agent.model)

    return agent


@pytest.fixture
def cascade_adapter(mock_agent, mock_memo_manager):
    """Create a CascadeOrchestratorAdapter with mock agent."""
    from apps.artagent.backend.voice.speech_cascade.orchestrator import (
        CascadeConfig,
        CascadeOrchestratorAdapter,
    )

    config = CascadeConfig(
        start_agent="TestAgent",
        session_id="test-session",
        call_connection_id="test-call",
    )

    adapter = CascadeOrchestratorAdapter(
        config=config,
        agents={"TestAgent": mock_agent},
        handoff_map={},
    )

    adapter._current_memo_manager = mock_memo_manager

    return adapter


# ═══════════════════════════════════════════════════════════════════════════════
# BASELINE TESTS - Current _process_llm() Behavior
# ═══════════════════════════════════════════════════════════════════════════════


class TestProcessLLMBaseline:
    """
    BASELINE: Test current _process_llm() behavior.

    These tests ensure we don't break functionality during refactoring.
    """

    @pytest.mark.asyncio
    async def test_simple_text_response(self, cascade_adapter):
        """
        BASELINE: _process_llm should handle simple text responses.
        """
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        tools = []

        # Mock the OpenAI client response
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta = MagicMock()
        mock_chunk.choices[0].delta.content = "Hello! How can I help you?"
        mock_chunk.choices[0].delta.tool_calls = None

        with patch.object(cascade_adapter, "async_client") as mock_client:
            mock_stream = AsyncStream([mock_chunk])
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

            response_text, tool_calls = await cascade_adapter._process_llm(
                messages=messages, tools=tools
            )

            # Verify response
            assert response_text == "Hello! How can I help you?"
            assert tool_calls == []
            assert mock_stream.closed

    @pytest.mark.asyncio
    async def test_streaming_with_tts_callback(self, cascade_adapter):
        """
        BASELINE: _process_llm should call TTS callback with sentence chunks.
        """
        messages = [
            {"role": "user", "content": "Tell me about the weather."},
        ]
        tools = []

        # Mock streaming response with sentences
        chunks = [
            "Hello! ",
            "The weather is sunny. ",
            "Temperature is 72 degrees.",
        ]

        mock_chunks = []
        for content in chunks:
            mock_chunk = MagicMock()
            mock_chunk.choices = [MagicMock()]
            mock_chunk.choices[0].delta = MagicMock()
            mock_chunk.choices[0].delta.content = content
            mock_chunk.choices[0].delta.tool_calls = None
            mock_chunks.append(mock_chunk)

        tts_callback = AsyncMock()

        with patch.object(cascade_adapter, "async_client") as mock_client:
            mock_stream = AsyncStream(mock_chunks)
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

            response_text, tool_calls = await cascade_adapter._process_llm(
                messages=messages, tools=tools, on_tts_chunk=tts_callback
            )

            # Verify TTS callback was called (may be called multiple times for sentences)
            assert tts_callback.called
            assert response_text == "Hello! The weather is sunny. Temperature is 72 degrees."

    @pytest.mark.asyncio
    async def test_tool_call_detection_and_execution(self, cascade_adapter, mock_agent):
        """
        BASELINE: _process_llm should detect tool calls and execute them.
        """
        messages = [
            {"role": "user", "content": "What's the weather?"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        # Mock streaming response with tool call
        tool_call_chunk = MagicMock()
        tool_call_chunk.choices = [MagicMock()]
        tool_call_chunk.choices[0].delta = MagicMock()
        tool_call_chunk.choices[0].delta.content = None

        # Mock tool call structure
        mock_tc = MagicMock()
        mock_tc.index = 0
        mock_tc.id = "call_123"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = "{}"

        tool_call_chunk.choices[0].delta.tool_calls = [mock_tc]

        # Second response after tool execution
        followup_chunk = MagicMock()
        followup_chunk.choices = [MagicMock()]
        followup_chunk.choices[0].delta = MagicMock()
        followup_chunk.choices[0].delta.content = "The weather is sunny!"
        followup_chunk.choices[0].delta.tool_calls = None

        with patch.object(cascade_adapter, "async_client") as mock_client:

            # First call returns tool call, second call returns followup
            call_count = [0]

            def create_stream(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return AsyncStream([tool_call_chunk])
                else:
                    return AsyncStream([followup_chunk])

            mock_client.chat.completions.create = AsyncMock(side_effect=create_stream)

            response_text, tool_calls = await cascade_adapter._process_llm(
                messages=messages, tools=tools
            )

            # Verify tool was executed
            assert mock_agent.execute_tool.called
            assert len(tool_calls) == 1
            assert tool_calls[0]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_handoff_tool_returns_immediately(self, cascade_adapter):
        """
        BASELINE: _process_llm should return immediately on handoff tool calls.
        """
        messages = [
            {"role": "user", "content": "Transfer me to support"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "handoff_support",
                    "description": "Transfer to support",
                },
            }
        ]

        # Mock handoff service
        cascade_adapter.handoff_service.is_handoff = MagicMock(return_value=True)

        # Mock streaming response with handoff tool call
        tool_call_chunk = MagicMock()
        tool_call_chunk.choices = [MagicMock()]
        tool_call_chunk.choices[0].delta = MagicMock()
        tool_call_chunk.choices[0].delta.content = None

        mock_tc = MagicMock()
        mock_tc.index = 0
        mock_tc.id = "call_handoff"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "handoff_support"
        mock_tc.function.arguments = "{}"

        tool_call_chunk.choices[0].delta.tool_calls = [mock_tc]

        with patch.object(cascade_adapter, "async_client") as mock_client:
            mock_stream = AsyncStream([tool_call_chunk])
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

            response_text, tool_calls = await cascade_adapter._process_llm(
                messages=messages, tools=tools
            )

            # Verify handoff tool is returned without execution
            assert len(tool_calls) == 1
            assert tool_calls[0]["name"] == "handoff_support"

    @pytest.mark.asyncio
    async def test_error_handling_returns_user_friendly_message(self, cascade_adapter):
        """Provider errors are classified and spoken, not silently lost."""
        with patch.object(cascade_adapter, "async_client") as client:
            client.chat.completions.create = AsyncMock(side_effect=TimeoutError("provider timeout"))
            response, tools = await cascade_adapter._process_llm(
                [{"role": "user", "content": "hi"}], []
            )
        assert response
        assert tools == []
        assert cascade_adapter._last_error_info is not None

    @pytest.mark.asyncio
    async def test_max_iterations_prevents_infinite_loop(self, cascade_adapter, mock_agent):
        """
        BASELINE: _process_llm should stop after max iterations to prevent infinite loops.
        """
        messages = [{"role": "user", "content": "Test"}]
        tools = [
            {
                "type": "function",
                "function": {"name": "get_weather"},
            }
        ]

        # Mock tool call that keeps returning itself
        tool_call_chunk = MagicMock()
        tool_call_chunk.choices = [MagicMock()]
        tool_call_chunk.choices[0].delta = MagicMock()
        tool_call_chunk.choices[0].delta.content = None

        mock_tc = MagicMock()
        mock_tc.index = 0
        mock_tc.id = "call_loop"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = "{}"

        tool_call_chunk.choices[0].delta.tool_calls = [mock_tc]

        with patch.object(cascade_adapter, "async_client") as mock_client:
            # Always return tool call (would loop forever without max_iterations)
            mock_client.chat.completions.create = AsyncMock(
                side_effect=lambda **kwargs: AsyncStream([tool_call_chunk])
            )

            # Call with low max_iterations
            response_text, tool_calls = await cascade_adapter._process_llm(
                messages=messages, tools=tools, _max_iterations=2
            )

            # Verify it stopped (didn't hang)
            # Tool execution count should be limited
            assert mock_agent.execute_tool.call_count <= 2


# ═══════════════════════════════════════════════════════════════════════════════
# COMPONENT TESTS - Individual Functionality
# ═══════════════════════════════════════════════════════════════════════════════


class TestTTSTextProcessing:
    """
    Test TTS text processing utilities that will be extracted.
    """

    def test_sanitize_tts_text_removes_markdown(self):
        """
        Test that _sanitize_tts_text removes markdown formatting.
        """
        text = "Here's a [link](http://example.com) and `code` block."
        from apps.artagent.backend.voice.speech_cascade.tts_processor import TTSTextProcessor

        result = TTSTextProcessor.sanitize_tts_text(text)

        assert "[" not in result
        assert "`" not in result
        assert "link" in result
        assert "code" in result

    def test_find_tts_boundary_detects_sentences(self):
        """
        Test that _find_tts_boundary finds sentence endings.
        """
        text = "Hello there. How are you?"
        from apps.artagent.backend.voice.speech_cascade.tts_processor import TTSTextProcessor

        boundary = TTSTextProcessor.find_tts_boundary(text, ".!?", 0)

        assert boundary > 0
        assert text[boundary] == "."

    def test_split_tts_buffer_splits_correctly(self):
        """
        Test that _split_tts_buffer splits at the right position.
        """
        text = "First sentence. Second sentence."
        from apps.artagent.backend.voice.speech_cascade.tts_processor import TTSTextProcessor

        left, right = TTSTextProcessor.split_tts_buffer(text, 15)

        assert "First sentence." in left
        assert "Second" in right


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════════════════════


class TestLLMProcessingIntegration:
    """
    INTEGRATION: End-to-end LLM processing test.
    """

    @pytest.mark.asyncio
    async def test_full_conversation_flow(self, cascade_adapter, mock_agent, mock_memo_manager):
        """
        INTEGRATION: Test full conversation flow with streaming, tools, and history.
        """
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What's the weather?"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        # Mock complete flow: tool call → tool result → final response
        tool_chunk = MagicMock()
        tool_chunk.choices = [MagicMock()]
        tool_chunk.choices[0].delta = MagicMock()
        tool_chunk.choices[0].delta.content = None
        mock_tc = MagicMock()
        mock_tc.index = 0
        mock_tc.id = "call_weather"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = "{}"
        tool_chunk.choices[0].delta.tool_calls = [mock_tc]

        final_chunk = MagicMock()
        final_chunk.choices = [MagicMock()]
        final_chunk.choices[0].delta = MagicMock()
        final_chunk.choices[0].delta.content = "The weather is sunny and 72 degrees!"
        final_chunk.choices[0].delta.tool_calls = None

        tts_callback = AsyncMock()
        tool_start_callback = AsyncMock()
        tool_end_callback = AsyncMock()

        with patch.object(cascade_adapter, "async_client") as mock_client:

            call_count = [0]

            def create_stream(**kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return AsyncStream([tool_chunk])
                else:
                    return AsyncStream([final_chunk])

            mock_client.chat.completions.create = AsyncMock(side_effect=create_stream)

            response_text, tool_calls = await cascade_adapter._process_llm(
                messages=messages,
                tools=tools,
                on_tts_chunk=tts_callback,
                on_tool_start=tool_start_callback,
                on_tool_end=tool_end_callback,
            )

            # Verify full flow
            assert response_text == "The weather is sunny and 72 degrees!"
            assert len(tool_calls) == 1
            assert mock_agent.execute_tool.called
            assert tool_start_callback.called
            assert tool_end_callback.called
            assert tts_callback.called
