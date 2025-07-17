"""
tools.py

This module defines the available function-calling tools for the Insurance Voice Agent.

Tools:
- record_fnol_schema
- authenticate_caller
- escalate_emergency
"""

from typing import Any, Dict, List

# -----------------------------  FNOL tools  -----------------------------


# 1) Create / record a First-Notice-of-Loss claim
record_fnol_schema: Dict[str, Any] = {
    "name": "record_fnol",
    "description": (
        "Create a First-Notice-of-Loss (FNOL) claim in XYMZ’s system using the "
        "minimal 12-field schema. Returns {claim_success: bool, claim_id?: str, "
        "missing_data?: str}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Full name of the caller.",
            },
            "caller_role": {
                "type": "string",
                "enum": ["insured", "claimant", "provider"],
                "description": "Relationship of the caller to the claim.",
            },
            "policy_id": {
                "type": "string",
                "description": "Policy identifier (e.g., ‘POL-A10001’).",
            },
            "date_reported": {
                "type": "string",
                "description": "Date the claim is reported (YYYY-MM-DD). "
                "Optional—backend will auto-stamp UTC today if omitted.",
            },
            "date_of_loss": {
                "type": "string",
                "description": "Date the loss occurred (YYYY-MM-DD).",
            },
            "time_of_loss": {
                "type": "string",
                "description": "Approx. time of loss (HH:MM 24-h) or blank.",
            },
            "collision": {
                "type": "boolean",
                "description": "Was the vehicle moving when damage occurred?",
            },
            "bodily_injury": {
                "type": "boolean",
                "description": "Were any injuries sustained?",
            },
            "property_damage": {
                "type": "boolean",
                "description": "Any property damage beyond the insured vehicle?",
            },
            "comprehensive_loss": {
                "type": "boolean",
                "description": "Non-collision or parked-vehicle loss?",
            },
            "narrative": {
                "type": "string",
                "description": "≤400-character incident description in the caller’s own words.",
            },
            "loss_location": {
                "type": "object",
                "description": "Structured street-level location of the loss.",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": "string"},
                    "zipcode": {"type": "string"},
                },
                "required": ["street", "city", "state", "zipcode"],
                "additionalProperties": False,
            },
            "location_description": {
                "type": "string",
                "description": "Free-text notes about the loss location "
                "(e.g., ‘same as policy address’, landmark details).",
            },
        },
        # Minimal set needed for backend success (matches _REQUIRED_SLOTS):
        "required": [
            "caller_name",
            "caller_role",
            "policy_id",
            "date_of_loss",
            "collision",
            "bodily_injury",
            "property_damage",
            "glass_damage",
            "comprehensive_loss",
            "narrative",
            "loss_location",
        ],
        "additionalProperties": False,
    },
}

authenticate_caller_schema: Dict[str, Any] = {
    "name": "authenticate_caller",
    "description": (
        "Verify a caller’s identity for FNOL by matching (full name + ZIP code + "
        "last-4 digits of one identifier). The last-4 may be SSN, policy, claim, "
        "or phone number. Returns {authenticated: bool, message: str, "
        "policy_id?: str, caller_name?: str}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {
                "type": "string",
                "description": "Caller’s full name, e.g., 'Alice Brown'.",
            },
            "zip_code": {"type": "string", "description": "Caller’s 5-digit ZIP code."},
            "last4_id": {
                "type": "string",
                "description": (
                    "Caller-supplied last 4 digits of SSN, policy number, "
                    "claim number, **or** phone number."
                ),
            },
        },
        "required": ["full_name", "zip_code", "last4_id"],
        "additionalProperties": False,
    },
}

# 2) Escalate an emergency discovered during intake
escalate_emergency_schema_fnol: Dict[str, Any] = {
    "name": "escalate_emergency",
    "description": "Immediately escalate an urgent situation (injury, fire, medical crisis) to human dispatch.",
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Brief reason for escalation."},
            "caller_name": {
                "type": "string",
                "description": "Full name of the caller.",
            },
            "policy_id": {"type": "string", "description": "Policy identifier."},
        },
        "required": ["reason", "caller_name", "policy_id"],
        "additionalProperties": False,
    },
}

available_tools: List[Dict[str, Any]] = [
    {"type": "function", "function": record_fnol_schema},
    {"type": "function", "function": escalate_emergency_schema_fnol},
    {"type": "function", "function": authenticate_caller_schema},
]

TOOL_REGISTRY: dict[str, dict] = {t["function"]["name"]: t for t in available_tools}
