from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any
import secrets

import asyncio
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import NetworkTimeout, PyMongoError

from src.cosmosdb.manager import CosmosDBMongoCoreManager

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


class DemoTransaction(BaseModel):
    transaction_id: str
    merchant: str
    amount: float
    category: str
    timestamp: datetime
    risk_score: int


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


DEMOS_TTL_SECONDS = int(os.getenv("DEMO_USER_TTL_SECONDS", "3600"))
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
        "Charles Schwab",
        "Goldman Sachs",
        "Bloomberg Terminal",
        "American Express Travel",
        "Four Seasons",
        "Whole Foods",
        "Tesla Supercharger",
        "Apple Store",
        "Nordstrom",
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
    return Random(datetime.now(tz=timezone.utc).timestamp())


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
    preferred_mfa = "sms" if payload.phone_number else template["default_mfa_method"]
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
            "last_login": (anchor - timedelta(days=rng.randint(0, min(6, ttl_days)))).date().isoformat(),
            "login_frequency": rng.choice(("daily", "weekly", "3x per week")),
        },
        "spending_patterns": {
            "avg_monthly_spend": rng.randint(*template["avg_spend_range"]),
            "common_merchants": rng.sample(merchants, k=min(3, len(merchants))),
            "preferred_transaction_times": rng.sample(PREFERRED_TIMES, k=2),
            "risk_tolerance": rng.choice(("Conservative", "Moderate", "Growth")),
            "usual_spending_range": rng.choice(SPENDING_RANGES),
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


def _build_transactions(
    client_id: str,
    rng: Random,
    anchor: datetime,
    count: int = 3,
) -> list[DemoTransaction]:
    """Generate lightweight transaction history aligned with the demo dataset."""
    merchants = (
        "Microsoft Store",
        "Azure Marketplace",
        "Contoso Travel",
        "Fabrikam Office Supply",
        "Northwind Analytics",
    )
    categories = ("software", "travel", "cloud", "services", "training")
    transactions: list[DemoTransaction] = []
    for index in range(count):
        timestamp = anchor - timedelta(hours=rng.randint(1, 96), minutes=rng.randint(0, 59))
        amount = round(rng.uniform(49.0, 3250.0), 2)
        transactions.append(
            DemoTransaction(
                transaction_id=f"TXN-{client_id}-{index + 1:03d}",
                merchant=rng.choice(merchants),
                amount=float(amount),
                category=rng.choice(categories),
                timestamp=timestamp,
                risk_score=rng.choice((8, 14, 22, 35, 55, 72)),
            ),
        )
    transactions.sort(key=lambda item: item.timestamp, reverse=True)
    return transactions


def _build_interaction_plan(payload: DemoUserRequest, rng: Random) -> DemoInteractionPlan:
    """Craft a communication plan that mirrors the financial seed intelligence."""
    has_phone = payload.phone_number is not None
    primary = "sms" if has_phone else "email"
    fallback = "email" if primary == "sms" else "voip_callback"
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
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    return str(value)


def _serialize_demo_user(response: DemoUserResponse) -> dict:
    profile_payload = response.profile.model_dump(mode="json")
    base_fields = {
        key: profile_payload[key]
        for key in (
            "client_id",
            "full_name",
            "institution_name",
            "company_code",
            "company_code_last4",
            "client_type",
            "authorization_level",
            "max_transaction_limit",
            "mfa_required_threshold",
            "contact_info",
            "verification_codes",
            "mfa_settings",
            "compliance",
            "customer_intelligence",
        )
    }
    created_at = _format_iso_z(profile_payload.get("created_at") or datetime.now(tz=timezone.utc))
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
    database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
    container_name = os.getenv("COSMOS_FINANCIAL_USERS_CONTAINER", "users")

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


@router.post(
    "/temporary-user",
    response_model=DemoUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_temporary_user(
    payload: DemoUserRequest,
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
    anchor = datetime.now(tz=timezone.utc)
    expires_at = anchor + timedelta(hours=24)
    profile = _build_profile(payload, rng, anchor)
    transactions = _build_transactions(profile.client_id, rng, anchor)
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
    return response
