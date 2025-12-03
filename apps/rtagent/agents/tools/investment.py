"""
Investment Tools
================

Tools for retirement accounts, 401k rollovers, and investment guidance.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from apps.rtagent.agents.tools.registry import register_tool
from utils.ml_logging import get_logger

logger = get_logger("agents.tools.investment")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

get_retirement_accounts_schema: Dict[str, Any] = {
    "name": "get_retirement_accounts",
    "description": (
        "Get summary of customer's retirement accounts including IRA, 401k, and other qualified accounts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
        },
        "required": ["client_id"],
    },
}

get_401k_details_schema: Dict[str, Any] = {
    "name": "get_401k_details",
    "description": (
        "Get detailed information about a specific 401k account including vesting, "
        "contribution history, and investment allocations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "account_id": {"type": "string", "description": "401k account identifier"},
        },
        "required": ["client_id"],
    },
}

get_rollover_options_schema: Dict[str, Any] = {
    "name": "get_rollover_options",
    "description": (
        "Get available rollover options for 401k or other retirement accounts. "
        "Includes IRA options, direct vs indirect rollover comparison."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "source_account_type": {
                "type": "string",
                "enum": ["401k", "403b", "457", "pension", "ira"],
                "description": "Type of source account",
            },
            "balance": {"type": "number", "description": "Approximate balance to roll over"},
        },
        "required": ["client_id", "source_account_type"],
    },
}

calculate_tax_impact_schema: Dict[str, Any] = {
    "name": "calculate_tax_impact",
    "description": (
        "Calculate potential tax implications of retirement account actions "
        "including withdrawals, conversions, and rollovers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "action_type": {
                "type": "string",
                "enum": ["withdrawal", "roth_conversion", "rollover", "rmd"],
                "description": "Type of action",
            },
            "amount": {"type": "number", "description": "Amount involved"},
            "age": {"type": "integer", "description": "Customer's age for penalty calculations"},
        },
        "required": ["action_type", "amount"],
    },
}

search_rollover_guidance_schema: Dict[str, Any] = {
    "name": "search_rollover_guidance",
    "description": (
        "Search knowledge base for rollover guidance, rules, and best practices."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Question or topic to search"},
        },
        "required": ["query"],
    },
}

get_account_routing_info_schema: Dict[str, Any] = {
    "name": "get_account_routing_info",
    "description": (
        "Get routing and account information needed for direct rollovers or transfers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "account_type": {
                "type": "string",
                "enum": ["traditional_ira", "roth_ira", "sep_ira", "simple_ira"],
                "description": "Type of destination account",
            },
            "client_id": {"type": "string", "description": "Customer identifier"},
        },
        "required": ["account_type", "client_id"],
    },
}

schedule_advisor_consultation_schema: Dict[str, Any] = {
    "name": "schedule_advisor_consultation",
    "description": (
        "Schedule a consultation with a licensed financial advisor for complex investment decisions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "topic": {"type": "string", "description": "Primary topic for consultation"},
            "preferred_time": {"type": "string", "description": "Preferred consultation time"},
            "advisor_type": {
                "type": "string",
                "enum": ["general", "retirement", "tax", "estate"],
                "description": "Specialization needed",
            },
        },
        "required": ["client_id", "topic"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK DATA
# ═══════════════════════════════════════════════════════════════════════════════

_MOCK_RETIREMENT_ACCOUNTS = {
    "CLT-001-JS": [
        {
            "account_id": "IRA-7823",
            "type": "Traditional IRA",
            "balance": 145230.50,
            "ytd_contributions": 6500,
            "ytd_growth": 12450.00,
            "custodian": "Merrill Lynch",
        },
        {
            "account_id": "401K-EXT-4521",
            "type": "Previous Employer 401k",
            "balance": 87650.00,
            "employer": "TechCorp Inc",
            "vested_percent": 100,
            "status": "eligible_for_rollover",
        },
    ],
    "CLT-002-JD": [
        {
            "account_id": "ROTH-9012",
            "type": "Roth IRA",
            "balance": 52340.00,
            "ytd_contributions": 7000,
            "ytd_growth": 5200.00,
            "custodian": "Merrill Lynch",
        },
    ],
}

_ROLLOVER_KNOWLEDGE = {
    "direct_vs_indirect": (
        "Direct rollovers transfer funds directly between custodians with no tax withholding. "
        "Indirect rollovers give you 60 days to deposit funds, with 20% mandatory withholding "
        "that you must make up from other funds to avoid taxes and penalties."
    ),
    "60_day_rule": (
        "For indirect rollovers, you have exactly 60 days to deposit the full amount into a "
        "qualified retirement account. Missing this deadline results in taxes and potential penalties."
    ),
    "one_rollover_per_year": (
        "IRS limits you to one IRA-to-IRA rollover per 12-month period. This does not apply to "
        "direct trustee-to-trustee transfers or 401k to IRA rollovers."
    ),
    "roth_conversion": (
        "Converting traditional 401k/IRA to Roth requires paying income tax on the converted amount. "
        "However, future qualified withdrawals from Roth are tax-free."
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_retirement_accounts(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get retirement account summary."""
    client_id = (args.get("client_id") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    accounts = _MOCK_RETIREMENT_ACCOUNTS.get(client_id, [])
    total_balance = sum(a.get("balance", 0) for a in accounts)
    
    logger.info("💰 Retirement accounts retrieved: %s - %d accounts", client_id, len(accounts))
    
    return {
        "success": True,
        "accounts": accounts,
        "total_balance": total_balance,
        "account_count": len(accounts),
    }


async def get_401k_details(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get detailed 401k information."""
    client_id = (args.get("client_id") or "").strip()
    account_id = (args.get("account_id") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    accounts = _MOCK_RETIREMENT_ACCOUNTS.get(client_id, [])
    for acct in accounts:
        if "401" in acct.get("type", "").lower():
            return {
                "success": True,
                "account": acct,
                "allocations": [
                    {"fund": "S&P 500 Index", "percent": 50, "balance": acct["balance"] * 0.5},
                    {"fund": "Bond Index", "percent": 30, "balance": acct["balance"] * 0.3},
                    {"fund": "International", "percent": 20, "balance": acct["balance"] * 0.2},
                ],
                "vesting_schedule": "100% vested",
                "loan_outstanding": 0,
            }
    
    return {"success": False, "message": "No 401k account found."}


async def get_rollover_options(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get available rollover options."""
    client_id = (args.get("client_id") or "").strip()
    source_type = (args.get("source_account_type") or "401k").strip()
    balance = args.get("balance", 0)
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    options = [
        {
            "option": "Direct Rollover to Traditional IRA",
            "tax_impact": "None - tax-deferred",
            "advantages": ["No withholding", "More investment options", "Consolidation"],
            "considerations": ["RMDs at 73", "10% penalty before 59.5"],
        },
        {
            "option": "Direct Rollover to Roth IRA",
            "tax_impact": f"Income tax on ~${balance:,.0f}" if balance else "Income tax on full amount",
            "advantages": ["Tax-free growth", "No RMDs", "Tax-free withdrawals"],
            "considerations": ["Pay taxes now", "5-year rule for conversions"],
        },
        {
            "option": "Leave in Current Plan",
            "tax_impact": "None",
            "advantages": ["Familiarity", "Possible loan access"],
            "considerations": ["Limited options", "Multiple accounts to track"],
        },
        {
            "option": "Roll to New Employer 401k",
            "tax_impact": "None if direct",
            "advantages": ["Consolidation", "Possible loan access"],
            "considerations": ["Only if new employer accepts rollovers"],
        },
    ]
    
    return {
        "success": True,
        "source_type": source_type,
        "balance": balance,
        "options": options,
        "recommendation": "Speak with an advisor for personalized guidance",
    }


async def calculate_tax_impact(args: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate tax implications."""
    action_type = (args.get("action_type") or "").strip()
    amount = args.get("amount", 0)
    age = args.get("age", 50)
    
    if not action_type or not amount:
        return {"success": False, "message": "action_type and amount required."}
    
    # Simplified tax calculation
    estimated_tax_rate = 0.24  # Assume 24% bracket
    penalty_rate = 0.10 if age < 59.5 and action_type == "withdrawal" else 0
    
    federal_tax = amount * estimated_tax_rate
    penalty = amount * penalty_rate
    state_tax = amount * 0.05  # Assume 5% state
    
    return {
        "success": True,
        "action": action_type,
        "amount": amount,
        "estimated_federal_tax": federal_tax,
        "estimated_state_tax": state_tax,
        "early_withdrawal_penalty": penalty,
        "total_tax_impact": federal_tax + state_tax + penalty,
        "net_after_taxes": amount - federal_tax - state_tax - penalty,
        "disclaimer": "This is an estimate. Consult a tax professional for exact figures.",
    }


async def search_rollover_guidance(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search rollover knowledge base."""
    query = (args.get("query") or "").strip().lower()
    
    if not query:
        return {"success": False, "message": "query is required."}
    
    results = []
    for key, content in _ROLLOVER_KNOWLEDGE.items():
        if any(word in key or word in content.lower() for word in query.split()):
            results.append({"topic": key.replace("_", " ").title(), "content": content})
    
    if not results:
        results.append({
            "topic": "General Rollover Info",
            "content": "For specific rollover questions, I recommend scheduling a consultation with an advisor.",
        })
    
    return {"success": True, "results": results}


async def get_account_routing_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get routing information for transfers."""
    account_type = (args.get("account_type") or "traditional_ira").strip()
    client_id = (args.get("client_id") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    return {
        "success": True,
        "account_type": account_type,
        "routing_info": {
            "custodian": "Merrill Lynch",
            "dtc_number": "0671",
            "for_further_credit": f"FBO {client_id}",
            "account_number": f"ML-IRA-{random.randint(10000, 99999)}",
            "address": "4800 Deer Lake Drive East, Jacksonville, FL 32246",
        },
        "instructions": "Provide this information to your current 401k administrator for direct rollover.",
    }


async def schedule_advisor_consultation(args: Dict[str, Any]) -> Dict[str, Any]:
    """Schedule advisor consultation."""
    client_id = (args.get("client_id") or "").strip()
    topic = (args.get("topic") or "").strip()
    preferred_time = (args.get("preferred_time") or "").strip()
    advisor_type = (args.get("advisor_type") or "general").strip()
    
    if not client_id or not topic:
        return {"success": False, "message": "client_id and topic required."}
    
    appointment_id = f"APT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    logger.info("📅 Advisor consultation scheduled: %s - topic: %s", client_id, topic)
    
    return {
        "success": True,
        "scheduled": True,
        "appointment_id": appointment_id,
        "advisor_type": advisor_type,
        "topic": topic,
        "scheduled_time": preferred_time or "Next available - within 48 hours",
        "confirmation_sent": True,
        "preparation_tips": [
            "Have recent statements ready",
            "Note specific questions",
            "Know your risk tolerance",
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

register_tool("get_retirement_accounts", get_retirement_accounts_schema, get_retirement_accounts, tags={"investment", "retirement"})
register_tool("get_401k_details", get_401k_details_schema, get_401k_details, tags={"investment", "retirement", "401k"})
register_tool("get_rollover_options", get_rollover_options_schema, get_rollover_options, tags={"investment", "retirement", "rollover"})
register_tool("calculate_tax_impact", calculate_tax_impact_schema, calculate_tax_impact, tags={"investment", "tax"})
register_tool("search_rollover_guidance", search_rollover_guidance_schema, search_rollover_guidance, tags={"investment", "knowledge"})
register_tool("get_account_routing_info", get_account_routing_info_schema, get_account_routing_info, tags={"investment", "transfer"})
register_tool("schedule_advisor_consultation", schedule_advisor_consultation_schema, schedule_advisor_consultation, tags={"investment", "scheduling"})
