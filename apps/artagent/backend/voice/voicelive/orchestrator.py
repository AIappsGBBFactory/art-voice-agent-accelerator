"""
VoiceLive Orchestrator
=======================

Orchestrates agent switching and tool execution for VoiceLive multi-agent system.

All tool execution flows through the shared tool registry for centralized management:
- Handoff tools → trigger agent switching
- Business tools → execute and return results to model

Architecture:
    VoiceLiveSDKHandler
           │
           ▼
    LiveOrchestrator ─► VoiceLiveAgentAdapter registry
           │                    │
           ├─► handle_event()   └─► apply_session()
           │                        trigger_response()
           └─► _execute_tool_call() ───► shared tool registry

Usage:
    from apps.artagent.backend.voice.voicelive import (
        LiveOrchestrator,
        TRANSFER_TOOL_NAMES,
        CALL_CENTER_TRIGGER_PHRASES,
    )

    orchestrator = LiveOrchestrator(
        conn=voicelive_connection,
        agents=adapted_agents,
        handoff_map=handoff_map,
        start_agent="Concierge",
    )
    await orchestrator.start(system_vars={...})
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

# Self-contained tool registry (no legacy vlagent dependency)
from apps.artagent.backend.registries.toolstore import (
    execute_tool,
    initialize_tools,
    is_handoff_tool,
)
from apps.artagent.backend.src.services.session_loader import load_user_profile_by_client_id
from apps.artagent.backend.voice.handoffs import build_handoff_system_vars, sanitize_handoff_context
from apps.artagent.backend.voice.shared.session_state import (
    sync_state_from_memo,
    sync_state_to_memo,
)
from azure.ai.voicelive.models import (
    FunctionCallOutputItem,
    ServerEventType,
)
from opentelemetry import trace

if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.session_manager import HandoffProvider
    from src.stateful.state_managment import MemoManager

    from .agent_adapter import VoiceLiveAgentAdapter

from apps.artagent.backend.src.utils.tracing import (
    create_service_dependency_attrs,
    create_service_handler_attrs,
)
from src.enums.monitoring import GenAIOperation, GenAIProvider, SpanAttr
from utils.ml_logging import get_logger

logger = get_logger("voicelive.orchestrator")
tracer = trace.get_tracer(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

TRANSFER_TOOL_NAMES = {"transfer_call_to_destination", "transfer_call_to_call_center"}

CALL_CENTER_TRIGGER_PHRASES = {
    "transfer to call center",
    "transfer me to the call center",
}

_PAYPAL_AGENT_NAME = "PayPalAgent"
_PAYPAL_SEARCH_PREFACE_MESSAGES: tuple[str, ...] = (
    "Got it, checking now.",
    "One sec while I look.",
    "Sure, let me pull that up.",
    "Let me take a quick look.",
)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


async def _auto_load_user_context(system_vars: dict[str, Any]) -> None:
    """
    Auto-load user profile into system_vars if client_id is present but session_profile is missing.

    This ensures that agents receiving handoffs with client_id can access user context
    for personalized conversations, even if the originating agent didn't pass full profile.

    Modifies system_vars in-place.
    """
    if system_vars.get("session_profile"):
        # Already have session_profile, no need to load
        return

    client_id = system_vars.get("client_id")
    if not client_id:
        # Check handoff_context for client_id
        handoff_ctx = system_vars.get("handoff_context", {})
        client_id = handoff_ctx.get("client_id") if isinstance(handoff_ctx, dict) else None

    if not client_id:
        return

    try:
        profile = await load_user_profile_by_client_id(client_id)
        if profile:
            system_vars["session_profile"] = profile
            system_vars["client_id"] = profile.get("client_id", client_id)
            system_vars["customer_intelligence"] = profile.get("customer_intelligence", {})
            system_vars["caller_name"] = profile.get("full_name")
            if profile.get("institution_name"):
                system_vars.setdefault("institution_name", profile["institution_name"])
            logger.info(
                "🔄 Auto-loaded user context for handoff | client_id=%s name=%s",
                client_id,
                profile.get("full_name"),
            )
    except Exception as exc:
        logger.warning("Failed to auto-load user context: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════


class LiveOrchestrator:
    """
    Orchestrates agent switching and tool execution for VoiceLive multi-agent system.

    All tool execution flows through the shared tool registry for centralized management:
    - Handoff tools → trigger agent switching
    - Business tools → execute and return results to model

    GenAI Telemetry:
    - Emits invoke_agent spans for App Insights Agents blade
    - Tracks token usage per agent session
    - Records LLM TTFT (Time To First Token) metrics
    """

    def __init__(
        self,
        conn,
        agents: dict[str, VoiceLiveAgentAdapter],
        handoff_map: dict[str, str] | None = None,
        start_agent: str = "EricaConcierge",
        audio_processor=None,
        messenger=None,
        call_connection_id: str | None = None,
        *,
        transport: str = "acs",
        model_name: str | None = None,
        memo_manager: MemoManager | None = None,
        handoff_provider: HandoffProvider | None = None,
    ):
        self.conn = conn
        self.agents = agents
        # Prefer handoff_provider for live lookups; fallback to static handoff_map
        self._handoff_provider = handoff_provider
        self._handoff_map = handoff_map or {}
        self.active = start_agent
        self.audio = audio_processor
        self.messenger = messenger
        self._model_name = model_name or "gpt-4o-realtime"
        self.visited_agents: set = set()
        self._pending_greeting: str | None = None
        self._pending_greeting_agent: str | None = None
        self._last_user_message: str | None = None
        self.call_connection_id = call_connection_id
        self._call_center_triggered = False
        self._transport = transport
        self._greeting_tasks: set[asyncio.Task] = set()
        self._search_preface_index = 0
        self._active_response_id: str | None = None
        self._system_vars: dict[str, Any] = {}

        # MemoManager for session state continuity (consistent with CascadeOrchestratorAdapter)
        self._memo_manager: MemoManager | None = memo_manager

        # LLM TTFT tracking
        self._llm_turn_start_time: float | None = None
        self._llm_first_token_time: float | None = None
        self._llm_turn_number: int = 0

        # Per-agent token usage tracking
        self._agent_input_tokens: int = 0
        self._agent_output_tokens: int = 0
        self._agent_start_time: float = time.perf_counter()
        self._agent_response_count: int = 0

        if self.messenger:
            try:
                self.messenger.set_active_agent(self.active)
            except AttributeError:
                logger.debug("Messenger does not support set_active_agent", exc_info=True)

        if self.active not in self.agents:
            raise ValueError(f"Start agent '{self.active}' not found in registry")

        # Initialize the tool registry
        initialize_tools()

        # Sync state from MemoManager if available
        if self._memo_manager:
            self._sync_from_memo_manager()

    # ═══════════════════════════════════════════════════════════════════════════
    # MEMO MANAGER SYNC (consistent with CascadeOrchestratorAdapter)
    # ═══════════════════════════════════════════════════════════════════════════

    @property
    def memo_manager(self) -> MemoManager | None:
        """Return the current MemoManager instance."""
        return self._memo_manager

    def _sync_from_memo_manager(self) -> None:
        """
        Sync orchestrator state from MemoManager.
        Called at initialization and optionally at turn boundaries.

        Uses shared sync_state_from_memo for consistency with CascadeOrchestratorAdapter.
        """
        if not self._memo_manager:
            return

        # Use shared sync utility
        state = sync_state_from_memo(
            self._memo_manager,
            available_agents=set(self.agents.keys()),
        )

        # Apply synced state
        if state.active_agent:
            self.active = state.active_agent
            logger.debug("[LiveOrchestrator] Synced active_agent: %s", self.active)

        if state.visited_agents:
            self.visited_agents = state.visited_agents
            logger.debug("[LiveOrchestrator] Synced visited_agents: %s", self.visited_agents)

        if state.system_vars:
            self._system_vars.update(state.system_vars)
            logger.debug("[LiveOrchestrator] Synced system_vars")

        # Handle pending handoff if any
        if state.pending_handoff:
            target = state.pending_handoff.get("target_agent")
            if target and target in self.agents:
                logger.info("[LiveOrchestrator] Pending handoff detected: %s", target)
                self.active = target
                # Clear the pending handoff
                sync_state_to_memo(
                    self._memo_manager, active_agent=self.active, clear_pending_handoff=True
                )

    def _sync_to_memo_manager(self) -> None:
        """
        Sync orchestrator state back to MemoManager.
        Called at turn boundaries to persist state.

        Uses shared sync_state_to_memo for consistency with CascadeOrchestratorAdapter.
        """
        if not self._memo_manager:
            return

        # Use shared sync utility
        sync_state_to_memo(
            self._memo_manager,
            active_agent=self.active,
            visited_agents=self.visited_agents,
            system_vars=self._system_vars,
        )

        # Sync last user message (VoiceLive-specific)
        if hasattr(self._memo_manager, "last_user_message") and self._last_user_message:
            self._memo_manager.last_user_message = self._last_user_message

        logger.debug("[LiveOrchestrator] Synced state to MemoManager")

    # ═══════════════════════════════════════════════════════════════════════════
    # HANDOFF RESOLUTION
    # ═══════════════════════════════════════════════════════════════════════════

    def get_handoff_target(self, tool_name: str) -> str | None:
        """
        Get the target agent for a handoff tool.

        Prefers HandoffProvider (live lookup) over static handoff_map.
        This allows session-level handoff_map updates to take effect.
        """
        if self._handoff_provider:
            return self._handoff_provider.get_handoff_target(tool_name)
        return self._handoff_map.get(tool_name)

    @property
    def handoff_map(self) -> dict[str, str]:
        """
        Get the current handoff map (for backward compatibility).

        Returns a copy if using HandoffProvider, or the static map.
        """
        if self._handoff_provider:
            return self._handoff_provider.handoff_map
        return self._handoff_map

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════════════

    async def start(self, system_vars: dict | None = None):
        """Apply initial agent session and trigger an intro response."""
        with tracer.start_as_current_span(
            "voicelive_orchestrator.start",
            kind=trace.SpanKind.INTERNAL,
            attributes=create_service_handler_attrs(
                service_name="LiveOrchestrator.start",
                call_connection_id=self.call_connection_id,
                session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
            ),
        ) as start_span:
            start_span.set_attribute("voicelive.start_agent", self.active)
            start_span.set_attribute("voicelive.agent_count", len(self.agents))
            logger.info("[Orchestrator] Starting with agent: %s", self.active)
            self._system_vars = dict(system_vars or {})
            await self._switch_to(self.active, self._system_vars)
            start_span.set_status(trace.StatusCode.OK)

    async def handle_event(self, event):
        """Route VoiceLive events to audio + handoff logic."""
        et = event.type

        if et == ServerEventType.SESSION_UPDATED:
            await self._handle_session_updated(event)

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            await self._handle_speech_started()

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            await self._handle_speech_stopped()

        elif et == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            await self._handle_transcription_completed(event)

        elif et == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA:
            await self._handle_transcription_delta(event)

        elif et == ServerEventType.RESPONSE_AUDIO_DELTA:
            if self.audio:
                await self.audio.queue_audio(event.delta)

        elif et == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
            await self._handle_transcript_delta(event)

        elif et == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            await self._handle_transcript_done(event)

        elif et == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            await self._execute_tool_call(
                call_id=getattr(event, "call_id", None),
                name=getattr(event, "name", None),
                args_json=getattr(event, "arguments", None),
            )

        elif et == ServerEventType.RESPONSE_DONE:
            await self._handle_response_done(event)

        elif et == ServerEventType.ERROR:
            logger.error("VoiceLive error: %s", getattr(event.error, "message", "unknown"))

    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_session_updated(self, event) -> None:
        """Handle SESSION_UPDATED event."""
        session_obj = getattr(event, "session", None)
        session_id = getattr(session_obj, "id", "unknown") if session_obj else "unknown"
        voice_info = getattr(session_obj, "voice", None) if session_obj else None
        logger.info("Session ready: %s | voice=%s", session_id, voice_info)

        if self.messenger:
            try:
                await self.messenger.send_session_update(
                    agent_name=self.active,
                    session_obj=session_obj,
                    transport=self._transport,
                )
            except Exception:
                logger.debug("Failed to emit session update envelope", exc_info=True)

        if self.audio:
            await self.audio.stop_playback()
        try:
            await self.conn.response.cancel()
        except Exception:
            logger.debug("response.cancel() failed during session_ready", exc_info=True)
        if self.audio:
            await self.audio.start_capture()

        if self._pending_greeting and self._pending_greeting_agent == self.active:
            self._cancel_pending_greeting_tasks()
            try:
                await self.agents[self.active].trigger_response(
                    self.conn,
                    say=self._pending_greeting,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "[Greeting] Session-ready trigger failed; retrying via fallback", exc_info=True
                )
                self._schedule_greeting_fallback(self.active)
            else:
                self._pending_greeting = None
                self._pending_greeting_agent = None

    async def _handle_speech_started(self) -> None:
        """Handle user speech started (barge-in)."""
        logger.debug("User speech started → cancel current response")
        if self.audio:
            await self.audio.stop_playback()
        try:
            await self.conn.response.cancel()
        except Exception:
            logger.debug("response.cancel() failed during barge-in", exc_info=True)
        if self.messenger and self._active_response_id:
            try:
                await self.messenger.send_assistant_cancelled(
                    response_id=self._active_response_id,
                    sender=self.active,
                    reason="user_barge_in",
                )
            except Exception:
                logger.debug("Failed to notify assistant cancellation on barge-in", exc_info=True)
        self._active_response_id = None

    async def _handle_speech_stopped(self) -> None:
        """Handle user speech stopped."""
        logger.debug("User speech stopped → start playback for assistant")
        if self.audio:
            await self.audio.start_playback()

        self._llm_turn_number += 1
        self._llm_turn_start_time = time.perf_counter()
        self._llm_first_token_time = None

    async def _handle_transcription_completed(self, event) -> None:
        """Handle user transcription completed."""
        user_transcript = getattr(event, "transcript", "")
        if user_transcript:
            logger.info("[USER] Says: %s", user_transcript)
            self._last_user_message = user_transcript.strip()
            await self._maybe_trigger_call_center_transfer(user_transcript)

    async def _handle_transcription_delta(self, event) -> None:
        """Handle user transcription delta."""
        user_transcript = getattr(event, "transcript", "")
        if user_transcript:
            logger.info("[USER delta] Says: %s", user_transcript)
            self._last_user_message = user_transcript.strip()

    async def _handle_transcript_delta(self, event) -> None:
        """Handle assistant transcript delta (streaming)."""
        transcript_delta = getattr(event, "delta", "") or getattr(event, "transcript", "")

        # Track LLM TTFT
        if self._llm_turn_start_time and self._llm_first_token_time is None and transcript_delta:
            self._llm_first_token_time = time.perf_counter()
            ttft_ms = (self._llm_first_token_time - self._llm_turn_start_time) * 1000

            session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
            with tracer.start_as_current_span(
                "voicelive.llm.ttft",
                kind=trace.SpanKind.INTERNAL,
                attributes={
                    SpanAttr.TURN_NUMBER.value: self._llm_turn_number,
                    SpanAttr.TURN_LLM_TTFB_MS.value: ttft_ms,
                    SpanAttr.SESSION_ID.value: session_id or "",
                    SpanAttr.CALL_CONNECTION_ID.value: self.call_connection_id or "",
                    "voicelive.active_agent": self.active,
                },
            ) as ttft_span:
                ttft_span.add_event("llm.first_token", {"ttft_ms": ttft_ms})
                logger.info(
                    "[Orchestrator] LLM TTFT | turn=%d ttft_ms=%.2f agent=%s",
                    self._llm_turn_number,
                    ttft_ms,
                    self.active,
                )

        if transcript_delta and self.messenger:
            response_id = self._response_id_from_event(event)
            if response_id:
                self._active_response_id = response_id
            else:
                response_id = self._active_response_id
            try:
                await self.messenger.send_assistant_streaming(
                    transcript_delta,
                    sender=self.active,
                    response_id=response_id,
                )
            except Exception:
                logger.debug("Failed to relay assistant streaming delta", exc_info=True)

    async def _handle_transcript_done(self, event) -> None:
        """Handle assistant transcript complete."""
        full_transcript = getattr(event, "transcript", "")
        if full_transcript:
            logger.info("[%s] Agent: %s", self.active, full_transcript)
            if self.messenger:
                response_id = self._response_id_from_event(event)
                if not response_id:
                    response_id = self._active_response_id
                try:
                    await self.messenger.send_assistant_message(
                        full_transcript,
                        sender=self.active,
                        response_id=response_id,
                    )
                except Exception:
                    logger.debug(
                        "Failed to relay assistant transcript to session UI", exc_info=True
                    )
                if response_id and response_id == self._active_response_id:
                    self._active_response_id = None

    async def _handle_response_done(self, event) -> None:
        """Handle response complete."""
        logger.debug("Response complete")
        response_id = self._response_id_from_event(event)
        if response_id and response_id == self._active_response_id:
            self._active_response_id = None

        self._emit_model_metrics(event)

        # Sync state to MemoManager at turn boundary
        self._sync_to_memo_manager()

    # ═══════════════════════════════════════════════════════════════════════════
    # AGENT SWITCHING
    # ═══════════════════════════════════════════════════════════════════════════

    async def _switch_to(self, agent_name: str, system_vars: dict):
        """Switch to a different agent and apply its session configuration."""
        previous_agent = self.active
        agent = self.agents[agent_name]

        # Emit invoke_agent summary span for the outgoing agent
        if previous_agent != agent_name and self._agent_response_count > 0:
            self._emit_agent_summary_span(previous_agent)

        with tracer.start_as_current_span(
            "voicelive_orchestrator.switch_agent",
            kind=trace.SpanKind.INTERNAL,
            attributes=create_service_handler_attrs(
                service_name="LiveOrchestrator._switch_to",
                call_connection_id=self.call_connection_id,
                session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
            ),
        ) as switch_span:
            switch_span.set_attribute("voicelive.previous_agent", previous_agent)
            switch_span.set_attribute("voicelive.target_agent", agent_name)

            self._cancel_pending_greeting_tasks()

            system_vars = dict(system_vars or {})
            system_vars.setdefault("previous_agent", previous_agent)
            system_vars.setdefault("active_agent", agent.name)

            is_first_visit = agent_name not in self.visited_agents
            self.visited_agents.add(agent_name)
            switch_span.set_attribute("voicelive.is_first_visit", is_first_visit)

            logger.info(
                "[Agent Switch] %s → %s | Context: %s | First visit: %s",
                previous_agent,
                agent_name,
                system_vars,
                is_first_visit,
            )

            greeting = self._select_pending_greeting(
                agent=agent,
                agent_name=agent_name,
                system_vars=system_vars,
                is_first_visit=is_first_visit,
            )
            if greeting:
                self._pending_greeting = greeting
                self._pending_greeting_agent = agent_name
            else:
                self._pending_greeting = None
                self._pending_greeting_agent = None

            handoff_context = sanitize_handoff_context(system_vars.get("handoff_context"))
            if handoff_context:
                system_vars["handoff_context"] = handoff_context
                for key in (
                    "caller_name",
                    "client_id",
                    "institution_name",
                    "service_type",
                    "case_id",
                    "issue_summary",
                    "details",
                    "handoff_reason",
                    "user_last_utterance",
                ):
                    if key not in system_vars and handoff_context.get(key) is not None:
                        system_vars[key] = handoff_context.get(key)

            # Include slots and tool outputs from MemoManager for context continuity
            if self._memo_manager:
                slots = self._memo_manager.get_context("slots", {})
                if slots:
                    system_vars.setdefault("slots", slots)
                    # Also merge collected info directly for easier template access
                    system_vars.setdefault("collected_information", slots)

                tool_outputs = self._memo_manager.get_context("tool_outputs", {})
                if tool_outputs:
                    system_vars.setdefault("tool_outputs", tool_outputs)

            # Auto-load user profile if client_id is present but session_profile is missing
            await _auto_load_user_context(system_vars)

            self.active = agent_name

            try:
                if self.messenger:
                    try:
                        self.messenger.set_active_agent(agent_name)
                    except AttributeError:
                        logger.debug("Messenger does not support set_active_agent", exc_info=True)

                has_handoff = bool(system_vars.get("handoff_context"))
                switch_span.set_attribute("voicelive.is_handoff", has_handoff)

                # For handoffs, DON'T use the handoff_message as a greeting.
                # The handoff_message is meant for the OLD agent to say ("I'll connect you to...")
                # but by the time we're here, the session has switched to the NEW agent.
                # Instead, let the new agent respond naturally as itself.
                # We'll trigger a response after session update, and the new agent will introduce itself.

                with tracer.start_as_current_span(
                    "voicelive.agent.apply_session",
                    kind=trace.SpanKind.SERVER,
                    attributes=create_service_dependency_attrs(
                        source_service="voicelive_orchestrator",
                        target_service="azure_voicelive",
                        call_connection_id=self.call_connection_id,
                        session_id=(
                            getattr(self.messenger, "session_id", None) if self.messenger else None
                        ),
                    ),
                ) as session_span:
                    session_span.set_attribute("voicelive.agent_name", agent_name)
                    session_id = (
                        getattr(self.messenger, "session_id", None) if self.messenger else None
                    )
                    await agent.apply_session(
                        self.conn,
                        system_vars=system_vars,
                        say=None,
                        session_id=session_id,
                        call_connection_id=self.call_connection_id,
                    )

                # Schedule greeting fallback if we have a pending greeting
                # This applies to both handoffs and normal agent switches
                if self._pending_greeting and self._pending_greeting_agent == agent_name:
                    self._schedule_greeting_fallback(agent_name)

                # Reset token counters for the new agent
                self._agent_input_tokens = 0
                self._agent_output_tokens = 0
                self._agent_start_time = time.perf_counter()
                self._agent_response_count = 0

                switch_span.set_status(trace.StatusCode.OK)
            except Exception as ex:
                switch_span.set_status(trace.StatusCode.ERROR, str(ex))
                switch_span.add_event(
                    "agent_switch.error",
                    {"error.type": type(ex).__name__, "error.message": str(ex)},
                )
                logger.exception("Failed to apply session for agent '%s'", agent_name)
                raise

            logger.info("[Active Agent] %s is now active", self.active)

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOL EXECUTION
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_tool_call(
        self, call_id: str | None, name: str | None, args_json: str | None
    ) -> bool:
        """
        Execute tool call via shared tool registry and send result back to model.

        Returns True if this was a handoff (agent switch), False otherwise.
        """
        if not name or not call_id:
            logger.warning("Missing call_id or name for function call")
            return False

        try:
            args = json.loads(args_json) if args_json else {}
        except Exception:
            logger.warning("Could not parse tool arguments for '%s'; using empty dict", name)
            args = {}

        session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
        with tracer.start_as_current_span(
            f"execute_tool {name}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                "component": "voicelive",
                "ai.session.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: self.call_connection_id or "",
                "transport.type": self._transport.upper() if self._transport else "ACS",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.EXECUTE_TOOL,
                SpanAttr.GENAI_TOOL_NAME.value: name,
                SpanAttr.GENAI_TOOL_CALL_ID.value: call_id,
                SpanAttr.GENAI_TOOL_TYPE.value: "function",
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                "tool.call_id": call_id,
                "tool.parameters_count": len(args),
                "voicelive.tool_name": name,
                "voicelive.tool_id": call_id,
                "voicelive.agent_name": self.active,
                "voicelive.is_acs": self._transport == "acs",
                "voicelive.args_length": len(args_json) if args_json else 0,
                "voicelive.tool.is_handoff": is_handoff_tool(name),
                "voicelive.tool.is_transfer": name in TRANSFER_TOOL_NAMES,
            },
        ) as tool_span:

            if name in TRANSFER_TOOL_NAMES:
                if (
                    self._transport_supports_acs()
                    and (not args.get("call_connection_id"))
                    and self.call_connection_id
                ):
                    args.setdefault("call_connection_id", self.call_connection_id)
                if (
                    self._transport_supports_acs()
                    and (not args.get("call_connection_id"))
                    and self.messenger
                ):
                    fallback_call_id = getattr(self.messenger, "call_id", None)
                    if fallback_call_id:
                        args.setdefault("call_connection_id", fallback_call_id)
                if self.messenger:
                    sess_id = getattr(self.messenger, "session_id", None)
                    if sess_id:
                        args.setdefault("session_id", sess_id)

            logger.info("Executing tool: %s with args: %s", name, args)

            notify_status = "success"
            notify_error: str | None = None

            await self._maybe_emit_paypal_search_preface(name)

            last_user_message = (self._last_user_message or "").strip()
            if is_handoff_tool(name) and last_user_message:
                for field in ("details", "issue_summary", "summary", "topic", "handoff_reason"):
                    if not args.get(field):
                        args[field] = last_user_message
                args.setdefault("user_last_utterance", last_user_message)

            MFA_TOOL_NAMES = {"send_mfa_code", "resend_mfa_code"}

            if self.messenger:
                try:
                    await self.messenger.notify_tool_start(call_id=call_id, name=name, args=args)
                except Exception:
                    logger.debug("Tool start messenger notification failed", exc_info=True)
                if name in MFA_TOOL_NAMES:
                    try:
                        await self.messenger.send_status_update(
                            text="Sending a verification code to your email…",
                            sender=self.active,
                            event_label="mfa_status_update",
                        )
                    except Exception:
                        logger.debug("Failed to emit MFA status update", exc_info=True)

            start_ts = time.perf_counter()
            result: dict[str, Any] = {}

            try:
                with tracer.start_as_current_span(
                    "voicelive.tool.execute",
                    kind=trace.SpanKind.INTERNAL,
                    attributes={"tool.name": name},
                ):
                    result = await execute_tool(name, args)
            except Exception as exc:
                notify_status = "error"
                notify_error = str(exc)
                tool_span.set_status(trace.StatusCode.ERROR, str(exc))
                tool_span.add_event(
                    "tool.execution_error",
                    {"error.type": type(exc).__name__, "error.message": str(exc)},
                )
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status="error",
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            error=notify_error,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)
                raise

            elapsed_ms = (time.perf_counter() - start_ts) * 1000
            tool_span.set_attribute("execution.duration_ms", elapsed_ms)
            tool_span.set_attribute("voicelive.tool.elapsed_ms", elapsed_ms)

            error_payload: str | None = None
            execution_success = True
            if isinstance(result, dict):
                for key in ("success", "ok", "authenticated"):
                    if key in result and not result[key]:
                        notify_status = "error"
                        execution_success = False
                        break
                if notify_status == "error":
                    err_val = result.get("message") or result.get("error")
                    if err_val:
                        error_payload = str(err_val)

            tool_span.set_attribute("execution.success", execution_success)
            tool_span.set_attribute("result.type", type(result).__name__ if result else "None")
            tool_span.set_attribute("voicelive.tool.status", notify_status)

            # Handle transfer tools
            if (
                name in TRANSFER_TOOL_NAMES
                and notify_status != "error"
                and isinstance(result, dict)
            ):
                takeover_message = result.get("message") or "Transferring call to destination."
                tool_span.add_event(
                    "tool.transfer_initiated",
                    {"transfer.message": takeover_message[:100] if takeover_message else ""},
                )
                if self.messenger:
                    try:
                        await self.messenger.send_status_update(
                            text=takeover_message,
                            sender=self.active,
                            event_label="acs_call_transfer_status",
                        )
                    except Exception:
                        logger.debug("Failed to emit transfer status update", exc_info=True)
                try:
                    if result.get("should_interrupt_playback", True):
                        await self.conn.response.cancel()
                except Exception:
                    logger.debug("response.cancel() failed during transfer", exc_info=True)
                if self.audio:
                    try:
                        await self.audio.stop_playback()
                    except Exception:
                        logger.debug("Audio stop playback failed during transfer", exc_info=True)
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status=notify_status,
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            result=result,
                            error=error_payload,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)
                tool_span.set_status(trace.StatusCode.OK)
                return False

            # Handle handoff tools
            if is_handoff_tool(name):
                target = self.get_handoff_target(name)
                if not target:
                    logger.warning("Handoff tool '%s' not in handoff_map", name)
                    notify_status = "error"
                    tool_span.set_status(trace.StatusCode.ERROR, "handoff_target_missing")
                    if self.messenger:
                        try:
                            await self.messenger.notify_tool_end(
                                call_id=call_id,
                                name=name,
                                status=notify_status,
                                elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                                result=result if isinstance(result, dict) else None,
                                error="handoff_target_missing",
                            )
                        except Exception:
                            logger.debug("Tool end messenger notification failed", exc_info=True)
                    return False

                tool_span.set_attribute("voicelive.handoff.target_agent", target)
                tool_span.add_event("tool.handoff_triggered", {"target_agent": target})

                # CRITICAL: Cancel any ongoing response from the OLD agent immediately.
                # This prevents the old agent from saying "I'll connect you..." while
                # the session switches to the new agent.
                try:
                    await self.conn.response.cancel()
                    logger.debug("[Handoff] Cancelled old agent response before switch")
                except Exception:
                    pass  # No active response to cancel

                # Stop audio playback to prevent old agent's voice from continuing
                if self.audio:
                    try:
                        await self.audio.stop_playback()
                    except Exception:
                        logger.debug("[Handoff] Audio stop failed", exc_info=True)

                # Use shared helper to build consistent handoff context
                ctx = build_handoff_system_vars(
                    source_agent=self.active,
                    target_agent=target,
                    tool_result=result if isinstance(result, dict) else {},
                    tool_args=args,
                    current_system_vars=self._system_vars,
                    user_last_utterance=last_user_message,
                )

                logger.info("[Handoff Tool] '%s' triggered | %s → %s", name, self.active, target)

                await self._switch_to(target, ctx)
                self._last_user_message = None

                if result.get("call_center_transfer"):
                    transfer_args: dict[str, Any] = {}
                    if self._transport_supports_acs() and self.call_connection_id:
                        transfer_args["call_connection_id"] = self.call_connection_id
                    if self.messenger:
                        sess_id = getattr(self.messenger, "session_id", None)
                        if sess_id:
                            transfer_args["session_id"] = sess_id
                    if transfer_args:
                        self._call_center_triggered = True
                        await self._trigger_call_center_transfer(transfer_args)
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status=notify_status,
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            result=result if isinstance(result, dict) else None,
                            error=error_payload,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)

                # After handoff, send tool result back to model
                # The session update from _switch_to already applied the new agent's config
                try:
                    handoff_output = FunctionCallOutputItem(
                        call_id=call_id,
                        output=(
                            json.dumps(result)
                            if isinstance(result, dict)
                            else json.dumps({"success": True})
                        ),
                    )
                    await self.conn.conversation.item.create(item=handoff_output)
                    logger.debug("Created handoff tool output for call_id=%s", call_id)
                except Exception as item_err:
                    logger.warning("Failed to create handoff tool output: %s", item_err)

                # Trigger the new agent to respond naturally as itself
                # Build context about the handoff for the new agent's instruction
                handoff_ctx = ctx.get("handoff_context", {})
                user_question = (
                    handoff_ctx.get("question")
                    or handoff_ctx.get("details")
                    or last_user_message
                    or "general inquiry"
                )
                handoff_summary = (
                    result.get("handoff_summary", "") if isinstance(result, dict) else ""
                )
                previous_agent = self._system_vars.get("previous_agent", "previous agent")

                # Schedule response trigger after a brief delay to let session settle.
                # The new agent will respond naturally to the context.
                async def _trigger_handoff_response():
                    await asyncio.sleep(0.25)
                    try:
                        # Don't use trigger_response with say= for handoffs.
                        # Instead, create a response.create() so the new agent
                        # responds naturally using its own personality and instructions.
                        # The session has already been updated with the new agent's config.
                        from azure.ai.voicelive.models import (
                            ClientEventResponseCreate,
                            ResponseCreateParams,
                        )

                        # Give the new agent context about the handoff
                        handoff_instruction = (
                            f"You just received a transfer from {previous_agent}. "
                            f'The customer\'s request: "{user_question}". '
                            f"Briefly greet them and address their request directly."
                        )
                        if handoff_summary:
                            handoff_instruction += f" Context: {handoff_summary}"

                        await self.conn.send(
                            ClientEventResponseCreate(
                                response=ResponseCreateParams(
                                    instructions=handoff_instruction,
                                )
                            )
                        )
                        logger.info(
                            "[Handoff] Triggered new agent '%s' to respond naturally", target
                        )
                    except Exception as e:
                        logger.warning("[Handoff] Failed to trigger response: %s", e)

                asyncio.create_task(_trigger_handoff_response(), name=f"handoff-response-{target}")

                tool_span.set_status(trace.StatusCode.OK)
                return True

            else:
                # Business tool - send result back to model
                output_item = FunctionCallOutputItem(
                    call_id=call_id,
                    output=json.dumps(result),
                )

                with tracer.start_as_current_span(
                    "voicelive.conversation.item_create",
                    kind=trace.SpanKind.SERVER,
                    attributes=create_service_dependency_attrs(
                        source_service="voicelive_orchestrator",
                        target_service="azure_voicelive",
                        call_connection_id=self.call_connection_id,
                        session_id=(
                            getattr(self.messenger, "session_id", None) if self.messenger else None
                        ),
                    ),
                ):
                    await self.conn.conversation.item.create(item=output_item)
                logger.debug("Created function_call_output item for call_id=%s", call_id)

                with tracer.start_as_current_span(
                    "voicelive.response.create",
                    kind=trace.SpanKind.SERVER,
                    attributes=create_service_dependency_attrs(
                        source_service="voicelive_orchestrator",
                        target_service="azure_voicelive",
                        call_connection_id=self.call_connection_id,
                        session_id=(
                            getattr(self.messenger, "session_id", None) if self.messenger else None
                        ),
                    ),
                ):
                    await self.conn.response.create()
                if self.messenger:
                    try:
                        await self.messenger.notify_tool_end(
                            call_id=call_id,
                            name=name,
                            status=notify_status,
                            elapsed_ms=(time.perf_counter() - start_ts) * 1000,
                            result=result if isinstance(result, dict) else None,
                            error=error_payload,
                        )
                    except Exception:
                        logger.debug("Tool end messenger notification failed", exc_info=True)
                tool_span.set_status(trace.StatusCode.OK)
                return False

    # ═══════════════════════════════════════════════════════════════════════════
    # GREETING HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _select_pending_greeting(
        self,
        *,
        agent: VoiceLiveAgentAdapter,
        agent_name: str,
        system_vars: dict,
        is_first_visit: bool,
    ) -> str | None:
        """
        Return a contextual greeting the agent should deliver once the session is ready.

        Uses the same context-aware rendering as Speech Cascade mode for consistency.
        Context variables (caller_name, institution_name, customer_intelligence, etc.)
        are passed to the greeting template for personalization.
        """
        # Priority 1: Explicit greeting override in system_vars
        explicit = system_vars.get("greeting")
        if not explicit:
            overrides = system_vars.get("session_overrides")
            if isinstance(overrides, dict):
                explicit = overrides.get("greeting")
        if explicit:
            return explicit.strip() or None

        # Check for handoff context
        handoff_context = system_vars.get("handoff_context") or {}
        has_handoff = bool(
            handoff_context
            or system_vars.get("handoff_message")
            or system_vars.get("handoff_reason")
        )

        # For handoffs (seamless continuation), skip automatic greeting
        # The new agent will respond naturally to the context
        if has_handoff:
            return None

        # Priority 2: Render greeting/return_greeting with full session context
        # This is consistent with Speech Cascade's _derive_default_greeting behavior
        greeting_context = self._build_greeting_context(system_vars, handoff_context)

        logger.debug(
            "[Greeting] Building greeting for %s | first_visit=%s | context keys=%s | caller_name=%s",
            agent_name,
            is_first_visit,
            list(greeting_context.keys()),
            greeting_context.get("caller_name"),
        )

        if is_first_visit:
            rendered = agent.render_greeting(greeting_context)
            logger.info(
                "[Greeting] Rendered first-visit greeting for %s | has_caller=%s | greeting_len=%d",
                agent_name,
                bool(greeting_context.get("caller_name")),
                len(rendered) if rendered else 0,
            )
            return (rendered or "").strip() or None
        else:
            rendered = agent.render_return_greeting(greeting_context)
            return (rendered or "Welcome back! How can I help you?").strip()

    def _build_greeting_context(
        self,
        system_vars: dict,
        handoff_context: dict | None = None,
    ) -> dict[str, Any]:
        """
        Build context dict for greeting template rendering.

        Extracts relevant variables from system_vars and handoff_context
        to pass to Jinja2 templates. This ensures consistent context
        with Speech Cascade mode's greeting rendering.
        """
        context: dict[str, Any] = {}

        # Core identity fields
        for key in (
            "caller_name",
            "client_id",
            "institution_name",
            "customer_intelligence",
            "session_profile",
            "relationship_tier",
            "active_agent",
            "previous_agent",
            "agent_name",
        ):
            if system_vars.get(key) is not None:
                context[key] = system_vars[key]

        # Extract from handoff_context if available
        if handoff_context and isinstance(handoff_context, dict):
            for key in ("caller_name", "client_id", "institution_name", "customer_intelligence"):
                if key not in context and handoff_context.get(key) is not None:
                    context[key] = handoff_context[key]

        # Extract from session_profile if available
        session_profile = system_vars.get("session_profile")
        if session_profile and isinstance(session_profile, dict):
            if "caller_name" not in context and session_profile.get("full_name"):
                context["caller_name"] = session_profile["full_name"]
            if "client_id" not in context and session_profile.get("client_id"):
                context["client_id"] = session_profile["client_id"]
            if "customer_intelligence" not in context and session_profile.get(
                "customer_intelligence"
            ):
                context["customer_intelligence"] = session_profile["customer_intelligence"]
            if "institution_name" not in context and session_profile.get("institution_name"):
                context["institution_name"] = session_profile["institution_name"]

        return context

    def _cancel_pending_greeting_tasks(self) -> None:
        if not self._greeting_tasks:
            return
        for task in list(self._greeting_tasks):
            task.cancel()
        self._greeting_tasks.clear()

    def _schedule_greeting_fallback(self, agent_name: str) -> None:
        if not self._pending_greeting or not self._pending_greeting_agent:
            return

        async def _fallback() -> None:
            try:
                await asyncio.sleep(0.35)
                if self._pending_greeting and self._pending_greeting_agent == agent_name:
                    logger.debug(
                        "[GreetingFallback] Triggering fallback introduction for %s", agent_name
                    )
                    try:
                        await self.agents[agent_name].trigger_response(
                            self.conn,
                            say=self._pending_greeting,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.debug("[GreetingFallback] Failed to deliver greeting", exc_info=True)
                        return
                    self._pending_greeting = None
                    self._pending_greeting_agent = None
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("[GreetingFallback] Unexpected error in fallback task", exc_info=True)

        task = asyncio.create_task(
            _fallback(),
            name=f"voicelive-greeting-fallback-{agent_name}",
        )
        task.add_done_callback(lambda t: self._greeting_tasks.discard(t))
        self._greeting_tasks.add(task)

    # ═══════════════════════════════════════════════════════════════════════════
    # CALL CENTER TRANSFER
    # ═══════════════════════════════════════════════════════════════════════════

    async def _maybe_trigger_call_center_transfer(self, transcript: str) -> None:
        """Detect trigger phrases and initiate automatic call center transfer."""
        if self._call_center_triggered:
            return

        normalized = transcript.strip().lower()
        if not normalized:
            return

        if not any(phrase in normalized for phrase in CALL_CENTER_TRIGGER_PHRASES):
            return

        self._call_center_triggered = True
        logger.info(
            "[Auto Transfer] Triggering call center transfer due to phrase match: '%s'", transcript
        )

        args: dict[str, Any] = {}
        if self._transport_supports_acs() and self.call_connection_id:
            args["call_connection_id"] = self.call_connection_id
        if self.messenger:
            session_id = getattr(self.messenger, "session_id", None)
            if session_id:
                args["session_id"] = session_id

        await self._trigger_call_center_transfer(args)

    async def _trigger_call_center_transfer(self, args: dict[str, Any]) -> None:
        """Invoke the call center transfer tool and handle playback cleanup."""
        tool_name = "transfer_call_to_call_center"

        if self.messenger:
            try:
                await self.messenger.send_status_update(
                    text="Routing you to a call center representative…",
                    sender=self.active,
                    event_label="acs_call_transfer_status",
                )
            except Exception:
                logger.debug("Failed to emit pre-transfer status update", exc_info=True)

        try:
            result = await execute_tool(tool_name, args)
        except Exception:
            self._call_center_triggered = False
            logger.exception("Automatic call center transfer failed unexpectedly")
            if self.messenger:
                try:
                    await self.messenger.send_status_update(
                        text="We encountered an issue reaching the call center. Staying with the virtual agent for now.",
                        sender=self.active,
                        event_label="acs_call_transfer_status",
                    )
                except Exception:
                    logger.debug("Failed to emit transfer failure status", exc_info=True)
            return

        if not isinstance(result, dict) or not result.get("success"):
            self._call_center_triggered = False
            error_message = None
            if isinstance(result, dict):
                error_message = result.get("message") or result.get("error")
            logger.warning(
                "Automatic call center transfer request was rejected | result=%s", result
            )
            if self.messenger:
                try:
                    await self.messenger.send_status_update(
                        text=error_message
                        or "Unable to reach the call center right now. I'll stay on the line with you.",
                        sender=self.active,
                        event_label="acs_call_transfer_status",
                    )
                except Exception:
                    logger.debug("Failed to emit transfer rejection status", exc_info=True)
            return

        takeover_message = result.get(
            "message", "Routing you to a live call center representative now."
        )

        if self.messenger:
            try:
                await self.messenger.send_status_update(
                    text=takeover_message,
                    sender=self.active,
                    event_label="acs_call_transfer_status",
                )
            except Exception:
                logger.debug("Failed to emit transfer success status", exc_info=True)

        try:
            if result.get("should_interrupt_playback", True):
                await self.conn.response.cancel()
        except Exception:
            logger.debug(
                "response.cancel() failed during automatic call center transfer", exc_info=True
            )

        if self.audio:
            try:
                await self.audio.stop_playback()
            except Exception:
                logger.debug(
                    "Audio stop playback failed during automatic call center transfer",
                    exc_info=True,
                )

    # ═══════════════════════════════════════════════════════════════════════════
    # TELEMETRY HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _emit_agent_summary_span(self, agent_name: str) -> None:
        """Emit an invoke_agent summary span with accumulated token usage."""
        agent = self.agents.get(agent_name)
        if not agent:
            return

        session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
        agent_duration_ms = (time.perf_counter() - self._agent_start_time) * 1000

        with tracer.start_as_current_span(
            f"invoke_agent {agent_name}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                "component": "voicelive",
                "ai.session.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: self.call_connection_id or "",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.INVOKE_AGENT,
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                SpanAttr.GENAI_REQUEST_MODEL.value: self._model_name,
                "gen_ai.agent.name": agent_name,
                "gen_ai.agent.description": getattr(
                    agent, "description", f"VoiceLive agent: {agent_name}"
                ),
                SpanAttr.GENAI_USAGE_INPUT_TOKENS.value: self._agent_input_tokens,
                SpanAttr.GENAI_USAGE_OUTPUT_TOKENS.value: self._agent_output_tokens,
                "voicelive.agent_name": agent_name,
                "voicelive.response_count": self._agent_response_count,
                "voicelive.duration_ms": agent_duration_ms,
            },
        ) as agent_span:
            agent_span.add_event(
                "gen_ai.agent.session_complete",
                {
                    "agent": agent_name,
                    "input_tokens": self._agent_input_tokens,
                    "output_tokens": self._agent_output_tokens,
                    "response_count": self._agent_response_count,
                    "duration_ms": agent_duration_ms,
                },
            )
            logger.debug(
                "[Agent Summary] %s complete | tokens=%d/%d responses=%d duration=%.1fms",
                agent_name,
                self._agent_input_tokens,
                self._agent_output_tokens,
                self._agent_response_count,
                agent_duration_ms,
            )

    def _emit_model_metrics(self, event: Any) -> None:
        """Emit GenAI model-level metrics for App Insights Agents blade."""
        response = getattr(event, "response", None)
        if not response:
            return

        response_id = getattr(response, "id", None)

        usage = getattr(response, "usage", None)
        input_tokens = None
        output_tokens = None

        if usage:
            input_tokens = getattr(usage, "input_tokens", None) or getattr(
                usage, "prompt_tokens", None
            )
            output_tokens = getattr(usage, "output_tokens", None) or getattr(
                usage, "completion_tokens", None
            )

        if input_tokens:
            self._agent_input_tokens += input_tokens
        if output_tokens:
            self._agent_output_tokens += output_tokens
        self._agent_response_count += 1

        model = self._model_name
        status = getattr(response, "status", None)

        turn_duration_ms = None
        if self._llm_turn_start_time:
            turn_duration_ms = (time.perf_counter() - self._llm_turn_start_time) * 1000

        session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
        span_name = model if model else "gpt-4o-realtime"

        with tracer.start_as_current_span(
            span_name,
            kind=trace.SpanKind.CLIENT,
            attributes={
                "component": "voicelive",
                "call.connection.id": self.call_connection_id or "",
                "ai.session.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                "ai.user.id": session_id or "",
                "transport.type": self._transport.upper() if self._transport else "ACS",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.CHAT,
                SpanAttr.GENAI_SYSTEM.value: "openai",
                SpanAttr.GENAI_REQUEST_MODEL.value: model,
                "voicelive.agent_name": self.active,
            },
        ) as model_span:
            model_span.set_attribute(SpanAttr.GENAI_RESPONSE_MODEL.value, model)

            if response_id:
                model_span.set_attribute(SpanAttr.GENAI_RESPONSE_ID.value, response_id)

            if input_tokens is not None:
                model_span.set_attribute(SpanAttr.GENAI_USAGE_INPUT_TOKENS.value, input_tokens)
            if output_tokens is not None:
                model_span.set_attribute(SpanAttr.GENAI_USAGE_OUTPUT_TOKENS.value, output_tokens)

            if turn_duration_ms is not None:
                model_span.set_attribute(
                    SpanAttr.GENAI_CLIENT_OPERATION_DURATION.value, turn_duration_ms
                )

            if self._llm_turn_start_time and self._llm_first_token_time:
                ttft_ms = (self._llm_first_token_time - self._llm_turn_start_time) * 1000
                model_span.set_attribute(SpanAttr.GENAI_SERVER_TIME_TO_FIRST_TOKEN.value, ttft_ms)

            model_span.add_event(
                "gen_ai.response.complete",
                {
                    "response_id": response_id or "",
                    "status": str(status) if status else "",
                    "input_tokens": input_tokens or 0,
                    "output_tokens": output_tokens or 0,
                    "agent": self.active,
                    "turn_number": self._llm_turn_number,
                },
            )

            logger.debug(
                "[Model Metrics] Response complete | agent=%s model=%s response_id=%s tokens=%s/%s",
                self.active,
                model,
                response_id or "N/A",
                input_tokens or "N/A",
                output_tokens or "N/A",
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _transport_supports_acs(self) -> bool:
        return self._transport == "acs"

    @staticmethod
    def _response_id_from_event(event: Any) -> str | None:
        response = getattr(event, "response", None)
        if response and hasattr(response, "id"):
            return response.id
        return getattr(event, "response_id", None)

    def _should_emit_paypal_search_preface(self, tool_name: str | None) -> bool:
        return (
            tool_name == "search_knowledge_base"
            and self.active == _PAYPAL_AGENT_NAME
            and self.active in self.agents
            and not self._pending_greeting
            and bool(_PAYPAL_SEARCH_PREFACE_MESSAGES)
        )

    def _next_paypal_search_preface(self) -> str:
        if not _PAYPAL_SEARCH_PREFACE_MESSAGES:
            return "Checking now."
        idx = self._search_preface_index % len(_PAYPAL_SEARCH_PREFACE_MESSAGES)
        self._search_preface_index = (self._search_preface_index + 1) % len(
            _PAYPAL_SEARCH_PREFACE_MESSAGES
        )
        return _PAYPAL_SEARCH_PREFACE_MESSAGES[idx]

    async def _maybe_emit_paypal_search_preface(self, tool_name: str | None) -> None:
        if not self._should_emit_paypal_search_preface(tool_name):
            return
        agent = self.agents.get(self.active)
        if not agent or not self.conn:
            return
        message = self._next_paypal_search_preface()
        logger.debug(
            "[PayPal Preface] Emitting search filler: '%s' | agent=%s", message, self.active
        )
        try:
            await agent.trigger_response(self.conn, say=message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Failed to send PayPal search preface", exc_info=True)


__all__ = [
    "LiveOrchestrator",
    "TRANSFER_TOOL_NAMES",
    "CALL_CENTER_TRIGGER_PHRASES",
]
