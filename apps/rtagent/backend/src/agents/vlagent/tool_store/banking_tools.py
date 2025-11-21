"""
Banking tools for Erica Concierge, Card Recommendation, and Investment Advisor agents.

Implements customer profile retrieval, account operations, card product search,
and retirement account management for the Bank of America voice assistant.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from utils.ml_logging import get_logger

logger = get_logger("banking_tools")


def _json(
    success: bool,
    message: str,
    **extras: Any,
) -> Dict[str, Any]:
    """Helper to build consistent JSON responses."""
    result = {"success": success, "message": message}
    result.update(extras)
    return result


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# USER PROFILE & ACCOUNT TOOLS
# ═══════════════════════════════════════════════════════════════════


class GetUserProfileArgs(TypedDict, total=False):
    """Input schema for get_user_profile."""
    client_id: str


async def get_user_profile(args: GetUserProfileArgs) -> Dict[str, Any]:
    """
    Retrieve comprehensive customer profile from Cosmos DB.
    
    Returns customer intelligence including:
    - Preferred tier (Gold, Platinum, Preferred Rewards)
    - Financial goals
    - Recent alerts (overdraft, low balance, promotional offers)
    - Account preferences
    
    This data is used for personalization and proactive assistance.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        if not client_id:
            return _json(False, "client_id is required.")
        
        logger.info("📋 Fetching user profile | client_id=%s", client_id)
        
        # TODO: Query Cosmos DB financial_services_db.users collection
        # For now, return mock data structure
        profile = {
            "client_id": client_id,
            "name": "Alex Thompson",
            "tier": "Platinum",
            "financial_goals": ["Save for home down payment", "Reduce credit card fees"],
            "alerts": [
                {
                    "type": "promotional",
                    "message": "You qualify for 0% APR balance transfer on Premium Rewards card",
                    "timestamp": _utc_now()
                }
            ],
            "preferred_contact": "mobile",
            "last_login": _utc_now()
        }
        
        return _json(
            True,
            "Profile retrieved successfully.",
            profile=profile
        )
    
    except Exception as exc:
        logger.error("Profile retrieval failed: %s", exc, exc_info=True)
        return _json(False, "Unable to retrieve profile at this time.")


class GetAccountSummaryArgs(TypedDict, total=False):
    """Input schema for get_account_summary."""
    client_id: str


async def get_account_summary(args: GetAccountSummaryArgs) -> Dict[str, Any]:
    """
    Get real-time account balances and summary from session profile.
    
    Returns:
    - Checking account balance
    - Savings account balance
    - Credit card balances
    - Recent transaction count
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        if not client_id:
            return _json(False, "client_id is required.")
        
        logger.info("💰 Fetching account summary | client_id=%s", client_id)
        
        # TODO: Query from session_profile.customer_intelligence.accounts
        summary = {
            "checking": {
                "account_number": "****1234",
                "balance": 2450.67,
                "available": 2450.67
            },
            "savings": {
                "account_number": "****5678",
                "balance": 15230.00,
                "available": 15230.00
            },
            "credit_cards": [
                {
                    "product_name": "Cash Rewards",
                    "last_four": "9012",
                    "balance": 450.00,
                    "credit_limit": 5000.00,
                    "available_credit": 4550.00
                }
            ],
            "as_of": _utc_now()
        }
        
        return _json(
            True,
            "Account summary retrieved.",
            summary=summary
        )
    
    except Exception as exc:
        logger.error("Account summary failed: %s", exc, exc_info=True)
        return _json(False, "Unable to retrieve account summary.")


class GetRecentTransactionsArgs(TypedDict, total=False):
    """Input schema for get_recent_transactions."""
    client_id: str
    limit: int
    account_type: str


async def get_recent_transactions(args: GetRecentTransactionsArgs) -> Dict[str, Any]:
    """
    Retrieve recent transaction history.
    
    Parameters:
    - client_id: Customer identifier
    - limit: Number of transactions to return (default 10)
    - account_type: 'checking', 'savings', or 'credit' (default all)
    
    Returns list of recent transactions with dates, amounts, merchants.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        if not client_id:
            return _json(False, "client_id is required.")
        
        limit = args.get("limit", 10)
        account_type = (args.get("account_type") or "all").strip()
        
        logger.info(
            "📊 Fetching recent transactions | client_id=%s limit=%d type=%s",
            client_id, limit, account_type
        )
        
        transactions = [
            {
                "date": "2025-11-20",
                "merchant": "Gas Station",
                "amount": -42.15,
                "account": "****1234",
                "type": "debit",
                "category": "transportation"
            },
            {
                "date": "2025-11-19",
                "merchant": "Coffee Shop",
                "amount": -5.75,
                "account": "****9012",
                "type": "credit",
                "category": "dining"
            },
            {
                "date": "2025-11-18",
                "merchant": "Online Retailer",
                "amount": -89.99,
                "account": "****9012",
                "type": "credit",
                "category": "shopping"
            },
            {
                "date": "2025-11-17",
                "merchant": "Streaming Service",
                "amount": -14.99,
                "account": "****1234",
                "type": "debit",
                "category": "entertainment"
            },
            {
                "date": "2025-11-16",
                "merchant": "Grocery Store",
                "amount": -123.45,
                "account": "****1234",
                "type": "debit",
                "category": "groceries"
            },
            {
                "date": "2025-11-15",
                "merchant": "Payroll Deposit - Employer",
                "amount": 2850.00,
                "account": "****1234",
                "type": "credit",
                "category": "income"
            },
            {
                "date": "2025-11-14",
                "merchant": "Electric Company",
                "amount": -89.32,
                "account": "****1234",
                "type": "debit",
                "category": "utilities"
            },
            {
                "date": "2025-11-13",
                "merchant": "Restaurant",
                "amount": -65.20,
                "account": "****9012",
                "type": "credit",
                "category": "dining"
            },
            {
                "date": "2025-11-12",
                "merchant": "Pharmacy",
                "amount": -27.50,
                "account": "****1234",
                "type": "debit",
                "category": "health"
            },
            {
                "date": "2025-11-11",
                "merchant": "Mobile Phone Bill",
                "amount": -75.00,
                "account": "****1234",
                "type": "debit",
                "category": "utilities"
            }
        ]
        
        return _json(
            True,
            f"Retrieved {len(transactions)} recent transactions.",
            transactions=transactions[:limit]
        )
    
    except Exception as exc:
        logger.error("Transaction retrieval failed: %s", exc, exc_info=True)
        return _json(False, "Unable to retrieve transactions.")


# ═══════════════════════════════════════════════════════════════════
# CARD RECOMMENDATION TOOLS
# ═══════════════════════════════════════════════════════════════════


class SearchCardProductsArgs(TypedDict, total=False):
    """Input schema for search_card_products."""
    customer_profile: str
    preferences: str
    spending_categories: List[str]


async def search_card_products(args: SearchCardProductsArgs) -> Dict[str, Any]:
    """
    Search credit card products from Cosmos DB based on customer preferences.
    
    Parameters:
    - customer_profile: Brief description of customer (tier, spending habits)
    - preferences: What customer is looking for (cash back, travel, balance transfer)
    - spending_categories: List of primary spending areas (groceries, gas, dining, travel)
    
    Returns ranked list of matching card products with key features.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        profile = (args.get("customer_profile") or "").strip()
        preferences = (args.get("preferences") or "").strip()
        categories = args.get("spending_categories", [])
        
        logger.info(
            "💳 Searching card products | profile=%s prefs=%s categories=%s",
            profile, preferences, categories
        )
        
        # Card product catalog with matching logic
        all_cards = [
            {
                "product_id": "travel-rewards-001",
                "name": "Travel Rewards Credit Card",
                "annual_fee": 0,
                "foreign_transaction_fee": 0,
                "rewards_rate": "1.5 points per $1 on all purchases",
                "intro_apr": "0% for 12 months on purchases",
                "sign_up_bonus": "25,000 bonus points after $1,000 spend in 90 days",
                "best_for": ["travel", "international", "no_annual_fee", "foreign_fee_avoidance"],
                "tier_requirement": "None",
                "highlights": [
                    "No annual fee",
                    "No foreign transaction fees",
                    "Unlimited 1.5% cash back",
                    "Travel insurance included"
                ]
            },
            {
                "product_id": "premium-rewards-001",
                "name": "Premium Rewards Credit Card",
                "annual_fee": 95,
                "foreign_transaction_fee": 0,
                "rewards_rate": "2 points per $1 on travel & dining, 1.5 points per $1 on everything else",
                "intro_apr": "0% for 15 months on purchases and balance transfers",
                "sign_up_bonus": "60,000 bonus points after $4,000 spend in 90 days",
                "best_for": ["travel", "dining", "balance_transfer", "premium_benefits"],
                "tier_requirement": "Preferred Rewards",
                "highlights": [
                    "$95 annual fee",
                    "2x points on travel and dining",
                    "$100 airline fee credit",
                    "$100 TSA PreCheck/Global Entry credit",
                    "Comprehensive travel insurance"
                ]
            },
            {
                "product_id": "cash-rewards-002",
                "name": "Customized Cash Rewards Credit Card",
                "annual_fee": 0,
                "foreign_transaction_fee": 3,
                "rewards_rate": "3% cash back on choice category, 2% at grocery stores and wholesale clubs, 1% on everything else",
                "intro_apr": "0% for 15 months on purchases and balance transfers",
                "sign_up_bonus": "$200 online cash rewards bonus after $1,000 in purchases in first 90 days",
                "best_for": ["groceries", "gas", "online_shopping", "everyday", "balance_transfer"],
                "tier_requirement": "None",
                "highlights": [
                    "No annual fee",
                    "3% cash back on your choice category",
                    "2% at grocery stores and wholesale clubs",
                    "1% cash back on all other purchases"
                ]
            },
            {
                "product_id": "unlimited-cash-003",
                "name": "Unlimited Cash Rewards Credit Card",
                "annual_fee": 0,
                "foreign_transaction_fee": 3,
                "rewards_rate": "1.5% cash back on all purchases",
                "intro_apr": "0% for 18 months on purchases and balance transfers",
                "sign_up_bonus": "$200 online cash rewards bonus",
                "best_for": ["balance_transfer", "everyday", "simple_rewards"],
                "tier_requirement": "None",
                "highlights": [
                    "No annual fee",
                    "Unlimited 1.5% cash back on all purchases",
                    "0% intro APR for 18 months",
                    "No categories to track"
                ]
            }
        ]
        
        # Simple matching logic based on preferences and categories
        def calculate_match_score(card: Dict[str, Any]) -> int:
            score = 0
            prefs_lower = preferences.lower()
            
            # Match preferences
            if "travel" in prefs_lower or "foreign" in prefs_lower or "international" in prefs_lower:
                if card["foreign_transaction_fee"] == 0:
                    score += 10
                if "travel" in card["best_for"]:
                    score += 5
            
            if "balance transfer" in prefs_lower or "debt" in prefs_lower:
                if "balance_transfer" in card["best_for"]:
                    score += 10
                if "18 months" in card["intro_apr"]:
                    score += 5
            
            if "rewards" in prefs_lower or "cash back" in prefs_lower:
                if "2 points" in card["rewards_rate"] or "3%" in card["rewards_rate"]:
                    score += 5
            
            if "no fee" in prefs_lower or "free" in prefs_lower:
                if card["annual_fee"] == 0:
                    score += 5
            
            # Match spending categories
            for category in categories:
                if category.lower() in card["best_for"]:
                    score += 3
            
            return score
        
        # Rank cards by match score
        scored_cards = [(card, calculate_match_score(card)) for card in all_cards]
        scored_cards.sort(key=lambda x: x[1], reverse=True)
        
        # Return top 3 cards
        top_cards = [card for card, score in scored_cards[:3]]
        
        return _json(
            True,
            f"Found {len(top_cards)} matching card products.",
            products=top_cards
        )
    
    except Exception as exc:
        logger.error("Card search failed: %s", exc, exc_info=True)
        return _json(False, "Unable to search card products.")


class GetCardDetailsArgs(TypedDict, total=False):
    """Input schema for get_card_details."""
    product_id: str
    query: str


async def get_card_details(args: GetCardDetailsArgs) -> Dict[str, Any]:
    """
    Get detailed information about a specific card product using Azure AI Search RAG.
    
    Parameters:
    - product_id: Unique card product identifier
    - query: Specific question about the card (fees, rewards, eligibility, etc.)
    
    Returns detailed answer grounded in indexed card documentation.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        product_id = (args.get("product_id") or "").strip()
        query = (args.get("query") or "").strip()
        
        if not product_id or not query:
            return _json(False, "Both product_id and query are required.")
        
        logger.info(
            "🔍 Getting card details | product_id=%s query=%s",
            product_id, query
        )
        
        # Card-specific knowledge base (simulates RAG until Azure AI Search is connected)
        card_knowledge = {
            "travel-rewards-001": {
                "apr": "Variable APR of 19.24% - 29.24% after intro period",
                "foreign_fees": "No foreign transaction fees on purchases made outside the US",
                "eligibility": "Good to excellent credit (FICO 670+). Must be 18+ and US resident.",
                "benefits": "No annual fee, travel insurance up to $250,000, baggage delay insurance, rental car coverage",
                "rewards": "Earn 1.5 points per $1 on all purchases with no category restrictions or caps",
                "balance_transfer": "0% intro APR for 12 months, then variable APR. 3% balance transfer fee"
            },
            "premium-rewards-001": {
                "apr": "Variable APR of 18.24% - 28.24% after intro period",
                "foreign_fees": "No foreign transaction fees",
                "eligibility": "Excellent credit (FICO 750+). Preferred Rewards tier recommended for maximum benefits.",
                "benefits": "$95 annual fee. $100 airline fee credit, $100 TSA PreCheck/Global Entry credit, travel insurance up to $500,000, trip cancellation coverage, lost luggage reimbursement",
                "rewards": "Earn 2 points per $1 on travel and dining, 1.5 points per $1 on all other purchases. Points value increases with Preferred Rewards tier: up to 75% bonus",
                "balance_transfer": "0% intro APR for 15 months, then variable APR. 3% balance transfer fee ($10 minimum)"
            },
            "cash-rewards-002": {
                "apr": "Variable APR of 19.24% - 29.24% after intro period",
                "foreign_fees": "3% foreign transaction fee on purchases made outside the US",
                "eligibility": "Good to excellent credit (FICO 670+)",
                "benefits": "No annual fee, choose your 3% cash back category each month (gas, online shopping, dining, travel, drugstores, home improvement)",
                "rewards": "3% cash back in your choice category (up to $2,500 per quarter), 2% at grocery stores and wholesale clubs (up to $2,500 per quarter), 1% on all other purchases",
                "balance_transfer": "0% intro APR for 15 months on purchases and balance transfers, then variable APR. 3% balance transfer fee"
            },
            "unlimited-cash-003": {
                "apr": "Variable APR of 18.24% - 28.24% after intro period",
                "foreign_fees": "3% foreign transaction fee",
                "eligibility": "Good credit (FICO 670+)",
                "benefits": "No annual fee, simple unlimited cash back structure with no categories to track",
                "rewards": "Flat 1.5% cash back on all purchases with no limits or caps",
                "balance_transfer": "0% intro APR for 18 months on purchases and balance transfers, then variable APR. 3% balance transfer fee ($10 minimum)"
            }
        }
        
        # Try to answer the query based on card knowledge
        query_lower = query.lower()
        card_info = card_knowledge.get(product_id, {})
        
        answer = "Information not available for this card."
        sources = [{"doc": f"{product_id}_terms.pdf", "page": 1}]
        
        if "apr" in query_lower or "rate" in query_lower or "interest" in query_lower:
            answer = card_info.get("apr", "APR information not available.")
        elif "foreign" in query_lower or "international" in query_lower:
            answer = card_info.get("foreign_fees", "Foreign fee information not available.")
        elif "eligible" in query_lower or "qualify" in query_lower or "credit score" in query_lower:
            answer = card_info.get("eligibility", "Eligibility information not available.")
        elif "benefit" in query_lower or "perk" in query_lower or "insurance" in query_lower:
            answer = card_info.get("benefits", "Benefits information not available.")
        elif "reward" in query_lower or "points" in query_lower or "cash back" in query_lower:
            answer = card_info.get("rewards", "Rewards information not available.")
        elif "balance transfer" in query_lower or "transfer balance" in query_lower:
            answer = card_info.get("balance_transfer", "Balance transfer information not available.")
        else:
            # General query - return most relevant info
            answer = f"{card_info.get('rewards', '')} {card_info.get('benefits', '')}"
        
        return _json(
            True,
            "Card details retrieved.",
            details={
                "product_id": product_id,
                "query": query,
                "answer": answer,
                "sources": sources
            }
        )
    
    except Exception as exc:
        logger.error("Card details retrieval failed: %s", exc, exc_info=True)
        return _json(False, "Unable to retrieve card details.")


# ═══════════════════════════════════════════════════════════════════
# INVESTMENT & RETIREMENT TOOLS
# ═══════════════════════════════════════════════════════════════════


class GetRetirementAccountsArgs(TypedDict, total=False):
    """Input schema for get_retirement_accounts."""
    client_id: str


async def get_retirement_accounts(args: GetRetirementAccountsArgs) -> Dict[str, Any]:
    """
    Retrieve customer's retirement account information from session profile.
    
    Returns:
    - 401(k) balances and contribution rates
    - IRA accounts
    - Retirement readiness score
    - Rollover eligibility
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        if not client_id:
            return _json(False, "client_id is required.")
        
        logger.info("🏦 Fetching retirement accounts | client_id=%s", client_id)
        
        # TODO: Query from session_profile.customer_intelligence.retirement_profile
        retirement_data = {
            "has_401k": True,
            "former_employer_401k": {
                "provider": "Fidelity",
                "balance": 45000.00,
                "eligible_for_rollover": True
            },
            "current_ira": {
                "type": "Traditional IRA",
                "balance": 12000.00,
                "account_number": "****7890"
            },
            "retirement_readiness_score": 6.5,
            "suggested_actions": [
                "Consider rolling over former 401(k) to IRA for lower fees",
                "Increase contribution rate to meet retirement goals"
            ]
        }
        
        return _json(
            True,
            "Retirement accounts retrieved.",
            retirement=retirement_data
        )
    
    except Exception as exc:
        logger.error("Retirement account retrieval failed: %s", exc, exc_info=True)
        return _json(False, "Unable to retrieve retirement accounts.")


class SearchRolloverGuidanceArgs(TypedDict, total=False):
    """Input schema for search_rollover_guidance."""
    query: str
    account_type: str


async def search_rollover_guidance(args: SearchRolloverGuidanceArgs) -> Dict[str, Any]:
    """
    Search retirement rollover guidance using Azure AI Search RAG.
    
    Parameters:
    - query: Customer's question about rollovers, taxes, deadlines, etc.
    - account_type: Type of retirement account (401k, 403b, IRA)
    
    Returns detailed guidance grounded in IRS rules and Bank of America policies.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        query = (args.get("query") or "").strip()
        account_type = (args.get("account_type") or "401k").strip()
        
        if not query:
            return _json(False, "query is required.")
        
        logger.info(
            "📚 Searching rollover guidance | query=%s type=%s",
            query, account_type
        )
        
        # TODO: Query Azure AI Search for retirement guidance documents
        guidance = {
            "query": query,
            "answer": "You have 60 days from receiving a distribution to roll it over to another qualified retirement plan. A direct rollover is recommended to avoid the mandatory 20% tax withholding. Bank of America can facilitate a direct trustee-to-trustee transfer to avoid any tax implications.",
            "sources": [
                {"doc": "ira_rollover_guide_2025.pdf", "page": 5},
                {"doc": "irs_publication_590.pdf", "page": 28}
            ],
            "next_steps": [
                "Gather former employer 401(k) statements",
                "Schedule call with Merrill advisor to initiate rollover"
            ]
        }
        
        return _json(
            True,
            "Rollover guidance retrieved.",
            guidance=guidance
        )
    
    except Exception as exc:
        logger.error("Rollover guidance search failed: %s", exc, exc_info=True)
        return _json(False, "Unable to search rollover guidance.")


class HandoffMerrillAdvisorArgs(TypedDict, total=False):
    """Input schema for handoff_merrill_advisor."""
    client_id: str
    reason: str
    context: str


async def handoff_merrill_advisor(args: HandoffMerrillAdvisorArgs) -> Dict[str, Any]:
    """
    Escalate to human Merrill Lynch financial advisor.
    
    Use when:
    - Customer needs personalized investment advice
    - Complex retirement planning beyond AI capabilities
    - Account opening or fund transfers
    - Customer explicitly requests human advisor
    
    This is a human escalation, not an AI agent handoff.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        reason = (args.get("reason") or "").strip()
        context = (args.get("context") or "").strip()
        
        if not client_id or not reason:
            return _json(False, "client_id and reason are required.")
        
        logger.info(
            "👤 Escalating to Merrill advisor | client_id=%s reason=%s",
            client_id, reason
        )
        
        # This triggers human escalation flow in orchestrator
        return {
            "success": True,
            "message": "Connecting you with a Merrill financial advisor. Please hold.",
            "handoff": "human",
            "target": "merrill_advisor",
            "escalation_reason": reason,
            "context": context,
            "should_interrupt_playback": True
        }
    
    except Exception as exc:
        logger.error("Merrill advisor handoff failed: %s", exc, exc_info=True)
        return _json(False, "Unable to connect to advisor.")
