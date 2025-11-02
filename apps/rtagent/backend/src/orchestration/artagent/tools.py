from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from fastapi import WebSocket

from .cm_utils import cm_get, cm_set
from .greetings import send_agent_greeting, sync_voice_from_agent
from .registry import get_specialist
from .config import SPECIALISTS
from utils.ml_logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager


def _get_field(resp: Dict[str, Any], key: str) -> Any:
    """
    Return resp[key] or resp['data'][key] if nested.
    """
    if key in resp:
        return resp[key]
    return resp.get("data", {}).get(key) if isinstance(resp.get("data"), dict) else None


async def process_tool_response(cm: "MemoManager", resp: Any, ws: WebSocket, is_acs: bool) -> None:
    """
    Process tool outputs and route agent handoffs for retail voice assistant.
    
    Handles:
    - Retail agent handoffs (ShoppingConcierge ↔ PersonalStylist ↔ PostSale)
    - Human agent escalations
    - Context preservation across handoffs
    """
    if cm is None:
        logger.error("MemoManager is None in process_tool_response")
        return

    if not isinstance(resp, dict):
        return

    prev_agent: str | None = cm_get(cm, "active_agent")

    handoff_to = _get_field(resp, "handoff_to")
    escalate_to = _get_field(resp, "escalate_to")
    topic = _get_field(resp, "topic")

    # ═══════════════════════════════════════════════════════════════════
    # Retail Agent Handoffs
    # ═══════════════════════════════════════════════════════════════════
    if handoff_to:
        # Map retail tool handoff targets to orchestrator agent names
        retail_handoff_map = {
            "personal_stylist": "PersonalStylist",
            "postsale": "PostSale",
            "shopping_concierge": "ShoppingConcierge",
        }
        
        new_agent = retail_handoff_map.get(handoff_to.lower(), handoff_to)
        
        # Verify agent is registered
        if new_agent in SPECIALISTS or get_specialist(new_agent) is not None:
            cm_set(cm, active_agent=new_agent, topic=topic)
            sync_voice_from_agent(cm, ws, new_agent)
            logger.info("Handoff: %s → %s (topic: %s)", prev_agent or "none", new_agent, topic or "general")
            if new_agent != prev_agent:
                await send_agent_greeting(cm, ws, new_agent, is_acs)
        else:
            logger.warning("Agent %s not found in specialists (handoff_to=%s)", new_agent, handoff_to)

    # ═══════════════════════════════════════════════════════════════════
    # Human Escalation
    # ═══════════════════════════════════════════════════════════════════
    elif escalate_to == "human_agent":
        reason = _get_field(resp, "reason") or _get_field(resp, "escalation_reason") or _get_field(resp, "issue")
        urgency = _get_field(resp, "urgency") or "medium"
        cm_set(cm, escalated=True, escalation_reason=reason, escalation_urgency=urgency)
        logger.warning("Escalation to human agent: reason=%s, urgency=%s", reason, urgency)
