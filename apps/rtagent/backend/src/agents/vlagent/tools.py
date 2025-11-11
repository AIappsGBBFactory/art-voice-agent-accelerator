# tools.py
"""
🎯 CENTRALIZED Tool Management for Azure AI VoiceLive Agents

All tool functionality (schemas, implementations, execution) in ONE place.

Benefits:
✅ Single file to add/modify any tool
✅ Easy to see all available tools  
✅ Both handoff AND business tools together
✅ Consistent error handling
✅ Simpler testing and maintenance
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, Any, List, Union
from azure.ai.voicelive.models import FunctionTool
import asyncio

# Add project root to path for utils and src imports
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.ml_logging import get_logger

logger = get_logger("voicelive.tools")

# Cosmos DB manager import
try:
    from src.cosmosdb.manager import CosmosDBMongoCoreManager
except ImportError:
    logger.warning("CosmosDB manager not available - authentication will use mock data")
    CosmosDBMongoCoreManager = None

# =============================================================================
# Tool Schema Registry
# =============================================================================
# Defines the interface (schema) for each tool that agents can use.
# These are sent to the Azure AI model so it knows what tools are available.
# =============================================================================

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ===== HANDOFF TOOLS =====
    "handoff_to_scheduler": {
        "name": "handoff_to_scheduler",
        "description": "Transfer caller to Appointment Scheduling agent for booking, rescheduling, or canceling appointments.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the user needs scheduling (e.g., 'book cardiology follow-up')"},
                "preferred_window": {"type": "string", "description": "Optional: time preference (e.g., 'next week mornings')"},
                "department": {"type": "string", "description": "Optional: specialty or department"},
                "details": {"type": "string", "description": "Short context to carry over"},
            },
            "required": ["reason"],
        },
    },
    "handoff_to_insurance": {
        "name": "handoff_to_insurance",
        "description": "Transfer caller to Insurance & Benefits agent for coverage, copays, deductibles, claims, or medications.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the user needs insurance help"},
                "topic": {"type": "string", "description": "Optional: benefits|eligibility|copay|deductible|claim|meds"},
                "details": {"type": "string", "description": "Short context"},
            },
            "required": ["reason"],
        },
    },
    
    # ===== SCHEDULING TOOLS =====
    "check_availability": {
        "name": "check_availability",
        "description": "Check available appointment slots for a department/specialty.",
        "parameters": {
            "type": "object",
            "properties": {
                "department": {"type": "string", "description": "Department or specialty (e.g., 'Cardiology', 'Primary Care')"},
                "window": {"type": "string", "description": "Time window (e.g., 'next week', 'this Friday', 'mornings')"},
                "provider": {"type": "string", "description": "Optional: specific provider name"},
            },
            "required": ["department"],
        },
    },
    "schedule_appointment": {
        "name": "schedule_appointment",
        "description": "Book an appointment for the patient.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient identifier"},
                "department": {"type": "string", "description": "Department or specialty"},
                "datetime": {"type": "string", "description": "ISO datetime for appointment"},
                "reason": {"type": "string", "description": "Reason for visit"},
            },
            "required": ["patient_id", "department", "datetime", "reason"],
        },
    },
    "set_reminder": {
        "name": "set_reminder",
        "description": "Set appointment reminder via SMS or email.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "datetime": {"type": "string", "description": "Appointment datetime"},
                "channel": {"type": "string", "description": "Delivery method: 'sms' or 'email'"},
            },
            "required": ["patient_id", "datetime", "channel"],
        },
    },
    
    # ===== INSURANCE & BENEFITS TOOLS =====
    "insurance_eligibility": {
        "name": "insurance_eligibility",
        "description": "Check patient insurance eligibility and coverage status.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient identifier"},
                "payer": {"type": "string", "description": "Insurance payer/carrier name"},
            },
            "required": ["patient_id"],
        },
    },
    "benefits_lookup": {
        "name": "benefits_lookup",
        "description": "Look up specific benefit details: deductible, copay, out-of-pocket max, coinsurance.",
        "parameters": {
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "Insurance member ID"},
                "topic": {"type": "string", "description": "Type: deductible|copay|oop|coinsurance"},
            },
            "required": ["member_id", "topic"],
        },
    },
    "list_medications": {
        "name": "list_medications",
        "description": "List patient's active medications with dosages and last fill dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient identifier"},
            },
            "required": ["patient_id"],
        },
    },
    "refill_prescription": {
        "name": "refill_prescription",
        "description": "Submit prescription refill request for patient.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "Patient identifier"},
                "medication": {"type": "string", "description": "Medication name and dosage (e.g., 'Lisinopril 10mg')"},
            },
            "required": ["patient_id", "medication"],
        },
    },
    
    # ===== AUTHENTICATION =====
    "authenticate_caller": {
        "name": "authenticate_caller",
        "description": "Authenticate caller by verifying full name, ZIP code, and last-4 digits of SSN, policy number, phone, or claim number.",
        "parameters": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string", "description": "Caller's full name (e.g., 'Jane Doe')"},
                "zip_code": {"type": "string", "description": "5-digit ZIP code for verification"},
                "last4_ssn": {"type": "string", "description": "Last 4 digits of Social Security Number"},
                "last4_policy": {"type": "string", "description": "Last 4 digits of policy number"},
                "last4_phone": {"type": "string", "description": "Last 4 digits of phone number"},
                "last4_claim": {"type": "string", "description": "Last 4 digits of claim number"},
                "intent": {"type": "string", "description": "Caller intent: 'scheduling' or 'insurance'"},
                "claim_intent": {"type": "string", "description": "Specific claim intent if applicable"},
                "attempt": {"type": "integer", "description": "Authentication attempt counter (default: 1)"}
            },
            "required": ["full_name"]
        },
    },
    
    # ===== ESCALATION =====
    "escalate_emergency": {
        "name": "escalate_emergency",
        "description": "Escalate immediately to emergency services for medical emergencies (chest pain, stroke symptoms, severe injury).",
        "parameters": {"type": "object", "properties": {}},
    },
    "escalate_human": {
        "name": "escalate_human",
        "description": "Transfer caller to a live human agent for complex issues or patient request.",
        "parameters": {"type": "object", "properties": {}},
    },
}

def build_function_tools(tools_cfg: List[Union[str, Dict[str, Any]]] | None) -> List[FunctionTool]:
    """Build FunctionTool objects from agent YAML tool configuration."""
    tools: List[FunctionTool] = []
    for entry in tools_cfg or []:
        spec = TOOL_REGISTRY[entry] if isinstance(entry, str) else entry
        name = spec.get("name") or spec.get("function", {}).get("name")
        if not name:
            raise ValueError("Tool spec missing 'name'")
        tools.append(FunctionTool(
            name=name,
            description=spec.get("description", ""),
            parameters=spec.get("parameters", {"type": "object", "properties": {}}),
        ))
    return tools


# =============================================================================
# Tool Implementation Functions
# =============================================================================
# These are the actual implementations called when the model uses tools.
# 
# NOTE: In Azure AI VoiceLive architecture:
# - handoff_* tools → Handled by orchestrator (agent switching)
# - Other tools → Implemented here and called via response.function_call_output
# =============================================================================

# =============================================================================

# Cosmos DB manager helper
def _get_cosmos_manager():
    return CosmosDBMongoCoreManager(
        database_name="voice_agent_db",
        collection_name="policyholders"
    )

async def authenticate_caller(
    full_name: str = None,
    zip_code: str = None,
    last4_ssn: str = None,
    last4_policy: str = None,
    last4_phone: str = None,
    last4_claim: str = None,
    intent: str = None,
    claim_intent: str = None,
    attempt: int = 1
) -> Dict[str, Any]:
    """
    Authenticate caller by verifying identity against Cosmos DB.
    """
    auth_logger = get_logger("voicelive.auth")
    full_name = (full_name or "").strip().title()
    zip_code = (zip_code or "").strip()
    last4_ssn = (last4_ssn or "").strip()
    last4_policy = (last4_policy or "").strip()
    last4_phone = (last4_phone or "").strip()
    last4_claim = (last4_claim or "").strip()
    intent = (intent or "").strip()
    claim_intent = (claim_intent or "").strip()

    if not full_name:
        auth_logger.error("Auth failed: missing full_name (attempt %d)", attempt)
        return {
            "authenticated": False,
            "message": "Full name is required for authentication.",
            "policy_id": None,
            "caller_name": None,
            "attempt": attempt,
            "active_agent": "AutoAuth"
        }
    if not zip_code and not (last4_ssn or last4_policy or last4_phone or last4_claim):
        auth_logger.error("Auth failed: no verification data for %s (attempt %d)", full_name, attempt)
        return {
            "authenticated": False,
            "message": "Provide ZIP code or last-4 of SSN, policy, phone, or claim.",
            "policy_id": None,
            "caller_name": None,
            "attempt": attempt,
            "active_agent": "AutoAuth"
        }

    # Build query
    query = {"full_name": full_name}
    if zip_code:
        query["zip"] = zip_code
    or_clauses = []
    if last4_ssn:
        or_clauses.append({"ssn4": last4_ssn})
    if last4_policy:
        or_clauses.append({"policy4": last4_policy})
    if last4_phone:
        or_clauses.append({"phone4": last4_phone})
    if last4_claim:
        or_clauses.append({"claim4": last4_claim})
    if or_clauses:
        query["$or"] = or_clauses

    cosmos = _get_cosmos_manager()
    try:
        rec = await asyncio.to_thread(cosmos.read_document, query=query)
    except Exception as e:
        error_msg = str(e)
        if "firewall" in error_msg.lower():
            auth_logger.error("Cosmos DB firewall error for %s (attempt %d): %s", full_name, attempt, error_msg)
        else:
            auth_logger.error("Cosmos DB error for %s (attempt %d): %s", full_name, attempt, error_msg)
        return {
            "authenticated": False,
            "message": "Authentication service is currently unavailable. Please try again later.",
            "policy_id": None,
            "caller_name": None,
            "attempt": attempt,
            "active_agent": "AutoAuth",
            "error": "database_unavailable"
        }

    if rec and rec.get("policy_id"):
        auth_logger.info("Auth success for %s (policy %s, attempt %d)", full_name, rec["policy_id"], attempt)
        return {
            "authenticated": True,
            "message": f"Authentication successful for {full_name}.",
            "policy_id": rec["policy_id"],
            "caller_name": full_name,
            "attempt": attempt,
            "active_agent": "AutoAuth",
            "intent": intent,
            "claim_intent": claim_intent
        }
    else:
        auth_logger.info("Auth failed for %s (attempt %d)", full_name, attempt)
        return {
            "authenticated": False,
            "message": "Authentication failed: information does not match records.",
            "policy_id": None,
            "caller_name": None,
            "attempt": attempt,
            "active_agent": "AutoAuth"
        }


# ========================================
# 📅 SCHEDULING TOOLS
# ========================================

async def check_availability(
    department: str,
    preferred_window: str = None,
    provider_name: str = None
) -> Dict[str, Any]:
    """
    Check available appointment slots.
    
    📅 Returns open time slots for scheduling appointments.
    
    Parameters:
    -----------
    department : str
        Medical department/specialty (e.g., "primary_care", "cardiology")
    preferred_window : str, optional
        Preferred time window (e.g., "morning", "afternoon", "next_week")
    provider_name : str, optional
        Specific provider requested
    
    Production Implementation:
    --------------------------
    - Query scheduling system for open slots
    - Filter by department, provider, time window
    - Return available dates/times
    - Include provider names and locations
    """
    import time
    
    schedule_logger = get_logger("voicelive.scheduling")
    query_start = time.time()
    
    schedule_logger.info(
        "📅 [Scheduler Agent] Checking availability | "
        "Department: %s | Window: %s | Provider: %s",
        department or "any",
        preferred_window or "any",
        provider_name or "any"
    )
    
    # Mock available slots (in production, query scheduling system)
    mock_slots = [
        {"date": "2025-06-15", "time": "09:00 AM", "provider": "Dr. Smith"},
        {"date": "2025-06-15", "time": "02:30 PM", "provider": "Dr. Johnson"},
        {"date": "2025-06-16", "time": "10:00 AM", "provider": "Dr. Smith"},
    ]
    
    query_duration = time.time() - query_start
    schedule_logger.info(
        "✅ [Scheduler Agent] Found %d available slots | Duration: %.3fs",
        len(mock_slots), query_duration
    )
    
    return {
        "success": True,
        "department": department or "primary_care",
        "slots": mock_slots,
        "message": f"Found {len(mock_slots)} available appointments.",
        "active_agent": "Scheduler"
    }


async def schedule_appointment(
    patient_id: str,
    department: str,
    appointment_datetime: str,
    reason: str = None
) -> Dict[str, Any]:
    """
    Schedule a new appointment.
    
    📝 Books appointment and sends confirmation.
    
    Parameters:
    -----------
    patient_id : str
        Patient identifier
    department : str
        Medical department/specialty
    appointment_datetime : str
        Scheduled date/time (e.g., "2025-06-15 09:00")
    reason : str, optional
        Reason for visit
    
    Production Implementation:
    --------------------------
    - Create appointment in scheduling system
    - Send confirmation (SMS/email)
    - Add to provider's calendar
    - Set up pre-visit reminders
    """
    import time
    
    schedule_logger = get_logger("voicelive.scheduling")
    booking_start = time.time()
    
    # Generate confirmation number
    confirmation = f"APPT-{hash(appointment_datetime) % 100000:05d}"
    
    schedule_logger.info(
        "📝 [Scheduler Agent] Booking appointment | "
        "Confirmation#: %s | Patient: %s | Department: %s | DateTime: %s | Reason: %s",
        confirmation,
        patient_id,
        department or "primary_care",
        appointment_datetime,
        reason or "not specified"
    )
    
    booking_duration = time.time() - booking_start
    schedule_logger.info(
        "✅ [Scheduler Agent] Appointment booked | "
        "Confirmation#: %s | Duration: %.3fs",
        confirmation, booking_duration
    )
    
    return {
        "success": True,
        "confirmation_number": confirmation,
        "patient_id": patient_id,
        "department": department,
        "datetime": appointment_datetime,
        "reason": reason or "general checkup",
        "message": f"Appointment confirmed for {appointment_datetime}. Confirmation number: {confirmation}",
        "active_agent": "Scheduler"
    }


async def set_reminder(
    patient_id: str,
    reminder_datetime: str,
    channel: str = "sms"
) -> Dict[str, Any]:
    """
    Set appointment reminder.
    
    ⏰ Schedules reminder notification for appointment.
    
    Parameters:
    -----------
    patient_id : str
        Patient identifier
    reminder_datetime : str
        When to send reminder (e.g., "2025-06-14 18:00")
    channel : str, optional
        Notification channel ("sms", "email", "both")
    
    Production Implementation:
    --------------------------
    - Schedule reminder in notification system
    - Support multiple channels (SMS, email, push)
    - Include appointment details in reminder
    """
    import time
    
    schedule_logger = get_logger("voicelive.scheduling")
    reminder_start = time.time()
    
    reminder_id = f"REM-{hash(reminder_datetime) % 100000:05d}"
    
    schedule_logger.info(
        "⏰ [Scheduler Agent] Setting reminder | "
        "ID: %s | Patient: %s | DateTime: %s | Channel: %s",
        reminder_id, patient_id, reminder_datetime, channel
    )
    
    reminder_duration = time.time() - reminder_start
    schedule_logger.info(
        "✅ [Scheduler Agent] Reminder set | ID: %s | Duration: %.3fs",
        reminder_id, reminder_duration
    )
    
    return {
        "success": True,
        "reminder_id": reminder_id,
        "patient_id": patient_id,
        "datetime": reminder_datetime,
        "channel": channel,
        "message": f"Reminder scheduled via {channel} for {reminder_datetime}",
        "active_agent": "Scheduler"
    }


# ========================================
# 🏥 INSURANCE & BENEFITS TOOLS
# ========================================


async def insurance_eligibility(
    patient_id: str,
    payer_name: str = None
) -> Dict[str, Any]:
    """
    Check insurance eligibility and coverage status.
    
    🏥 Verifies active coverage and benefit details.
    
    Parameters:
    -----------
    patient_id : str
        Patient identifier
    payer_name : str, optional
        Insurance company name
    
    Production Implementation:
    --------------------------
    - Query insurance verification system
    - Return coverage status (active/inactive)
    - Show benefit periods
    - Display remaining benefits
    - Include copay/deductible info
    """
    import time
    
    insurance_logger = get_logger("voicelive.insurance")
    eligibility_start = time.time()
    
    insurance_logger.info(
        "🏥 [Insurance Agent] Checking eligibility | "
        "Patient: %s | Payer: %s",
        patient_id,
        payer_name or "on file"
    )
    
    # Mock eligibility response (in production, call insurance API)
    eligibility_duration = time.time() - eligibility_start
    insurance_logger.info(
        "✅ [Insurance Agent] Eligibility verified | "
        "Patient: %s | Duration: %.3fs",
        patient_id, eligibility_duration
    )
    
    return {
        "success": True,
        "patient_id": patient_id,
        "status": "active",
        "payer": payer_name or "Blue Cross Blue Shield",
        "coverage_start": "2025-01-01",
        "coverage_end": "2025-12-31",
        "message": "Insurance coverage is active and verified.",
        "active_agent": "Insurance"
    }


async def benefits_lookup(
    member_id: str,
    benefit_topic: str = None
) -> Dict[str, Any]:
    """
    Look up specific benefit information.
    
    💰 Returns copay, deductible, and coverage details.
    
    Parameters:
    -----------
    member_id : str
        Insurance member identifier
    benefit_topic : str, optional
        Specific benefit area (e.g., "copay", "deductible", "out_of_pocket_max")
    
    Production Implementation:
    --------------------------
    - Query benefits database
    - Return topic-specific details
    - Include remaining amounts (if applicable)
    - Show coverage percentages
    """
    import time
    
    insurance_logger = get_logger("voicelive.insurance")
    lookup_start = time.time()
    
    insurance_logger.info(
        "💰 [Insurance Agent] Benefits lookup | "
        "Member: %s | Topic: %s",
        member_id,
        benefit_topic or "general"
    )
    
    # Mock benefits data (in production, query benefits system)
    benefits_data = {
        "copay_primary_care": "$25",
        "copay_specialist": "$50",
        "deductible_annual": "$1,500",
        "deductible_met": "$800",
        "out_of_pocket_max": "$5,000",
        "coverage_percentage": "80/20 after deductible"
    }
    
    lookup_duration = time.time() - lookup_start
    insurance_logger.info(
        "✅ [Insurance Agent] Benefits retrieved | "
        "Member: %s | Duration: %.3fs",
        member_id, lookup_duration
    )
    
    return {
        "success": True,
        "member_id": member_id,
        "benefits": benefits_data,
        "message": "Benefit information retrieved successfully.",
        "active_agent": "Insurance"
    }


async def list_medications(patient_id: str) -> Dict[str, Any]:
    """
    List patient's current medications.
    
    💊 Returns medication list with dosages.
    
    Parameters:
    -----------
    patient_id : str
        Patient identifier
    
    Production Implementation:
    --------------------------
    - Query pharmacy/EHR system
    - Return active prescriptions
    - Include dosage and frequency
    - Show refill information
    """
    import time
    
    insurance_logger = get_logger("voicelive.insurance")
    med_start = time.time()
    
    insurance_logger.info(
        "� [Insurance Agent] Listing medications | Patient: %s",
        patient_id
    )
    
    # Mock medication list (in production, query pharmacy system)
    medications = [
        {"name": "Lisinopril", "dosage": "10mg", "frequency": "once daily", "refills": 2},
        {"name": "Metformin", "dosage": "500mg", "frequency": "twice daily", "refills": 1},
    ]
    
    med_duration = time.time() - med_start
    insurance_logger.info(
        "✅ [Insurance Agent] Medications listed | "
        "Patient: %s | Count: %d | Duration: %.3fs",
        patient_id, len(medications), med_duration
    )
    
    return {
        "success": True,
        "patient_id": patient_id,
        "medications": medications,
        "message": f"Found {len(medications)} active medications.",
        "active_agent": "Insurance"
    }


async def refill_prescription(
    patient_id: str,
    medication_name: str
) -> Dict[str, Any]:
    """
    Request prescription refill.
    
    🔄 Submits refill request to pharmacy.
    
    Parameters:
    -----------
    patient_id : str
        Patient identifier
    medication_name : str
        Name of medication to refill
    
    Production Implementation:
    --------------------------
    - Submit refill request to pharmacy
    - Check remaining refills
    - Send confirmation
    - Notify when ready for pickup
    """
    import time
    
    insurance_logger = get_logger("voicelive.insurance")
    refill_start = time.time()
    
    refill_id = f"RX-{hash(medication_name) % 100000:05d}"
    
    insurance_logger.info(
        "🔄 [Insurance Agent] Refill request | "
        "ID: %s | Patient: %s | Medication: %s",
        refill_id, patient_id, medication_name
    )
    
    refill_duration = time.time() - refill_start
    insurance_logger.info(
        "✅ [Insurance Agent] Refill requested | "
        "ID: %s | Duration: %.3fs",
        refill_id, refill_duration
    )
    
    return {
        "success": True,
        "refill_id": refill_id,
        "patient_id": patient_id,
        "medication": medication_name,
        "status": "processing",
        "estimated_ready": "Tomorrow at 2 PM",
        "message": f"Refill request {refill_id} submitted. Will be ready tomorrow at 2 PM.",
        "active_agent": "Insurance"
    }


# ========================================
# 🚨 ESCALATION TOOLS
# ========================================


async def escalate_emergency() -> Dict[str, Any]:
    """
    Escalate to emergency services.
    
    In production, this would:
    - Trigger immediate escalation
    - Connect to emergency dispatcher
    - Log emergency event
    """
    # TODO: Implement actual emergency escalation
    return {
        "escalated": True,
        "type": "emergency",
        "message": "Connecting to emergency services..."
    }


async def escalate_human() -> Dict[str, Any]:
    """
    Transfer to live human agent.
    
    In production, this would:
    - Find available agent
    - Transfer call
    - Provide context to agent
    """
    # TODO: Implement actual human escalation
    return {
        "escalated": True,
        "type": "human_agent",
        "queue_position": 1,
        "estimated_wait": "2 minutes",
        "message": "Transferring to live agent..."
    }


async def handoff_to_scheduler(reason: str, preferred_window: str = "", department: str = "", details: str = "") -> Dict[str, Any]:
    """
    🔀 Transfer caller to Scheduler agent.
    
    This is a special "handoff" tool that triggers agent switching.
    The orchestrator intercepts this and switches to the Scheduler agent
    with context about why the handoff occurred.
    
    Parameters:
    -----------
    reason : str
        Why the caller needs Scheduler agent (e.g., "book_appointment", "check_availability")
    preferred_window : str, optional
        Preferred time window (e.g., "morning", "afternoon", "this_week")
    department : str, optional
        Medical department or specialty (e.g., "primary_care", "cardiology")
    details : str, optional
        Additional context to pass to Scheduler agent
    """
    handoff_logger = get_logger("voicelive.handoff")
    
    handoff_logger.info(
        "🔀 [Handoff] AuthAgent → Scheduler | Reason: %s | Window: %s | Department: %s | Details: %s",
        reason, preferred_window or "<none>", department or "<none>", details or "<none>"
    )
    
    return {
        "handoff": True,
        "target_agent": "Scheduler",
        "reason": reason,
        "preferred_window": preferred_window,
        "department": department,
        "details": details,
        "message": "Transferring you to our scheduling specialist..."
    }


async def handoff_to_insurance(reason: str, topic: str = "", details: str = "") -> Dict[str, Any]:
    """
    🔀 Transfer caller to Insurance agent.
    
    This is a special "handoff" tool that triggers agent switching.
    The orchestrator intercepts this and switches to the Insurance agent
    with context about why the handoff occurred.
    
    Parameters:
    -----------
    reason : str
        Why the caller needs Insurance agent (e.g., "check_benefits", "medication_question")
    topic : str, optional
        Specific topic area (e.g., "copay", "deductible", "prescription_refill")
    details : str, optional
        Additional context to pass to Insurance agent
    """
    handoff_logger2 = get_logger("voicelive.handoff")
    
    handoff_logger2.info(
        "🔀 [Handoff] AuthAgent → Insurance | Reason: %s | Topic: %s | Details: %s",
        reason, topic or "<none>", details or "<none>"
    )
    
    return {
        "handoff": True,
        "target_agent": "Insurance",
        "reason": reason,
        "topic": topic,
        "details": details,
        "message": "Transferring you to our insurance benefits specialist..."
    }


# =============================================================================
# Tool Registry and Execution
# =============================================================================
# Single source of truth for ALL tool implementations.
# Both business logic tools AND handoff tools are defined here.
# =============================================================================

TOOL_IMPLEMENTATIONS: Dict[str, Any] = {
    # Business logic tools
    # Authentication
    "authenticate_caller": authenticate_caller,
    
    # Escalation tools
    "escalate_emergency": escalate_emergency,
    "escalate_human": escalate_human,
    
    # Handoff tools (agent switching)
    "handoff_to_scheduler": handoff_to_scheduler,
    "handoff_to_insurance": handoff_to_insurance,
    
    # Scheduling tools
    "check_availability": check_availability,
    "schedule_appointment": schedule_appointment,
    "set_reminder": set_reminder,
    
    # Insurance/Benefits tools
    "insurance_eligibility": insurance_eligibility,
    "benefits_lookup": benefits_lookup,
    "list_medications": list_medications,
    "refill_prescription": refill_prescription,
}


async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool by name with given arguments.
    
    This is the SINGLE POINT for all tool execution. Both handoff tools
    and business logic tools go through here.
    
    Returns tool output that includes:
    - For handoff tools: {"handoff": True, "target_agent": "...", ...}
    - For business tools: {"success": True, "data": {...}, ...}
    """
    impl = TOOL_IMPLEMENTATIONS.get(tool_name)
    if not impl:
        return {
            "error": f"Tool '{tool_name}' not implemented",
            "message": "This tool has not been implemented yet"
        }
    
    try:
        result = await impl(**arguments)
        return result
    except Exception as e:
        return {
            "error": str(e),
            "tool": tool_name,
            "message": f"Error executing tool: {e}"
        }


def is_handoff_tool(tool_name: str) -> bool:
    """Check if a tool is a handoff (agent switching) tool."""
    return tool_name.startswith("handoff_to_")
