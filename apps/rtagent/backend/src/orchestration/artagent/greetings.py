from __future__ import annotations

import json
from typing import Any, Dict, Optional, TYPE_CHECKING

from fastapi import WebSocket

from .bindings import get_agent_instance
from .cm_utils import cm_get, cm_set, get_correlation_context
from .config import LAST_ANNOUNCED_KEY, APP_GREETS_ATTR
from config import ACS_STREAMING_MODE
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


def create_personalized_greeting(
    caller_name: Optional[str],
    agent_name: str, 
    customer_intelligence: Dict[str, Any],
    institution_name: str,
    topic: str
) -> str:
    """
    Create ultra-personalized greeting using 360° customer intelligence.
    
    Uses behavioral patterns, relationship context, account status, 
    and communication preferences for 10/10 customer experience.
    """
    try:
        # Safely handle caller name
        first_name = "there"  # Default fallback
        if caller_name and caller_name.strip():
            first_name = caller_name.split()[0] if caller_name.split() else "there"
        
        # Extract intelligence data
        relationship_context = customer_intelligence.get("relationship_context", {})
        account_status = customer_intelligence.get("account_status", {})
        memory_score = customer_intelligence.get("memory_score", {})
        conversation_context = customer_intelligence.get("conversation_context", {})
        active_alerts = customer_intelligence.get("active_alerts", [])
        
        # Get personalization elements
        relationship_tier = relationship_context.get("relationship_tier", "valued").lower()
        relationship_years = relationship_context.get("relationship_duration_years", 0)
        communication_style = memory_score.get("communication_style", "Direct/Business-focused")
        account_health = account_status.get("account_health_score", 95)
        
        # Use custom greeting if available
        custom_greeting = conversation_context.get("greeting_style", "")
        first_name = caller_name.split()[0] if caller_name and caller_name.strip() else "there"
        if custom_greeting and first_name in custom_greeting:
            # Use the pre-generated personalized greeting
            base_greeting = custom_greeting
        else:
            # Create greeting based on relationship tier and communication style
            # first_name already set above with null safety
            
            if "Direct" in communication_style or "Business" in communication_style:
                base_greeting = f"Good morning {first_name}. This is your {agent_name} specialist at {institution_name}"
            elif "Relationship" in communication_style:
                base_greeting = f"Hello {first_name}, it's great to hear from you again. This is your dedicated {agent_name} specialist"
            else:  # Detail-oriented
                base_greeting = f"Good morning {first_name}. I'm your {agent_name} specialist, and I have your complete account profile ready"
        
        # Add relationship recognition
        if relationship_years >= 3:
            loyalty_note = f"I see you've been with us for {int(relationship_years)} years as a {relationship_tier} client"
        elif relationship_tier in ["platinum", "gold"]:
            loyalty_note = f"As our {relationship_tier} client, you have priority access to our specialist team"
        else:
            loyalty_note = f"I have your complete {relationship_tier} account profile here"
        
        # Add proactive service based on account status
        if active_alerts:
            alert_count = len(active_alerts)
            service_note = f"I see you have {alert_count} account update{'s' if alert_count > 1 else ''} I can address"
        elif account_health >= 95:
            service_note = "Your account is in excellent standing, and I'm here to ensure it stays that way"
        else:
            service_note = "I'm here to help with any concerns about your account"
        
        # Combine into ultra-personalized greeting
        personalized_greeting = f"{base_greeting}. {loyalty_note}. {service_note}. How can I assist you today?"
        
        return personalized_greeting
        
    except Exception as e:
        logger.warning(f"Error creating personalized greeting: {e}")
        # Fallback to enhanced but simpler greeting
        first_name = caller_name.split()[0] if caller_name else "there"
        return (
            f"Good morning {first_name}, this is your {agent_name} specialist from {institution_name}. "
            f"I have your account information ready and I'm here to help. What can I do for you today?"
        )


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
    Emit a greeting when switching to a specialist agent (behavior-preserving).
    """
    if cm is None:
        logger.error("MemoManager is None in send_agent_greeting for agent=%s", agent_name)
        return

    if agent_name == cm_get(cm, LAST_ANNOUNCED_KEY):
        return  # prevent duplicate greeting

    agent = get_agent_instance(ws, agent_name)
    voice_name = getattr(agent, "voice_name", None) if agent else None
    voice_style = getattr(agent, "voice_style", "chat") if agent else "chat"
    voice_rate = getattr(agent, "voice_rate", "+3%") if agent else "+3%"
    actual_agent_name = getattr(agent, "name", None) or agent_name

    state_counts: Dict[str, int] = getattr(ws.state, APP_GREETS_ATTR, {})
    if not hasattr(ws.state, APP_GREETS_ATTR):
        ws.state.__setattr__(APP_GREETS_ATTR, state_counts)

    counter = state_counts.get(actual_agent_name, 0)
    state_counts[actual_agent_name] = counter + 1

    caller_name = cm_get(cm, "caller_name")
    topic = cm_get(cm, "topic") or cm_get(cm, "claim_intent") or "your policy"
    
    # 🎯 ULTRA-PERSONALIZED GREETING USING CUSTOMER INTELLIGENCE
    customer_intelligence = cm_get(cm, "customer_intelligence")
    institution_name = cm_get(cm, "institution_name")
    
    if customer_intelligence and counter == 0:
        # Use 360° customer intelligence for 10/10 personalized experience
        greeting = create_personalized_greeting(
            caller_name=caller_name,
            agent_name=agent_name,
            customer_intelligence=customer_intelligence,
            institution_name=institution_name,
            topic=topic
        )
    elif counter == 0:
        # Fallback to enhanced greeting with available data
        if institution_name:
            greeting = (
                f"Good morning {caller_name}, I see you're calling from {institution_name}. "
                f"This is your {agent_name} specialist. I'm here to help you with any concerns about {topic}. "
                f"How can I assist you today?"
            )
        else:
            greeting = (
                f"Hi {caller_name}, this is the {agent_name} specialist agent. "
                f"I understand you're calling about {topic}. How can I help you further?"
            )
    else:
        # Return customer greeting with intelligence
        if customer_intelligence:
            relationship_tier = customer_intelligence.get("relationship_context", {}).get("relationship_tier", "valued")
            greeting = (
                f"Welcome back, {caller_name}. This is your {agent_name} specialist again. "
                f"As a {relationship_tier.lower()} client, you have my full attention. "
                f"What else can I help you with today?"
            )
        else:
            greeting = (
                f"Welcome back, {caller_name}. {agent_name} specialist here. "
                f"What else can I assist you with?"
            )

    cm.append_to_history(actual_agent_name, "assistant", greeting)
    cm_set(cm, **{LAST_ANNOUNCED_KEY: agent_name})

    if is_acs:
        logger.info("ACS greeting #%s for %s (voice: %s): %s", counter + 1, agent_name, voice_name or "default", greeting)
        if agent_name == "Fraud":
            agent_sender = "Fraud Specialist"
        elif agent_name == "Agency":
            agent_sender = "Transfer Agency Specialist"
        elif agent_name == "Compliance":
            agent_sender = "Compliance Specialist"
        elif agent_name == "Trading":
            agent_sender = "Trading Specialist"
        else:
            agent_sender = "Assistant"

        _, session_id = get_correlation_context(ws, cm)
        await broadcast_message(None, greeting, agent_sender, app_state=ws.app.state, session_id=session_id)
        try:
            stream_mode = getattr(ws.state, "stream_mode", ACS_STREAMING_MODE)
            await send_response_to_acs(
                ws=ws,
                text=greeting,
                blocking=False,
                latency_tool=ws.state.lt,
                voice_name=voice_name,
                voice_style=voice_style,
                rate=voice_rate,
                stream_mode=stream_mode,
            )
        except Exception as exc:  # pragma: no cover
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
