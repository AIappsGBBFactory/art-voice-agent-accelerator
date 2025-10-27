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
        # Connect to users collection (customer intelligence is embedded in user profiles)
        intelligence_manager = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="users"
        )
        
        # Fetch customer intelligence using flexible client_id query
        client_query = {
            "$or": [
                {"_id": client_id},
                {"client_id": client_id},
                {"full_name": client_id.replace("_", " ").title()}
            ]
        }
        
        # Use query_documents to get user profile with embedded intelligence
        user_profiles = await asyncio.to_thread(
            intelligence_manager.query_documents,
            query=client_query
        )
        
        intelligence_profile = None
        if user_profiles and len(user_profiles) > 0:
            # Extract customer intelligence from user profile
            user_profile = user_profiles[0]
            intelligence_profile = user_profile.get('customer_intelligence', {})
            # Also include basic user info for context
            intelligence_profile['full_name'] = user_profile.get('full_name')
            intelligence_profile['client_id'] = user_profile.get('client_id')
            intelligence_profile['institution_name'] = user_profile.get('institution_name')
        
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

    # Handle successful authentication with intent-based routing
    if isinstance(result, dict) and result.get("authenticated"):
        # Handle successful authentication with intent-based routing
        caller_name: str | None = result.get("caller_name")
        client_id: str | None = result.get("client_id") 
        institution_name: str | None = result.get("institution_name")
        topic: str | None = result.get("topic") or result.get("service_type", "your account")
        intent: str = result.get("intent", "fraud")  # Default to fraud for financial services
        
        # Route to specialist agent based on intent
        if intent == "transfer_agency":
            active_agent = "Agency"  # Route to Transfer Agency coordinator
        elif intent == "fraud":
            active_agent = "Fraud"
        else:
            active_agent = "Fraud"  # Default fallback to fraud for financial services

        # 🧠 FETCH CUSTOMER INTELLIGENCE FOR PERSONALIZED EXPERIENCE  
        customer_intelligence = await fetch_customer_intelligence(client_id) if client_id else None
        
        cm_set(
            cm,
            authenticated=True,
            caller_name=caller_name,
            client_id=client_id,
            institution_name=institution_name,
            topic=topic,
            active_agent=active_agent,
            # 🎯 PERSONALIZATION DATA
            customer_intelligence=customer_intelligence,
        )

        logger.info(
            "Financial MFA auth OK – session=%s caller=%s client_id=%s intent=%s → %s agent (Intelligence: %s)",
            cm.session_id, caller_name, client_id, intent, active_agent,
            "✅ Loaded" if customer_intelligence else "❌ Not Found"
        )

        sync_voice_from_agent(cm, ws, active_agent)
        await send_agent_greeting(cm, ws, active_agent, is_acs)
