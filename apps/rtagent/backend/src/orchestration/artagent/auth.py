from __future__ import annotations

import asyncio
from typing import Any, Dict, TYPE_CHECKING

from fastapi import WebSocket

from .bindings import get_agent_instance
from .cm_utils import cm_get, cm_set
from .greetings import send_agent_greeting, sync_voice_from_agent
from .latency import track_latency
from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager


async def fetch_customer_intelligence(client_id: str) -> Dict[str, Any] | None:
    """
    Fetch comprehensive customer intelligence for 10/10 personalized experience.
    
    Uses client_id to retrieve complete 360° customer profile including:
    - Behavioral patterns & spending habits
    - Communication preferences & memory scores  
    - Account status & relationship context
    - Fraud-specific intelligence & risk profile
    - Personalized greeting templates & talking points
    """
    if not client_id:
        return None
        
    try:
        # Connect to customer intelligence collection
        intelligence_manager = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="customer_intelligence"
        )
        
        # Fetch customer intelligence using client_id
        intelligence_profile = await asyncio.to_thread(
            intelligence_manager.read_document,
            query={"client_id": client_id}
        )
        
        if intelligence_profile:
            logger.info(f"✅ Customer intelligence loaded for client {client_id}: "
                       f"Tier={intelligence_profile.get('relationship_context', {}).get('relationship_tier', 'Unknown')}, "
                       f"Communication={intelligence_profile.get('memory_score', {}).get('communication_style', 'Unknown')}")
            return intelligence_profile
        else:
            logger.warning(f"❌ No customer intelligence found for client_id: {client_id}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error fetching customer intelligence for client_id {client_id}: {e}")
        return None


async def run_auth_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """
    Run the Financial MFA Auth agent once per session until authenticated.
    
    The auth agent handles complete authentication flow including MFA and 
    direct handoffs to specialist agents (Fraud/Transfer Agency).
    """
    if cm is None:
        logger.error("MemoManager is None in run_auth_agent")
        raise ValueError("MemoManager (cm) parameter cannot be None in run_auth_agent")

    auth_agent = get_agent_instance(ws, "AutoAuth")

    async with track_latency(ws.state.lt, "auth_agent", ws.app.state.redis, meta={"agent": "AutoAuth"}):
        result: Dict[str, Any] | Any = await auth_agent.respond(  # type: ignore[union-attr]
            cm, utterance, ws, is_acs=is_acs
        )

    # Handle human escalations from auth agent
    if isinstance(result, dict) and result.get("handoff") == "human_agent":
        reason = result.get("reason") or result.get("escalation_reason")
        cm_set(cm, escalated=True, escalation_reason=reason)
        logger.warning("Escalation during auth – session=%s reason=%s", cm.session_id, reason)
        return

    # Handle direct agent handoffs from auth agent after successful MFA
    if isinstance(result, dict) and result.get("handoff") in ["Fraud", "Claims", "Transfer"]:
        # Auth agent completed MFA and is handing off to specialist
        handoff_agent = result.get("handoff")
        caller_name = result.get("caller_name") or result.get("client_name")
        client_id = result.get("client_id")
        institution_name = result.get("institution_name")
        topic = result.get("topic") or result.get("service_type", "your account")
        
        logger.info(
            "Auth completed with MFA – session=%s caller=%s client_id=%s → %s agent",
            cm.session_id, caller_name, client_id, handoff_agent
        )
        
        # 🧠 FETCH CUSTOMER INTELLIGENCE FOR PERSONALIZED EXPERIENCE
        customer_intelligence = await fetch_customer_intelligence(client_id) if client_id else None
        
        # Store authentication and customer data in memory
        cm_set(
            cm,
            authenticated=True,
            caller_name=caller_name,
            client_id=client_id,
            institution_name=institution_name,
            topic=topic,
            active_agent=handoff_agent,
            # 🎯 PERSONALIZATION DATA 
            customer_intelligence=customer_intelligence,
        )
        
        # Sync voice and send specialist greeting
        sync_voice_from_agent(cm, ws, handoff_agent)
        await send_agent_greeting(cm, ws, handoff_agent, is_acs)
        return

    # Legacy fallback for old insurance authentication (if still needed)
    if isinstance(result, dict) and result.get("authenticated"):
        # Support legacy insurance authentication flow
        caller_name: str | None = result.get("caller_name")
        client_id: str | None = result.get("client_id") or result.get("policy_id")  # Legacy support
        institution_name: str | None = result.get("institution_name")
        claim_intent: str | None = result.get("claim_intent")
        topic: str | None = result.get("topic") or "your policy"
        intent: str = result.get("intent", "general")
        
        active_agent: str = "Claims" if intent == "claims" else "Fraud"

        # 🧠 FETCH CUSTOMER INTELLIGENCE FOR PERSONALIZED EXPERIENCE  
        customer_intelligence = await fetch_customer_intelligence(client_id) if client_id else None
        
        cm_set(
            cm,
            authenticated=True,
            caller_name=caller_name,
            client_id=client_id,
            institution_name=institution_name,
            claim_intent=claim_intent,
            topic=topic,
            active_agent=active_agent,
            # 🎯 PERSONALIZATION DATA
            customer_intelligence=customer_intelligence,
        )

        logger.info(
            "Legacy auth OK – session=%s caller=%s client_id=%s → %s agent (Intelligence: %s)",
            cm.session_id, caller_name, client_id, active_agent,
            "✅ Loaded" if customer_intelligence else "❌ Not Found"
        )

        sync_voice_from_agent(cm, ws, active_agent)
        await send_agent_greeting(cm, ws, active_agent, is_acs)
