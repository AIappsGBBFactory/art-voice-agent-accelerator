"""
Banking tools for Erica Concierge, Card Recommendation, and Investment Advisor agents.

Implements customer profile retrieval, account operations, card product search,
and retirement account management for the Bank of America voice assistant.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from utils.ml_logging import get_logger

# Import centralized constants
from ..constants.banking_constants import (
    INSTITUTION_CONFIG,
    CARD_PRODUCTS,
    CARD_KNOWLEDGE_BASE,
    MOCK_CUSTOMER_PROFILE,
    MOCK_ACCOUNT_SUMMARY,
    MOCK_TRANSACTIONS,
    MOCK_RETIREMENT_DATA,
    REFUND_PROCESSING_DAYS,
    card_product_to_dict,
    get_all_card_products,
)

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
        # For now, return mock data from constants
        profile = {
            "client_id": client_id,
            "name": MOCK_CUSTOMER_PROFILE["name"],
            "tier": MOCK_CUSTOMER_PROFILE["tier"],
            "financial_goals": MOCK_CUSTOMER_PROFILE["financial_goals"],
            "alerts": [
                {
                    **alert,
                    "timestamp": _utc_now()
                }
                for alert in MOCK_CUSTOMER_PROFILE["alerts"]
            ],
            "preferred_contact": MOCK_CUSTOMER_PROFILE["preferred_contact"],
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
        # For now, return mock data from constants
        summary = {
            **MOCK_ACCOUNT_SUMMARY,
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
        
        # Use mock transaction data from constants
        transactions = MOCK_TRANSACTIONS
        
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
        
        # Get card products from constants and convert to dicts for processing
        all_cards = [card_product_to_dict(card) for card in get_all_card_products()]
        
        # Tier-aware, data-driven matching logic
        def calculate_match_score(card: Dict[str, Any]) -> int:
            score = 0
            prefs_lower = preferences.lower()
            profile_lower = profile.lower()
            
            # Extract tier from customer profile
            tier = None
            if "platinum" in profile_lower or "preferred rewards" in profile_lower:
                tier = "platinum"
            elif "gold" in profile_lower:
                tier = "gold"
            else:
                tier = "standard"
            
            # Extract monthly spend from profile
            monthly_spend = 0
            if "$" in profile:
                # Extract numeric spend amount (e.g., "$4500" -> 4500)
                import re
                spend_match = re.search(r'\$(\d+(?:,\d+)?)', profile)
                if spend_match:
                    monthly_spend = int(spend_match.group(1).replace(',', ''))
            
            # Tier-based eligibility and scoring
            if tier == "platinum":
                # Platinum customers: Premium cards are great value
                if "premium" in card["name"].lower():
                    score += 15
                elif card["annual_fee"] > 0:
                    score += 5  # Premium cards still good for high-tier customers
            elif tier == "gold":
                # Gold customers: Mid-tier cards, consider annual fee value
                if card["annual_fee"] == 0:
                    score += 5
                if "travel" in card["best_for"] or "rewards" in card["name"].lower():
                    score += 8
            else:
                # Standard tier: No-fee cards are best
                if card["annual_fee"] == 0:
                    score += 10
                if card["annual_fee"] > 50:
                    score -= 5  # Penalize high annual fees for standard tier
            
            # Spending-based ROI calculation
            if monthly_spend > 3000:
                # High spenders benefit from premium cards
                if "2 points" in card["rewards_rate"] or "3%" in card["rewards_rate"]:
                    score += 10
                if card["annual_fee"] > 0 and "$100" in str(card.get("highlights", [])):
                    score += 5  # Credits offset annual fee
            elif monthly_spend > 1500:
                # Medium spenders: Balance rewards and fees
                if "1.5" in card["rewards_rate"]:
                    score += 5
            
            # Match preferences (from handoff context)
            if "travel" in prefs_lower or "foreign" in prefs_lower or "international" in prefs_lower:
                if card["foreign_transaction_fee"] == 0:
                    score += 15  # Critical for international travelers
                if "travel" in card["best_for"]:
                    score += 8
            
            if "avoid fees" in prefs_lower or "no foreign transaction" in prefs_lower:
                if card["foreign_transaction_fee"] == 0:
                    score += 20  # Top priority
            
            if "balance transfer" in prefs_lower or "debt" in prefs_lower:
                if "balance_transfer" in card["best_for"]:
                    score += 12
                if "18 months" in card["intro_apr"]:
                    score += 5
            
            if "rewards" in prefs_lower or "cash back" in prefs_lower:
                if "2 points" in card["rewards_rate"] or "3%" in card["rewards_rate"]:
                    score += 7
            
            if "no fee" in prefs_lower or "free" in prefs_lower:
                if card["annual_fee"] == 0:
                    score += 10
            
            # Match spending categories (from profile behavior)
            for category in categories:
                if category.lower() in card["best_for"]:
                    score += 5
            
            # Foreign transaction frequency boost
            if "foreign" in " ".join(categories).lower() or "international" in " ".join(categories).lower():
                if card["foreign_transaction_fee"] == 0:
                    score += 10
            
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
        
        # Use card knowledge base from constants (simulates RAG until Azure AI Search is connected)
        query_lower = query.lower()
        card_info = CARD_KNOWLEDGE_BASE.get(product_id, {})
        
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
        # For now, return mock data from constants
        retirement_data = MOCK_RETIREMENT_DATA
        
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


class RefundFeeArgs(TypedDict, total=False):
    """Input schema for refund_fee."""
    client_id: str
    amount: float
    fee_type: str
    reason: str


async def refund_fee(args: RefundFeeArgs) -> Dict[str, Any]:
    """
    Process a fee refund for the customer.
    
    Use when:
    - Customer qualifies for courtesy refund (based on tier/tenure)
    - ATM fees, foreign transaction fees, overdraft fees
    - Customer has confirmed they want the refund processed
    
    Args:
        client_id: Customer identifier
        amount: Refund amount in dollars (e.g., 10.00)
        fee_type: Type of fee (e.g., "atm_fee", "foreign_transaction_fee")
        reason: Reason for refund (e.g., "courtesy refund - Platinum member")
    
    Returns success with processing details.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        amount = args.get("amount")
        fee_type = (args.get("fee_type") or "").strip()
        reason = (args.get("reason") or "courtesy refund").strip()
        
        if not client_id or not amount:
            return _json(False, "client_id and amount are required.")
        
        # Validate amount
        try:
            amount = float(amount)
            if amount <= 0:
                return _json(False, "Refund amount must be positive.")
        except (ValueError, TypeError):
            return _json(False, "Invalid refund amount.")
        
        logger.info(
            "💵 Processing fee refund | client_id=%s amount=$%.2f type=%s",
            client_id, amount, fee_type
        )
        
        # Mock refund processing
        return {
            "success": True,
            "message": f"Refund of ${amount:.2f} processed successfully.",
            "refund_amount": amount,
            "fee_type": fee_type,
            "reason": reason,
            "processing_time": REFUND_PROCESSING_DAYS,
            "confirmation_number": f"RFD{client_id[-4:]}{int(amount*100):04d}",
            "timestamp": _utc_now()
        }
    
    except Exception as exc:
        logger.error("Fee refund failed: %s", exc, exc_info=True)
        return _json(False, "Unable to process refund.")
