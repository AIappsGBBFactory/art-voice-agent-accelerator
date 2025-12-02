"""
Banking E-Signature Tools
========================

Tools for credit card application e-signature workflow:
- send_card_agreement: Send cardholder agreement email with verification code
- verify_esignature: Verify MFA code and process e-signature
- finalize_card_application: Complete application and send confirmation
"""

from __future__ import annotations

import asyncio
import random
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, TypedDict

from apps.artagent.backend.src.agents.vlagents.tool_store.banking.banking_email_templates import BankingEmailTemplates
from src.acs import EmailService
from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

# Import centralized constants
from ..constants.banking_constants import (
    INSTITUTION_CONFIG,
    CARD_PRODUCTS,
    CREDIT_LIMITS_BY_INCOME,
    MFA_CODE_LENGTH,
    MFA_CODE_EXPIRY_HOURS,
    CARD_DELIVERY_TIMEFRAME,
    card_product_to_dict,
)

logger = get_logger("banking_esign_tools")

# Initialize Cosmos DB managers
_banking_cosmos_manager = None
_esign_sessions_manager = None

def get_banking_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get or create the banking services Cosmos DB manager."""
    global _banking_cosmos_manager
    if _banking_cosmos_manager is None:
        _banking_cosmos_manager = CosmosDBMongoCoreManager(
            database_name="banking_services_db",
            collection_name="users"
        )
    return _banking_cosmos_manager

def get_esign_sessions_manager() -> CosmosDBMongoCoreManager:
    """Get or create the e-signature sessions Cosmos DB manager."""
    global _esign_sessions_manager
    if _esign_sessions_manager is None:
        _esign_sessions_manager = CosmosDBMongoCoreManager(
            database_name="banking_services_db",
            collection_name="esign_sessions"
        )
    return _esign_sessions_manager


def _json(success: bool, message: str, **extras: Any) -> Dict[str, Any]:
    """Helper to build consistent JSON responses."""
    result = {"success": success, "message": message}
    result.update(extras)
    return result


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_mfa_code() -> str:
    """Generate a 6-digit MFA code."""
    max_val = 10 ** MFA_CODE_LENGTH - 1
    min_val = 10 ** (MFA_CODE_LENGTH - 1)
    return f"{random.randint(min_val, max_val)}"


# ═══════════════════════════════════════════════════════════════════
# E-SIGNATURE WORKFLOW TOOLS
# ═══════════════════════════════════════════════════════════════════


class SendCardAgreementArgs(TypedDict, total=False):
    """Input schema for send_card_agreement."""
    client_id: str
    card_product_id: str
    card_name: str


async def send_card_agreement(args: SendCardAgreementArgs) -> Dict[str, Any]:
    """
    Send cardholder agreement email with personalized card details and verification code.
    
    This initiates the e-signature workflow by:
    1. Generating a 6-digit MFA verification code
    2. Creating personalized cardholder agreement email with card details
    3. Sending email with secure e-signature link
    4. Storing verification code for later validation
    
    Args:
        client_id: Unique customer identifier
        card_product_id: Selected card product ID (e.g., 'travel-rewards-001')
    
    Returns:
        Dict with success status, message, verification_code, and email details
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        card_product_id = (args.get("card_product_id") or "").strip()
        
        if not client_id or not card_product_id:
            return _json(False, "client_id and card_product_id are required.")
        
        logger.info(
            "📧 Sending card agreement | client_id=%s card=%s",
            client_id, card_product_id
        )
        
        # Generate MFA verification code
        verification_code = _generate_mfa_code()
        
        # Get card details from constants
        card_product = CARD_PRODUCTS.get(card_product_id)
        if card_product:
            card_data = {
                "card_name": card_product.name,
                "annual_fee": card_product.annual_fee,
                "regular_apr": card_product.regular_apr,
                "intro_apr": card_product.intro_apr,
                "rewards_rate": card_product.rewards_rate,
                "foreign_transaction_fee": card_product.foreign_transaction_fee,
                "highlights": card_product.highlights
            }
        else:
            card_data = {
                "card_name": "Credit Card",
                "annual_fee": 0,
                "regular_apr": "19.24% - 29.24% variable APR",
                "intro_apr": "",
                "rewards_rate": "Rewards vary by card",
                "foreign_transaction_fee": 0,
                "highlights": ["Benefits vary by card"]
            }
        
        # Fetch customer data from Cosmos DB
        try:
            cosmos = get_banking_cosmos_manager()
            customer_data = await asyncio.to_thread(
                cosmos.read_document, 
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error during customer lookup: {db_error}")
            return _json(False, "Unable to retrieve customer information.")
        
        if not customer_data:
            logger.error(f"❌ Customer not found: {client_id}")
            return _json(False, "Customer not found.")
        
        # Get customer details
        customer_name = customer_data.get("full_name", "Valued Customer")
        contact_info = customer_data.get("contact_info", {})
        customer_email = contact_info.get("email", "")
        
        if not customer_email:
            return _json(False, "No email address found for customer.")
        
        # Create email using BankingEmailTemplates
        subject, plain_text, html_body = BankingEmailTemplates.create_card_agreement_email(
            customer_name=customer_name,
            email=customer_email,
            card_data=card_data,
            verification_code=verification_code,
            institution_name="Bank of America"
        )
        
        # Store verification code in Cosmos DB for later validation
        current_time = datetime.now(timezone.utc)
        session_id = f"esign_{client_id}_{current_time.strftime('%Y%m%d_%H%M%S')}"
        
        session_data = {
            "_id": session_id,
            "client_id": client_id,
            "verification_code": verification_code,
            "card_product_id": card_product_id,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "created_at": current_time.isoformat(),
            "expires_at": (current_time + timedelta(hours=MFA_CODE_EXPIRY_HOURS)).isoformat(),
            "verified": False,
            "session_status": "pending",
            "ttl": MFA_CODE_EXPIRY_HOURS * 3600  # Auto-delete after expiry
        }
        
        try:
            esign_cosmos = get_esign_sessions_manager()
            await asyncio.to_thread(
                esign_cosmos.upsert_document,
                document=session_data,
                query={"_id": session_id}
            )
        except Exception as storage_error:
            logger.error(f"❌ Failed to store e-signature session: {storage_error}")
            return _json(False, "Unable to create verification session.")
        
        # Send email via Azure Communication Services
        try:
            email_service = EmailService()
            if email_service.is_configured():
                logger.info(f"📧 Sending card agreement email to {customer_email} with code {verification_code}")
                result = await email_service.send_email(
                    email_address=customer_email,
                    subject=subject,
                    plain_text_body=plain_text,
                    html_body=html_body
                )
                
                if result.get("success"):
                    logger.info(
                        "✅ Card agreement email sent | to=%s card=%s code=%s",
                        customer_email, card_data["card_name"], verification_code
                    )
                else:
                    logger.error(f"❌ Email send failed: {result.get('error')}")
                    return _json(False, "Unable to send email. Please try again.")
            else:
                logger.error("❌ Email service not configured")
                return _json(False, "Email service unavailable. Please contact support.")
        except Exception as send_error:
            logger.error(f"❌ Failed to send email: {send_error}", exc_info=True)
            return _json(False, "Unable to send email at this time.")
        
        return _json(
            True,
            f"Cardholder agreement sent to {customer_email}. Customer should check email for verification code.",
            verification_code=verification_code,
            email=customer_email,
            card_name=card_data["card_name"],
            expires_in_hours=MFA_CODE_EXPIRY_HOURS,
            session_id=session_id
        )
    
    except Exception as exc:
        logger.error("Failed to send card agreement: %s", exc, exc_info=True)
        return _json(False, "Unable to send cardholder agreement at this time.")


class VerifyEsignatureArgs(TypedDict, total=False):
    """Input schema for verify_esignature."""
    client_id: str
    verification_code: str


async def verify_esignature(args: VerifyEsignatureArgs) -> Dict[str, Any]:
    """
    Verify MFA code and process e-signature confirmation.
    
    This validates the customer's identity and confirms they've signed the agreement:
    1. Validates the 6-digit MFA code
    2. Confirms code hasn't expired
    3. Marks e-signature as complete
    4. Returns card product details for adjudication
    
    Args:
        client_id: Unique customer identifier
        verification_code: 6-digit code customer entered
    
    Returns:
        Dict with success status, signature confirmation, and card details
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        verification_code = (args.get("verification_code") or "").strip()
        
        if not client_id or not verification_code:
            return _json(False, "client_id and verification_code are required.")
        
        logger.info(
            "🔐 Verifying e-signature | client_id=%s code=%s",
            client_id, verification_code
        )
        
        # Validate code format
        if len(verification_code) != 6 or not verification_code.isdigit():
            return _json(False, "Invalid verification code format. Must be 6 digits.")
        
        # Find active session for this client with matching verification code
        try:
            esign_cosmos = get_esign_sessions_manager()
            session_data = await asyncio.to_thread(
                esign_cosmos.read_document,
                {
                    "client_id": client_id,
                    "verification_code": verification_code,
                    "verified": False
                }
            )
        except Exception as db_error:
            logger.error(f"❌ Database error during verification lookup: {db_error}")
            return _json(False, "Unable to verify code at this time.")
        
        if not session_data:
            logger.warning(f"❌ Invalid or expired verification code for client: {client_id}")
            return _json(False, "Invalid or expired verification code.")
        
        # Check expiration
        expires_at_str = session_data["expires_at"]
        # Handle both Z and +00:00 formats, remove any duplicate timezone markers
        if expires_at_str.endswith("Z"):
            expires_at_str = expires_at_str[:-1] + "+00:00"
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now(timezone.utc) > expires_at:
            logger.warning(f"❌ Verification code expired for client: {client_id}")
            return _json(False, "Verification code has expired. Please request a new agreement.")
        
        # Mark session as verified
        session_data["verified"] = True
        session_data["verified_at"] = _utc_now()
        session_data["session_status"] = "verified"
        
        try:
            await asyncio.to_thread(
                esign_cosmos.upsert_document,
                document=session_data,
                query={"_id": session_data["_id"]}
            )
        except Exception as update_error:
            logger.error(f"❌ Failed to update session: {update_error}")
        
        logger.info("✅ E-signature verified for client: %s", client_id)
        
        return _json(
            True,
            "E-signature verified successfully.",
            client_id=client_id,
            verified_at=_utc_now(),
            card_product_id=session_data.get("card_product_id"),
            next_step="finalize_card_application"
        )
    
    except Exception as exc:
        logger.error("E-signature verification failed: %s", exc, exc_info=True)
        return _json(False, "Unable to verify e-signature at this time.")


class FinalizeCardApplicationArgs(TypedDict, total=False):
    """Input schema for finalize_card_application."""
    client_id: str
    card_product_id: str
    card_name: str


async def finalize_card_application(args: FinalizeCardApplicationArgs) -> Dict[str, Any]:
    """
    Complete card application, simulate adjudication, and send approval confirmation.
    
    This finalizes the application workflow:
    1. Simulates instant adjudication/approval (deterministic bot in production)
    2. Generates card number and credit limit
    3. Sends approval confirmation email with delivery details
    4. Provides digital wallet setup instructions
    
    Args:
        client_id: Unique customer identifier
        card_product_id: Selected card product ID
        card_name: Human-readable card name
    
    Returns:
        Dict with approval status, card details, and delivery information
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format.")
    
    try:
        client_id = (args.get("client_id") or "").strip()
        card_product_id = (args.get("card_product_id") or "").strip()
        card_name = (args.get("card_name") or "Credit Card").strip()
        
        if not client_id or not card_product_id:
            return _json(False, "client_id and card_product_id are required.")
        
        logger.info(
            "🎉 Finalizing card application | client_id=%s card=%s",
            client_id, card_product_id
        )
        
        # Fetch customer data from Cosmos DB
        try:
            cosmos = get_banking_cosmos_manager()
            customer_data = await asyncio.to_thread(
                cosmos.read_document,
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error during customer lookup: {db_error}")
            return _json(False, "Unable to retrieve customer information.")
        
        if not customer_data:
            logger.error(f"❌ Customer not found: {client_id}")
            return _json(False, "Customer not found.")
        
        # Get customer details
        customer_name = customer_data.get("full_name", "Valued Customer")
        contact_info = customer_data.get("contact_info", {})
        customer_email = contact_info.get("email", "")
        
        if not customer_email:
            return _json(False, "No email address found for customer.")
        
        # Generate card details (in production, create actual card account)
        card_number_last4 = f"{secrets.randbelow(10000):04d}"
        
        # Get card name from constants
        card_product = CARD_PRODUCTS.get(card_product_id)
        if card_product:
            card_name = card_product.name
        else:
            card_name = args.get("card_name", "Credit Card")
        
        # Determine credit limit based on customer profile using constants
        bank_profile = customer_data.get("customer_intelligence", {}).get("bank_profile", {})
        income_band = customer_data.get("customer_intelligence", {}).get("employment", {}).get("incomeBand", "medium")
        
        # Calculate credit limit based on profile from constants
        credit_limit = CREDIT_LIMITS_BY_INCOME.get(income_band, CREDIT_LIMITS_BY_INCOME["medium"])
        
        card_details = {
            "card_number_last4": card_number_last4,
            "card_name": card_name,
            "credit_limit": credit_limit,
            "activation_date": _utc_now(),
            "physical_card_delivery": CARD_DELIVERY_TIMEFRAME,
            "digital_wallet_ready": True
        }
        
        # Create approval email
        subject, plain_text, html_body = BankingEmailTemplates.create_card_approval_email(
            customer_name=customer_name,
            email=customer_email,
            card_details=card_details,
            institution_name="Bank of America"
        )
        
        # Send approval email via Azure Communication Services
        try:
            email_service = EmailService()
            if email_service.is_configured():
                logger.info(f"📧 Sending card approval email to {customer_email}")
                result = await email_service.send_email(
                    email_address=customer_email,
                    subject=subject,
                    plain_text_body=plain_text,
                    html_body=html_body
                )
                
                if result.get("success"):
                    logger.info(
                        "✅ Card approval email sent | to=%s card=****%s limit=$%d",
                        customer_email, card_details["card_number_last4"], credit_limit
                    )
                else:
                    logger.warning(f"⚠️ Approval email failed: {result.get('error')} | Card still approved")
            else:
                logger.warning("⚠️ Email service not configured | Card still approved")
        except Exception as send_error:
            logger.error(f"❌ Failed to send approval email: {send_error}", exc_info=True)
            logger.warning("Card approved but email notification failed")
        
        return _json(
            True,
            f"Congratulations! Your {card_details['card_name']} has been approved.",
            card_number_last4=card_details["card_number_last4"],
            credit_limit=card_details["credit_limit"],
            physical_delivery=card_details["physical_card_delivery"],
            digital_wallet_ready=card_details["digital_wallet_ready"],
            confirmation_email_sent=True
        )
    
    except Exception as exc:
        logger.error("Card application finalization failed: %s", exc, exc_info=True)
        return _json(False, "Unable to finalize application at this time.")
