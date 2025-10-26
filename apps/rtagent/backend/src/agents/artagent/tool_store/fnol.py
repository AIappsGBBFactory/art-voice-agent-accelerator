from __future__ import annotations

import asyncio
import os
import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from apps.rtagent.backend.src.agents.artagent.tool_store.functions_helper import _json
from utils.ml_logging import get_logger

# Import reusable ACS services
from src.acs import EmailService, EmailTemplates

log = get_logger("fnol_tools_min")

# ──────────────────────────────────────────────────────────────────────────────
# Mock DBs
# ──────────────────────────────────────────────────────────────────────────────
policyholders_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {"policy_id": "POL-A10001", "zip": "60601"},
    "Amelia Johnson": {"policy_id": "POL-B20417", "zip": "60601"},
    "Carlos Rivera": {"policy_id": "POL-C88230", "zip": "77002"},
}

# Email database mapping policyholder names to email addresses
policyholders_emails: Dict[str, str] = {
    "Alice Brown": "pablosal@microsoft.com",  # Real email for testing
    "Amelia Johnson": "amelia.johnson@mockinsurance.com",  # Mock email
    "Carlos Rivera": "carlos.rivera@mockinsurance.com",  # Mock email
}

claims_db: List[Dict[str, Any]] = []


# ──────────────────────────────────────────────────────────────────────────────
# TypedDict models
# ──────────────────────────────────────────────────────────────────────────────
class LossLocation(TypedDict, total=False):
    street: str
    city: str
    state: str
    zipcode: str


class PassengerInfo(TypedDict, total=False):
    name: str
    relationship: str


class InjuryAssessment(TypedDict, total=False):
    injured: bool
    details: Optional[str]


class VehicleDetails(TypedDict, total=False):
    make: str
    model: str
    year: str
    policy_id: str


class ClaimIntakeFull(TypedDict, total=False):
    caller_name: str
    driver_name: str
    driver_relationship: str
    vehicle_details: VehicleDetails
    number_of_vehicles_involved: int
    incident_description: str
    loss_date: str
    loss_time: str
    loss_location: LossLocation
    vehicle_drivable: bool
    passenger_information: Optional[List[PassengerInfo]]  # ← now Optional
    injury_assessment: InjuryAssessment
    trip_purpose: str
    date_reported: str  # YYYY-MM-DD (auto-filled)
    location_description: Optional[str]


class EscalateArgs(TypedDict):
    reason: str
    caller_name: str
    policy_id: str


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _new_claim_id() -> str:
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"CLA-{datetime.utcnow().year}-{rand}"


_REQUIRED_SLOTS = [
    "caller_name",
    "driver_name",
    "driver_relationship",
    "vehicle_details.make",
    "vehicle_details.model",
    "vehicle_details.year",
    "vehicle_details.policy_id",
    "number_of_vehicles_involved",
    "incident_description",
    "loss_date",
    "loss_time",
    "loss_location.street",
    "loss_location.city",
    "loss_location.state",
    "loss_location.zipcode",
    "vehicle_drivable",
    "injury_assessment.injured",
    "injury_assessment.details",
    "trip_purpose",
]


def _validate(data: ClaimIntakeFull) -> tuple[bool, str]:
    """Return (ok, message).  Message lists missing fields if any."""
    missing: List[str] = []

    # Field-presence walk
    for field in _REQUIRED_SLOTS:
        ptr = data
        for part in field.split("."):
            if isinstance(ptr, dict) and part in ptr:
                ptr = ptr[part]
            else:
                missing.append(field)
                break

    if "passenger_information" not in data or data["passenger_information"] in (
        None,
        [],
    ):
        data["passenger_information"] = []
    else:
        for i, pax in enumerate(data["passenger_information"]):
            if not pax.get("name") or not pax.get("relationship"):
                missing.append(f"passenger_information[{i}]")

    if missing:
        return False, "Missing: " + ", ".join(sorted(set(missing)))

    return True, ""








async def _send_claim_confirmation_email(claim_data: ClaimIntakeFull, claim_id: str) -> Dict[str, Any]:
    """Send confirmation email to the policyholder using the reusable email service."""
    try:
        caller_name = claim_data.get("caller_name", "Unknown")
        email_address = policyholders_emails.get(caller_name)
        
        if not email_address:
            log.warning("No email address found for caller: %s", caller_name)
            return {
                "email_sent": False,
                "email_status": f"No email address found for {caller_name}",
                "email_address": None
            }
        
        # Create email service instance
        email_service = EmailService()
        
        if not email_service.is_configured():
            log.error("Email service not configured")
            return {
                "email_sent": False,
                "email_status": "Email service not configured",
                "email_address": email_address
            }
        
        # Use the reusable email template
        subject, plain_text_body, html_body = EmailTemplates.create_claim_confirmation_email(
            claim_data, claim_id, caller_name
        )
        
        # Send email using the reusable service
        email_result = await email_service.send_email_async(
            to_email=email_address,
            subject=subject,
            plain_text_body=plain_text_body,
            html_body=html_body
        )
        
        if email_result.get("success"):
            return {
                "email_sent": True,
                "email_status": f"Email sent successfully via {email_result.get('service', 'unknown service')}",
                "email_address": email_address,
                "email_subject": subject,
                "message_id": email_result.get("message_id"),
                "service_used": email_result.get("service")
            }
        else:
            return {
                "email_sent": False,
                "email_status": f"Email sending failed: {email_result.get('error', 'Unknown error')}",
                "email_address": email_address
            }
        
    except Exception as exc:
        log.error("Failed to send confirmation email: %s", exc, exc_info=True)
        return {
            "email_sent": False,
            "email_status": f"Email sending failed: {str(exc)}",
            "email_address": email_address if 'email_address' in locals() else None
        }


def _send_claim_email_callback(result: Dict[str, Any]) -> None:
    """Callback function to handle email sending results."""
    if result.get("success"):
        log.info("📧 Background claim email sent successfully: %s", result.get("message_id"))
    else:
        log.warning("📧 Background claim email failed: %s", result.get("error"))


async def record_fnol(args: ClaimIntakeFull) -> Dict[str, Any]:
    """Store the claim if validation passes; else enumerate missing fields."""
    # Input type validation to prevent 400 errors
    if not isinstance(args, dict):
        log.error("Invalid args type: %s. Expected dict.", type(args))
        return {
            "claim_success": False,
            "missing_data": "Invalid request format. Please provide claim details as a structured object.",
        }

    try:
        args.setdefault("date_reported", datetime.now(timezone.utc).date().isoformat())

        ok, msg = _validate(args)
        if not ok:
            return {
                "claim_success": False,
                "missing_data": f"{msg}.",
            }

        claim_id = _new_claim_id()
        claims_db.append({**args, "claim_id": claim_id, "status": "OPEN"})
        log.info(
            "📄 FNOL recorded (%s) for %s", claim_id, args.get("caller_name", "unknown")
        )

        # Return immediately to the agent - don't wait for email
        response = {
            "claim_success": True,
            "claim_id": claim_id,
            "claim_data": {**args},
            "email_confirmation": {
                "email_sent": "pending",
                "email_status": "Email confirmation will be sent in background",
                "email_address": policyholders_emails.get(args.get("caller_name", ""), "unknown")
            }
        }

        # Start background email sending using the reusable email service
        try:
            caller_name = args.get("caller_name", "Unknown")
            email_address = policyholders_emails.get(caller_name)
            
            # Create email service instance
            email_service = EmailService()
            
            if email_address and email_service.is_configured():
                # Generate email content using the template
                subject, plain_text_body, html_body = EmailTemplates.create_claim_confirmation_email(
                    args, claim_id, caller_name
                )
                
                # Send email in background
                email_service.send_email_background(
                    to_email=email_address, 
                    subject=subject, 
                    plain_text_body=plain_text_body, 
                    html_body=html_body,
                    callback=_send_claim_email_callback
                )
                log.info("📧 Email sending started in background thread")
            else:
                log.warning("📧 Email not sent - address not found or service not configured")
        except Exception as exc:
            log.error("Failed to start background email: %s", exc)

        return response
    except Exception as exc:
        # Catch all exceptions to prevent 400 errors
        log.error("FNOL recording failed: %s", exc, exc_info=True)
        return {
            "claim_success": False,
            "missing_data": "Technical error occurred. Please try again or contact support.",
        }
