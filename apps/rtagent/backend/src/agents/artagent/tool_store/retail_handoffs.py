"""
ARTAgent Retail Handoff Tools
==============================

Agent routing and handoff functions for retail multi-agent system:
- Shopping Concierge → Personal Stylist
- Shopping Concierge → Post-Sale Agent
- Personal Stylist → Post-Sale Agent  
- Any Agent → Shopping Concierge (fallback)

Follows ARTAgent handoff pattern with context preservation.

Author: Pablo Salvador Lopez
Organization: GBB AI
"""

from typing import Optional, TypedDict

from apps.rtagent.backend.src.agents.artagent.tool_store.functions_helper import _json
from utils.ml_logging import get_logger

logger = get_logger("retail_handoffs")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 1: Concierge → Stylist
# ═══════════════════════════════════════════════════════════════════

class HandoffToStylistArgs(TypedDict):
    """Schema for handoff to Personal Stylist Agent"""
    caller_name: Optional[str]  # Customer name if known
    query_context: str          # What customer is looking for
    preferences: Optional[str]  # Known preferences (colors, style, etc.)


async def handoff_to_stylist(args: HandoffToStylistArgs) -> dict:
    """
    HANDOFF: Transfer to Personal Stylist Agent
    
    Use when customer needs:
    - Personalized styling advice
    - Outfit coordination for events
    - Fashion recommendations (gifts, specific occasions)
    - Context-based searches (weather, formality, age)
    
    Triggers:
    - "what should I wear to..."
    - "help me find outfit for..."
    - "gift for my grandmother"
    - "style me for..."
    
    Args:
        caller_name: Customer name (if available)
        query_context: Summary of what customer needs
        preferences: Known style preferences
    
    Returns:
        Handoff confirmation with context
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for handoff_to_stylist")
        return _json(False, "Unable to transfer to stylist. Please repeat your request.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        query_context = (args.get("query_context") or "").strip()
        preferences = (args.get("preferences") or "").strip()
        
        if not query_context:
            return _json(False, "I need more details about what you're looking for before connecting you to our stylist.")
        
        logger.info(f"HANDOFF to Stylist | caller='{caller_name}' | context='{query_context}'")
        
        # Build handoff message
        handoff_msg = "Perfect! Let me connect you with our Personal Stylist who specializes in personalized recommendations. "
        
        if caller_name:
            handoff_msg += f"They'll help you, {caller_name}, find exactly what you need. "
        
        handoff_msg += "One moment please..."
        
        return _json(
            True,
            handoff_msg,
            handoff_to="personal_stylist",
            caller_name=caller_name or "Customer",
            query_context=query_context,
            preferences=preferences,
            handoff_reason="Needs personalized styling advice"
        )
    
    except Exception as e:
        logger.error(f"Handoff to stylist failed: {e}", exc_info=True)
        return _json(False, "Transfer error. Let me try to help you directly.")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 2: Concierge → Post-Sale
# ═══════════════════════════════════════════════════════════════════

class HandoffToPostSaleArgs(TypedDict):
    """Schema for handoff to Post-Sale Agent"""
    caller_name: Optional[str]  # Customer name
    cart_items: Optional[str]   # Products customer wants to buy (JSON or summary)
    intent: str                 # checkout, return, track_order, exchange


async def handoff_to_postsale(args: HandoffToPostSaleArgs) -> dict:
    """
    HANDOFF: Transfer to Post-Sale Agent
    
    Use when customer wants to:
    - Complete purchase (checkout)
    - Track existing order
    - Initiate return or exchange
    - Apply payment, shipping, or loyalty actions
    
    Triggers:
    - "I'll take it"
    - "checkout" / "buy this"
    - "track my order"
    - "return this item"
    
    Args:
        caller_name: Customer name
        cart_items: Products to purchase (product IDs or summary)
        intent: Action type (checkout, return, track_order, exchange)
    
    Returns:
        Handoff confirmation with transaction context
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for handoff_to_postsale")
        return _json(False, "Unable to process purchase. Please try again.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        cart_items = (args.get("cart_items") or "").strip()
        intent = (args.get("intent") or "checkout").strip()
        
        logger.info(f"HANDOFF to Post-Sale | caller='{caller_name}' | intent='{intent}'")
        
        # Build context-specific handoff message
        if intent == "checkout":
            handoff_msg = "Great choice! Let me connect you with our checkout specialist to complete your purchase. "
            if cart_items:
                handoff_msg += "They'll help you finalize these items. "
        elif intent == "return":
            handoff_msg = "I understand you'd like to return an item. Let me connect you with our returns team. "
        elif intent == "track_order":
            handoff_msg = "I'll transfer you to our order tracking specialist right away. "
        elif intent == "exchange":
            handoff_msg = "Let me connect you with our exchange specialist to help with that. "
        else:
            handoff_msg = "Transferring you to our transaction specialist. "
        
        handoff_msg += "One moment please..."
        
        return _json(
            True,
            handoff_msg,
            handoff_to="postsale",
            caller_name=caller_name or "Customer",
            cart_items=cart_items,
            intent=intent,
            handoff_reason=f"Transaction action: {intent}"
        )
    
    except Exception as e:
        logger.error(f"Handoff to post-sale failed: {e}", exc_info=True)
        return _json(False, "Transfer error. Let me try to assist you directly.")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 3: Stylist → Post-Sale
# ═══════════════════════════════════════════════════════════════════

class StylistToPostSaleArgs(TypedDict):
    """Schema for stylist to post-sale handoff"""
    caller_name: Optional[str]
    recommended_items: str      # Products stylist suggested
    styling_context: Optional[str]  # Occasion, weather, etc.


async def stylist_handoff_to_postsale(args: StylistToPostSaleArgs) -> dict:
    """
    HANDOFF: Stylist to Post-Sale Agent
    
    Use when customer is ready to purchase after styling session.
    
    Args:
        caller_name: Customer name
        recommended_items: Products from styling recommendations
        styling_context: Context about occasion, style preferences
    
    Returns:
        Handoff to post-sale with styling context
    """
    if not isinstance(args, dict):
        return _json(False, "Unable to process purchase.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        recommended_items = (args.get("recommended_items") or "").strip()
        styling_context = (args.get("styling_context") or "").strip()
        
        logger.info(f"HANDOFF Stylist to Post-Sale | caller='{caller_name}'")
        
        handoff_msg = "Wonderful! I'm so glad you love these pieces. "
        handoff_msg += "Let me connect you with our checkout specialist to complete your purchase. "
        
        if styling_context:
            handoff_msg += f"They'll make sure everything is ready for your {styling_context}. "
        
        handoff_msg += "One moment please..."
        
        return _json(
            True,
            handoff_msg,
            handoff_to="postsale",
            caller_name=caller_name or "Customer",
            cart_items=recommended_items,
            styling_context=styling_context,
            intent="checkout",
            handoff_reason="Customer ready to purchase styled items"
        )
    
    except Exception as e:
        logger.error(f"Stylist→Post-Sale handoff failed: {e}", exc_info=True)
        return _json(False, "Transfer error occurred.")


# ═══════════════════════════════════════════════════════════════════
# HANDOFF 4: Any Agent → Concierge (Fallback)
# ═══════════════════════════════════════════════════════════════════

class HandoffToConciergeArgs(TypedDict):
    """Schema for handoff back to Concierge"""
    caller_name: Optional[str]
    reason: str  # Why returning to concierge


async def handoff_to_concierge(args: HandoffToConciergeArgs) -> dict:
    """
    HANDOFF: Return to Shopping Concierge
    
    Use when customer needs:
    - General product search
    - Store information
    - Policy questions  
    - Routing to different specialist
    
    Args:
        caller_name: Customer name
        reason: Why returning to concierge
    
    Returns:
        Handoff confirmation
    """
    if not isinstance(args, dict):
        return _json(False, "Unable to transfer.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        reason = (args.get("reason") or "").strip()
        
        logger.info(f"HANDOFF to Concierge | caller='{caller_name}' | reason='{reason}'")
        
        handoff_msg = "Let me connect you back to our Shopping Concierge who can help with that. "
        handoff_msg += "One moment..."
        
        return _json(
            True,
            handoff_msg,
            handoff_to="shopping_concierge",
            caller_name=caller_name or "Customer",
            reason=reason,
            handoff_reason="Return to general assistance"
        )
    
    except Exception as e:
        logger.error(f"Handoff to concierge failed: {e}", exc_info=True)
        return _json(False, "Transfer error.")


# ═══════════════════════════════════════════════════════════════════
# ESCALATION: Human Agent
# ═══════════════════════════════════════════════════════════════════

class EscalateToHumanArgs(TypedDict):
    """Escalate to human customer service"""
    caller_name: Optional[str]
    issue: str  # Description of issue
    urgency: str  # low, medium, high


async def escalate_to_human(args: EscalateToHumanArgs) -> dict:
    """
    ESCALATION: Transfer to Human Agent
    
    Use when:
    - Customer explicitly requests human
    - Complex issue beyond AI capabilities
    - High-priority complaint
    
    Args:
        caller_name: Customer name
        issue: Description of problem
        urgency: Priority level (low, medium, high)
    
    Returns:
        Escalation confirmation
    """
    if not isinstance(args, dict):
        return _json(False, "Unable to escalate.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        issue = (args.get("issue") or "").strip()
        urgency = (args.get("urgency") or "medium").strip()
        
        logger.warning(f"ESCALATION to Human | caller='{caller_name}' | urgency={urgency} | issue='{issue}'")
        
        if urgency == "high":
            handoff_msg = "I understand this is urgent. Connecting you to our customer service team right now. "
        else:
            handoff_msg = "I'd be happy to connect you with a human specialist. "
        
        handoff_msg += "Please hold for a moment..."
        
        return _json(
            True,
            handoff_msg,
            escalate_to="human_agent",
            caller_name=caller_name or "Customer",
            issue=issue,
            urgency=urgency,
            handoff_reason="Human escalation requested"
        )
    
    except Exception as e:
        logger.error(f"Human escalation failed: {e}", exc_info=True)
        return _json(False, "Unable to connect to human agent right now.")


# ═══════════════════════════════════════════════════════════════════
# Export Handoff Registry
# ═══════════════════════════════════════════════════════════════════

RETAIL_HANDOFF_TOOLS = {
    "handoff_to_stylist": {
        "function": handoff_to_stylist,
        "schema": {
            "name": "handoff_to_stylist",
            "description": "Transfer customer to Personal Stylist for personalized fashion advice and outfit coordination",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string", "description": "Customer name if known"},
                    "query_context": {"type": "string", "description": "What customer is looking for (required)"},
                    "preferences": {"type": "string", "description": "Known style preferences"}
                },
                "required": ["query_context"]
            }
        }
    },
    "handoff_to_postsale": {
        "function": handoff_to_postsale,
        "schema": {
            "name": "handoff_to_postsale",
            "description": "Transfer customer to Post-Sale Agent for checkout, order tracking, returns, or exchanges",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string", "description": "Customer name"},
                    "cart_items": {"type": "string", "description": "Products to purchase or manage"},
                    "intent": {
                        "type": "string",
                        "enum": ["checkout", "return", "track_order", "exchange"],
                        "description": "Transaction intent"
                    }
                },
                "required": ["intent"]
            }
        }
    },
    "stylist_handoff_to_postsale": {
        "function": stylist_handoff_to_postsale,
        "schema": {
            "name": "stylist_handoff_to_postsale",
            "description": "Stylist transfers customer to Post-Sale after successful styling session",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string"},
                    "recommended_items": {"type": "string", "description": "Products recommended by stylist"},
                    "styling_context": {"type": "string", "description": "Occasion and style context"}
                },
                "required": ["recommended_items"]
            }
        }
    },
    "handoff_to_concierge": {
        "function": handoff_to_concierge,
        "schema": {
            "name": "handoff_to_concierge",
            "description": "Return customer to Shopping Concierge for general assistance",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string"},
                    "reason": {"type": "string", "description": "Why returning to concierge"}
                },
                "required": ["reason"]
            }
        }
    },
    "escalate_to_human": {
        "function": escalate_to_human,
        "schema": {
            "name": "escalate_to_human",
            "description": "Escalate to human customer service agent for complex issues",
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_name": {"type": "string"},
                    "issue": {"type": "string", "description": "Description of problem"},
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Priority level"
                    }
                },
                "required": ["issue"]
            }
        }
    }
}
