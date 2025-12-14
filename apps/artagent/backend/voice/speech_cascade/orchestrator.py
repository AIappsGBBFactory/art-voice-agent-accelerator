"""
Cascade Orchestrator Adapter
==============================

Adapter that integrates the unified agent structure (apps/artagent/agents/)
with the SpeechCascade handler for multi-agent voice orchestration.

This adapter:
- Uses UnifiedAgent from the new modular agent structure
- Provides multi-agent handoffs via state-based transitions
- Integrates with the shared tool registry
- Processes turns synchronously via process_gpt_response pattern

Architecture:
    SpeechCascadeHandler
           │
           ▼
    CascadeOrchestratorAdapter ─► UnifiedAgent registry
           │                           │
           ├─► process_turn()          └─► get_tools()
           │                               render_prompt()
           └─► HandoffManager ─────────► build_handoff_map()

Usage:
    from apps.artagent.backend.voice.speech_cascade import CascadeOrchestratorAdapter

    # Create with unified agents
    adapter = CascadeOrchestratorAdapter.create(
        start_agent="Concierge",
        call_connection_id="call_123",
        session_id="session_456",
    )

    # Use as orchestrator_func in SpeechCascadeHandler
    async def orchestrator_func(cm, transcript):
        await adapter.process_user_input(transcript, cm)

    # Or wrap for legacy gpt_flow interface
    func = adapter.as_orchestrator_func()
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import os
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.registries.toolstore.registry import is_handoff_tool
from apps.artagent.backend.voice.shared.base import (
    OrchestratorContext,
    OrchestratorResult,
)
from apps.artagent.backend.voice.shared.config_resolver import (
    DEFAULT_START_AGENT,
    resolve_from_app_state,
    resolve_orchestrator_config,
)
from apps.artagent.backend.voice.shared.handoff_service import HandoffService
from apps.artagent.backend.voice.shared.session_state import (
    SessionStateKeys,
    sync_state_from_memo,
    sync_state_to_memo,
)
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode


@dataclass
class HandoffResult:
    """Result from executing a handoff."""
    success: bool
    target_agent: str = ""
    handoff_type: str = "announced"  # "discrete" or "announced"
    greeting: str | None = None
    error: str | None = None


if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
    from apps.artagent.backend.registries.agentstore.session_manager import HandoffProvider
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

    @classmethod
    def get_current(cls) -> CascadeSessionScope | None:
        """Get the current session scope from context variable."""
        return _cascade_session_ctx.get()

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
# Main Adapter
# ─────────────────────────────────────────────────────────────────────


@dataclass
class CascadeOrchestratorAdapter:
    """
    Adapter for SpeechCascade multi-agent orchestration using unified agents.

    This adapter integrates the modular agent structure (apps/artagent/agents/)
    with the SpeechCascadeHandler, providing:

    - State-based handoffs via MemoManager
    - Tool execution via shared registry
    - Prompt rendering with runtime context
    - OpenTelemetry instrumentation

    Design:
    - Synchronous turn processing (not event-driven)
    - State-based handoffs (not tool-based)
    - Uses gpt_flow pattern for LLM streaming

    Attributes:
        config: Orchestrator configuration
        agents: Registry of UnifiedAgent instances
        handoff_map: Tool name → agent name mapping
    """

    config: CascadeConfig = field(default_factory=CascadeConfig)
    agents: dict[str, UnifiedAgent] = field(default_factory=dict)
    handoff_map: dict[str, str] = field(default_factory=dict)

    # Runtime state
    _active_agent: str = field(default="", init=False)
    _visited_agents: set = field(default_factory=set, init=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _last_user_message: str | None = field(default=None, init=False)

    # Session context - preserves MemoManager reference for turn duration
    _current_memo_manager: MemoManager | None = field(default=None, init=False)
    _session_vars: dict[str, Any] = field(default_factory=dict, init=False)

    # HandoffProvider for session-aware handoff lookups (preferred over handoff_map)
    _handoff_provider: HandoffProvider | None = field(default=None, init=False)

    # Token tracking
    _agent_input_tokens: int = field(default=0, init=False)
    _agent_output_tokens: int = field(default=0, init=False)
    _agent_start_time: float = field(default_factory=time.perf_counter, init=False)
    _turn_count: int = field(default=0, init=False)

    # Callbacks for integration with SpeechCascadeHandler
    _on_tts_chunk: Callable[[str], Awaitable[None]] | None = field(default=None, init=False)
    _on_agent_switch: Callable[[str, str], Awaitable[None]] | None = field(default=None, init=False)

    def __post_init__(self):
        """Initialize agent registry if not provided."""
        if not self.agents:
            self._load_agents()

        if not self.handoff_map:
            self._build_handoff_map()

        if not self._active_agent:
            self._active_agent = self.config.start_agent

        # Validate start agent exists
        if self._active_agent and self._active_agent not in self.agents:
            available = list(self.agents.keys())
            if available:
                logger.warning(
                    "Start agent '%s' not found, using '%s'",
                    self._active_agent,
                    available[0],
                )
                self._active_agent = available[0]

    def _load_agents(self) -> None:
        """Load agents from the unified agent registry with scenario support."""
        config = resolve_orchestrator_config()
        self.agents = config.agents
        self.handoff_map = config.handoff_map

        # Update start agent if scenario specifies one
        if config.has_scenario and config.start_agent:
            self.config.start_agent = config.start_agent
            self._active_agent = config.start_agent

        logger.info(
            "Loaded %d agents for cascade adapter",
            len(self.agents),
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
        handoff_provider: HandoffProvider | None = None,
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
            handoff_map: Optional pre-built handoff map (fallback if no provider)
            handoff_provider: Optional provider for session-aware handoff lookups
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

        if handoff_provider:
            adapter.set_handoff_provider(handoff_provider)

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
    def handoff_service(self) -> HandoffService:
        """
        Get the HandoffService for consistent handoff resolution.

        Lazily initialized on first access using current orchestrator state.
        Uses scenario config for handoff behavior (discrete/announced).
        """
        if not hasattr(self, "_handoff_service") or self._handoff_service is None:
            # Get scenario name from config resolver
            config = resolve_orchestrator_config()
            self._handoff_service = HandoffService(
                scenario_name=config.scenario_name,
                handoff_map=self.handoff_map,
                agents=self.agents,
                memo_manager=self._current_memo_manager,
            )
        return self._handoff_service

    def get_handoff_target(self, tool_name: str) -> str | None:
        """
        Get the target agent for a handoff tool.

        Uses HandoffService (preferred) or falls back to provider/static map.
        """
        # Use HandoffService for consistent resolution
        return self.handoff_service.get_handoff_target(tool_name)

    def set_handoff_provider(self, provider: HandoffProvider) -> None:
        """
        Set the HandoffProvider for session-aware handoff lookups.

        When set, get_handoff_target() will use the provider instead of
        the static handoff_map, enabling dynamic handoff configuration.
        """
        self._handoff_provider = provider

    def set_on_agent_switch(self, callback: Callable[[str, str], Awaitable[None]] | None) -> None:
        """
        Set callback for agent switch notifications.

        The callback receives (previous_agent, new_agent) when a handoff occurs.
        Use this to emit agent_change envelopes or update voice configuration.

        Args:
            callback: Async function(previous_agent, new_agent) -> None
        """
        self._on_agent_switch = callback

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
        return {
            "memo_manager": cm,
            "session_profile": cm.get_value_from_corememory("session_profile"),
            "caller_name": cm.get_value_from_corememory("caller_name"),
            "client_id": cm.get_value_from_corememory("client_id"),
            "customer_intelligence": cm.get_value_from_corememory("customer_intelligence"),
            "institution_name": cm.get_value_from_corememory("institution_name"),
            "active_agent": cm.get_value_from_corememory("active_agent"),
            "previous_agent": cm.get_value_from_corememory("previous_agent"),
            "visited_agents": cm.get_value_from_corememory("visited_agents"),
            "handoff_context": cm.get_value_from_corememory("handoff_context"),
        }

    # ─────────────────────────────────────────────────────────────────
    # Turn Processing
    # ─────────────────────────────────────────────────────────────────

    async def process_turn(
        self,
        context: OrchestratorContext,
        *,
        on_tts_chunk: Callable[[str], Awaitable[None]] | None = None,
        on_tool_start: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        on_tool_end: Callable[[str, Any], Awaitable[None]] | None = None,
    ) -> OrchestratorResult:
        """
        Process a conversation turn using the cascade pattern.

        Flow:
        1. Extract MemoManager from context
        2. Build messages from history + user input
        3. Call LLM with streaming
        4. Handle tool calls / handoffs
        5. Record conversation to history
        6. Sync state to MemoManager

        Args:
            context: OrchestratorContext with user input and state

            on_tts_chunk: Callback for streaming TTS chunks
            on_tool_start: Callback when tool execution starts
            on_tool_end: Callback when tool execution completes

        Returns:
            OrchestratorResult with response and metadata
        """
        self._cancel_event.clear()
        self._turn_count += 1
        self._last_user_message = context.user_text

        # Extract and preserve MemoManager reference for this turn
        self._current_memo_manager = (
            context.metadata.get("memo_manager") if context.metadata else None
        )
        turn_id = context.metadata.get("run_id", "") if context.metadata else ""

        agent = self.current_agent_config
        if not agent:
            return OrchestratorResult(
                response_text="",
                agent_name=self._active_agent,
                error=f"Agent '{self._active_agent}' not found",
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
                    "cascade.turn": self._turn_count,
                    "session.id": self.config.session_id or "",
                    "call.connection.id": self.config.call_connection_id or "",
                    "cascade.has_memo_manager": self._current_memo_manager is not None,
                },
            ) as span:
                try:
                    # Build messages
                    messages = self._build_messages(context, agent)

                    # Get tools for current agent
                    tools = agent.get_tools()

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
                        if is_handoff_tool(tool_name):
                            target_agent = self.get_handoff_target(tool_name)
                            if not target_agent:
                                logger.warning("Handoff tool '%s' not in handoff_map", tool_name)
                                continue
                            # Parse arguments - they come as JSON string from streaming
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
                                target_agent=target_agent,
                                tool_name=tool_name,
                                args=parsed_args,
                            )

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
                                logger.warning("Handoff to %s failed: %s", target_agent, handoff_result.error)
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

                            # Update context metadata for new agent
                            updated_metadata = dict(context.metadata) if context.metadata else {}
                            updated_metadata["agent_name"] = handoff_target
                            updated_metadata["previous_agent"] = (
                                context.metadata.get("agent_name") if context.metadata else None
                            )
                            updated_metadata["handoff_context"] = parsed_args.get(
                                "context"
                            ) or parsed_args.get("reason")

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
                            if not new_agent_history and context.user_text:
                                new_agent_history.append(
                                    {
                                        "role": "user",
                                        "content": context.user_text,
                                    }
                                )

                            # Build messages for new agent with its own history
                            new_context = OrchestratorContext(
                                session_id=context.session_id,
                                websocket=context.websocket,
                                call_connection_id=context.call_connection_id,
                                user_text=(
                                    "" if new_agent_history else context.user_text
                                ),  # Avoid duplicate if added above
                                conversation_history=new_agent_history,
                                metadata=updated_metadata,
                            )

                            new_messages = self._build_messages(new_context, new_agent)
                            new_tools = new_agent.get_tools()

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
                                user_for_handoff = context.user_text if not new_agent_history else None
                                self._record_turn(handoff_target, user_for_handoff, new_response_text)
                                
                                # Sync state
                                if self._current_memo_manager:
                                    self.sync_to_memo_manager(self._current_memo_manager)

                                span.set_status(Status(StatusCode.OK))

                                return OrchestratorResult(
                                    response_text=new_response_text,
                                    tool_calls=tool_calls + new_tool_calls,
                                    agent_name=self._active_agent,
                                    interrupted=self._cancel_event.is_set(),
                                    input_tokens=self._agent_input_tokens,
                                    output_tokens=self._agent_output_tokens,
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
                                    self._record_turn(handoff_target, context.user_text, handoff_greeting)
                                    
                                    if self._current_memo_manager:
                                        self.sync_to_memo_manager(self._current_memo_manager)
                                    
                                    span.set_status(Status(StatusCode.OK))
                                    return OrchestratorResult(
                                        response_text=handoff_greeting,
                                        tool_calls=tool_calls,
                                        agent_name=self._active_agent,
                                        interrupted=self._cancel_event.is_set(),
                                        input_tokens=self._agent_input_tokens,
                                        output_tokens=self._agent_output_tokens,
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
                    span.set_attributes({
                        "cascade.user_recorded": user_recorded,
                        "cascade.assistant_recorded": assistant_recorded,
                        "cascade.user_text_len": len(context.user_text or ""),
                        "cascade.response_text_len": len(response_text or ""),
                        "cascade.handoff_executed": handoff_executed,
                    })
                    span.set_status(Status(StatusCode.OK))

                    return OrchestratorResult(
                        response_text=response_text,
                        tool_calls=tool_calls,
                        agent_name=self._active_agent,
                        interrupted=self._cancel_event.is_set(),
                        input_tokens=self._agent_input_tokens,
                        output_tokens=self._agent_output_tokens,
                    )

                except asyncio.CancelledError:
                    span.set_status(Status(StatusCode.ERROR, "Cancelled"))
                    return OrchestratorResult(
                        response_text="",
                        agent_name=self._active_agent,
                        interrupted=True,
                    )
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    logger.exception("Turn processing failed: %s", e)
                    return OrchestratorResult(
                        response_text="",
                        agent_name=self._active_agent,
                        error=str(e),
                    )

    def _build_messages(
        self,
        context: OrchestratorContext,
        agent: UnifiedAgent,
    ) -> list[dict[str, Any]]:
        """Build messages for LLM request.

        Handles both simple messages (role + content) and complex messages
        (tool calls, tool results) which are stored as JSON in the content field.
        """
        messages = []

        # System prompt from agent
        system_content = agent.render_prompt(context.metadata)
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

        Uses STREAMING with async queue for low-latency TTS dispatch:
        - OpenAI stream runs in thread, puts chunks to asyncio.Queue
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
        temperature = 0.7  # Default
        top_p = 0.9  # Default
        max_tokens = 4096  # Default

        if agent:
            # Use get_model_for_mode to pick cascade_model if available, else fallback to model
            model_config = agent.get_model_for_mode("cascade")
            model_name = model_config.deployment_id or model_name
            temperature = model_config.temperature
            top_p = model_config.top_p
            max_tokens = model_config.max_tokens

        # Safety: prevent infinite tool loops
        if _iteration >= _max_iterations:
            logger.warning(
                "Tool loop reached max iterations (%d); returning current state",
                _max_iterations,
            )
            return ("", [])

        # Use existing OpenAI client
        try:
            from src.aoai.client import get_client as get_aoai_client

            client = get_aoai_client()
            if client is None:
                logger.error("AOAI client is None - not initialized")
                return ("I'm having trouble connecting to the AI service.", [])
        except ImportError as e:
            logger.error("Failed to import AOAI client: %s", e)
            return ("I'm having trouble connecting to the AI service.", [])

        response_text = ""
        tool_calls: list[dict[str, Any]] = []
        all_tool_calls: list[dict[str, Any]] = []
        output_tokens = 0

        # Create span with GenAI semantic conventions
        with tracer.start_as_current_span(
            f"invoke_agent {self._active_agent}",
            kind=SpanKind.CLIENT,
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": self._active_agent,
                "gen_ai.agent.description": f"Voice agent: {self._active_agent}",
                "gen_ai.provider.name": "azure.ai.openai",
                "gen_ai.request.model": model_name,
                "gen_ai.request.temperature": temperature,
                "gen_ai.request.top_p": top_p,
                "gen_ai.request.max_tokens": max_tokens,
                "session.id": self.config.session_id or "",
                "rt.session.id": self.config.session_id or "",
                "rt.call.connection_id": self.config.call_connection_id or "",
                "peer.service": "azure-openai",
                "component": "cascade_adapter",
                "cascade.streaming": True,
                "cascade.tool_loop_iteration": _iteration,
            },
        ) as span:
            try:
                logger.info(
                    "Starting LLM request (streaming) | agent=%s model=%s temp=%.2f iteration=%d",
                    self._active_agent,
                    model_name,
                    temperature,
                    _iteration,
                )

                # Use asyncio.Queue for thread-safe async communication
                tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
                tool_buffers: dict[str, dict[str, Any]] = {}
                collected_text: list[str] = []
                stream_error: list[Exception] = []
                loop = asyncio.get_running_loop()
                tool_call_detected = False  # Track if tool calls are streaming

                # Sentence buffer state for aggressive TTS streaming
                sentence_buffer = ""
                # Primary breaks: sentence endings
                primary_terms = ".!?"
                # Secondary breaks: natural pause points (colon, semicolon, newline)
                # Note: comma excluded to avoid breaking numbers like "100,000"
                secondary_terms = ";:\n"
                min_chunk = 15  # Minimum chars before dispatching
                max_buffer = 80  # Force dispatch if buffer exceeds this (even without breaks)

                def _put_chunk(text: str) -> None:
                    """Thread-safe put to async queue."""
                    # Don't send text to TTS if tool calls are being made
                    # The LLM sometimes outputs explanatory text alongside tool calls
                    if tool_call_detected:
                        return
                    if text and text.strip():
                        loop.call_soon_threadsafe(tts_queue.put_nowait, text.strip())

                def _streaming_completion():
                    """Run in thread - consumes OpenAI stream."""
                    nonlocal sentence_buffer, tool_call_detected
                    try:
                        logger.debug(
                            "Starting OpenAI stream | model=%s messages=%d tools=%d temp=%.2f",
                            model_name,
                            len(messages),
                            len(tools) if tools else 0,
                            temperature,
                        )
                        chunk_count = 0
                        for chunk in client.chat.completions.create(
                            model=model_name,
                            messages=messages,
                            tools=tools if tools else None,
                            stream=True,
                            timeout=60,
                            temperature=temperature,
                            top_p=top_p,
                            max_tokens=max_tokens,
                        ):
                            chunk_count += 1
                            if not getattr(chunk, "choices", None):
                                continue
                            choice = chunk.choices[0]
                            delta = getattr(choice, "delta", None)
                            if not delta:
                                continue

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
                                        fn_args = getattr(fn, "arguments", None)
                                        if fn_args:
                                            buf["arguments"] += fn_args

                            # Text content - collect but only TTS if no tool calls
                            if getattr(delta, "content", None):
                                text = delta.content
                                collected_text.append(text)
                                sentence_buffer += text

                                # Aggressive TTS streaming - dispatch as soon as we have a break point
                                while len(sentence_buffer) >= min_chunk:
                                    # First try primary breaks (sentence endings)
                                    term_idx = -1
                                    for t in primary_terms:
                                        idx = sentence_buffer.rfind(t)
                                        if idx > term_idx:
                                            term_idx = idx

                                    # If no sentence end, try secondary breaks (commas, colons, etc.)
                                    if term_idx < min_chunk - 5:
                                        for t in secondary_terms:
                                            idx = sentence_buffer.rfind(t)
                                            if idx > term_idx:
                                                term_idx = idx

                                    # If found a break point, dispatch up to it
                                    if term_idx >= min_chunk - 5:
                                        dispatch = sentence_buffer[: term_idx + 1]
                                        sentence_buffer = sentence_buffer[term_idx + 1 :]
                                        _put_chunk(dispatch)
                                    # Force dispatch if buffer is getting too long (no break point found)
                                    elif len(sentence_buffer) >= max_buffer:
                                        # Find last space to avoid cutting mid-word
                                        space_idx = sentence_buffer.rfind(" ", 0, max_buffer)
                                        if space_idx > min_chunk:
                                            dispatch = sentence_buffer[:space_idx]
                                            sentence_buffer = sentence_buffer[space_idx + 1:]
                                        else:
                                            dispatch = sentence_buffer[:max_buffer]
                                            sentence_buffer = sentence_buffer[max_buffer:]
                                        _put_chunk(dispatch)
                                    else:
                                        break

                        logger.debug("OpenAI stream completed | chunks=%d", chunk_count)
                        # Flush remaining buffer (only if no tool calls)
                        if sentence_buffer.strip():
                            _put_chunk(sentence_buffer)
                    except Exception as e:
                        logger.error("OpenAI stream error: %s", e)
                        stream_error.append(e)
                    finally:
                        # Signal end
                        loop.call_soon_threadsafe(tts_queue.put_nowait, None)

                # Start stream in thread
                stream_future = asyncio.get_running_loop().run_in_executor(
                    None, _streaming_completion
                )

                # Consume queue with timeout - don't hang forever
                llm_timeout = 90.0  # seconds
                queue_timeout = 5.0  # per-chunk timeout
                start_time = time.perf_counter()

                while True:
                    elapsed = time.perf_counter() - start_time
                    if elapsed > llm_timeout:
                        logger.error("LLM response timeout after %.1fs", elapsed)
                        break

                    try:
                        chunk = await asyncio.wait_for(tts_queue.get(), timeout=queue_timeout)
                    except TimeoutError:
                        # Check if stream is still running
                        if stream_future.done():
                            # Stream finished but didn't signal - break out
                            logger.warning("Stream finished without signaling queue end")
                            break
                        # Otherwise keep waiting
                        continue

                    if chunk is None:
                        break
                    if on_tts_chunk:
                        try:
                            await on_tts_chunk(chunk)
                        except Exception as e:
                            logger.debug("TTS callback error: %s", e)

                # Wait for stream to finish with timeout
                try:
                    await asyncio.wait_for(stream_future, timeout=10.0)
                except TimeoutError:
                    logger.error("Stream thread did not complete in time")

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

                # Estimate token usage
                output_tokens = len(response_text) // 4
                self._agent_output_tokens += output_tokens

                logger.info(
                    "LLM response (streamed) | agent=%s text_len=%d tool_calls=%d (filtered from %d) iteration=%d",
                    self._active_agent,
                    len(response_text),
                    len(tool_calls),
                    len(raw_tool_calls),
                    _iteration,
                )

                # Set GenAI semantic convention attributes
                span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                span.set_attribute("gen_ai.response.length", len(response_text))

                if tool_calls:
                    span.set_attribute("tool_call_detected", True)
                    span.set_attribute("tool_names", [tc.get("name", "") for tc in tool_calls])

                # Process tool calls if any
                non_handoff_tools = [
                    tc for tc in tool_calls if not is_handoff_tool(tc.get("name", ""))
                ]
                handoff_tools = [tc for tc in tool_calls if is_handoff_tool(tc.get("name", ""))]

                all_tool_calls.extend(tool_calls)

                # If we have handoff tools, return immediately (handoffs handled by caller)
                if handoff_tools:
                    span.set_attribute("cascade.handoff_detected", True)
                    span.set_status(Status(StatusCode.OK))
                    return response_text, all_tool_calls

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

                    tool_results_for_history: list[dict[str, Any]] = []

                    for tool_call in non_handoff_tools:
                        tool_name = tool_call.get("name", "")
                        tool_id = tool_call.get("id", "")
                        raw_args = tool_call.get("arguments", "{}")

                        if on_tool_start:
                            await on_tool_start(tool_name, raw_args)

                        result: dict[str, Any] = {"error": "Tool execution failed"}
                        if agent:
                            try:
                                args = (
                                    json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                                )
                                # Inject session context into tool args for profile-aware tools
                                # This allows tools to use already-loaded session data
                                if cm:
                                    session_profile = cm.get_value_from_corememory("session_profile")
                                    if session_profile:
                                        args["_session_profile"] = session_profile
                                result = await agent.execute_tool(tool_name, args)
                                logger.info(
                                    "Tool executed | name=%s result_keys=%s",
                                    tool_name,
                                    (
                                        list(result.keys())
                                        if isinstance(result, dict)
                                        else type(result).__name__
                                    ),
                                )

                                # Persist tool output to MemoManager for context continuity
                                if cm:
                                    try:
                                        cm.persist_tool_output(tool_name, result)
                                        # Update any slots returned by the tool
                                        if isinstance(result, dict) and "slots" in result:
                                            cm.update_slots(result["slots"])
                                    except Exception as persist_err:
                                        logger.debug(
                                            "Failed to persist tool output: %s", persist_err
                                        )

                            except Exception as e:
                                logger.error("Tool execution failed for %s: %s", tool_name, e)
                                result = {"error": str(e), "tool_name": tool_name}

                        if on_tool_end:
                            await on_tool_end(tool_name, result)

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
                        tool_results_for_history.append(tool_result_msg)

                    # Persist tool results to MemoManager for history continuity
                    if cm and tool_results_for_history:
                        try:
                            for tool_msg in tool_results_for_history:
                                cm.append_to_history(
                                    self._active_agent, "tool", json.dumps(tool_msg)
                                )
                        except Exception:
                            logger.debug("Failed to persist tool results to history", exc_info=True)

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
                response_text = "I apologize, I encountered an error processing your request."

        return response_text, all_tool_calls

    async def _dispatch_tts_chunks(
        self,
        text: str,
        on_tts_chunk: Callable[[str], Awaitable[None]],
        *,
        min_chunk: int = 40,
    ) -> None:
        """
        Emit TTS chunks in small batches to reduce latency.

        Splits by sentence boundaries when possible, otherwise falls back to
        fixed-size slices to ensure early audio playback.
        """
        try:
            segments: list[str] = []
            buf = ""
            for part in text.split():
                if buf:
                    candidate = f"{buf} {part}"
                else:
                    candidate = part
                buf = candidate
                if any(buf.endswith(p) for p in (".", "!", "?", ";")) and len(buf) >= min_chunk:
                    segments.append(buf.strip())
                    buf = ""
            if buf:
                segments.append(buf.strip())

            # Fallback: no sentence boundaries, chunk by size
            if len(segments) == 1 and len(segments[0]) > min_chunk * 2:
                s = segments.pop()
                for i in range(0, len(s), min_chunk * 2):
                    segments.append(s[i : i + min_chunk * 2].strip())

            for segment in segments:
                result = on_tts_chunk(segment)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("TTS chunk dispatch failed: %s", exc)

    async def cancel_current(self) -> None:
        """Signal cancellation for barge-in."""
        self._cancel_event.set()

    # ─────────────────────────────────────────────────────────────────
    # Handoff Management
    # ─────────────────────────────────────────────────────────────────

    async def _execute_handoff(
        self,
        target_agent: str,
        tool_name: str,
        args: dict[str, Any],
        system_vars: dict[str, Any] | None = None,
    ) -> HandoffResult:
        """
        Execute a handoff to another agent.

        Uses HandoffService for consistent resolution and greeting selection
        across both Cascade and VoiceLive orchestrators.

        Args:
            target_agent: Target agent name
            tool_name: Handoff tool that triggered the switch
            args: Tool arguments (may contain context)
            system_vars: Optional system variables for greeting selection

        Returns:
            HandoffResult with success status, handoff_type, greeting, etc.
        """
        previous_agent = self._active_agent
        is_first_visit = target_agent not in self._visited_agents

        with tracer.start_as_current_span(
            "cascade.handoff",
            kind=SpanKind.INTERNAL,
            attributes={
                "cascade.source_agent": previous_agent,
                "cascade.target_agent": target_agent,
                "cascade.tool_name": tool_name,
                "cascade.is_first_visit": is_first_visit,
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
                    target_agent=target_agent,
                    handoff_type=resolution.handoff_type,
                    error=resolution.error,
                )

            # Update state
            self._visited_agents.add(target_agent)
            self._active_agent = target_agent

            # Reset token counters for new agent
            self._agent_input_tokens = 0
            self._agent_output_tokens = 0
            self._agent_start_time = time.perf_counter()

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
            )

    # ─────────────────────────────────────────────────────────────────
    # Greeting Selection (delegates to HandoffService)
    # ─────────────────────────────────────────────────────────────────

    def _select_greeting(
        self,
        agent: UnifiedAgent,
        agent_name: str,
        system_vars: dict[str, Any],
        is_first_visit: bool,
        greet_on_switch: bool = True,
    ) -> str | None:
        """
        Select appropriate greeting for agent activation.

        Delegates to HandoffService for consistent behavior across orchestrators.

        Args:
            agent: The agent to get greeting for
            agent_name: Name of the agent (unused, kept for backward compat)
            system_vars: System variables for template rendering
            is_first_visit: Whether this is first visit to agent
            greet_on_switch: Whether to greet (from scenario config)

        Returns:
            Greeting text or None
        """
        return self.handoff_service.select_greeting(
            agent=agent,
            is_first_visit=is_first_visit,
            greet_on_switch=greet_on_switch,
            system_vars=system_vars,
        )

    async def switch_agent(
        self,
        agent_name: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """
        Programmatically switch to a different agent.

        Args:
            agent_name: Target agent name
            context: Optional handoff context

        Returns:
            True if switch succeeded
        """
        result = await self._execute_handoff(
            target_agent=agent_name,
            tool_name=f"manual_switch_{agent_name}",
            args=context or {},
        )
        return result.success

    # ─────────────────────────────────────────────────────────────────
    # MemoManager Integration
    # ─────────────────────────────────────────────────────────────────

    def sync_from_memo_manager(self, cm: MemoManager) -> None:
        """
        Sync adapter state from MemoManager.

        Call this at the start of each turn to pick up any
        state changes (e.g., handoffs set by tools), ensuring
        session context continuity.

        Args:
            cm: MemoManager instance
        """
        # Use shared sync utility
        state = sync_state_from_memo(cm, available_agents=set(self.agents.keys()))

        # Handle pending handoff (clears the pending key)
        if state.pending_handoff:
            target = state.pending_handoff.get("target_agent")
            if target and target in self.agents:
                logger.info("Pending handoff detected: %s", target)
                self._active_agent = target
                sync_state_to_memo(cm, active_agent=self._active_agent, clear_pending_handoff=True)

        # Apply synced state
        if state.active_agent:
            self._active_agent = state.active_agent
        if state.visited_agents:
            self._visited_agents = state.visited_agents
        if state.system_vars:
            self._session_vars.update(state.system_vars)

        # Restore cascade-specific state (turn count, tokens)
        turn_count = (
            cm.get_value_from_corememory("cascade_turn_count")
            if hasattr(cm, "get_value_from_corememory")
            else None
        )
        if turn_count and isinstance(turn_count, int):
            self._turn_count = turn_count

        tokens = (
            cm.get_value_from_corememory("cascade_tokens")
            if hasattr(cm, "get_value_from_corememory")
            else None
        )
        if tokens and isinstance(tokens, dict):
            self._agent_input_tokens = tokens.get("input", 0)
            self._agent_output_tokens = tokens.get("output", 0)

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

        # Persist cascade-specific state (turn count, tokens)
        if hasattr(cm, "set_corememory"):
            cm.set_corememory("cascade_turn_count", self._turn_count)
            cm.set_corememory(
                "cascade_tokens",
                {
                    "input": self._agent_input_tokens,
                    "output": self._agent_output_tokens,
                },
            )

    # ─────────────────────────────────────────────────────────────────
    # Legacy Interface for SpeechCascadeHandler
    # ─────────────────────────────────────────────────────────────────

    async def process_user_input(
        self,
        transcript: str,
        cm: MemoManager,
        *,
        on_tts_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """
        Process user input in cascade pattern.

        This is the main entry point called by SpeechCascadeHandler.
        
        Flow:
        1. Sync state from MemoManager
        2. Build history (with cross-agent context)
        3. Build context and call process_turn
        4. Fire-and-forget Redis persistence
        5. Return response

        Args:
            transcript: User's transcribed speech
            cm: MemoManager for conversation state
            on_tts_chunk: Optional callback for streaming TTS

        Returns:
            Full response text (or None if cancelled/error)
        """
        # 1. Sync orchestrator state from MemoManager
        self.sync_from_memo_manager(cm)
        
        # Store reference for use in process_turn
        self._current_memo_manager = cm

        # 2. Build conversation history using helper
        history = self._get_conversation_history(cm)

        # 3. Build context and process
        context = OrchestratorContext(
            session_id=self.config.session_id or "",
            websocket=None,
            call_connection_id=self.config.call_connection_id,
            user_text=transcript,
            conversation_history=history,
            metadata=self._build_session_context(cm),
        )

        result = await self.process_turn(context, on_tts_chunk=on_tts_chunk)

        # 4. Handle errors/interrupts
        if result.error:
            logger.error("Turn processing error: %s", result.error)
            return None
        if result.interrupted:
            return None

        # 5. Fire-and-forget Redis persistence (non-blocking)
        if hasattr(cm, "_redis_manager") and cm._redis_manager:
            asyncio.create_task(self._persist_to_redis_background(cm))

        return result.response_text

    async def _persist_to_redis_background(self, cm: MemoManager) -> None:
        """Background task to persist session state to Redis."""
        try:
            await cm.persist_to_redis_async(cm._redis_manager)
        except Exception as e:
            logger.warning("Redis persist failed: %s", e)

    def as_orchestrator_func(
        self,
    ) -> Callable[[MemoManager, str], Awaitable[str | None]]:
        """
        Return a function compatible with SpeechCascadeHandler.

        Usage:
            handler = SpeechCascadeHandler(
                orchestrator_func=adapter.as_orchestrator_func(),
                ...
            )

        Returns:
            Callable matching the legacy orchestrator signature
        """

        async def orchestrator_func(
            cm: MemoManager,
            transcript: str,
        ) -> str | None:
            return await self.process_user_input(transcript, cm)

        return orchestrator_func


# ─────────────────────────────────────────────────────────────────────
# Factory Functions
# ─────────────────────────────────────────────────────────────────────


def get_cascade_orchestrator(
    *,
    start_agent: str | None = None,
    model_name: str | None = None,
    call_connection_id: str | None = None,
    session_id: str | None = None,
    scenario_name: str | None = None,
    app_state: Any | None = None,
    **kwargs,
) -> CascadeOrchestratorAdapter:
    """
    Create a CascadeOrchestratorAdapter instance with scenario support.

    Resolution order for start_agent and agents:
    1. Explicit start_agent parameter
    2. app_state (if provided)
    3. Scenario configuration (AGENT_SCENARIO env var or scenario_name param)
    4. Default values

    Args:
        start_agent: Override initial agent name (None = auto-resolve)
        model_name: LLM deployment name (defaults to AZURE_OPENAI_DEPLOYMENT)
        call_connection_id: ACS call ID for tracing
        session_id: Session ID for tracing
        scenario_name: Override scenario name
        app_state: FastAPI app.state for pre-loaded config
        **kwargs: Additional configuration

    Returns:
        Configured CascadeOrchestratorAdapter
    """
    # Resolve configuration
    # Priority: explicit scenario_name overrides app_state preloads so per-session
    # scenarios (stored in MemoManager) take effect for cascade mode.
    if scenario_name:
        config = resolve_orchestrator_config(
            scenario_name=scenario_name,
            start_agent=start_agent,
        )
    elif app_state is not None:
        config = resolve_from_app_state(app_state)
    else:
        config = resolve_orchestrator_config(start_agent=start_agent)

    # Use resolved start_agent unless explicitly overridden
    effective_start_agent = start_agent or config.start_agent

    return CascadeOrchestratorAdapter.create(
        start_agent=effective_start_agent,
        model_name=model_name,
        call_connection_id=call_connection_id,
        session_id=session_id,
        agents=config.agents,
        handoff_map=config.handoff_map,
        streaming=True,  # Explicitly disable streaming for cascade
        **kwargs,
    )


def create_cascade_orchestrator_func(
    *,
    start_agent: str | None = None,
    call_connection_id: str | None = None,
    session_id: str | None = None,
    scenario_name: str | None = None,
    app_state: Any | None = None,
) -> Callable[[MemoManager, str], Awaitable[str | None]]:
    """
    Create an orchestrator function for SpeechCascadeHandler.

    Supports scenario-based configuration for start agent and agents.

    Usage:
        handler = SpeechCascadeHandler(
            orchestrator_func=create_cascade_orchestrator_func(
                # Let scenario determine start_agent
            ),
            ...
        )

    Args:
        start_agent: Override initial agent name (None = auto-resolve from scenario)
        call_connection_id: ACS call ID for tracing
        session_id: Session ID for tracing
        scenario_name: Override scenario name
        app_state: FastAPI app.state for pre-loaded config

    Returns:
        Orchestrator function compatible with SpeechCascadeHandler
    """
    adapter = get_cascade_orchestrator(
        start_agent=start_agent,
        call_connection_id=call_connection_id,
        session_id=session_id,
        scenario_name=scenario_name,
        app_state=app_state,
    )
    return adapter.as_orchestrator_func()


__all__ = [
    "CascadeOrchestratorAdapter",
    "CascadeConfig",
    "CascadeHandoffContext",
    "StateKeys",
    "get_cascade_orchestrator",
    "create_cascade_orchestrator_func",
]
