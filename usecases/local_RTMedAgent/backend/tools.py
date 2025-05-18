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
"""

from typing import Any, Dict

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

available_tools = [
    {"type": "function", "function": schedule_appointment_schema},
    {"type": "function", "function": refill_prescription_schema},
    {"type": "function", "function": lookup_medication_info_schema},
    {"type": "function", "function": evaluate_prior_authorization_schema},
    {"type": "function", "function": escalate_emergency_schema},
    {"type": "function", "function": authentication_schema},
]
