"""
Retail Agent Specialist Handlers
=================================

Specialist agent handlers for retail voice assistant use case.
Supports Shopping Concierge (entry point), Personal Stylist, and Post-Sale agents.
"""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from fastapi import WebSocket

from .cm_utils import cm_get
from .greetings import send_agent_greeting
from .latency import track_latency
from .bindings import get_agent_instance
from .tools import process_tool_response
from utils.ml_logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager


async def _run_specialist_base(
    *,
    agent_key: str,
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    is_acs: bool,
    context_message: str,
    respond_kwargs: Dict[str, Any],
    latency_label: str,
) -> None:
    """
    Shared runner for specialist agents (behavior-preserving).
    """
    agent = get_agent_instance(ws, agent_key)

    cm.append_to_history(getattr(agent, "name", agent_key), "assistant", context_message)

    async with track_latency(ws.state.lt, latency_label, ws.app.state.redis, meta={"agent": agent_key}):
        resp = await agent.respond(  # type: ignore[union-attr]
            cm,
            utterance,
            ws,
            is_acs=is_acs,
            **respond_kwargs,
        )

    await process_tool_response(cm, resp, ws, is_acs)


async def run_shopping_concierge_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """
    Handle Shopping Concierge agent - entry point for retail voice assistant.
    Routes to product discovery, general inquiries, and specialist handoffs.
    """
    if cm is None:
        logger.error("MemoManager is None in run_shopping_concierge_agent")
        raise ValueError("MemoManager (cm) parameter cannot be None")

    # Get user profile from core memory for dynamic prompt injection
    current_user = cm.get_value_from_corememory("current_user") or {}
    user_name = current_user.get("full_name") if isinstance(current_user, dict) else None
    if not user_name:
        user_name = cm.get_value_from_corememory("caller_name") or "valued customer"
    
    # Extract nested data for Jinja2 template access
    loyalty_data = current_user.get("dynamics365_data", {}) if isinstance(current_user, dict) else {}
    location_data = current_user.get("location", {}) if isinstance(current_user, dict) else {}
    preferences_data = current_user.get("preferences", {}) if isinstance(current_user, dict) else {}
    
    # Flatten for easy Jinja2 access
    customer_name = user_name
    loyalty_tier = loyalty_data.get("loyalty_tier", "Member")
    location = f"{location_data.get('city', 'US')}, {location_data.get('state', '')}".strip(", ") or "US"
    style_preferences = ", ".join(preferences_data.get("style", [])) or "Not specified"
    recent_searches = ", ".join(current_user.get("search_history", [])[:3]) if isinstance(current_user, dict) else ""
    
    context_msg = f"Shopping Concierge serving {customer_name} ({loyalty_tier})"
    
    # Pass flattened data for Jinja2 template
    await _run_specialist_base(
        agent_key="ShoppingConcierge",
        cm=cm,
        utterance=utterance,
        ws=ws,
        is_acs=is_acs,
        context_message=context_msg,
        respond_kwargs={
            "user_profile": current_user,  # Full profile for reference
            "customer_name": customer_name,
            "loyalty_tier": loyalty_tier,
            "location": location,
            "style_preferences": style_preferences,
            "recent_searches": recent_searches,
        },
        latency_label="shopping_concierge_agent",
    )


async def run_personal_stylist_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """
    Handle Personal Stylist agent - personalized style recommendations and outfit building.
    Receives handoffs from Shopping Concierge for styling consultations.
    """
    if cm is None:
        logger.error("MemoManager is None in run_personal_stylist_agent")
        raise ValueError("MemoManager (cm) parameter cannot be None")

    # Get user profile from core memory for dynamic prompt injection
    current_user = cm.get_value_from_corememory("current_user") or {}
    user_name = current_user.get("full_name") if isinstance(current_user, dict) else None
    if not user_name:
        user_name = cm.get_value_from_corememory("caller_name") or "valued customer"
    
    # Extract nested data for Jinja2 template access
    loyalty_data = current_user.get("dynamics365_data", {}) if isinstance(current_user, dict) else {}
    location_data = current_user.get("location", {}) if isinstance(current_user, dict) else {}
    preferences_data = current_user.get("preferences", {}) if isinstance(current_user, dict) else {}
    
    # Flatten for easy Jinja2 access
    customer_name = user_name
    loyalty_tier = loyalty_data.get("loyalty_tier", "Member")
    location = f"{location_data.get('city', 'US')}, {location_data.get('state', '')}".strip(", ") or "US"
    style_preferences = ", ".join(preferences_data.get("style", [])) or "Not specified"
    recent_searches = ", ".join(current_user.get("search_history", [])[:3]) if isinstance(current_user, dict) else ""
    
    context_msg = f"Personal Stylist consulting with {customer_name} ({loyalty_tier})"
    
    # Pass flattened data for Jinja2 template
    await _run_specialist_base(
        agent_key="PersonalStylist",
        cm=cm,
        utterance=utterance,
        ws=ws,
        is_acs=is_acs,
        context_message=context_msg,
        respond_kwargs={
            "user_profile": current_user,  # Full profile for reference
            "customer_name": customer_name,
            "loyalty_tier": loyalty_tier,
            "location": location,
            "style_preferences": style_preferences,
            "recent_searches": recent_searches,
        },
        latency_label="personal_stylist_agent",
    )


async def run_postsale_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """
    Handle Post-Sale Support agent - order tracking, returns, and customer service.
    Receives handoffs from Shopping Concierge for post-purchase inquiries.
    """
    if cm is None:
        logger.error("MemoManager is None in run_postsale_agent")
        raise ValueError("MemoManager (cm) parameter cannot be None")

    # Get user profile from core memory for dynamic prompt injection
    current_user = cm.get_value_from_corememory("current_user") or {}
    user_name = current_user.get("full_name") if isinstance(current_user, dict) else None
    if not user_name:
        user_name = cm.get_value_from_corememory("caller_name") or "valued customer"
    
    # Extract nested data for Jinja2 template access
    loyalty_data = current_user.get("dynamics365_data", {}) if isinstance(current_user, dict) else {}
    location_data = current_user.get("location", {}) if isinstance(current_user, dict) else {}
    preferences_data = current_user.get("preferences", {}) if isinstance(current_user, dict) else {}
    
    # Flatten for easy Jinja2 access
    customer_name = user_name
    loyalty_tier = loyalty_data.get("loyalty_tier", "Member")
    location = f"{location_data.get('city', 'US')}, {location_data.get('state', '')}".strip(", ") or "US"
    style_preferences = ", ".join(preferences_data.get("style", [])) or "Not specified"
    recent_searches = ", ".join(current_user.get("search_history", [])[:3]) if isinstance(current_user, dict) else ""
    
    context_msg = f"Post-Sale Support assisting {customer_name} ({loyalty_tier})"
    
    # Pass flattened data for Jinja2 template
    await _run_specialist_base(
        agent_key="PostSale",
        cm=cm,
        utterance=utterance,
        ws=ws,
        is_acs=is_acs,
        context_message=context_msg,
        respond_kwargs={
            "user_profile": current_user,  # Full profile for reference
            "customer_name": customer_name,
            "loyalty_tier": loyalty_tier,
            "location": location,
            "style_preferences": style_preferences,
            "recent_searches": recent_searches,
        },
        latency_label="postsale_agent",
    )
