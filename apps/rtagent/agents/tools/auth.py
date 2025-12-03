"""
Authentication & MFA Tools
==========================

Tools for identity verification, MFA, and authentication.
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any, Dict

from apps.rtagent.agents.tools.registry import register_tool
from utils.ml_logging import get_logger

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


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_client_identity(args: Dict[str, Any]) -> Dict[str, Any]:
    """Verify caller identity using name and SSN last 4."""
    full_name = (args.get("full_name") or "").strip().lower()
    ssn_last_4 = (args.get("ssn_last_4") or "").strip()
    
    if not full_name or not ssn_last_4:
        return {
            "success": False,
            "authenticated": False,
            "message": "Both full_name and ssn_last_4 are required.",
        }
    
    # Look up user
    user = _MOCK_USERS.get((full_name, ssn_last_4))
    
    if user:
        logger.info("✓ Identity verified: %s", user["client_id"])
        return {
            "success": True,
            "authenticated": True,
            "client_id": user["client_id"],
            "caller_name": user["full_name"],
            "message": f"Identity verified for {user['full_name']}",
        }
    
    logger.warning("✗ Identity verification failed: %s / %s", full_name, ssn_last_4)
    return {
        "success": False,
        "authenticated": False,
        "message": "Could not verify identity. Please check your information.",
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
