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
    from apps.rtagent.backend.voice.orchestrators import (
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
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from opentelemetry import trace
from azure.ai.voicelive.models import (
    ServerEventType,
    FunctionCallOutputItem,
    UserMessageItem,
    InputTextContentPart,
)

# Self-contained tool registry (no legacy vlagent dependency)
from apps.rtagent.backend.agents.tools import (
    execute_tool,
    is_handoff_tool,
    initialize_tools,
)
from apps.rtagent.backend.src.services.session_loader import load_user_profile_by_client_id

if TYPE_CHECKING:
    from ..voicelive.agent_adapter import VoiceLiveAgentAdapter
    from src.stateful.state_managment import MemoManager

from utils.ml_logging import get_logger
from apps.rtagent.backend.src.utils.tracing import (
    create_service_handler_attrs,
    create_service_dependency_attrs,
)
from src.enums.monitoring import SpanAttr, GenAIOperation, GenAIProvider

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
_PAYPAL_SEARCH_PREFACE_MESSAGES: Tuple[str, ...] = (
    "Got it, checking now.",
    "One sec while I look.",
    "Sure, let me pull that up.",
    "Let me take a quick look.",
)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_handoff_context(raw: Any) -> Dict[str, Any]:
    """Remove control flags so prompt variables stay clean."""
    if not isinstance(raw, dict):
        return {}

    disallowed = {
        "success",
        "handoff",
        "target_agent",
        "message",
        "handoff_summary",
        "should_interrupt_playback",
        "session_overrides",
    }
    return {
        key: value
        for key, value in raw.items()
        if key not in disallowed and value not in (None, "", [], {})
    }


async def _auto_load_user_context(system_vars: Dict[str, Any]) -> None:
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
        agents: Dict[str, "VoiceLiveAgentAdapter"],
        handoff_map: Dict[str, str],
        start_agent: str = "EricaConcierge",
        audio_processor=None,
        messenger=None,
        call_connection_id: Optional[str] = None,
        *,
        transport: str = "acs",
        model_name: Optional[str] = None,
        memo_manager: Optional["MemoManager"] = None,
    ):
        self.conn = conn
        self.agents = agents
        self.handoff_map = handoff_map
        self.active = start_agent
        self.audio = audio_processor
        self.messenger = messenger
        self._model_name = model_name or "gpt-4o-realtime"
        self.visited_agents: set = set()
        self._pending_greeting: Optional[str] = None
        self._pending_greeting_agent: Optional[str] = None
        self._last_user_message: Optional[str] = None
        self.call_connection_id = call_connection_id
        self._call_center_triggered = False
        self._transport = transport
        self._greeting_tasks: set[asyncio.Task] = set()
        self._search_preface_index = 0
        self._active_response_id: Optional[str] = None
        self._system_vars: Dict[str, Any] = {}
        
        # MemoManager for session state continuity (consistent with CascadeOrchestratorAdapter)
        self._memo_manager: Optional["MemoManager"] = memo_manager
        
        # LLM TTFT tracking
        self._llm_turn_start_time: Optional[float] = None
        self._llm_first_token_time: Optional[float] = None
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
    def memo_manager(self) -> Optional["MemoManager"]:
        """Return the current MemoManager instance."""
        return self._memo_manager

    def _sync_from_memo_manager(self) -> None:
        """
        Sync orchestrator state from MemoManager.
        Called at initialization and optionally at turn boundaries.
        
        Loads:
        - active_agent: Current agent name
        - visited_agents: Set of previously visited agents
        - session_profile: User profile for personalization
        - customer_intelligence: Customer data for agent context
        - client_id, caller_name, institution_name: Core identity info
        """
        if not self._memo_manager:
            return
        
        mm = self._memo_manager
        
        # Sync active agent (from attribute or corememory)
        active = getattr(mm, "active_agent", None)
        if not active and hasattr(mm, "get_value_from_corememory"):
            active = mm.get_value_from_corememory("active_agent")
        if active and active in self.agents:
            self.active = active
            logger.debug("[LiveOrchestrator] Synced active_agent from MemoManager: %s", self.active)
        
        # Sync visited agents
        visited = getattr(mm, "visited_agents", None)
        if not visited and hasattr(mm, "get_value_from_corememory"):
            visited = mm.get_value_from_corememory("visited_agents")
        if visited:
            self.visited_agents = set(visited)
            logger.debug("[LiveOrchestrator] Synced visited_agents from MemoManager: %s", self.visited_agents)
        
        # Sync system_vars from attribute if available
        if hasattr(mm, "system_vars") and mm.system_vars:
            self._system_vars.update(mm.system_vars)
            logger.debug("[LiveOrchestrator] Synced system_vars from MemoManager")
        
        # Load session profile and related context from corememory
        if hasattr(mm, "get_value_from_corememory"):
            # Session profile is the main user context
            session_profile = mm.get_value_from_corememory("session_profile")
            if session_profile:
                self._system_vars["session_profile"] = session_profile
                self._system_vars["client_id"] = session_profile.get("client_id")
                self._system_vars["caller_name"] = session_profile.get("full_name")
                self._system_vars["customer_intelligence"] = session_profile.get("customer_intelligence", {})
                if session_profile.get("institution_name"):
                    self._system_vars["institution_name"] = session_profile["institution_name"]
                logger.info(
                    "🔄 Restored session context | client_id=%s name=%s",
                    session_profile.get("client_id"),
                    session_profile.get("full_name"),
                )
            else:
                # Try loading individual fields as fallback
                for key in ("client_id", "caller_name", "customer_intelligence", "institution_name"):
                    val = mm.get_value_from_corememory(key)
                    if val and key not in self._system_vars:
                        self._system_vars[key] = val
        
        # Legacy: sync user_profile attribute if available
        if hasattr(mm, "user_profile") and mm.user_profile:
            if "session_profile" not in self._system_vars:
                self._system_vars["session_profile"] = mm.user_profile
                logger.debug("[LiveOrchestrator] Synced user_profile to session_profile")

    def _sync_to_memo_manager(self) -> None:
        """
        Sync orchestrator state back to MemoManager.
        Called at turn boundaries to persist state.
        
        Saves:
        - active_agent: Current agent name
        - visited_agents: Set of visited agents
        - session_profile: User profile for next session
        - customer_intelligence, client_id, etc.: Core context
        """
        if not self._memo_manager:
            return
        
        mm = self._memo_manager
        
        # Sync active agent
        if hasattr(mm, "set_corememory"):
            mm.set_corememory("active_agent", self.active)
        elif hasattr(mm, "active_agent"):
            mm.active_agent = self.active
        
        # Sync visited agents
        if hasattr(mm, "set_corememory"):
            mm.set_corememory("visited_agents", list(self.visited_agents))
        elif hasattr(mm, "visited_agents"):
            mm.visited_agents = list(self.visited_agents)
        
        # Sync system_vars (legacy attribute)
        if hasattr(mm, "system_vars"):
            mm.system_vars = dict(self._system_vars)
        
        # Persist session profile to corememory for next session restore
        if hasattr(mm, "set_corememory"):
            session_profile = self._system_vars.get("session_profile")
            if session_profile:
                mm.set_corememory("session_profile", session_profile)
            
            # Also persist individual fields for backward compatibility
            for key in ("client_id", "caller_name", "customer_intelligence", "institution_name"):
                if key in self._system_vars and self._system_vars[key]:
                    mm.set_corememory(key, self._system_vars[key])
        
        # Sync last user message
        if hasattr(mm, "last_user_message") and self._last_user_message:
            mm.last_user_message = self._last_user_message
        
        logger.debug("[LiveOrchestrator] Synced state to MemoManager")

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════════════════════

    async def start(self, system_vars: Optional[dict] = None):
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
                args_json=getattr(event, "arguments", None)
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
                logger.warning("[Greeting] Session-ready trigger failed; retrying via fallback", exc_info=True)
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
                logger.info("[Orchestrator] LLM TTFT | turn=%d ttft_ms=%.2f agent=%s",
                            self._llm_turn_number, ttft_ms, self.active)
        
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
                    logger.debug("Failed to relay assistant transcript to session UI", exc_info=True)
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
            
            logger.info("[Agent Switch] %s → %s | Context: %s | First visit: %s",
                        previous_agent, agent_name, system_vars, is_first_visit)
            
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

            handoff_context = _sanitize_handoff_context(system_vars.get("handoff_context"))
            if handoff_context:
                system_vars["handoff_context"] = handoff_context
                for key in ("caller_name", "client_id", "institution_name", "service_type",
                            "case_id", "issue_summary", "details", "handoff_reason", "user_last_utterance"):
                    if key not in system_vars and handoff_context.get(key) is not None:
                        system_vars[key] = handoff_context.get(key)

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
                handoff_message = system_vars.get("handoff_message") if has_handoff else None
                switch_span.set_attribute("voicelive.is_handoff", has_handoff)
                
                if handoff_message:
                    self._pending_greeting = handoff_message
                    self._pending_greeting_agent = agent_name
                    logger.info("[Handoff] Pending transition message: %s",
                                handoff_message[:50] + "..." if len(handoff_message) > 50 else handoff_message)
                
                with tracer.start_as_current_span(
                    "voicelive.agent.apply_session",
                    kind=trace.SpanKind.SERVER,
                    attributes=create_service_dependency_attrs(
                        source_service="voicelive_orchestrator",
                        target_service="azure_voicelive",
                        call_connection_id=self.call_connection_id,
                        session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
                    ),
                ) as session_span:
                    session_span.set_attribute("voicelive.agent_name", agent_name)
                    session_id = getattr(self.messenger, "session_id", None) if self.messenger else None
                    await agent.apply_session(
                        self.conn,
                        system_vars=system_vars,
                        say=None,
                        session_id=session_id,
                        call_connection_id=self.call_connection_id,
                    )
                
                if not has_handoff and self._pending_greeting and self._pending_greeting_agent == agent_name:
                    self._schedule_greeting_fallback(agent_name)
                
                # Reset token counters for the new agent
                self._agent_input_tokens = 0
                self._agent_output_tokens = 0
                self._agent_start_time = time.perf_counter()
                self._agent_response_count = 0
                
                switch_span.set_status(trace.StatusCode.OK)
            except Exception as ex:
                switch_span.set_status(trace.StatusCode.ERROR, str(ex))
                switch_span.add_event("agent_switch.error", {"error.type": type(ex).__name__, "error.message": str(ex)})
                logger.exception("Failed to apply session for agent '%s'", agent_name)
                raise
            
            logger.info("[Active Agent] %s is now active", self.active)

    # ═══════════════════════════════════════════════════════════════════════════
    # TOOL EXECUTION
    # ═══════════════════════════════════════════════════════════════════════════

    async def _execute_tool_call(self, call_id: Optional[str], name: Optional[str], args_json: Optional[str]) -> bool:
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
                if self._transport_supports_acs() and (not args.get("call_connection_id")) and self.call_connection_id:
                    args.setdefault("call_connection_id", self.call_connection_id)
                if self._transport_supports_acs() and (not args.get("call_connection_id")) and self.messenger:
                    fallback_call_id = getattr(self.messenger, "call_id", None)
                    if fallback_call_id:
                        args.setdefault("call_connection_id", fallback_call_id)
                if self.messenger:
                    sess_id = getattr(self.messenger, "session_id", None)
                    if sess_id:
                        args.setdefault("session_id", sess_id)

            logger.info("Executing tool: %s with args: %s", name, args)

            notify_status = "success"
            notify_error: Optional[str] = None

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
            result: Dict[str, Any] = {}

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
                tool_span.add_event("tool.execution_error", {"error.type": type(exc).__name__, "error.message": str(exc)})
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

            error_payload: Optional[str] = None
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
            if name in TRANSFER_TOOL_NAMES and notify_status != "error" and isinstance(result, dict):
                takeover_message = result.get("message") or "Transferring call to destination."
                tool_span.add_event("tool.transfer_initiated", {"transfer.message": takeover_message[:100] if takeover_message else ""})
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
                target = self.handoff_map.get(name)
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

                raw_handoff_context = result.get("handoff_context") if isinstance(result, dict) else {}
                handoff_context: Dict[str, Any] = {}
                if isinstance(raw_handoff_context, dict):
                    handoff_context = dict(raw_handoff_context)
                if last_user_message:
                    handoff_context.setdefault("user_last_utterance", last_user_message)
                    handoff_context.setdefault("details", last_user_message)
                handoff_context = _sanitize_handoff_context(handoff_context)
                session_overrides = result.get("session_overrides")
                if not isinstance(session_overrides, dict) or not session_overrides:
                    session_overrides = None
                ctx = {
                    "handoff_reason": result.get("handoff_summary")
                    or handoff_context.get("reason")
                    or args.get("reason", "unspecified"),
                    "details": handoff_context.get("details")
                    or result.get("details")
                    or args.get("details")
                    or last_user_message,
                    "previous_agent": self.active,
                    "handoff_context": handoff_context,
                    "handoff_message": result.get("message"),
                }
                for key in ("session_profile", "client_id", "customer_intelligence", "institution_name"):
                    if key in self._system_vars:
                        ctx[key] = self._system_vars[key]
                if last_user_message:
                    ctx.setdefault("user_last_utterance", last_user_message)
                if session_overrides:
                    ctx["session_overrides"] = session_overrides
                
                logger.info("[Handoff Tool] '%s' triggered | %s → %s", name, self.active, target)

                await self._switch_to(target, ctx)
                self._last_user_message = None

                if result.get("call_center_transfer"):
                    transfer_args: Dict[str, Any] = {}
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
                        output=json.dumps(result) if isinstance(result, dict) else json.dumps({"success": True}),
                    )
                    await self.conn.conversation.item.create(item=handoff_output)
                    logger.debug("Created handoff tool output for call_id=%s", call_id)
                except Exception as item_err:
                    logger.warning("Failed to create handoff tool output: %s", item_err)
                
                # Clear active response tracking since we're transitioning agents
                self._active_response_id = None
                
                # Try to trigger new agent response, but don't fail if already active
                # The model should naturally continue after receiving the tool result
                try:
                    await self.conn.response.create()
                    logger.info("[Handoff] Triggered new agent '%s' to respond", target)
                except Exception as resp_err:
                    # This is expected if a response is already in progress
                    # The model will continue on its own after the tool result
                    logger.debug("Handoff response.create skipped (response may already be active): %s", resp_err)
                
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
                        session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
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
                        session_id=getattr(self.messenger, "session_id", None) if self.messenger else None,
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
        agent: "VoiceLiveAgentAdapter",
        agent_name: str,
        system_vars: dict,
        is_first_visit: bool,
    ) -> Optional[str]:
        """Return a contextual greeting the agent should deliver once the session is ready."""
        explicit = system_vars.get("greeting")
        if not explicit:
            overrides = system_vars.get("session_overrides")
            if isinstance(overrides, dict):
                explicit = overrides.get("greeting")
        if explicit:
            return explicit.strip() or None

        handoff_context = system_vars.get("handoff_context") or {}
        has_handoff = bool(
            handoff_context
            or system_vars.get("handoff_message")
            or system_vars.get("handoff_reason")
        )

        if not has_handoff:
            if is_first_visit:
                return (agent.greeting or "").strip() or None
            return (agent.return_greeting or "Welcome back! How can I help you?").strip()

        caller = (
            handoff_context.get("caller_name")
            if isinstance(handoff_context, dict)
            else None
        ) or system_vars.get("caller_name") or "there"

        intent = None
        if isinstance(handoff_context, dict):
            intent = (
                handoff_context.get("issue_summary")
                or handoff_context.get("details")
                or handoff_context.get("reason")
            )
        intent = (
            system_vars.get("handoff_reason")
            or system_vars.get("issue_summary")
            or system_vars.get("details")
            or intent
        )

        intro = agent.return_greeting if not is_first_visit else agent.greeting
        intro = (intro or "").strip()
        
        # For handoffs (seamless continuation), skip automatic greeting
        if has_handoff:
            return None

        if intent:
            intent = intent.strip().rstrip(".")
            if intro:
                return f"Hi {caller}, {intro} I understand you're calling about {intent}. Let's get started."
            return None

        handoff_message = (system_vars.get("handoff_message") or "").strip()
        if handoff_message:
            if intro:
                return f"Hi {caller}, {intro} {handoff_message}"
            return None

        if intro:
            return f"Hi {caller}, {intro}".strip()
        return None

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
                    logger.debug("[GreetingFallback] Triggering fallback introduction for %s", agent_name)
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
        logger.info("[Auto Transfer] Triggering call center transfer due to phrase match: '%s'", transcript)

        args: Dict[str, Any] = {}
        if self._transport_supports_acs() and self.call_connection_id:
            args["call_connection_id"] = self.call_connection_id
        if self.messenger:
            session_id = getattr(self.messenger, "session_id", None)
            if session_id:
                args["session_id"] = session_id

        await self._trigger_call_center_transfer(args)

    async def _trigger_call_center_transfer(self, args: Dict[str, Any]) -> None:
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
            logger.warning("Automatic call center transfer request was rejected | result=%s", result)
            if self.messenger:
                try:
                    await self.messenger.send_status_update(
                        text=error_message or "Unable to reach the call center right now. I'll stay on the line with you.",
                        sender=self.active,
                        event_label="acs_call_transfer_status",
                    )
                except Exception:
                    logger.debug("Failed to emit transfer rejection status", exc_info=True)
            return

        takeover_message = result.get("message", "Routing you to a live call center representative now.")

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
            logger.debug("response.cancel() failed during automatic call center transfer", exc_info=True)

        if self.audio:
            try:
                await self.audio.stop_playback()
            except Exception:
                logger.debug("Audio stop playback failed during automatic call center transfer", exc_info=True)

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
                "gen_ai.agent.description": getattr(agent, "description", f"VoiceLive agent: {agent_name}"),
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
            logger.debug("[Agent Summary] %s complete | tokens=%d/%d responses=%d duration=%.1fms",
                         agent_name, self._agent_input_tokens, self._agent_output_tokens,
                         self._agent_response_count, agent_duration_ms)

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
            input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None)
        
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
                model_span.set_attribute(SpanAttr.GENAI_CLIENT_OPERATION_DURATION.value, turn_duration_ms)
            
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
            
            logger.debug("[Model Metrics] Response complete | agent=%s model=%s response_id=%s tokens=%s/%s",
                         self.active, model, response_id or "N/A", input_tokens or "N/A", output_tokens or "N/A")

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILITY HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _transport_supports_acs(self) -> bool:
        return self._transport == "acs"

    @staticmethod
    def _response_id_from_event(event: Any) -> Optional[str]:
        response = getattr(event, "response", None)
        if response and hasattr(response, "id"):
            return getattr(response, "id")
        return getattr(event, "response_id", None)

    def _should_emit_paypal_search_preface(self, tool_name: Optional[str]) -> bool:
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
        self._search_preface_index = (self._search_preface_index + 1) % len(_PAYPAL_SEARCH_PREFACE_MESSAGES)
        return _PAYPAL_SEARCH_PREFACE_MESSAGES[idx]

    async def _maybe_emit_paypal_search_preface(self, tool_name: Optional[str]) -> None:
        if not self._should_emit_paypal_search_preface(tool_name):
            return
        agent = self.agents.get(self.active)
        if not agent or not self.conn:
            return
        message = self._next_paypal_search_preface()
        logger.debug("[PayPal Preface] Emitting search filler: '%s' | agent=%s", message, self.active)
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
