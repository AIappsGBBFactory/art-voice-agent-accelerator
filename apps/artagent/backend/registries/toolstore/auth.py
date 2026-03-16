"""
Authentication & MFA Tools
==========================

Tools for identity verification, MFA, and authentication.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import string
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics, trace
from opentelemetry.trace import StatusCode

from apps.artagent.backend.registries.toolstore.registry import register_tool
from apps.artagent.backend.voice.shared.context import VoiceSessionContext
from config import ENABLE_VOICEPRINT
from src.enums.monitoring import SpanAttr
from src.speech.speaker_recognition import SpeakerRecognitionService
from utils.ml_logging import get_logger

try:  # pragma: no cover - optional dependency during tests
    from src.cosmosdb.manager import CosmosDBMongoCoreManager as _CosmosManagerImpl
    from src.cosmosdb.config import get_database_name, get_users_collection_name
except Exception:  # pragma: no cover - handled at runtime
    _CosmosManagerImpl = None
    # Fallback if config import fails
    def get_database_name() -> str:
        return os.getenv("AZURE_COSMOS_DATABASE_NAME", "audioagentdb")
    def get_users_collection_name() -> str:
        return os.getenv("AZURE_COSMOS_USERS_COLLECTION_NAME", "users")

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.cosmosdb.manager import CosmosDBMongoCoreManager

logger = get_logger("agents.tools.auth")

# ── Voiceprint OTel instrumentation ──────────────────────────────────────────
_tracer = trace.get_tracer("artagent.voiceprint")
_meter = metrics.get_meter("artagent.voiceprint")

_voiceprint_enroll_counter = _meter.create_counter(
    "voiceprint.enroll.attempts",
    description="Number of voiceprint enrollment attempts",
)
_voiceprint_enroll_success = _meter.create_counter(
    "voiceprint.enroll.success",
    description="Number of successful voiceprint enrollments",
)
_voiceprint_enroll_errors = _meter.create_counter(
    "voiceprint.enroll.errors",
    description="Number of voiceprint enrollment errors",
)
_voiceprint_verify_counter = _meter.create_counter(
    "voiceprint.verify.attempts",
    description="Number of voiceprint verification attempts",
)
_voiceprint_verify_match = _meter.create_counter(
    "voiceprint.verify.match",
    description="Number of successful voiceprint verification matches",
)
_voiceprint_verify_mismatch = _meter.create_counter(
    "voiceprint.verify.mismatch",
    description="Number of voiceprint verification mismatches",
)
_voiceprint_verify_errors = _meter.create_counter(
    "voiceprint.verify.errors",
    description="Number of voiceprint verification errors",
)
_voiceprint_duration = _meter.create_histogram(
    "voiceprint.operation.duration_ms",
    description="Duration of voiceprint operations in milliseconds",
    unit="ms",
)


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

verify_client_identity_schema: dict[str, Any] = {
    "name": "verify_client_identity",
    "description": (
        "Verify caller's identity using name and last 4 digits of SSN. "
        "Returns client_id if verified, otherwise returns authentication failure."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string", "description": "Caller's full legal name"},
            "ssn_last_4": {"type": "string", "description": "Last 4 digits of SSN"},
        },
        "required": ["full_name", "ssn_last_4"],
    },
}

enroll_voiceprint_schema: dict[str, Any] = {
    "name": "enroll_voiceprint",
    "description": (
        "Enroll the current caller's voice as a biometric voiceprint. "
        "Requires the caller to be already identified via name and SSN. "
        "The system will use recent audio from the call for enrollment."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string", "description": "Caller's full legal name"},
            "ssn_last_4": {"type": "string", "description": "Last 4 digits of SSN"},
        },
        "required": ["full_name", "ssn_last_4"],
    },
}

verify_voiceprint_schema: dict[str, Any] = {
    "name": "verify_voiceprint",
    "description": (
        "Verify the caller's identity using their biometric voiceprint. "
        "This is an alternative to SSN verification for enrolled users. "
        "Requires the caller's name to look up their stored voiceprint profile."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string", "description": "Caller's full legal name"},
        },
        "required": ["full_name"],
    },
}

send_mfa_code_schema: dict[str, Any] = {
    "name": "send_mfa_code",
    "description": (
        "Send MFA verification code to customer's registered phone. "
        "Returns confirmation that code was sent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "method": {
                "type": "string",
                "enum": ["sms", "voice", "email"],
                "description": "Delivery method for code",
            },
        },
        "required": ["client_id"],
    },
}

verify_mfa_code_schema: dict[str, Any] = {
    "name": "verify_mfa_code",
    "description": (
        "Verify the MFA code provided by customer. "
        "Returns success if code matches, failure otherwise."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "code": {"type": "string", "description": "6-digit verification code"},
        },
        "required": ["client_id", "code"],
    },
}

resend_mfa_code_schema: dict[str, Any] = {
    "name": "resend_mfa_code",
    "description": "Resend MFA code to customer if they didn't receive it.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "Customer identifier"},
            "method": {
                "type": "string",
                "enum": ["sms", "voice", "email"],
                "description": "Delivery method",
            },
        },
        "required": ["client_id"],
    },
}

verify_cc_caller_schema: dict[str, Any] = {
    "name": "verify_cc_caller",
    "description": (
        "Verify a Claimant Carrier (CC) representative's access to claim information. "
        "Use this for B2B subrogation calls to authenticate the caller represents "
        "the claimant carrier on record for the specified claim. "
        "Required: claim_number, company_name, caller_name. "
        "Returns retry_allowed=true on failure - retry up to 3 times before escalating."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claim_number": {
                "type": "string",
                "description": "The claim number the CC rep is calling about (e.g., CLM-2024-001234)",
            },
            "company_name": {
                "type": "string",
                "description": "The insurance company the caller represents (e.g., Contoso Insurance)",
            },
            "caller_name": {
                "type": "string",
                "description": "The name of the caller (CC representative)",
            },
        },
        "required": ["claim_number", "company_name", "caller_name"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK DATA (for demo purposes)
# ═══════════════════════════════════════════════════════════════════════════════

_MOCK_USERS = {
    ("john smith", "1234"): {
        "client_id": "CLT-001-JS",
        "full_name": "John Smith",
        "phone_last_4": "5678",
        "email": "john.smith@email.com",
    },
    ("jane doe", "5678"): {
        "client_id": "CLT-002-JD",
        "full_name": "Jane Doe",
        "phone_last_4": "9012",
        "email": "jane.doe@email.com",
    },
    ("michael chen", "9999"): {
        "client_id": "CLT-003-MC",
        "full_name": "Michael Chen",
        "phone_last_4": "3456",
        "email": "m.chen@email.com",
    },
    # Common test users (seed data profiles)
    ("alice brown", "1234"): {
        "client_id": "alice_brown_ab",
        "full_name": "Alice Brown",
        "phone_last_4": "9907",
        "email": "alice.brown@example.com",
    },
    ("bob williams", "5432"): {
        "client_id": "bob_williams_bw",
        "full_name": "Bob Williams",
        "phone_last_4": "4441",
        "email": "bob.williams@example.com",
    },
    # Test scenario users
    ("john smith", "5678"): {
        "client_id": "john_smith_js",
        "full_name": "John Smith",
        "phone_last_4": "1234",
        "email": "john.smith.test@example.com",
    },
    ("sarah johnson", "4321"): {
        "client_id": "sarah_johnson_sj",
        "full_name": "Sarah Johnson",
        "phone_last_4": "7890",
        "email": "sarah.johnson@example.com",
    },
}

_PENDING_MFA: dict[str, str] = {}  # client_id -> code
_COSMOS_MANAGER: CosmosDBMongoCoreManager | None = None
_COSMOS_USERS_MANAGER: CosmosDBMongoCoreManager | None = None

# User profiles are stored in the shared Cosmos DB config (see src.cosmosdb.config)
# Functions get_database_name() and get_users_collection_name() imported above


def _manager_targets_collection(
    manager: CosmosDBMongoCoreManager,
    database_name: str,
    collection_name: str,
) -> bool:
    """Return True when the manager already points to the requested db/collection."""
    try:
        db_name = getattr(getattr(manager, "database", None), "name", None)
        coll_name = getattr(getattr(manager, "collection", None), "name", None)
    except Exception:  # pragma: no cover - inspecting defensive attributes
        logger.debug("Failed to introspect Cosmos manager target", exc_info=True)
        return False
    return db_name == database_name and coll_name == collection_name


def _describe_manager_target(manager: CosmosDBMongoCoreManager) -> dict[str, str | None]:
    """Provide db/collection names for logging."""
    db_name = getattr(getattr(manager, "database", None), "name", None)
    coll_name = getattr(getattr(manager, "collection", None), "name", None)
    return {
        "database": db_name or "unknown",
        "collection": coll_name or "unknown",
    }


def _get_cosmos_manager() -> CosmosDBMongoCoreManager | None:
    """Resolve the shared Cosmos DB client from FastAPI app state."""
    global _COSMOS_MANAGER
    if _COSMOS_MANAGER is not None:
        return _COSMOS_MANAGER

    try:
        from apps.artagent.backend import main as backend_main  # local import to avoid cycles
    except Exception:  # pragma: no cover - best-effort resolution
        return None

    app = getattr(backend_main, "app", None)
    state = getattr(app, "state", None) if app else None
    cosmos = getattr(state, "cosmos", None)
    if cosmos is not None:
        _COSMOS_MANAGER = cosmos
    return cosmos


def _get_demo_users_manager() -> CosmosDBMongoCoreManager | None:
    """Return a Cosmos DB manager pointed at the demo users collection."""
    global _COSMOS_USERS_MANAGER
    database_name = get_database_name()
    container_name = get_users_collection_name()

    if _COSMOS_USERS_MANAGER is not None:
        if _manager_targets_collection(_COSMOS_USERS_MANAGER, database_name, container_name):
            return _COSMOS_USERS_MANAGER
        logger.warning(
            "Cached Cosmos demo-users manager pointed to different collection; refreshing",
            extra=_describe_manager_target(_COSMOS_USERS_MANAGER),
        )
        _COSMOS_USERS_MANAGER = None

    base_manager = _get_cosmos_manager()
    if base_manager is not None:
        if _manager_targets_collection(base_manager, database_name, container_name):
            _COSMOS_USERS_MANAGER = base_manager
            return _COSMOS_USERS_MANAGER
        logger.info(
            "Base Cosmos manager uses different collection; creating scoped users manager",
            extra=_describe_manager_target(base_manager),
        )

    if _CosmosManagerImpl is None:
        logger.warning(
            "Cosmos manager implementation unavailable; cannot query demo users collection"
        )
        return None

    try:
        _COSMOS_USERS_MANAGER = _CosmosManagerImpl(
            database_name=database_name,
            collection_name=container_name,
        )
        logger.info(
            "Auth tools connected to Cosmos demo users collection",
            extra={
                "database": database_name,
                "collection": container_name,
            },
        )
        return _COSMOS_USERS_MANAGER
    except Exception as exc:  # pragma: no cover - connection issues
        logger.warning("Unable to initialize Cosmos demo users manager: %s", exc)
        return None


async def _lookup_user_in_cosmos(
    full_name: str, ssn_last_4: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Query Cosmos DB for the caller. Returns (record, failure_reason)."""
    cosmos = _get_demo_users_manager()
    if cosmos is None:
        logger.warning(
            "⚠️ Cosmos manager unavailable for identity lookup: %s / %s",
            full_name, ssn_last_4
        )
        return None, "unavailable"

    # First try: exact match on name + SSN
    name_pattern = f"^{re.escape(full_name)}$"
    query: dict[str, Any] = {
        "verification_codes.ssn4": ssn_last_4,
        "full_name": {"$regex": name_pattern, "$options": "i"},
    }

    logger.info(
        "🔍 Cosmos identity lookup | full_name=%s | ssn_last_4=%s",
        full_name, ssn_last_4
    )

    try:
        document = await asyncio.to_thread(cosmos.read_document, query)
        if document:
            logger.info(
                "✓ Identity verified via Cosmos (exact match): %s",
                document.get("client_id") or document.get("_id")
            )
            return document, None

        # Second try: SSN-only lookup (in case speech-to-text misheard the name)
        ssn_only_query: dict[str, Any] = {"verification_codes.ssn4": ssn_last_4}
        document = await asyncio.to_thread(cosmos.read_document, ssn_only_query)
        if document:
            actual_name = document.get("full_name", "unknown")
            logger.warning(
                "⚠️ SSN matched but name mismatch | input_name=%s | db_name=%s | client_id=%s",
                full_name, actual_name, document.get("client_id")
            )
            # Return the document - the LLM can confirm with user
            return document, None

    except Exception as exc:  # pragma: no cover - network/driver failures
        logger.warning("Cosmos identity lookup failed: %s", exc)
        return None, "error"

    logger.warning(
        "✗ No user found in Cosmos | full_name=%s | ssn_last_4=%s",
        full_name, ssn_last_4
    )
    return None, "not_found"


def _format_identity_success(user: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Normalize successful identity responses."""
    client_id = user.get("client_id") or user.get("_id") or "unknown"
    caller_name = user.get("full_name") or user.get("caller_name") or user.get("name") or "caller"
    suffix = " (mock data)" if source == "mock" else ""
    return {
        "success": True,
        "authenticated": True,
        "client_id": client_id,
        "caller_name": caller_name,
        "message": f"Identity verified for {caller_name}{suffix}",
        "data_source": source,
    }


def _log_mock_usage(full_name: str, ssn_last_4: str, reason: str | None) -> None:
    reason_text = f"reason={reason}" if reason else "no cosmos access"
    logger.warning(
        "⚠️ verify_client_identity using mock dataset (%s) for %s / %s",
        reason_text,
        full_name,
        ssn_last_4,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════


async def _lookup_claim_in_cosmos(
    claim_number: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """
    Query Cosmos DB for a user profile containing the given claim number.
    
    Returns:
        (user_profile, claim, failure_reason)
        - user_profile: Full user document if found
        - claim: The matching claim dict from demo_metadata.claims
        - failure_reason: None if found, or 'unavailable'/'not_found'/'error'
    """
    cosmos = _get_demo_users_manager()
    if cosmos is None:
        logger.warning(
            "⚠️ Cosmos manager unavailable for claim lookup: %s",
            claim_number
        )
        return None, None, "unavailable"

    # Query for user with matching claim in demo_metadata.claims
    query: dict[str, Any] = {
        "demo_metadata.claims.claim_number": {"$regex": f"^{re.escape(claim_number)}$", "$options": "i"}
    }

    logger.info("🔍 Cosmos claim lookup | claim_number=%s", claim_number)

    try:
        document = await asyncio.to_thread(cosmos.read_document, query)
        if document:
            # Extract the matching claim from the document
            claims = document.get("demo_metadata", {}).get("claims", [])
            claim_upper = claim_number.upper()
            for claim in claims:
                if claim.get("claim_number", "").upper() == claim_upper:
                    logger.info(
                        "✓ Claim found in Cosmos: %s (user: %s)",
                        claim_number,
                        document.get("client_id") or document.get("_id")
                    )
                    return document, claim, None
            # Document matched but claim not in expected location
            logger.warning(
                "⚠️ Document matched query but claim not found in demo_metadata.claims: %s",
                claim_number
            )
            return document, None, "not_found"
    except Exception as exc:  # pragma: no cover - network/driver failures
        logger.warning("Cosmos claim lookup failed: %s", exc)
        return None, None, "error"

    logger.warning("✗ No user found with claim: %s", claim_number)
    return None, None, "not_found"


async def verify_cc_caller(args: dict[str, Any]) -> dict[str, Any]:
    """
    Verify Claimant Carrier representative access to claim.

    Checks:
    1. Claim exists in our system (queries Cosmos DB directly)
    2. Caller's company matches the claimant carrier on record

    Returns:
        success: bool - whether verification passed
        claim_exists: bool - whether the claim was found
        cc_verified: bool - whether the company matches
        claim_number: str - the verified claim number
        cc_company: str - the verified company name
        caller_name: str - the caller's name
        retry_allowed: bool - whether the agent should retry (max 3 attempts)
        message: str - human-readable status
    """
    claim_number = (args.get("claim_number") or "").strip().upper()
    company_name = (args.get("company_name") or "").strip()
    caller_name = (args.get("caller_name") or "").strip()

    logger.info(
        "🔐 CC Verification | claim=%s company=%s caller=%s",
        claim_number, company_name, caller_name
    )

    # Validate required fields
    if not claim_number:
        return {
            "success": False,
            "claim_exists": False,
            "cc_verified": False,
            "retry_allowed": True,
            "message": "Claim number is required. Please ask for the claim number.",
        }

    if not company_name:
        return {
            "success": False,
            "claim_exists": False,
            "cc_verified": False,
            "retry_allowed": True,
            "message": "Company name is required. Please ask which company the caller represents.",
        }

    if not caller_name:
        return {
            "success": False,
            "claim_exists": False,
            "cc_verified": False,
            "retry_allowed": True,
            "message": "Caller name is required. Please ask for the caller's name.",
        }

    # Look up claim from Cosmos DB
    user_profile, claim, failure_reason = await _lookup_claim_in_cosmos(claim_number)
    
    if not claim:
        logger.warning("❌ Claim not found: %s (reason: %s)", claim_number, failure_reason)
        return {
            "success": False,
            "claim_exists": False,
            "cc_verified": False,
            "claim_number": claim_number,
            "retry_allowed": True,
            "message": f"Claim {claim_number} not found in our system. Please verify the claim number.",
        }

    # Check if company matches the claimant carrier on record
    cc_on_record = (claim.get("claimant_carrier") or "").lower()
    company_normalized = company_name.lower()
    
    # Normalize common variations
    cc_on_record_clean = cc_on_record.replace(" insurance", "").strip()
    company_clean = company_normalized.replace(" insurance", "").strip()

    # Allow partial matching for better UX (e.g., "Contoso" matches "Contoso Insurance")
    cc_matches = (
        cc_on_record == company_normalized or
        cc_on_record_clean == company_clean or
        cc_on_record.startswith(company_clean) or
        company_normalized.startswith(cc_on_record_clean)
    )

    if not cc_matches:
        logger.warning(
            "❌ CC mismatch | claim=%s expected=%s got=%s",
            claim_number, cc_on_record, company_normalized
        )
        return {
            "success": False,
            "claim_exists": True,
            "cc_verified": False,
            "claim_number": claim_number,
            "cc_company": company_name,
            "caller_name": caller_name,
            "retry_allowed": True,
            "message": (
                f"Unable to verify. The claimant carrier on record for claim "
                f"{claim_number} does not match {company_name}."
            ),
        }

    # Verification successful
    logger.info(
        "✅ CC Verified | claim=%s company=%s caller=%s",
        claim_number, company_name, caller_name
    )
    return {
        "success": True,
        "claim_exists": True,
        "cc_verified": True,
        "claim_number": claim_number,
        "cc_company": company_name,
        "caller_name": caller_name,
        "claimant_name": claim.get("claimant_name"),
        "loss_date": claim.get("loss_date"),
        "message": f"Verified. {caller_name} from {company_name} accessing claim {claim_number}.",
    }


async def verify_client_identity(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Verify caller identity using Cosmos DB first, then fall back to mock data."""
    raw_full_name = (args.get("full_name") or "").strip()
    normalized_full_name = raw_full_name.lower()
    ssn_last_4 = (args.get("ssn_last_4") or "").strip()

    if not raw_full_name or not ssn_last_4:
        return {
            "success": False,
            "authenticated": False,
            "message": "Both full_name and ssn_last_4 are required.",
        }

    cosmos_user, cosmos_failure = await _lookup_user_in_cosmos(raw_full_name, ssn_last_4)
    if cosmos_user:
        return _format_identity_success(cosmos_user, source="cosmos")

    user = _MOCK_USERS.get((normalized_full_name, ssn_last_4))
    if user:
        _log_mock_usage(raw_full_name, ssn_last_4, cosmos_failure)
        return _format_identity_success(user, source="mock")

    logger.warning(
        "✗ Identity verification failed after Cosmos lookup (%s): %s / %s",
        cosmos_failure or "no_match",
        raw_full_name,
        ssn_last_4,
    )
    return {
        "success": False,
        "authenticated": False,
        "message": "Could not verify identity. Please check your information.",
        "data_source": "cosmos",
    }


async def enroll_voiceprint(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Enroll the current caller's voice as a biometric voiceprint."""
    if not ENABLE_VOICEPRINT:
        return {"success": False, "voiceprint_unavailable": True, "message": "Voiceprint features are currently disabled."}

    import time as _time

    full_name = (args.get("full_name") or "").strip()
    ssn_last_4 = (args.get("ssn_last_4") or "").strip()
    context: VoiceSessionContext | None = kwargs.get("context")
    t0 = _time.monotonic()

    _voiceprint_enroll_counter.add(1, {SpanAttr.VOICEPRINT_USER_NAME: full_name})

    with _tracer.start_as_current_span(
        "voiceprint.enroll",
        attributes={
            SpanAttr.VOICEPRINT_OPERATION: "enroll",
            SpanAttr.VOICEPRINT_USER_NAME: full_name,
        },
    ) as span:
        if not context or not context.recent_audio_buffer:
            span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, "audio")
            span.set_status(StatusCode.ERROR, "no audio buffer")
            _voiceprint_enroll_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: "audio"})
            return {
                "success": False,
                "message": "Unable to enroll: No audio data captured from the call yet. Please keep talking for a few more seconds.",
            }

        audio_bytes = len(context.recent_audio_buffer)
        span.set_attribute(SpanAttr.VOICEPRINT_AUDIO_BYTES, audio_bytes)

        # Verify identity first (Cosmos DB, then mock fallback)
        user, cosmos_failure = await _lookup_user_in_cosmos(full_name, ssn_last_4)
        if not user:
            # Fall back to mock data (same as verify_client_identity)
            normalized = full_name.lower()
            mock_user = _MOCK_USERS.get((normalized, ssn_last_4))
            if mock_user:
                _log_mock_usage(full_name, ssn_last_4, cosmos_failure)
                user = mock_user
            else:
                span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, "identity")
                span.set_status(StatusCode.ERROR, "user not found")
                _voiceprint_enroll_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: "identity"})
                return {"success": False, "message": "User must be verified via SSN before voice enrollment."}

        try:
            service = SpeakerRecognitionService()

            # Extract speaker embedding from recent audio
            audio_data = bytes(context.recent_audio_buffer)
            embedding = await asyncio.to_thread(service.get_embedding, audio_data)

            elapsed_ms = (_time.monotonic() - t0) * 1000
            _voiceprint_duration.record(elapsed_ms, {SpanAttr.VOICEPRINT_OPERATION: "enroll"})

            # Save embedding to user record in Cosmos
            # Strategy: find the existing Cosmos record first (by _id or name)
            # so we merge the voiceprint into the full profile, not a bare stub.
            cosmos = _get_demo_users_manager()
            if cosmos:
                user_id = user.get("_id") or user.get("client_id")
                upsert_query: dict[str, Any] = {"_id": user_id}

                # If user came from mock data (no _id from Cosmos), try to find
                # an existing Cosmos record by name to merge into instead
                if "_id" not in user:
                    name_query = {
                        "full_name": {"$regex": f"^{re.escape(full_name)}$", "$options": "i"}
                    }
                    existing = await asyncio.to_thread(cosmos.read_document, name_query)
                    if existing:
                        upsert_query = {"_id": existing["_id"]}
                        user_id = existing["_id"]
                        logger.info(
                            "Voiceprint enrollment: merging into existing Cosmos record _id=%s (instead of mock client_id=%s)",
                            user_id, user.get("client_id"),
                        )

                await asyncio.to_thread(
                    cosmos.upsert_document,
                    {
                        "voice_embedding": embedding,
                        "full_name": user.get("full_name") or full_name,
                        "client_id": user.get("client_id") or user_id,
                    },
                    upsert_query,
                )

            span.set_attribute(SpanAttr.VOICEPRINT_SUCCESS, True)
            _voiceprint_enroll_success.add(1)
            logger.info("Voiceprint enrolled for %s (embedding=%d dims, audio=%d bytes, %.0fms)", full_name, len(embedding), audio_bytes, elapsed_ms)
            return {
                "success": True,
                "message": f"Voiceprint successfully enrolled for {full_name}. You can now be verified by your voice in future calls.",
            }

        except Exception as exc:
            elapsed_ms = (_time.monotonic() - t0) * 1000
            _voiceprint_duration.record(elapsed_ms, {SpanAttr.VOICEPRINT_OPERATION: "enroll"})
            error_type = "config" if "region" in str(exc).lower() or "endpoint" in str(exc).lower() else "service"
            span.set_attribute(SpanAttr.VOICEPRINT_SUCCESS, False)
            span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, error_type)
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            _voiceprint_enroll_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: error_type})
            logger.error("Voice enrollment error (%s): %s", error_type, exc, exc_info=True)
            return {
                "success": False,
                "voiceprint_unavailable": True,
                "message": "Voiceprint service is temporarily unavailable. Please continue with standard verification.",
            }


async def verify_voiceprint(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Verify the caller's identity using their biometric voiceprint."""
    if not ENABLE_VOICEPRINT:
        return {"success": False, "voiceprint_unavailable": True, "message": "Voiceprint features are currently disabled."}

    import time as _time

    full_name = (args.get("full_name") or "").strip()
    context: VoiceSessionContext | None = kwargs.get("context")
    t0 = _time.monotonic()

    _voiceprint_verify_counter.add(1, {SpanAttr.VOICEPRINT_USER_NAME: full_name})

    with _tracer.start_as_current_span(
        "voiceprint.verify",
        attributes={
            SpanAttr.VOICEPRINT_OPERATION: "verify",
            SpanAttr.VOICEPRINT_USER_NAME: full_name,
        },
    ) as span:
        if not context or not context.recent_audio_buffer:
            span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, "audio")
            span.set_status(StatusCode.ERROR, "no audio buffer")
            _voiceprint_verify_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: "audio"})
            return {
                "success": False,
                "message": "Unable to verify: No audio data captured. Please speak clearly into the microphone.",
            }

        audio_bytes = len(context.recent_audio_buffer)
        span.set_attribute(SpanAttr.VOICEPRINT_AUDIO_BYTES, audio_bytes)

        # Lookup user to get their profile_id
        cosmos = _get_demo_users_manager()
        if not cosmos:
            span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, "service")
            span.set_status(StatusCode.ERROR, "database offline")
            _voiceprint_verify_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: "service"})
            return {"success": False, "message": "Voice verification unavailable (database offline)."}

        query = {"full_name": {"$regex": f"^{re.escape(full_name)}$", "$options": "i"}}
        user = await asyncio.to_thread(cosmos.read_document, query)

        if not user or not user.get("voice_embedding"):
            span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, "profile_missing")
            _voiceprint_verify_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: "profile_missing"})
            return {
                "success": False,
                "message": f"No voiceprint enrolled for {full_name}. Please verify via SSN first and enroll your voice.",
            }

        stored_embedding = user["voice_embedding"]

        try:
            service = SpeakerRecognitionService()
            audio_data = bytes(context.recent_audio_buffer)

            result = await asyncio.to_thread(service.verify, audio_data, stored_embedding)

            elapsed_ms = (_time.monotonic() - t0) * 1000
            _voiceprint_duration.record(elapsed_ms, {SpanAttr.VOICEPRINT_OPERATION: "verify"})

            score = result.get("score")
            matched = bool(result.get("match"))
            span.set_attribute(SpanAttr.VOICEPRINT_VERIFY_MATCH, matched)
            if score is not None:
                span.set_attribute(SpanAttr.VOICEPRINT_VERIFY_SCORE, score)

            if matched:
                span.set_attribute(SpanAttr.VOICEPRINT_SUCCESS, True)
                _voiceprint_verify_match.add(1)
                logger.info("Voiceprint verified for %s (score=%.3f, %.0fms)", full_name, score or 0, elapsed_ms)
                return _format_identity_success(user, source="voiceprint")
            else:
                span.set_attribute(SpanAttr.VOICEPRINT_SUCCESS, False)
                _voiceprint_verify_mismatch.add(1)
                logger.info("Voiceprint mismatch for %s (score=%.3f, %.0fms)", full_name, score or 0, elapsed_ms)
                return {
                    "success": False,
                    "authenticated": False,
                    "message": "Voice biometric mismatch. Identity could not be verified by voice.",
                    "score": score,
                }

        except Exception as exc:
            elapsed_ms = (_time.monotonic() - t0) * 1000
            _voiceprint_duration.record(elapsed_ms, {SpanAttr.VOICEPRINT_OPERATION: "verify"})
            error_type = "service"
            span.set_attribute(SpanAttr.VOICEPRINT_SUCCESS, False)
            span.set_attribute(SpanAttr.VOICEPRINT_ERROR_TYPE, error_type)
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            _voiceprint_verify_errors.add(1, {SpanAttr.VOICEPRINT_ERROR_TYPE: error_type})
            logger.error("Voice verification error: %s", exc, exc_info=True)
            return {
                "success": False,
                "voiceprint_unavailable": True,
                "message": "Voiceprint service is temporarily unavailable. Please continue with standard verification.",
            }


async def passive_verify_all_voiceprints(audio_data: bytes) -> dict[str, Any] | None:
    """
    Compare audio against ALL enrolled voiceprints in Cosmos DB.

    Returns the matched user dict with 'voice_score' if a match is found,
    or None if no match or if the service is unavailable.

    This is used for passive/automatic voice biometric verification —
    the system checks the caller's identity in the background without
    requiring them to explicitly ask for verification.
    """
    if not ENABLE_VOICEPRINT:
        logger.debug("Passive voiceprint: disabled by ENABLE_VOICEPRINT flag")
        return None

    import time as _time

    t0 = _time.monotonic()

    cosmos = _get_demo_users_manager()
    if not cosmos:
        logger.debug("Passive voiceprint: Cosmos unavailable")
        return None

    try:
        # Find all users with enrolled voiceprints
        enrolled_users = await asyncio.to_thread(
            cosmos.query_documents,
            {"voice_embedding": {"$exists": True}},
            projection={"full_name": 1, "client_id": 1, "voice_embedding": 1, "_id": 1},
        )

        if not enrolled_users:
            logger.debug("Passive voiceprint: No enrolled users found")
            return None

        logger.info(
            "Passive voiceprint: Checking %d enrolled users (%d bytes audio)",
            len(enrolled_users),
            len(audio_data),
        )

        service = SpeakerRecognitionService()

        best_match: dict[str, Any] | None = None
        best_score: float = 0.0

        for user in enrolled_users:
            embedding = user.get("voice_embedding")
            if not embedding:
                continue

            try:
                result = await asyncio.to_thread(
                    service.verify, audio_data, embedding
                )
                score = result.get("score", 0.0)
                matched = bool(result.get("match"))

                user_name = user.get("full_name", "unknown")
                logger.info(
                    "Passive voiceprint: %s → score=%.3f match=%s",
                    user_name, score, matched,
                )

                if matched and score > best_score:
                    best_score = score
                    best_match = {
                        "full_name": user.get("full_name"),
                        "client_id": user.get("client_id") or str(user.get("_id")),
                        "voice_score": score,
                    }
            except Exception as exc:
                logger.warning(
                    "Passive voiceprint: Error checking user %s: %s",
                    user.get("full_name"), exc,
                )
                continue

        elapsed_ms = (_time.monotonic() - t0) * 1000
        _voiceprint_duration.record(elapsed_ms, {SpanAttr.VOICEPRINT_OPERATION: "passive_verify"})

        if best_match:
            _voiceprint_verify_match.add(1)
            logger.info(
                "Passive voiceprint MATCH: %s (score=%.3f, %.0fms)",
                best_match["full_name"], best_score, elapsed_ms,
            )
        else:
            logger.info("Passive voiceprint: No match found (%.0fms)", elapsed_ms)

        return best_match

    except Exception as exc:
        logger.warning("Passive voiceprint error: %s", exc, exc_info=True)
        return None


async def send_mfa_code(args: dict[str, Any]) -> dict[str, Any]:
    """Send MFA code to customer."""
    # Prefer session-injected _client_id over LLM-provided client_id
    client_id = (args.get("_client_id") or args.get("client_id") or "").strip()
    method = (args.get("method") or "sms").strip()

    if not client_id:
        return {"success": False, "message": "client_id is required."}

    # Generate 6-digit code
    code = "".join(random.choices(string.digits, k=6))
    _PENDING_MFA[client_id] = code

    logger.info("📱 MFA code sent to %s via %s: %s", client_id, method, code)

    return {
        "success": True,
        "code_sent": True,
        "method": method,
        "message": f"Verification code sent via {method}.",
        # For demo: include code in response
        "_demo_code": code,
    }


async def verify_mfa_code(args: dict[str, Any]) -> dict[str, Any]:
    """Verify MFA code provided by customer."""
    # Prefer session-injected _client_id over LLM-provided client_id
    client_id = (args.get("_client_id") or args.get("client_id") or "").strip()
    code = (args.get("code") or "").strip()

    if not client_id or not code:
        return {"success": False, "message": "client_id and code are required."}

    expected = _PENDING_MFA.get(client_id)

    if expected and code == expected:
        del _PENDING_MFA[client_id]
        logger.info("✓ MFA verified for %s", client_id)
        return {
            "success": True,
            "verified": True,
            "message": "Verification successful. You're now authenticated.",
        }

    logger.warning("✗ MFA verification failed for %s", client_id)
    return {
        "success": False,
        "verified": False,
        "message": "Invalid code. Please try again.",
    }


async def resend_mfa_code(args: dict[str, Any]) -> dict[str, Any]:
    """Resend MFA code."""
    return await send_mfa_code(args)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

register_tool(
    "verify_client_identity",
    verify_client_identity_schema,
    verify_client_identity,
    tags={"auth", "identity"},
)

register_tool(
    "enroll_voiceprint",
    enroll_voiceprint_schema,
    enroll_voiceprint,
    tags={"auth", "voiceprint", "enrollment"},
)

register_tool(
    "verify_voiceprint",
    verify_voiceprint_schema,
    verify_voiceprint,
    tags={"auth", "voiceprint", "verification"},
)
register_tool("send_mfa_code", send_mfa_code_schema, send_mfa_code, tags={"auth", "mfa"})
register_tool("verify_mfa_code", verify_mfa_code_schema, verify_mfa_code, tags={"auth", "mfa"})
register_tool("resend_mfa_code", resend_mfa_code_schema, resend_mfa_code, tags={"auth", "mfa"})
register_tool(
    "verify_cc_caller",
    verify_cc_caller_schema,
    verify_cc_caller,
    tags={"auth", "insurance", "b2b"},
)
