"""
Cascade model request binding — focused fix verification.

Companion to ``tests/test_quick_tune_service_bindings.py::TestCascadeModelAdvancedSettings``,
which documents the *bug*: ``endpoint_preference``, ``api_version``,
``reasoning_effort``, ``verbosity``, ``store``, ``metadata``, and
``response_format`` were computed only for tracing/span attributes and never
reached ``client.chat.completions.create(**params)``, and the streaming path
never actually dispatched to the Responses API regardless of
``endpoint_preference``.

This file verifies the *fix* in
``apps/artagent/backend/voice/speech_cascade/orchestrator.py``:

  * ``CascadeOrchestratorAdapter._prepare_streaming_params`` (chat.completions
    path) now forwards ``reasoning_effort``, ``verbosity``, ``store``,
    ``metadata``, and ``response_format`` — confirmed valid keyword
    parameters on the installed openai SDK's
    ``chat.completions.create`` signature via ``inspect.signature`` — while
    leaving prior defaults byte-for-byte unchanged when unconfigured.
  * ``CascadeOrchestratorAdapter._prepare_responses_streaming_params`` (new)
    builds a real ``responses.create`` request: ``instructions``/``input``
    (not the flattened single text blob ``AzureOpenAIManager._prepare_responses_params``
    produces), ``max_output_tokens``, ``reasoning.effort``, ``text.verbosity``.
  * ``_resolve_endpoint_choice`` only ever routes to "responses" on an
    explicit ``endpoint_preference == "responses"``; every other value
    preserves the default chat streaming path, and the choice is never
    silently swapped.
  * ``_resolve_api_version_override`` only overrides the shared client's
    ``api_version`` when explicitly configured away from the schema
    default, and does so via ``with_options`` (verified against the
    installed SDK's ``AzureOpenAI.copy``/``with_options`` reusing the
    existing transport/credentials — see ``test_api_version_override_reuses_with_options``).
  * ``_validate_model_config_capabilities`` rejects ``min_p``/``typical_p``
    clearly on both endpoints (raising ``UnsupportedModelOptionError``,
    surfaced by ``_extract_error_details`` as a structured
    ``UnsupportedModelOption`` error) instead of silently dropping them —
    neither has an equivalent keyword argument on ``chat.completions.create``
    or ``responses.create`` in the installed openai SDK (verified via
    ``inspect.signature`` against both). ``include_reasoning`` means
    "surface an available reasoning SUMMARY", never raw hidden
    chain-of-thought — the Responses endpoint genuinely supports this via
    ``reasoning.summary``, so it is only rejected when the resolved
    endpoint is chat.completions (which has no such concept at all).
  * ``_normalize_responses_stream`` converts real (constructed, not
    hand-stubbed) ``openai.types.responses`` streaming events into the same
    ChatCompletionChunk-shaped objects the existing tool-call/text
    accumulation logic already consumes, so structured tool calls, tool
    arguments, text deltas, and usage all round-trip correctly for the
    Responses path too.

Only the network boundary (a fake ``client.responses.create`` /
``client.chat.completions.create`` iterator) is mocked; every parameter
builder and the event normalizer run as real production code.
"""

from __future__ import annotations

import json

import pytest
from apps.artagent.backend.registries.agentstore.base import ModelConfig
from apps.artagent.backend.voice.speech_cascade.orchestrator import (
    CascadeOrchestratorAdapter,
    UnsupportedModelOptionError,
    _convert_messages_to_responses_input,
    _convert_tools_to_responses_format,
    _map_verbosity_level,
    _normalize_responses_stream,
    _resolve_api_version_override,
    _resolve_endpoint_choice,
    _validate_model_config_capabilities,
)
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseOutputItemAddedEvent,
    ResponseTextDeltaEvent,
)
from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)

CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Look up the weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]


def _model_config(**overrides) -> ModelConfig:
    base = dict(
        deployment_id="gpt-4o",
        temperature=0.55,
        top_p=0.8,
        max_tokens=555,
    )
    base.update(overrides)
    return ModelConfig(**base)


# ─────────────────────────────────────────────────────────────────────
# 1. Chat path — advanced properties now genuinely reach the request,
#    backward-compatible defaults are preserved.
# ─────────────────────────────────────────────────────────────────────


class TestChatStreamingParamsBinding:
    def test_default_config_matches_prior_param_set_exactly(self) -> None:
        """An agent that never touches the Advanced Builder controls gets
        byte-for-byte the same request it always has — no new keys appear.
        """
        model_config = _model_config()
        messages = [{"role": "user", "content": "hi"}]

        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", messages, None
        )

        assert set(params.keys()) == {
            "model",
            "messages",
            "stream",
            "timeout",
            "max_tokens",
            "temperature",
            "top_p",
        }
        assert params["temperature"] == 0.55
        assert params["top_p"] == 0.8
        assert params["max_tokens"] == 555

    def test_reasoning_effort_verbosity_store_metadata_response_format_reach_the_call(self) -> None:
        model_config = _model_config(
            reasoning_effort="high",
            verbosity=2,
            store=True,
            metadata={"trace": "abc"},
            response_format={"type": "json_object"},
        )
        messages = [{"role": "user", "content": "hi"}]

        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", messages, None
        )

        assert params["reasoning_effort"] == "high"
        assert params["verbosity"] == "high"  # mapped from int 2
        assert params["store"] is True
        assert params["metadata"] == {"trace": "abc"}
        assert params["response_format"] == {"type": "json_object"}

    def test_verbosity_zero_default_is_not_forwarded(self) -> None:
        """verbosity=0 is ModelConfig's own default (real-time/minimal); it
        is treated as "not configured" so pre-existing agents that never set
        it keep receiving a request with no verbosity key at all.
        """
        model_config = _model_config(verbosity=0)
        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", [{"role": "user", "content": "hi"}], None
        )
        assert "verbosity" not in params

    def test_store_false_is_forwarded_explicitly(self) -> None:
        """store=False is a meaningful explicit value (distinct from the
        None default) and must not be dropped."""
        model_config = _model_config(store=False)
        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", [{"role": "user", "content": "hi"}], None
        )
        assert params["store"] is False

    def test_min_p_typical_p_never_merge_into_chat_params(self) -> None:
        """Even though these are genuinely unsupported (rejected earlier by
        _validate_model_config_capabilities in the live call path), the pure
        param builder itself must never emit a key with no meaning to
        chat.completions.create.
        """
        model_config = _model_config(min_p=0.1, typical_p=0.2)
        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", [{"role": "user", "content": "hi"}], None
        )
        assert "min_p" not in params
        assert "typical_p" not in params

    def test_endpoint_preference_and_api_version_are_not_chat_completions_params(self) -> None:
        model_config = _model_config(endpoint_preference="auto", api_version="2025-01-01-preview")
        params = CascadeOrchestratorAdapter._prepare_streaming_params(
            None, model_config, "gpt-4o", [{"role": "user", "content": "hi"}], None
        )
        assert "endpoint_preference" not in params
        assert "api_version" not in params


# ─────────────────────────────────────────────────────────────────────
# 2. Endpoint dispatch resolution — explicit opt-in only, no silent swap.
# ─────────────────────────────────────────────────────────────────────


class TestEndpointDispatchResolution:
    @pytest.mark.parametrize("preference", ["auto", "chat", None, "unknown-value"])
    def test_non_responses_preferences_preserve_default_chat_behavior(self, preference) -> None:
        model_config = (
            _model_config(endpoint_preference=preference) if preference is not None else None
        )
        assert _resolve_endpoint_choice(model_config) == "chat"

    def test_explicit_responses_preference_routes_to_responses(self) -> None:
        model_config = _model_config(endpoint_preference="responses")
        assert _resolve_endpoint_choice(model_config) == "responses"

    def test_none_model_config_preserves_default_chat_behavior(self) -> None:
        assert _resolve_endpoint_choice(None) == "chat"


# ─────────────────────────────────────────────────────────────────────
# 3. api_version override — only applied when explicitly configured; the
#    "v1" schema default never overrides the shared client.
# ─────────────────────────────────────────────────────────────────────


class TestApiVersionOverride:
    def test_default_sentinel_v1_means_no_override(self) -> None:
        model_config = _model_config(api_version="v1")
        assert _resolve_api_version_override(model_config) is None

    def test_unset_model_config_means_no_override(self) -> None:
        assert _resolve_api_version_override(None) is None

    def test_explicit_dated_api_version_is_returned_for_override(self) -> None:
        model_config = _model_config(api_version="2025-04-01-preview")
        assert _resolve_api_version_override(model_config) == "2025-04-01-preview"

    def test_api_version_override_reuses_with_options(self) -> None:
        """The live call path must reuse the shared client (no fresh
        credentials/client per request). `with_options`/`copy` on the
        installed AzureOpenAI SDK reuses the underlying transport unless an
        explicit http_client override is passed — assert that contract
        directly against the installed SDK so a future SDK upgrade that
        changes this would fail this test rather than silently regress.
        """
        from openai.lib.azure import AzureOpenAI

        client = AzureOpenAI(
            api_key="test-key",
            azure_endpoint="https://example.openai.azure.com",
            api_version="2025-01-01-preview",
        )
        overridden = client.with_options(api_version="2025-04-01-preview")
        assert overridden._api_version == "2025-04-01-preview"
        # Same underlying httpx transport instance -> no new client/creds.
        assert overridden._client is client._client


# ─────────────────────────────────────────────────────────────────────
# 4. Capability validation — genuinely unsupported controls are rejected
#    clearly, not silently dropped. include_reasoning means "surface an
#    available reasoning SUMMARY" (never raw chain-of-thought); it is only
#    honored on the Responses endpoint (reasoning.summary), so it is only
#    rejected when this turn resolves to chat.completions.
# ─────────────────────────────────────────────────────────────────────


class TestUnsupportedOptionRejection:
    def test_min_p_is_rejected_on_chat_endpoint(self) -> None:
        with pytest.raises(UnsupportedModelOptionError) as exc_info:
            _validate_model_config_capabilities(_model_config(min_p=0.1), "chat")
        assert exc_info.value.options == ["min_p"]

    def test_min_p_is_rejected_on_responses_endpoint_too(self) -> None:
        """min_p has no equivalent on either endpoint — always rejected."""
        with pytest.raises(UnsupportedModelOptionError) as exc_info:
            _validate_model_config_capabilities(_model_config(min_p=0.1), "responses")
        assert exc_info.value.options == ["min_p"]

    def test_typical_p_is_rejected(self) -> None:
        with pytest.raises(UnsupportedModelOptionError) as exc_info:
            _validate_model_config_capabilities(_model_config(typical_p=0.2), "chat")
        assert exc_info.value.options == ["typical_p"]

    def test_include_reasoning_is_rejected_on_chat_endpoint(self) -> None:
        """chat.completions.create has no reasoning-visibility concept at
        all in the installed SDK, so this is rejected there.
        """
        with pytest.raises(UnsupportedModelOptionError) as exc_info:
            _validate_model_config_capabilities(_model_config(include_reasoning=True), "chat")
        assert exc_info.value.options == ["include_reasoning"]

    def test_include_reasoning_is_allowed_on_responses_endpoint(self) -> None:
        """The Responses endpoint supports an available reasoning summary
        via reasoning.summary — must not raise.
        """
        _validate_model_config_capabilities(
            _model_config(include_reasoning=True), "responses"
        )  # must not raise

    def test_all_applicable_reported_together_on_chat(self) -> None:
        with pytest.raises(UnsupportedModelOptionError) as exc_info:
            _validate_model_config_capabilities(
                _model_config(min_p=0.1, typical_p=0.2, include_reasoning=True), "chat"
            )
        assert exc_info.value.options == ["min_p", "typical_p", "include_reasoning"]

    def test_min_p_and_typical_p_still_reported_on_responses_even_with_include_reasoning(
        self,
    ) -> None:
        with pytest.raises(UnsupportedModelOptionError) as exc_info:
            _validate_model_config_capabilities(
                _model_config(min_p=0.1, typical_p=0.2, include_reasoning=True), "responses"
            )
        assert exc_info.value.options == ["min_p", "typical_p"]

    def test_supported_config_passes_validation(self) -> None:
        _validate_model_config_capabilities(
            _model_config(reasoning_effort="high", verbosity=1, store=True), "chat"
        )  # must not raise

    def test_none_model_config_passes_validation(self) -> None:
        _validate_model_config_capabilities(None, "chat")  # must not raise

    def test_extract_error_details_names_exact_unsupported_controls(self) -> None:
        """Parent/Advanced Builder needs the exact control names to
        disable/label — assert the structured error carries them.
        """
        adapter = CascadeOrchestratorAdapter.__new__(CascadeOrchestratorAdapter)
        error = UnsupportedModelOptionError(["min_p", "typical_p", "include_reasoning"])

        details = json.loads(adapter._extract_error_details(error))

        assert details["code"] == "UnsupportedModelOption"
        assert details["unsupported_options"] == ["min_p", "typical_p", "include_reasoning"]
        assert "min_p" in details["message"]


# ─────────────────────────────────────────────────────────────────────
# 5. Responses API param builder — real request shape, not the flattened
#    src.aoai.manager._prepare_responses_params approach.
# ─────────────────────────────────────────────────────────────────────


class TestResponsesStreamingParamsBinding:
    def test_system_content_becomes_instructions_not_a_flattened_blob(self) -> None:
        model_config = _model_config(endpoint_preference="responses")
        messages = [
            {"role": "system", "content": "You are a helpful banking assistant."},
            {"role": "user", "content": "What's my balance?"},
        ]

        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, model_config, "gpt-5", messages, None
        )

        assert params["instructions"] == "You are a helpful banking assistant."
        assert params["input"] == [{"role": "user", "content": "What's my balance?"}]
        assert params["model"] == "gpt-5"
        assert params["stream"] is True

    def test_assistant_tool_calls_and_tool_results_round_trip(self) -> None:
        """Multi-turn tool calling threads correctly: the assistant's
        function_call and the tool's function_call_output share call_id.
        """
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "weather in Boston?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "Boston"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc",
                "name": "get_weather",
                "content": '{"temp_f": 62}',
            },
        ]

        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, _model_config(), "gpt-4o", messages, CHAT_TOOLS
        )

        function_call = next(i for i in params["input"] if i.get("type") == "function_call")
        function_call_output = next(
            i for i in params["input"] if i.get("type") == "function_call_output"
        )

        assert function_call["call_id"] == "call_abc"
        assert function_call["name"] == "get_weather"
        assert function_call["arguments"] == '{"city": "Boston"}'
        assert function_call_output["call_id"] == "call_abc"
        assert function_call_output["output"] == '{"temp_f": 62}'

        # Tools flattened to the Responses shape (no nested "function" key).
        assert params["tools"] == [
            {
                "type": "function",
                "name": "get_weather",
                "description": "Look up the weather for a city.",
                "parameters": CHAT_TOOLS[0]["function"]["parameters"],
            }
        ]

    def test_reasoning_effort_and_verbosity_use_responses_shapes(self) -> None:
        model_config = _model_config(
            deployment_id="gpt-5",
            model_family="gpt-5",
            reasoning_effort="medium",
            verbosity=1,
            response_format={"type": "json_object"},
            store=True,
            metadata={"trace": "xyz"},
        )
        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, model_config, "gpt-5", [{"role": "user", "content": "hi"}], None
        )

        assert params["reasoning"] == {"effort": "medium"}
        assert params["text"]["verbosity"] == "medium"  # mapped from int 1
        assert params["text"]["format"] == {"type": "json_object"}
        assert params["store"] is True
        assert params["metadata"] == {"trace": "xyz"}
        assert "max_output_tokens" in params
        # Responses uses max_output_tokens, never max_tokens/max_completion_tokens.
        assert "max_tokens" not in params
        assert "max_completion_tokens" not in params

    def test_include_reasoning_requests_a_summary_not_hidden_chain_of_thought(self) -> None:
        """include_reasoning=True must map to reasoning.summary (an
        available summary the API is documented to expose), never a made-up
        parameter that would leak raw chain-of-thought — no such parameter
        exists on the installed SDK's Responses.create signature.
        """
        model_config = _model_config(
            deployment_id="gpt-5", model_family="gpt-5", include_reasoning=True
        )
        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, model_config, "gpt-5", [{"role": "user", "content": "hi"}], None
        )
        assert params["reasoning"] == {"summary": "auto"}

    def test_include_reasoning_and_reasoning_effort_combine(self) -> None:
        model_config = _model_config(
            deployment_id="gpt-5",
            model_family="gpt-5",
            reasoning_effort="high",
            include_reasoning=True,
        )
        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, model_config, "gpt-5", [{"role": "user", "content": "hi"}], None
        )
        assert params["reasoning"] == {"effort": "high", "summary": "auto"}

    def test_include_reasoning_false_omits_summary(self) -> None:
        model_config = _model_config(
            deployment_id="gpt-5", model_family="gpt-5", reasoning_effort="high"
        )
        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, model_config, "gpt-5", [{"role": "user", "content": "hi"}], None
        )
        assert params["reasoning"] == {"effort": "high"}
        assert "summary" not in params["reasoning"]


# ─────────────────────────────────────────────────────────────────────
# 6. Message/tool conversion helpers, tested standalone.
# ─────────────────────────────────────────────────────────────────────


class TestMessageAndToolConversion:
    def test_multiple_system_messages_are_joined(self) -> None:
        messages = [
            {"role": "system", "content": "Part one."},
            {"role": "developer", "content": "Part two."},
            {"role": "user", "content": "hi"},
        ]
        instructions, input_items = _convert_messages_to_responses_input(messages)
        assert instructions == "Part one.\n\nPart two."
        assert input_items == [{"role": "user", "content": "hi"}]

    def test_no_system_message_yields_none_instructions(self) -> None:
        instructions, _ = _convert_messages_to_responses_input([{"role": "user", "content": "hi"}])
        assert instructions is None

    def test_assistant_text_alongside_tool_call_preserves_both(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": "Let me check that for you.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    }
                ],
            }
        ]
        _, input_items = _convert_messages_to_responses_input(messages)
        assert {"role": "assistant", "content": "Let me check that for you."} in input_items
        assert any(
            i.get("type") == "function_call" and i["call_id"] == "call_1" for i in input_items
        )

    def test_non_function_tools_pass_through_unmodified(self) -> None:
        tools = [{"type": "web_search"}]
        assert _convert_tools_to_responses_format(tools) == tools


# ─────────────────────────────────────────────────────────────────────
# 7. verbosity level mapping.
# ─────────────────────────────────────────────────────────────────────


class TestVerbosityMapping:
    @pytest.mark.parametrize("level,expected", [(0, "low"), (1, "medium"), (2, "high")])
    def test_int_levels_map_to_sdk_literals(self, level, expected) -> None:
        assert _map_verbosity_level(level) == expected

    def test_valid_string_passthrough(self) -> None:
        assert _map_verbosity_level("high") == "high"

    def test_invalid_string_is_rejected(self) -> None:
        with pytest.raises(UnsupportedModelOptionError):
            _map_verbosity_level("extremely-verbose")


# ─────────────────────────────────────────────────────────────────────
# 8. Responses stream normalization — real SDK event objects, verifying
#    structured tool-call roundtrip, text chunks, and usage metrics survive
#    into the same chunk shape the chat.completions consumption loop uses.
# ─────────────────────────────────────────────────────────────────────


def _accumulate_like_the_orchestrator(chunks):
    """Mirror the exact accumulation algorithm
    ``CascadeOrchestratorAdapter._process_llm._streaming_completion`` uses
    to consume ``chunk.choices[0].delta`` (content + tool_calls), so this
    test proves the normalizer's output is consumable identically to a real
    chat.completions stream, without re-implementing/duplicating the
    production tool loop itself.
    """
    collected_text: list[str] = []
    tool_buffers: dict[str, dict] = {}
    usage: dict[str, int] = {}

    for chunk in chunks:
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage:
            usage["input_tokens"] = getattr(chunk_usage, "prompt_tokens", 0)
            usage["output_tokens"] = getattr(chunk_usage, "completion_tokens", 0)

        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        if not delta:
            continue

        if getattr(delta, "tool_calls", None):
            for tc in delta.tool_calls:
                tc_idx = getattr(tc, "index", None)
                if tc_idx is None:
                    tc_idx = len(tool_buffers)
                tc_key = f"tool_{tc_idx}"
                if tc_key not in tool_buffers:
                    tool_buffers[tc_key] = {
                        "id": getattr(tc, "id", None) or tc_key,
                        "name": "",
                        "arguments": "",
                    }
                buf = tool_buffers[tc_key]
                tc_id = getattr(tc, "id", None)
                if tc_id:
                    buf["id"] = tc_id
                fn = getattr(tc, "function", None)
                if fn:
                    fn_name = getattr(fn, "name", None)
                    if fn_name:
                        buf["name"] = fn_name
                    fn_args = getattr(fn, "arguments", None)
                    if fn_args:
                        buf["arguments"] += fn_args

        if getattr(delta, "content", None):
            collected_text.append(delta.content)

    return "".join(collected_text), tool_buffers, usage


class TestResponsesStreamNormalization:
    def test_text_delta_events_accumulate_into_content(self) -> None:
        events = [
            ResponseTextDeltaEvent(
                content_index=0,
                delta="Hello, ",
                item_id="msg_1",
                logprobs=[],
                output_index=0,
                sequence_number=1,
                type="response.output_text.delta",
            ),
            ResponseTextDeltaEvent(
                content_index=0,
                delta="world!",
                item_id="msg_1",
                logprobs=[],
                output_index=0,
                sequence_number=2,
                type="response.output_text.delta",
            ),
        ]
        text, tool_buffers, usage = _accumulate_like_the_orchestrator(
            _normalize_responses_stream(events)
        )
        assert text == "Hello, world!"
        assert tool_buffers == {}
        assert usage == {}

    def test_function_call_arguments_and_usage_round_trip(self) -> None:
        tool_item = ResponseFunctionToolCall(
            arguments="",
            call_id="call_xyz",
            name="get_weather",
            type="function_call",
            id="fc_1",
        )
        usage_obj = ResponseUsage(
            input_tokens=42,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens=17,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
            total_tokens=59,
        )
        completed_response = Response(
            id="resp_1",
            created_at=0.0,
            model="gpt-5",
            object="response",
            output=[],
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
            usage=usage_obj,
        )

        events = [
            ResponseOutputItemAddedEvent(
                item=tool_item, output_index=0, sequence_number=1, type="response.output_item.added"
            ),
            ResponseFunctionCallArgumentsDeltaEvent(
                delta='{"city": ',
                item_id="fc_1",
                output_index=0,
                sequence_number=2,
                type="response.function_call_arguments.delta",
            ),
            ResponseFunctionCallArgumentsDeltaEvent(
                delta='"Boston"}',
                item_id="fc_1",
                output_index=0,
                sequence_number=3,
                type="response.function_call_arguments.delta",
            ),
            ResponseCompletedEvent(
                response=completed_response, sequence_number=4, type="response.completed"
            ),
        ]

        text, tool_buffers, usage = _accumulate_like_the_orchestrator(
            _normalize_responses_stream(events)
        )

        assert text == ""
        assert len(tool_buffers) == 1
        buf = next(iter(tool_buffers.values()))
        assert buf["id"] == "call_xyz"  # call_id, not the internal item id
        assert buf["name"] == "get_weather"
        assert buf["arguments"] == '{"city": "Boston"}'
        assert usage == {"input_tokens": 42, "output_tokens": 17}

    def test_handoff_tool_name_is_visible_on_first_delta_for_suppression(self) -> None:
        """The orchestrator detects handoff tools by inspecting
        delta.tool_calls[].function.name as soon as it streams in — assert
        the normalizer exposes the name on the *added* event, matching how
        chat.completions delivers the function name in its first tool_call
        delta.
        """
        tool_item = ResponseFunctionToolCall(
            arguments="",
            call_id="call_1",
            name="transfer_to_specialist",
            type="function_call",
            id="fc_2",
        )
        event = ResponseOutputItemAddedEvent(
            item=tool_item, output_index=0, sequence_number=1, type="response.output_item.added"
        )
        normalized = list(_normalize_responses_stream([event]))
        assert len(normalized) == 1
        tc = normalized[0].choices[0].delta.tool_calls[0]
        assert tc.function.name == "transfer_to_specialist"

    def test_lifecycle_events_with_no_delta_are_skipped(self) -> None:
        from openai.types.responses import ResponseCreatedEvent

        created_response = Response(
            id="resp_1",
            created_at=0.0,
            model="gpt-5",
            object="response",
            output=[],
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
        )
        event = ResponseCreatedEvent(
            response=created_response, sequence_number=0, type="response.created"
        )
        assert list(_normalize_responses_stream([event])) == []


# ─────────────────────────────────────────────────────────────────────
# 9. End-to-end-ish: explicit "responses" preference actually builds a
#    Responses-shaped request and consumes a Responses-shaped stream,
#    proving the endpoint is never silently substituted.
# ─────────────────────────────────────────────────────────────────────


class TestExplicitResponsesEndpointEndToEnd:
    def test_explicit_preference_builds_responses_params_and_normalizes_its_stream(self) -> None:
        model_config = _model_config(endpoint_preference="responses", reasoning_effort="low")
        assert _resolve_endpoint_choice(model_config) == "responses"

        messages = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "2+2?"},
        ]
        params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
            None, model_config, "gpt-5", messages, None
        )
        assert params["instructions"] == "Be concise."
        assert params["reasoning"] == {"effort": "low"}

        fake_stream = [
            ResponseTextDeltaEvent(
                content_index=0,
                delta="4",
                item_id="msg_1",
                logprobs=[],
                output_index=0,
                sequence_number=1,
                type="response.output_text.delta",
            )
        ]
        text, _, _ = _accumulate_like_the_orchestrator(_normalize_responses_stream(fake_stream))
        assert text == "4"


def test_responses_error_event_is_not_silently_discarded():
    from types import SimpleNamespace

    with pytest.raises(RuntimeError, match="Service unavailable"):
        list(
            _normalize_responses_stream(
                [SimpleNamespace(type="error", message="Service unavailable")]
            )
        )


def test_responses_preserves_strict_function_schema():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                "strict": True,
            },
        }
    ]
    assert _convert_tools_to_responses_format(tools)[0]["strict"] is True


def test_responses_converts_chat_json_schema_format():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    config = _model_config(
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": schema},
        }
    )
    params = CascadeOrchestratorAdapter._prepare_responses_streaming_params(
        None, config, config.deployment_id, [{"role": "user", "content": "Hello"}], None
    )
    assert params["text"]["format"] == {
        "type": "json_schema",
        "name": "answer",
        "strict": True,
        "schema": schema,
    }
