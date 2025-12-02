"""
Banking Constants & Synthetic Data Configuration
================================================

Central repository for all banking-related constants, mock data, and configuration.
Edit this file to customize the demo experience for different institutions or scenarios.

Architecture:
- All hardcoded demo data is centralized here
- Tool modules import from this file instead of inline definitions
- Enables easy A/B testing of different demo scenarios
- Supports multi-tenant customization via environment overrides

Usage:
    from .constants.banking_constants import (
        INSTITUTION_CONFIG,
        CARD_PRODUCTS,
        MOCK_CUSTOMER_PROFILE,
    )
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: INSTITUTION CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class InstitutionConfig:
    """Financial institution branding and contact configuration."""
    name: str = "Bank of America"
    routing_number: str = "026009593"
    swift_code: str = "BOFAUS3N"
    support_phone: str = "1-800-432-1000"
    support_phone_display: str = "1-800-432-1000"
    website_domain: str = "bankofamerica.com"
    secure_domain: str = "secure.bankofamerica.com"
    atm_network_count: str = "40,000+"
    partner_atm_message: str = "No fees at 40,000+ Bank of America ATMs nationwide and partner ATMs internationally"


# Allow environment override for multi-tenant demos
INSTITUTION_CONFIG = InstitutionConfig(
    name=os.getenv("INSTITUTION_NAME", "Bank of America"),
    support_phone=os.getenv("INSTITUTION_SUPPORT_PHONE", "1-800-432-1000"),
)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: CUSTOMER TIERS & INCOME BANDS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CustomerTierConfig:
    """Customer tier definitions and benefits."""
    name: str
    rewards_bonus_pct: int  # e.g., 75 for 75% bonus
    annual_fee_waived: bool
    description: str


CUSTOMER_TIERS: Dict[str, CustomerTierConfig] = {
    "platinum": CustomerTierConfig(
        name="Preferred Rewards Platinum",
        rewards_bonus_pct=75,
        annual_fee_waived=True,
        description="Preferred Rewards Platinum: 75% rewards bonus + expedited benefits"
    ),
    "gold": CustomerTierConfig(
        name="Preferred Rewards Gold",
        rewards_bonus_pct=50,
        annual_fee_waived=False,
        description="Preferred Rewards Gold: 50% rewards bonus"
    ),
    "standard": CustomerTierConfig(
        name="Standard",
        rewards_bonus_pct=0,
        annual_fee_waived=False,
        description="Standard rewards earning"
    ),
}

# Credit limits by income band (used in card approval)
CREDIT_LIMITS_BY_INCOME: Dict[str, int] = {
    "high": 15000,
    "medium": 8500,
    "low": 5000,
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: CREDIT CARD PRODUCT CATALOG
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CardProduct:
    """Credit card product definition."""
    product_id: str
    name: str
    annual_fee: int
    foreign_transaction_fee: float  # as percentage (0, 3, etc.)
    rewards_rate: str
    intro_apr: str
    regular_apr: str
    sign_up_bonus: str
    best_for: List[str]
    tier_requirement: str
    tier_benefits: Dict[str, str]
    highlights: List[str]
    atm_benefits: str
    # Optional extended attributes
    roi_example: Optional[str] = None


# Complete card product catalog
CARD_PRODUCTS: Dict[str, CardProduct] = {
    "travel-rewards-001": CardProduct(
        product_id="travel-rewards-001",
        name="Travel Rewards Credit Card",
        annual_fee=0,
        foreign_transaction_fee=0,
        rewards_rate="1.5 points per $1 on all purchases",
        intro_apr="0% for 12 months on purchases",
        regular_apr="19.24% - 29.24% variable APR",
        sign_up_bonus="25,000 bonus points after $1,000 spend in 90 days",
        best_for=["travel", "international", "no_annual_fee", "foreign_fee_avoidance"],
        tier_requirement="All tiers (Gold, Platinum, Standard)",
        tier_benefits={
            "platinum": "Preferred Rewards members earn 25%-75% more points",
            "gold": "Gold members earn 25%-50% more points",
            "standard": "Standard rewards earning"
        },
        highlights=[
            "No annual fee",
            "No foreign transaction fees - perfect for international travelers",
            "Unlimited 1.5% cash back or travel rewards",
            "Redeem points for travel, dining, or cash back with no blackout dates",
            "Travel insurance included (trip delay, baggage delay)",
            "No foreign ATM network fees when using partner ATMs"
        ],
        atm_benefits="No fees at 40,000+ Bank of America ATMs nationwide and partner ATMs internationally"
    ),
    "premium-rewards-001": CardProduct(
        product_id="premium-rewards-001",
        name="Premium Rewards Credit Card",
        annual_fee=95,
        foreign_transaction_fee=0,
        rewards_rate="2 points per $1 on travel & dining, 1.5 points per $1 on everything else",
        intro_apr="0% for 15 months on purchases and balance transfers",
        regular_apr="19.24% - 29.24% variable APR",
        sign_up_bonus="60,000 bonus points after $4,000 spend in 90 days",
        best_for=["travel", "dining", "balance_transfer", "premium_benefits", "international"],
        tier_requirement="Preferred Rewards Platinum or Gold (income verification required)",
        tier_benefits={
            "platinum": "Preferred Rewards Platinum: 75% rewards bonus + expedited benefits",
            "gold": "Preferred Rewards Gold: 50% rewards bonus",
            "standard": "Not recommended - consider Travel Rewards card instead"
        },
        highlights=[
            "$95 annual fee (waived first year for Platinum tier)",
            "2x points on travel and dining - ideal for high spenders",
            "$100 airline fee credit (reimbursement for baggage fees, seat selection)",
            "$100 TSA PreCheck/Global Entry credit every 4 years",
            "Comprehensive travel insurance (trip cancellation, interruption, delay)",
            "No foreign transaction fees on any purchase",
            "Priority airport lounge access (4 free visits annually)"
        ],
        atm_benefits="No fees at 40,000+ Bank of America ATMs + no fees at international partner ATMs",
        roi_example="Customer spending $4,000/month on travel & dining earns ~$1,200/year in rewards, offsetting annual fee"
    ),
    "cash-rewards-002": CardProduct(
        product_id="cash-rewards-002",
        name="Customized Cash Rewards Credit Card",
        annual_fee=0,
        foreign_transaction_fee=3,
        rewards_rate="3% cash back on choice category, 2% at grocery stores and wholesale clubs, 1% on everything else",
        intro_apr="0% for 15 months on purchases and balance transfers",
        regular_apr="19.24% - 29.24% variable APR",
        sign_up_bonus="$200 online cash rewards bonus after $1,000 in purchases in first 90 days",
        best_for=["groceries", "gas", "online_shopping", "everyday", "balance_transfer", "domestic"],
        tier_requirement="All tiers",
        tier_benefits={
            "platinum": "Preferred Rewards Platinum: 75% cash back bonus (up to 5.25% on choice category)",
            "gold": "Preferred Rewards Gold: 50% cash back bonus (up to 4.5% on choice category)",
            "standard": "Standard 3% cash back on choice category"
        },
        highlights=[
            "No annual fee",
            "3% cash back on your choice category (gas, online shopping, dining, travel, drugstores, or home improvement)",
            "2% at grocery stores and wholesale clubs (up to $2,500 in combined quarterly purchases)",
            "1% cash back on all other purchases",
            "Not ideal for international travelers - 3% foreign transaction fee"
        ],
        atm_benefits="Standard Bank of America ATM access"
    ),
    "unlimited-cash-003": CardProduct(
        product_id="unlimited-cash-003",
        name="Unlimited Cash Rewards Credit Card",
        annual_fee=0,
        foreign_transaction_fee=3,
        rewards_rate="1.5% cash back on all purchases",
        intro_apr="0% for 18 months on purchases and balance transfers",
        regular_apr="19.24% - 29.24% variable APR",
        sign_up_bonus="$200 online cash rewards bonus",
        best_for=["balance_transfer", "everyday", "simple_rewards", "domestic"],
        tier_requirement="All tiers",
        tier_benefits={
            "platinum": "Preferred Rewards Platinum: 75% cash back bonus (2.625% on everything)",
            "gold": "Preferred Rewards Gold: 50% cash back bonus (2.25% on everything)",
            "standard": "Standard 1.5% cash back"
        },
        highlights=[
            "No annual fee",
            "Unlimited 1.5% cash back on all purchases",
            "0% intro APR for 18 months - longest intro period for balance transfers",
            "No categories to track - simple flat-rate rewards",
            "Not ideal for international travelers - 3% foreign transaction fee"
        ],
        atm_benefits="Standard Bank of America ATM access"
    ),
}


def get_card_product(product_id: str) -> Optional[CardProduct]:
    """Get card product by ID."""
    return CARD_PRODUCTS.get(product_id)


def get_all_card_products() -> List[CardProduct]:
    """Get all card products as a list."""
    return list(CARD_PRODUCTS.values())


def card_product_to_dict(card: CardProduct) -> Dict[str, Any]:
    """Convert CardProduct dataclass to dict for JSON serialization."""
    return {
        "product_id": card.product_id,
        "name": card.name,
        "annual_fee": card.annual_fee,
        "foreign_transaction_fee": card.foreign_transaction_fee,
        "rewards_rate": card.rewards_rate,
        "intro_apr": card.intro_apr,
        "regular_apr": card.regular_apr,
        "sign_up_bonus": card.sign_up_bonus,
        "best_for": card.best_for,
        "tier_requirement": card.tier_requirement,
        "tier_benefits": card.tier_benefits,
        "highlights": card.highlights,
        "atm_benefits": card.atm_benefits,
        "roi_example": card.roi_example,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: CARD KNOWLEDGE BASE (RAG Fallback)
# ═══════════════════════════════════════════════════════════════════════════════

# Card-specific FAQ answers when Azure AI Search is unavailable
CARD_KNOWLEDGE_BASE: Dict[str, Dict[str, str]] = {
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


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: MOCK CUSTOMER DATA (Demo Profiles)
# ═══════════════════════════════════════════════════════════════════════════════

def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# Default mock customer profile (used when Cosmos DB is unavailable)
MOCK_CUSTOMER_PROFILE: Dict[str, Any] = {
    "client_id": "demo-001",
    "name": "Alex Thompson",
    "tier": "Platinum",
    "financial_goals": ["Save for home down payment", "Reduce credit card fees"],
    "alerts": [
        {
            "type": "promotional",
            "message": "You qualify for 0% APR balance transfer on Premium Rewards card",
        }
    ],
    "preferred_contact": "mobile",
}

# Default mock account summary
MOCK_ACCOUNT_SUMMARY: Dict[str, Any] = {
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
}

# Default mock transaction history
# Designed to showcase ATM fees, foreign transaction fees, and various categories
MOCK_TRANSACTIONS: List[Dict[str, Any]] = [
    {
        "date": "2025-11-20",
        "merchant": "ATM Withdrawal - Non-Network ATM",
        "amount": -18.00,
        "account": "****1234",
        "type": "fee",
        "category": "atm_fee",
        "location": "Paris, France",
        "fee_breakdown": {
            "bank_fee": 10.00,
            "foreign_atm_surcharge": 8.00,
            "description": "Non-network ATM withdrawal outside our partner network. Foreign ATM surcharge set by ATM owner."
        },
        "is_foreign_transaction": True,
        "network_status": "non-network"
    },
    {
        "date": "2025-11-20",
        "merchant": "ATM Cash Withdrawal",
        "amount": -200.00,
        "account": "****1234",
        "type": "debit",
        "category": "cash_withdrawal",
        "location": "Paris, France",
        "is_foreign_transaction": True
    },
    {
        "date": "2025-11-19",
        "merchant": "Hotel Le Royal",
        "amount": -385.00,
        "account": "****9012",
        "type": "credit",
        "category": "travel",
        "location": "Paris, France",
        "foreign_transaction_fee": 11.55,
        "is_foreign_transaction": True
    },
    {
        "date": "2025-11-19",
        "merchant": "Foreign Transaction Fee",
        "amount": -11.55,
        "account": "****9012",
        "type": "fee",
        "category": "foreign_transaction_fee",
        "fee_breakdown": {
            "description": "3% foreign transaction fee on $385.00 purchase",
            "base_transaction": 385.00,
            "fee_percentage": 3.0
        },
        "is_foreign_transaction": True
    },
    {
        "date": "2025-11-18",
        "merchant": "Restaurant Le Bistro",
        "amount": -125.00,
        "account": "****9012",
        "type": "credit",
        "category": "dining",
        "location": "Paris, France",
        "is_foreign_transaction": True
    },
    {
        "date": "2025-11-17",
        "merchant": "Airline - International Flight",
        "amount": -850.00,
        "account": "****9012",
        "type": "credit",
        "category": "travel"
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
        "merchant": "Gas Station",
        "amount": -65.00,
        "account": "****9012",
        "type": "credit",
        "category": "transportation"
    },
    {
        "date": "2025-11-13",
        "merchant": "Coffee Shop",
        "amount": -5.75,
        "account": "****9012",
        "type": "credit",
        "category": "dining"
    },
    {
        "date": "2025-11-12",
        "merchant": "Online Retailer",
        "amount": -89.99,
        "account": "****9012",
        "type": "credit",
        "category": "shopping"
    },
    {
        "date": "2025-11-11",
        "merchant": "Streaming Service",
        "amount": -14.99,
        "account": "****1234",
        "type": "debit",
        "category": "entertainment"
    }
]

# Default mock retirement data
MOCK_RETIREMENT_DATA: Dict[str, Any] = {
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


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: AI SEARCH CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Known card names for fuzzy matching in AI Search queries
KNOWN_CARD_NAMES: List[str] = [
    "Premium Rewards",
    "Travel Rewards",
    "Unlimited Cash Rewards",
    "Customized Cash Rewards",
    "BankAmericard",
    "Elite",
]

# Card name abbreviation mappings for normalization
CARD_NAME_ABBREVIATIONS: Dict[str, str] = {
    "premium": "Premium Rewards",
    "travel": "Travel Rewards",
    "unlimited": "Unlimited Cash Rewards",
    "unlimited cash": "Unlimited Cash Rewards",
    "customized": "Customized Cash Rewards",
    "customized cash": "Customized Cash Rewards",
    "bankamericard": "BankAmericard",
    "elite": "Elite",
}

# Default embedding model dimensions
DEFAULT_EMBEDDING_DIMENSIONS: int = 3072


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: AGENT NAMES & HANDOFF CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

class AgentNames:
    """Agent identifiers for handoff orchestration."""
    ERICA_CONCIERGE = "EricaConcierge"
    CARD_RECOMMENDATION = "CardRecommendation"
    INVESTMENT_ADVISOR = "InvestmentAdvisor"
    TRANSFER_AGENCY = "TransferAgencyAgent"
    FRAUD_AGENT = "FraudAgent"
    MERRILL_ADVISOR = "merrill_advisor"  # Human escalation target


# Handoff transition messages
HANDOFF_MESSAGES: Dict[str, str] = {
    "card_recommendation": "Let me find the best card options for you.",
    "investment_advisor": "Let me look at your retirement accounts and options.",
    "transfer_agency": "Let me connect you with our Transfer Agency specialist.",
    "merrill_advisor": "Connecting you with a Merrill financial advisor. Please hold.",
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: EMAIL & DELIVERY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Card delivery timeframes
CARD_DELIVERY_TIMEFRAME: str = "3-5 business days"
CARD_DELIVERY_DAYS_MIN: int = 3
CARD_DELIVERY_DAYS_MAX: int = 7

# MFA code configuration
MFA_CODE_LENGTH: int = 6
MFA_CODE_EXPIRY_HOURS: int = 24

# Email configuration
EMAIL_VERIFICATION_EXPIRY_HOURS: int = 24


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9: ROLLOVER & TAX CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Tax withholding rates for retirement account operations
TAX_WITHHOLDING_INDIRECT_ROLLOVER: float = 0.20  # 20% mandatory withholding
EARLY_WITHDRAWAL_PENALTY: float = 0.10  # 10% penalty if under 59½
ESTIMATED_TAX_BRACKET: float = 0.25  # Default 25% estimate for Roth conversions

# Rollover option identifiers
ROLLOVER_OPTIONS: Dict[str, str] = {
    "leave_in_old_plan": "Leave it in your old employer's plan",
    "roll_to_new_401k": "Roll over to new employer's 401(k)",
    "roll_to_ira": "Roll over to an IRA (Individual Retirement Account)",
    "cash_out": "Cash out (not recommended)",
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10: FEE REFUND CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Fee types that can be refunded
REFUNDABLE_FEE_TYPES: List[str] = [
    "atm_fee",
    "foreign_transaction_fee",
    "overdraft_fee",
    "late_payment_fee",
    "annual_fee",
]

# Refund processing time
REFUND_PROCESSING_DAYS: str = "2 business days"


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Institution
    "INSTITUTION_CONFIG",
    "InstitutionConfig",
    # Tiers
    "CUSTOMER_TIERS",
    "CustomerTierConfig",
    "CREDIT_LIMITS_BY_INCOME",
    # Card Products
    "CARD_PRODUCTS",
    "CardProduct",
    "get_card_product",
    "get_all_card_products",
    "card_product_to_dict",
    "CARD_KNOWLEDGE_BASE",
    # Mock Data
    "MOCK_CUSTOMER_PROFILE",
    "MOCK_ACCOUNT_SUMMARY",
    "MOCK_TRANSACTIONS",
    "MOCK_RETIREMENT_DATA",
    # AI Search
    "KNOWN_CARD_NAMES",
    "CARD_NAME_ABBREVIATIONS",
    "DEFAULT_EMBEDDING_DIMENSIONS",
    # Agents
    "AgentNames",
    "HANDOFF_MESSAGES",
    # Email/Delivery
    "CARD_DELIVERY_TIMEFRAME",
    "CARD_DELIVERY_DAYS_MIN",
    "CARD_DELIVERY_DAYS_MAX",
    "MFA_CODE_LENGTH",
    "MFA_CODE_EXPIRY_HOURS",
    "EMAIL_VERIFICATION_EXPIRY_HOURS",
    # Rollover/Tax
    "TAX_WITHHOLDING_INDIRECT_ROLLOVER",
    "EARLY_WITHDRAWAL_PENALTY",
    "ESTIMATED_TAX_BRACKET",
    "ROLLOVER_OPTIONS",
    # Fees
    "REFUNDABLE_FEE_TYPES",
    "REFUND_PROCESSING_DAYS",
]
