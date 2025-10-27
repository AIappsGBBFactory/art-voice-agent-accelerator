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
    Inspect structured tool outputs and update core-memory accordingly.

    Behavior-preserving port of the original _process_tool_response.
    """
    if cm is None:
        logger.error("MemoManager is None in process_tool_response")
        return

    if not isinstance(resp, dict):
        return

    prev_agent: str | None = cm_get(cm, "active_agent")

    handoff_type = _get_field(resp, "handoff")
    target_agent = _get_field(resp, "target_agent")
    topic = _get_field(resp, "topic")

    # Financial Services Hand-offs (post-auth) �
    if handoff_type in ["Transfer", "Fraud", "Compliance", "Trading"] and target_agent:
        # Map handoff types to agent names
        handoff_to_agent_map = {
            "Transfer": "Agency",
            "Fraud": "Fraud", 
            "Compliance": "Compliance",
            "Trading": "Trading"
        }
        
        new_agent = handoff_to_agent_map.get(handoff_type, target_agent)
        
        # Ensure the agent exists in specialists
        if new_agent in SPECIALISTS or get_specialist(new_agent) is not None:
            pass  # Agent exists
        else:
            logger.warning("Agent %s not found in specialists, using target_agent: %s", new_agent, target_agent)
            new_agent = target_agent
        
        cm_set(cm, active_agent=new_agent, topic=topic)
        sync_voice_from_agent(cm, ws, new_agent)
        logger.info("Financial Services Hand-off → %s (type: %s)", new_agent, handoff_type)
        if new_agent != prev_agent:
            await send_agent_greeting(cm, ws, new_agent, is_acs)

    elif handoff_type == "human_agent":
        reason = _get_field(resp, "reason") or _get_field(resp, "escalation_reason")
        cm_set(cm, escalated=True, escalation_reason=reason)
