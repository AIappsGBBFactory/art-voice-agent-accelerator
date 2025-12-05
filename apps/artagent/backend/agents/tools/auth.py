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
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from apps.artagent.backend.agents.tools.registry import register_tool
from utils.ml_logging import get_logger

try:  # pragma: no cover - optional dependency during tests
    from src.cosmosdb.manager import CosmosDBMongoCoreManager as _CosmosManagerImpl
except Exception:  # pragma: no cover - handled at runtime
    _CosmosManagerImpl = None

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.cosmosdb.manager import CosmosDBMongoCoreManager

logger = get_logger("agents.tools.auth")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

verify_client_identity_schema: Dict[str, Any] = {
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

send_mfa_code_schema: Dict[str, Any] = {
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

verify_mfa_code_schema: Dict[str, Any] = {
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

resend_mfa_code_schema: Dict[str, Any] = {
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
}

_PENDING_MFA: Dict[str, str] = {}  # client_id -> code
_COSMOS_MANAGER: Optional["CosmosDBMongoCoreManager"] = None
_COSMOS_USERS_MANAGER: Optional["CosmosDBMongoCoreManager"] = None

_DEFAULT_DEMO_DB = "financial_services_db"
_DEFAULT_DEMO_USERS_COLLECTION = "users"


def _get_demo_database_name() -> str:
    value = os.getenv("AZURE_COSMOS_DATABASE_NAME")
    if value:
        stripped = value.strip()
        if stripped:
            return stripped
    return _DEFAULT_DEMO_DB


def _get_demo_users_collection_name() -> str:
    for env_key in ("AZURE_COSMOS_USERS_COLLECTION_NAME", "AZURE_COSMOS_COLLECTION_NAME"):
        value = os.getenv(env_key)
        if value:
            stripped = value.strip()
            if stripped:
                return stripped
    return _DEFAULT_DEMO_USERS_COLLECTION


def _manager_targets_collection(
    manager: "CosmosDBMongoCoreManager",
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


def _describe_manager_target(manager: "CosmosDBMongoCoreManager") -> Dict[str, Optional[str]]:
    """Provide db/collection names for logging."""
    db_name = getattr(getattr(manager, "database", None), "name", None)
    coll_name = getattr(getattr(manager, "collection", None), "name", None)
    return {
        "database": db_name or "unknown",
        "collection": coll_name or "unknown",
    }


def _get_cosmos_manager() -> Optional["CosmosDBMongoCoreManager"]:
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


def _get_demo_users_manager() -> Optional["CosmosDBMongoCoreManager"]:
    """Return a Cosmos DB manager pointed at the demo users collection."""
    global _COSMOS_USERS_MANAGER
    database_name = _get_demo_database_name()
    container_name = _get_demo_users_collection_name()

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
        logger.warning("Cosmos manager implementation unavailable; cannot query demo users collection")
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


async def _lookup_user_in_cosmos(full_name: str, ssn_last_4: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Query Cosmos DB for the caller. Returns (record, failure_reason)."""
    cosmos = _get_demo_users_manager()
    if cosmos is None:
        return None, "unavailable"

    name_pattern = f"^{re.escape(full_name)}$"
    query: Dict[str, Any] = {
        "verification_codes.ssn4": ssn_last_4,
        "full_name": {"$regex": name_pattern, "$options": "i"},
    }

    try:
        document = await asyncio.to_thread(cosmos.read_document, query)
    except Exception as exc:  # pragma: no cover - network/driver failures
        logger.warning("Cosmos identity lookup failed: %s", exc)
        return None, "error"

    if document:
        logger.info("✓ Identity verified via Cosmos: %s", document.get("client_id") or document.get("_id"))
        return document, None

    return None, "not_found"


def _format_identity_success(user: Dict[str, Any], *, source: str) -> Dict[str, Any]:
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


def _log_mock_usage(full_name: str, ssn_last_4: str, reason: Optional[str]) -> None:
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

async def verify_client_identity(args: Dict[str, Any]) -> Dict[str, Any]:
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


async def send_mfa_code(args: Dict[str, Any]) -> Dict[str, Any]:
    """Send MFA code to customer."""
    client_id = (args.get("client_id") or "").strip()
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


async def verify_mfa_code(args: Dict[str, Any]) -> Dict[str, Any]:
    """Verify MFA code provided by customer."""
    client_id = (args.get("client_id") or "").strip()
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


async def resend_mfa_code(args: Dict[str, Any]) -> Dict[str, Any]:
    """Resend MFA code."""
    return await send_mfa_code(args)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

register_tool("verify_client_identity", verify_client_identity_schema, verify_client_identity, tags={"auth"})
register_tool("send_mfa_code", send_mfa_code_schema, send_mfa_code, tags={"auth", "mfa"})
register_tool("verify_mfa_code", verify_mfa_code_schema, verify_mfa_code, tags={"auth", "mfa"})
register_tool("resend_mfa_code", resend_mfa_code_schema, resend_mfa_code, tags={"auth", "mfa"})
