"""
Subrogation (Subro) Tools - B2B Claimant Carrier Hotline
=========================================================

Tools for handling inbound calls from Claimant Carriers (other insurance
companies) inquiring about subrogation demand status on claims.

B2B Context:
- Callers are representatives from OTHER insurance companies
- They represent claimants who were hit by OUR insureds
- They call to check demand status, liability, coverage, limits, etc.

Data Source:
- Tools query Cosmos DB directly to find claims by claim_number
- Falls back to _session_profile if available
- Falls back to MOCK_CLAIMS for testing if no other source is available
"""

from __future__ import annotations

import asyncio
import os
import random
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List

from apps.artagent.backend.registries.toolstore.registry import register_tool
from apps.artagent.backend.registries.toolstore.insurance.constants import (
    SUBRO_FAX_NUMBER,
    SUBRO_PHONE_NUMBER,
    KNOWN_CC_COMPANIES,
    RUSH_CRITERIA,
    MOCK_CLAIMS,
)
from utils.ml_logging import get_logger

try:  # pragma: no cover - optional dependency during tests
    from src.cosmosdb.manager import CosmosDBMongoCoreManager as _CosmosManagerImpl
    from src.cosmosdb.config import get_database_name, get_users_collection_name
except Exception:  # pragma: no cover - handled at runtime
    _CosmosManagerImpl = None
    def get_database_name() -> str:
        return os.getenv("AZURE_COSMOS_DATABASE_NAME", "audioagentdb")
    def get_users_collection_name() -> str:
        return os.getenv("AZURE_COSMOS_USERS_COLLECTION_NAME", "users")

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.cosmosdb.manager import CosmosDBMongoCoreManager

logger = get_logger("agents.tools.subro")

# Cached Cosmos manager for subro tools
_COSMOS_USERS_MANAGER: CosmosDBMongoCoreManager | None = None


def _json(data: Any) -> Dict[str, Any]:
    """Wrap response data for consistent JSON output."""
    return data if isinstance(data, dict) else {"result": data}


# ═══════════════════════════════════════════════════════════════════════════════
# COSMOS DB HELPERS: Query claims directly from database
# ═══════════════════════════════════════════════════════════════════════════════

def _get_cosmos_manager() -> CosmosDBMongoCoreManager | None:
    """Resolve the shared Cosmos DB client from FastAPI app state."""
    try:
        from apps.artagent.backend import main as backend_main
    except Exception:  # pragma: no cover
        return None

    app = getattr(backend_main, "app", None)
    state = getattr(app, "state", None) if app else None
    return getattr(state, "cosmos", None)


def _get_demo_users_manager() -> CosmosDBMongoCoreManager | None:
    """Return a Cosmos DB manager pointed at the demo users collection."""
    global _COSMOS_USERS_MANAGER
    database_name = get_database_name()
    container_name = get_users_collection_name()

    if _COSMOS_USERS_MANAGER is not None:
        return _COSMOS_USERS_MANAGER

    base_manager = _get_cosmos_manager()
    if base_manager is not None:
        # Check if base manager targets our collection
        try:
            db_name = getattr(getattr(base_manager, "database", None), "name", None)
            coll_name = getattr(getattr(base_manager, "collection", None), "name", None)
            if db_name == database_name and coll_name == container_name:
                _COSMOS_USERS_MANAGER = base_manager
                return _COSMOS_USERS_MANAGER
        except Exception:
            pass

    if _CosmosManagerImpl is None:
        logger.debug("Cosmos manager implementation unavailable for subro tools")
        return None

    try:
        _COSMOS_USERS_MANAGER = _CosmosManagerImpl(
            database_name=database_name,
            collection_name=container_name,
        )
        logger.info(
            "Subro tools connected to Cosmos demo users collection",
            extra={"database": database_name, "collection": container_name},
        )
        return _COSMOS_USERS_MANAGER
    except Exception as exc:  # pragma: no cover
        logger.warning("Unable to initialize Cosmos manager for subro tools: %s", exc)
        return None


def _lookup_claim_in_cosmos_sync(claim_number: str) -> Dict[str, Any] | None:
    """
    Synchronously query Cosmos DB for a claim by claim number.
    
    Returns the claim dict if found, None otherwise.
    """
    cosmos = _get_demo_users_manager()
    if cosmos is None:
        return None

    # Query for user with matching claim in demo_metadata.claims
    query: Dict[str, Any] = {
        "demo_metadata.claims.claim_number": {"$regex": f"^{re.escape(claim_number)}$", "$options": "i"}
    }

    logger.info("🔍 Cosmos claim lookup (subro) | claim_number=%s", claim_number)

    try:
        document = cosmos.read_document(query)
        if document:
            # Extract the matching claim from the document
            claims = document.get("demo_metadata", {}).get("claims", [])
            claim_upper = claim_number.upper()
            for claim in claims:
                if claim.get("claim_number", "").upper() == claim_upper:
                    logger.info("✓ Claim found in Cosmos (subro): %s", claim_number)
                    return claim
    except Exception as exc:  # pragma: no cover
        logger.warning("Cosmos claim lookup failed (subro): %s", exc)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Get claims from session profile or fallback to MOCK_CLAIMS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_claims_from_profile(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract claims list from session profile.
    
    Looks in:
    1. _session_profile.demo_metadata.claims
    2. _session_profile.claims
    
    Returns empty list if no claims found.
    """
    session_profile = args.get("_session_profile")
    if not session_profile:
        return []
    
    # Try demo_metadata.claims first
    demo_meta = session_profile.get("demo_metadata", {})
    claims = demo_meta.get("claims", [])
    if claims:
        return claims
    
    # Try top-level claims
    claims = session_profile.get("claims", [])
    return claims if claims else []


def _find_claim_by_number(args: Dict[str, Any], claim_number: str) -> Dict[str, Any] | None:
    """
    Find a claim by claim number.
    
    Lookup order:
    1. Cosmos DB (direct query) - primary source
    2. Session profile (_session_profile.demo_metadata.claims)
    3. MOCK_CLAIMS fallback for testing
    
    Args:
        args: Tool arguments (may contain _session_profile)
        claim_number: The claim number to look up (case-insensitive)
    
    Returns:
        Claim dict if found, None otherwise
    """
    claim_number_upper = claim_number.upper()
    
    # First, try Cosmos DB direct lookup (most reliable)
    cosmos_claim = _lookup_claim_in_cosmos_sync(claim_number_upper)
    if cosmos_claim:
        return cosmos_claim
    
    # Second, try session profile
    claims = _get_claims_from_profile(args)
    if claims:
        for claim in claims:
            if claim.get("claim_number", "").upper() == claim_number_upper:
                logger.info("📋 Found claim %s in session profile", claim_number_upper)
                return claim
    
    # Fallback to MOCK_CLAIMS for testing
    claim = MOCK_CLAIMS.get(claim_number_upper)
    if claim:
        logger.info("📋 Found claim %s in MOCK_CLAIMS (fallback)", claim_number_upper)
        return claim
    
    logger.warning("❌ Claim %s not found in any source", claim_number_upper)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_claim_summary
# ═══════════════════════════════════════════════════════════════════════════════

get_claim_summary_schema: Dict[str, Any] = {
    "name": "get_claim_summary",
    "description": (
        "Retrieve claim summary information for a verified Claimant Carrier. "
        "Returns basic claim details including parties, dates, and current status. "
        "Use after verify_cc_caller succeeds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number to look up",
            },
        },
        "required": ["claim_number"],
    },
}


async def get_claim_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get basic claim summary for CC rep."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    return _json({
        "success": True,
        "claim_number": claim_number,
        "insured_name": claim.get("insured_name", "Unknown"),
        "claimant_name": claim.get("claimant_name", "Unknown"),
        "claimant_carrier": claim.get("claimant_carrier", "Unknown"),
        "loss_date": claim.get("loss_date", "Unknown"),
        "status": claim.get("status", "unknown"),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_subro_demand_status
# ═══════════════════════════════════════════════════════════════════════════════

get_subro_demand_status_schema: Dict[str, Any] = {
    "name": "get_subro_demand_status",
    "description": (
        "Check subrogation demand status for a claim. Returns whether demand "
        "was received, when, amount, assignment status, and current handler."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number to check demand status for",
            },
        },
        "required": ["claim_number"],
    },
}


async def get_subro_demand_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get subrogation demand status."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    demand = claim.get("subro_demand", {})

    return _json({
        "success": True,
        "claim_number": claim_number,
        "demand_received": demand.get("received", False),
        "received_date": demand.get("received_date"),
        "demand_amount": demand.get("amount"),
        "assigned_to": demand.get("assigned_to"),
        "assigned_date": demand.get("assigned_date"),
        "status": demand.get("status"),
        "fax_number": SUBRO_FAX_NUMBER if not demand.get("received") else None,
        "message": _format_demand_status_message(demand),
    })


def _format_demand_status_message(demand: Dict[str, Any]) -> str:
    """Format human-readable demand status message."""
    if not demand.get("received"):
        return f"No demand received. Please fax demands to {SUBRO_FAX_NUMBER}."

    status = demand.get("status", "unknown")
    assigned = demand.get("assigned_to")

    if status == "paid":
        return "Demand has been paid."
    elif status == "denied_no_coverage":
        return "Demand denied due to no coverage."
    elif status == "under_review" and assigned:
        return f"Demand is under review by {assigned}."
    elif assigned:
        return f"Demand assigned to {assigned}. Status: {status}."
    else:
        return f"Demand received. Status: {status}."


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_coverage_status
# ═══════════════════════════════════════════════════════════════════════════════

get_coverage_status_schema: Dict[str, Any] = {
    "name": "get_coverage_status",
    "description": (
        "Check coverage status for a claim. Returns whether coverage is "
        "confirmed, pending, or denied, plus any coverage question (CVQ) status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number to check coverage for",
            },
        },
        "required": ["claim_number"],
    },
}


async def get_coverage_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get coverage status for claim."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    coverage_status = claim.get("coverage_status", "unknown")
    cvq_status = claim.get("cvq_status")

    message = f"Coverage status: {coverage_status}."
    if cvq_status:
        message += f" CVQ: {cvq_status}."

    return _json({
        "success": True,
        "claim_number": claim_number,
        "coverage_status": coverage_status,
        "cvq_status": cvq_status,
        "message": message,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_liability_decision
# ═══════════════════════════════════════════════════════════════════════════════

get_liability_decision_schema: Dict[str, Any] = {
    "name": "get_liability_decision",
    "description": (
        "Get liability decision and range for a claim. Returns liability "
        "status (pending/accepted/denied) and if accepted, the liability "
        "percentage range (always disclose lower end only)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number to check liability for",
            },
        },
        "required": ["claim_number"],
    },
}


async def get_liability_decision(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get liability decision for claim."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    decision = claim.get("liability_decision", "unknown")
    # Support both liability_percentage (from demo_env) and liability_range_low (legacy)
    percentage = claim.get("liability_percentage") or claim.get("liability_range_low")

    result = {
        "success": True,
        "claim_number": claim_number,
        "liability_decision": decision,
        "liability_percentage": percentage,
    }

    if decision == "pending":
        result["message"] = "Liability decision is still pending."
    elif decision == "accepted" and percentage is not None:
        result["message"] = f"Liability accepted at {percentage}%."
    elif decision == "denied":
        result["message"] = "Liability denied."
    elif decision == "not_applicable":
        result["message"] = "Liability not applicable (no coverage)."
    else:
        result["message"] = f"Liability status: {decision}."

    return _json(result)


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_pd_policy_limits
# ═══════════════════════════════════════════════════════════════════════════════

get_pd_policy_limits_schema: Dict[str, Any] = {
    "name": "get_pd_policy_limits",
    "description": (
        "Get property damage policy limits for a claim. IMPORTANT: Only disclose "
        "limits if liability has been accepted (liability > 0%). If liability is "
        "pending or denied, do not disclose limits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number to check PD limits for",
            },
        },
        "required": ["claim_number"],
    },
}


async def get_pd_policy_limits(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get PD limits - only if liability accepted."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    decision = claim.get("liability_decision")
    # Support both liability_percentage (from demo_env) and liability_range_low (legacy)
    percentage = claim.get("liability_percentage") or claim.get("liability_range_low")
    limits = claim.get("pd_limits", 0)

    # Only disclose limits if liability > 0
    if decision == "accepted" and percentage and percentage > 0:
        return _json({
            "success": True,
            "claim_number": claim_number,
            "can_disclose": True,
            "pd_limits": limits,
            "message": f"Property damage limits: ${limits:,}.",
        })
    else:
        return _json({
            "success": True,
            "claim_number": claim_number,
            "can_disclose": False,
            "pd_limits": None,
            "liability_status": decision,
            "message": "Cannot disclose limits until liability is accepted.",
        })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_pd_payments
# ═══════════════════════════════════════════════════════════════════════════════

get_pd_payments_schema: Dict[str, Any] = {
    "name": "get_pd_payments",
    "description": (
        "Check payments made on the property damage (PD) feature of a claim. "
        "Returns payment history including dates, amounts, and payees."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number to check PD payments for",
            },
        },
        "required": ["claim_number"],
    },
}


async def get_pd_payments(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get PD payment history."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    # Support both 'payments' (from demo_env) and 'pd_payments' (legacy)
    payments = claim.get("payments") or claim.get("pd_payments") or []
    total = sum(p.get("amount", 0) for p in payments)

    return _json({
        "success": True,
        "claim_number": claim_number,
        "payments": payments,
        "payment_count": len(payments),
        "total_paid": total,
        "message": f"{len(payments)} payment(s) totaling ${total:,.2f}." if payments else "No payments made.",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: resolve_feature_owner
# ═══════════════════════════════════════════════════════════════════════════════

resolve_feature_owner_schema: Dict[str, Any] = {
    "name": "resolve_feature_owner",
    "description": (
        "Find the owner/handler for a specific claim feature (PD, BI, SUBRO). "
        "Use when caller has questions outside subrogation scope that need "
        "to be routed to the correct handler."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number",
            },
            "feature": {
                "type": "string",
                "enum": ["PD", "BI", "SUBRO"],
                "description": "The feature type (PD=Property Damage, BI=Bodily Injury, SUBRO=Subrogation)",
            },
        },
        "required": ["claim_number", "feature"],
    },
}


async def resolve_feature_owner(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get the handler for a specific feature."""
    claim_number = (args.get("claim_number") or "").strip().upper()
    feature = (args.get("feature") or "").strip().upper()

    claim = _find_claim_by_number(args, claim_number)
    if not claim:
        return _json({"success": False, "message": f"Claim {claim_number} not found."})

    owners = claim.get("feature_owners", {})
    owner = owners.get(feature)

    if owner:
        return _json({
            "success": True,
            "claim_number": claim_number,
            "feature": feature,
            "owner": owner,
            "message": f"{feature} feature is handled by {owner}.",
        })
    else:
        return _json({
            "success": True,
            "claim_number": claim_number,
            "feature": feature,
            "owner": None,
            "message": f"No handler assigned to {feature} feature.",
        })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: evaluate_rush_criteria
# ═══════════════════════════════════════════════════════════════════════════════

evaluate_rush_criteria_schema: Dict[str, Any] = {
    "name": "evaluate_rush_criteria",
    "description": (
        "Evaluate if a subrogation demand qualifies for rush (ISRUSH) assignment. "
        "Rush criteria include: attorney represented, demand over limits, "
        "statute of limitations near, prior demands unanswered, or explicit escalation request."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number",
            },
            "attorney_represented": {
                "type": "boolean",
                "description": "Whether the claimant is represented by an attorney",
            },
            "demand_over_limits": {
                "type": "boolean",
                "description": "Whether the demand exceeds policy limits",
            },
            "statute_near": {
                "type": "boolean",
                "description": "Whether statute of limitations is within 60 days",
            },
            "prior_demands_unanswered": {
                "type": "boolean",
                "description": "Whether there are prior unanswered demands",
            },
            "escalation_request": {
                "type": "boolean",
                "description": "Whether caller is explicitly requesting escalation",
            },
        },
        "required": ["claim_number"],
    },
}


async def evaluate_rush_criteria(args: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate if demand qualifies for rush assignment."""
    claim_number = (args.get("claim_number") or "").strip().upper()

    criteria_met = []
    if args.get("attorney_represented"):
        criteria_met.append("attorney_represented")
    if args.get("demand_over_limits"):
        criteria_met.append("demand_over_limits")
    if args.get("statute_near"):
        criteria_met.append("statute_of_limitations_near")
    if args.get("prior_demands_unanswered"):
        criteria_met.append("prior_demands_unanswered")
    if args.get("escalation_request"):
        criteria_met.append("escalation_request")

    qualifies = len(criteria_met) > 0

    return _json({
        "success": True,
        "claim_number": claim_number,
        "qualifies_for_rush": qualifies,
        "criteria_met": criteria_met,
        "message": (
            f"Qualifies for ISRUSH. Criteria: {', '.join(criteria_met)}."
            if qualifies else "Does not meet rush criteria."
        ),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: create_isrush_diary
# ═══════════════════════════════════════════════════════════════════════════════

create_isrush_diary_schema: Dict[str, Any] = {
    "name": "create_isrush_diary",
    "description": (
        "Create an ISRUSH diary entry for expedited subrogation demand handling. "
        "Use after evaluate_rush_criteria confirms qualification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number",
            },
            "reason": {
                "type": "string",
                "description": "Reason for rush assignment (from rush criteria)",
            },
            "cc_company": {
                "type": "string",
                "description": "Claimant Carrier company name",
            },
            "caller_name": {
                "type": "string",
                "description": "Name of the CC representative who called",
            },
        },
        "required": ["claim_number", "reason"],
    },
}


async def create_isrush_diary(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create ISRUSH diary entry."""
    claim_number = (args.get("claim_number") or "").strip().upper()
    reason = (args.get("reason") or "").strip()
    cc_company = (args.get("cc_company") or "").strip()
    caller_name = (args.get("caller_name") or "").strip()

    if not claim_number or not reason:
        return _json({
            "success": False,
            "message": "Claim number and reason are required.",
        })

    # Generate diary ID
    diary_id = f"ISRUSH-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"

    logger.info(
        "📋 ISRUSH Diary Created | claim=%s diary=%s reason=%s",
        claim_number, diary_id, reason
    )

    return _json({
        "success": True,
        "claim_number": claim_number,
        "diary_id": diary_id,
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": f"ISRUSH diary {diary_id} created for rush handling. Reason: {reason}.",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: append_claim_note
# ═══════════════════════════════════════════════════════════════════════════════

append_claim_note_schema: Dict[str, Any] = {
    "name": "append_claim_note",
    "description": (
        "Document the Claimant Carrier call interaction in CLAIMPRO. "
        "Should be called at the end of every subrogation call to record "
        "who called, what was discussed, and any actions taken."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number",
            },
            "cc_company": {
                "type": "string",
                "description": "Claimant Carrier company name",
            },
            "caller_name": {
                "type": "string",
                "description": "Name of the CC representative",
            },
            "inquiry_type": {
                "type": "string",
                "description": "Type of inquiry (demand_status, liability, coverage, limits, rush_request, other)",
            },
            "summary": {
                "type": "string",
                "description": "Brief summary of the call and any information provided",
            },
            "actions_taken": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of actions taken during the call",
            },
        },
        "required": ["claim_number", "cc_company", "caller_name", "summary"],
    },
}


async def append_claim_note(args: Dict[str, Any]) -> Dict[str, Any]:
    """Append note to claim documenting the CC call."""
    claim_number = (args.get("claim_number") or "").strip().upper()
    cc_company = (args.get("cc_company") or "").strip()
    caller_name = (args.get("caller_name") or "").strip()
    inquiry_type = (args.get("inquiry_type") or "general").strip()
    summary = (args.get("summary") or "").strip()
    actions = args.get("actions_taken") or []

    if not claim_number or not summary:
        return _json({
            "success": False,
            "message": "Claim number and summary are required.",
        })

    # Generate note ID
    note_id = f"NOTE-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"

    note_content = (
        f"CC HOTLINE CALL\n"
        f"Caller: {caller_name} from {cc_company}\n"
        f"Inquiry Type: {inquiry_type}\n"
        f"Summary: {summary}\n"
    )
    if actions:
        note_content += f"Actions: {', '.join(actions)}\n"

    logger.info(
        "📝 Claim Note Added | claim=%s note=%s cc=%s",
        claim_number, note_id, cc_company
    )

    return _json({
        "success": True,
        "claim_number": claim_number,
        "note_id": note_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": f"Note {note_id} added to claim {claim_number}.",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA: get_subro_contact_info
# ═══════════════════════════════════════════════════════════════════════════════

get_subro_contact_info_schema: Dict[str, Any] = {
    "name": "get_subro_contact_info",
    "description": (
        "Get contact information for the subrogation department. "
        "Returns fax number for demands and phone number for inquiries."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


async def get_subro_contact_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get subro department contact info."""
    return _json({
        "success": True,
        "fax_number": SUBRO_FAX_NUMBER,
        "phone_number": SUBRO_PHONE_NUMBER,
        "message": (
            f"Subrogation demands can be faxed to {SUBRO_FAX_NUMBER}. "
            f"For inquiries, call {SUBRO_PHONE_NUMBER}."
        ),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

# NOTE: verify_cc_caller is registered in auth.py (it queries Cosmos DB directly)

# Claim Information Tools
register_tool(
    name="get_claim_summary",
    schema=get_claim_summary_schema,
    executor=get_claim_summary,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="get_subro_demand_status",
    schema=get_subro_demand_status_schema,
    executor=get_subro_demand_status,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="get_coverage_status",
    schema=get_coverage_status_schema,
    executor=get_coverage_status,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="get_liability_decision",
    schema=get_liability_decision_schema,
    executor=get_liability_decision,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="get_pd_policy_limits",
    schema=get_pd_policy_limits_schema,
    executor=get_pd_policy_limits,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="get_pd_payments",
    schema=get_pd_payments_schema,
    executor=get_pd_payments,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="resolve_feature_owner",
    schema=resolve_feature_owner_schema,
    executor=resolve_feature_owner,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="evaluate_rush_criteria",
    schema=evaluate_rush_criteria_schema,
    executor=evaluate_rush_criteria,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="create_isrush_diary",
    schema=create_isrush_diary_schema,
    executor=create_isrush_diary,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="append_claim_note",
    schema=append_claim_note_schema,
    executor=append_claim_note,
    tags={"scenario": "insurance", "category": "subro"},
)

register_tool(
    name="get_subro_contact_info",
    schema=get_subro_contact_info_schema,
    executor=get_subro_contact_info,
    tags={"scenario": "insurance", "category": "subro"},
)
