"""
tools.py

Defines the function-calling tools exposed to the Insurance Voice Agent.

Tools:
- record_fnol
- authenticate_caller
- escalate_emergency
- handoff_general_agent
- handoff_claim_agent
- escalate_human
- detect_voicemail_and_end_call
"""

from __future__ import annotations

from typing import Any, Dict, List

record_fnol_schema: Dict[str, Any] = {
    "name": "record_fnol",
    "description": (
        "Create a First-Notice-of-Loss (FNOL) claim in the insurance system. "
        "This tool collects all required details about the incident, vehicle, and involved parties, "
        "and returns a structured response indicating claim success, claim ID, and any missing data. "
        "Use this to initiate a new claim after a loss event. "
        "Returns: {claim_success: bool, claim_id?: str, missing_data?: str}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Full legal name of the caller reporting the loss.",
            },
            "driver_name": {
                "type": "string",
                "description": "Name of the driver involved in the incident.",
            },
            "driver_relationship": {
                "type": "string",
                "description": "Relationship of the driver to the policyholder (e.g., self, spouse, child, other).",
            },
            "vehicle_details": {
                "type": "object",
                "description": "Detailed information about the vehicle involved in the incident.",
                "properties": {
                    "make": {
                        "type": "string",
                        "description": "Vehicle manufacturer (e.g., Toyota).",
                    },
                    "model": {
                        "type": "string",
                        "description": "Vehicle model (e.g., Camry).",
                    },
                    "year": {
                        "type": "string",
                        "description": "Year of manufacture (e.g., 2022).",
                    },
                    "policy_id": {
                        "type": "string",
                        "description": "Unique policy identifier for the vehicle.",
                    },
                },
                "required": ["make", "model", "year", "policy_id"],
            },
            "number_of_vehicles_involved": {
                "type": "integer",
                "description": "Total number of vehicles involved in the incident (including caller's vehicle).",
            },
            "incident_description": {
                "type": "string",
                "description": "Brief summary of the incident (e.g., collision, theft, vandalism, fire, etc.).",
            },
            "loss_date": {
                "type": "string",
                "description": "Date the loss occurred in YYYY-MM-DD format.",
            },
            "loss_time": {
                "type": "string",
                "description": "Approximate time of loss in HH:MM (24-hour) format, or blank if unknown.",
            },
            "loss_location": {
                "type": "object",
                "description": "Street-level location where the loss occurred.",
                "properties": {
                    "street": {
                        "type": "string",
                        "description": "Street address of the incident.",
                    },
                    "city": {
                        "type": "string",
                        "description": "City where the incident occurred.",
                    },
                    "state": {
                        "type": "string",
                        "description": "State abbreviation (e.g., CA, NY).",
                    },
                    "zipcode": {"type": "string", "description": "5-digit ZIP code."},
                },
                "required": ["street", "city", "state", "zipcode"],
            },
            "vehicle_drivable": {
                "type": "boolean",
                "description": "Indicates whether the vehicle was drivable after the incident.",
            },
            "passenger_information": {
                "type": ["array", "null"],
                "nullable": True,
                "description": (
                    "List of passengers in the vehicle at the time of the incident. "
                    "Each passenger includes name and relationship to the policyholder. "
                    "Send null or omit if caller confirms no passengers."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Passenger's full name.",
                        },
                        "relationship": {
                            "type": "string",
                            "description": "Relationship to policyholder.",
                        },
                    },
                    "required": ["name", "relationship"],
                },
            },
            "injury_assessment": {
                "type": "object",
                "description": "Assessment of any injuries sustained in the incident.",
                "properties": {
                    "injured": {
                        "type": "boolean",
                        "description": "Was anyone injured in the incident?",
                    },
                    "details": {
                        "type": "string",
                        "description": "Details of injury, or 'None' if no injuries.",
                    },
                },
                "required": ["injured", "details"],
            },
            "trip_purpose": {
                "type": "string",
                "enum": ["commuting", "work", "personal", "other"],
                "description": "Purpose of the trip at the time of the incident.",
            },
            "date_reported": {
                "type": "string",
                "description": "Date the claim is reported (YYYY-MM-DD). Optional—auto-filled if omitted.",
            },
            "location_description": {
                "type": "string",
                "description": "Optional free-text notes about the location or context.",
            },
        },
        "required": [
            "caller_name",
            "driver_name",
            "driver_relationship",
            "vehicle_details",
            "number_of_vehicles_involved",
            "incident_description",
            "loss_date",
            "loss_time",
            "loss_location",
            "vehicle_drivable",
            "injury_assessment",
            "trip_purpose",
        ],
        "additionalProperties": False,
    },
}


authenticate_caller_schema: Dict[str, Any] = {
    "name": "authenticate_caller",
    "description": (
        "Verify the caller’s identity by matching their full legal name, ZIP code, "
        "and the last 4 digits of a key identifier (SSN, policy number, claim "
        "number, or phone number). "
        "Returns: {authenticated: bool, message: str, client_id: str | null, "
        "caller_name: str | null, attempt: int, intent: str | null, "
        "claim_intent: str | null}. "
        "At least one of ZIP code or last‑4 must be provided."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {
                "type": "string",
                "description": "Caller’s full legal name (e.g., 'Alice Brown').",
            },
            "zip_code": {
                "type": "string",
                "description": "Caller’s 5‑digit ZIP code. May be blank if last4_id is provided.",
            },
            "last4_id": {
                "type": "string",
                "description": (
                    "Last 4 digits of SSN, policy number, claim number, or phone "
                    "number. May be blank if zip_code is provided."
                ),
            },
            "intent": {
                "type": "string",
                "enum": ["claims", "general"],
                "description": "High‑level reason for the call.",
            },
            "claim_intent": {
                "type": ["string", "null"],
                "enum": ["new_claim", "existing_claim", "unknown", None],
                "description": "Sub‑intent when intent == 'claims'. Null for general inquiries.",
            },
            "attempt": {
                "type": "integer",
                "minimum": 1,
                "description": "Nth authentication attempt within the current call (starts at 1).",
            },
        },
        "required": [
            "full_name",
            "zip_code",
            "last4_id",
            "intent",
            "claim_intent",
        ],
        "additionalProperties": False,
    },
}

escalate_emergency_schema: Dict[str, Any] = {
    "name": "escalate_emergency",
    "description": (
        "Immediately escalate an urgent or life-threatening situation (such as injury, fire, or medical crisis) to emergency dispatch. "
        "Use this tool when the caller reports a scenario requiring immediate emergency response."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Concise reason for escalation (e.g., 'injury', 'fire', 'medical emergency').",
            },
            "caller_name": {
                "type": "string",
                "description": "Full legal name of the caller.",
            },
            "policy_id": {
                "type": "string",
                "description": "Unique policy identifier for the caller.",
            },
        },
        "required": ["reason", "caller_name", "policy_id"],
        "additionalProperties": False,
    },
}

handoff_general_schema: Dict[str, Any] = {
    "name": "handoff_general_agent",
    "description": (
        "Route the call to the General Insurance Questions AI agent when the "
        "caller requests broad information not tied to a specific claim."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Full legal name of the caller.",
            },
            "topic": {
                "type": "string",
                "description": "Short keyword describing the caller’s question "
                "(e.g., 'coverage', 'billing').",
            },
        },
        "required": ["caller_name", "topic"],
        "additionalProperties": False,
    },
}

handoff_claim_schema: Dict[str, Any] = {
    "name": "handoff_claim_agent",
    "description": (
        "Route the call to the Claims Intake AI agent when the caller needs to "
        "start or update a claim."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Full legal name of the caller.",
            },
            "policy_id": {
                "type": "string",
                "description": "Unique policy identifier for the caller.",
            },
            "claim_intent": {
                "type": "string",
                "description": (
                    "Brief intent string (e.g., 'new_claim', 'update_claim')."
                ),
            },
        },
        "required": ["caller_name", "policy_id", "claim_intent"],
        "additionalProperties": False,
    },
}

find_information_schema: Dict[str, Any] = {
    "name": "find_information_for_policy",
    "description": (
        "Retrieve grounded, caller-specific details from a policy record. "
        "Use this tool for any question that depends on the caller’s actual "
        "coverage (deductible amount, roadside assistance, glass coverage, "
        "rental reimbursement, etc.)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "policy_id": {
                "type": "string",
                "description": "Unique policy identifier (e.g., 'POL-A10001').",
            },
            "question": {
                "type": "string",
                "description": "Exact caller question to ground (e.g., "
                "'Do I have roadside assistance?').",
            },
        },
        "required": ["policy_id", "question"],
        "additionalProperties": False,
    },
}


escalate_human_schema: Dict[str, Any] = {
    "name": "escalate_human",
    "description": (
        "Escalate the call to a live human specialist for non-emergency but complex scenarios. "
        "Use this tool for backend errors, repeated validation failures, suspected fraud, or caller requests for human assistance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "route_reason": {
                "type": "string",
                "description": "Reason for escalation (e.g., 'mfa_authentication_failed', 'backend_unavailable', 'caller_request').",
            },
            "caller_name": {
                "type": "string",
                "description": "Full legal name of the caller.",
            },
            "policy_id": {
                "type": "string",
                "description": "Policy identifier for insurance, optional for financial services.",
            },
        },
        "required": ["route_reason", "caller_name"],
        "additionalProperties": False,
    },
}

handoff_fraud_agent_schema: Dict[str, Any] = {
    "name": "handoff_fraud_agent",
    "description": (
        "Hand off client to fraud specialist after successful MFA authentication. "
        "Use for fraud reporting, suspicious activity, or fraud investigations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Client's full legal name from identity verification.",
            },
            "client_id": {
                "type": "string",
                "description": "Verified client identifier from MFA process.",
            },
            "institution_name": {
                "type": "string",
                "description": "Client's financial institution name.",
            },
            "fraud_type": {
                "type": "string",
                "enum": ["suspicious_activity", "card_fraud", "identity_theft", "account_takeover"],
                "description": "Type of fraud concern reported by client.",
            },
        },
        "required": ["caller_name", "client_id", "institution_name", "fraud_type"],
        "additionalProperties": False,
    },
}

handoff_transfer_agency_agent_schema: Dict[str, Any] = {
    "name": "handoff_transfer_agency_agent",
    "description": (
        "Hand off client to transfer agency specialist after successful MFA authentication. "
        "Use for stock transfers, account transfers, or transfer agency services."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Client's full legal name from identity verification.",
            },
            "client_id": {
                "type": "string",
                "description": "Verified client identifier from MFA process.",
            },
            "institution_name": {
                "type": "string",
                "description": "Client's financial institution name.",
            },
            "service_type": {
                "type": "string",
                "enum": ["stock_transfer", "account_transfer", "dividend_inquiry", "general_transfer"],
                "description": "Type of transfer agency service requested.",
            },
        },
        "required": ["caller_name", "client_id", "institution_name", "service_type"],
        "additionalProperties": False,
    },
}

handoff_paypal_agent_schema: Dict[str, Any] = {
    "name": "handoff_paypal_agent",
    "description": (
        "Transfer the caller to the PayPal/Venmo support specialist with a concise summary of the issue. "
        "Include the caller's name, issue overview, and institution metadata when available."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Full name of the caller requesting PayPal or Venmo assistance.",
            },
            "client_id": {
                "type": "string",
                "description": "Optional verified client identifier if authentication already captured it.",
            },
            "issue_summary": {
                "type": "string",
                "description": "Short summary of the PayPal/Venmo topic the specialist should pick up.",
            },
            "inquiry_type": {
                "type": "string",
                "description": "Categorised PayPal/Venmo inquiry type (e.g., payments, limits, disputes).",
            },
            "institution_name": {
                "type": "string",
                "description": "Optional institution or company association if relevant to the call.",
            },
            "session_overrides": {
                "type": "object",
                "description": "Optional session overrides to apply when the PayPal agent becomes active.",
            },
        },
        "required": ["caller_name"],
        "additionalProperties": False,
    },
}

handoff_to_auth_schema: Dict[str, Any] = {
    "name": "handoff_to_auth",
    "description": (
        "Return the caller to the authentication specialist to resume identity checks or provide broader assistance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {
                "type": "string",
                "description": "Full name of the caller being redirected.",
            },
            "reason": {
                "type": "string",
                "description": "Primary reason for routing back to authentication.",
            },
            "details": {
                "type": "string",
                "description": "Additional context gathered before the handoff.",
            },
            "session_overrides": {
                "type": "object",
                "description": "Optional session overrides to apply when the authentication agent resumes.",
            },
        },
        "required": ["caller_name"],
        "additionalProperties": False,
    },
}

verify_client_identity_schema: Dict[str, Any] = {
    "name": "verify_client_identity",
    "description": (
        "Verify client identity using name, institution, and company code for financial services. "
        "First step in multi-factor authentication process."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {
                "type": "string",
                "description": "Client's full legal name.",
            },
            "institution_name": {
                "type": "string", 
                "description": "Name of the financial institution.",
            },
            "company_code_last4": {
                "type": "string",
                "description": "Last 4 digits of company code.",
            },
        },
        "required": ["full_name", "institution_name", "company_code_last4"],
        "additionalProperties": False,
    },
}

verify_fraud_client_identity_schema: Dict[str, Any] = {
    "name": "verify_fraud_client_identity",
    "description": (
        "Verify fraud client identity using simplified authentication (name + SSN last 4). "
        "Used for urgent fraud reporting cases. Faster than full institutional verification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {
                "type": "string",
                "description": "Client's full legal name.",
            },
            "ssn_last4": {
                "type": "string",
                "description": "Last 4 digits of Social Security Number.",
            },
        },
        "required": ["full_name", "ssn_last4"],
        "additionalProperties": False,
    },
}

send_mfa_code_schema: Dict[str, Any] = {
    "name": "send_mfa_code",
    "description": (
        "Send MFA verification code via email or SMS to authenticated client. "
        "Used after successful identity verification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Unique client identifier from verification.",
            },
            "delivery_method": {
                "type": "string",
                "enum": ["email", "sms"],
                "description": "Delivery method for verification code.",
            },
            "intent": {
                "type": "string",
                "enum": ["fraud", "transfer_agency"],
                "description": "Service intent to determine specialist routing after authentication.",
            },
            "transaction_amount": {
                "type": "number",
                "description": "Transaction amount if applicable.",
            },
            "transaction_type": {
                "type": "string",
                "description": "Type of transaction if applicable.",
            },
        },
        "required": ["client_id", "delivery_method"],
        "additionalProperties": False,
    },
}

verify_mfa_code_schema: Dict[str, Any] = {
    "name": "verify_mfa_code",
    "description": (
        "Verify the MFA code provided by client. "
        "Completes the authentication process."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session ID from MFA code sending.",
            },
            "otp_code": {
                "type": "string",
                "description": "6-digit verification code provided by client.",
            },
        },
        "required": ["session_id", "otp_code"],
        "additionalProperties": False,
    },
}

resend_mfa_code_schema: Dict[str, Any] = {
    "name": "resend_mfa_code", 
    "description": (
        "Resend the MFA verification code to client if they didn't receive it "
        "or it expired. Uses the same session_id as original MFA request."
    ),
    "parameters": {
        "type": "object", 
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session ID from original MFA code sending.",
            },
        },
        "required": ["session_id"],
        "additionalProperties": False,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Fraud Detection Tool Schemas
# ──────────────────────────────────────────────────────────────────────────────

analyze_recent_transactions_schema: Dict[str, Any] = {
    "name": "analyze_recent_transactions",
    "description": (
        "Analyze recent transactions for fraud patterns, suspicious activity, and risk assessment. "
        "Provides comprehensive fraud indicators and recommended actions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "days_back": {
                "type": "integer",
                "description": "Number of days to analyze (default: 30).",
                "minimum": 1,
                "maximum": 90,
            },
            "transaction_limit": {
                "type": "integer", 
                "description": "Maximum transactions to analyze (default: 50).",
                "minimum": 10,
                "maximum": 200,
            },
        },
        "required": ["client_id"],
        "additionalProperties": False,
    },
}

check_suspicious_activity_schema: Dict[str, Any] = {
    "name": "check_suspicious_activity",
    "description": (
        "Check for suspicious account activity patterns including login anomalies, "
        "transaction patterns, and geographic inconsistencies. Provides risk assessment."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "activity_type": {
                "type": "string",
                "enum": ["all", "login", "transaction", "profile_change"],
                "description": "Type of activity to check (default: 'all').",
            },
        },
        "required": ["client_id"],
        "additionalProperties": False,
    },
}

create_fraud_case_schema: Dict[str, Any] = {
    "name": "create_fraud_case",
    "description": (
        "Create formal fraud investigation case with case number, priority assignment, "
        "and investigation timeline. Used for documented fraud incidents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "fraud_type": {
                "type": "string",
                "enum": ["card_fraud", "identity_theft", "account_takeover", "phishing", "unauthorized_transactions", "other"],
                "description": "Type of fraud being reported.",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the fraud incident.",
            },
            "reported_transactions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of transaction IDs involved in the fraud (optional).",
            },
            "estimated_loss": {
                "type": "number",
                "description": "Estimated financial loss in USD (optional).",
                "minimum": 0,
            },
        },
        "required": ["client_id", "fraud_type", "description"],
        "additionalProperties": False,
    },
}

send_fraud_case_email_schema: Dict[str, Any] = {
    "name": "send_fraud_case_email",
    "description": (
        "Send comprehensive email notification with fraud case details including case number, "
        "blocked card information, provisional credits, next steps, and investigation timeline."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "fraud_case_id": {
                "type": "string",
                "description": "The fraud case number to include in email.",
            },
            "email_type": {
                "type": "string",
                "enum": ["case_created", "card_blocked", "investigation_update", "resolution"],
                "description": "Type of email notification to send.",
            },
            "additional_details": {
                "type": "string",
                "description": "Optional extra information to include in email.",
            },
        },
        "required": ["client_id", "fraud_case_id", "email_type"],
        "additionalProperties": False,
    },
}

create_transaction_dispute_schema: Dict[str, Any] = {
    "name": "create_transaction_dispute",
    "description": (
        "Create a transaction dispute case for billing errors, merchant issues, or service problems "
        "(NOT fraud cases). Use when customer disputes charges but card doesn't need blocking."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "transaction_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of transaction IDs being disputed by the customer.",
            },
            "dispute_reason": {
                "type": "string",
                "enum": ["merchant_error", "billing_error", "service_not_received", "duplicate_charge", "authorization_issue"],
                "description": "Primary reason for the transaction dispute.",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the dispute issue from the customer.",
            },
        },
        "required": ["client_id", "transaction_ids", "dispute_reason", "description"],
        "additionalProperties": False,
    },
}

block_card_emergency_schema: Dict[str, Any] = {
    "name": "block_card_emergency",
    "description": (
        "Immediately block credit/debit card to prevent further fraudulent use. "
        "Provides replacement timeline and temporary access options."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "card_last_4": {
                "type": "string",
                "description": "Last 4 digits of card to block.",
                "pattern": "^[0-9]{4}$",
            },
            "block_reason": {
                "type": "string",
                "enum": ["fraud_suspected", "card_lost", "card_stolen", "unauthorized_use", "compromised"],
                "description": "Reason for blocking the card.",
            },
        },
        "required": ["client_id", "card_last_4", "block_reason"],
        "additionalProperties": False,
    },
}

provide_fraud_education_schema: Dict[str, Any] = {
    "name": "provide_fraud_education",
    "description": (
        "Provide fraud prevention education, warning signs, and best practices "
        "tailored to specific fraud types. Helps customers protect themselves."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier.",
            },
            "fraud_type": {
                "type": "string",
                "enum": ["phishing", "identity_theft", "card_skimming", "general"],
                "description": "Type of fraud education to provide (default: 'general').",
            },
        },
        "required": ["client_id"],
        "additionalProperties": False,
    },
}

ship_replacement_card_schema: Dict[str, Any] = {
    "name": "ship_replacement_card",
    "description": (
        "Ship a replacement card to the client in case of fraud, theft, or card compromise. "
        "This tool blocks the current card, generates a new card number, and arranges expedited shipping "
        "with tracking notification. Creates a comprehensive audit trail in Cosmos DB."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Authenticated client identifier from previous auth step.",
            },
            "reason": {
                "type": "string",
                "enum": ["fraud_detected", "card_theft", "card_compromise", "suspicious_activity"],
                "description": "Reason for replacement card shipment.",
            },
            "expedited_shipping": {
                "type": "boolean",
                "description": "Whether to use expedited shipping (default: true for fraud cases).",
            },
            "fraud_case_id": {
                "type": "string",
                "description": "Optional fraud case ID to link this card replacement to an existing fraud investigation.",
            },
        },
        "required": ["client_id", "reason"],
        "additionalProperties": False,
    },
}

check_transaction_authorization_schema: Dict[str, Any] = {
    "name": "check_transaction_authorization",
    "description": (
        "Check if client is authorized for specific transaction type and amount. "
        "Validates operations before execution."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Unique client identifier.",
            },
            "operation": {
                "type": "string",
                "description": "Type of operation to authorize.",
            },
            "amount": {
                "type": "number",
                "description": "Transaction amount to validate.",
            },
        },
        "required": ["client_id", "operation"],
        "additionalProperties": False,
    },
}

# =============================================================================
# Transfer Agency Tools
# =============================================================================

get_client_data_schema: Dict[str, Any] = {
    "name": "get_client_data",
    "description": (
        "Retrieve institutional client data including account details, compliance status, and contact information. "
        "Use this to verify client identity and get account configuration."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_code": {
                "type": "string",
                "description": "Institutional client code (e.g., GCA-48273).",
            },
        },
        "required": ["client_code"],
        "additionalProperties": False,
    },
}

get_drip_positions_schema: Dict[str, Any] = {
    "name": "get_drip_positions",
    "description": (
        "Get client's current Dividend Reinvestment Plan (DRIP) positions including shares, cost basis, and market values. "
        "Returns detailed position data for all DRIP holdings."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_code": {
                "type": "string",
                "description": "Institutional client code to look up positions for.",
            },
        },
        "required": ["client_code"],
        "additionalProperties": False,
    },
}

check_compliance_status_schema: Dict[str, Any] = {
    "name": "check_compliance_status",
    "description": (
        "Check client's AML and FATCA compliance status including expiry dates and review requirements. "
        "Use this to determine if compliance review is needed before processing transactions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_code": {
                "type": "string",
                "description": "Institutional client code to check compliance for.",
            },
        },
        "required": ["client_code"],
        "additionalProperties": False,
    },
}

calculate_liquidation_proceeds_schema: Dict[str, Any] = {
    "name": "calculate_liquidation_proceeds",
    "description": (
        "Calculate liquidation proceeds, fees, taxes, and net settlement amounts for DRIP positions. "
        "Includes FX conversion for non-USD accounts and fee calculations based on settlement speed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_code": {
                "type": "string",
                "description": "Institutional client code.",
            },
            "symbol": {
                "type": "string",
                "description": "Stock symbol to liquidate (e.g., PLTR, MSFT, TSLA).",
            },
            "shares": {
                "type": "number",
                "description": "Number of shares to liquidate. If omitted, liquidates entire position.",
            },
            "settlement_speed": {
                "type": "string",
                "enum": ["standard", "expedited"],
                "description": "Settlement speed: 'standard' (2-3 days) or 'expedited' (same-day).",
                "default": "standard",
            },
        },
        "required": ["client_code", "symbol"],
        "additionalProperties": False,
    },
}

handoff_to_compliance_schema: Dict[str, Any] = {
    "name": "handoff_to_compliance",
    "description": (
        "Transfer client to compliance specialist for AML/FATCA review and regulatory verification. "
        "Use when compliance issues need specialist attention before proceeding with transactions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_code": {
                "type": "string",
                "description": "Institutional client code.",
            },
            "client_name": {
                "type": "string",
                "description": "Client contact name for personalized handoff.",
            },
            "compliance_issue": {
                "type": "string",
                "description": "Description of the compliance issue requiring specialist review.",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "high", "expedited"],
                "description": "Urgency level for the compliance review.",
                "default": "normal",
            },
        },
        "required": ["client_code", "client_name", "compliance_issue"],
        "additionalProperties": False,
    },
}

handoff_to_trading_schema: Dict[str, Any] = {
    "name": "handoff_to_trading",
    "description": (
        "Transfer client to trading specialist for complex trade execution, FX conversion, or institutional settlement. "
        "Use for trades requiring specialist attention beyond basic processing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_code": {
                "type": "string",
                "description": "Institutional client code.",
            },
            "client_name": {
                "type": "string",
                "description": "Client contact name for personalized handoff.",
            },
            "trade_details": {
                "type": "object",
                "description": "Trade execution details and requirements.",
            },
            "complexity": {
                "type": "string",
                "enum": ["standard", "complex", "institutional"],
                "description": "Trade complexity level to determine appropriate desk.",
                "default": "standard",
            },
        },
        "required": ["client_code", "client_name", "trade_details"],
        "additionalProperties": False,
    },
}


detect_voicemail_schema: Dict[str, Any] = {
    "name": "detect_voicemail_and_end_call",
    "description": (
        "Use when you suspect the caller is a voicemail or answering machine. "
        "This tool will give the caller one opportunity to respond as a human before ending the call. "
        "Provide the cues that informed your decision and optionally customize the confirmation message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "voicemail_cues": {
                "type": "string",
                "description": (
                    "Brief note describing the audio/text cues indicating voicemail "
                    "(e.g., 'automated greeting', 'beep', 'no live response', 'machine-like tone')."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Optional confidence score between 0 and 1 for voicemail detection.",
            },
            "confirmation_message": {
                "type": "string",
                "description": (
                    "Optional custom message to give the caller one chance to respond as a human. "
                    "If not provided, a default polite confirmation will be used."
                ),
            },
        },
        "required": ["voicemail_cues"],
        "additionalProperties": False,
    },
}

confirm_voicemail_schema: Dict[str, Any] = {
    "name": "confirm_voicemail_and_end_call",
    "description": (
        "Use ONLY after calling detect_voicemail_and_end_call when no human response is received. "
        "This confirms the voicemail detection and gracefully terminates the call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "confirmation_reason": {
                "type": "string",
                "description": (
                    "Brief explanation of why you're confirming this is a voicemail "
                    "(e.g., 'no response to confirmation request', 'continued automated message')."
                ),
            },
        },
        "required": ["confirmation_reason"],
        "additionalProperties": False,
    },
}
