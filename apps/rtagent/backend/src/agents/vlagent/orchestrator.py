# orchestrator.py
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from azure.ai.voicelive.models import ServerEventType, FunctionCallOutputItem
from .financial_tools import execute_tool, is_handoff_tool

if TYPE_CHECKING:
    from .base import AzureVoiceLiveAgent
from utils.ml_logging import get_logger

logger = get_logger("voicelive.orchestrator")

TRANSFER_TOOL_NAMES = {"transfer_call_to_destination", "transfer_call_to_call_center"}

CALL_CENTER_TRIGGER_PHRASES = {
    "transfer to call center",
    "transfer me to the call center",
}


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
        messenger=None,
        call_connection_id: Optional[str] = None,
        *,
        transport: str = "acs",
    ):
        self.conn = conn
        self.agents = agents
        self.handoff_map = handoff_map
        self.active = start_agent
        self.audio = audio_processor
        self.messenger = messenger
        self.visited_agents: set = set()  # Track which agents have been visited
        self._pending_greeting: Optional[str] = None
        self._pending_greeting_agent: Optional[str] = None
        self._last_user_message: Optional[str] = None
        self.call_connection_id = call_connection_id
        self._call_center_triggered = False
        self._transport = transport
        self._greeting_tasks: set[asyncio.Task] = set()

        if self.messenger:
            try:
                self.messenger.set_active_agent(self.active)
            except AttributeError:
                logger.debug("Messenger does not support set_active_agent", exc_info=True)

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
        
        self._cancel_pending_greeting_tasks()

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

        self.active = agent_name

        try:
            if self.messenger:
                try:
                    self.messenger.set_active_agent(agent_name)
                except AttributeError:
                    logger.debug("Messenger does not support set_active_agent", exc_info=True)
            await agent.apply_session(
                self.conn,
                system_vars=system_vars,
                say=None,
            )
            if self._pending_greeting and self._pending_greeting_agent == agent_name:
                self._schedule_greeting_fallback(agent_name)
        except Exception:
            logger.exception("Failed to apply session for agent '%s'", agent_name)
            raise
        
        logger.info("[Active Agent] %s is now active", self.active)

    def _transport_supports_acs(self) -> bool:
        return self._transport == "acs"

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
                if (
                    self._pending_greeting
                    and self._pending_greeting_agent == agent_name
                ):
                    logger.debug(
                        "[GreetingFallback] Triggering fallback introduction for %s",
                        agent_name,
                    )
                    try:
                        await self.agents[agent_name].trigger_response(
                            self.conn,
                            say=self._pending_greeting,
                        )
                    finally:
                        self._pending_greeting = None
                        self._pending_greeting_agent = None
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("[GreetingFallback] Failed to deliver greeting", exc_info=True)

        task = asyncio.create_task(
            _fallback(),
            name=f"voicelive-greeting-fallback-{agent_name}",
        )

        task.add_done_callback(lambda t: self._greeting_tasks.discard(t))
        self._greeting_tasks.add(task)

    def _select_pending_greeting(
        self,
        *,
        agent: "AzureVoiceLiveAgent",
        agent_name: str,
        system_vars: dict,
        is_first_visit: bool,
    ) -> Optional[str]:
        """Return a contextual greeting the agent should deliver once the session is ready."""

        explicit = system_vars.get("greeting")
        if explicit:
            return explicit.strip() or None

        # Prefer agent defaults when there's no transfer context.
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
        intro = (intro or f"Hi, I'm {agent_name}.").strip()

        if intent:
            intent = intent.strip().rstrip(".")
            return f"Hi {caller}, {intro} I understand you're calling about {intent}. Let's get started."

        handoff_message = (system_vars.get("handoff_message") or "").strip()
        if handoff_message:
            return f"Hi {caller}, {intro} {handoff_message}"

        return f"Hi {caller}, {intro}".strip()

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
        
        if name in TRANSFER_TOOL_NAMES:
            if self._transport_supports_acs() and (not args.get("call_connection_id")) and self.call_connection_id:
                args.setdefault("call_connection_id", self.call_connection_id)
            if self._transport_supports_acs() and (not args.get("call_connection_id")) and self.messenger:
                fallback_call_id = getattr(self.messenger, "call_id", None)
                if fallback_call_id:
                    args.setdefault("call_connection_id", fallback_call_id)
            if self.messenger:
                session_id = getattr(self.messenger, "session_id", None)
                if session_id:
                    args.setdefault("session_id", session_id)

        # Execute tool via centralized tools.py
        logger.info("Executing tool: %s with args: %s", name, args)

        notify_status = "success"
        notify_error: Optional[str] = None

        last_user_message = (self._last_user_message or "").strip()
        if is_handoff_tool(name) and last_user_message:
            # Pre-populate commonly used handoff fields so the caller is not asked to repeat themselves.
            for field in ("details", "issue_summary", "summary", "topic", "handoff_reason"):
                if not args.get(field):
                    args[field] = last_user_message
            # Preserve the raw utterance for downstream agents even if they use custom field names.
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
            result = await execute_tool(name, args)
        except Exception as exc:
            notify_status = "error"
            notify_error = str(exc)
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

        error_payload: Optional[str] = None
        if isinstance(result, dict):
            for key in ("success", "ok", "authenticated"):
                if key in result and not result[key]:
                    notify_status = "error"
                    break
            if notify_status == "error":
                err_val = result.get("message") or result.get("error")
                if err_val:
                    error_payload = str(err_val)

        if name in TRANSFER_TOOL_NAMES and notify_status != "error" and isinstance(result, dict):
            takeover_message = result.get("message") or "Transferring call to destination."
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
            return False

        # Check if this is a handoff tool
        if is_handoff_tool(name):
            # Extract target agent from handoff_map
            target = self.handoff_map.get(name)
            if not target:
                logger.warning("Handoff tool '%s' not in handoff_map", name)
                notify_status = "error"
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
            
            # Build context from tool result
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
            if last_user_message:
                ctx.setdefault("user_last_utterance", last_user_message)
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
            # Clear the cached user message once the handoff has completed.
            self._last_user_message = None

            if result.get("call_center_transfer"):
                transfer_args: Dict[str, Any] = {}
                if self._transport_supports_acs() and self.call_connection_id:
                    transfer_args["call_connection_id"] = self.call_connection_id
                if self.messenger:
                    session_id = getattr(self.messenger, "session_id", None)
                    if session_id:
                        transfer_args["session_id"] = session_id
                if transfer_args:
                    self._call_center_triggered = True
                    await self._trigger_call_center_transfer(transfer_args)
            # Note: _switch_to triggers greeting automatically via apply_session(say=...)
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
            # logger.info(
            #     "[%s] Tool '%s' %s | Result:\n%s",
            #     self.active,
            #     name,
            #     success_indicator,
            #     pretty_result,
            # )

            output_item = FunctionCallOutputItem(
                call_id=call_id,
                output=json.dumps(result),  # SDK expects JSON string
            )

            await self.conn.conversation.item.create(item=output_item)
            logger.debug("Created function_call_output item for call_id=%s", call_id)

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
                await self.audio.stop_playback()
            try:
                await self.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during session_ready", exc_info=True)
            if self.audio:
                await self.audio.start_capture()

            if self._pending_greeting and (
                self._pending_greeting_agent == self.active
            ):
                self._cancel_pending_greeting_tasks()
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
                self._last_user_message = user_transcript.strip()
                await self._maybe_trigger_call_center_transfer(user_transcript)

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
                if self.messenger:
                    try:
                        await self.messenger.send_assistant_message(full_transcript, sender=self.active)
                    except Exception:
                        logger.debug("Failed to relay assistant transcript to session UI", exc_info=True)

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
            logger.warning(
                "Automatic call center transfer request was rejected | result=%s",
                result,
            )
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

        takeover_message = result.get(
            "message",
            "Routing you to a live call center representative now.",
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
            logger.debug("response.cancel() failed during automatic call center transfer", exc_info=True)

        if self.audio:
            try:
                await self.audio.stop_playback()
            except Exception:
                logger.debug("Audio stop playback failed during automatic call center transfer", exc_info=True)
