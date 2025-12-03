"""
Banking E-Signature Tools
========================

Tools for credit card application e-signature workflow:
- evaluate_card_eligibility: Check if customer is pre-approved for a card
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
    CUSTOMER_TIERS,
    CREDIT_LIMITS_BY_INCOME,
    MFA_CODE_LENGTH,
    MFA_CODE_EXPIRY_HOURS,
    CARD_DELIVERY_TIMEFRAME,
    card_product_to_dict,
    get_tier_atm_benefits,
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
# CARD ELIGIBILITY EVALUATION TOOL
# ═══════════════════════════════════════════════════════════════════


class EvaluateCardEligibilityArgs(TypedDict, total=False):
    """Input schema for evaluate_card_eligibility."""
    client_id: str
    card_product_id: str


async def evaluate_card_eligibility(args: EvaluateCardEligibilityArgs) -> Dict[str, Any]:
    """
    Evaluate if a customer is pre-approved or eligible for a specific credit card.
    
    This simulates the bank's underwriting decision by checking:
    1. Customer tier (Platinum/Diamond = high trust, likely pre-approved)
    2. Account tenure (longer = more trust)
    3. Income bracket vs card tier match
    4. Existing cards and payment history
    5. Card-specific requirements
    
    Decision outcomes:
    - PRE_APPROVED: Customer can proceed directly to e-signature (fast track)
    - APPROVED_WITH_REVIEW: Approved but may get different terms
    - PENDING_VERIFICATION: Need additional information before approval
    - DECLINED: Not eligible for this card (suggest alternatives)
    
    Args:
        client_id: Unique customer identifier
        card_product_id: The card product being applied for
    
    Returns:
        Dict with eligibility_status, credit_limit, reasoning, and next_steps
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
            "🔍 Evaluating card eligibility | client_id=%s card=%s",
            client_id, card_product_id
        )
        
        # Get card product details
        card_product = CARD_PRODUCTS.get(card_product_id)
        if not card_product:
            return _json(False, f"Unknown card product: {card_product_id}")
        
        # Fetch customer data from Cosmos DB
        try:
            cosmos = get_banking_cosmos_manager()
            customer_data = await asyncio.to_thread(
                cosmos.read_document,
                {"client_id": client_id}
            )
        except Exception as db_error:
            logger.error(f"❌ Database error during eligibility check: {db_error}")
            return _json(False, "Unable to retrieve customer information for eligibility check.")
        
        if not customer_data:
            logger.error(f"❌ Customer not found: {client_id}")
            return _json(
                False,
                "Customer not found. New customers need to complete identity verification first.",
                eligibility_status="IDENTITY_REQUIRED",
                next_step="verify_identity"
            )
        
        # Extract customer profile for evaluation
        customer_intelligence = customer_data.get("customer_intelligence", {})
        relationship_context = customer_intelligence.get("relationship_context", {})
        bank_profile = customer_intelligence.get("bank_profile", {})
        employment = customer_intelligence.get("employment", {})
        
        customer_tier = relationship_context.get("relationship_tier", "Standard")
        account_tenure_years = bank_profile.get("accountTenureYears", 0)
        income_bracket = employment.get("income_bracket", employment.get("incomeBand", "unknown"))
        existing_cards = bank_profile.get("cards", [])
        
        # Normalize tier for comparison
        tier_lower = customer_tier.lower()
        
        # ═══════════════════════════════════════════════════════════════════
        # UNDERWRITING LOGIC - Simulate bank's credit decision
        # ═══════════════════════════════════════════════════════════════════
        
        eligibility_score = 0
        approval_reasons = []
        concern_reasons = []
        
        # 1. TIER EVALUATION (max 40 points)
        if "diamond" in tier_lower:
            eligibility_score += 40
            approval_reasons.append("Diamond tier - highest relationship level")
        elif "platinum" in tier_lower and "honors" in tier_lower:
            eligibility_score += 38
            approval_reasons.append("Platinum Honors tier - excellent relationship")
        elif "platinum" in tier_lower:
            eligibility_score += 35
            approval_reasons.append("Platinum tier - strong relationship")
        elif "gold" in tier_lower:
            eligibility_score += 25
            approval_reasons.append("Gold tier member")
        else:
            eligibility_score += 10
            concern_reasons.append("Standard tier - limited relationship history")
        
        # 2. TENURE EVALUATION (max 25 points)
        if account_tenure_years >= 10:
            eligibility_score += 25
            approval_reasons.append(f"{account_tenure_years}+ years as customer - long-standing relationship")
        elif account_tenure_years >= 5:
            eligibility_score += 20
            approval_reasons.append(f"{account_tenure_years} years as customer")
        elif account_tenure_years >= 2:
            eligibility_score += 12
            approval_reasons.append(f"{account_tenure_years} years as customer")
        elif account_tenure_years >= 1:
            eligibility_score += 5
            concern_reasons.append("Relatively new customer (under 2 years)")
        else:
            eligibility_score += 0
            concern_reasons.append("New customer - limited account history")
        
        # 3. INCOME EVALUATION (max 20 points)
        income_lower = income_bracket.lower() if income_bracket else "unknown"
        if income_lower in ["high", "very_high", "150k+", "100k-150k"]:
            eligibility_score += 20
            approval_reasons.append("Strong income level")
        elif income_lower in ["medium", "medium_high", "75k-100k", "50k-75k"]:
            eligibility_score += 12
            approval_reasons.append("Adequate income level")
        elif income_lower in ["low", "25k-50k"]:
            eligibility_score += 5
            concern_reasons.append("Income may limit credit availability")
        else:
            eligibility_score += 8  # Unknown = assume medium
            concern_reasons.append("Income not verified")
        
        # 4. EXISTING RELATIONSHIP (max 15 points)
        if len(existing_cards) > 0:
            eligibility_score += 15
            approval_reasons.append(f"Existing cardholder ({len(existing_cards)} card(s)) - payment history on file")
        else:
            eligibility_score += 0
            concern_reasons.append("No existing credit cards with us")
        
        # 5. CARD-SPECIFIC REQUIREMENTS
        is_premium_card = card_product.annual_fee > 0 or "premium" in card_product.name.lower()
        
        if is_premium_card:
            # Premium cards have stricter requirements
            if "platinum" not in tier_lower and "diamond" not in tier_lower:
                eligibility_score -= 10
                concern_reasons.append("Premium card typically requires Platinum tier or higher")
            if income_lower in ["low", "unknown"]:
                eligibility_score -= 5
                concern_reasons.append("Premium card benefits best utilized with higher income")
        
        # ═══════════════════════════════════════════════════════════════════
        # DETERMINE ELIGIBILITY STATUS
        # ═══════════════════════════════════════════════════════════════════
        
        # Calculate credit limit based on score and income
        if eligibility_score >= 80:
            base_limit = CREDIT_LIMITS_BY_INCOME.get("high", 15000)
        elif eligibility_score >= 60:
            base_limit = CREDIT_LIMITS_BY_INCOME.get("medium", 8500)
        else:
            base_limit = CREDIT_LIMITS_BY_INCOME.get("low", 5000)
        
        # Adjust for income
        if income_lower in ["high", "very_high", "150k+"]:
            credit_limit = int(base_limit * 1.5)
        elif income_lower in ["medium_high", "100k-150k"]:
            credit_limit = int(base_limit * 1.2)
        elif income_lower in ["low"]:
            credit_limit = int(base_limit * 0.7)
        else:
            credit_limit = base_limit
        
        # Determine status
        if eligibility_score >= 75:
            eligibility_status = "PRE_APPROVED"
            status_message = "Great news! You're pre-approved for this card."
            next_step = "send_card_agreement"
            can_proceed = True
        elif eligibility_score >= 55:
            eligibility_status = "APPROVED_WITH_REVIEW"
            status_message = "You're approved! I just need to send you the agreement to review and sign."
            next_step = "send_card_agreement"
            can_proceed = True
        elif eligibility_score >= 40:
            eligibility_status = "PENDING_VERIFICATION"
            status_message = "We need a bit more information to complete your application. Let me verify a few details."
            next_step = "request_income_verification"
            can_proceed = False
        else:
            eligibility_status = "DECLINED"
            status_message = "I'm sorry, but we're unable to approve this card at this time. Let me suggest some alternatives that might be a better fit."
            next_step = "suggest_alternatives"
            can_proceed = False
        
        # Build alternative suggestions for declined/pending
        alternative_cards = []
        if eligibility_status in ["DECLINED", "PENDING_VERIFICATION"]:
            # Suggest easier-to-get cards
            for pid, product in CARD_PRODUCTS.items():
                if product.annual_fee == 0 and pid != card_product_id:
                    alternative_cards.append({
                        "product_id": pid,
                        "name": product.name,
                        "reason": "No annual fee, easier approval"
                    })
                    if len(alternative_cards) >= 2:
                        break
        
        logger.info(
            "✅ Eligibility evaluated | client_id=%s card=%s score=%d status=%s limit=$%d",
            client_id, card_product_id, eligibility_score, eligibility_status, credit_limit
        )
        
        return _json(
            True,
            status_message,
            eligibility_status=eligibility_status,
            eligibility_score=eligibility_score,
            credit_limit=credit_limit,
            card_name=card_product.name,
            card_product_id=card_product_id,
            can_proceed_to_agreement=can_proceed,
            next_step=next_step,
            approval_reasons=approval_reasons,
            concern_reasons=concern_reasons,
            alternative_cards=alternative_cards if alternative_cards else None,
            customer_tier=customer_tier,
            account_tenure_years=account_tenure_years
        )
    
    except Exception as exc:
        logger.error("Eligibility evaluation failed: %s", exc, exc_info=True)
        return _json(False, "Unable to evaluate eligibility at this time.")


# ═══════════════════════════════════════════════════════════════════
# E-SIGNATURE WORKFLOW TOOLS
# ═══════════════════════════════════════════════════════════════════


class SendCardAgreementArgs(TypedDict, total=False):
    """Input schema for send_card_agreement."""
    client_id: str
    card_product_id: str
    card_name: str
    eligibility_credit_limit: int


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
        eligibility_credit_limit = args.get("eligibility_credit_limit")  # From evaluate_card_eligibility
        
        if not client_id or not card_product_id:
            return _json(False, "client_id and card_product_id are required.")
        
        # Warn if credit limit not provided (will cause inconsistency later)
        if eligibility_credit_limit is None:
            logger.warning(
                "⚠️ CONSISTENCY ISSUE: send_card_agreement called WITHOUT eligibility_credit_limit. "
                "Final approval will recalculate credit limit and may differ from eligibility estimate. "
                "Client: %s, Card: %s",
                client_id, card_product_id
            )
        
        logger.info(
            "📧 Sending card agreement | client_id=%s card=%s eligible_limit=%s",
            client_id, card_product_id, eligibility_credit_limit
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
            "eligibility_credit_limit": eligibility_credit_limit,  # Store for finalize step
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
            sessions = await asyncio.to_thread(
                esign_cosmos.query_documents,
                {
                    "client_id": client_id,
                    "verification_code": verification_code,
                    "verified": False
                }
            )
            
            # Get the first matching session (should only be one)
            session_data = sessions[0] if sessions and len(sessions) > 0 else None
        except Exception as db_error:
            logger.error(f"❌ Database error during verification lookup: {db_error}", exc_info=True)
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
        
        # Retrieve credit limit from e-signature session (set during eligibility check)
        credit_limit = None
        try:
            esign_cosmos = get_esign_sessions_manager()
            # Find most recent verified session for this client + card
            # Use query instead of read_document since we're filtering by multiple fields
            sessions = await asyncio.to_thread(
                esign_cosmos.query_documents,
                {
                    "client_id": client_id,
                    "card_product_id": card_product_id,
                    "verified": True
                }
            )
            
            # Get the most recent session (sort by verified_at descending)
            if sessions and len(sessions) > 0:
                # Sort by verified_at to get most recent
                sorted_sessions = sorted(
                    sessions,
                    key=lambda x: x.get("verified_at", ""),
                    reverse=True
                )
                session_data = sorted_sessions[0]
                
                if "eligibility_credit_limit" in session_data and session_data["eligibility_credit_limit"]:
                    credit_limit = session_data["eligibility_credit_limit"]
                    logger.info(f"✅ Using eligibility credit limit from session: ${credit_limit}")
                else:
                    logger.warning(f"⚠️ Session found but no eligibility_credit_limit stored (value: {session_data.get('eligibility_credit_limit')})")
            else:
                logger.warning(f"⚠️ No verified session found for client_id={client_id}, card={card_product_id}")
        except Exception as session_error:
            logger.warning(f"⚠️ Could not retrieve eligibility session: {session_error}", exc_info=True)
        
        # Fallback: If no eligibility session found, calculate based on customer profile
        if credit_limit is None:
            bank_profile = customer_data.get("customer_intelligence", {}).get("bank_profile", {})
            income_band = customer_data.get("customer_intelligence", {}).get("employment", {}).get("incomeBand", "medium")
            
            # Calculate credit limit based on profile from constants
            credit_limit = CREDIT_LIMITS_BY_INCOME.get(income_band, CREDIT_LIMITS_BY_INCOME["medium"])
            logger.warning(f"⚠️ No eligibility session found, using income-based credit limit: ${credit_limit} (income_band={income_band})")
        
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
