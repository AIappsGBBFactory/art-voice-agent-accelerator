# orchestrator.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional

# Add project root to path for utils imports
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from azure.ai.voicelive.models import ServerEventType, ResponseCreateParams, FunctionCallOutputItem
from tools import execute_tool, is_handoff_tool
from utils.ml_logging import get_logger

logger = get_logger("voicelive.orchestrator")

class LiveOrchestrator:
    """
    Orchestrates agent switching and tool execution for VoiceLive multi-agent system.
    
    All tool execution flows through tools.py for centralized management:
    - Handoff tools → trigger agent switching
    - Business tools → execute and return results to model
    """

    def __init__(
        self,
        conn,
        agents: Dict[str, "AzureLiveVoiceAgent"],
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
        
        await agent.apply_session(self.conn, system_vars=system_vars, say=greeting)
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
            ctx = {
                "handoff_reason": result.get("reason", args.get("reason", "unspecified")),
                "details": result.get("details", args.get("details", "")),
                "previous_agent": self.active,
            }
            
            logger.info(
                "[Handoff Tool] '%s' triggered | %s → %s",
                name, self.active, target
            )
            await self._switch_to(target, ctx)
            # Note: _switch_to triggers greeting automatically via apply_session(say=...)
            return True
        
        else:
            # Business tool - log result and send back via conversation.item.create
            success_indicator = "✓" if result.get("authenticated") or result.get("success") else "✗"
            logger.info(
                "[%s] Tool '%s' %s | Result: %s",
                self.active, name, success_indicator, 
                {k: v for k, v in result.items() if k not in ["message"]}  # Log key fields only
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
            logger.info("Session ready: %s", getattr(event.session, "id", "unknown"))
            if self.audio:
                await self.audio.start_capture()

        elif et == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            logger.debug("User speech started → stop playback, cancel current response")
            if self.audio:
                await self.audio.stop_playback()
            try:
                await self.conn.response.cancel()
            except Exception:
                pass

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
