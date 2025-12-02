"""
Customer Intelligence Utilities for Ultra-Personalized Fraud Detection

This module provides utility functions to access and format customer intelligence data
for creating 10/10 personalized fraud detection experiences.
"""

from typing import Dict, Any, Optional, List
from fastapi import WebSocket

from src.orchestration.artagent.cm_utils import cm_get
from utils.ml_logging import get_logger

logger = get_logger(__name__)

def get_customer_intelligence_from_memory(cm) -> Optional[Dict[str, Any]]:
    """
    Retrieve customer intelligence data from conversation memory.
    
    Returns:
        Complete customer intelligence profile or None if not available
    """
    try:
        intelligence = cm_get(cm, "customer_intelligence")
        if intelligence:
            logger.info("✅ Customer intelligence retrieved from memory")
            return intelligence
        else:
            logger.warning("❌ No customer intelligence found in memory")
            return None
    except Exception as e:
        logger.error(f"Error retrieving customer intelligence from memory: {e}")
        return None

def get_personalized_greeting_data(cm) -> Dict[str, str]:
    """
    Extract data needed for personalized greetings.
    
    Returns:
        Dictionary with greeting personalization data
    """
    intelligence = get_customer_intelligence_from_memory(cm)
    caller_name = cm_get(cm, "caller_name", "")
    institution = cm_get(cm, "institution_name", "")
    
    if not intelligence:
        return {
            "first_name": caller_name.split()[0] if caller_name else "there",
            "institution": institution,
            "tier": "valued",
            "years": "0",
            "communication_style": "adaptive"
        }
    
    relationship = intelligence.get("relationship_context", {})
    memory_score = intelligence.get("memory_score", {})
    
    return {
        "first_name": caller_name.split()[0] if caller_name else "there",
        "full_name": caller_name,
        "institution": institution,
        "tier": relationship.get("relationship_tier", "valued").lower(),
        "years": str(int(relationship.get("relationship_duration_years", 0))),
        "communication_style": memory_score.get("communication_style", "adaptive"),
        "patience_level": memory_score.get("personality_traits", {}).get("patience_level", "medium"),
        "satisfaction_score": str(relationship.get("satisfaction_score", 95))
    }

def get_fraud_context_data(cm) -> Dict[str, Any]:
    """
    Extract fraud-specific intelligence for personalized fraud detection.
    
    Returns:
        Fraud context data for personalized investigations
    """
    intelligence = get_customer_intelligence_from_memory(cm)
    client_id = cm_get(cm, "client_id")
    
    base_context = {
        "client_id": client_id,
        "has_intelligence": False,
        "risk_profile": "medium",
        "typical_spending": "$50-$500",
        "common_merchants": ["Standard retail"],
        "security_preferences": {
            "verification_method": "email",
            "card_replacement": "standard",
            "notification_urgency": "standard"
        }
    }
    
    if not intelligence:
        return base_context
    
    fraud_context = intelligence.get("fraud_context", {})
    spending_patterns = intelligence.get("spending_patterns", {})
    account_status = intelligence.get("account_status", {})
    
    return {
        "client_id": client_id,
        "has_intelligence": True,
        "risk_profile": fraud_context.get("risk_profile", "medium"),
        "typical_spending": fraud_context.get("typical_transaction_behavior", {}).get("usual_spending_range", "$50-$500"),
        "common_merchants": spending_patterns.get("common_merchants", ["Standard retail"]),
        "common_locations": fraud_context.get("typical_transaction_behavior", {}).get("common_locations", ["Unknown"]),
        "security_preferences": fraud_context.get("security_preferences", base_context["security_preferences"]),
        "account_balance": account_status.get("current_balance", 0),
        "ytd_volume": account_status.get("ytd_transaction_volume", 0),
        "health_score": account_status.get("account_health_score", 95)
    }

def format_personalized_response(cm, base_message: str, context_type: str = "general") -> str:
    """
    Format a response message with personalization based on customer intelligence.
    
    Args:
        cm: Memory manager instance
        base_message: Base message to personalize
        context_type: Type of context ("fraud", "transaction", "general")
    
    Returns:
        Personalized message string
    """
    greeting_data = get_personalized_greeting_data(cm)
    first_name = greeting_data["first_name"]
    communication_style = greeting_data["communication_style"]
    tier = greeting_data["tier"]
    
    # Add personal touch with name
    if first_name != "there" and first_name not in base_message:
        base_message = f"{first_name}, {base_message.lower()}"
    
    # Adjust message style based on communication preference
    if "Direct" in communication_style or "Business" in communication_style:
        # Make message more direct and action-oriented
        base_message = base_message.replace("I'm going to", "I'm").replace("I will", "I'm")
        base_message = base_message.replace("Let me", "I'm").replace("I'll", "I'm")
    elif "Relationship" in communication_style:
        # Add relationship warmth
        if tier in ["platinum", "gold"]:
            base_message = base_message.replace("I'm", f"I'm personally")
        base_message = base_message.replace("your account", f"your {tier} account")
    elif "Detail" in communication_style:
        # Add more comprehensive language
        base_message = base_message.replace("checking", "conducting a comprehensive analysis of")
        base_message = base_message.replace("reviewing", "performing a detailed review of")
    
    return base_message

def get_intelligence_summary_for_tools(cm) -> str:
    """
    Create a summary of customer intelligence for use in tool descriptions.
    
    Returns:
        Formatted summary string for tool context
    """
    intelligence = get_customer_intelligence_from_memory(cm)
    
    if not intelligence:
        return "No customer intelligence available - using standard fraud detection protocols."
    
    greeting_data = get_personalized_greeting_data(cm)
    fraud_data = get_fraud_context_data(cm)
    
    summary_parts = [
        f"Client: {greeting_data['first_name']} ({greeting_data['tier']} tier, {greeting_data['years']} years)",
        f"Communication: {greeting_data['communication_style']}",
        f"Spending: {fraud_data['typical_spending']} typical range",
        f"Security: {fraud_data['security_preferences']['card_replacement']} replacement preference"
    ]
    
    return " | ".join(summary_parts)

def should_use_enhanced_monitoring(cm) -> bool:
    """
    Determine if customer qualifies for enhanced monitoring based on intelligence.
    
    Returns:
        True if enhanced monitoring should be offered
    """
    intelligence = get_customer_intelligence_from_memory(cm)
    
    if not intelligence:
        return False
    
    relationship = intelligence.get("relationship_context", {})
    tier = relationship.get("relationship_tier", "").lower()
    years = relationship.get("relationship_duration_years", 0)
    satisfaction = relationship.get("satisfaction_score", 0)
    
    # Enhanced monitoring for premium clients or long relationships
    return tier in ["platinum", "gold"] or years >= 3 or satisfaction >= 90

def get_personalized_fraud_education_topics(cm) -> List[str]:
    """
    Get personalized fraud education topics based on customer profile.
    
    Returns:
        List of relevant fraud education topics
    """
    intelligence = get_customer_intelligence_from_memory(cm)
    
    if not intelligence:
        return [
            "General fraud prevention tips",
            "Card security best practices",
            "Account monitoring guidance"
        ]
    
    spending_patterns = intelligence.get("spending_patterns", {})
    fraud_context = intelligence.get("fraud_context", {})
    
    topics = []
    
    # Add topics based on spending patterns
    common_merchants = spending_patterns.get("common_merchants", [])
    if "Online" in str(common_merchants) or "Amazon" in str(common_merchants):
        topics.append("Online shopping security")
    if "Travel" in str(common_merchants):
        topics.append("Travel fraud protection")
    if "Business" in str(common_merchants):
        topics.append("Business account security")
    
    # Add topics based on risk profile
    risk_profile = fraud_context.get("risk_profile", "medium")
    if risk_profile == "low":
        topics.append("Maintaining excellent security practices")
    elif risk_profile == "medium":
        topics.append("Enhanced monitoring benefits")
    else:
        topics.append("Advanced fraud protection strategies")
    
    # Always include general best practices
    topics.extend([
        "Real-time fraud alerts setup",
        "Secure transaction verification",
        "Emergency contact procedures"
    ])
    
    return topics[:5]  # Limit to top 5 most relevant

def log_personalization_usage(cm, tool_name: str, personalization_applied: str) -> None:
    """
    Log personalization usage for analytics and improvement.
    
    Args:
        cm: Memory manager instance
        tool_name: Name of the tool using personalization
        personalization_applied: Description of personalization used
    """
    client_id = cm_get(cm, "client_id", "unknown")
    session_id = getattr(cm, 'session_id', 'unknown')
    
    logger.info(
        f"Personalization used - Session: {session_id}, Client: {client_id}, "
        f"Tool: {tool_name}, Applied: {personalization_applied}"
    )