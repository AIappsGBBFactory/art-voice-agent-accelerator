# orchestrator.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from azure.ai.voicelive.models import ServerEventType, FunctionCallOutputItem
from .financial_tools import execute_tool, is_handoff_tool

if TYPE_CHECKING:
    from .base import AzureVoiceLiveAgent
from utils.ml_logging import get_logger

logger = get_logger("voicelive.orchestrator")


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

class LiveOrchestrator:
    """
    Orchestrates agent switching and tool execution for VoiceLive multi-agent system.

    All tool execution flows through financial_tools.py for centralized management:
    - Handoff tools → trigger agent switching
    - Business tools → execute and return results to model
    """

    def __init__(
        self,
        conn,
        agents: Dict[str, "AzureVoiceLiveAgent"],
        handoff_map: Dict[str, str],
        start_agent: str = "AutoAuth",
        audio_processor=None,
    ):
        self.conn = conn
        self.agents = agents
        self.handoff_map = handoff_map
        self.active = start_agent
        self.audio = audio_processor
        self.visited_agents: set = set()  # Track which agents have been visited
        self._pending_greeting: Optional[str] = None
        self._pending_greeting_agent: Optional[str] = None

        if self.active not in self.agents:
            raise ValueError(f"Start agent '{self.active}' not found in registry")

    async def start(self, system_vars: Optional[dict] = None):
        """Apply initial agent session and trigger an intro response."""
        logger.info("[Orchestrator] Starting with agent: %s", self.active)
        await self._switch_to(self.active, system_vars or {})
        # Note: _switch_to now triggers greeting automatically, no need for separate response.create()

    async def _switch_to(self, agent_name: str, system_vars: dict):
        """Switch to a different agent and apply its session configuration."""
        previous_agent = self.active
        agent = self.agents[agent_name]
        
        # Always work with a copy so we do not mutate upstream state.
        system_vars = dict(system_vars or {})
        system_vars.setdefault("previous_agent", previous_agent)
        system_vars.setdefault("active_agent", agent.name)

        # Check if this is first visit or returning
        is_first_visit = agent_name not in self.visited_agents
        self.visited_agents.add(agent_name)
        
        logger.info(
            "[Agent Switch] %s → %s | Context: %s | First visit: %s",
            previous_agent,
            agent_name,
            system_vars,
            is_first_visit
        )
        
        # Choose greeting based on visit history
        if system_vars.get("greeting"):
            greeting = system_vars["greeting"]
        elif is_first_visit:
            greeting = agent.greeting
        else:
            greeting = agent.return_greeting or f"Welcome back! How can I help you?"
        
        handoff_message = system_vars.get("handoff_message")
        combined_greeting = " ".join(
            segment.strip()
            for segment in (handoff_message, greeting)
            if segment and segment.strip()
        )

        if combined_greeting:
            self._pending_greeting = combined_greeting
            self._pending_greeting_agent = agent_name
        else:
            self._pending_greeting = None
            self._pending_greeting_agent = None

        handoff_context = _sanitize_handoff_context(system_vars.get("handoff_context"))
        if handoff_context:
            system_vars["handoff_context"] = handoff_context
            for key in ("caller_name", "client_id", "institution_name", "service_type", "case_id"):
                if key not in system_vars and handoff_context.get(key) is not None:
                    system_vars[key] = handoff_context.get(key)

        try:
            await agent.apply_session(
                self.conn,
                system_vars=system_vars,
                say=None,
            )
        except Exception:
            logger.exception("Failed to apply session for agent '%s'", agent_name)
            raise

        self.active = agent_name
        
        logger.info("[Active Agent] %s is now active", self.active)

    async def _execute_tool_call(self, call_id: Optional[str], name: Optional[str], args_json: Optional[str]) -> bool:
        """
        Execute tool call via centralized tools.py and send result back to model.
        
        ALL tool execution goes through tools.execute_tool():
        - Handoff tools → Switch agents
        - Business tools → Execute, create FunctionCallOutputItem, trigger response
        
        Args:
            call_id: Function call ID from the model (required for sending output back)
            name: Tool name
            args_json: Tool arguments as JSON string
        
        Returns True if this was a handoff (agent switch), False otherwise.
        """
        if not name or not call_id:
            logger.warning("Missing call_id or name for function call")
            return False
        
        # Parse arguments
        try:
            args = json.loads(args_json) if args_json else {}
        except Exception:
            logger.warning("Could not parse tool arguments for '%s'; using empty dict", name)
            args = {}
        
        # Execute tool via centralized tools.py
        logger.info("Executing tool: %s with args: %s", name, args)
        result = await execute_tool(name, args)
        
        # Check if this is a handoff tool
        if is_handoff_tool(name):
            # Extract target agent from handoff_map
            target = self.handoff_map.get(name)
            if not target:
                logger.warning("Handoff tool '%s' not in handoff_map", name)
                return False
            
            # Build context from tool result
            handoff_context = _sanitize_handoff_context(result.get("handoff_context"))
            session_overrides = result.get("session_overrides")
            if not isinstance(session_overrides, dict) or not session_overrides:
                session_overrides = None
            ctx = {
                "handoff_reason": result.get("handoff_summary")
                or handoff_context.get("reason")
                or args.get("reason", "unspecified"),
                "details": handoff_context.get("details")
                or result.get("details")
                or args.get("details", ""),
                "previous_agent": self.active,
                "handoff_context": handoff_context,
                "handoff_message": result.get("message"),
            }
            if session_overrides:
                ctx["session_overrides"] = session_overrides
            
            logger.info(
                "[Handoff Tool] '%s' triggered | %s → %s",
                name, self.active, target
            )

            # Cancel the current response to prevent the previous agent from continuing to speak
            try:
                if result.get("should_interrupt_playback", True):
                    await self.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during handoff", exc_info=True)

            await self._switch_to(target, ctx)
            # Note: _switch_to triggers greeting automatically via apply_session(say=...)
            return True
        
        else:
            # Business tool - log result and send back via conversation.item.create
            success_indicator = "✓" if result.get("authenticated") or result.get("success") else "✗"
            safe_result = {}
            for key, value in result.items():
                if key == "message":
                    continue
                text = str(value)
                safe_result[key] = text if len(text) <= 50 else f"{text[:47]}..."
            pretty_result = json.dumps(safe_result, indent=2, ensure_ascii=False)
            logger.info(
                "[%s] Tool '%s' %s | Result:\n%s",
                self.active,
                name,
                success_indicator,
                pretty_result,
            )
            
            output_item = FunctionCallOutputItem(
                call_id=call_id,
                output=json.dumps(result)  # SDK expects JSON string
            )
            
            await self.conn.conversation.item.create(item=output_item)
            logger.debug("Created function_call_output item for call_id=%s", call_id)
            
            await self.conn.response.create()
            return False

    async def handle_event(self, event):
        """Route VoiceLive events to audio + handoff logic."""
        et = event.type

        if et == ServerEventType.SESSION_UPDATED:
            session_obj = getattr(event, "session", None)
            session_id = getattr(session_obj, "id", "unknown") if session_obj else "unknown"
            voice_info = getattr(session_obj, "voice", None) if session_obj else None
            logger.info("Session ready: %s | voice=%s", session_id, voice_info)
            if self.audio:
                await self.audio.start_capture()

            if self._pending_greeting and self._pending_greeting_agent == self.active:
                try:
                    await self.agents[self.active].trigger_response(
                        self.conn,
                        say=self._pending_greeting,
                    )
                finally:
                    self._pending_greeting = None
                    self._pending_greeting_agent = None

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            logger.debug("User speech started → cancel current response")
            if self.audio:
                await self.audio.stop_playback()
            try:
                await self.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during barge-in", exc_info=True)

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            logger.debug("User speech stopped → start playback for assistant")
            if self.audio:
                await self.audio.start_playback()

        elif et == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            # Log user's spoken input (transcription)
            user_transcript = getattr(event, "transcript", "")
            if user_transcript:
                logger.info("[USER] Says: %s", user_transcript)

        elif et == ServerEventType.RESPONSE_AUDIO_DELTA:
            if self.audio:
                await self.audio.queue_audio(event.delta)

        elif et == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DELTA:
            # Collect transcription deltas (don't log each token to reduce noise)
            pass

        elif et == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            # Log complete transcript only
            full_transcript = getattr(event, "transcript", "")
            if full_transcript:
                logger.info("[%s] Agent: %s", self.active, full_transcript)

        elif et == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            await self._execute_tool_call(
                call_id=getattr(event, "call_id", None),
                name=getattr(event, "name", None),
                args_json=getattr(event, "arguments", None)
            )

        elif et == ServerEventType.RESPONSE_DONE:
            logger.debug("Response complete")

        elif et == ServerEventType.ERROR:
            logger.error("VoiceLive error: %s", getattr(event.error, "message", "unknown"))
