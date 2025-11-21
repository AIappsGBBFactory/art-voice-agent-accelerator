"""
Banking agent handoff utilities for multi-agent voice orchestration.

Implements handoff functions for Erica Concierge to route customers to:
- Card Recommendation Agent (credit card product specialist)
- Investment Advisor Agent (retirement & 401k specialist)

Follows VoiceLive handoff pattern with orchestrator-friendly payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, TypedDict

from utils.ml_logging import get_logger

logger = get_logger("banking_handoffs")


def _cleanup_context(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None, empty strings, and control flags from context."""
    return {
        key: value for key, value in (data or {}).items()
        if value not in (None, "", [], {}, False)
    }


def _build_handoff_payload(
    *,
    target_agent: str,
    message: str,
    summary: str,
    context: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build standardized handoff payload for orchestrator."""
    payload = {
        "handoff": True,
        "target_agent": target_agent,
        "message": message,
        "handoff_summary": summary,
        "handoff_context": _cleanup_context(context),
    }
    if extra:
        payload.update(extra)
    return payload


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# CARD RECOMMENDATION AGENT HANDOFF
# ═══════════════════════════════════════════════════════════════════


class HandoffCardRecommendationArgs(TypedDict, total=False):
    """Input schema for handoff_card_recommendation."""
    client_id: str
    customer_goal: str
    spending_preferences: str
    current_cards: str


async def handoff_card_recommendation(args: HandoffCardRecommendationArgs) -> Dict[str, Any]:
    """
    Hand off customer to Card Recommendation Agent.
    
    Use when customer asks about:
    - Credit card recommendations
    - Balance transfer offers
    - Rewards program comparisons
    - Fee disputes or card upgrades
    
    Parameters:
    - client_id: Customer identifier
    - customer_goal: What they want (lower fees, better rewards, balance transfer)
    - spending_preferences: Where they spend most (travel, dining, groceries, etc.)
    - current_cards: Brief description of cards they currently have
    
    The Card Recommendation Agent will search products and provide tailored recommendations.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return {
            "success": False,
            "message": "Invalid request format. Please provide handoff details."
        }
    
    try:
        client_id = (args.get("client_id") or "").strip()
        customer_goal = (args.get("customer_goal") or "").strip()
        spending_prefs = (args.get("spending_preferences") or "").strip()
        current_cards = (args.get("current_cards") or "").strip()
        
        if not client_id:
            return {
                "success": False,
                "message": "client_id is required for handoff."
            }
        
        logger.info(
            "💳 Handoff to Card Recommendation Agent | client=%s goal=%s",
            client_id, customer_goal
        )
        
        context = {
            "client_id": client_id,
            "customer_goal": customer_goal,
            "spending_preferences": spending_prefs,
            "current_cards": current_cards,
            "handoff_timestamp": _utc_now(),
            "previous_agent": "EricaConcierge"
        }
        
        # Transition message that gets spoken via trigger_response(say=...)
        transition_message = "Let me find the best card options for you."
        
        return _build_handoff_payload(
            target_agent="CardRecommendation",
            message=transition_message,  # This gets spoken, then agent continues
            summary=f"Card recommendation request: {customer_goal or 'general inquiry'}",
            context=context,
            extra={"should_interrupt_playback": True}
        )
    
    except Exception as exc:
        logger.error("Card recommendation handoff failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "Unable to transfer to card specialist. Please try again."
        }


# ═══════════════════════════════════════════════════════════════════
# INVESTMENT ADVISOR AGENT HANDOFF
# ═══════════════════════════════════════════════════════════════════


class HandoffInvestmentAdvisorArgs(TypedDict, total=False):
    """Input schema for handoff_investment_advisor."""
    client_id: str
    topic: str
    employment_change: str
    retirement_question: str


async def handoff_investment_advisor(args: HandoffInvestmentAdvisorArgs) -> Dict[str, Any]:
    """
    Hand off customer to Investment Advisor Agent.
    
    Use when customer asks about:
    - 401(k) rollover after job change
    - IRA account questions
    - Retirement planning and readiness
    - Investment product comparisons
    - Contribution rate optimization
    
    Parameters:
    - client_id: Customer identifier
    - topic: Main topic (rollover, IRA, retirement planning, etc.)
    - employment_change: Details if they changed jobs (optional)
    - retirement_question: Specific question about retirement
    
    The Investment Advisor Agent specializes in retirement accounts and rollover guidance.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return {
            "success": False,
            "message": "Invalid request format. Please provide handoff details."
        }
    
    try:
        client_id = (args.get("client_id") or "").strip()
        topic = (args.get("topic") or "retirement planning").strip()
        employment_change = (args.get("employment_change") or "").strip()
        retirement_question = (args.get("retirement_question") or "").strip()
        
        if not client_id:
            return {
                "success": False,
                "message": "client_id is required for handoff."
            }
        
        logger.info(
            "🏦 Handoff to Investment Advisor Agent | client=%s topic=%s",
            client_id, topic
        )
        
        context = {
            "client_id": client_id,
            "topic": topic,
            "employment_change": employment_change,
            "retirement_question": retirement_question,
            "handoff_timestamp": _utc_now(),
            "previous_agent": "EricaConcierge"
        }
        
        # Transition message that gets spoken via trigger_response(say=...)
        transition_message = "Let me look at your retirement accounts and options."
        
        return _build_handoff_payload(
            target_agent="InvestmentAdvisor",
            message=transition_message,  # This gets spoken, then agent continues
            summary=f"Retirement inquiry: {topic}",
            context=context,
            extra={"should_interrupt_playback": True}
        )
    
    except Exception as exc:
        logger.error("Investment advisor handoff failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "Unable to transfer to investment specialist. Please try again."
        }


# ═══════════════════════════════════════════════════════════════════
# ERICA CONCIERGE RETURN HANDOFF (from specialist agents back to concierge)
# ═══════════════════════════════════════════════════════════════════


class HandoffEricaConciergeArgs(TypedDict, total=False):
    """Input schema for handoff_erica_concierge."""
    client_id: str
    previous_topic: str
    resolution_summary: str


async def handoff_erica_concierge(args: HandoffEricaConciergeArgs) -> Dict[str, Any]:
    """
    Return customer to Erica Concierge from specialist agent.
    
    Use when:
    - Specialist agent has completed their task
    - Customer needs help with a different topic
    - Customer asks to go back to main assistant
    
    Parameters:
    - client_id: Customer identifier
    - previous_topic: What the specialist agent helped with
    - resolution_summary: Brief summary of what was accomplished
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return {
            "success": False,
            "message": "Invalid request format."
        }
    
    try:
        client_id = (args.get("client_id") or "").strip()
        previous_topic = (args.get("previous_topic") or "").strip()
        resolution_summary = (args.get("resolution_summary") or "").strip()
        
        if not client_id:
            return {
                "success": False,
                "message": "client_id is required."
            }
        
        logger.info(
            "🔄 Returning to Erica Concierge | client=%s from_topic=%s",
            client_id, previous_topic
        )
        
        context = {
            "client_id": client_id,
            "previous_topic": previous_topic,
            "resolution_summary": resolution_summary,
            "handoff_timestamp": _utc_now()
        }
        
        return _build_handoff_payload(
            target_agent="EricaConcierge",
            message="",
            summary=f"Returning from {previous_topic}",
            context=context,
            extra={"should_interrupt_playback": True}
        )
    
    except Exception as exc:
        logger.error("Erica concierge handoff failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "message": "Unable to return to main assistant."
        }
