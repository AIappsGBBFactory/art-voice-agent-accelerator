from __future__ import annotations

import asyncio
import os
import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from src.utils.ml_logging import get_logger

# Email service imports
try:
    from azure.communication.email import EmailClient
    from azure.core.credentials import AzureKeyCredential
    AZURE_EMAIL_AVAILABLE = True
except ImportError:
    AZURE_EMAIL_AVAILABLE = False

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


async def _send_with_azure_email(email_address: str, subject: str, plain_text_body: str, html_body: str) -> Dict[str, Any]:
    """Send email using Azure Communication Services Email."""
    try:
        # Get configuration from environment variables
        connection_string = os.getenv("AZURE_COMMUNICATION_EMAIL_CONNECTION_STRING")
        sender_address = os.getenv("AZURE_EMAIL_SENDER_ADDRESS")
        
        if not connection_string or not sender_address:
            return {
                "success": False,
                "error": "Azure Email configuration not found in environment variables"
            }
        
        # Create email client using the exact same pattern
        client = EmailClient.from_connection_string(connection_string)
        
        # Prepare email message with both plain text and HTML
        message = {
            "senderAddress": sender_address,
            "recipients": {
                "to": [{"address": email_address}]
            },
            "content": {
                "subject": subject,
                "plainText": plain_text_body,
                "html": html_body
            }
        }
        
        # Send email using the exact same pattern
        poller = client.begin_send(message)
        result = poller.result()
        
        # Extract message ID from result - Azure returns it as 'id' not 'message_id'
        message_id = getattr(result, 'id', None) or getattr(result, 'message_id', 'unknown')
        
        log.info("📧 Azure Email sent successfully to %s, message ID: %s", email_address, message_id)
        return {
            "success": True,
            "message_id": message_id,
            "service": "Azure Communication Services Email"
        }
        
    except Exception as exc:
        log.error("Azure Email sending failed: %s", exc)
        return {
            "success": False,
            "error": f"Azure Email error: {str(exc)}"
        }





async def _send_claim_confirmation_email(claim_data: ClaimIntakeFull, claim_id: str) -> Dict[str, Any]:
    """Send confirmation email to the policyholder with claim details using real email services."""
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
        
        # Create email content with claim details
        vehicle_details = claim_data.get("vehicle_details", {})
        loss_location = claim_data.get("loss_location", {})
        injury_assessment = claim_data.get("injury_assessment", {})
        
        email_subject = f"Claim Confirmation - {claim_id}"
        
        # Professional plain text version
        plain_text_body = f"""Dear {caller_name},

Your First Notice of Loss (FNOL) claim has been successfully recorded and assigned the following reference number:

CLAIM ID: {claim_id}

═══════════════════════════════════════════════════════════════════
CLAIM SUMMARY
═══════════════════════════════════════════════════════════════════

Date Reported: {claim_data.get('date_reported', 'N/A')}
Loss Date: {claim_data.get('loss_date', 'N/A')} at {claim_data.get('loss_time', 'N/A')}

VEHICLE INFORMATION:
• Vehicle: {vehicle_details.get('make', 'N/A')} {vehicle_details.get('model', 'N/A')} ({vehicle_details.get('year', 'N/A')})
• Policy ID: {vehicle_details.get('policy_id', 'N/A')}
• Vehicle Condition: {'Drivable' if claim_data.get('vehicle_drivable') else 'Not Drivable'}

INCIDENT DETAILS:
• Description: {claim_data.get('incident_description', 'N/A')}
• Vehicles Involved: {claim_data.get('number_of_vehicles_involved', 'N/A')}
• Trip Purpose: {claim_data.get('trip_purpose', 'N/A')}

LOCATION:
• Address: {loss_location.get('street', 'N/A')}
• City/State: {loss_location.get('city', 'N/A')}, {loss_location.get('state', 'N/A')} {loss_location.get('zipcode', 'N/A')}

INJURY ASSESSMENT:
• Injuries Reported: {'Yes' if injury_assessment.get('injured') else 'No'}
• Details: {injury_assessment.get('details', 'None reported')}

DRIVER INFORMATION:
• Driver Name: {claim_data.get('driver_name', 'N/A')}
• Relationship to Policyholder: {claim_data.get('driver_relationship', 'N/A')}

═══════════════════════════════════════════════════════════════════
NEXT STEPS
═══════════════════════════════════════════════════════════════════

1. A claims adjuster will contact you within 24-48 hours
2. Please keep this claim number for all future communications: {claim_id}
3. If you need immediate assistance, please call our 24/7 claims hotline

Thank you for choosing ARTVoice Insurance. We're here to help you through this process.

Best regards,
ARTVoice Insurance Claims Department
"""

        # Professional HTML version (using string concatenation to avoid f-string complexity)
        vehicle_condition_class = ' highlight' if not claim_data.get('vehicle_drivable') else ''
        vehicle_condition_text = 'Drivable' if claim_data.get('vehicle_drivable') else 'Not Drivable'
        injury_class = ' highlight' if injury_assessment.get('injured') else ''
        injury_text = 'Yes' if injury_assessment.get('injured') else 'No'
        injury_details_row = f'<div class="info-row"><span class="label">Details:</span><span class="value">{injury_assessment.get("details", "None reported")}</span></div>' if injury_assessment.get('details') else ''
        
        html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #0078d4, #106ebe); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
        .claim-id {{ font-size: 24px; font-weight: bold; background: rgba(255,255,255,0.2); padding: 10px; border-radius: 5px; margin: 10px 0; }}
        .content {{ padding: 20px; background: #f9f9f9; }}
        .section {{ background: white; margin: 15px 0; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .section h3 {{ color: #0078d4; margin-top: 0; border-bottom: 2px solid #0078d4; padding-bottom: 5px; }}
        .info-row {{ display: flex; justify-content: space-between; margin: 8px 0; padding: 5px 0; border-bottom: 1px solid #eee; }}
        .label {{ font-weight: bold; color: #555; }}
        .value {{ color: #333; }}
        .next-steps {{ background: #e8f4fd; border-left: 4px solid #0078d4; }}
        .footer {{ background: #333; color: white; padding: 15px; text-align: center; border-radius: 0 0 8px 8px; }}
        .highlight {{ background: #fff3cd; padding: 3px 6px; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ Claim Confirmation</h1>
        <div class="claim-id">CLAIM ID: {claim_id}</div>
        <p>Your First Notice of Loss has been successfully recorded</p>
    </div>
    
    <div class="content">
        <p>Dear <strong>{caller_name}</strong>,</p>
        <p>Thank you for reporting your claim. We have successfully recorded all the details and assigned your claim the reference number above.</p>
        
        <div class="section">
            <h3>📋 Claim Information</h3>
            <div class="info-row">
                <span class="label">Date Reported:</span>
                <span class="value">{claim_data.get('date_reported', 'N/A')}</span>
            </div>
            <div class="info-row">
                <span class="label">Loss Date & Time:</span>
                <span class="value">{claim_data.get('loss_date', 'N/A')} at {claim_data.get('loss_time', 'N/A')}</span>
            </div>
        </div>
        
        <div class="section">
            <h3>🚗 Vehicle Information</h3>
            <div class="info-row">
                <span class="label">Vehicle:</span>
                <span class="value">{vehicle_details.get('make', 'N/A')} {vehicle_details.get('model', 'N/A')} ({vehicle_details.get('year', 'N/A')})</span>
            </div>
            <div class="info-row">
                <span class="label">Policy ID:</span>
                <span class="value">{vehicle_details.get('policy_id', 'N/A')}</span>
            </div>
            <div class="info-row">
                <span class="label">Vehicle Condition:</span>
                <span class="value{vehicle_condition_class}">{vehicle_condition_text}</span>
            </div>
        </div>
        
        <div class="section">
            <h3>📍 Incident Details</h3>
            <div class="info-row">
                <span class="label">Description:</span>
                <span class="value">{claim_data.get('incident_description', 'N/A')}</span>
            </div>
            <div class="info-row">
                <span class="label">Vehicles Involved:</span>
                <span class="value">{claim_data.get('number_of_vehicles_involved', 'N/A')}</span>
            </div>
            <div class="info-row">
                <span class="label">Location:</span>
                <span class="value">{loss_location.get('street', 'N/A')}, {loss_location.get('city', 'N/A')}, {loss_location.get('state', 'N/A')} {loss_location.get('zipcode', 'N/A')}</span>
            </div>
        </div>
        
        <div class="section">
            <h3>🏥 Injury Assessment</h3>
            <div class="info-row">
                <span class="label">Injuries Reported:</span>
                <span class="value{injury_class}">{injury_text}</span>
            </div>
            {injury_details_row}
        </div>
        
        <div class="section next-steps">
            <h3>🎯 Next Steps</h3>
            <ol>
                <li><strong>Claims Adjuster Contact:</strong> You will be contacted within 24-48 hours</li>
                <li><strong>Reference Number:</strong> Please save this claim ID: <span class="highlight">{claim_id}</span></li>
                <li><strong>24/7 Support:</strong> Contact our claims hotline for immediate assistance</li>
            </ol>
        </div>
    </div>
    
    <div class="footer">
        <p><strong>ARTVoice Insurance Claims Department</strong></p>
        <p>We're here to help you through this process</p>
    </div>
</body>
</html>"""
        
        # Send email via Azure Communication Services Email
        email_result = None
        if AZURE_EMAIL_AVAILABLE:
            log.info("Sending email via Azure Communication Services...")
            email_result = await _send_with_azure_email(email_address, email_subject, plain_text_body, html_body)
        else:
            log.error("Azure Communication Services Email not available")
            return {
                "email_sent": False,
                "email_status": "Azure Communication Services Email not available",
                "email_address": email_address
            }
        
        if email_result and email_result.get("success"):
            return {
                "email_sent": True,
                "email_status": f"Email sent successfully via {email_result.get('service', 'unknown service')}",
                "email_address": email_address,
                "email_subject": email_subject,
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


def _send_email_background(claim_data: ClaimIntakeFull, claim_id: str) -> None:
    """Send email in background without blocking the main response."""
    try:
        # Create a new event loop for the background task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the email sending coroutine
        result = loop.run_until_complete(_send_claim_confirmation_email(claim_data, claim_id))
        
        # Log the result for monitoring
        if result.get("email_sent"):
            log.info("📧 Background email sent successfully: %s", result.get("email_status"))
        else:
            log.warning("📧 Background email failed: %s", result.get("email_status"))
            
    except Exception as exc:
        log.error("Background email task failed: %s", exc, exc_info=True)
    finally:
        loop.close()


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

        # Start background email sending
        try:
            import threading
            email_thread = threading.Thread(
                target=_send_email_background, 
                args=(args, claim_id),
                daemon=True  
            )
            email_thread.start()
            log.info("📧 Email sending started in background thread")
        except Exception as exc:
            log.error("Failed to start background email thread: %s", exc)

        return response
    except Exception as exc:
        # Catch all exceptions to prevent 400 errors
        log.error("FNOL recording failed: %s", exc, exc_info=True)
        return {
            "claim_success": False,
            "missing_data": "Technical error occurred. Please try again or contact support.",
        }

