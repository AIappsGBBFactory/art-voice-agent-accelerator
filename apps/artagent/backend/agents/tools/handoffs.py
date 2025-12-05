"""
Handoff Tools
=============

Agent handoff tools for multi-agent orchestration.
These tools trigger agent transfers in both VoiceLive and SpeechCascade orchestrators.

Each handoff tool returns a standardized payload:
{
    "handoff": True,
    "target_agent": "AgentName",
    "message": "Transition message to speak",
    "handoff_summary": "Brief summary",
    "handoff_context": {...}
}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, TypedDict

from apps.artagent.backend.agents.tools.registry import register_tool
from utils.ml_logging import get_logger

logger = get_logger("agents.tools.handoffs")


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


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


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

handoff_concierge_schema: Dict[str, Any] = {
    "name": "handoff_concierge",
    "description": (
        "Return customer to Erica Concierge (main banking assistant). "
        "Use after completing specialist task or when customer needs different help."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "previous_topic": {"type": "string", "description": "What you helped with"},
            "resolution_summary": {"type": "string", "description": "Brief summary of resolution"},
        },
        "required": ["client_id"],
    },
}

handoff_fraud_agent_schema: Dict[str, Any] = {
    "name": "handoff_fraud_agent",
    "description": (
        "Transfer to Fraud Detection Agent for suspicious activity investigation. "
        "Use when customer reports fraud, unauthorized charges, or suspicious transactions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "fraud_type": {
                "type": "string",
                "description": "Type of fraud (unauthorized_charge, identity_theft, card_stolen, etc.)",
            },
            "issue_summary": {"type": "string", "description": "Brief summary of the fraud concern"},
        },
        "required": ["client_id"],
    },
}

handoff_to_auth_schema: Dict[str, Any] = {
    "name": "handoff_to_auth",
    "description": (
        "Transfer to Authentication Agent for identity verification. "
        "Use when MFA or additional identity verification is required."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "reason": {"type": "string", "description": "Reason for authentication required"},
        },
        "required": ["client_id"],
    },
}

handoff_card_recommendation_schema: Dict[str, Any] = {
    "name": "handoff_card_recommendation",
    "description": (
        "Transfer to Card Recommendation Agent for credit card advice. "
        "Use when customer asks about new cards, rewards, or upgrades."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "customer_goal": {
                "type": "string",
                "description": "What they want (lower fees, better rewards, travel perks)",
            },
            "spending_preferences": {
                "type": "string",
                "description": "Where they spend most (travel, dining, groceries)",
            },
            "current_cards": {"type": "string", "description": "Cards they currently have"},
        },
        "required": ["client_id"],
    },
}

handoff_investment_advisor_schema: Dict[str, Any] = {
    "name": "handoff_investment_advisor",
    "description": (
        "Transfer to Investment Advisor for retirement and investment questions. "
        "Use for 401(k) rollover, IRA, retirement planning topics."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "topic": {"type": "string", "description": "Main topic (rollover, IRA, retirement)"},
            "employment_change": {"type": "string", "description": "Job change details if applicable"},
            "retirement_question": {"type": "string", "description": "Specific retirement question"},
        },
        "required": ["client_id"],
    },
}

handoff_compliance_desk_schema: Dict[str, Any] = {
    "name": "handoff_compliance_desk",
    "description": (
        "Transfer to Compliance Desk for AML/FATCA verification and regulatory review. "
        "Use for compliance issues, sanctions screening, or regulatory requirements."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer or client code"},
            "compliance_issue": {"type": "string", "description": "Type of compliance issue"},
            "urgency": {"type": "string", "enum": ["normal", "high", "expedited"], "description": "Urgency level"},
            "transaction_details": {"type": "string", "description": "Transaction context"},
        },
        "required": ["client_id"],
    },
}

handoff_transfer_agency_agent_schema: Dict[str, Any] = {
    "name": "handoff_transfer_agency_agent",
    "description": (
        "Transfer to Transfer Agency Agent for DRIP liquidations and institutional services. "
        "Use for dividend reinvestment, institutional client codes, position inquiries."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "request_type": {
                "type": "string",
                "description": "Type of request (drip_liquidation, compliance_inquiry, position_inquiry)",
            },
            "client_code": {"type": "string", "description": "Institutional client code (e.g., GCA-48273)"},
            "drip_symbols": {"type": "string", "description": "Stock symbols to liquidate"},
        },
        "required": [],
    },
}

handoff_bank_advisor_schema: Dict[str, Any] = {
    "name": "handoff_bank_advisor",
    "description": (
        "Schedule callback with Merrill human advisor for personalized investment advice. "
        "Use when customer needs human specialist for complex investment decisions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "reason": {"type": "string", "description": "Reason for advisor callback"},
            "context": {"type": "string", "description": "Summary of conversation and needs"},
        },
        "required": ["client_id", "reason"],
    },
}

handoff_to_trading_schema: Dict[str, Any] = {
    "name": "handoff_to_trading",
    "description": (
        "Transfer to Trading Desk for complex execution. "
        "Use for FX conversions, large trades, or institutional execution."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "trade_details": {"type": "string", "description": "Details of the trade"},
            "complexity_level": {"type": "string", "enum": ["standard", "institutional"], "description": "Complexity"},
        },
        "required": ["client_id"],
    },
}

handoff_general_kb_schema: Dict[str, Any] = {
    "name": "handoff_general_kb",
    "description": (
        "Transfer to General Knowledge Base agent for general inquiries. "
        "No authentication required. Use for product info, FAQs, policies, and general questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic of inquiry (products, policies, faq, general)"},
            "question": {"type": "string", "description": "The user's question or topic of interest"},
        },
        "required": [],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════

async def handoff_concierge(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return customer to Erica Concierge from specialist agent."""
    client_id = (args.get("client_id") or "").strip()
    previous_topic = (args.get("previous_topic") or "").strip()
    resolution_summary = (args.get("resolution_summary") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("🔄 Handoff to Concierge | client=%s", client_id)
    
    return _build_handoff_payload(
        target_agent="Concierge",
        message="",
        summary=f"Returning from {previous_topic}",
        context={
            "client_id": client_id,
            "previous_topic": previous_topic,
            "resolution_summary": resolution_summary,
            "handoff_timestamp": _utc_now(),
        },
    )


async def handoff_fraud_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Fraud Detection Agent."""
    client_id = (args.get("client_id") or "").strip()
    fraud_type = (args.get("fraud_type") or "").strip()
    issue_summary = (args.get("issue_summary") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("🚨 Handoff to FraudAgent | client=%s type=%s", client_id, fraud_type)
    
    return _build_handoff_payload(
        target_agent="FraudAgent",
        message="Let me connect you with our fraud specialist.",
        summary=f"Fraud investigation: {fraud_type or 'suspicious activity'}",
        context={
            "client_id": client_id,
            "fraud_type": fraud_type,
            "issue_summary": issue_summary,
            "handoff_timestamp": _utc_now(),
            "previous_agent": "Concierge",
        },
        extra={"should_interrupt_playback": True},
    )


async def handoff_to_auth(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Authentication Agent."""
    client_id = (args.get("client_id") or "").strip()
    reason = (args.get("reason") or "identity verification required").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("🔐 Handoff to AuthAgent | client=%s", client_id)
    
    return _build_handoff_payload(
        target_agent="AuthAgent",
        message="I need to verify your identity before we continue.",
        summary=f"Authentication required: {reason}",
        context={
            "client_id": client_id,
            "reason": reason,
            "handoff_timestamp": _utc_now(),
        },
    )


async def handoff_card_recommendation(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Card Recommendation Agent."""
    client_id = (args.get("client_id") or "").strip()
    customer_goal = (args.get("customer_goal") or "").strip()
    spending_prefs = (args.get("spending_preferences") or "").strip()
    current_cards = (args.get("current_cards") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("💳 Handoff to CardRecommendation | client=%s goal=%s", client_id, customer_goal)
    
    return _build_handoff_payload(
        target_agent="CardRecommendation",
        message="Let me find the best card options for you.",
        summary=f"Card recommendation: {customer_goal or 'general inquiry'}",
        context={
            "client_id": client_id,
            "customer_goal": customer_goal,
            "spending_preferences": spending_prefs,
            "current_cards": current_cards,
            "handoff_timestamp": _utc_now(),
            "previous_agent": "Concierge",
        },
        extra={"should_interrupt_playback": True},
    )


async def handoff_investment_advisor(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Investment Advisor Agent."""
    client_id = (args.get("client_id") or "").strip()
    topic = (args.get("topic") or "retirement planning").strip()
    employment_change = (args.get("employment_change") or "").strip()
    retirement_question = (args.get("retirement_question") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("🏦 Handoff to InvestmentAdvisor | client=%s topic=%s", client_id, topic)
    
    return _build_handoff_payload(
        target_agent="InvestmentAdvisor",
        message="Let me look at your retirement accounts and options.",
        summary=f"Retirement inquiry: {topic}",
        context={
            "client_id": client_id,
            "topic": topic,
            "employment_change": employment_change,
            "retirement_question": retirement_question,
            "handoff_timestamp": _utc_now(),
            "previous_agent": "Concierge",
        },
        extra={"should_interrupt_playback": True},
    )


async def handoff_compliance_desk(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Compliance Desk Agent."""
    client_id = (args.get("client_id") or "").strip()
    compliance_issue = (args.get("compliance_issue") or "").strip()
    urgency = (args.get("urgency") or "normal").strip()
    transaction_details = (args.get("transaction_details") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("📋 Handoff to ComplianceDesk | client=%s issue=%s", client_id, compliance_issue)
    
    return _build_handoff_payload(
        target_agent="ComplianceDesk",
        message="Let me review the compliance requirements for your transaction.",
        summary=f"Compliance review: {compliance_issue or 'verification required'}",
        context={
            "client_id": client_id,
            "compliance_issue": compliance_issue,
            "urgency": urgency,
            "transaction_details": transaction_details,
            "handoff_timestamp": _utc_now(),
        },
    )


async def handoff_transfer_agency_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Transfer Agency Agent."""
    client_id = (args.get("client_id") or "").strip()
    request_type = (args.get("request_type") or "drip_liquidation").strip()
    client_code = (args.get("client_code") or "").strip()
    drip_symbols = (args.get("drip_symbols") or "").strip()
    
    logger.info("🏛️ Handoff to TransferAgency | type=%s code=%s", request_type, client_code)
    
    context = {
        "request_type": request_type,
        "client_code": client_code,
        "drip_symbols": drip_symbols,
        "handoff_timestamp": _utc_now(),
        "previous_agent": "Concierge",
    }
    if client_id:
        context["client_id"] = client_id
    
    return _build_handoff_payload(
        target_agent="TransferAgencyAgent",
        message="Let me connect you with our Transfer Agency specialist.",
        summary=f"Transfer agency: {request_type}",
        context=context,
        extra={"should_interrupt_playback": True},
    )


async def handoff_bank_advisor(args: Dict[str, Any]) -> Dict[str, Any]:
    """Schedule callback with Merrill human advisor."""
    client_id = (args.get("client_id") or "").strip()
    reason = (args.get("reason") or "").strip()
    context_summary = (args.get("context") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    if not reason:
        return {"success": False, "message": "reason is required."}
    
    logger.info("👤 Merrill Advisor callback scheduled | client=%s reason=%s", client_id, reason)
    
    # This is a callback scheduling, not a live transfer
    return {
        "success": True,
        "callback_scheduled": True,
        "target_agent": "MerrillAdvisor",
        "message": f"Callback scheduled for {reason}",
        "handoff_context": {
            "client_id": client_id,
            "reason": reason,
            "context": context_summary,
            "scheduled_at": _utc_now(),
        },
    }


async def handoff_to_trading(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to Trading Desk."""
    client_id = (args.get("client_id") or "").strip()
    trade_details = (args.get("trade_details") or "").strip()
    complexity = (args.get("complexity_level") or "standard").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("📈 Handoff to Trading | client=%s complexity=%s", client_id, complexity)
    
    return _build_handoff_payload(
        target_agent="TradingDesk",
        message="Connecting you with our trading desk.",
        summary=f"Trade execution: {complexity}",
        context={
            "client_id": client_id,
            "trade_details": trade_details,
            "complexity_level": complexity,
            "handoff_timestamp": _utc_now(),
        },
    )


async def handoff_general_kb(args: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer to General Knowledge Base agent for general inquiries."""
    topic = (args.get("topic") or "general").strip()
    question = (args.get("question") or "").strip()
    
    logger.info("📚 Handoff to GeneralKBAgent | topic=%s", topic)
    
    return _build_handoff_payload(
        target_agent="GeneralKBAgent",
        message="I'll connect you with our knowledge assistant who can help with general questions.",
        summary=f"General inquiry: {topic}",
        context={
            "topic": topic,
            "question": question,
            "handoff_timestamp": _utc_now(),
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

# Register all handoff tools
register_tool("handoff_concierge", handoff_concierge_schema, handoff_concierge, is_handoff=True, tags={"handoff"})
register_tool("handoff_fraud_agent", handoff_fraud_agent_schema, handoff_fraud_agent, is_handoff=True, tags={"handoff", "fraud"})
register_tool("handoff_to_auth", handoff_to_auth_schema, handoff_to_auth, is_handoff=True, tags={"handoff", "auth"})
register_tool("handoff_card_recommendation", handoff_card_recommendation_schema, handoff_card_recommendation, is_handoff=True, tags={"handoff", "banking"})
register_tool("handoff_investment_advisor", handoff_investment_advisor_schema, handoff_investment_advisor, is_handoff=True, tags={"handoff", "investment"})
register_tool("handoff_compliance_desk", handoff_compliance_desk_schema, handoff_compliance_desk, is_handoff=True, tags={"handoff", "compliance"})
register_tool("handoff_transfer_agency_agent", handoff_transfer_agency_agent_schema, handoff_transfer_agency_agent, is_handoff=True, tags={"handoff", "transfer_agency"})
register_tool("handoff_bank_advisor", handoff_bank_advisor_schema, handoff_bank_advisor, is_handoff=True, tags={"handoff", "investment"})
register_tool("handoff_to_trading", handoff_to_trading_schema, handoff_to_trading, is_handoff=True, tags={"handoff", "trading"})
register_tool("handoff_general_kb", handoff_general_kb_schema, handoff_general_kb, is_handoff=True, tags={"handoff", "knowledge_base"})
