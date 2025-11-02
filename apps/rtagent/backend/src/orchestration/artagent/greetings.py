from __future__ import annotations

import json
from typing import Dict, Optional, TYPE_CHECKING

from fastapi import WebSocket

from .bindings import get_agent_instance
from .cm_utils import cm_get, cm_set, get_correlation_context
from .config import LAST_ANNOUNCED_KEY, APP_GREETS_ATTR
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
    broadcast_message,
    send_tts_audio,
    send_response_to_acs,
)
from apps.rtagent.backend.src.ws_helpers.envelopes import make_status_envelope
from utils.ml_logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager


def create_retail_greeting(
    agent_name: str,
    caller_name: Optional[str] = None,
    topic: Optional[str] = None,
    is_returning: bool = False,
) -> str:
    """
    Create friendly, natural retail greeting for agent handoffs.
    
    Args:
        agent_name: Agent name (ShoppingConcierge, PersonalStylist, PostSale)
        caller_name: Customer name if available
        topic: Current topic/context
        is_returning: Whether customer is returning to this agent
    
    Returns:
        Friendly greeting text
    """
    first_name = caller_name.split()[0] if caller_name and caller_name.strip() else None
    
    # Agent-specific greetings
    if agent_name == "ShoppingConcierge":
        if is_returning:
            base = f"Welcome back{f', {first_name}' if first_name else ''}! I'm here to help you find anything else you need."
        else:
            base = f"Hi{f' {first_name}' if first_name else ''}! Welcome to our store. I'm here to help you find exactly what you're looking for."
    
    elif agent_name == "PersonalStylist":
        if is_returning:
            base = f"Great to style with you again{f', {first_name}' if first_name else ''}! What can I help you put together today?"
        else:
            base = f"Hi{f' {first_name}' if first_name else ''}! I'm your personal stylist. I'd love to help you find the perfect look."
    
    elif agent_name == "PostSale":
        if is_returning:
            base = f"I'm back to help{f', {first_name}' if first_name else ''}. What else can I do for you?"
        else:
            base = f"Perfect{f', {first_name}' if first_name else ''}! Let's get your order finalized. I'll make this quick and easy."
    
    else:
        base = f"Hi{f' {first_name}' if first_name else ''}! How can I help you today?"
    
    # Add context if available
    if topic and not is_returning:
        base += f" I understand you're interested in {topic}."
    
    return base


def sync_voice_from_agent(cm: "MemoManager", ws: WebSocket, agent_name: str) -> None:
    """
    Update CoreMemory voice fields based on the agent instance.
    """
    agent = get_agent_instance(ws, agent_name)
    voice_name = getattr(agent, "voice_name", None) if agent else None
    voice_style = getattr(agent, "voice_style", "chat") if agent else "chat"
    voice_rate = getattr(agent, "voice_rate", "+3%") if agent else "+3%"
    cm_set(
        cm,
        current_agent_voice=voice_name,
        current_agent_voice_style=voice_style,
        current_agent_voice_rate=voice_rate,
    )


async def send_agent_greeting(
    cm: "MemoManager", ws: WebSocket, agent_name: str, is_acs: bool
) -> None:
    """
    Send friendly retail greeting when switching to a specialist agent.
    
    Args:
        cm: MemoManager with conversation state
        ws: WebSocket connection
        agent_name: Target agent name (ShoppingConcierge, PersonalStylist, PostSale)
        is_acs: Whether this is an ACS phone call context
    """
    if cm is None:
        logger.error("MemoManager is None in send_agent_greeting for agent=%s", agent_name)
        return

    if agent_name == cm_get(cm, LAST_ANNOUNCED_KEY):
        return  # Prevent duplicate greeting

    # Get agent voice configuration
    agent = get_agent_instance(ws, agent_name)
    voice_name = getattr(agent, "voice_name", None) if agent else None
    voice_style = getattr(agent, "voice_style", "chat") if agent else "chat"
    voice_rate = getattr(agent, "voice_rate", "+2%") if agent else "+2%"
    actual_agent_name = getattr(agent, "name", None) or agent_name

    # Track greeting count per agent
    state_counts: Dict[str, int] = getattr(ws.state, APP_GREETS_ATTR, {})
    if not hasattr(ws.state, APP_GREETS_ATTR):
        ws.state.__setattr__(APP_GREETS_ATTR, state_counts)

    counter = state_counts.get(actual_agent_name, 0)
    state_counts[actual_agent_name] = counter + 1
    is_returning = counter > 0

    # Get customer context
    caller_name = cm_get(cm, "caller_name")
    topic = cm_get(cm, "topic")

    # Create retail-specific greeting
    greeting = create_retail_greeting(
        agent_name=agent_name,
        caller_name=caller_name,
        topic=topic,
        is_returning=is_returning,
    )

    # Add to conversation history
    cm.append_to_history(actual_agent_name, "assistant", greeting)
    cm_set(cm, **{LAST_ANNOUNCED_KEY: agent_name})

    # Send greeting via appropriate channel
    if is_acs:
        logger.info("ACS greeting #%s for %s (voice: %s): %s", counter + 1, agent_name, voice_name or "default", greeting)
        
        # Map agent names to display names
        agent_display_names = {
            "ShoppingConcierge": "Shopping Assistant",
            "PersonalStylist": "Personal Stylist",
            "PostSale": "Order Support"
        }
        agent_sender = agent_display_names.get(agent_name, "Assistant")

        _, session_id = get_correlation_context(ws, cm)
        await broadcast_message(None, greeting, agent_sender, app_state=ws.app.state, session_id=session_id)
        
        try:
            await send_response_to_acs(
                ws=ws,
                text=greeting,
                blocking=False,
                latency_tool=ws.state.lt,
                voice_name=voice_name,
                voice_style=voice_style,
                rate=voice_rate,
            )
        except Exception as exc:
            logger.error("Failed to send ACS greeting audio: %s", exc)
            logger.warning("ACS greeting sent as text only.")
    else:
        logger.info("WS greeting #%s for %s (voice: %s)", counter + 1, agent_name, voice_name or "default")
        _, session_id = get_correlation_context(ws, cm)
        envelope = make_status_envelope(message=greeting, session_id=session_id)
        
        if hasattr(ws.app.state, "conn_manager") and hasattr(ws.state, "conn_id"):
            await ws.app.state.conn_manager.send_to_connection(ws.state.conn_id, envelope)
        else:
            await ws.send_text(json.dumps({"type": "status", "message": greeting}))
        
        await send_tts_audio(
            greeting,
            ws,
            latency_tool=ws.state.lt,
            voice_name=voice_name,
            voice_style=voice_style,
            rate=voice_rate,
        )
