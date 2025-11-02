from typing import Any, Callable, Dict, List

from apps.rtagent.backend.src.agents.artagent.tool_store.emergency import escalate_emergency
from apps.rtagent.backend.src.agents.artagent.tool_store.handoffs import (
    escalate_human,
    handoff_fraud_agent,
    handoff_transfer_agency_agent,
)

# Retail Tools
from apps.rtagent.backend.src.agents.artagent.tool_store.retail_product_tools import (
    search_products_general,
    search_products_filtered,
    check_product_availability,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.retail_handoffs import (
    handoff_to_stylist,
    handoff_to_postsale,
    handoff_to_concierge,
    stylist_handoff_to_postsale,
    escalate_to_human as retail_escalate_to_human,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.retail_checkout_tools import (
    initiate_checkout,
    apply_membership_discount,
    get_shipping_options,
    process_payment,
    create_order,
    get_order_status,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.retail_store_info_tools import (
    get_product_details,
    get_pricing_for_tier,
    check_current_promotions,
    get_store_hours,
    get_return_policy,
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
    create_transaction_dispute,
)
from apps.rtagent.backend.src.agents.artagent.tool_store.transfer_agency_tools import (
    get_client_data,
    get_drip_positions,
    check_compliance_status,
    calculate_liquidation_proceeds,
    handoff_to_compliance,
    handoff_to_trading,
)
from utils.ml_logging import get_logger

log = get_logger("tools_helper")

from apps.rtagent.backend.src.agents.artagent.tool_store.schemas import (
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
)

# Retail Tool Schemas
from apps.rtagent.backend.src.agents.artagent.tool_store.retail_schemas import (
    search_products_general_schema,
    search_products_filtered_schema,
    check_product_availability_schema,
    handoff_to_stylist_schema,
    handoff_to_postsale_schema,
    handoff_to_concierge_schema,
    escalate_to_human_schema as retail_escalate_to_human_schema,
    initiate_checkout_schema,
    apply_membership_discount_schema,
    get_shipping_options_schema,
    process_payment_schema,
    create_order_schema,
    get_order_status_schema,
    get_product_details_schema,
    get_pricing_for_tier_schema,
    check_current_promotions_schema,
    get_store_hours_schema,
    get_return_policy_schema,
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
    # Retail Product Search Tools
    "search_products_general": search_products_general,
    "search_products_filtered": search_products_filtered,
    "check_product_availability": check_product_availability,
    # Retail Handoff Tools
    "handoff_to_stylist": handoff_to_stylist,
    "handoff_to_postsale": handoff_to_postsale,
    "handoff_to_concierge": handoff_to_concierge,
    "stylist_handoff_to_postsale": stylist_handoff_to_postsale,
    # Retail Checkout Tools
    "initiate_checkout": initiate_checkout,
    "apply_membership_discount": apply_membership_discount,
    "get_shipping_options": get_shipping_options,
    "process_payment": process_payment,
    "create_order": create_order,
    "get_order_status": get_order_status,
    # Retail Store Info Tools
    "get_product_details": get_product_details,
    "get_pricing_for_tier": get_pricing_for_tier,
    "check_current_promotions": check_current_promotions,
    "get_store_hours": get_store_hours,
    "get_return_policy": get_return_policy,
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
    # Retail Product Search Tools
    {"type": "function", "function": search_products_general_schema},
    {"type": "function", "function": search_products_filtered_schema},
    {"type": "function", "function": check_product_availability_schema},
    # Retail Handoff Tools
    {"type": "function", "function": handoff_to_stylist_schema},
    {"type": "function", "function": handoff_to_postsale_schema},
    {"type": "function", "function": handoff_to_concierge_schema},
    {"type": "function", "function": retail_escalate_to_human_schema},
    # Retail Checkout Tools
    {"type": "function", "function": initiate_checkout_schema},
    {"type": "function", "function": apply_membership_discount_schema},
    {"type": "function", "function": get_shipping_options_schema},
    {"type": "function", "function": process_payment_schema},
    {"type": "function", "function": create_order_schema},
    {"type": "function", "function": get_order_status_schema},
    # Retail Store Info Tools
    {"type": "function", "function": get_product_details_schema},
    {"type": "function", "function": get_pricing_for_tier_schema},
    {"type": "function", "function": check_current_promotions_schema},
    {"type": "function", "function": get_store_hours_schema},
    {"type": "function", "function": get_return_policy_schema},
]

TOOL_REGISTRY: dict[str, dict] = {t["function"]["name"]: t for t in available_tools}
