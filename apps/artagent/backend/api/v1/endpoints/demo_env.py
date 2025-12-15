from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from random import Random
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import NetworkTimeout, PyMongoError
from src.cosmosdb.manager import CosmosDBMongoCoreManager
from src.cosmosdb.config import get_database_name, get_users_collection_name
from src.stateful.state_managment import MemoManager

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/demo-env", tags=["demo-env"])


class DemoUserRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    phone_number: str | None = Field(
        default=None,
        pattern=r"^\+\d{10,15}$",
        description="Optional phone number in E.164 format for SMS demos.",
    )
    preferred_channel: Literal["email", "sms"] | None = Field(
        default=None,
        description="Preferred MFA delivery channel. Defaults to email unless explicitly set to SMS.",
    )
    session_id: str | None = Field(
        default=None,
        min_length=5,
        max_length=120,
        description="Browser session identifier used to correlate demo activity.",
    )


class DemoUserProfile(BaseModel):
    client_id: str
    full_name: str
    email: EmailStr
    phone_number: str | None
    relationship_tier: str
    created_at: datetime
    institution_name: str
    company_code: str
    company_code_last4: str
    client_type: str
    authorization_level: str
    max_transaction_limit: int
    mfa_required_threshold: int
    contact_info: dict[str, Any]
    verification_codes: dict[str, str]
    mfa_settings: dict[str, Any]
    compliance: dict[str, Any]
    customer_intelligence: dict[str, Any]


class TransactionLocation(BaseModel):
    """Location details for a transaction."""
    city: str | None = None
    state: str | None = None
    country: str
    country_code: str
    is_international: bool = False


class DemoTransaction(BaseModel):
    """Transaction model matching UI ProfileDetailsPanel expectations."""
    transaction_id: str
    merchant: str
    amount: float
    category: str
    timestamp: datetime
    risk_score: int
    # Location object for UI display
    location: TransactionLocation
    # Card used for transaction
    card_last4: str
    # Fee fields
    foreign_transaction_fee: float | None = None
    fee_reason: str | None = None
    # Original currency for international transactions
    original_amount: float | None = None
    original_currency: str | None = None
    # Optional notes
    notes: str | None = None


class DemoInteractionPlan(BaseModel):
    primary_channel: str
    fallback_channel: str
    notification_message: str
    mfa_required: bool


class DemoUserResponse(BaseModel):
    entry_id: str
    expires_at: datetime
    profile: DemoUserProfile
    transactions: list[DemoTransaction]
    interaction_plan: DemoInteractionPlan
    session_id: str | None = None
    safety_notice: str


class DemoUserLookupResponse(DemoUserResponse):
    """Alias to reuse DemoUserResponse shape for lookup endpoint."""


DEMOS_TTL_SECONDS = int(os.getenv("DEMO_USER_TTL_SECONDS", "86400"))
PROFILE_TEMPLATES = (
    {
        "key": "contoso_exec",
        "institution_name": "Contoso Financial Services",
        "company_code_prefix": "CFS",
        "authorization_level": "senior_advisor",
        "relationship_tier": "Platinum",
        "default_phone": "+18881231234",
        "default_mfa_method": "email",
        "max_txn_range": (40_000_000, 55_000_000),
        "balance_range": (350_000, 950_000),
        "volume_range": (7_500_000, 12_500_000),
        "avg_spend_range": (60_000, 130_000),
    },
    {
        "key": "global_advisors",
        "institution_name": "Global Capital Advisors",
        "company_code_prefix": "GCA",
        "authorization_level": "senior_advisor",
        "relationship_tier": "Gold",
        "default_phone": "+15551234567",
        "default_mfa_method": "sms",
        "max_txn_range": (18_000_000, 28_000_000),
        "balance_range": (220_000, 420_000),
        "volume_range": (3_800_000, 6_500_000),
        "avg_spend_range": (35_000, 75_000),
    },
)
MERCHANT_OPTIONS = {
    "contoso_exec": [
        "Microsoft Store",
        "Azure Marketplace",
        "Contoso Travel",
        "Fabrikam Office Supply",
        "Northwind Analytics",
        "LinkedIn Sales Navigator",
    ],
    "global_advisors": [
        "Woodgrove Financial",
        "Proseware Investments",
        "Margie's Travel",
        "Alpine Ski House",
        "Coho Winery",
        "Wide World Importers",
        "Adatum Corporation",
        "Trey Research",
        "Lucerne Publishing",
    ],
}
LOCATION_OPTIONS = {
    "contoso_exec": ["Seattle", "Redmond", "San Francisco", "New York"],
    "global_advisors": ["New York", "Boston", "Miami", "Chicago"],
}
CONVERSATION_PROFILES = {
    "contoso_exec": {
        "communication_style": "Direct/Business-focused",
        "personality_traits": {
            "patience_level": "Medium",
            "detail_preference": "High-level summaries",
            "urgency_style": "Immediate action",
        },
        "preferred_resolution_style": "Fast, efficient solutions",
        "known_preferences": [
            "Prefers quick summaries over detailed explanations",
            "Values immediate action on security issues",
            "Appreciates proactive service",
        ],
        "talking_points": [
            "Your security posture remains exemplary.",
            "Platinum tier benefits available on demand.",
            "We can regenerate demo identifiers whenever needed.",
        ],
        "alert_type": "positive_behavior",
    },
    "global_advisors": {
        "communication_style": "Relationship-oriented",
        "personality_traits": {
            "patience_level": "High",
            "detail_preference": "Moderate detail with examples",
            "urgency_style": "Collaborative discussion",
        },
        "preferred_resolution_style": "Thorough explanation with options",
        "known_preferences": [
            "Enjoys step-by-step walk-throughs.",
            "Wants rationale behind each security control.",
            "Responds well to relationship-focused language.",
        ],
        "talking_points": [
            "Your vigilance keeps operations running smoothly.",
            "Gold tier support remains prioritized for you.",
            "Recent fraud review closed successfully with no loss.",
        ],
        "alert_type": "account_optimization",
    },
}
SECURITY_PROFILES = {
    "contoso_exec": {
        "preferred_verification": "Email",
        "notification_urgency": ("Immediate", "Standard"),
        "card_replacement_speed": ("Expedited", "Standard"),
    },
    "global_advisors": {
        "preferred_verification": "Email",
        "notification_urgency": ("Standard", "Immediate"),
        "card_replacement_speed": ("Standard", "Expedited"),
    },
}
PREFERRED_TIMES = (
    "8-10 AM",
    "10-12 PM",
    "1-3 PM",
    "3-5 PM",
)
SPENDING_RANGES = ("$500 - $8,000", "$1,000 - $15,000", "$1,000 - $25,000")


def _rng_dependency() -> Random:
    """Provide a per-request random generator without storing global state."""
    return Random(datetime.now(tz=UTC).timestamp())


def _slugify_name(full_name: str) -> str:
    """Normalize a human name for client identifiers."""
    return "_".join(full_name.lower().strip().split())


def _build_profile(
    payload: DemoUserRequest,
    rng: Random,
    anchor: datetime,
) -> DemoUserProfile:
    template = rng.choice(PROFILE_TEMPLATES)
    slug = _slugify_name(payload.full_name)
    company_suffix = rng.randint(10_000, 99_999)
    client_id = f"{slug}_{template['company_code_prefix'].lower()}"
    company_code = f"{template['company_code_prefix']}-{company_suffix}"
    contact_phone = payload.phone_number or template["default_phone"]
    explicit_channel = (payload.preferred_channel or "").lower()
    prefers_sms = explicit_channel == "sms" and bool(payload.phone_number)
    preferred_mfa = "sms" if prefers_sms else "email"
    phone_last4 = contact_phone[-4:] if contact_phone else f"{rng.randint(0, 9999):04d}"
    contact_info = {
        "email": str(payload.email),
        "phone": contact_phone,
        "preferred_mfa_method": preferred_mfa,
    }
    verification_codes = {
        "ssn4": f"{rng.randint(0, 9999):04d}",
        "employee_id4": f"{rng.randint(0, 9999):04d}",
        "phone4": phone_last4,
    }
    mfa_settings = {
        "enabled": True,
        "secret_key": secrets.token_urlsafe(24),
        "code_expiry_minutes": 5,
        "max_attempts": 3,
    }
    compliance = {
        "kyc_verified": True,
        "aml_cleared": True,
        "last_review_date": (anchor - timedelta(days=rng.randint(30, 140))).date().isoformat(),
        "risk_rating": "low",
    }

    tenure_days = rng.randint(365 * 2, 365 * 8)
    client_since_date = (anchor - timedelta(days=tenure_days)).date()
    relationship_duration = round(tenure_days / 365, 1)
    merchants = MERCHANT_OPTIONS[template["key"]]
    locations = LOCATION_OPTIONS[template["key"]]
    conversation = CONVERSATION_PROFILES[template["key"]]
    security = SECURITY_PROFILES[template["key"]]

    # Calculate TTL-dependent values
    ttl_hours = DEMOS_TTL_SECONDS // 3600
    ttl_days = max(1, ttl_hours // 24)

    # Generate banking-specific data for banking tools
    account_tenure_years = round(relationship_duration)
    has_existing_card = rng.choice([True, True, False])  # 66% have existing card
    has_401k = rng.choice([True, True, True, False])  # 75% have 401k
    income_bracket = rng.choice(["medium", "medium_high", "high", "very_high"])
    
    # Generate account numbers (last 4 digits only for display)
    checking_last4 = f"{rng.randint(1000, 9999)}"
    savings_last4 = f"{rng.randint(1000, 9999)}"
    
    # Generate existing credit card if applicable
    existing_cards = []
    if has_existing_card:
        card_types = [
            {"name": "Cash Rewards", "product_id": "cash-rewards-002"},
            {"name": "Travel Rewards", "product_id": "travel-rewards-001"},
        ]
        card = rng.choice(card_types)
        card_last4 = f"{rng.randint(1000, 9999)}"
        card_opened = (anchor - timedelta(days=rng.randint(180, 1800))).date().isoformat()
        existing_cards.append({
            # UI field names
            "productName": card["name"],
            "last4": card_last4,
            "openedDate": card_opened,
            "rewardsType": "cash_back" if "Cash" in card["name"] else "points",
            "hasAnnualFee": False,
            "foreignTxFeePct": 0 if "Travel" in card["name"] else 3,
            # Tool field names (for banking tools)
            "product_name": card["name"],
            "product_id": card["product_id"],
            "last_four": card_last4,
            "credit_limit": rng.choice([5000, 7500, 10000, 15000]),
            "current_balance": round(rng.uniform(200, 2500), 2),
        })

    # Generate 401k/retirement data
    former_employer_401k_balance = rng.randint(25000, 150000) if has_401k else 0
    current_ira_balance = rng.randint(5000, 50000) if rng.choice([True, False]) else 0

    customer_intelligence = {
        "relationship_context": {
            "relationship_tier": template["relationship_tier"],
            "client_since": client_since_date.isoformat(),
            "relationship_duration_years": relationship_duration,
            "lifetime_value": rng.randint(450_000, 2_600_000),
            "satisfaction_score": rng.randint(88, 99),
            "previous_interactions": rng.randint(18, 64),
        },
        "account_status": {
            "current_balance": rng.randint(*template["balance_range"]),
            "ytd_transaction_volume": rng.randint(*template["volume_range"]),
            "account_health_score": rng.randint(88, 99),
            "last_login": (anchor - timedelta(days=rng.randint(0, min(6, ttl_days))))
            .date()
            .isoformat(),
            "login_frequency": rng.choice(("daily", "weekly", "3x per week")),
        },
        "spending_patterns": {
            "avg_monthly_spend": rng.randint(*template["avg_spend_range"]),
            "common_merchants": rng.sample(merchants, k=min(3, len(merchants))),
            "preferred_transaction_times": rng.sample(PREFERRED_TIMES, k=2),
            "risk_tolerance": rng.choice(("Conservative", "Moderate", "Growth")),
            "usual_spending_range": rng.choice(SPENDING_RANGES),
        },
        # Banking-specific profile data for banking tools
        "bank_profile": {
            "accountTenureYears": account_tenure_years,
            "cards": existing_cards,
            "uses_contoso_401k": has_401k,
            "has_direct_deposit": rng.choice([True, True, False]),
            "preferred_branch": rng.choice(["Online", "Downtown", "Westside", "Mobile App"]),
            # Account details for UI display
            "account_number_last4": checking_last4,
            "routing_number": "021000021",  # Contoso Bank routing
            "current_balance": round(rng.uniform(1500, 25000), 2),
        },
        "employment": {
            "income_bracket": income_bracket,
            "incomeBand": income_bracket,  # UI field name
            "employment_status": "employed",
            "employer_name": template.get("institution_name", "Contoso Corp"),
            "currentEmployerName": template.get("institution_name", "Contoso Corp"),  # UI field
            "currentEmployerStartDate": (anchor - timedelta(days=rng.randint(180, 730))).date().isoformat(),
            "previousEmployerName": "Previous Employer Inc." if has_401k else None,
            "previousEmployerEndDate": (anchor - timedelta(days=rng.randint(30, 180))).date().isoformat() if has_401k else None,
            "usesContosoFor401k": has_401k,  # Used by get_401k_details tool
        },
        "payroll_setup": {
            "hasDirectDeposit": rng.choice([True, True, False]),
            "pendingSetup": False,
            "lastPaycheckDate": (anchor - timedelta(days=rng.randint(1, 14))).date().isoformat(),
            "payFrequency": rng.choice(["biweekly", "monthly", "weekly"]),
        },
        "accounts": {
            "checking": {
                "account_number_last4": checking_last4,
                "balance": round(rng.uniform(1500, 25000), 2),
                "available": round(rng.uniform(1500, 25000), 2),
                "account_type": "checking",
            },
            "savings": {
                "account_number_last4": savings_last4,
                "balance": round(rng.uniform(5000, 75000), 2),
                "available": round(rng.uniform(5000, 75000), 2),
                "account_type": "savings",
            },
        },
        # Retirement profile - matches UI (ProfileDetailsPanel) and tools (investments.py) expectations
        "retirement_profile": {
            # Retirement accounts array - displayed in UI and used by get_401k_details
            "retirement_accounts": [
                {
                    "accountId": f"401k-{rng.randint(100000, 999999)}",
                    "type": "401k",  # UI expects 'type' not 'accountType'
                    "accountType": "401(k)",  # Keep for tools
                    "provider": rng.choice(["Fidelity", "Vanguard", "Charles Schwab", "T. Rowe Price"]),
                    "balance": former_employer_401k_balance,
                    "estimatedBalance": former_employer_401k_balance,  # UI field
                    "balanceBand": "$50k-$100k" if former_employer_401k_balance < 100000 else "$100k-$200k",
                    "employerName": "Previous Employer Inc.",
                    "isFormerEmployer": True,
                    "status": "active",  # UI expects status
                    "vestingPercentage": 100,
                    "vestingStatus": "100% Vested",  # UI expects vestingStatus string
                },
            ] if has_401k else [],
            # Merrill Lynch accounts (for Contoso Banking customers)
            "merrill_accounts": [
                {
                    "accountId": f"ML-{rng.randint(100000, 999999)}",
                    "brand": "Merrill Lynch",  # UI expects brand
                    "accountType": rng.choice(["ira", "roth_ira"]),
                    "balance": current_ira_balance,
                    "estimatedBalance": current_ira_balance,  # UI field
                },
            ] if current_ira_balance > 0 else [],
            # Plan features - used by UI and tools
            "plan_features": {
                "has401kPayOnCurrentPlan": has_401k,
                "currentEmployerMatchPct": rng.choice([3, 4, 5, 6]) if has_401k else 0,
                "rolloverEligible": has_401k,
                "vestingSchedule": "immediate" if has_401k else None,
            },
            # Additional profile fields used by UI and tools
            "risk_profile": rng.choice(["conservative", "moderate", "growth", "aggressive"]),
            "investmentKnowledgeLevel": rng.choice(["beginner", "intermediate", "advanced"]),
            "retirement_readiness_score": round(rng.uniform(5.0, 9.5), 1),
        },
        "memory_score": {
            "communication_style": conversation["communication_style"],
            "personality_traits": conversation["personality_traits"],
            "preferred_resolution_style": conversation["preferred_resolution_style"],
        },
        "fraud_context": {
            "risk_profile": "Low Risk",
            "typical_transaction_behavior": {
                "usual_spending_range": rng.choice(SPENDING_RANGES),
                "common_locations": rng.sample(locations, k=min(3, len(locations))),
                "typical_merchants": rng.sample(merchants, k=min(3, len(merchants))),
            },
            "security_preferences": {
                "preferred_verification": security["preferred_verification"],
                "notification_urgency": rng.choice(security["notification_urgency"]),
                "card_replacement_speed": rng.choice(security["card_replacement_speed"]),
            },
            "fraud_history": {
                "previous_cases": rng.choice((0, 1)),
                "false_positive_rate": rng.randint(5, 15),
                "security_awareness_score": rng.randint(86, 97),
            },
        },
        "conversation_context": {
            "known_preferences": conversation["known_preferences"],
            "suggested_talking_points": conversation["talking_points"],
        },
        # Preferences for prompt templates (used by banking_concierge prompt.jinja)
        "preferences": {
            "preferredContactMethod": rng.choice(["phone", "email", "sms", "app"]),
            "communicationStyle": conversation["communication_style"],
            "languagePreference": "en-US",
        },
        "active_alerts": [
            {
                "type": conversation["alert_type"],
                "message": f"Demo identity issued. Data purges automatically within {ttl_hours} hours.",
                "priority": rng.choice(("info", "medium")),
            }
        ],
    }

    max_txn_limit = rng.randint(*template["max_txn_range"])
    mfa_threshold = rng.randint(3_000, 15_000)

    return DemoUserProfile(
        client_id=client_id,
        full_name=payload.full_name.strip(),
        email=payload.email,
        phone_number=contact_phone,
        relationship_tier=template["relationship_tier"],
        created_at=anchor,
        institution_name=template["institution_name"],
        company_code=company_code,
        company_code_last4=str(company_suffix)[-4:],
        client_type="institutional",
        authorization_level=template["authorization_level"],
        max_transaction_limit=max_txn_limit,
        mfa_required_threshold=mfa_threshold,
        contact_info=contact_info,
        verification_codes=verification_codes,
        mfa_settings=mfa_settings,
        compliance=compliance,
        customer_intelligence=customer_intelligence,
    )


# International merchants with country, city, code, merchant, category
# Format: (country, country_code, city, merchant, category, currency)
INTERNATIONAL_MERCHANTS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("United Kingdom", "GB", "London", "Harrods London", "shopping", "GBP"),
    ("Germany", "DE", "Berlin", "Berliner Technik GmbH", "electronics", "EUR"),
    ("Japan", "JP", "Tokyo", "Tokyo Electronics Co.", "electronics", "JPY"),
    ("France", "FR", "Paris", "Parisian Boutique", "shopping", "EUR"),
    ("Mexico", "MX", "Cancun", "Cancun Resort & Spa", "travel", "MXN"),
    ("Canada", "CA", "Vancouver", "Vancouver Tech Hub", "software", "CAD"),
    ("Australia", "AU", "Sydney", "Sydney Trading Co.", "services", "AUD"),
    ("Italy", "IT", "Milan", "Milano Fashion House", "shopping", "EUR"),
    ("Spain", "ES", "Barcelona", "Barcelona Digital Services", "services", "EUR"),
    ("Brazil", "BR", "São Paulo", "São Paulo Tech Solutions", "software", "BRL"),
)

# Domestic cities for transaction locations
DOMESTIC_LOCATIONS: tuple[tuple[str, str], ...] = (
    ("Seattle", "WA"),
    ("San Francisco", "CA"),
    ("New York", "NY"),
    ("Austin", "TX"),
    ("Chicago", "IL"),
    ("Boston", "MA"),
    ("Denver", "CO"),
    ("Miami", "FL"),
)

# Foreign transaction fee percentage (3%)
FOREIGN_TRANSACTION_FEE_RATE = 0.03

# Currency exchange rates (approximate, for demo purposes)
EXCHANGE_RATES: dict[str, float] = {
    "GBP": 0.79,  # 1 USD = 0.79 GBP
    "EUR": 0.92,  # 1 USD = 0.92 EUR
    "JPY": 149.5,  # 1 USD = 149.5 JPY
    "MXN": 17.2,  # 1 USD = 17.2 MXN
    "CAD": 1.36,  # 1 USD = 1.36 CAD
    "AUD": 1.53,  # 1 USD = 1.53 AUD
    "BRL": 4.97,  # 1 USD = 4.97 BRL
}


def _build_transactions(
    client_id: str,
    rng: Random,
    anchor: datetime,
    count: int = 5,
    card_last4: str = "4242",
) -> list[DemoTransaction]:
    """Generate transaction history with 2 international + domestic transactions.
    
    Args:
        client_id: User identifier for transaction IDs
        rng: Random generator for consistent demo data
        anchor: Base timestamp for transaction dates
        count: Total number of transactions (min 2 international + rest domestic)
        card_last4: Last 4 digits of card used for transactions
    
    Returns:
        List of DemoTransaction objects sorted by timestamp (newest first)
    """
    domestic_merchants = (
        "Microsoft Store",
        "Azure Marketplace",
        "Contoso Travel",
        "Fabrikam Office Supply",
        "Northwind Analytics",
        "Starbucks",
        "Amazon",
        "Whole Foods",
    )
    domestic_categories = ("software", "travel", "cloud", "services", "training", "dining", "shopping", "groceries")
    transactions: list[DemoTransaction] = []

    # Always generate 2 international transactions with fees
    intl_choices = rng.sample(INTERNATIONAL_MERCHANTS, k=2)
    for idx, (country, country_code, city, merchant, category, currency) in enumerate(intl_choices):
        timestamp = anchor - timedelta(hours=rng.randint(1, 48), minutes=rng.randint(0, 59))
        amount_usd = round(rng.uniform(150.0, 2500.0), 2)
        fee = round(amount_usd * FOREIGN_TRANSACTION_FEE_RATE, 2)
        
        # Calculate original amount in foreign currency
        exchange_rate = EXCHANGE_RATES.get(currency, 1.0)
        original_amount = round(amount_usd * exchange_rate, 2)
        
        transactions.append(
            DemoTransaction(
                transaction_id=f"TXN-{client_id}-INT-{idx + 1:03d}",
                merchant=merchant,
                amount=float(amount_usd),
                category=category,
                timestamp=timestamp,
                risk_score=rng.choice((35, 55, 72, 85)),  # Higher risk for international
                location=TransactionLocation(
                    city=city,
                    state=None,
                    country=country,
                    country_code=country_code,
                    is_international=True,
                ),
                card_last4=card_last4,
                foreign_transaction_fee=fee,
                fee_reason="Foreign Transaction Fee (3%)",
                original_amount=original_amount,
                original_currency=currency,
                notes=f"International purchase in {city}, {country}",
            ),
        )

    # Generate remaining domestic transactions
    domestic_count = max(0, count - 2)
    for index in range(domestic_count):
        timestamp = anchor - timedelta(hours=rng.randint(1, 96), minutes=rng.randint(0, 59))
        amount = round(rng.uniform(5.0, 500.0), 2)
        city, state = rng.choice(DOMESTIC_LOCATIONS)
        
        transactions.append(
            DemoTransaction(
                transaction_id=f"TXN-{client_id}-{index + 1:03d}",
                merchant=rng.choice(domestic_merchants),
                amount=float(amount),
                category=rng.choice(domestic_categories),
                timestamp=timestamp,
                risk_score=rng.choice((8, 14, 22, 35)),
                location=TransactionLocation(
                    city=city,
                    state=state,
                    country="United States",
                    country_code="US",
                    is_international=False,
                ),
                card_last4=card_last4,
                foreign_transaction_fee=None,
                fee_reason=None,
                original_amount=None,
                original_currency=None,
                notes=None,
            ),
        )

    transactions.sort(key=lambda item: item.timestamp, reverse=True)
    return transactions


def _build_interaction_plan(payload: DemoUserRequest, rng: Random) -> DemoInteractionPlan:
    """Craft a communication plan that mirrors the financial seed intelligence."""
    explicit_channel = (payload.preferred_channel or "").lower()
    has_phone = payload.phone_number is not None
    primary = "sms" if explicit_channel == "sms" and has_phone else "email"
    fallback = "sms" if primary == "email" and has_phone else "voip_callback"
    tone = rng.choice(("concise summary", "step-by-step guidance", "proactive alert"))
    notification = (
        f"Demo profile ready for {payload.full_name}. Expect a {tone} via {primary.upper()}."
    )
    return DemoInteractionPlan(
        primary_channel=primary,
        fallback_channel=fallback,
        notification_message=notification,
        mfa_required=rng.choice((True, False)),
    )


logger = logging.getLogger(__name__)


def _format_iso_z(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    return str(value)


def _parse_iso8601(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def _serialize_demo_user(response: DemoUserResponse) -> dict:
    profile_payload = response.profile.model_dump(mode="json")
    base_fields = {
        key: profile_payload[key]
        for key in (
            "client_id",
            "full_name",
            "email",
            "phone_number",
            "institution_name",
            "company_code",
            "company_code_last4",
            "client_type",
            "authorization_level",
            "relationship_tier",
            "max_transaction_limit",
            "mfa_required_threshold",
            "contact_info",
            "verification_codes",
            "mfa_settings",
            "compliance",
            "customer_intelligence",
        )
    }
    created_at = _format_iso_z(profile_payload.get("created_at") or datetime.now(tz=UTC))
    document = {
        "_id": base_fields["client_id"],
        **base_fields,
        "created_at": created_at,
        "updated_at": created_at,
        "last_login": None,
        "login_attempts": 0,
        "demo_metadata": {
            "entry_id": response.entry_id,
            "expires_at": response.expires_at.isoformat(),
            "session_id": response.session_id,
            "safety_notice": response.safety_notice,
            "interaction_plan": response.interaction_plan.model_dump(mode="json"),
            "transactions": [txn.model_dump(mode="json") for txn in response.transactions],
        },
    }
    return document


async def _persist_demo_user(response: DemoUserResponse) -> None:
    document = _serialize_demo_user(response)
    database_name = get_database_name()
    container_name = get_users_collection_name()

    def _upsert() -> None:
        manager = CosmosDBMongoCoreManager(
            database_name=database_name,
            collection_name=container_name,
        )
        try:
            manager.ensure_ttl_index(field_name="ttl", expire_seconds=0)
            manager.upsert_document_with_ttl(
                document=document,
                query={"_id": document["_id"]},
                ttl_seconds=DEMOS_TTL_SECONDS,
            )
        finally:
            manager.close_connection()

    try:
        await asyncio.to_thread(_upsert)
    except (NetworkTimeout, PyMongoError) as exc:
        logger.exception("Failed to persist demo profile %s", document["_id"], exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to persist demo profile.",
        ) from exc


async def _append_phrase_bias_entries(profile: DemoUserProfile, request: Request) -> None:
    """Add demo user's key identifiers to the shared phrase list manager if configured."""

    manager = getattr(request.app.state, "speech_phrase_manager", None)
    if not manager:
        return

    try:
        added = await manager.add_phrases([profile.full_name, profile.institution_name])
        if added:
            total = len(await manager.snapshot())
            logger.info(
                "Phrase list updated from demo profile",
                extra={
                    "profile": profile.full_name,
                    "institution": profile.institution_name,
                    "new_entries": added,
                    "total_entries": total,
                },
            )
    except Exception:  # pragma: no cover - defensive logging only
        logger.debug("Could not append phrase bias entry", exc_info=True)


async def _persist_profile_to_session(
    request: Request,
    profile: DemoUserProfile,
    session_id: str | None,
) -> None:
    """
    Persist demo profile to Redis MemoManager for media handler discovery.

    This enables the media_handler to access the demo profile data (caller_name,
    customer_intelligence, institution_name, etc.) when the voice session starts.

    Args:
        request: FastAPI request with app.state.redis
        profile: The demo user profile to persist
        session_id: Browser session ID to use as the Redis key
    """
    if not session_id:
        logger.debug("No session_id provided, skipping session profile persistence")
        return

    redis_mgr = getattr(request.app.state, "redis", None)
    if not redis_mgr:
        logger.warning("Redis manager not available, skipping session profile persistence")
        return

    try:
        # Load or create MemoManager for this session
        mm = MemoManager.from_redis(session_id, redis_mgr)
        if mm is None:
            mm = MemoManager(session_id=session_id)

        # Build full session profile dict for comprehensive context
        profile_dict = profile.model_dump(mode="json")

        # Set core memory values that media_handler._derive_default_greeting expects
        mm.set_corememory("session_profile", profile_dict)
        mm.set_corememory("caller_name", profile.full_name)
        mm.set_corememory("client_id", profile.client_id)
        mm.set_corememory("institution_name", profile.institution_name)
        mm.set_corememory("customer_intelligence", profile.customer_intelligence)
        mm.set_corememory("relationship_tier", profile.relationship_tier)
        mm.set_corememory("user_email", str(profile.email))

        # Persist to Redis with TTL matching demo expiration
        await mm.persist_to_redis_async(redis_mgr, ttl_seconds=DEMOS_TTL_SECONDS)

        logger.info(
            "Persisted demo profile to session",
            extra={
                "session_id": session_id,
                "client_id": profile.client_id,
                "caller_name": profile.full_name,
            },
        )
    except Exception as exc:
        # Don't fail the request if session persistence fails
        logger.warning(
            "Failed to persist demo profile to session: %s",
            exc,
            extra={"session_id": session_id, "client_id": profile.client_id},
        )


@router.post(
    "/temporary-user",
    response_model=DemoUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_temporary_user(
    payload: DemoUserRequest,
    request: Request,
    rng: Random = Depends(_rng_dependency),
) -> DemoUserResponse:
    """Create a synthetic 24-hour demo user record.

    Args:
        payload: User-supplied identity details for the temporary profile.
        rng: Request-scoped random number generator.

    Returns:
        DemoUserResponse: Generated profile plus sample telemetry valid for hour set by DEMOS_TTL_SECONDS.

    Latency:
        Pure CPU work; expected response within ~25 ms under typical load.
    """
    anchor = datetime.now(tz=UTC)
    expires_at = anchor + timedelta(hours=24)
    profile = _build_profile(payload, rng, anchor)
    
    # Extract card last4 from profile for transaction generation
    bank_profile = profile.customer_intelligence.get("bank_profile", {})
    cards = bank_profile.get("cards", [])
    card_last4 = cards[0].get("last4", "4242") if cards else f"{rng.randint(1000, 9999)}"
    
    transactions = _build_transactions(profile.client_id, rng, anchor, card_last4=card_last4)
    interaction_plan = _build_interaction_plan(payload, rng)
    response = DemoUserResponse(
        entry_id=f"demo-entry-{rng.randint(100000, 999999)}",
        expires_at=expires_at,
        profile=profile,
        transactions=transactions,
        interaction_plan=interaction_plan,
        session_id=payload.session_id,
        safety_notice="Demo data only. Never enter real customer or personal information in this sandbox.",
    )
    await _persist_demo_user(response)
    await _append_phrase_bias_entries(profile, request)
    # Persist profile to Redis session so media_handler can discover it
    await _persist_profile_to_session(request, profile, payload.session_id)
    return response


@router.get(
    "/temporary-user",
    response_model=DemoUserLookupResponse,
    status_code=status.HTTP_200_OK,
)
async def lookup_demo_user(
    request: Request,
    email: EmailStr,
    session_id: str | None = None,
) -> DemoUserLookupResponse:
    """Retrieve the latest synthetic demo profile by email if it exists."""

    database_name = get_database_name()
    container_name = get_users_collection_name()

    def _query() -> dict | None:
        manager = CosmosDBMongoCoreManager(
            database_name=database_name,
            collection_name=container_name,
        )
        try:
            # Retrieve profile by email (no sort needed for banking profiles)
            return manager.collection.find_one({"contact_info.email": str(email)})
        finally:
            manager.close_connection()

    try:
        document = await asyncio.to_thread(_query)
    except (NetworkTimeout, PyMongoError) as exc:
        logger.exception("Failed to lookup demo profile for email=%s", email, exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to lookup demo profile.",
        ) from exc

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No demo profile found for that email.",
        )

    demo_metadata = document.get("demo_metadata") or {}
    profile_payload = document.copy()
    # Remove internal fields that aren't part of DemoUserProfile
    for key in ("demo_metadata", "_id", "ttl", "expires_at", "transactions"):
        profile_payload.pop(key, None)

    contact_info = profile_payload.get("contact_info") or {}
    profile_payload["email"] = (
        profile_payload.get("email") or contact_info.get("email") or "demo@example.com"
    )
    profile_payload["phone_number"] = profile_payload.get("phone_number") or contact_info.get(
        "phone"
    )
    relationship_context = profile_payload.get("customer_intelligence", {}).get(
        "relationship_context", {}
    )
    profile_payload["relationship_tier"] = (
        profile_payload.get("relationship_tier")
        or relationship_context.get("relationship_tier")
        or "Gold"
    )

    profile_model = DemoUserProfile.model_validate(profile_payload)

    # Support both demo_metadata.transactions and document.transactions (for banking profiles)
    transactions_payload = demo_metadata.get("transactions") or document.get("transactions") or []

    # Create default interaction_plan if not present (for banking profiles)
    interaction_payload = demo_metadata.get("interaction_plan") or {
        "primary_channel": "voice",
        "fallback_channel": "sms",
        "mfa_required": False,
        "notification_message": "Banking profile loaded successfully",
    }

    # Determine effective session_id
    effective_session_id = session_id or demo_metadata.get("session_id")

    response = DemoUserLookupResponse(
        entry_id=demo_metadata.get("entry_id")
        or document.get("_id")
        or document.get("client_id")
        or "",
        expires_at=_parse_iso8601(demo_metadata.get("expires_at") or document.get("expires_at")),
        profile=profile_model,
        transactions=[DemoTransaction.model_validate(txn) for txn in transactions_payload],
        interaction_plan=DemoInteractionPlan.model_validate(interaction_payload),
        session_id=effective_session_id,
        safety_notice=demo_metadata.get(
            "safety_notice",
            "Demo data only. Never enter real customer or personal information in this sandbox.",
        ),
    )

    # Persist profile to Redis session so media_handler can discover it
    await _persist_profile_to_session(request, profile_model, effective_session_id)

    return response
