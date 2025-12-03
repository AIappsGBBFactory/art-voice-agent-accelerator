"""
Banking Tools
=============

Core banking tools for account info, transactions, cards, and user profiles.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from apps.rtagent.agents.tools.registry import register_tool
from utils.ml_logging import get_logger

logger = get_logger("agents.tools.banking")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

get_user_profile_schema: Dict[str, Any] = {
    "name": "get_user_profile",
    "description": (
        "Retrieve customer profile including account info, preferences, and relationship tier. "
        "Call this immediately after identity verification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
        },
        "required": ["client_id"],
    },
}

get_account_summary_schema: Dict[str, Any] = {
    "name": "get_account_summary",
    "description": (
        "Get summary of customer's accounts including balances, account numbers, and routing info. "
        "Useful for direct deposit setup or balance inquiries."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
        },
        "required": ["client_id"],
    },
}

get_recent_transactions_schema: Dict[str, Any] = {
    "name": "get_recent_transactions",
    "description": (
        "Get recent transactions for customer's primary account. "
        "Includes merchant, amount, date, and fee breakdowns."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "limit": {"type": "integer", "description": "Max transactions to return (default 10)"},
        },
        "required": ["client_id"],
    },
}

search_card_products_schema: Dict[str, Any] = {
    "name": "search_card_products",
    "description": (
        "Search available credit card products based on customer profile and preferences. "
        "Returns personalized card recommendations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_profile": {"type": "string", "description": "Customer tier and spending info"},
            "preferences": {"type": "string", "description": "What they want (travel, cash back, etc.)"},
            "spending_categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Categories like travel, dining, groceries",
            },
        },
        "required": ["preferences"],
    },
}

get_card_details_schema: Dict[str, Any] = {
    "name": "get_card_details",
    "description": "Get detailed information about a specific card product.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "Card product ID"},
            "query": {"type": "string", "description": "Specific question about the card"},
        },
        "required": ["product_id"],
    },
}

refund_fee_schema: Dict[str, Any] = {
    "name": "refund_fee",
    "description": (
        "Process a fee refund for the customer as a courtesy. "
        "Only call after customer explicitly approves the refund."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "transaction_id": {"type": "string", "description": "ID of the fee transaction"},
            "amount": {"type": "number", "description": "Amount to refund"},
            "reason": {"type": "string", "description": "Reason for refund"},
        },
        "required": ["client_id", "amount"],
    },
}

send_card_agreement_schema: Dict[str, Any] = {
    "name": "send_card_agreement",
    "description": "Send cardholder agreement email with verification code for e-signature.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "card_product_id": {"type": "string", "description": "Card product ID"},
        },
        "required": ["client_id", "card_product_id"],
    },
}

verify_esignature_schema: Dict[str, Any] = {
    "name": "verify_esignature",
    "description": "Verify the e-signature code provided by customer.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "verification_code": {"type": "string", "description": "6-digit code from email"},
        },
        "required": ["client_id", "verification_code"],
    },
}

finalize_card_application_schema: Dict[str, Any] = {
    "name": "finalize_card_application",
    "description": "Complete card application after e-signature verification.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "card_product_id": {"type": "string", "description": "Card product ID"},
            "card_name": {"type": "string", "description": "Full card product name"},
        },
        "required": ["client_id", "card_product_id"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK DATA
# ═══════════════════════════════════════════════════════════════════════════════

_MOCK_PROFILES = {
    "CLT-001-JS": {
        "full_name": "John Smith",
        "client_id": "CLT-001-JS",
        "institution_name": "Contoso Bank",
        "contact_info": {"email": "john.smith@email.com", "phone_last_4": "5678"},
        "customer_intelligence": {
            "relationship_context": {"relationship_tier": "Platinum", "relationship_duration_years": 8},
            "bank_profile": {
                "current_balance": 45230.50,
                "accountTenureYears": 8,
                "cards": [{"productName": "Cash Rewards"}],
                "behavior_summary": {"travelSpendShare": 0.25, "diningSpendShare": 0.15, "foreignTransactionCount": 4},
            },
            "spending_patterns": {"avg_monthly_spend": 4500},
            "preferences": {"preferredContactMethod": "mobile"},
        },
    },
    "CLT-002-JD": {
        "full_name": "Jane Doe",
        "client_id": "CLT-002-JD",
        "institution_name": "Contoso Bank",
        "contact_info": {"email": "jane.doe@email.com", "phone_last_4": "9012"},
        "customer_intelligence": {
            "relationship_context": {"relationship_tier": "Gold", "relationship_duration_years": 3},
            "bank_profile": {
                "current_balance": 12500.00,
                "accountTenureYears": 3,
                "cards": [{"productName": "Travel Rewards"}],
                "behavior_summary": {"travelSpendShare": 0.40, "diningSpendShare": 0.20, "foreignTransactionCount": 8},
            },
            "spending_patterns": {"avg_monthly_spend": 3200},
            "preferences": {"preferredContactMethod": "email"},
        },
    },
}

_MOCK_TRANSACTIONS = [
    {"id": "TXN-001", "merchant": "Starbucks", "amount": 5.75, "date": "2024-12-01", "category": "dining"},
    {"id": "TXN-002", "merchant": "ATM - Non-Network", "amount": 18.00, "date": "2024-11-30", "is_fee": True, "fee_breakdown": {"atm_fee": 10.00, "owner_surcharge": 8.00}},
    {"id": "TXN-003", "merchant": "Amazon", "amount": 127.50, "date": "2024-11-29", "category": "shopping"},
    {"id": "TXN-004", "merchant": "Whole Foods", "amount": 89.23, "date": "2024-11-28", "category": "groceries"},
    {"id": "TXN-005", "merchant": "Uber", "amount": 24.50, "date": "2024-11-27", "category": "transport"},
]

_CARD_PRODUCTS = {
    "travel-rewards-001": {
        "product_id": "travel-rewards-001",
        "name": "Contoso Bank Travel Rewards",
        "annual_fee": 0,
        "rewards": "1.5 points per $1 on all purchases",
        "benefits": ["No foreign transaction fees", "Flexible redemption"],
        "intro_apr": "0% for 15 billing cycles",
        "regular_apr": "17.24% - 27.24%",
    },
    "premium-travel-002": {
        "product_id": "premium-travel-002",
        "name": "Contoso Bank Premium Rewards Elite",
        "annual_fee": 550,
        "rewards": "3x on travel and dining, 1.5x on everything else",
        "benefits": ["$300 travel credit", "TSA PreCheck credit", "Airport lounge access", "No foreign fees"],
        "intro_apr": "N/A",
        "regular_apr": "19.24% - 29.24%",
    },
    "cash-back-003": {
        "product_id": "cash-back-003",
        "name": "Contoso Bank Customized Cash Rewards",
        "annual_fee": 0,
        "rewards": "3% in category of choice, 2% grocery/wholesale, 1% everywhere",
        "benefits": ["No annual fee", "Online shopping protection"],
        "intro_apr": "0% for 15 billing cycles",
        "regular_apr": "16.24% - 26.24%",
    },
}

_PENDING_ESIGN: Dict[str, Dict] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_user_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get customer profile."""
    client_id = (args.get("client_id") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    profile = _MOCK_PROFILES.get(client_id)
    if profile:
        logger.info("📋 Profile loaded: %s", client_id)
        return {"success": True, "profile": profile}
    
    return {"success": False, "message": f"Profile not found for {client_id}"}


async def get_account_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get account summary with balances and routing info."""
    client_id = (args.get("client_id") or "").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    profile = _MOCK_PROFILES.get(client_id)
    if not profile:
        return {"success": False, "message": f"Account not found for {client_id}"}
    
    balance = profile["customer_intelligence"]["bank_profile"]["current_balance"]
    
    return {
        "success": True,
        "accounts": [
            {
                "type": "checking",
                "balance": balance,
                "account_number_last4": "4532",
                "routing_number": "026009593",
            },
            {
                "type": "savings",
                "balance": balance * 0.3,
                "account_number_last4": "7891",
                "routing_number": "026009593",
            },
        ],
    }


async def get_recent_transactions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get recent transactions."""
    client_id = (args.get("client_id") or "").strip()
    limit = args.get("limit", 10)
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    return {
        "success": True,
        "transactions": _MOCK_TRANSACTIONS[:limit],
    }


async def search_card_products(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search for card products based on preferences."""
    preferences = (args.get("preferences") or "").strip().lower()
    categories = args.get("spending_categories", [])
    
    results = []
    for card in _CARD_PRODUCTS.values():
        score = 0
        if "travel" in preferences and "travel" in card["name"].lower():
            score += 3
        if "cash" in preferences and "cash" in card["name"].lower():
            score += 3
        if "no fee" in preferences and card["annual_fee"] == 0:
            score += 2
        if score > 0:
            results.append({**card, "_score": score})
    
    # Sort by score
    results.sort(key=lambda x: x.get("_score", 0), reverse=True)
    
    return {
        "success": True,
        "cards": results[:3],
        "message": f"Found {len(results)} matching cards",
    }


async def get_card_details(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get details for a specific card."""
    product_id = (args.get("product_id") or "").strip()
    query = (args.get("query") or "").strip()
    
    card = _CARD_PRODUCTS.get(product_id)
    if not card:
        return {"success": False, "message": f"Card {product_id} not found"}
    
    return {"success": True, "card": card}


async def refund_fee(args: Dict[str, Any]) -> Dict[str, Any]:
    """Process fee refund."""
    client_id = (args.get("client_id") or "").strip()
    amount = args.get("amount", 0)
    reason = (args.get("reason") or "courtesy refund").strip()
    
    if not client_id:
        return {"success": False, "message": "client_id is required."}
    
    logger.info("💰 Fee refund processed: %s - $%.2f", client_id, amount)
    
    return {
        "success": True,
        "refunded": True,
        "amount": amount,
        "message": f"Refund of ${amount:.2f} processed. Credit in 2 business days.",
    }


async def send_card_agreement(args: Dict[str, Any]) -> Dict[str, Any]:
    """Send card agreement email."""
    client_id = (args.get("client_id") or "").strip()
    product_id = (args.get("card_product_id") or "").strip()
    
    if not client_id or not product_id:
        return {"success": False, "message": "client_id and card_product_id required."}
    
    card = _CARD_PRODUCTS.get(product_id)
    if not card:
        return {"success": False, "message": f"Card {product_id} not found"}
    
    # Generate verification code
    import random, string
    code = "".join(random.choices(string.digits, k=6))
    
    _PENDING_ESIGN[client_id] = {"code": code, "card_product_id": product_id}
    
    profile = _MOCK_PROFILES.get(client_id, {})
    email = profile.get("contact_info", {}).get("email", "customer@email.com")
    
    logger.info("📧 Card agreement sent: %s - code: %s", client_id, code)
    
    return {
        "success": True,
        "email_sent": True,
        "verification_code": code,
        "email": email,
        "card_name": card["name"],
        "expires_in_hours": 24,
    }


async def verify_esignature(args: Dict[str, Any]) -> Dict[str, Any]:
    """Verify e-signature code."""
    client_id = (args.get("client_id") or "").strip()
    code = (args.get("verification_code") or "").strip()
    
    if not client_id or not code:
        return {"success": False, "message": "client_id and code required."}
    
    pending = _PENDING_ESIGN.get(client_id)
    if not pending:
        return {"success": False, "message": "No pending agreement found."}
    
    if pending["code"] == code:
        return {
            "success": True,
            "verified": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "card_product_id": pending["card_product_id"],
            "next_step": "finalize_card_application",
        }
    
    return {"success": False, "verified": False, "message": "Invalid code."}


async def finalize_card_application(args: Dict[str, Any]) -> Dict[str, Any]:
    """Finalize card application."""
    client_id = (args.get("client_id") or "").strip()
    product_id = (args.get("card_product_id") or "").strip()
    card_name = (args.get("card_name") or "").strip()
    
    if not client_id or not product_id:
        return {"success": False, "message": "client_id and card_product_id required."}
    
    # Clean up pending
    _PENDING_ESIGN.pop(client_id, None)
    
    card = _CARD_PRODUCTS.get(product_id, {})
    
    logger.info("✅ Card application approved: %s - %s", client_id, card.get("name"))
    
    return {
        "success": True,
        "approved": True,
        "card_number_last4": "".join(random.choices("0123456789", k=4)),
        "credit_limit": random.choice([5000, 7500, 10000, 15000, 20000]),
        "physical_delivery": "3-5 business days",
        "digital_wallet_ready": True,
        "confirmation_email_sent": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

register_tool("get_user_profile", get_user_profile_schema, get_user_profile, tags={"banking", "profile"})
register_tool("get_account_summary", get_account_summary_schema, get_account_summary, tags={"banking", "account"})
register_tool("get_recent_transactions", get_recent_transactions_schema, get_recent_transactions, tags={"banking", "transactions"})
register_tool("search_card_products", search_card_products_schema, search_card_products, tags={"banking", "cards"})
register_tool("get_card_details", get_card_details_schema, get_card_details, tags={"banking", "cards"})
register_tool("refund_fee", refund_fee_schema, refund_fee, tags={"banking", "fees"})
register_tool("send_card_agreement", send_card_agreement_schema, send_card_agreement, tags={"banking", "cards", "esign"})
register_tool("verify_esignature", verify_esignature_schema, verify_esignature, tags={"banking", "cards", "esign"})
register_tool("finalize_card_application", finalize_card_application_schema, finalize_card_application, tags={"banking", "cards", "esign"})
