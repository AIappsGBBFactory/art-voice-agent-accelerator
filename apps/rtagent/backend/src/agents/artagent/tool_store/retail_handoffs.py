"""
ARTAgent Retail Handoff Tools
==============================

Agent routing and handoff functions for retail multi-agent system:
- Shopping Concierge → Personal Stylist
- Shopping Concierge → Post-Sale Agent
- Personal Stylist → Post-Sale Agent  
- Any Agent → Shopping Concierge (fallback)

Follows ARTAgent handoff pattern with clean, professional transitions.
Context preservation handled by orchestrator through CoreMemory injection in prompts.

Author: Pablo Salvador Lopez
Organization: GBB AI
"""

from typing import Any, Dict, Optional, TypedDict

from apps.rtagent.backend.src.agents.artagent.tool_store.functions_helper import _json
from utils.ml_logging import get_logger

logger = get_logger("retail_handoffs")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 1: Concierge → Stylist
# ═══════════════════════════════════════════════════════════════════

class HandoffToStylistArgs(TypedDict):
    """Schema for handoff to Personal Stylist Agent"""
    query_context: str          # What customer is looking for
    preferences: Optional[str]  # Known preferences (colors, style, etc.)


async def handoff_to_stylist(args: HandoffToStylistArgs) -> Dict[str, Any]:
    """
    Transfer customer to Personal Stylist Agent for personalized fashion advice.
    
    Use When Customer Needs:
        - Personalized styling advice and outfit coordination
        - Fashion recommendations for specific events (wedding, date, interview)
        - Gift suggestions with recipient context
        - Context-aware searches (weather, formality, age group)
    
    Trigger Phrases:
        - "what should I wear to..."
        - "help me find an outfit for..."
        - "style me for..."
        - "gift for [person]"
    
    Args:
        query_context: Summary of customer's styling need (required)
        preferences: Known style preferences (colors, brands, formality)
    
    Returns:
        Handoff confirmation with customer context for stylist
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for handoff_to_stylist")
        return _json(False, "Unable to transfer to stylist. Please repeat your request.")
    
    try:
        query_context = (args.get("query_context") or "").strip()
        preferences = (args.get("preferences") or "").strip()
        
        if not query_context:
            return _json(
                False,
                "I need more details about what you're looking for before connecting you to our Personal Stylist."
            )
        
        logger.info(f"HANDOFF: Concierge → Stylist | context='{query_context[:100]}'")
        
        return _json(
            True,
            "Perfect! Let me connect you with our Personal Stylist who specializes in personalized recommendations. One moment please...",
            handoff_to="personal_stylist",
            query_context=query_context,
            preferences=preferences,
            handoff_reason="Customer needs personalized styling advice"
        )
    
    except Exception as e:
        logger.error(f"Handoff to stylist failed: {e}", exc_info=True)
        return _json(False, "I'm having trouble with that transfer. Let me try to help you directly.")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 2: Concierge → Post-Sale
# ═══════════════════════════════════════════════════════════════════

class HandoffToPostSaleArgs(TypedDict):
    """Schema for handoff to Post-Sale Agent"""
    intent: str                 # checkout, return, track_order, exchange
    cart_items: Optional[str]   # Products customer wants to buy (product IDs or summary)


async def handoff_to_postsale(args: HandoffToPostSaleArgs) -> Dict[str, Any]:
    """
    Transfer customer to Post-Sale Agent for transactions and order management.
    
    Use When Customer Wants To:
        - Complete purchase (checkout process)
        - Track existing order status
        - Initiate return or exchange
        - Apply discounts, gift cards, or loyalty points
    
    Trigger Phrases:
        - "I'll take it" / "checkout" / "buy this"
        - "track my order" / "where's my package"
        - "return this" / "I want a refund"
        - "exchange for different size"
    
    Args:
        intent: Transaction type (checkout, return, track_order, exchange) - required
        cart_items: Products to purchase or manage (product IDs or summary)
    
    Returns:
        Handoff confirmation with transaction context for post-sale agent
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for handoff_to_postsale")
        return _json(False, "Unable to process that request. Please try again.")
    
    try:
        intent = (args.get("intent") or "checkout").strip().lower()
        cart_items = (args.get("cart_items") or "").strip()
        
        # Validate intent
        valid_intents = ["checkout", "return", "track_order", "exchange"]
        if intent not in valid_intents:
            intent = "checkout"
        
        logger.info(f"HANDOFF: Concierge → Post-Sale | intent='{intent}'")
        
        # Context-specific handoff messages
        intent_messages = {
            "checkout": "Great choice! Let me connect you with our checkout specialist to complete your purchase. One moment...",
            "return": "I understand you'd like to return an item. Connecting you with our returns team now...",
            "track_order": "I'll transfer you to our order tracking specialist right away...",
            "exchange": "Let me connect you with our exchange specialist to help with that. One moment..."
        }
        
        handoff_msg = intent_messages.get(intent, "Transferring you to our transaction specialist. One moment...")
        
        return _json(
            True,
            handoff_msg,
            handoff_to="postsale",
            cart_items=cart_items,
            intent=intent,
            handoff_reason=f"Customer needs {intent} assistance"
        )
    
    except Exception as e:
        logger.error(f"Handoff to post-sale failed: {e}", exc_info=True)
        return _json(False, "I'm having trouble with that transfer. Let me try to assist you directly.")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 3: Stylist → Post-Sale
# ═══════════════════════════════════════════════════════════════════

class StylistHandoffToPostSaleArgs(TypedDict):
    """Schema for stylist to post-sale handoff"""
    recommended_items: str              # Products stylist suggested
    styling_context: Optional[str]      # Occasion, weather, style notes


async def stylist_handoff_to_postsale(args: StylistHandoffToPostSaleArgs) -> Dict[str, Any]:
    """
    Transfer customer from Personal Stylist to Post-Sale Agent after styling session.
    
    Use When:
        - Customer is ready to purchase stylist recommendations
        - Styling session complete and customer wants to checkout
    
    Args:
        recommended_items: Products from styling recommendations (required)
        styling_context: Context about occasion and style (e.g., "wedding attire")
    
    Returns:
        Handoff confirmation with styled items for checkout
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for stylist_handoff_to_postsale")
        return _json(False, "Unable to process that purchase request.")
    
    try:
        recommended_items = (args.get("recommended_items") or "").strip()
        styling_context = (args.get("styling_context") or "").strip()
        
        if not recommended_items:
            return _json(
                False,
                "I need to know which items you'd like to purchase before transferring to checkout."
            )
        
        logger.info(f"HANDOFF: Stylist → Post-Sale | items='{recommended_items[:100]}'")
        
        # Build context-aware handoff message
        handoff_msg = "Wonderful! I'm so glad you love these pieces. "
        handoff_msg += "Let me connect you with our checkout specialist to complete your purchase"
        
        if styling_context:
            handoff_msg += f" and make sure everything is ready for your {styling_context}"
        
        handoff_msg += ". One moment..."
        
        return _json(
            True,
            handoff_msg,
            handoff_to="postsale",
            cart_items=recommended_items,
            styling_context=styling_context,
            intent="checkout",
            handoff_reason="Customer ready to purchase styled items"
        )
    
    except Exception as e:
        logger.error(f"Stylist→Post-Sale handoff failed: {e}", exc_info=True)
        return _json(False, "I'm having trouble with that transfer. Let me help you complete this purchase.")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 4: Any Agent → Concierge (Fallback)
# ═══════════════════════════════════════════════════════════════════

class HandoffToConciergeArgs(TypedDict):
    """Schema for handoff back to Concierge"""
    reason: str                     # Why returning to concierge
    completed_task: Optional[str]   # What was accomplished


async def handoff_to_concierge(args: HandoffToConciergeArgs) -> Dict[str, Any]:
    """
    Transfer customer back to Shopping Concierge for general assistance.
    
    Use When:
        - Specialist task is complete and customer needs broader help
        - Customer wants to explore different product categories
        - After successful checkout, customer has new shopping needs
    
    Trigger Phrases:
        - "I'd also like to browse..."
        - "What else do you have?"
        - "Can I see other products?"
    
    Args:
        reason: Why returning (e.g., "wants to browse electronics")
        completed_task: Summary of what was accomplished (e.g., "styled outfit purchased")
    
    Returns:
        Handoff confirmation routing back to Shopping Concierge
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for handoff_to_concierge")
        return _json(False, "Unable to transfer you at this time.")
    
    try:
        reason = (args.get("reason") or "").strip()
        completed_task = (args.get("completed_task") or "").strip()
        
        if not reason:
            reason = "customer needs general shopping assistance"
        
        logger.info(f"HANDOFF: → Shopping Concierge | reason='{reason[:80]}'")
        
        handoff_msg = "Let me reconnect you with our Shopping Concierge"
        
        if completed_task:
            handoff_msg += f" now that we've {completed_task}"
        
        handoff_msg += " for further assistance. One moment..."
        
        return _json(
            True,
            handoff_msg,
            handoff_to="shopping_concierge",
            reason=reason,
            completed_task=completed_task,
            handoff_reason="Return to general assistance"
        )
    
    except Exception as e:
        logger.error(f"Handoff to concierge failed: {e}", exc_info=True)
        return _json(False, "I'm having trouble with that transfer. How else can I help you today?")


# ═══════════════════════════════════════════════════════════════════
# ESCALATION: Human Agent
# ═══════════════════════════════════════════════════════════════════

class EscalateToHumanArgs(TypedDict):
    """Escalate to human customer service"""
    issue: str      # Description of issue
    urgency: str    # low, medium, high


async def escalate_to_human(args: EscalateToHumanArgs) -> Dict[str, Any]:
    """
    Escalate customer to human customer service representative.
    
    Use When:
        - Customer explicitly requests human agent
        - Technical issue AI cannot resolve
        - Complex complaint requiring manager intervention
        - Policy exception or special accommodation needed
        - Sensitive personal information handling required
    
    Trigger Phrases:
        - "I need to speak with a person"
        - "Let me talk to your manager"
        - "This isn't working, get me a human"
    
    Args:
        issue: Description of problem (e.g., "payment declined repeatedly")
        urgency: Priority level - "low", "medium", or "high"
    
    Returns:
        Escalation confirmation with priority routing
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for escalate_to_human")
        return _json(False, "Unable to process that escalation request.")
    
    try:
        issue = (args.get("issue") or "").strip()
        urgency = (args.get("urgency") or "medium").strip().lower()
        
        # Validate urgency level
        valid_urgency = {"low", "medium", "high"}
        if urgency not in valid_urgency:
            urgency = "medium"
        
        if not issue:
            issue = "customer requested human assistance"
        
        logger.warning(f"ESCALATION: → Human Agent | urgency='{urgency}' | issue='{issue[:80]}'")
        
        # Build urgency-appropriate message
        urgency_messages = {
            "high": "I understand this requires immediate attention. Let me connect you with one of our specialists right away. They'll prioritize your request.",
            "medium": "I understand this requires special attention. Let me connect you with one of our customer service specialists.",
            "low": "I'll be happy to connect you with a customer service specialist for personalized assistance."
        }
        
        handoff_msg = urgency_messages.get(urgency, urgency_messages["medium"])
        handoff_msg += " Please hold..."
        
        return _json(
            True,
            handoff_msg,
            escalate_to="human_agent",
            issue=issue,
            urgency=urgency,
            handoff_reason=f"Escalation: {urgency} priority"
        )
    
    except Exception as e:
        logger.error(f"Escalation to human failed: {e}", exc_info=True)
        return _json(False, "I'm having trouble with that transfer. Let me note your concern and get help right away.")
