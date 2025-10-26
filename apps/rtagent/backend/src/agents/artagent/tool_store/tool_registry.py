from typing import Any, Callable, Dict, List

from apps.rtagent.backend.src.agents.artagent.tool_store.auth import authenticate_caller
from apps.rtagent.backend.src.agents.artagent.tool_store.emergency import escalate_emergency
from apps.rtagent.backend.src.agents.artagent.tool_store.fnol import record_fnol
from apps.rtagent.backend.src.agents.artagent.tool_store.handoffs import (
    escalate_human,
    handoff_claim_agent,
    handoff_general_agent,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.policies import (
    find_information_for_policy,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.financial_mfa_auth import (
    verify_client_identity,
    verify_fraud_client_identity,
    send_mfa_code,
    verify_mfa_code,
    check_transaction_authorization,
    resend_mfa_code,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.fraud_detection import (
    analyze_recent_transactions,
    check_suspicious_activity,
    create_fraud_case,
    block_card_emergency,
    provide_fraud_education,
    ship_replacement_card,
    send_fraud_case_email,
)
from utils.ml_logging import get_logger

log = get_logger("tools_helper")

from apps.rtagent.backend.src.agents.artagent.tool_store.schemas import (
    authenticate_caller_schema,
    escalate_emergency_schema,
    escalate_human_schema,
    find_information_schema,
    handoff_claim_schema,
    handoff_general_schema,
    record_fnol_schema,
    verify_client_identity_schema,
    verify_fraud_client_identity_schema,
    send_mfa_code_schema,
    verify_mfa_code_schema,
    check_transaction_authorization_schema,
    analyze_recent_transactions_schema,
    check_suspicious_activity_schema,
    create_fraud_case_schema,
    block_card_emergency_schema,
    provide_fraud_education_schema,
    ship_replacement_card_schema,
    send_fraud_case_email_schema,
)

function_mapping: Dict[str, Callable[..., Any]] = {
    "record_fnol": record_fnol,
    "escalate_emergency": escalate_emergency,
    "authenticate_caller": authenticate_caller,
    "handoff_general_agent": handoff_general_agent,
    "escalate_human": escalate_human,
    "handoff_claim_agent": handoff_claim_agent,
    "find_information_for_policy": find_information_for_policy,
    "verify_client_identity": verify_client_identity,
    "verify_fraud_client_identity": verify_fraud_client_identity,
    "send_mfa_code": send_mfa_code,
    "verify_mfa_code": verify_mfa_code,
    "check_transaction_authorization": check_transaction_authorization,
    "resend_mfa_code": resend_mfa_code,
    # Fraud Detection Tools
    "analyze_recent_transactions": analyze_recent_transactions,
    "check_suspicious_activity": check_suspicious_activity,
    "create_fraud_case": create_fraud_case,
    "block_card_emergency": block_card_emergency,
    "provide_fraud_education": provide_fraud_education,
    "ship_replacement_card": ship_replacement_card,
    "send_fraud_case_email": send_fraud_case_email,
}


available_tools: List[Dict[str, Any]] = [
    {"type": "function", "function": record_fnol_schema},
    {"type": "function", "function": authenticate_caller_schema},
    {"type": "function", "function": escalate_emergency_schema},
    {"type": "function", "function": handoff_general_schema},
    {"type": "function", "function": escalate_human_schema},
    {"type": "function", "function": handoff_claim_schema},
    {"type": "function", "function": find_information_schema},
    {"type": "function", "function": verify_client_identity_schema},
    {"type": "function", "function": verify_fraud_client_identity_schema},
    {"type": "function", "function": send_mfa_code_schema},
    {"type": "function", "function": verify_mfa_code_schema},
    {"type": "function", "function": check_transaction_authorization_schema},
    {"type": "function", "function": send_mfa_code_schema},  # resend_mfa_code uses same schema
    # Fraud Detection Tools
    {"type": "function", "function": analyze_recent_transactions_schema},
    {"type": "function", "function": check_suspicious_activity_schema},
    {"type": "function", "function": create_fraud_case_schema},
    {"type": "function", "function": block_card_emergency_schema},
    {"type": "function", "function": provide_fraud_education_schema},
    {"type": "function", "function": ship_replacement_card_schema},
    {"type": "function", "function": send_fraud_case_email_schema},
]

TOOL_REGISTRY: dict[str, dict] = {t["function"]["name"]: t for t in available_tools}
