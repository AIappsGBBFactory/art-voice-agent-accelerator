"""
Enhanced Financial Services MFA Authentication Tools for ARTAgent

Provides multi-factor authentication for financial services clients including:
1. Client Identity Verification (Name + Institution)
2. Company Code Authentication 
3. MFA OTP Generation and Verification
4. Transaction Authorization Levels

Integrates with the financial_services_db created in the data setup notebook.
"""

import asyncio
import datetime
import os
import secrets
import string
from typing import Any, Awaitable, Dict, List, Literal, Optional, TypedDict

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from src.acs import EmailService, SmsService, EmailTemplates
from src.acs.email_templates import _get_call_context
from utils.ml_logging import get_logger

logger = get_logger("tools.financial_mfa_auth")

# Cosmos-Only MFA Session Manager - Simplified for Scale and Traceability
class MFASessionManager:
    """
    Simplified MFA session manager using Cosmos DB only for better traceability.
    
    Key Design Decisions:
    - Cosmos DB only: Global scale, automatic replication, better auditing
    - Session Correlation: Links MFA sessions to main conversation sessions
    - TTL Support: Automatic cleanup without complex cache invalidation
    - Full Traceability: All MFA events stored permanently with correlation IDs
    """
    
    @staticmethod
    async def store_session(cosmos_mgr, session_id: str, session_data: dict) -> bool:
        """Store MFA session in Cosmos DB with automatic TTL cleanup."""
        try:
            await asyncio.to_thread(
                cosmos_mgr.upsert_document,
                document=session_data,
                query={"_id": session_id}
            )
            logger.info(f"✅ MFA session stored in Cosmos: {session_id}", 
                       extra={"mfa_session_id": session_id})
            return True
        except Exception as e:
            logger.error(f"❌ MFA session storage failed: {e}", 
                        extra={"mfa_session_id": session_id, "error_type": "storage_error"})
            return False
    
    @staticmethod
    async def get_session(cosmos_mgr, session_id: str) -> dict:
        """Get MFA session from Cosmos DB."""
        try:
            session_data = await asyncio.to_thread(
                cosmos_mgr.read_document, {"_id": session_id}
            )
            if session_data:
                logger.info(f"📋 MFA session retrieved from Cosmos: {session_id}", 
                           extra={"mfa_session_id": session_id})
            return session_data
        except Exception as e:
            logger.error(f"❌ MFA session lookup failed: {e}", 
                        extra={"mfa_session_id": session_id, "error_type": "lookup_error"})
            return None

# Initialize Cosmos DB managers for financial services
_cosmos_manager = None
_mfa_cosmos_manager = None

def get_financial_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create the financial services Cosmos DB manager for client data."""
    global _cosmos_manager
    if _cosmos_manager is None:
        # Use usecase-scoped database from environment variable
        # e.g., COSMOS_FINANCIAL_DATABASE=bofa_db for Bank of America
        #       COSMOS_FINANCIAL_DATABASE=bony_db for Bank of New York Mellon
        database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
        _cosmos_manager = CosmosDBMongoCoreManager(
            database_name=database_name,
            collection_name="users"
        )
        logger.info(f"📊 Financial Cosmos DB initialized: {database_name}.users")
    return _cosmos_manager

def get_mfa_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create the MFA sessions Cosmos DB manager."""
    global _mfa_cosmos_manager
    if _mfa_cosmos_manager is None:
        # Use same usecase-scoped database for MFA sessions
        database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
        _mfa_cosmos_manager = CosmosDBMongoCoreManager(
            database_name=database_name,
            collection_name="mfa_sessions"
        )
        logger.info(f"📊 MFA Cosmos DB initialized: {database_name}.mfa_sessions")
    return _mfa_cosmos_manager


# ──────────────────────────────────────────────────────────────────────────────
# TypedDict Models for Financial Authentication
# ──────────────────────────────────────────────────────────────────────────────

class VerifyClientArgs(TypedDict):
    """Arguments for client identity verification (Transfer Agency)."""
    full_name: str
    institution_name: str
    company_code_last4: str  # Last 4 digits of company code

class VerifyClientResult(TypedDict):
    """Result of client identity verification."""
    verified: bool
    message: str
    client_id: Optional[str]
    institution_verified: bool
    company_code_verified: bool
    requires_mfa: bool
    max_transaction_limit: Optional[int]
    authorization_level: Optional[str]

class VerifyFraudClientArgs(TypedDict):
    """Arguments for fraud client identity verification (simplified)."""
    full_name: str
    ssn_last4: str  # Last 4 digits of SSN

class VerifyFraudClientResult(TypedDict):
    """Result of fraud client identity verification."""
    verified: bool
    message: str
    client_id: Optional[str]
    requires_mfa: bool

class SendMfaCodeArgs(TypedDict):
    """Arguments for sending MFA code."""
    client_id: str
    delivery_method: Literal["email", "sms"]  # Client's preference or override
    intent: Optional[Literal["fraud", "transfer_agency"]]  # Service intent for routing
    transaction_amount: Optional[float]
    transaction_type: Optional[str]

class SendMfaCodeResult(TypedDict):
    """Result of MFA code sending."""
    sent: bool
    message: str
    session_id: Optional[str]
    delivery_address: Optional[str]
    expires_in_minutes: int

class VerifyMfaCodeArgs(TypedDict):
    """Arguments for MFA code verification."""
    session_id: str
    otp_code: str

class VerifyMfaCodeResult(TypedDict):
    """Result of MFA code verification."""
    verified: bool
    message: str
    authenticated: bool
    client_id: Optional[str]  # ← Added for orchestration compatibility
    client_name: Optional[str]
    institution_name: Optional[str]
    intent: Optional[str]  # ← Service intent for orchestration routing
    authorization_level: Optional[str]
    max_transaction_limit: Optional[int]

class CheckAuthorizationArgs(TypedDict):
    """Arguments for transaction authorization check."""
    client_id: str
    operation: str
    amount: Optional[float]

class CheckAuthorizationResult(TypedDict):
    """Result of transaction authorization check."""
    authorized: bool
    requires_mfa: bool
    requires_supervisor: bool
    message: str
    max_allowed: Optional[int]


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers for asynchronous MFA delivery
# ──────────────────────────────────────────────────────────────────────────────

class _ChannelSelection(TypedDict, total=False):
    method: Optional[str]
    address: Optional[str]
    service: Any


def _log_background_error(task: asyncio.Task) -> None:
    try:
        task.result()
    except Exception:
        logger.error("Deferred MFA delivery task failed", exc_info=True)


def _schedule_background_task(coro: Awaitable[Any], *, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_background_error)


def _select_mfa_delivery_channel(
    *,
    preferred_method: str,
    contact_info: Dict[str, Any],
    client_id: str,
) -> _ChannelSelection:
    method = (preferred_method or "email").lower()
    phone_number = (contact_info.get("phone") or "").strip()
    email_address = (contact_info.get("email") or "").strip()

    if method == "sms":
        sms_service = SmsService()
        if sms_service.is_configured() and phone_number:
            return {"method": "sms", "address": phone_number, "service": sms_service}
        logger.warning(
            "SMS delivery unavailable, falling back to email",
            extra={"client_id": client_id, "phone_present": bool(phone_number)},
        )
        method = "email"

    email_service = EmailService()
    email_configured = email_service.is_configured()
    if method == "email" and email_configured and email_address:
        return {"method": "email", "address": email_address, "service": email_service}

    logger.error(
        "No configured delivery channel for MFA code",
        extra={
            "client_id": client_id,
            "preferred_method": preferred_method,
            "email_configured": email_configured,
            "phone_available": bool(phone_number),
            "email_available": bool(email_address),
        },
    )
    return {}


async def _deliver_mfa_via_email(
    *,
    service: EmailService,
    session_id: str,
    client_id: str,
    email_address: str,
    otp_code: str,
    client_name: str,
    institution_name: str,
    transaction_amount: Optional[float],
    transaction_type: Optional[str],
) -> None:
    try:
        subject, plain_text, html = EmailTemplates.create_mfa_code_email(
            otp_code,
            client_name,
            institution_name,
            transaction_amount or 0,
            transaction_type or "general_inquiry",
        )
        await service.send_email(
            email_address=email_address,
            subject=subject,
            plain_text_body=plain_text,
            html_body=html,
        )
        logger.info(
            "✅ MFA email dispatched",
            extra={
                "mfa_session_id": session_id,
                "client_id": client_id,
                "delivery_address": email_address,
            },
        )
    except Exception as exc:  # pragma: no cover - background logging only
        logger.error(
            "Deferred MFA email delivery failed: %s",
            exc,
            extra={"mfa_session_id": session_id, "client_id": client_id},
        )


async def _deliver_mfa_via_sms(
    *,
    service: SmsService,
    session_id: str,
    client_id: str,
    phone_number: str,
    otp_code: str,
    client_first_name: str,
    transaction_type: Optional[str],
) -> None:
    try:
        call_reason = _get_call_context(transaction_type)
        message = (
            f"Hello {client_first_name or 'there'},\n\n"
            f"Your verification code for {call_reason} is: {otp_code}\n\n"
            "This code expires in 5 minutes. Our specialist will ask for this code to securely assist you.\n\n"
            "If you didn't call us, please contact us immediately.\n\n"
            "- Financial Services"
        )
        await service.send_sms(
            to_phone_numbers=phone_number,
            message=message,
        )
        logger.info(
            "✅ MFA SMS dispatched",
            extra={
                "mfa_session_id": session_id,
                "client_id": client_id,
                "delivery_address": phone_number,
            },
        )
    except Exception as exc:  # pragma: no cover - background logging only
        logger.error(
            "Deferred MFA SMS delivery failed: %s",
            exc,
            extra={"mfa_session_id": session_id, "client_id": client_id},
        )


def _start_mfa_delivery_task(
    *,
    method: str,
    service: Any,
    session_id: str,
    client_data: Dict[str, Any],
    delivery_address: str,
    otp_code: str,
    transaction_amount: Optional[float],
    transaction_type: Optional[str],
) -> None:
    client_id = client_data.get("_id") or client_data.get("client_id") or "unknown"
    if method == "sms":
        full_name = client_data.get("full_name") or ""
        client_first_name = full_name.split()[0] if full_name else ""
        _schedule_background_task(
            _deliver_mfa_via_sms(
                service=service,
                session_id=session_id,
                client_id=client_id,
                phone_number=delivery_address,
                otp_code=otp_code,
                client_first_name=client_first_name,
                transaction_type=transaction_type,
            ),
            name=f"mfa-sms-{session_id}",
        )
    else:
        _schedule_background_task(
            _deliver_mfa_via_email(
                service=service,
                session_id=session_id,
                client_id=client_id,
                email_address=delivery_address,
                otp_code=otp_code,
                client_name=client_data.get("full_name", ""),
                institution_name=client_data.get("institution_name", ""),
                transaction_amount=transaction_amount,
                transaction_type=transaction_type,
            ),
            name=f"mfa-email-{session_id}",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Financial Authentication Tools
# ──────────────────────────────────────────────────────────────────────────────

async def verify_client_identity(args: VerifyClientArgs) -> VerifyClientResult:
    """Verify client identity using name, institution, and company code."""
    client_id = None
    try:
        # Input validation
        full_name = args.get("full_name", "").strip().title()
        institution_name = args.get("institution_name", "").strip()
        company_code_last4 = args.get("company_code_last4", "").strip()
        
        if not full_name or not institution_name or not company_code_last4:
            return {
                "verified": False,
                "message": "Full name, institution, and company code (last 4 digits) are required.",
                "client_id": None,
                "institution_verified": False,
                "company_code_verified": False,
                "requires_mfa": False,
                "max_transaction_limit": None,
                "authorization_level": None
            }
        
        logger.info(f"🔍 Verifying client: {full_name} at {institution_name}", 
                   extra={"client_name": full_name, "institution": institution_name, "operation": "verify_client_identity"})
        
        try:
            cosmos = get_financial_cosmos_manager()
            database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
            logger.info(f"📊 Querying database: {database_name}.users for {full_name} at {institution_name}",
                       extra={"database": database_name, "client_name": full_name, "institution": institution_name})
            query = {"full_name": full_name, "institution_name": institution_name}
            logger.info(f"🔎 Query: {query}", extra={"query": query})
            client_data = await asyncio.to_thread(cosmos.read_document, query)
        except Exception as db_error:
            logger.error(f"❌ Database error during client lookup: {db_error}", 
                        extra={"client_name": full_name, "institution": institution_name, "error_type": "database_error"})
            return {
                "verified": False,
                "message": "Authentication service temporarily unavailable.",
                "client_id": None,
                "institution_verified": False,
                "company_code_verified": False,
                "requires_mfa": False,
                "max_transaction_limit": None,
                "authorization_level": None
            }
        
        if not client_data:
            logger.warning(f"❌ Client not found: {full_name} at {institution_name} in database {database_name}",
                          extra={"database": database_name, "client_name": full_name, "institution": institution_name})
            return {
                "verified": False,
                "message": f"Client '{full_name}' not found at '{institution_name}'.",
                "client_id": None,
                "institution_verified": False,
                "company_code_verified": False,
                "requires_mfa": False,
                "max_transaction_limit": None,
                "authorization_level": None
            }
        
        # Verify company code
        stored_code_last4 = client_data.get("company_code_last4", "")
        company_code_verified = stored_code_last4 == company_code_last4
        
        if not company_code_verified:
            logger.warning(f"❌ Company code verification failed for {full_name}")
            return {
                "verified": False,
                "message": f"Company code verification failed. Please confirm the last 4 digits of your firm's client code.",
                "client_id": client_data.get("_id"),
                "institution_verified": True,
                "company_code_verified": False,
                "requires_mfa": False,
                "max_transaction_limit": None,
                "authorization_level": None
            }
        
        # Check if client requires MFA (always true for financial services)
        mfa_enabled = client_data.get("mfa_settings", {}).get("enabled", False)
        
        logger.info(f"✅ Client verified: {full_name}")
        return {
            "verified": True,
            "message": f"Identity verified for {full_name} at {institution_name}.",
            "client_id": client_data.get("_id"),
            "institution_verified": True,
            "company_code_verified": True,
            "requires_mfa": mfa_enabled,
            "max_transaction_limit": client_data.get("max_transaction_limit"),
            "authorization_level": client_data.get("authorization_level")
        }
        
    except Exception as e:
        logger.error(f"❌ Error verifying client identity: {e}", exc_info=True)
        return {
            "verified": False,
            "message": "Authentication service temporarily unavailable. Please try again.",
            "client_id": None,
            "institution_verified": False,
            "company_code_verified": False,
            "requires_mfa": False,
            "max_transaction_limit": None,
            "authorization_level": None
        }


async def verify_fraud_client_identity(args: VerifyFraudClientArgs) -> VerifyFraudClientResult:
    """Verify fraud client identity using simplified authentication (name + SSN last 4)."""
    try:
        # Input validation
        full_name = args.get("full_name", "").strip().title()
        ssn_last4 = args.get("ssn_last4", "").strip()
        
        if not full_name or not ssn_last4:
            return {
                "verified": False,
                "message": "Full name and last 4 digits of SSN are required.",
                "client_id": None,
                "requires_mfa": False
            }
        
        logger.info(f"🔍 Verifying fraud client: {full_name} (SSN: ***{ssn_last4})", 
                   extra={"client_name": full_name, "operation": "verify_fraud_client_identity"})
        
        try:
            cosmos = get_financial_cosmos_manager()
            database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
            logger.info(f"📊 Querying database: {database_name}.users for {full_name}",
                       extra={"database": database_name, "client_name": full_name})
            # Query by name and SSN last 4 from verification_codes
            query = {
                "full_name": full_name,
                "verification_codes.ssn4": ssn_last4
            }
            logger.info(f"🔎 Query: {query}", extra={"query": query})
            client_data = await asyncio.to_thread(cosmos.read_document, query)
        except Exception as db_error:
            logger.error(f"❌ Database error during fraud client lookup: {db_error}", 
                        extra={"client_name": full_name, "error_type": "database_error"})
            return {
                "verified": False,
                "message": "Authentication service temporarily unavailable.",
                "client_id": None,
                "requires_mfa": False
            }
        
        if not client_data:
            logger.warning(f"❌ Fraud client not found: {full_name} with SSN ending {ssn_last4} in database {database_name}",
                          extra={"database": database_name, "client_name": full_name, "ssn_last4": ssn_last4})
            return {
                "verified": False,
                "message": f"Client '{full_name}' not found with provided SSN information.",
                "client_id": None,
                "requires_mfa": False
            }
        
        # Fraud reporting always requires MFA for security
        mfa_enabled = client_data.get("mfa_settings", {}).get("enabled", False)
        
        logger.info(f"✅ Fraud client verified: {full_name}")
        return {
            "verified": True,
            "message": f"Identity verified for {full_name}. Ready for fraud reporting.",
            "client_id": client_data.get("_id"),
            "requires_mfa": mfa_enabled
        }
        
    except Exception as e:
        logger.error(f"❌ Error verifying fraud client identity: {e}", exc_info=True)
        return {
            "verified": False,
            "message": "Authentication service temporarily unavailable. Please try again.",
            "client_id": None,
            "requires_mfa": False
        }


async def send_mfa_code(args: SendMfaCodeArgs) -> SendMfaCodeResult:
    """Send MFA verification code via email or SMS."""
    session_id = None
    try:
        client_id = args.get("client_id", "").strip()
        delivery_method = args.get("delivery_method", "email")
        transaction_amount = args.get("transaction_amount", 0)
        transaction_type = args.get("transaction_type", "general_inquiry")
        
        if not client_id:
            return {
                "sent": False,
                "message": "Client ID is required.",
                "session_id": None,
                "delivery_address": None,
                "expires_in_minutes": 0
            }
        
        logger.info(f"📧 Sending MFA code to client: {client_id}", 
                   extra={"client_id": client_id, "operation": "send_mfa_code"})
        
        try:
            cosmos = get_financial_cosmos_manager()
            client_data = await asyncio.to_thread(cosmos.read_document, {"_id": client_id})
        except Exception as db_error:
            logger.error(f"❌ Database error during client lookup: {db_error}", 
                        extra={"client_id": client_id, "error_type": "database_error"})
            return {
                "sent": False,
                "message": "Authentication service temporarily unavailable.",
                "session_id": None,
                "delivery_address": None,
                "expires_in_minutes": 0
            }
        
        if not client_data:
            return {
                "sent": False,
                "message": "Client not found for MFA code delivery.",
                "session_id": None,
                "delivery_address": None,
                "expires_in_minutes": 0
            }
        
        # Generate 6-digit OTP
        otp_code = ''.join(secrets.choice(string.digits) for _ in range(6))
        
        # 🎯 PERFECT SOLUTION: Store MFA session under client-specific key
        # The verification will use this same client ID to find the session
        # This creates perfect correlation without needing session ID injection
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        session_id = f"mfa_{client_id}_{timestamp}"
        
        # Get contact info and delivery channel
        contact_info = client_data.get("contact_info", {})
        preferred_method = contact_info.get("preferred_mfa_method", "email")

        if delivery_method != "email":
            preferred_method = delivery_method

        channel = _select_mfa_delivery_channel(
            preferred_method=preferred_method,
            contact_info=contact_info,
            client_id=client_id,
        )

        resolved_method = channel.get("method")
        delivery_address = channel.get("address")
        delivery_service = channel.get("service")

        if not resolved_method or not delivery_address or delivery_service is None:
            return {
                "sent": False,
                "message": "Unable to reach the configured verification channel. Please escalate to a specialist.",
                "session_id": None,
                "delivery_address": None,
                "expires_in_minutes": 0,
            }
        
        # Create MFA session record with Cosmos DB TTL for automatic cleanup
        current_time = datetime.datetime.utcnow()
        # Get intent from args (passed by auth agent based on conversation)
        intent = args.get("intent", "fraud")  # Default to fraud if not specified
        
        session_data = {
            "_id": session_id,
            "client_id": client_id,
            "full_name": client_data.get("full_name"),
            "institution_name": client_data.get("institution_name"),
            "intent": intent,  # ← Store intent for orchestration routing
            "otp_code": otp_code,
            "delivery_method": resolved_method,
            "delivery_address": delivery_address,
            "created_at": current_time.isoformat() + "Z",
            "expires_at": (current_time + datetime.timedelta(minutes=5)).isoformat() + "Z",
            "verified": False,
            "verification_attempts": 0,
            "max_attempts": 3,
            "transaction_amount": transaction_amount,
            "transaction_type": transaction_type,
            "session_status": "pending",
            # Cosmos DB TTL: Auto-delete after 12 hours (43200 seconds)
            "ttl": 43200
        }
        
        # Store session using simplified Cosmos-only approach
        mfa_cosmos = get_mfa_cosmos_manager()
        stored = await MFASessionManager.store_session(
            mfa_cosmos, session_id, session_data
        )
        
        if not stored:
            return {
                "sent": False,
                "message": "Unable to create verification session.",
                "session_id": None,
                "delivery_address": None,
                "expires_in_minutes": 0
            }
        
        _start_mfa_delivery_task(
            method=resolved_method,
            service=delivery_service,
            session_id=session_id,
            client_data=client_data,
            delivery_address=delivery_address,
            otp_code=otp_code,
            transaction_amount=transaction_amount,
            transaction_type=transaction_type,
        )
        
        logger.info(f"✅ MFA code queued via {resolved_method} to {delivery_address}", 
                   extra={"mfa_session_id": session_id, "client_id": client_id, "delivery_method": resolved_method, 
                         "delivery_address": delivery_address})
        return {
            "sent": True,
            "message": f"Verification code sent via {resolved_method}.",
            "session_id": session_id,
            "delivery_address": delivery_address,
            "expires_in_minutes": 5
        }
        
    except Exception as e:
        logger.error(f"❌ Error sending MFA code: {e}", exc_info=True)
        return {
            "sent": False,
            "message": "Failed to send verification code. Please try again.",
            "session_id": None,
            "delivery_address": None,
            "expires_in_minutes": 0
        }


async def verify_mfa_code(args: VerifyMfaCodeArgs) -> VerifyMfaCodeResult:
    """Verify the MFA code provided by the client."""
    try:
        session_id = args.get("session_id", "").strip()
        provided_code = args.get("otp_code", "").strip()
        
        if not session_id or not provided_code:
            return {
                "verified": False,
                "message": "Session ID and verification code are required.",
                "authenticated": False,
                "client_name": None,
                "institution_name": None,
                "authorization_level": None,
                "max_transaction_limit": None
            }
        
        logger.info(f"🔐 Verifying MFA code for session: {session_id}", 
                   extra={"mfa_session_id": session_id, "operation": "verify_mfa_code"})
        
        # Simplified Cosmos-only lookup
        mfa_cosmos = get_mfa_cosmos_manager()
        session_data = await MFASessionManager.get_session(mfa_cosmos, session_id)
        
        if not session_data:
            return {
                "verified": False,
                "message": "Session not found or expired. Please request a new verification code.",
                "authenticated": False,
                "client_id": None,
                "client_name": None,
                "institution_name": None,
                "authorization_level": None,
                "max_transaction_limit": None
            }
        
        # Check if session has expired
        expires_at = datetime.datetime.fromisoformat(session_data.get("expires_at", "").replace("Z", ""))
        current_time = datetime.datetime.utcnow()
        time_remaining = (expires_at - current_time).total_seconds()
        
        if current_time > expires_at:
            logger.info(f"❌ MFA session {session_id} expired at {expires_at}")
            return {
                "verified": False,
                "message": "Verification code has expired. I'll send you a new code to continue authentication.",
                "authenticated": False,
                "client_name": None,
                "institution_name": None,
                "authorization_level": None,
                "max_transaction_limit": None
            }
        
        # Warn if approaching expiration (less than 1 minute remaining)
        if time_remaining < 60:
            logger.info(f"⚠️ MFA session {session_id} expiring soon ({int(time_remaining)}s remaining)")
        
        # Check attempt limits
        attempts = session_data.get("verification_attempts", 0)
        max_attempts = session_data.get("max_attempts", 3)
        
        if attempts >= max_attempts:
            logger.warning(f"❌ Maximum MFA attempts exceeded for session {session_id}")
            return {
                "verified": False,
                "message": "Maximum verification attempts exceeded. For your security, I'm connecting you to a specialist who can authenticate you.",
                "authenticated": False,
                "client_id": None,
                "client_name": None,
                "institution_name": None,
                "authorization_level": None,
                "max_transaction_limit": None
            }
        
        # Verify the code
        stored_code = session_data.get("otp_code", "")
        code_valid = stored_code == provided_code
        
        # Update attempt count
        await asyncio.to_thread(
            mfa_cosmos.upsert_document,
            document={**session_data, "verification_attempts": attempts + 1},
            query={"_id": session_id}
        )
        
        if not code_valid:
            remaining_attempts = max_attempts - (attempts + 1)
            
            # Provide helpful feedback based on remaining attempts
            if remaining_attempts > 1:
                message = f"That code doesn't match. Please double-check the 6-digit code and try again. You have {remaining_attempts} attempts remaining."
            elif remaining_attempts == 1:
                message = "That code doesn't match. Please carefully check your email or phone for the correct 6-digit code. This is your final attempt."
            else:
                message = "Maximum verification attempts exceeded. For your security, I'm connecting you to a specialist."
            
            logger.info(f"❌ Invalid MFA code for session {session_id}. Attempts: {attempts + 1}/{max_attempts}")
            
            return {
                "verified": False,
                "message": message,
                "authenticated": False,
                "client_id": None,
                "client_name": None,
                "institution_name": None,
                "authorization_level": None,
                "max_transaction_limit": None
            }
        
        # Get client data for final response
        client_id = session_data.get("client_id")
        cosmos = get_financial_cosmos_manager()  # Use financial clients manager
        client_data = await asyncio.to_thread(cosmos.read_document, {"_id": client_id})
        
        if not client_data:
            return {
                "verified": False,
                "message": "Client data not found.",
                "authenticated": False,
                "client_id": None,
                "client_name": None,
                "intent": None,
                "institution_name": None,
                "authorization_level": None,
                "max_transaction_limit": None
            }
        
        # Mark session as verified
        await asyncio.to_thread(
            mfa_cosmos.upsert_document,
            document={**session_data, "verified": True, "session_status": "verified"},
            query={"_id": session_id}
        )
        
        client_name = client_data.get("full_name", "Unknown")
        institution_name = client_data.get("institution_name", "Unknown")
        
        logger.info(f"✅ MFA verification successful for {client_name}", 
                   extra={"mfa_session_id": session_id, "client_id": client_id, 
                         "client_name": client_name, "institution": institution_name})
        # Get intent from session for orchestration routing
        intent = session_data.get("intent", "fraud")
        
        return {
            "verified": True,
            "message": "Authentication complete. Welcome to Financial Services.",
            "authenticated": True,
            "client_id": client_id,  # ← Now returning client_id for memory storage
            "client_name": client_name,
            "institution_name": institution_name,
            "intent": intent,  # ← Return intent for orchestration routing
            "authorization_level": client_data.get("authorization_level"),
            "max_transaction_limit": client_data.get("max_transaction_limit")
        }
        
    except Exception as e:
        logger.error(f"❌ Error verifying MFA code: {e}", exc_info=True, 
                    extra={"mfa_session_id": session_id, "error_type": "mfa_verification_error"})
        return {
            "verified": False,
            "message": "Verification service temporarily unavailable. Please try again.",
            "authenticated": False,
            "client_id": None,
            "client_name": None,
            "institution_name": None,
            "intent": None,
            "authorization_level": None,
            "max_transaction_limit": None
        }


async def resend_mfa_code(args: SendMfaCodeArgs) -> SendMfaCodeResult:
    """Resend MFA code - invalidates previous session and creates new one."""
    try:
        client_id = args.get("client_id", "").strip()
        preferred_method = args.get("delivery_method", "email").lower()
        
        if not client_id:
            return {
                "sent": False,
                "message": "Client ID is required to resend verification code.",
                "session_id": None,
                "delivery_address": None,
                "expires_in_minutes": 0
            }
        
        logger.info(f"🔄 Resending MFA code for client {client_id}")
        
        # Invalidate any existing sessions for this client
        try:
            cosmos = get_financial_cosmos_manager()
            # Find existing sessions and mark them as expired
            existing_sessions = await asyncio.to_thread(
                cosmos.query_documents, 
                {"client_id": client_id, "session_status": "pending"}
            )
            
            for session in existing_sessions:
                await asyncio.to_thread(
                    cosmos.upsert_document,
                    document={**session, "session_status": "superseded"},
                    query={"_id": session["_id"]}
                )
            
            logger.info(f"📝 Invalidated {len(existing_sessions)} existing MFA sessions")
            
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Could not cleanup existing sessions: {cleanup_error}")
        
        # Send new MFA code (reuse existing function)
        return await send_mfa_code(args)
        
    except Exception as e:
        logger.error(f"❌ Error resending MFA code: {e}", exc_info=True)
        return {
            "sent": False,
            "message": "Failed to resend verification code. Please try again.",
            "session_id": None,
            "delivery_address": None,
            "expires_in_minutes": 0
        }


async def check_transaction_authorization(args: CheckAuthorizationArgs) -> CheckAuthorizationResult:
    """Check if client is authorized for specific transaction type and amount."""
    try:
        client_id = args.get("client_id", "").strip()
        operation = args.get("operation", "").strip()
        amount = args.get("amount", 0)
        
        if not client_id or not operation:
            return {
                "authorized": False,
                "requires_mfa": False,
                "requires_supervisor": False,
                "message": "Client ID and operation are required.",
                "max_allowed": None
            }
        
        logger.info(f"🔍 Checking authorization for {operation} (${amount:,})")
        
        try:
            cosmos = get_financial_cosmos_manager()
            client_data = await asyncio.to_thread(cosmos.read_document, {"_id": client_id})
        except Exception as db_error:
            logger.error(f"❌ Database error during authorization check: {db_error}")
            return {
                "authorized": False,
                "requires_mfa": False,
                "requires_supervisor": False,
                "message": "Authorization service temporarily unavailable.",
                "max_allowed": None
            }
        
        if not client_data:
            return {
                "authorized": False,
                "requires_mfa": False,
                "requires_supervisor": False,
                "message": "Client not found for authorization check.",
                "max_allowed": None
            }
        
        # Authorization matrix for Transfer Agency & Fraud Reporting services
        authorization_matrix = {
            "junior_analyst": {
                "max_transaction_limit": 5000000,
                "allowed_operations": ["account_inquiry", "balance_check", "transaction_history", "small_transfers", "fraud_reporting", "dispute_transaction"],
                "requires_supervisor_approval": ["large_transfers", "liquidations", "account_modifications", "drip_liquidation"]
            },
            "portfolio_manager": {
                "max_transaction_limit": 25000000,
                "allowed_operations": ["account_inquiry", "balance_check", "transaction_history", "small_transfers", "medium_transfers", "liquidations", "portfolio_rebalancing", "fraud_reporting", "dispute_transaction", "drip_liquidation", "institutional_servicing"],
                "requires_supervisor_approval": ["large_liquidations", "account_closures", "fraud_investigation"]
            },
            "senior_advisor": {
                "max_transaction_limit": 50000000,
                "allowed_operations": ["account_inquiry", "balance_check", "transaction_history", "small_transfers", "medium_transfers", "large_transfers", "liquidations", "large_liquidations", "portfolio_rebalancing", "account_modifications", "fraud_reporting", "dispute_transaction", "drip_liquidation", "institutional_servicing", "fraud_investigation"],
                "requires_supervisor_approval": ["account_closures", "regulatory_overrides", "large_drip_liquidation"]
            },
            "fund_manager": {
                "max_transaction_limit": 100000000,
                "allowed_operations": ["account_inquiry", "balance_check", "transaction_history", "small_transfers", "medium_transfers", "large_transfers", "liquidations", "large_liquidations", "portfolio_rebalancing", "account_modifications", "fund_operations", "institutional_transfers", "fraud_reporting", "dispute_transaction", "drip_liquidation", "large_drip_liquidation", "institutional_servicing", "fraud_investigation"],
                "requires_supervisor_approval": ["regulatory_overrides", "emergency_liquidations", "major_fraud_cases"]
            }
        }
        
        auth_level = client_data.get("authorization_level", "junior_analyst")
        max_limit = client_data.get("max_transaction_limit", 0)
        mfa_threshold = client_data.get("mfa_required_threshold", 10000)
        
        auth_config = authorization_matrix.get(auth_level, {})
        allowed_ops = auth_config.get("allowed_operations", [])
        supervisor_ops = auth_config.get("requires_supervisor_approval", [])
        
        # Check operation permission
        if operation in allowed_ops:
            authorized = True
            requires_supervisor = False
            message = "Operation authorized."
        elif operation in supervisor_ops:
            authorized = True
            requires_supervisor = True
            message = "Operation requires supervisor approval."
        else:
            return {
                "authorized": False,
                "requires_mfa": False,
                "requires_supervisor": False,
                "message": f"Operation '{operation}' not authorized for {auth_level.replace('_', ' ')}.",
                "max_allowed": max_limit
            }
        
        # Check amount limits
        if amount > max_limit:
            return {
                "authorized": False,
                "requires_mfa": False,
                "requires_supervisor": False,
                "message": f"Amount ${amount:,} exceeds limit of ${max_limit:,}.",
                "max_allowed": max_limit
            }
        
        # Check MFA requirement
        requires_mfa = amount >= mfa_threshold
        
        logger.info(f"✅ Authorization check complete: {message}")
        return {
            "authorized": authorized,
            "requires_mfa": requires_mfa,
            "requires_supervisor": requires_supervisor,
            "message": message,
            "max_allowed": max_limit
        }
        
    except Exception as e:
        logger.error(f"❌ Error checking transaction authorization: {e}", exc_info=True)
        return {
            "authorized": False,
            "requires_mfa": False,
            "requires_supervisor": False,
            "message": "Authorization service temporarily unavailable.",
            "max_allowed": None
        }


# Add MFA email template creation function
def create_mfa_code_email(otp_code: str, client_name: str, institution_name: str, transaction_amount: float, transaction_type: str) -> tuple[str, str, str]:
    """Create MFA code email for financial services with context about the call reason."""
    subject = f"Financial Services - Verification Code for Your Call"
    
    # Determine the actual service/topic the user is calling about
    call_reason = _get_call_context(transaction_type)
    
    plain_text = f"""Dear {client_name},

Thank you for contacting Financial Services regarding {call_reason}.

To continue assisting you securely, please use this verification code: {otp_code}

This code will expire in 5 minutes.

Our specialist will verify this code with you during your call to ensure we can safely assist with your {call_reason.lower()}.

If you did not initiate this call, please contact us immediately.

Best regards,
Financial Services Team"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <div style="background: #0066cc; color: white; padding: 20px; text-align: center;">
        <h1>🏛️ Financial Services</h1>
        <h2>Verification Code for Your Call</h2>
    </div>
    
    <div style="padding: 20px; background: #f9f9f9;">
        <p>Dear <strong>{client_name}</strong>,</p>
        
        <p>Thank you for contacting Financial Services regarding <strong>{call_reason}</strong>.</p>
        
        <div style="background: white; padding: 20px; text-align: center; margin: 20px 0; border-radius: 8px;">
            <h3>Your Verification Code</h3>
            <div style="font-size: 32px; font-weight: bold; color: #0066cc; letter-spacing: 8px;">{otp_code}</div>
            <p style="color: #666;">This code expires in 5 minutes</p>
        </div>
        
        <div style="background: white; padding: 15px; margin: 20px 0; border-radius: 8px; border-left: 4px solid #0066cc;">
            <h4>📞 What happens next?</h4>
            <p>Our specialist will ask you for this code during your call to securely verify your identity before we can assist with your {call_reason.lower()}.</p>
        </div>
        
        <p><em>If you did not initiate this call, please contact us immediately.</em></p>
    </div>
    
    <div style="background: #333; color: white; padding: 15px; text-align: center;">
        <p>Financial Services - Your Trusted Partner</p>
        <p style="font-size: 12px; margin: 5px 0;">Institution: {institution_name}</p>
    </div>
</body>
</html>"""

    return subject, plain_text, html