"""
Cascade Orchestrator Adapter
==============================

Native async turn execution over UnifiedAgent definitions. VoiceHandler's
serialized turn worker enters through unified.route_turn and process_turn.
Model/TTS sequencing stays here; scenario routing, tool effects and definition
conversion delegate to their shared contracts. Standalone callers may construct
an adapter with create() and pass an OrchestratorContext to process_turn().
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.src.orchestration.naming import find_agent_by_name
from apps.artagent.backend.src.orchestration.prompt_context import cascade_runtime_prompt_context
from apps.artagent.backend.voice.shared.base import (
    OrchestratorContext,
    OrchestratorResult,
)
from apps.artagent.backend.voice.shared.config_resolver import (
    DEFAULT_START_AGENT,
    OrchestratorConfigResult,
    resolve_orchestrator_config,
)
from apps.artagent.backend.voice.shared.errors import (
    VoiceErrorInfo,
    classify_voice_error,
    emit_voice_error,
)
from apps.artagent.backend.voice.shared.handoff_service import HandoffService
from apps.artagent.backend.voice.shared.metrics import OrchestratorMetrics
from apps.artagent.backend.voice.shared.session_state import (
    SessionStateKeys,
    sync_state_from_memo,
    sync_state_to_memo,
)
from apps.artagent.backend.voice.shared.tool_policy import (
    apply_tool_result,
    normalize_tool_result,
    tool_arguments,
)
from apps.artagent.backend.voice.speech_cascade.tts_processor import TTSTextProcessor
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from src.enums.monitoring import GenAIOperation, SpanAttr
from utils.eval_span import annotate_eval_content


@dataclass
class HandoffResult:
    """Result from executing a handoff."""

    success: bool
    target_agent: str = ""
    handoff_type: str = "announced"  # "discrete" or "announced"
    greeting: str | None = None
    error: str | None = None
    system_vars: dict[str, Any] = field(default_factory=dict)


if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig
    from src.stateful.state_managment import MemoManager

try:
    from utils.ml_logging import get_logger

    logger = get_logger("cascade.adapter")
except ImportError:
    import logging

    logger = logging.getLogger("cascade.adapter")

tracer = trace.get_tracer(__name__)


# ─────────────────────────────────────────────────────────────────────
# State Keys (use shared SessionStateKeys for consistency)
# ─────────────────────────────────────────────────────────────────────

# Re-export for backward compatibility
StateKeys = SessionStateKeys


# ─────────────────────────────────────────────────────────────────────
# Session Context (for cross-thread preservation)
# ─────────────────────────────────────────────────────────────────────

# Context variable to preserve session state across thread boundaries
_cascade_session_ctx: contextvars.ContextVar[CascadeSessionScope | None] = contextvars.ContextVar(
    "cascade_session", default=None
)


@dataclass
class CascadeSessionScope:
    """
    Session scope for preserving context across thread boundaries.

    This dataclass holds session-specific state that must be preserved
    when crossing async/thread boundaries (e.g., during LLM streaming).
    """

    session_id: str
    call_connection_id: str
    memo_manager: MemoManager | None = None
    active_agent: str = ""
    turn_id: str = ""
    _turn_sequence: int = field(default=0, repr=False)  # Track tool call boundaries
    _base_turn_id: str = field(default="", repr=False)  # Original turn_id before tools

    @classmethod
    def get_current(cls) -> CascadeSessionScope | None:
        """Get the current session scope from context variable."""
        return _cascade_session_ctx.get()

    def advance_turn_for_tool(self) -> str:
        """
        Advance the turn_id after a tool call to create a new message segment.

        Returns:
            The new turn_id to use for post-tool responses.
        """
        if not self._base_turn_id:
            self._base_turn_id = self.turn_id or ""
        self._turn_sequence += 1
        self.turn_id = f"{self._base_turn_id}_s{self._turn_sequence}"
        logger.debug(
            "[TurnAdvance] Cascade turn_id advanced: base=%s, seq=%d, new=%s",
            self._base_turn_id,
            self._turn_sequence,
            self.turn_id,
        )
        return self.turn_id

    def get_effective_turn_id(self) -> str:
        """Get the current response segment ID (which may have been advanced)."""
        return self.turn_id

    def get_root_turn_id(self) -> str:
        """Get the canonical user-turn ID shared by transcripts, tools, and responses."""
        return self._base_turn_id or self.turn_id

    @classmethod
    @contextmanager
    def activate(
        cls,
        session_id: str,
        call_connection_id: str,
        memo_manager: MemoManager | None = None,
        active_agent: str = "",
        turn_id: str = "",
    ):
        """
        Context manager that activates a session scope.

        Usage:
            with CascadeSessionScope.activate(session_id, call_id, cm):
                # Session context is preserved here
                await process_llm(...)
        """
        scope = cls(
            session_id=session_id,
            call_connection_id=call_connection_id,
            memo_manager=memo_manager,
            active_agent=active_agent,
            turn_id=turn_id,
        )
        token = _cascade_session_ctx.set(scope)
        try:
            yield scope
        finally:
            _cascade_session_ctx.reset(token)


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

# Get deployment name from environment, with fallback
DEFAULT_MODEL_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")


@dataclass
class CascadeConfig:
    """
    Configuration for CascadeOrchestratorAdapter.

    Attributes:
        start_agent: Name of the initial agent
        model_name: LLM deployment name (from AZURE_OPENAI_DEPLOYMENT)
        call_connection_id: ACS call connection for tracing
        session_id: Session identifier for tracing
        enable_rag: Whether to enable RAG search for responses
        streaming: Whether to stream responses (default False for sentence-level TTS)
    """

    start_agent: str = DEFAULT_START_AGENT
    model_name: str = field(default_factory=lambda: DEFAULT_MODEL_NAME)
    call_connection_id: str | None = None
    session_id: str | None = None
    enable_rag: bool = True
    streaming: bool = False  # Non-streaming matches legacy gpt_flow behavior


# ─────────────────────────────────────────────────────────────────────
# Model Request Preparation Helpers
#
# Pure, module-level functions (no adapter classes) so Cascade model
# binding can be unit tested without constructing a full orchestrator, and
# so `_streaming_completion` can dispatch to either OpenAI endpoint without
# duplicating its chunk-consumption loop. All parameter names below were
# confirmed against the installed openai SDK's actual call signatures
# (`Completions.create` / `Responses.create`), not assumed from docs.
# ─────────────────────────────────────────────────────────────────────


class UnsupportedModelOptionError(ValueError):
    """A stored ``ModelConfig`` option has no supported parameter on the
    installed OpenAI SDK's chat.completions or responses endpoints.

    Cascade must reject these clearly instead of silently dropping them so
    the Advanced Builder UI can disable/label the offending controls.
    """

    def __init__(self, options: list[str]):
        self.options = list(options)
        super().__init__(
            "Unsupported model configuration option(s) for the installed "
            f"OpenAI SDK: {', '.join(self.options)}"
        )


def _validate_model_config_capabilities(model_config: Any, endpoint_choice: str) -> None:
    """Reject ``ModelConfig`` options with no supported equivalent for the
    endpoint this request is about to use, instead of silently dropping
    them from the request.

    ``min_p`` and ``typical_p`` are not accepted keyword arguments of either
    ``chat.completions.create`` or ``responses.create`` in the installed
    openai package (verified via ``inspect.signature`` against both
    methods — neither exposes these names) — unsupported on both endpoints.

    ``include_reasoning`` means "surface an available reasoning SUMMARY",
    never raw hidden chain-of-thought. The Responses endpoint supports this
    via ``reasoning.summary`` (``response_create_params`` / the installed
    SDK's ``Reasoning`` TypedDict), so it is honored — see
    ``_prepare_responses_streaming_params`` — only when this request is
    actually going to ``responses.create``. ``chat.completions.create`` has
    no summary (or any reasoning-visibility) concept at all in the
    installed SDK, so ``include_reasoning`` is rejected when the resolved
    endpoint is "chat".
    """
    if model_config is None:
        return

    unsupported: list[str] = []
    if getattr(model_config, "min_p", None) is not None:
        unsupported.append("min_p")
    if getattr(model_config, "typical_p", None) is not None:
        unsupported.append("typical_p")
    if getattr(model_config, "include_reasoning", False) and endpoint_choice != "responses":
        unsupported.append("include_reasoning")

    if unsupported:
        raise UnsupportedModelOptionError(unsupported)


# ModelConfig.verbosity is stored as an int (0=minimal, 1=standard,
# 2=detailed) but both endpoints only accept the string literals below.
_VERBOSITY_LEVEL_NAMES: dict[int, str] = {0: "low", 1: "medium", 2: "high"}


def _map_verbosity_level(verbosity: int | str) -> str:
    """Map ModelConfig's numeric verbosity to the "low"/"medium"/"high"
    string literal required by chat.completions.create and responses.create.
    """
    if isinstance(verbosity, str):
        normalized = verbosity.strip().lower()
        if normalized in ("low", "medium", "high"):
            return normalized
        raise UnsupportedModelOptionError([f"verbosity={verbosity!r}"])
    return _VERBOSITY_LEVEL_NAMES.get(int(verbosity), "medium")


def _resolve_endpoint_choice(model_config: Any) -> str:
    """Resolve which OpenAI endpoint services a Cascade streaming request.

    Only an explicit ``endpoint_preference == "responses"`` routes off
    chat.completions. Every other value — ``"auto"``, ``"chat"``, ``None``,
    or an unset attribute — preserves the existing default streaming
    behavior. Once "responses" is chosen it is the only endpoint attempted
    for that turn; there is no silent fallback to the other endpoint.
    """
    preference = getattr(model_config, "endpoint_preference", "auto") if model_config else "auto"
    return "responses" if preference == "responses" else "chat"


# ModelConfig.api_version defaults to "v1", which is not a valid Azure
# `api-version` value (Azure expects dated strings like
# "2025-01-01-preview"). Treat that default as "no override requested" so
# an agent that never touched this Advanced Builder field keeps using the
# shared client's configured api_version unchanged.
_API_VERSION_SENTINEL_DEFAULT = "v1"


def _resolve_api_version_override(model_config: Any) -> str | None:
    """Return an explicit Azure ``api-version`` override, or ``None``.

    ``None`` means "reuse the shared client's configured api_version
    unchanged". The caller applies a non-``None`` override via
    ``client.with_options(api_version=...)``, which reuses the existing
    transport/credentials instead of constructing a fresh client.
    """
    if model_config is None:
        return None
    api_version = getattr(model_config, "api_version", None)
    if not api_version or api_version == _API_VERSION_SENTINEL_DEFAULT:
        return None
    return api_version


def _convert_messages_to_responses_input(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert chat.completions-style messages into Responses API
    ``instructions`` + ``input`` items.

    Preserves:
      - system/developer content as ``instructions`` (Responses has no
        "system" role in ``input``; the dedicated ``instructions`` field is
        the documented equivalent).
      - assistant tool calls as ``function_call`` input items keyed by
        ``call_id`` (from the chat-format ``tool_calls[].id``).
      - tool results as ``function_call_output`` items, threaded back to
        their originating call via that same ``call_id``.
      - plain user/assistant text turns as simple role/content items.
    """
    instructions_parts: list[str] = []
    input_items: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role in ("system", "developer"):
            if content:
                instructions_parts.append(
                    content if isinstance(content, str) else json.dumps(content)
                )
            continue

        if role == "assistant":
            if content:
                input_items.append({"role": "assistant", "content": content})
            for tool_call in msg.get("tool_calls") or []:
                function = tool_call.get("function", {}) or {}
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments", "{}"),
                    }
                )
            continue

        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id"),
                    "output": content if isinstance(content, str) else json.dumps(content),
                }
            )
            continue

        # user (and any other conversational role) maps directly.
        if content is not None:
            input_items.append({"role": role or "user", "content": content})

    instructions = "\n\n".join(instructions_parts) if instructions_parts else None
    return instructions, input_items


def _convert_tools_to_responses_format(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten chat.completions-style tool definitions
    (``{"type": "function", "function": {...}}``) into the Responses API's
    flat tool shape (``{"type": "function", "name": ..., "parameters": ...}``),
    confirmed against the installed SDK's ``FunctionToolParam`` TypedDict.
    """
    responses_tools: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            # Only the function shape differs between the two endpoints;
            # pass any other tool type through unmodified.
            responses_tools.append(tool)
            continue
        function = tool.get("function", {}) or {}
        definition = {
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description"),
            "parameters": function.get("parameters"),
        }
        if "strict" in function:
            definition["strict"] = function["strict"]
        responses_tools.append(definition)
    return responses_tools


def _normalize_responses_stream_event(event: Any, state: dict[str, Any]) -> Any | None:
    """Convert a single Responses API streaming event into a
    ChatCompletionChunk-shaped ``SimpleNamespace`` so the existing Cascade
    streaming consumption loop (written for chat.completions chunks) can
    process both endpoints identically without any change to that loop.

    ``state`` tracks ``item_id -> tool_call index`` across the stream since
    Responses events key function-call deltas by ``item_id``, not the
    stable numeric ``index`` chat.completions chunks provide.

    Returns ``None`` for event types that carry no text/tool/usage delta
    (e.g. lifecycle events like ``response.created``); the caller skips
    those exactly like a chat.completions chunk with no choices/usage.
    """
    event_type = getattr(event, "type", None)

    if event_type == "response.output_text.delta":
        delta = SimpleNamespace(content=event.delta, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    if event_type == "response.output_item.added":
        item = event.item
        if getattr(item, "type", None) != "function_call":
            return None
        item_id = getattr(item, "id", None)
        index = state["next_index"]
        state["next_index"] += 1
        if item_id is not None:
            state["item_index"][item_id] = index
        function = SimpleNamespace(name=getattr(item, "name", None), arguments=None)
        tool_call = SimpleNamespace(
            index=index, id=getattr(item, "call_id", None), function=function
        )
        delta = SimpleNamespace(content=None, tool_calls=[tool_call])
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    if event_type == "response.function_call_arguments.delta":
        index = state["item_index"].get(event.item_id)
        if index is None:
            index = state["next_index"]
            state["next_index"] += 1
            state["item_index"][event.item_id] = index
        function = SimpleNamespace(name=None, arguments=event.delta)
        tool_call = SimpleNamespace(index=index, id=None, function=function)
        delta = SimpleNamespace(content=None, tool_calls=[tool_call])
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    if event_type == "response.completed":
        usage = getattr(event.response, "usage", None)
        usage_ns = None
        if usage is not None:
            usage_ns = SimpleNamespace(
                prompt_tokens=getattr(usage, "input_tokens", 0),
                completion_tokens=getattr(usage, "output_tokens", 0),
            )
        return SimpleNamespace(choices=[], usage=usage_ns)

    if event_type in ("error", "response.failed", "response.error", "response.incomplete"):
        response_obj = getattr(event, "response", None)
        error = (
            getattr(response_obj, "error", None)
            if response_obj is not None
            else getattr(event, "message", None)
        )
        raise RuntimeError(f"Responses API stream event={event_type} error={error}")

    return None


def _normalize_responses_stream(raw_stream: Any):
    """Normalize a recorded sequence of Responses events without performing I/O.

    The live runtime normalizes individual events on its owned async stream so
    cancellation and close always target the original SDK stream.
    """
    state: dict[str, Any] = {"next_index": 0, "item_index": {}}
    for event in raw_stream:
        normalized = _normalize_responses_stream_event(event, state)
        if normalized is not None:
            yield normalized


# ─────────────────────────────────────────────────────────────────────
# Main Adapter
# ─────────────────────────────────────────────────────────────────────


@dataclass
class CascadeOrchestratorAdapter:
    """
    Adapter for SpeechCascade multi-agent orchestration using unified agents.

    This adapter integrates neutral agent definitions with VoiceHandler, providing:

    - State-based handoffs via MemoManager
    - Tool execution via shared registry
    - Prompt rendering with runtime context
    - OpenTelemetry instrumentation

    Design:
    - Serialized async turns with owned model/TTS producers
    - Scenario-authoritative handoffs
    - Shared tool effects with native streaming and continuation

    Attributes:
        config: Orchestrator configuration
        agents: Registry of UnifiedAgent instances
        handoff_map: Tool name → agent name mapping
    """

    config: CascadeConfig = field(default_factory=CascadeConfig)
    agents: dict[str, UnifiedAgent] = field(default_factory=dict)
    handoff_map: dict[str, str] = field(default_factory=dict)
    async_client: Any | None = field(default=None, repr=False)

    # Runtime state
    _active_agent: str = field(default="", init=False)
    _visited_agents: set = field(default_factory=set, init=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _last_user_message: str | None = field(default=None, init=False)
    _turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _turn_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    # Scenario switch flag — prevents sync_from_memo_manager from overwriting
    # _active_agent with stale MemoManager data after an explicit scenario switch
    _scenario_switch_pending: bool = field(default=False, init=False)

    # Session context - preserves MemoManager reference for turn duration
    _current_memo_manager: MemoManager | None = field(default=None, init=False)
    _session_vars: dict[str, Any] = field(default_factory=dict, init=False)

    # Unified metrics tracking (replaces individual token/timing fields)
    _metrics: OrchestratorMetrics = field(default=None, init=False)  # type: ignore

    # Native runtime and evaluation agent-switch notification.
    _on_agent_switch: Callable[[str, str], Awaitable[None]] | None = field(default=None, init=False)

    def __post_init__(self):
        """Initialize agent registry if not provided."""
        # Initialize metrics tracker
        self._metrics = OrchestratorMetrics(
            agent_name=self.config.start_agent or "",
            call_connection_id=self.config.call_connection_id,
            session_id=self.config.session_id,
        )
        # Per-turn LLM time-to-first-token (ms), populated during streaming.
        self._last_turn_ttft_ms: float | None = None
        # Deployment/model name resolved for the most recent turn (via
        # get_model_for_mode("cascade")). Surfaced on turn KPIs so the model that
        # actually processed the turn can be validated against the selected model.
        self._last_model_name: str | None = None
        # Classified failure captured during the most recent turn. The LLM path
        # keeps speaking a short apology so the caller isn't met with silence,
        # but the structured cause is surfaced to the operator UI from here.
        self._last_error_info: VoiceErrorInfo | None = None
        # perf_counter at turn entry (== finalized user input / recognition
        # complete) and the recognition->first-token latency derived from it.
        # ttft_ms is anchored at the LLM request; this is anchored at end of
        # user speech, so it includes context-build/orchestration overhead.
        self._turn_perf_start: float | None = None
        self._last_turn_recog_to_llm_ms: float | None = None
        # Optional external anchor (perf_counter) marking the end of user speech.
        # When set before process_turn, it overrides the process_turn-entry
        # anchor so recog_to_llm_first_ms measures from the true end of
        # recognition (i.e. includes queue + context-build overhead).
        self._recognition_anchor: float | None = None

        if not self.agents:
            self._load_agents()

        if not self.handoff_map:
            self._build_handoff_map()

        if not self._active_agent:
            self._active_agent = self.config.start_agent

        # Validate start agent exists (case-insensitive)
        if self._active_agent:
            actual_key, _ = find_agent_by_name(self.agents, self._active_agent)
            if actual_key is None:
                available = list(self.agents.keys())
                if available:
                    logger.warning(
                        "Start agent '%s' not found, using '%s'",
                        self._active_agent,
                        available[0],
                    )
                    self._active_agent = available[0]
            else:
                # Normalize to actual key
                self._active_agent = actual_key

    def _load_agents(self) -> None:
        """Load agents from the unified agent registry with scenario support."""
        # Use cached orchestrator config (this also populates the cache for future use)
        config = self._orchestrator_config
        self.agents = config.agents
        self.handoff_map = config.handoff_map

        # Update start agent if scenario specifies one
        if config.has_scenario and config.start_agent:
            self.config.start_agent = config.start_agent
            self._active_agent = config.start_agent

        logger.info(
            "Loaded %d agents for cascade adapter (session_id=%s)",
            len(self.agents),
            self.config.session_id or "(none)",
            extra={
                "scenario": config.scenario_name or "(none)",
                "start_agent": config.start_agent,
            },
        )

    def _build_handoff_map(self) -> None:
        """Build handoff map from agent declarations."""
        # Already built by _load_agents via resolver
        if self.handoff_map:
            return

        try:
            from apps.artagent.backend.registries.agentstore.loader import build_handoff_map

            self.handoff_map = build_handoff_map(self.agents)
            logger.debug("Built handoff map: %s", self.handoff_map)
        except ImportError as e:
            logger.error("Failed to import build_handoff_map: %s", e)
            self.handoff_map = {}

    @classmethod
    def create(
        cls,
        *,
        start_agent: str = "Concierge",
        model_name: str | None = None,
        call_connection_id: str | None = None,
        session_id: str | None = None,
        agents: dict[str, UnifiedAgent] | None = None,
        handoff_map: dict[str, str] | None = None,
        enable_rag: bool = True,
        streaming: bool = False,  # Non-streaming for sentence-level TTS
    ) -> CascadeOrchestratorAdapter:
        """
        Factory method to create a fully configured adapter.

        Args:
            start_agent: Initial agent name
            model_name: LLM deployment name (defaults to AZURE_OPENAI_DEPLOYMENT)
            call_connection_id: ACS call ID for tracing
            session_id: Session ID for tracing
            agents: Optional pre-loaded agent registry
            handoff_map: Optional pre-built handoff map
            enable_rag: Whether to enable RAG search
            streaming: Whether to stream responses

        Returns:
            Configured CascadeOrchestratorAdapter instance
        """
        config = CascadeConfig(
            start_agent=start_agent,
            model_name=model_name or DEFAULT_MODEL_NAME,
            call_connection_id=call_connection_id,
            session_id=session_id,
            enable_rag=enable_rag,
            streaming=streaming,
        )

        adapter = cls(
            config=config,
            agents=agents or {},
            handoff_map=handoff_map or {},
        )

        return adapter

    # ─────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "cascade_orchestrator"

    @property
    def current_agent(self) -> str | None:
        """Get the currently active agent name."""
        return self._active_agent

    @property
    def last_model_name(self) -> str | None:
        """Deployment/model resolved for the most recent turn.

        Populated by ``_streaming_completion`` from the active agent's
        ``get_model_for_mode(\"cascade\")``; used by turn-KPI reporting to validate
        that the model actually processing the turn matches the selected model.
        """
        return self._last_model_name

    @property
    def current_agent_config(self) -> UnifiedAgent | None:
        """Get the currently active agent configuration."""
        return self.agents.get(self._active_agent)

    @property
    def available_agents(self) -> list[str]:
        """Get list of available agent names."""
        return list(self.agents.keys())

    @property
    def memo_manager(self) -> MemoManager | None:
        """
        Get the current MemoManager reference.

        This is available during turn processing and allows
        tools and callbacks to access session state.
        """
        # Try session scope first (for cross-thread access)
        scope = CascadeSessionScope.get_current()
        if scope and scope.memo_manager:
            return scope.memo_manager
        # Fall back to instance reference
        return self._current_memo_manager

    @property
    def _orchestrator_config(self):
        """
        Get cached orchestrator config for scenario resolution.

        Lazily resolves and caches the config on first access to avoid
        repeated calls to resolve_orchestrator_config() during the session.

        The config is cached per-instance (session lifetime), which is appropriate
        because scenario changes during a call would be disruptive anyway.
        """
        if not hasattr(self, "_cached_orchestrator_config"):
            # Get scenario_name from session memo_manager using centralized utility
            scenario_name = getattr(self, "_active_scenario_name", None)
            if not scenario_name and self._current_memo_manager:
                from apps.artagent.backend.src.orchestration.naming import (
                    get_scenario_from_corememory,
                )

                scenario_name = get_scenario_from_corememory(self._current_memo_manager)
            self._cached_orchestrator_config = resolve_orchestrator_config(
                session_id=self.config.session_id,
                scenario_name=scenario_name,
            )
            logger.debug(
                "Cached orchestrator config | scenario=%s session=%s",
                self._cached_orchestrator_config.scenario_name,
                self.config.session_id,
            )
        return self._cached_orchestrator_config

    @property
    def handoff_service(self) -> HandoffService:
        """
        Get the HandoffService for consistent handoff resolution.

        Lazily initialized on first access using current orchestrator state.
        Uses cached scenario config for handoff behavior (discrete/announced).

        For session-scoped scenarios (from Scenario Builder), passes the
        ScenarioConfig object directly so HandoffService can use it without
        trying to load from YAML files.
        """
        if not hasattr(self, "_handoff_service") or self._handoff_service is None:
            # Use cached orchestrator config for scenario resolution
            config = self._orchestrator_config
            self._handoff_service = HandoffService(
                scenario_name=config.scenario_name,
                handoff_map=self.handoff_map,
                agents=self.agents,
                memo_manager=self._current_memo_manager,
                scenario=config.scenario,  # Pass scenario object for session-scoped scenarios
            )
        return self._handoff_service

    def get_handoff_target(self, tool_name: str) -> str | None:
        """
        Get the target agent for a handoff tool.

        Uses HandoffService for consistent resolution.
        """
        return self.handoff_service.get_handoff_target(tool_name)

    # ─────────────────────────────────────────────────────────────────
    # MCP Server Integration
    # ─────────────────────────────────────────────────────────────────

    async def _init_mcp_for_agent(self, agent_name: str, memo_manager: MemoManager | None) -> None:
        """
        Initialize MCP server connections for an agent's configured servers.

        Connects to MCP servers listed in the agent's mcp_servers field.
        Tools from connected servers become available for the session.

        Args:
            agent_name: Name of the agent to initialize MCP for
            memo_manager: MemoManager instance for session state
        """
        if not memo_manager:
            return

        agent = self.agents.get(agent_name)
        if not agent or not agent.mcp_servers:
            return

        # Check if already initialized for this agent
        if hasattr(self, "_mcp_initialized_agents"):
            if agent_name in self._mcp_initialized_agents:
                return
        else:
            self._mcp_initialized_agents = set()

        try:
            from apps.artagent.backend.registries.toolstore.mcp import get_mcp_configs_for_agent

            configs = get_mcp_configs_for_agent(agent.mcp_servers)
            if not configs:
                logger.debug(
                    "[CascadeOrchestrator] No MCP servers configured for agent %s",
                    agent_name,
                )
                return

            results = await memo_manager.init_mcp_servers(configs)

            self._mcp_initialized_agents.add(agent_name)

            connected = [name for name, success in results.items() if success]
            failed = [name for name, success in results.items() if not success]

            if connected:
                logger.info(
                    "[CascadeOrchestrator] MCP servers connected for %s: %s",
                    agent_name,
                    connected,
                )
            if failed:
                logger.warning(
                    "[CascadeOrchestrator] MCP servers failed for %s: %s",
                    agent_name,
                    failed,
                )
        except Exception as exc:
            logger.warning(
                "[CascadeOrchestrator] MCP initialization failed for %s: %s",
                agent_name,
                exc,
            )

    def set_on_agent_switch(self, callback: Callable[[str, str], Awaitable[None]] | None) -> None:
        """
        Set callback for agent switch notifications.

        The callback receives (previous_agent, new_agent) when a handoff occurs.
        Use this to emit agent_change envelopes or update voice configuration.

        Args:
            callback: Async function(previous_agent, new_agent) -> None
        """
        self._on_agent_switch = callback

    def _get_tools_with_handoffs(self, agent: UnifiedAgent) -> list[dict[str, Any]]:
        from apps.artagent.backend.voice.shared.tool_policy import agent_tool_schemas

        return agent_tool_schemas(
            agent,
            scenario=self._orchestrator_config.scenario,
            agents=self.agents,
            is_handoff=self.handoff_service.is_handoff,
        )

    def update_scenario(
        self,
        agents: dict[str, UnifiedAgent],
        handoff_map: dict[str, str],
        start_agent: str | None = None,
        scenario_name: str | None = None,
        *,
        scenario: ScenarioConfig | None = None,
    ) -> None:
        """
        Update the adapter with a new scenario configuration.

        This is called when the user changes scenarios mid-session via the UI.
        All agent-related attributes are updated to reflect the new scenario.

        Args:
            agents: New agents registry
            handoff_map: New handoff routing map
            start_agent: Optional new start agent to switch to
            scenario_name: Optional scenario name for logging
            scenario: Optional authoritative in-memory scenario definition
        """
        old_agents = list(self.agents.keys())
        old_active = self._active_agent

        # Update agents registry
        self.agents = agents

        # Update handoff map
        self.handoff_map = handoff_map
        self._active_scenario_name = scenario_name

        # Clear cached HandoffService so it's recreated with new values
        if hasattr(self, "_handoff_service"):
            self._handoff_service = None
        if hasattr(self, "_cached_orchestrator_config"):
            delattr(self, "_cached_orchestrator_config")
        if scenario is not None:
            self._cached_orchestrator_config = OrchestratorConfigResult(
                start_agent=start_agent or scenario.start_agent,
                agents=agents,
                handoff_map=handoff_map,
                scenario=scenario,
                scenario_name=scenario.name,
                template_vars=dict(scenario.global_template_vars),
            )

        # Clear visited agents for fresh scenario experience
        self._visited_agents.clear()

        # Update config start_agent
        if start_agent:
            self.config.start_agent = start_agent

        # Switch to start_agent if provided (always switch for explicit scenario change)
        if start_agent:
            # Normalize to actual key
            actual_key, _ = find_agent_by_name(agents, start_agent)
            self._active_agent = actual_key or start_agent
            logger.info(
                "🔄 Cascade switching to scenario start_agent | from=%s to=%s scenario=%s",
                old_active,
                self._active_agent,
                scenario_name or "(unknown)",
            )
        else:
            # Check if current agent in new scenario (case-insensitive)
            actual_key, _ = find_agent_by_name(agents, self._active_agent)
            if actual_key is None:
                # Current agent not in new scenario - switch to first available
                available = list(agents.keys())
                if available:
                    self._active_agent = available[0]
                    logger.warning(
                        "🔄 Cascade current agent not in scenario, switching | from=%s to=%s",
                        old_active,
                        self._active_agent,
                    )
            else:
                # Normalize to actual key
                self._active_agent = actual_key

        logger.info(
            "🔄 Cascade scenario updated | old_agents=%s new_agents=%s active=%s scenario=%s",
            old_agents,
            list(agents.keys()),
            self._active_agent,
            scenario_name or "(unknown)",
        )

        # Mark scenario switch pending so sync_from_memo_manager doesn't
        # overwrite _active_agent with stale data from a previous MemoManager snapshot
        self._scenario_switch_pending = True

    # ─────────────────────────────────────────────────────────────────
    # History Management (Consolidated)
    # ─────────────────────────────────────────────────────────────────

    def _record_turn(
        self,
        agent: str,
        user_text: str | None,
        assistant_text: str | None,
    ) -> tuple[bool, bool]:
        """
        Record a conversation turn to history.

        This is the SINGLE place where conversation history is written.
        All in-memory, no I/O - safe for hot path.

        Args:
            agent: Agent name for the history thread
            user_text: User's message (or None to skip)
            assistant_text: Assistant's response (or None to skip)

        Returns:
            Tuple of (user_recorded, assistant_recorded)
        """
        cm = self._current_memo_manager
        if not cm:
            return (False, False)

        user_recorded = False
        assistant_recorded = False

        if user_text and user_text.strip():
            cm.append_to_history(agent, "user", user_text)
            user_recorded = True

        if assistant_text:
            cm.append_to_history(agent, "assistant", assistant_text)
            assistant_recorded = True

        return (user_recorded, assistant_recorded)

    def _get_conversation_history(self, cm: MemoManager) -> list[dict[str, str]]:
        """
        Build conversation history for the current agent.

        Includes context from other agents to preserve cross-agent continuity.
        Makes a COPY to avoid mutation issues.

        Args:
            cm: MemoManager instance

        Returns:
            List of message dicts for conversation history
        """
        # Get current agent's history (copy to avoid reference issues)
        agent_history = list(cm.get_history(self._active_agent) or [])

        # Collect substantive user messages from other agents
        all_histories = cm.history.get_all()
        seen_content: set[str] = set()
        cross_agent_context: list[dict[str, str]] = []

        for agent_name, msgs in all_histories.items():
            if agent_name == self._active_agent:
                continue
            for msg in msgs:
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "").strip()
                # Skip short or greeting-like messages
                if len(content) <= 10 or content.lower().startswith("welcome"):
                    continue
                # Deduplicate
                key = content.lower()
                if key not in seen_content:
                    seen_content.add(key)
                    cross_agent_context.append(msg)

        # Cross-agent context first, then current agent's history
        return cross_agent_context + agent_history

    def _build_session_context(self, cm: MemoManager) -> dict[str, Any]:
        """
        Build session context dict for prompt rendering.

        Args:
            cm: MemoManager instance

        Returns:
            Dict with session variables for Jinja templates
        """
        from apps.artagent.backend.src.orchestration.prompt_context import cascade_prompt_context

        return {"memo_manager": cm, **cascade_prompt_context(cm)}

    # ─────────────────────────────────────────────────────────────────
    # Turn Processing
    # ─────────────────────────────────────────────────────────────────

    def set_recognition_anchor(self, perf_ts: float | None) -> None:
        """Set the end-of-recognition perf_counter anchor for the next turn.

        Overrides the default process_turn-entry anchor so the per-turn
        recognition->first-token KPI reflects the true gap from when the user
        stopped speaking (including queue + orchestration overhead). Consumed
        (cleared) on the next process_turn so it never leaks across turns.
        """
        self._recognition_anchor = perf_ts

    async def process_turn(
        self,
        context: OrchestratorContext | None = None,
        *,
        user_text: str | None = None,
        memo_manager: MemoManager | None = None,
        on_tts_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_tool_start: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        on_tool_end: Callable[[str, Any], Awaitable[None]] | None = None,
    ) -> OrchestratorResult:
        """Run a serialized turn with an explicitly owned async HTTP client.

        Websocket sessions borrow the application's AoaiClientManager. Standalone
        callers may inject async_client or use a client scoped to this whole turn
        (including tool recursion and handoffs), closed before returning.
        """
        async with self._turn_lock, AsyncExitStack() as resources:
            previous_client = self.async_client
            try:
                if self.async_client is None:
                    websocket = context.websocket if context else None
                    app = getattr(websocket, "app", None)
                    manager = getattr(getattr(app, "state", None), "aoai_client_manager", None)
                    if manager is not None:
                        self.async_client = await manager.get_async_client()
                    else:
                        from src.aoai.client import create_async_azure_openai_client

                        self.async_client = await resources.enter_async_context(
                            create_async_azure_openai_client()
                        )
                self._turn_task = asyncio.current_task()
                return await self._process_turn(
                    context,
                    user_text=user_text,
                    memo_manager=memo_manager,
                    on_tts_chunk=on_tts_chunk,
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                )
            finally:
                self._turn_task = None
                self.async_client = previous_client

    async def _process_turn(
        self,
        context: OrchestratorContext | None = None,
        *,
        user_text: str | None = None,
        memo_manager: MemoManager | None = None,
        on_tts_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_tool_start: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        on_tool_end: Callable[[str, Any], Awaitable[None]] | None = None,
    ) -> OrchestratorResult:
        """
        Process a conversation turn - UNIFIED ENTRY POINT.

        This is the single entry point for turn processing. Supports two calling patterns:

        Pattern 1 (Full context):
            result = await adapter.process_turn(context=orchestrator_context)

        Pattern 2 (Direct MemoManager - simplified):
            result = await adapter.process_turn(
                user_text="Hello",
                memo_manager=cm,
                on_tts_chunk=my_callback
            )

        Flow:
        1. Build/extract context and MemoManager
        2. Sync state from MemoManager (if provided)
        3. Build messages from history + user input
        4. Call LLM with streaming
        5. Handle tool calls / handoffs
        6. Record conversation to history
        7. Sync state to MemoManager

        Args:
            context: OrchestratorContext with user input and state (Pattern 1)
            user_text: User's input text (Pattern 2)
            memo_manager: MemoManager for state management (Pattern 2)
            on_tts_chunk: Callback for streaming TTS chunks
            on_tool_start: Callback when tool execution starts
            on_tool_end: Callback when tool execution completes

        Returns:
            OrchestratorResult with response and metadata
        """
        self._cancel_event.clear()
        self._metrics.start_turn()  # Increments turn count and resets TTFT tracking
        # Reset per-turn LLM time-to-first-token (captured during streaming).
        self._last_turn_ttft_ms = None
        self._last_error_info = None
        # Anchor recognition-complete -> first-token at turn entry (the finalized
        # user input has arrived by the time process_turn is called).
        self._turn_perf_start = time.perf_counter()
        self._last_turn_recog_to_llm_ms = None

        # Support both calling patterns: context OR direct parameters
        if context is None:
            # Pattern 2: Build context from parameters
            if memo_manager:
                self.sync_from_memo_manager(memo_manager)
                self._current_memo_manager = memo_manager

                # Initialize MCP servers for active agent (non-blocking)
                await self._init_mcp_for_agent(self._active_agent, memo_manager)

                # Get history and append current user message
                history = list(memo_manager.get_history(self._active_agent) or [])
                if user_text:
                    memo_manager.append_to_history(self._active_agent, "user", user_text)

                # Build context using helper (eliminates duplication)
                session_context = self._build_session_context(memo_manager)
            else:
                history = []
                session_context = {}

            context = OrchestratorContext(
                session_id=self.config.session_id or "",
                websocket=None,
                call_connection_id=self.config.call_connection_id,
                user_text=user_text or "",
                conversation_history=history,
                metadata=session_context,
            )
        else:
            # Pattern 1: Extract from provided context
            self._current_memo_manager = (
                context.metadata.get("memo_manager") if context.metadata else None
            )

        self._last_user_message = context.user_text
        turn_id = context.metadata.get("run_id", "") if context.metadata else ""

        agent = self.current_agent_config
        if not agent:
            info = VoiceErrorInfo(
                code="AgentNotFound",
                message=f"Agent '{self._active_agent}' is not available.",
                remediation=(
                    "Check that the agent exists in the agent registry and that the "
                    "active scenario lists it."
                ),
                source="config",
                fatal=True,
            )
            await self._surface_error(info, context)
            return OrchestratorResult(
                response_text="",
                agent_name=self._active_agent,
                error=info.as_json(),
            )

        # Activate session scope for cross-thread context preservation
        with CascadeSessionScope.activate(
            session_id=self.config.session_id or "",
            call_connection_id=self.config.call_connection_id or "",
            memo_manager=self._current_memo_manager,
            active_agent=self._active_agent,
            turn_id=turn_id,
        ):
            with tracer.start_as_current_span(
                "cascade.process_turn",
                kind=SpanKind.INTERNAL,
                attributes={
                    "cascade.agent": self._active_agent,
                    "cascade.turn": self._metrics.turn_count,
                    "session.id": self.config.session_id or "",
                    "call.connection.id": self.config.call_connection_id or "",
                    "cascade.has_memo_manager": self._current_memo_manager is not None,
                },
            ) as span:
                try:
                    # Build messages
                    messages = self._build_messages(context, agent)

                    # Get tools for current agent with automatic handoff tool injection
                    tools = self._get_tools_with_handoffs(agent)
                    logger.info(
                        "🔧 Agent tools loaded | agent=%s tool_count=%d tool_names=%s",
                        self._active_agent,
                        len(tools) if tools else 0,
                        [t.get("function", {}).get("name") for t in tools] if tools else [],
                    )

                    # Process with LLM (streaming) - session scope is preserved
                    response_text, tool_calls = await self._process_llm(
                        messages=messages,
                        tools=tools,
                        on_tts_chunk=on_tts_chunk,
                        on_tool_start=on_tool_start,
                        on_tool_end=on_tool_end,
                    )

                    # Check for handoff tool calls
                    handoff_executed = False
                    handoff_target = None
                    handoff_greeting = None  # Store greeting for fallback
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name", "")
                        if self.handoff_service.is_handoff(tool_name):
                            # Parse arguments first - they come as JSON string from streaming
                            raw_args = tool_call.get("arguments", "{}")
                            if isinstance(raw_args, str):
                                try:
                                    parsed_args = json.loads(raw_args) if raw_args else {}
                                except json.JSONDecodeError:
                                    parsed_args = {}
                            else:
                                parsed_args = raw_args if isinstance(raw_args, dict) else {}

                            # Emit tool_start for handoff tool (before execution)
                            if on_tool_start:
                                try:
                                    await on_tool_start(tool_name, raw_args)
                                except Exception:
                                    logger.debug("Failed to emit handoff tool_start", exc_info=True)

                            handoff_result = await self._execute_handoff(
                                tool_name=tool_name,
                                args=parsed_args,
                            )
                            target_agent = handoff_result.target_agent

                            # Emit tool_end for handoff tool (after execution)
                            if on_tool_end:
                                try:
                                    await on_tool_end(
                                        tool_name,
                                        {
                                            "handoff": True,
                                            "target_agent": target_agent,
                                            "handoff_type": handoff_result.handoff_type,
                                            "success": handoff_result.success,
                                        },
                                    )
                                except Exception:
                                    logger.debug("Failed to emit handoff tool_end", exc_info=True)

                            if not handoff_result.success:
                                logger.warning(
                                    "Handoff to %s failed: %s", target_agent, handoff_result.error
                                )
                                continue

                            handoff_executed = True
                            handoff_target = target_agent
                            handoff_greeting = handoff_result.greeting
                            break

                    # If handoff occurred, let the NEW agent respond immediately
                    # This eliminates the awkward "handoff confirmation" message
                    if handoff_executed and handoff_target:
                        span.set_attribute("cascade.handoff_executed", True)
                        span.set_attribute("cascade.handoff_target", handoff_target)

                        # Get the new agent
                        new_agent = self.agents.get(handoff_target)
                        if new_agent:
                            logger.info(
                                "Handoff complete, new agent responding | from=%s to=%s",
                                context.metadata.get("agent_name", "unknown"),
                                handoff_target,
                            )

                            updated_metadata = handoff_result.system_vars
                            handoff_user_text = updated_metadata.get("user_last_utterance", "")

                            # Get the new agent's existing history (if returning to this agent)
                            # Plus add user's current message for context about why handoff happened
                            new_agent_history = []
                            if self._current_memo_manager:
                                try:
                                    new_agent_history = list(
                                        self._current_memo_manager.get_history(handoff_target) or []
                                    )
                                except Exception:
                                    pass

                            # If this is first visit to agent, add context about user's request
                            if not new_agent_history and handoff_user_text:
                                new_agent_history.append(
                                    {
                                        "role": "user",
                                        "content": handoff_user_text,
                                    }
                                )

                            # Build messages for new agent with its own history
                            new_context = OrchestratorContext(
                                session_id=context.session_id,
                                websocket=context.websocket,
                                call_connection_id=context.call_connection_id,
                                user_text=(
                                    "" if new_agent_history else handoff_user_text
                                ),  # Avoid duplicate if added above
                                conversation_history=new_agent_history,
                                metadata=updated_metadata,
                            )

                            new_messages = self._build_messages(new_context, new_agent)
                            new_tools = self._get_tools_with_handoffs(new_agent)

                            try:
                                # Get response from new agent
                                new_response_text, new_tool_calls = await self._process_llm(
                                    messages=new_messages,
                                    tools=new_tools,
                                    on_tts_chunk=on_tts_chunk,
                                    on_tool_start=on_tool_start,
                                    on_tool_end=on_tool_end,
                                )

                                # Check if LLM produced meaningful response
                                if not new_response_text or len(new_response_text.strip()) < 10:
                                    # LLM response too short or empty - use greeting as fallback
                                    if handoff_greeting:
                                        logger.warning(
                                            "New agent LLM response too short (%d chars), using greeting fallback",
                                            len(new_response_text) if new_response_text else 0,
                                        )
                                        new_response_text = handoff_greeting
                                        # Stream greeting to TTS
                                        if on_tts_chunk and handoff_greeting:
                                            await on_tts_chunk(handoff_greeting)

                                logger.info(
                                    "New agent responded | agent=%s text_len=%d tool_calls=%d",
                                    handoff_target,
                                    len(new_response_text),
                                    len(new_tool_calls),
                                )

                                # Record handoff turn using consolidated helper
                                user_for_handoff = (
                                    handoff_user_text if not new_agent_history else None
                                )
                                self._record_turn(
                                    handoff_target, user_for_handoff, new_response_text
                                )

                                # Sync state
                                if self._current_memo_manager:
                                    self.sync_to_memo_manager(self._current_memo_manager)

                                span.set_status(Status(StatusCode.OK))

                                # _process_llm classifies rather than raises, so
                                # a failure by the agent we just handed off to
                                # arrives here as an apology string. Surface it
                                # instead of returning a "successful" turn.
                                handoff_error = self._last_error_info
                                if handoff_error is not None:
                                    span.set_attribute("error.code", handoff_error.code)
                                    await self._surface_error(handoff_error, context)

                                return OrchestratorResult(
                                    response_text=new_response_text,
                                    tool_calls=tool_calls + new_tool_calls,
                                    agent_name=self._active_agent,
                                    interrupted=self._cancel_event.is_set(),
                                    input_tokens=self._metrics.input_tokens,
                                    output_tokens=self._metrics.output_tokens,
                                    error=handoff_error.as_json() if handoff_error else None,
                                )
                            except Exception as handoff_err:
                                logger.error(
                                    "New agent failed to respond after handoff: %s",
                                    handoff_err,
                                    exc_info=True,
                                )
                                # Use greeting as fallback response
                                if handoff_greeting:
                                    logger.info(
                                        "Using greeting as fallback after LLM error | agent=%s",
                                        handoff_target,
                                    )
                                    # Stream greeting to TTS
                                    if on_tts_chunk:
                                        await on_tts_chunk(handoff_greeting)

                                    # Record the greeting as agent response
                                    self._record_turn(
                                        handoff_target, handoff_user_text, handoff_greeting
                                    )

                                    if self._current_memo_manager:
                                        self.sync_to_memo_manager(self._current_memo_manager)

                                    span.set_status(Status(StatusCode.OK))
                                    return OrchestratorResult(
                                        response_text=handoff_greeting,
                                        tool_calls=tool_calls,
                                        agent_name=self._active_agent,
                                        interrupted=self._cancel_event.is_set(),
                                        input_tokens=self._metrics.input_tokens,
                                        output_tokens=self._metrics.output_tokens,
                                    )
                                # No greeting fallback - fall through to return original response
                        else:
                            logger.warning(
                                "Handoff target agent not found: %s",
                                handoff_target,
                            )

                    # ─── RECORD & FINALIZE ───
                    # Record turn using consolidated helper (in-memory, no I/O)
                    user_recorded, assistant_recorded = self._record_turn(
                        self._active_agent, context.user_text, response_text
                    )

                    # Sync orchestrator state to MemoManager (in-memory)
                    if self._current_memo_manager:
                        self.sync_to_memo_manager(self._current_memo_manager)

                    # Set span attributes for observability
                    span.set_attributes(
                        {
                            "cascade.user_recorded": user_recorded,
                            "cascade.assistant_recorded": assistant_recorded,
                            "cascade.user_text_len": len(context.user_text or ""),
                            "cascade.response_text_len": len(response_text or ""),
                            "cascade.handoff_executed": handoff_executed,
                        }
                    )
                    span.set_status(Status(StatusCode.OK))

                    # A classified LLM failure still produces a spoken apology so
                    # the caller isn't met with silence, but the real cause must
                    # reach the operator UI.
                    llm_error = self._last_error_info
                    if llm_error is not None:
                        await self._surface_error(llm_error, context)

                    return OrchestratorResult(
                        response_text=response_text,
                        tool_calls=tool_calls,
                        agent_name=self._active_agent,
                        interrupted=self._cancel_event.is_set(),
                        input_tokens=self._metrics.input_tokens,
                        output_tokens=self._metrics.output_tokens,
                        ttft_ms=self._last_turn_ttft_ms,
                        error=llm_error.as_json() if llm_error else None,
                    )

                except asyncio.CancelledError:
                    span.set_status(Status(StatusCode.ERROR, "Cancelled"))
                    raise
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    logger.exception("Turn processing failed: %s", e)

                    info = self._classify_llm_error(e)
                    self._last_error_info = info
                    span.set_attribute("error.code", info.code)
                    await self._surface_error(info, context)

                    return OrchestratorResult(
                        response_text=info.spoken_message,
                        agent_name=self._active_agent,
                        error=info.as_json(),
                    )

    async def _surface_error(
        self,
        info: VoiceErrorInfo,
        context: OrchestratorContext | None = None,
    ) -> None:
        """Push a classified error to the session WebSocket and dashboards.

        Args:
            info: The classified error to surface.
            context: Turn context, used to locate the session WebSocket.
        """
        websocket = getattr(context, "websocket", None) if context else None
        if websocket is None:
            # Pattern-2 callers build their own context without a socket, so
            # there is nothing to surface to; the classified error is still
            # logged by emit_voice_error and returned on OrchestratorResult.
            logger.debug("No websocket available to surface %s", info.code)

        await emit_voice_error(
            websocket,
            info,
            session_id=self.config.session_id,
            call_id=self.config.call_connection_id,
        )

    def _build_messages(
        self,
        context: OrchestratorContext,
        agent: UnifiedAgent,
    ) -> list[dict[str, Any]]:
        """Build messages for LLM request.

        Handles both simple messages (role + content) and complex messages
        (tool calls, tool results) which are stored as JSON in the content field.

        Also injects scenario-based handoff instructions if defined.
        """
        messages = []

        # A resolved handoff owns the target's prompt scope, including later turns.
        # MemoManager remains transport/runtime state, never a template variable.
        system_content = agent.render_prompt(
            cascade_runtime_prompt_context(context.metadata, session_vars=self._session_vars)
        )

        # Inject handoff instructions from scenario configuration
        # Use cached orchestrator config (supports both file-based and session-scoped)
        config = self._orchestrator_config
        if config.scenario and agent.name:
            # Use scenario.build_handoff_instructions directly (works for session scenarios)
            handoff_instructions = config.scenario.build_handoff_instructions(agent.name)
            if handoff_instructions:
                system_content = (
                    f"{system_content}\n\n{handoff_instructions}"
                    if system_content
                    else handoff_instructions
                )
                logger.info(
                    "Injected handoff instructions into system prompt | agent=%s scenario=%s len=%d",
                    agent.name,
                    config.scenario_name,
                    len(handoff_instructions),
                )
        else:
            logger.debug(
                "_build_messages: no scenario or agent name | scenario=%s agent_name=%s",
                config.scenario_name if config.scenario else None,
                agent.name if agent else None,
            )

        if system_content:
            messages.append({"role": "system", "content": system_content})

        # Conversation history - expand any JSON-encoded tool messages
        for msg in context.conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Check if this is a JSON-encoded complex message (tool call or tool result)
            if role in ("assistant", "tool") and content and content.startswith("{"):
                try:
                    decoded = json.loads(content)
                    # If it has the expected structure, use it directly
                    if isinstance(decoded, dict) and "role" in decoded:
                        messages.append(decoded)
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass  # Not JSON, use as-is

            # Regular message
            messages.append(msg)

        # Current user message
        if context.user_text:
            messages.append({"role": "user", "content": context.user_text})

        return messages

    async def _process_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_tts_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_tool_start: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        on_tool_end: Callable[[str, Any], Awaitable[None]] | None = None,
        *,
        _iteration: int = 0,
        _max_iterations: int = 5,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Process messages through LLM with streaming TTS and tool-call loop.

        Uses STREAMING with a bounded async queue for low-latency TTS dispatch:
        - An owned async producer awaits HTTP deltas and queue backpressure
        - Main coroutine consumes queue and dispatches to TTS immediately
        - Tool calls are aggregated during streaming
        - After stream completes, tools are executed and we recurse

        Uses the current agent's model configuration (deployment_id, temperature, etc.)
        to allow session agents to specify their own LLM settings.

        Args:
            messages: Conversation messages including system prompt
            tools: OpenAI-format tool definitions
            on_tts_chunk: Callback for streaming TTS chunks
            on_tool_start: Callback when tool execution starts
            on_tool_end: Callback when tool execution completes
            _iteration: Internal recursion counter
            _max_iterations: Maximum tool-loop iterations

        Returns:
            Tuple of (response_text, all_tool_calls)
        """
        import json

        # Get model configuration from current agent (prefers cascade_model over generic model)
        agent = self.current_agent_config
        model_name = self.config.model_name  # Default from adapter config
        model_config = None

        if agent:
            # Use get_model_for_mode to pick cascade_model if available, else fallback to model
            model_config = agent.get_model_for_mode("cascade")
            model_name = model_config.deployment_id or model_name

        # Record the resolved deployment so turn KPIs can report the model that
        # actually processed this turn (selected-vs-processed validation).
        self._last_model_name = model_name
        # Safety: prevent infinite tool loops
        if _iteration >= _max_iterations:
            logger.warning(
                "Tool loop reached max iterations (%d); returning current state",
                _max_iterations,
            )
            return ("", [])

        # Tracks whether any audio text reached the caller this turn, so an error
        # after partial output doesn't tack an apology onto a half-spoken answer.
        spoke_any = False

        client = self.async_client
        if client is None:
            raise RuntimeError("Cascade requires process_turn() or an injected async_client")

        response_text = ""
        tool_calls: list[dict[str, Any]] = []
        all_tool_calls: list[dict[str, Any]] = []
        output_tokens = 0

        # Resolve endpoint dispatch once so telemetry, param building, and
        # the actual client call all agree. Only an explicit "responses"
        # preference routes off chat.completions; auto/chat/unset preserve
        # the existing default streaming behavior.
        endpoint_choice = _resolve_endpoint_choice(model_config)

        # Reject genuinely unsupported Advanced Builder controls before
        # building any request params, instead of silently dropping them.
        # min_p / typical_p have no equivalent parameter on either endpoint.
        # include_reasoning (an available reasoning SUMMARY, never raw
        # chain-of-thought) is only supported on the Responses endpoint, so
        # it is only rejected here when this turn is going to chat.completions.
        # This propagates out of _process_llm and is converted into a clear
        # structured error by _extract_error_details.
        _validate_model_config_capabilities(model_config, endpoint_choice)

        if endpoint_choice == "responses":
            streaming_params = self._prepare_responses_streaming_params(
                model_config, model_name, messages, tools
            )
        else:
            streaming_params = self._prepare_streaming_params(
                model_config, model_name, messages, tools
            )
        temp_attr = streaming_params.get("temperature")
        top_p_attr = streaming_params.get("top_p")
        max_tokens_attr = (
            streaming_params.get("max_tokens")
            or streaming_params.get("max_completion_tokens")
            or streaming_params.get("max_output_tokens")
        )

        # Extract endpoint preference and reasoning params from model_config for logging
        endpoint_pref = (
            getattr(model_config, "endpoint_preference", "auto") if model_config else "auto"
        )
        reasoning_effort = getattr(model_config, "reasoning_effort", None) if model_config else None
        verbosity = getattr(model_config, "verbosity", None) if model_config else None

        # Create span with GenAI semantic conventions
        span_attributes = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": self._active_agent,
            "gen_ai.agent.id": f"{self._active_agent}:v1",
            "gen_ai.agent.description": f"Voice agent: {self._active_agent}",
            "gen_ai.provider.name": "azure.ai.openai",
            "gen_ai.request.model": model_name,
            "gen_ai.request.max_tokens": max_tokens_attr,
            "gen_ai.request.endpoint_preference": endpoint_pref,
            "session.id": self.config.session_id or "",
            "rt.session.id": self.config.session_id or "",
            "rt.call.connection_id": self.config.call_connection_id or "",
            # Azure Monitor semantic conventions
            "dependency.type": "Azure OpenAI",
            "peer.service": "azure.ai.openai",
            "component": "cascade_adapter",
            "cascade.streaming": True,
            "cascade.tool_loop_iteration": _iteration,
        }
        # Add chat completions params (always used for streaming)
        span_attributes["gen_ai.request.temperature"] = temp_attr
        span_attributes["gen_ai.request.top_p"] = top_p_attr
        # Add responses API params if configured
        if reasoning_effort:
            span_attributes["gen_ai.request.reasoning_effort"] = reasoning_effort
        if verbosity is not None:
            span_attributes["gen_ai.request.verbosity"] = verbosity

        with tracer.start_as_current_span(
            f"invoke_agent {self._active_agent}",
            kind=SpanKind.INTERNAL,
            attributes=span_attributes,
        ) as span:
            try:
                # Build log message based on the resolved endpoint dispatch
                if endpoint_choice == "responses":
                    # Responses API config: show reasoning-specific parameters
                    params_str = f"reasoning_effort={reasoning_effort or 'N/A'} verbosity={verbosity if verbosity is not None else 'N/A'} max_tokens={max_tokens_attr or 'N/A'}"
                else:
                    # Chat Completions config: show traditional parameters
                    params_str = f"temp={temp_attr if temp_attr is not None else 'N/A'} top_p={top_p_attr if top_p_attr is not None else 'N/A'} max_tokens={max_tokens_attr or 'N/A'}"

                logger.info(
                    "Starting LLM request (streaming) | agent=%s model=%s endpoint=%s %s iteration=%d tools=%d",
                    self._active_agent,
                    model_name,
                    endpoint_pref,
                    params_str,
                    _iteration,
                    len(tools) if tools else 0,
                )

                # Bounded backpressure between the async model and TTS tasks.
                # Items are (sanitized_text, raw_display_text) tuples.
                # Special markers: None = stream end, "__HANDOFF_DETECTED__" = discard prior text
                tts_queue: asyncio.Queue[tuple[str, str] | str | None] = asyncio.Queue(maxsize=8)
                tool_buffers: dict[str, dict[str, Any]] = {}
                collected_text: list[str] = []
                stream_error: list[Exception] = []
                stream_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
                # TTFT capture: request_start set before the API call, first_token
                # set when the first content/tool delta arrives. Read on the async
                # side after the stream completes to derive llm.ttft_ms.
                ttft_tracker: dict[str, float] = {}
                tool_call_detected = False  # Track if tool calls are streaming
                handoff_tool_detected = False  # Track if specifically a handoff tool

                # Sentence buffer state for sentence-based TTS streaming
                sentence_buffer = ""
                # Parallel raw buffer preserving markdown for the UI envelope
                raw_sentence_buffer = ""
                # Primary breaks: sentence endings
                primary_terms = ".!?"

                async def _put_chunk(sanitized: str, raw: str | None = None) -> None:
                    """Backpressure text production while TTS is behind."""
                    # Don't send text to TTS if tool calls are being made
                    # The LLM sometimes outputs explanatory text alongside tool calls
                    if tool_call_detected:
                        return
                    if sanitized and sanitized.strip():
                        await tts_queue.put((sanitized, raw or sanitized))

                async def _signal_handoff_detected() -> None:
                    """Signal consumer to discard any queued text (for discrete handoffs)."""
                    await tts_queue.put("__HANDOFF_DETECTED__")

                async def _streaming_completion():
                    """Consume deltas in the task's inherited telemetry context."""
                    nonlocal sentence_buffer, raw_sentence_buffer, tool_call_detected, handoff_tool_detected
                    stream = None
                    try:
                        # Use pre-prepared streaming parameters
                        api_params = streaming_params

                        logger.debug(
                            "Starting OpenAI stream | model=%s messages=%d tools=%d params=%s",
                            model_name,
                            len(messages),
                            len(tools) if tools else 0,
                            {k: v for k, v in api_params.items() if k not in ["messages", "tools"]},
                        )
                        chunk_count = 0

                        # Extract telemetry values for span attributes
                        temp_value = api_params.get("temperature")
                        top_p_value = api_params.get("top_p")
                        max_tokens_value = (
                            api_params.get("max_tokens")
                            or api_params.get("max_completion_tokens")
                            or api_params.get("max_output_tokens")
                        )

                        # Dispatch to the endpoint explicitly resolved above
                        # (endpoint_choice). Only "responses" routes off
                        # chat.completions; once chosen it is the only
                        # endpoint attempted this turn — never silently
                        # substituted for the other on error.
                        endpoint_name = (
                            "responses" if endpoint_choice == "responses" else "chat.completions"
                        )

                        request_client = client
                        api_version_override = _resolve_api_version_override(model_config)
                        if api_version_override:
                            # Reuse the shared client's transport/credentials;
                            # only the api-version query param changes.
                            request_client = client.with_options(api_version=api_version_override)

                        # Create a span for the OpenAI streaming call
                        with tracer.start_as_current_span(
                            f"openai.{endpoint_name}.create (streaming)",
                            kind=SpanKind.CLIENT,
                            attributes={
                                "dependency.type": "Azure OpenAI",
                                "peer.service": "azure.ai.openai",
                                "gen_ai.operation.name": "chat",
                                "gen_ai.request.model": model_name,
                                "gen_ai.request.temperature": temp_value,
                                "gen_ai.request.top_p": top_p_value,
                                "gen_ai.request.max_tokens": max_tokens_value,
                                "gen_ai.streaming": True,
                                "gen_ai.endpoint_type": (
                                    "responses" if endpoint_choice == "responses" else "chat"
                                ),
                            },
                        ) as openai_span:
                            ttft_tracker["request_start"] = time.perf_counter()
                            if endpoint_choice == "responses":
                                stream = await request_client.responses.create(**api_params)
                            else:
                                stream = await request_client.chat.completions.create(**api_params)

                            response_state = {"next_index": 0, "item_index": {}}
                            async for chunk in stream:
                                if self._cancel_event.is_set():
                                    raise asyncio.CancelledError
                                if endpoint_choice == "responses":
                                    chunk = _normalize_responses_stream_event(chunk, response_state)
                                    if chunk is None:
                                        continue
                                chunk_count += 1

                                # Capture usage data from final chunk (stream_options.include_usage)
                                # Usage comes in a separate chunk at the end of the stream
                                usage = getattr(chunk, "usage", None)
                                if usage:
                                    # Handle both OpenAI and Azure naming conventions
                                    input_tok = (
                                        getattr(usage, "prompt_tokens", None)
                                        or getattr(usage, "input_tokens", None)
                                        or 0
                                    )
                                    output_tok = (
                                        getattr(usage, "completion_tokens", None)
                                        or getattr(usage, "output_tokens", None)
                                        or 0
                                    )
                                    stream_usage["input_tokens"] = input_tok
                                    stream_usage["output_tokens"] = output_tok
                                    logger.debug(
                                        "Stream usage captured | input=%d output=%d",
                                        input_tok,
                                        output_tok,
                                    )

                                if not getattr(chunk, "choices", None):
                                    continue
                                choice = chunk.choices[0]
                                delta = getattr(choice, "delta", None)
                                if not delta:
                                    continue

                                # Stamp time-to-first-token on the first content/tool delta
                                if "first_token" not in ttft_tracker and (
                                    getattr(delta, "content", None)
                                    or getattr(delta, "tool_calls", None)
                                ):
                                    ttft_tracker["first_token"] = time.perf_counter()
                                    if "request_start" in ttft_tracker:
                                        _ttft_ms = (
                                            ttft_tracker["first_token"]
                                            - ttft_tracker["request_start"]
                                        ) * 1000
                                        openai_span.set_attribute("llm.ttft_ms", round(_ttft_ms, 1))
                                        openai_span.add_event(
                                            "llm.first_token",
                                            attributes={"llm.ttft_ms": round(_ttft_ms, 1)},
                                        )

                                # Tool calls - aggregate streamed chunks by index
                                # Check tool calls FIRST to detect before dispatching text
                                if getattr(delta, "tool_calls", None):
                                    if not tool_call_detected:
                                        tool_call_detected = True
                                        logger.debug("Tool call detected - suppressing TTS output")
                                    for tc in delta.tool_calls:
                                        # Use explicit None check - index=0 is valid!
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
                                                # Check if this is a handoff tool - signal to discard queued text
                                                # This ensures discrete handoffs are seamless (no old agent speech)
                                                if (
                                                    not handoff_tool_detected
                                                    and self.handoff_service.is_handoff(fn_name)
                                                ):
                                                    handoff_tool_detected = True
                                                    logger.debug(
                                                        "Handoff tool detected: %s - signaling to discard queued TTS",
                                                        fn_name,
                                                    )
                                                    await _signal_handoff_detected()
                                            fn_args = getattr(fn, "arguments", None)
                                            if fn_args:
                                                buf["arguments"] += fn_args

                                # Text content - collect but only TTS if no tool calls
                                if getattr(delta, "content", None):
                                    text = delta.content
                                    collected_text.append(text)
                                    sentence_buffer += TTSTextProcessor.sanitize_tts_text(text)
                                    raw_sentence_buffer += text

                                    # Dispatch only on sentence boundaries.
                                    while True:
                                        term_idx = TTSTextProcessor.find_tts_boundary(
                                            sentence_buffer, primary_terms, 0
                                        )
                                        if term_idx < 0:
                                            break
                                        dispatch, sentence_buffer = (
                                            TTSTextProcessor.split_tts_buffer(
                                                sentence_buffer, term_idx + 1
                                            )
                                        )
                                        # Split raw buffer at the same character ratio
                                        ratio = len(dispatch) / max(
                                            len(dispatch) + len(sentence_buffer), 1
                                        )
                                        raw_split = max(1, round(len(raw_sentence_buffer) * ratio))
                                        raw_dispatch = raw_sentence_buffer[:raw_split]
                                        raw_sentence_buffer = raw_sentence_buffer[raw_split:]
                                        await _put_chunk(dispatch, raw_dispatch)

                            logger.debug("OpenAI stream completed | chunks=%d", chunk_count)
                            # Flush remaining buffer (only if no tool calls)
                            if sentence_buffer.strip():
                                await _put_chunk(sentence_buffer, raw_sentence_buffer)
                    except Exception as e:
                        logger.error("OpenAI stream error: %s", e)
                        stream_error.append(e)
                    finally:
                        if stream is not None:
                            await stream.close()
                    await tts_queue.put(None)

                async def _consume_stream() -> None:
                    nonlocal spoke_any
                    suppress_tts_output = False
                    while True:
                        try:
                            chunk = await asyncio.wait_for(tts_queue.get(), timeout=5.0)
                        except TimeoutError:
                            if stream_future.done():
                                break
                            continue
                        if chunk is None:
                            break
                        if self._cancel_event.is_set():
                            raise asyncio.CancelledError
                        if chunk == "__HANDOFF_DETECTED__":
                            suppress_tts_output = True
                            continue
                        tts_text, display_text = (
                            chunk if isinstance(chunk, tuple) else (chunk, chunk)
                        )
                        # Inspect the producer flag as well: queued text can
                        # precede the handoff marker when synthesis is slow.
                        if suppress_tts_output or handoff_tool_detected:
                            continue
                        if on_tts_chunk:
                            await on_tts_chunk(tts_text, display_text=display_text)
                            spoke_any = True

                stream_future = asyncio.create_task(
                    _streaming_completion(), name="cascade-llm-stream"
                )
                try:
                    async with asyncio.timeout(90.0):
                        await _consume_stream()
                        # Observe producer failures (including stream.close), even
                        # if the queue consumer found the task already finished.
                        await stream_future
                finally:
                    if not stream_future.done():
                        stream_future.cancel()
                    await asyncio.gather(stream_future, return_exceptions=True)

                if stream_error:
                    raise stream_error[0]

                response_text = "".join(collected_text).strip()

                # Filter out incomplete tool calls (empty name or malformed)
                raw_tool_calls = list(tool_buffers.values())
                tool_calls = []
                for tc in raw_tool_calls:
                    name = tc.get("name", "").strip()
                    if not name:
                        logger.debug("Skipping tool call with empty name: %s", tc)
                        continue
                    # Validate arguments are parseable JSON
                    args_str = tc.get("arguments", "")
                    if args_str:
                        try:
                            json.loads(args_str)
                        except json.JSONDecodeError as e:
                            logger.warning(
                                "Skipping tool call with invalid JSON args: name=%s error=%s",
                                name,
                                e,
                            )
                            continue
                    tool_calls.append(tc)

                # Use actual token usage from stream if available, fallback to estimate
                input_tokens = stream_usage.get("input_tokens", 0)
                output_tokens = stream_usage.get("output_tokens", 0)

                # Fallback to estimate if stream didn't provide usage
                if input_tokens == 0 and messages:
                    # Estimate ~4 chars per token for input messages
                    total_chars = sum(
                        len(str(m.get("content", ""))) for m in messages if isinstance(m, dict)
                    )
                    input_tokens = max(total_chars // 4, 1)
                    logger.debug(
                        "Using estimated input_tokens=%d (stream usage not available)", input_tokens
                    )

                if output_tokens == 0 and response_text:
                    output_tokens = len(response_text) // 4
                    logger.debug(
                        "Using estimated output_tokens=%d (stream usage not available)",
                        output_tokens,
                    )

                # Track tokens via metrics - now includes input tokens
                self._metrics.add_tokens(input_tokens=input_tokens, output_tokens=output_tokens)
                self._metrics.record_response()

                logger.info(
                    "LLM response (streamed) | agent=%s text_len=%d tool_calls=%d (filtered from %d) iteration=%d tokens=%d/%d",
                    self._active_agent,
                    len(response_text),
                    len(tool_calls),
                    len(raw_tool_calls),
                    _iteration,
                    input_tokens,
                    output_tokens,
                )

                # Set GenAI semantic convention attributes for App Insights
                span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                span.set_attribute("gen_ai.response.length", len(response_text))

                # Attach eval-ready content so Foundry trace evaluation can grade
                # this turn directly from the invoke_agent span. No-op unless
                # EVAL_SPAN_CONTENT_ENABLED=true; PII-scrubbed by default.
                annotate_eval_content(
                    span,
                    input_messages=messages,
                    output_text=response_text,
                )

                # Surface LLM time-to-first-token (request -> first streamed token).
                # Keep the first iteration's value for the turn-level KPI summary.
                if "request_start" in ttft_tracker and "first_token" in ttft_tracker:
                    ttft_ms = (ttft_tracker["first_token"] - ttft_tracker["request_start"]) * 1000
                    span.set_attribute("llm.ttft_ms", round(ttft_ms, 1))
                    if self._last_turn_ttft_ms is None:
                        self._last_turn_ttft_ms = ttft_ms

                if tool_calls:
                    span.set_attribute("tool_call_detected", True)
                    span.set_attribute("tool_names", [tc.get("name", "") for tc in tool_calls])

                # Process tool calls if any
                non_handoff_tools = [
                    tc
                    for tc in tool_calls
                    if not self.handoff_service.is_handoff(tc.get("name", ""))
                ]
                handoff_tools = [
                    tc for tc in tool_calls if self.handoff_service.is_handoff(tc.get("name", ""))
                ]

                all_tool_calls.extend(tool_calls)

                # Commit business calls in the same batch before changing agents.
                if handoff_tools:
                    span.set_attribute("cascade.handoff_detected", True)

                # Execute non-handoff tools and loop back to LLM
                if non_handoff_tools:
                    # Append assistant message with tool calls to history
                    assistant_msg: dict[str, Any] = {"role": "assistant"}
                    if response_text:
                        assistant_msg["content"] = response_text
                    else:
                        assistant_msg["content"] = None
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.get("id"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": tc.get("arguments", "{}"),
                            },
                        }
                        for tc in non_handoff_tools
                    ]
                    messages.append(assistant_msg)

                    # Execute each tool and collect results
                    agent = self.current_agent_config

                    # Get session scope for context preservation
                    session_scope = CascadeSessionScope.get_current()
                    cm = session_scope.memo_manager if session_scope else self._current_memo_manager

                    # Persist assistant message with tool calls to MemoManager
                    # This ensures the tool call is in history for subsequent turns
                    if cm:
                        try:
                            # Store the assistant message as JSON to preserve tool_calls structure
                            cm.append_to_history(
                                self._active_agent,
                                "assistant",
                                (
                                    json.dumps(assistant_msg)
                                    if assistant_msg.get("tool_calls")
                                    else (response_text or "")
                                ),
                            )
                        except Exception:
                            logger.debug(
                                "Failed to persist assistant tool_call message to history",
                                exc_info=True,
                            )

                    for tool_call in non_handoff_tools:
                        tool_name = tool_call.get("name", "")
                        tool_id = tool_call.get("id", "")
                        raw_args = tool_call.get("arguments", "{}")

                        # Create tool execution span for App Insights tracing
                        tool_span_attrs = {
                            SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.EXECUTE_TOOL,
                            SpanAttr.GENAI_TOOL_NAME.value: tool_name,
                            SpanAttr.GENAI_TOOL_CALL_ID.value: tool_id,
                            SpanAttr.GENAI_TOOL_TYPE.value: "function",
                            SpanAttr.PEER_SERVICE.value: "agent.tools",
                        }

                        with tracer.start_as_current_span(
                            f"execute_tool {tool_name}",
                            kind=trace.SpanKind.INTERNAL,
                            attributes=tool_span_attrs,
                        ) as tool_span:
                            if on_tool_start:
                                await on_tool_start(tool_name, raw_args)

                            result: dict[str, Any] = {"error": "Tool execution failed"}
                            if agent:
                                try:
                                    args = tool_arguments(raw_args, cm)
                                    result = normalize_tool_result(
                                        await agent.execute_tool(tool_name, args)
                                    )
                                    self._session_vars.update(
                                        apply_tool_result(cm, tool_name, result)
                                    )
                                    logger.info(
                                        "Tool executed | name=%s result_keys=%s",
                                        tool_name,
                                        (
                                            list(result.keys())
                                            if isinstance(result, dict)
                                            else type(result).__name__
                                        ),
                                    )

                                    # Mark tool span as successful
                                    tool_span.set_status(Status(StatusCode.OK))

                                except Exception as e:
                                    logger.error("Tool execution failed for %s: %s", tool_name, e)
                                    result = {"error": str(e), "tool_name": tool_name}
                                    # Record GenAI error for failed tool execution
                                    tool_span.set_status(Status(StatusCode.ERROR, str(e)))
                                    tool_span.record_exception(e)
                                    tool_span.add_event(
                                        "gen_ai.tool.execution_error",
                                        {
                                            "error.type": type(e).__name__,
                                            "error.message": str(e),
                                            "gen_ai.tool.name": tool_name,
                                        },
                                    )

                            # Append tool result message
                            tool_result_msg = {
                                "tool_call_id": tool_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": (
                                    json.dumps(result) if isinstance(result, dict) else str(result)
                                ),
                            }
                            messages.append(tool_result_msg)
                            if cm:
                                cm.append_to_history(
                                    self._active_agent, "tool", json.dumps(tool_result_msg)
                                )
                            if on_tool_end:
                                await on_tool_end(tool_name, result)

                    if handoff_tools:
                        span.set_status(Status(StatusCode.OK))
                        return response_text, all_tool_calls

                    # Advance turn_id to create a new message segment for post-tool response
                    # This prevents the UI from overwriting pre-tool assistant content
                    session_scope = CascadeSessionScope.get_current()
                    if session_scope:
                        session_scope.advance_turn_for_tool()

                    # Recurse to get LLM follow-up response
                    span.add_event(
                        "tool_followup_starting", {"tools_executed": len(non_handoff_tools)}
                    )
                    followup_text, followup_tools = await self._process_llm(
                        messages=messages,
                        tools=tools,
                        on_tts_chunk=on_tts_chunk,
                        on_tool_start=on_tool_start,
                        on_tool_end=on_tool_end,
                        _iteration=_iteration + 1,
                        _max_iterations=_max_iterations,
                    )

                    # Combine results
                    all_tool_calls.extend(followup_tools)
                    span.set_status(Status(StatusCode.OK))
                    return followup_text, all_tool_calls

                span.set_status(Status(StatusCode.OK))

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                logger.exception("LLM processing failed: %s", e)

                # Classify so the operator UI can show the real cause (missing
                # deployment, bad credentials, exhausted quota) instead of a
                # generic apology. process_turn picks this up and emits it.
                info = self._classify_llm_error(e)
                self._last_error_info = info
                span.set_attribute("error.code", info.code)
                response_text = info.spoken_message or (
                    "I apologize, I encountered an error processing your request."
                )

                # An ACS caller has no UI, so the envelope alone leaves them with
                # dead air. Speak the fallback unless the turn was interrupted or
                # the caller already heard part of an answer.
                if on_tts_chunk and not spoke_any and not self._cancel_event.is_set():
                    try:
                        await on_tts_chunk(response_text)
                    except Exception:  # noqa: BLE001 - never mask the LLM failure
                        logger.debug("Failed to speak LLM error fallback", exc_info=True)

        return response_text, all_tool_calls

    async def _dispatch_tts_chunks(
        self,
        text: str,
        on_tts_chunk: Callable[[str], Awaitable[None]],
        *,
        min_chunk: int = 40,
    ) -> None:
        """
        Emit TTS chunks based on sentence boundaries.

        Splits by sentence boundaries and flushes any remaining text at end.
        Passes the original (unsanitized) text as *display_text* so
        the UI can render markdown while TTS receives plain text.
        """
        try:
            sanitized = TTSTextProcessor.sanitize_tts_text(text).strip()
            if not sanitized:
                return

            segments: list[tuple[str, str]] = []  # (sanitized, raw_display)
            buffer = sanitized
            raw_buffer = text
            primary_terms = ".!?"
            while True:
                term_idx = TTSTextProcessor.find_tts_boundary(buffer, primary_terms, 0)
                if term_idx < 0:
                    break
                segment, buffer = TTSTextProcessor.split_tts_buffer(buffer, term_idx + 1)
                if segment.strip():
                    ratio = len(segment) / max(len(segment) + len(buffer), 1)
                    raw_split = max(1, round(len(raw_buffer) * ratio))
                    raw_segment = raw_buffer[:raw_split]
                    raw_buffer = raw_buffer[raw_split:]
                    segments.append((segment, raw_segment))

            if buffer.strip():
                segments.append((buffer, raw_buffer))

            for segment, raw_segment in segments:
                result = on_tts_chunk(segment, display_text=raw_segment)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("TTS chunk dispatch failed: %s", exc)

    def _prepare_streaming_params(
        self,
        model_config: Any,
        model_name: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> dict[str, Any]:
        """
        Prepare API parameters for streaming LLM calls.

        SIMPLIFIED: Always builds chat.completions compatible params for streaming.
        This avoids endpoint/param mismatches that cause runtime errors.

        Parameter rules by model type:
        - Legacy models (gpt-4o, gpt-4): temperature, top_p, max_tokens
        - New-gen models (o1, o3, o4, gpt-5, gpt-5.1, gpt-4.1): max_completion_tokens

        Args:
            model_config: ModelConfig instance (or None for defaults)
            model_name: Deployment ID
            messages: Conversation messages
            tools: Tool definitions

        Returns:
            Dict of parameters for chat.completions.create()
        """
        # Detect if this is a new-generation model that uses max_completion_tokens
        # This includes: reasoning models (o1/o3/o4) AND new GPT models (gpt-5.x, gpt-4.1)
        deployment_lower = model_name.lower() if model_name else ""

        # Patterns for new-gen models requiring max_completion_tokens
        new_gen_patterns = ["o1", "o3-", "o4-", "gpt-5", "gpt5", "gpt-4.1", "gpt4.1"]
        uses_max_completion_tokens = any(p in deployment_lower for p in new_gen_patterns)

        # Also check model_config for explicit settings
        if model_config:
            uses_max_completion_tokens = uses_max_completion_tokens or getattr(
                model_config, "is_reasoning_model", False
            )
            model_family = getattr(model_config, "model_family", None)
            if model_family in ["o1", "o3", "o4", "gpt-5", "gpt-4.1"]:
                uses_max_completion_tokens = True

        # Models that don't support custom temperature (reasoning models only)
        no_custom_temp = any(p in deployment_lower for p in ["o1", "o3-", "o4-"])
        if model_config:
            model_family = getattr(model_config, "model_family", None)
            if model_family in ["o1", "o3", "o4"]:
                no_custom_temp = True

        # Base params - always required
        params: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "timeout": 60,
        }

        # Add tools if provided
        if tools:
            params["tools"] = tools

        # Token limit parameter
        max_tokens = 4096  # default
        if model_config:
            max_tokens = (
                getattr(model_config, "max_completion_tokens", None)
                or getattr(model_config, "max_tokens", None)
                or 4096
            )

        if uses_max_completion_tokens:
            params["max_completion_tokens"] = max_tokens
        else:
            params["max_tokens"] = max_tokens

        # Temperature/top_p - only for models that support them
        if not no_custom_temp:
            temp = 0.7  # default
            if model_config:
                temp = getattr(model_config, "temperature", None)
                if temp is None:
                    temp = 0.7
            params["temperature"] = temp

            top_p = None
            if model_config:
                top_p = getattr(model_config, "top_p", None)
            if top_p is not None:
                params["top_p"] = top_p

        # Propagate advanced request properties confirmed present on the
        # installed OpenAI SDK's chat.completions.create signature
        # (verified via inspect.signature: metadata, reasoning_effort,
        # response_format, store, and verbosity are all real keyword
        # params). These were previously computed only for telemetry/span
        # attributes and never added to the request dict. Only forwarded
        # when explicitly configured (non-default/non-None) so agents that
        # never touch these Advanced Builder controls keep receiving
        # byte-for-byte the same request they always have.
        if model_config:
            reasoning_effort = getattr(model_config, "reasoning_effort", None)
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort

            verbosity = getattr(model_config, "verbosity", None)
            if verbosity:
                params["verbosity"] = _map_verbosity_level(verbosity)

            store = getattr(model_config, "store", None)
            if store is not None:
                params["store"] = store

            metadata = getattr(model_config, "metadata", None)
            if metadata:
                params["metadata"] = metadata

            response_format = getattr(model_config, "response_format", None)
            if response_format:
                params["response_format"] = response_format

        logger.debug(
            "Prepared streaming params | model=%s uses_max_completion_tokens=%s no_custom_temp=%s",
            model_name,
            uses_max_completion_tokens,
            no_custom_temp,
        )

        return params

    def _prepare_responses_streaming_params(
        self,
        model_config: Any,
        model_name: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> dict[str, Any]:
        """
        Prepare API parameters for an explicit Responses API streaming call.

        Only used when ``model_config.endpoint_preference == "responses"``.
        Builds the Responses-shaped request (``input``/``instructions``/
        ``max_output_tokens``/``reasoning``/``text``) instead of reusing
        ``_prepare_streaming_params``'s chat.completions shape.

        Deliberately does NOT reuse
        ``src.aoai.manager.AzureOpenAIManager._prepare_responses_params``:
        that helper flattens conversation history (including tool calls and
        tool results) into a single text blob and emits parameter
        names/values not present on the installed SDK, which would silently
        break multi-turn tool-calling for the voice streaming path.

        Args:
            model_config: ModelConfig instance (or None for defaults)
            model_name: Deployment ID
            messages: Conversation messages (chat.completions shape)
            tools: Tool definitions (chat.completions shape; converted below)

        Returns:
            Dict of parameters for ``client.responses.create()``.
        """
        instructions, input_items = _convert_messages_to_responses_input(messages)

        params: dict[str, Any] = {
            "model": model_name,
            "input": input_items,
            "stream": True,
            "timeout": 60,
        }
        if instructions:
            params["instructions"] = instructions
        if tools:
            params["tools"] = _convert_tools_to_responses_format(tools)

        deployment_lower = model_name.lower() if model_name else ""
        no_custom_temp = any(p in deployment_lower for p in ["o1", "o3-", "o4-"])
        if model_config:
            model_family = getattr(model_config, "model_family", None)
            if model_family in ["o1", "o3", "o4"]:
                no_custom_temp = True

        max_tokens = 4096
        if model_config:
            max_tokens = (
                getattr(model_config, "max_completion_tokens", None)
                or getattr(model_config, "max_tokens", None)
                or 4096
            )
        params["max_output_tokens"] = max_tokens

        if not no_custom_temp:
            temp = getattr(model_config, "temperature", None) if model_config else None
            if temp is None:
                temp = 0.7
            params["temperature"] = temp

            top_p = getattr(model_config, "top_p", None) if model_config else None
            if top_p is not None:
                params["top_p"] = top_p

        reasoning_effort = getattr(model_config, "reasoning_effort", None) if model_config else None
        include_reasoning = (
            getattr(model_config, "include_reasoning", False) if model_config else False
        )
        reasoning_config: dict[str, Any] = {}
        if reasoning_effort:
            reasoning_config["effort"] = reasoning_effort
        if include_reasoning:
            # "auto" surfaces whatever reasoning SUMMARY the model makes
            # available (openai.types.shared_params.reasoning.Reasoning.summary) —
            # never the raw hidden chain-of-thought, which no endpoint exposes.
            reasoning_config["summary"] = "auto"
        if reasoning_config:
            params["reasoning"] = reasoning_config

        verbosity = getattr(model_config, "verbosity", None) if model_config else None
        text_config: dict[str, Any] = {}
        if verbosity:
            text_config["verbosity"] = _map_verbosity_level(verbosity)
        response_format = getattr(model_config, "response_format", None) if model_config else None
        if response_format:
            if response_format.get("type") == "json_schema" and isinstance(
                response_format.get("json_schema"), dict
            ):
                text_config["format"] = {"type": "json_schema", **response_format["json_schema"]}
            else:
                text_config["format"] = response_format
        if text_config:
            params["text"] = text_config

        store = getattr(model_config, "store", None) if model_config else None
        if store is not None:
            params["store"] = store

        metadata = getattr(model_config, "metadata", None) if model_config else None
        if metadata:
            params["metadata"] = metadata

        logger.debug(
            "Prepared responses streaming params | model=%s no_custom_temp=%s has_reasoning=%s "
            "has_summary=%s has_verbosity=%s",
            model_name,
            no_custom_temp,
            bool(reasoning_effort),
            include_reasoning,
            bool(verbosity),
        )

        return params

    def _extract_error_details(self, exception: Exception) -> str:
        """Return a JSON error payload for the frontend.

        Thin wrapper over the shared classifier so cascade and VoiceLive report
        identical codes for the same underlying Azure failure.

        Args:
            exception: The exception to describe.

        Returns:
            JSON string with ``code``, ``message``, ``details`` and ``remediation``.
        """
        return self._classify_llm_error(exception).as_json()

    def _classify_llm_error(self, exception: Exception) -> VoiceErrorInfo:
        if isinstance(exception, UnsupportedModelOptionError):
            return VoiceErrorInfo(
                code="UnsupportedModelOption",
                message=(
                    "This agent's model configuration uses option(s) with no "
                    "supported parameter for the endpoint this turn used: "
                    + ", ".join(exception.options)
                ),
                details=str(exception),
                remediation=(
                    "Remove min_p and typical_p; neither endpoint supports them. "
                    "For include_reasoning, select endpoint_preference='responses' "
                    "to request an available reasoning summary, not hidden chain-of-thought."
                ),
                source="config",
                fatal=True,
                metadata={"unsupported_options": list(exception.options)},
            )
        return classify_voice_error(
            exception,
            source="llm",
            model=self._last_model_name,
            agent=self._active_agent,
        )

    async def cancel_current(self) -> None:
        """Signal cancellation for barge-in."""
        self._cancel_event.set()
        task = self._turn_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # ─────────────────────────────────────────────────────────────────
    # Handoff Management
    # ─────────────────────────────────────────────────────────────────

    async def _execute_handoff(
        self,
        tool_name: str,
        args: dict[str, Any],
        system_vars: dict[str, Any] | None = None,
    ) -> HandoffResult:
        """
        Execute a handoff to another agent.

        Uses HandoffService for consistent resolution and greeting selection
        across both Cascade and VoiceLive orchestrators.

        Args:
            tool_name: Handoff tool that triggered the switch
            args: Tool arguments (may contain context)
            system_vars: Optional system variables for greeting selection

        Returns:
            HandoffResult with success status, handoff_type, greeting, etc.
        """
        previous_agent = self._active_agent

        with tracer.start_as_current_span(
            "cascade.handoff",
            kind=SpanKind.INTERNAL,
            attributes={
                "cascade.source_agent": previous_agent,
                "cascade.tool_name": tool_name,
            },
        ) as span:
            # Use HandoffService for consistent resolution
            resolution = self.handoff_service.resolve_handoff(
                tool_name=tool_name,
                tool_args=args,
                source_agent=previous_agent,
                current_system_vars=system_vars or self._session_vars,
                user_last_utterance=self._last_user_message,
            )

            if not resolution.success:
                logger.warning(
                    "Handoff resolution failed | tool=%s error=%s",
                    tool_name,
                    resolution.error,
                )
                span.set_status(Status(StatusCode.ERROR, resolution.error or "Handoff failed"))
                return HandoffResult(
                    success=False,
                    target_agent=resolution.target_agent or "",
                    handoff_type=resolution.handoff_type,
                    error=resolution.error,
                )

            target_agent = resolution.target_agent
            is_first_visit = target_agent not in self._visited_agents
            span.set_attribute("cascade.target_agent", target_agent)
            span.set_attribute("cascade.is_first_visit", is_first_visit)
            # Update state
            self._visited_agents.add(target_agent)
            self._active_agent = target_agent
            self._session_vars = resolution.system_vars

            # Reset metrics for new agent (captures summary of previous)
            self._metrics.reset_for_agent_switch(target_agent)

            # Select greeting using HandoffService for consistent behavior
            new_agent = self.agents[target_agent]
            greeting = self.handoff_service.select_greeting(
                agent=new_agent,
                is_first_visit=is_first_visit,
                greet_on_switch=resolution.greet_on_switch,
                system_vars=resolution.system_vars,
            )

            # Notify callback
            if self._on_agent_switch:
                await self._on_agent_switch(previous_agent, target_agent)

            span.set_attribute("cascade.greeting", greeting or "(none)")
            span.set_attribute("cascade.handoff_type", resolution.handoff_type)
            span.set_attribute("cascade.share_context", resolution.share_context)
            span.set_status(Status(StatusCode.OK))

            logger.info(
                "Handoff: %s → %s (trigger=%s type=%s greeting=%s)",
                previous_agent,
                target_agent,
                tool_name,
                resolution.handoff_type,
                "yes" if greeting else "no",
            )

            return HandoffResult(
                success=True,
                target_agent=target_agent,
                handoff_type=resolution.handoff_type,
                greeting=greeting,
                system_vars=resolution.system_vars,
            )

    # ─────────────────────────────────────────────────────────────────
    # Greeting Selection (delegates to HandoffService)
    # ─────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────
    # MemoManager Integration
    # ─────────────────────────────────────────────────────────────────

    def sync_from_memo_manager(self, cm: MemoManager) -> None:
        """
        Sync adapter state from MemoManager.

        Call this at the start of each turn to pick up any
        state changes (e.g., handoffs set by tools), ensuring
        session context continuity.

        If a scenario switch is pending (set by update_scenario), the adapter's
        _active_agent takes precedence over MemoManager's stale value. The
        correct active_agent is written TO the MemoManager so downstream code
        and subsequent turns see the updated value.

        Args:
            cm: MemoManager instance
        """
        # Use shared sync utility
        state = sync_state_from_memo(cm, available_agents=set(self.agents.keys()))

        # If a scenario switch is pending, the adapter's _active_agent is
        # authoritative — write it to MemoManager instead of reading from it.
        scenario_switched = self._scenario_switch_pending
        if scenario_switched:
            logger.info(
                "Scenario switch pending — writing active_agent to MemoManager | active=%s memo_active=%s",
                self._active_agent,
                state.active_agent,
            )
            sync_state_to_memo(
                cm,
                active_agent=self._active_agent,
                visited_agents=self._visited_agents,
                clear_pending_handoff=True,
            )
            self._scenario_switch_pending = False
            self._session_vars = {}
        elif state.pending_handoff and state.pending_handoff.get("target_agent") in self.agents:
            self._active_agent = state.pending_handoff["target_agent"]
            sync_state_to_memo(cm, active_agent=self._active_agent, clear_pending_handoff=True)
        elif state.active_agent:
            # Normal path: MemoManager is authoritative
            self._active_agent = state.active_agent

        if state.visited_agents and not scenario_switched:
            self._visited_agents = state.visited_agents
        if (
            self._session_vars.get("is_handoff")
            and self._session_vars.get("active_agent") != self._active_agent
        ):
            self._session_vars = {}
        if state.system_vars and not self._session_vars.get("is_handoff"):
            self._session_vars.update(state.system_vars)

        # Restore cascade-specific state (turn count via metrics)
        turn_count = (
            cm.get_value_from_corememory("cascade_turn_count")
            if hasattr(cm, "get_value_from_corememory")
            else None
        )
        if turn_count and isinstance(turn_count, int):
            self._metrics._turn_count = turn_count

        # Restore token counts via metrics
        tokens = (
            cm.get_value_from_corememory("cascade_tokens")
            if hasattr(cm, "get_value_from_corememory")
            else None
        )
        if tokens and isinstance(tokens, dict):
            self._metrics.restore_from_memo(tokens)

    def sync_to_memo_manager(self, cm: MemoManager) -> None:
        """
        Sync adapter state to MemoManager.

        Call this after processing to persist state, ensuring
        session context continuity across turns.

        Args:
            cm: MemoManager instance
        """
        # Use shared sync utility for common state
        sync_state_to_memo(
            cm,
            active_agent=self._active_agent,
            visited_agents=self._visited_agents,
            system_vars=self._session_vars,
        )

        # Persist cascade-specific state (turn count, tokens) via metrics
        if hasattr(cm, "set_corememory"):
            cm.set_corememory("cascade_turn_count", self._metrics.turn_count)
            cm.set_corememory("cascade_tokens", self._metrics.to_memo_state())


__all__ = [
    "CascadeOrchestratorAdapter",
    "CascadeConfig",
    "CascadeSessionScope",
    "StateKeys",
]
