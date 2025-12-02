from typing import Any, Callable, Dict, List

from apps.artagent.backend.src.agents.stiched_agents.tool_store.emergency import escalate_emergency
from apps.artagent.backend.src.agents.stiched_agents.tool_store.handoffs import (
    escalate_human,
    handoff_fraud_agent,
    handoff_transfer_agency_agent,
)

from apps.artagent.backend.src.agents.stiched_agents.tool_store.financial_mfa_auth import (
    verify_client_identity,
    verify_fraud_client_identity,
    send_mfa_code,
    verify_mfa_code,
    check_transaction_authorization,
    resend_mfa_code,
)
from apps.artagent.backend.src.agents.stiched_agents.tool_store.fraud_detection import (
    analyze_recent_transactions,
    check_suspicious_activity,
    create_fraud_case,
    block_card_emergency,
    provide_fraud_education,
    ship_replacement_card,
    send_fraud_case_email,
    create_transaction_dispute,
)
from apps.artagent.backend.src.agents.stiched_agents.tool_store.transfer_agency_tools import (
    get_client_data,
    get_drip_positions,
    check_compliance_status,
    calculate_liquidation_proceeds,
    handoff_to_compliance,
    handoff_to_trading,
)
from apps.artagent.backend.src.agents.stiched_agents.tool_store.voicemail import (
    detect_voicemail_and_end_call,
    confirm_voicemail_and_end_call,
)
from utils.ml_logging import get_logger

log = get_logger("tools_helper")

from apps.artagent.backend.src.agents.stiched_agents.tool_store.schemas import (
    escalate_emergency_schema,
    escalate_human_schema,
    handoff_fraud_agent_schema,
    handoff_transfer_agency_agent_schema,
    verify_client_identity_schema,
    verify_fraud_client_identity_schema,
    send_mfa_code_schema,
    verify_mfa_code_schema,
    resend_mfa_code_schema,
    check_transaction_authorization_schema,
    analyze_recent_transactions_schema,
    check_suspicious_activity_schema,
    create_fraud_case_schema,
    block_card_emergency_schema,
    provide_fraud_education_schema,
    ship_replacement_card_schema,
    send_fraud_case_email_schema,
    create_transaction_dispute_schema,
    # Transfer Agency Tools
    get_client_data_schema,
    get_drip_positions_schema,
    check_compliance_status_schema,
    calculate_liquidation_proceeds_schema,
    handoff_to_compliance_schema,
    handoff_to_trading_schema,
    find_information_schema,
    handoff_claim_schema,
    handoff_general_schema,
    record_fnol_schema,
    detect_voicemail_schema,
    confirm_voicemail_schema,
)

function_mapping: Dict[str, Callable[..., Any]] = {
    "escalate_emergency": escalate_emergency,
    "escalate_human": escalate_human,
    "handoff_fraud_agent": handoff_fraud_agent,
    "handoff_transfer_agency_agent": handoff_transfer_agency_agent,
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
    "create_transaction_dispute": create_transaction_dispute,
    # Transfer Agency Tools
    "get_client_data": get_client_data,
    "get_drip_positions": get_drip_positions,
    "check_compliance_status": check_compliance_status,
    "calculate_liquidation_proceeds": calculate_liquidation_proceeds,
    "handoff_to_compliance": handoff_to_compliance,
    "handoff_to_trading": handoff_to_trading,
    # "handoff_claim_agent": handoff_claim_agent,
    # "find_information_for_policy": find_information_for_policy,
    "detect_voicemail_and_end_call": detect_voicemail_and_end_call,
    "confirm_voicemail_and_end_call": confirm_voicemail_and_end_call,
}


available_tools: List[Dict[str, Any]] = [
    {"type": "function", "function": escalate_emergency_schema},
    {"type": "function", "function": escalate_human_schema},
    {"type": "function", "function": handoff_fraud_agent_schema},
    {"type": "function", "function": handoff_transfer_agency_agent_schema},
    {"type": "function", "function": verify_client_identity_schema},
    {"type": "function", "function": verify_fraud_client_identity_schema},
    {"type": "function", "function": send_mfa_code_schema},
    {"type": "function", "function": verify_mfa_code_schema},
    {"type": "function", "function": check_transaction_authorization_schema},
    {"type": "function", "function": resend_mfa_code_schema},
    # Fraud Detection Tools
    {"type": "function", "function": analyze_recent_transactions_schema},
    {"type": "function", "function": check_suspicious_activity_schema},
    {"type": "function", "function": create_fraud_case_schema},
    {"type": "function", "function": block_card_emergency_schema},
    {"type": "function", "function": provide_fraud_education_schema},
    {"type": "function", "function": ship_replacement_card_schema},
    {"type": "function", "function": send_fraud_case_email_schema},
    {"type": "function", "function": create_transaction_dispute_schema},
    # Transfer Agency Tools
    {"type": "function", "function": get_client_data_schema},
    {"type": "function", "function": get_drip_positions_schema},
    {"type": "function", "function": check_compliance_status_schema},
    {"type": "function", "function": calculate_liquidation_proceeds_schema},
    {"type": "function", "function": handoff_to_compliance_schema},
    {"type": "function", "function": handoff_to_trading_schema},
    # {"type": "function", "function": handoff_claim_schema},
    # {"type": "function", "function": find_information_schema},
    {"type": "function", "function": detect_voicemail_schema},
    {"type": "function", "function": confirm_voicemail_schema},
]

TOOL_REGISTRY: dict[str, dict] = {t["function"]["name"]: t for t in available_tools}
