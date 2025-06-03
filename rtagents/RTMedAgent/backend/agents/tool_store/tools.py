"""
tools.py

This module defines the available function-calling tools for the Healthcare Voice Agent.

Tools:
- schedule_appointment
- refill_prescription
- lookup_medication_info
- evaluate_prior_authorization
- escalate_emergency
- authenticate_user
- fill_new_prescription
- lookup_side_effects
- get_current_prescriptions
- check_drug_interactions
- handoff_agent
"""

from typing import Any, Dict, List

schedule_appointment_schema: Dict[str, Any] = {
    "name": "schedule_appointment",
    "description": "Schedule or modify a healthcare appointment based on patient preferences and availability.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "dob": {"type": "string", "description": "Date of birth (YYYY-MM-DD)."},
            "appointment_type": {
                "type": "string",
                "description": "Type of appointment (consultation, follow-up, etc.).",
            },
            "preferred_date": {
                "type": "string",
                "description": "Preferred appointment date (YYYY-MM-DD).",
            },
            "preferred_time": {
                "type": "string",
                "description": "Preferred appointment time (e.g., '10:00 AM').",
            },
        },
        "required": ["patient_name", "dob", "appointment_type"],
        "additionalProperties": False,
    },
}

refill_prescription_schema: Dict[str, Any] = {
    "name": "refill_prescription",
    "description": "Refill an existing prescription for a patient's medication.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "medication_name": {
                "type": "string",
                "description": "Name of the medication to refill.",
            },
            "pharmacy": {
                "type": "string",
                "description": "Preferred pharmacy name or location (optional).",
            },
        },
        "required": ["patient_name", "medication_name"],
        "additionalProperties": False,
    },
}

lookup_medication_info_schema: Dict[str, Any] = {
    "name": "lookup_medication_info",
    "description": "Retrieve basic usage, warnings, and side effects information about a medication.",
    "parameters": {
        "type": "object",
        "properties": {
            "medication_name": {
                "type": "string",
                "description": "Medication name to look up.",
            }
        },
        "required": ["medication_name"],
        "additionalProperties": False,
    },
}

evaluate_prior_authorization_schema: Dict[str, Any] = {
    "name": "evaluate_prior_authorization",
    "description": "Analyze a prior authorization request based on patient information, clinical history, and policy text.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_info": {
                "type": "object",
                "description": "Patient demographics and identifiers.",
            },
            "physician_info": {
                "type": "object",
                "description": "Physician specialty and contact details.",
            },
            "clinical_info": {
                "type": "object",
                "description": "Clinical diagnosis, lab results, prior treatments.",
            },
            "treatment_plan": {
                "type": "object",
                "description": "Requested treatment or medication plan.",
            },
            "policy_text": {
                "type": "string",
                "description": "Insurance or payer policy text to evaluate against.",
            },
        },
        "required": [
            "patient_info",
            "physician_info",
            "clinical_info",
            "treatment_plan",
            "policy_text",
        ],
        "additionalProperties": False,
    },
}

escalate_emergency_schema: Dict[str, Any] = {
    "name": "escalate_emergency",
    "description": "Immediately escalate an urgent healthcare concern to a human agent.",
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Reason for the escalation (e.g., chest pain, severe symptoms).",
            }
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}

authentication_schema: Dict[str, Any] = {
    "name": "authenticate_user",
    "description": "Authenticate a user by verifying first name, last name, and phone number.",
    "parameters": {
        "type": "object",
        "properties": {
            "first_name": {"type": "string", "description": "User's first name."},
            "last_name": {"type": "string", "description": "User's last name."},
            "phone_number": {
                "type": "string",
                "description": "User's phone number (digits only, no spaces).",
            },
        },
        "required": ["first_name", "last_name", "phone_number"],
        "additionalProperties": False,
    },
}

# -------------------------------------------------------
# Assemble all tools wrapped as GPT-4o-compatible entries
# -------------------------------------------------------

fill_new_prescription_schema: Dict[str, Any] = {
    "name": "fill_new_prescription",
    "description": "Add a new prescription for the patient in the system.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "medication_name": {
                "type": "string",
                "description": "Name of the new medication to add.",
            },
            "dosage": {
                "type": "string",
                "description": "Dosage information (e.g., '500 mg twice daily').",
            },
            "pharmacy": {
                "type": "string",
                "description": "Pharmacy where medication will be filled.",
            },
        },
        "required": ["patient_name", "medication_name", "dosage", "pharmacy"],
        "additionalProperties": False,
    },
}

lookup_side_effects_schema: Dict[str, Any] = {
    "name": "lookup_side_effects",
    "description": "Retrieve initial and long-term side effects for a given medication.",
    "parameters": {
        "type": "object",
        "properties": {
            "medication_name": {
                "type": "string",
                "description": "Name of medication to query.",
            }
        },
        "required": ["medication_name"],
        "additionalProperties": False,
    },
}

get_current_prescriptions_schema: Dict[str, Any] = {
    "name": "get_current_prescriptions",
    "description": "Fetch all active prescriptions for the patient.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            }
        },
        "required": ["patient_name"],
        "additionalProperties": False,
    },
}

check_drug_interactions_schema: Dict[str, Any] = {
    "name": "check_drug_interactions",
    "description": "Check for known interactions between a new medication and the patient's current medications.",
    "parameters": {
        "type": "object",
        "properties": {
            "new_medication": {
                "type": "string",
                "description": "Name of the new medication.",
            },
            "current_medications": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of patient's current medication names.",
            },
        },
        "required": ["new_medication", "current_medications"],
        "additionalProperties": False,
    },
}

request_referral_schema: Dict[str, Any] = {
    "name": "request_referral",
    "description": "Submit a referral request to a specialist or new provider for the patient.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "specialty": {
                "type": "string",
                "description": "Medical specialty for the referral (e.g., cardiology, dermatology).",
            },
            "reason_for_referral": {
                "type": "string",
                "description": "Reason for the referral (e.g., symptoms, diagnosis).",
            },
            "provider_preference": {
                "type": "string",
                "description": "Patient's preferred provider, if any.",
            },
            "preferred_location": {
                "type": "string",
                "description": "Preferred location for specialist visit.",
            },
            "urgency": {
                "type": "string",
                "description": "Urgency of referral (routine, urgent, stat, etc.).",
            },
            "insurance_details": {
                "type": "string",
                "description": "Relevant insurance or authorization info.",
            },
        },
        "required": [
            "patient_name",
            "specialty",
            "reason_for_referral",
            "urgency",
            "insurance_details",
        ],
        "additionalProperties": False,
    },
}

get_specialist_list_schema: Dict[str, Any] = {
    "name": "get_specialist_list",
    "description": "List available specialists by specialty and/or location.",
    "parameters": {
        "type": "object",
        "properties": {
            "specialty": {
                "type": "string",
                "description": "Specialty to search for (optional).",
            },
            "location": {
                "type": "string",
                "description": "Preferred location (optional).",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}

check_referral_status_schema: Dict[str, Any] = {
    "name": "check_referral_status",
    "description": "Check status of an existing specialist referral.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "specialty": {
                "type": "string",
                "description": "Specialty of referral being checked.",
            },
            "referral_id": {
                "type": "string",
                "description": "Referral or appointment ID, if available.",
            },
        },
        "required": ["patient_name"],
        "additionalProperties": False,
    },
}

# ---------- Billing ----------
insurance_billing_question_schema: Dict[str, Any] = {
    "name": "insurance_billing_question",
    "description": "Answer or escalate a billing or insurance-related question from the patient.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "question_summary": {
                "type": "string",
                "description": "The billing or insurance question in the patient's own words.",
            },
            "claim_number": {
                "type": "string",
                "description": "Insurance claim number, if relevant.",
            },
            "invoice_date": {
                "type": "string",
                "description": "Date of the invoice or service, if applicable.",
            },
        },
        "required": ["patient_name", "question_summary"],
        "additionalProperties": False,
    },
}

# ---------- General Health ----------
general_health_question_schema: Dict[str, Any] = {
    "name": "general_health_question",
    "description": "Respond to general health or wellness questions that do not require diagnosis or treatment.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "question_summary": {
                "type": "string",
                "description": "Health or wellness question in the patient's own words.",
            },
        },
        "required": ["patient_name", "question_summary"],
        "additionalProperties": False,
    },
}

# ---------- Scheduling Enhancements ----------
change_appointment_schema: Dict[str, Any] = {
    "name": "change_appointment",
    "description": "Change the date/time/provider for an existing appointment.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {"type": "string", "description": "Patient's full name."},
            "appt_id": {"type": "string", "description": "Appointment ID to change."},
            "new_date": {
                "type": "string",
                "description": "New appointment date (YYYY-MM-DD).",
            },
            "new_time": {"type": "string", "description": "New appointment time."},
            "provider": {
                "type": "string",
                "description": "Provider name, if changing.",
            },
        },
        "required": ["patient_name", "appt_id"],
        "additionalProperties": False,
    },
}

cancel_appointment_schema: Dict[str, Any] = {
    "name": "cancel_appointment",
    "description": "Cancel an existing appointment for a patient.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {"type": "string", "description": "Patient's full name."},
            "appt_id": {"type": "string", "description": "Appointment ID to cancel."},
        },
        "required": ["patient_name", "appt_id"],
        "additionalProperties": False,
    },
}

get_upcoming_appointments_schema: Dict[str, Any] = {
    "name": "get_upcoming_appointments",
    "description": "List all upcoming appointments for a patient.",
    "parameters": {
        "type": "object",
        "properties": {
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
        },
        "required": ["patient_name"],
        "additionalProperties": False,
    },
}

handoff_agent_schema: Dict[str, Any] = {
    "name": "handoff_agent",
    "description": "Signal that the agent has completed its task and is ready to hand off control to the intent classifier or next agent.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}

# -------------------------------------------------------
# Assemble all tools wrapped as GPT-4o-compatible entries
# -------------------------------------------------------

available_tools: List[Dict[str, Any]] = [
    {"type": "function", "function": schedule_appointment_schema},
    {"type": "function", "function": change_appointment_schema},
    {"type": "function", "function": cancel_appointment_schema},
    {"type": "function", "function": get_upcoming_appointments_schema},
    {"type": "function", "function": refill_prescription_schema},
    {"type": "function", "function": lookup_medication_info_schema},
    {"type": "function", "function": evaluate_prior_authorization_schema},
    {"type": "function", "function": escalate_emergency_schema},
    {"type": "function", "function": authentication_schema},
    {"type": "function", "function": fill_new_prescription_schema},
    {"type": "function", "function": lookup_side_effects_schema},
    {"type": "function", "function": get_current_prescriptions_schema},
    {"type": "function", "function": check_drug_interactions_schema},
    {"type": "function", "function": insurance_billing_question_schema},
    {"type": "function", "function": request_referral_schema},
    {"type": "function", "function": get_specialist_list_schema},
    {"type": "function", "function": check_referral_status_schema},
    {"type": "function", "function": general_health_question_schema},
    {"type": "function", "function": handoff_agent_schema},
]


TOOL_REGISTRY: dict[str, dict] = {t["function"]["name"]: t for t in available_tools}
