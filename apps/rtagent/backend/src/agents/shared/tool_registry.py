"""
Unified Tool Registry
=====================

Central registry for all agent tools (ARTAgent + VLAgent).
Provides a single source of truth for tool schemas and implementations.

Usage:
    from apps.rtagent.backend.src.agents.shared.tool_registry import (
        TOOL_REGISTRY,
        FUNCTION_MAPPING,
        get_tool_schema,
        get_tool_executor,
        list_tools,
    )
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, TypeAlias, Union

from pydantic import BaseModel

from utils.ml_logging import get_logger

logger = get_logger("shared.tool_registry")

# Type aliases
ToolExecutor: TypeAlias = Callable[..., Any]
AsyncToolExecutor: TypeAlias = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class ToolDefinition:
    """Complete tool definition with schema and executor."""

    name: str
    schema: Dict[str, Any]
    executor: ToolExecutor
    is_handoff: bool = False
    description: str = ""
    tags: Set[str] = field(default_factory=set)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY STATE
# ═══════════════════════════════════════════════════════════════════════════════

_TOOL_DEFINITIONS: Dict[str, ToolDefinition] = {}
_INITIALIZED: bool = False


def register_tool(
    name: str,
    schema: Dict[str, Any],
    executor: ToolExecutor,
    *,
    is_handoff: bool = False,
    tags: Optional[Set[str]] = None,
    override: bool = False,
) -> None:
    """
    Register a tool with schema and executor.

    :param name: Unique tool name
    :param schema: OpenAI-compatible function schema
    :param executor: Callable implementation (sync or async)
    :param is_handoff: True if tool triggers agent handoff
    :param tags: Optional categorization tags (e.g., {'banking', 'auth'})
    :param override: If True, allow overriding existing registration
    """
    if name in _TOOL_DEFINITIONS and not override:
        logger.debug("Tool '%s' already registered, skipping", name)
        return

    _TOOL_DEFINITIONS[name] = ToolDefinition(
        name=name,
        schema=schema,
        executor=executor,
        is_handoff=is_handoff,
        description=schema.get("description", ""),
        tags=tags or set(),
    )
    logger.debug("Registered tool: %s (handoff=%s)", name, is_handoff)


def get_tool_schema(name: str) -> Optional[Dict[str, Any]]:
    """Get the schema for a registered tool."""
    defn = _TOOL_DEFINITIONS.get(name)
    return defn.schema if defn else None


def get_tool_executor(name: str) -> Optional[ToolExecutor]:
    """Get the executor for a registered tool."""
    defn = _TOOL_DEFINITIONS.get(name)
    return defn.executor if defn else None


def get_tool_definition(name: str) -> Optional[ToolDefinition]:
    """Get the complete definition for a tool."""
    return _TOOL_DEFINITIONS.get(name)


def is_handoff_tool(name: str) -> bool:
    """Check if a tool triggers agent handoff."""
    defn = _TOOL_DEFINITIONS.get(name)
    return defn.is_handoff if defn else False


def list_tools(*, tags: Optional[Set[str]] = None, handoffs_only: bool = False) -> List[str]:
    """
    List registered tool names with optional filtering.

    :param tags: Only return tools with ALL specified tags
    :param handoffs_only: Only return handoff tools
    """
    result = []
    for name, defn in _TOOL_DEFINITIONS.items():
        if handoffs_only and not defn.is_handoff:
            continue
        if tags and not tags.issubset(defn.tags):
            continue
        result.append(name)
    return result


def get_tools_for_agent(tool_names: List[str]) -> List[Dict[str, Any]]:
    """
    Build OpenAI-compatible tool list for specified tools.

    :param tool_names: List of tool names to include
    :return: List of {"type": "function", "function": schema} dicts
    """
    tools = []
    for name in tool_names:
        defn = _TOOL_DEFINITIONS.get(name)
        if defn:
            tools.append({"type": "function", "function": defn.schema})
        else:
            logger.warning("Tool '%s' not found in registry", name)
    return tools


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _prepare_args(
    fn: Callable[..., Any], raw_args: Dict[str, Any]
) -> Tuple[List[Any], Dict[str, Any]]:
    """Coerce dict arguments into the tool's declared signature."""
    signature = inspect.signature(fn)
    params = list(signature.parameters.values())

    if not params:
        return [], {}

    if len(params) == 1:
        param = params[0]
        annotation = param.annotation
        if annotation is not inspect._empty and inspect.isclass(annotation):
            try:
                if issubclass(annotation, BaseModel):
                    return [annotation(**raw_args)], {}
            except TypeError:
                pass
        return [raw_args], {}

    return [], raw_args


async def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a registered tool with the given arguments.

    Handles both sync and async executors.
    """
    defn = _TOOL_DEFINITIONS.get(name)
    if not defn:
        return {
            "success": False,
            "error": f"Tool '{name}' not found",
            "message": f"Tool '{name}' is not registered.",
        }

    fn = defn.executor
    positional, keyword = _prepare_args(fn, arguments)

    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(*positional, **keyword)
        else:
            result = await asyncio.to_thread(fn, *positional, **keyword)

        # Normalize result
        if isinstance(result, dict):
            return result
        return {"success": True, "result": result}

    except Exception as exc:
        logger.exception("Tool '%s' execution failed", name)
        return {
            "success": False,
            "error": str(exc),
            "message": f"Tool execution failed: {exc}",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

# These provide backwards compatibility with existing code

@property
def TOOL_REGISTRY() -> Dict[str, Dict[str, Any]]:
    """Legacy: dict of {name: {"type": "function", "function": schema}}."""
    return {
        name: {"type": "function", "function": defn.schema}
        for name, defn in _TOOL_DEFINITIONS.items()
    }


@property  
def FUNCTION_MAPPING() -> Dict[str, ToolExecutor]:
    """Legacy: dict of {name: executor}."""
    return {name: defn.executor for name, defn in _TOOL_DEFINITIONS.items()}


def get_legacy_tool_registry() -> Dict[str, Dict[str, Any]]:
    """Get legacy TOOL_REGISTRY format."""
    return {
        name: {"type": "function", "function": defn.schema}
        for name, defn in _TOOL_DEFINITIONS.items()
    }


def get_legacy_function_mapping() -> Dict[str, ToolExecutor]:
    """Get legacy function_mapping format."""
    return {name: defn.executor for name, defn in _TOOL_DEFINITIONS.items()}


def get_legacy_available_tools() -> List[Dict[str, Any]]:
    """Get legacy available_tools list format."""
    return [
        {"type": "function", "function": defn.schema}
        for defn in _TOOL_DEFINITIONS.values()
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def initialize_tools() -> int:
    """
    Load and register all tools from both ARTAgent and VLAgent tool stores.

    Returns the number of tools registered.
    """
    global _INITIALIZED

    if _INITIALIZED:
        logger.debug("Tools already initialized, skipping")
        return len(_TOOL_DEFINITIONS)

    # Import tool modules - this triggers their registration
    _register_core_tools()
    _register_banking_tools()
    _register_investment_tools()
    _register_financial_tools()

    _INITIALIZED = True
    logger.info("Unified tool registry initialized with %d tools", len(_TOOL_DEFINITIONS))
    return len(_TOOL_DEFINITIONS)


def _register_core_tools() -> None:
    """Register core financial services tools (auth, fraud, transfer agency)."""
    # Import implementations from VLAgent tool store (more complete)
    from apps.rtagent.backend.src.agents.vlagent.tool_store.emergency import (
        escalate_emergency,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.handoffs import (
        escalate_human,
        handoff_fraud_agent,
        handoff_transfer_agency_agent,
    )
    from apps.rtagent.backend.src.agents.vlagent.handoffs import (
        handoff_to_auth,
        handoff_paypal_agent,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.financial_mfa_auth import (
        verify_client_identity,
        verify_fraud_client_identity,
        send_mfa_code,
        verify_mfa_code,
        check_transaction_authorization,
        resend_mfa_code,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.fraud_detection import (
        analyze_recent_transactions,
        check_suspicious_activity,
        create_fraud_case,
        block_card_emergency,
        provide_fraud_education,
        ship_replacement_card,
        send_fraud_case_email,
        create_transaction_dispute,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.transfer_agency_tools import (
        get_client_data,
        get_drip_positions,
        check_compliance_status,
        calculate_liquidation_proceeds,
        handoff_to_compliance,
        handoff_to_trading,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.voicemail import (
        detect_voicemail_and_end_call,
        confirm_voicemail_and_end_call,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.call_transfer import (
        TRANSFER_CALL_SCHEMA,
        transfer_call_to_destination,
        TRANSFER_CALL_CENTER_SCHEMA,
        transfer_call_to_call_center,
    )

    # Import schemas
    from apps.rtagent.backend.src.agents.vlagent.tool_store.schemas import (
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
        get_client_data_schema,
        get_drip_positions_schema,
        check_compliance_status_schema,
        calculate_liquidation_proceeds_schema,
        handoff_to_compliance_schema,
        handoff_to_trading_schema,
        handoff_to_auth_schema,
        handoff_paypal_agent_schema,
        detect_voicemail_schema,
        confirm_voicemail_schema,
    )

    # Emergency & Escalation
    register_tool("escalate_emergency", escalate_emergency_schema, escalate_emergency, tags={"emergency"})
    register_tool("escalate_human", escalate_human_schema, escalate_human, is_handoff=True, tags={"escalation"})

    # Authentication & MFA
    register_tool("verify_client_identity", verify_client_identity_schema, verify_client_identity, tags={"auth"})
    register_tool("verify_fraud_client_identity", verify_fraud_client_identity_schema, verify_fraud_client_identity, tags={"auth", "fraud"})
    register_tool("send_mfa_code", send_mfa_code_schema, send_mfa_code, tags={"auth", "mfa"})
    register_tool("verify_mfa_code", verify_mfa_code_schema, verify_mfa_code, tags={"auth", "mfa"})
    register_tool("resend_mfa_code", resend_mfa_code_schema, resend_mfa_code, tags={"auth", "mfa"})
    register_tool("check_transaction_authorization", check_transaction_authorization_schema, check_transaction_authorization, tags={"auth"})

    # Fraud Detection
    register_tool("analyze_recent_transactions", analyze_recent_transactions_schema, analyze_recent_transactions, tags={"fraud"})
    register_tool("check_suspicious_activity", check_suspicious_activity_schema, check_suspicious_activity, tags={"fraud"})
    register_tool("create_fraud_case", create_fraud_case_schema, create_fraud_case, is_handoff=True, tags={"fraud"})
    register_tool("block_card_emergency", block_card_emergency_schema, block_card_emergency, tags={"fraud", "emergency"})
    register_tool("provide_fraud_education", provide_fraud_education_schema, provide_fraud_education, tags={"fraud"})
    register_tool("ship_replacement_card", ship_replacement_card_schema, ship_replacement_card, tags={"fraud"})
    register_tool("send_fraud_case_email", send_fraud_case_email_schema, send_fraud_case_email, tags={"fraud"})
    register_tool("create_transaction_dispute", create_transaction_dispute_schema, create_transaction_dispute, tags={"fraud"})

    # Transfer Agency
    register_tool("get_client_data", get_client_data_schema, get_client_data, tags={"transfer_agency"})
    register_tool("get_drip_positions", get_drip_positions_schema, get_drip_positions, tags={"transfer_agency"})
    register_tool("check_compliance_status", check_compliance_status_schema, check_compliance_status, tags={"transfer_agency", "compliance"})
    register_tool("calculate_liquidation_proceeds", calculate_liquidation_proceeds_schema, calculate_liquidation_proceeds, tags={"transfer_agency"})
    register_tool("handoff_to_compliance", handoff_to_compliance_schema, handoff_to_compliance, is_handoff=True, tags={"transfer_agency", "handoff"})
    register_tool("handoff_to_trading", handoff_to_trading_schema, handoff_to_trading, is_handoff=True, tags={"transfer_agency", "handoff"})

    # Agent Handoffs
    register_tool("handoff_fraud_agent", handoff_fraud_agent_schema, handoff_fraud_agent, is_handoff=True, tags={"handoff"})
    register_tool("handoff_transfer_agency_agent", handoff_transfer_agency_agent_schema, handoff_transfer_agency_agent, is_handoff=True, tags={"handoff"})
    register_tool("handoff_to_auth", handoff_to_auth_schema, handoff_to_auth, is_handoff=True, tags={"handoff"})
    register_tool("handoff_paypal_agent", handoff_paypal_agent_schema, handoff_paypal_agent, is_handoff=True, tags={"handoff"})

    # Voicemail Detection
    register_tool("detect_voicemail_and_end_call", detect_voicemail_schema, detect_voicemail_and_end_call, tags={"voicemail"})
    register_tool("confirm_voicemail_and_end_call", confirm_voicemail_schema, confirm_voicemail_and_end_call, tags={"voicemail"})

    # Call Transfer
    register_tool("transfer_call_to_destination", TRANSFER_CALL_SCHEMA, transfer_call_to_destination, tags={"call_transfer"})
    register_tool("transfer_call_to_call_center", TRANSFER_CALL_CENTER_SCHEMA, transfer_call_to_call_center, tags={"call_transfer"})


def _register_banking_tools() -> None:
    """Register banking-specific tools."""
    from apps.rtagent.backend.src.agents.vlagent.tool_store.banking_tools import (
        get_user_profile,
        get_account_summary,
        get_recent_transactions,
        search_card_products,
        get_card_details,
        get_retirement_accounts,
        search_rollover_guidance,
        refund_fee,
        handoff_merrill_advisor,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.banking_esign_tools import (
        send_card_agreement,
        verify_esignature,
        finalize_card_application,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.banking_handoffs import (
        handoff_card_recommendation,
        handoff_investment_advisor,
        handoff_erica_concierge,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.schemas import (
        get_user_profile_schema,
        get_account_summary_schema,
        get_recent_transactions_schema,
        search_card_products_schema,
        get_card_details_schema,
        send_card_agreement_schema,
        verify_esignature_schema,
        finalize_card_application_schema,
        get_retirement_accounts_schema,
        search_rollover_guidance_schema,
        refund_fee_schema,
        handoff_card_recommendation_schema,
        handoff_investment_advisor_schema,
        handoff_erica_concierge_schema,
        handoff_merrill_advisor_schema,
    )

    # Banking account tools
    register_tool("get_user_profile", get_user_profile_schema, get_user_profile, tags={"banking"})
    register_tool("get_account_summary", get_account_summary_schema, get_account_summary, tags={"banking"})
    register_tool("get_recent_transactions", get_recent_transactions_schema, get_recent_transactions, tags={"banking"})
    register_tool("search_card_products", search_card_products_schema, search_card_products, tags={"banking", "cards"})
    register_tool("get_card_details", get_card_details_schema, get_card_details, tags={"banking", "cards"})
    register_tool("get_retirement_accounts", get_retirement_accounts_schema, get_retirement_accounts, tags={"banking", "retirement"})
    register_tool("search_rollover_guidance", search_rollover_guidance_schema, search_rollover_guidance, tags={"banking", "retirement"})
    register_tool("refund_fee", refund_fee_schema, refund_fee, tags={"banking"})

    # E-signature tools
    register_tool("send_card_agreement", send_card_agreement_schema, send_card_agreement, tags={"banking", "esign"})
    register_tool("verify_esignature", verify_esignature_schema, verify_esignature, tags={"banking", "esign"})
    register_tool("finalize_card_application", finalize_card_application_schema, finalize_card_application, tags={"banking", "esign"})

    # Banking handoffs
    register_tool("handoff_card_recommendation", handoff_card_recommendation_schema, handoff_card_recommendation, is_handoff=True, tags={"banking", "handoff"})
    register_tool("handoff_investment_advisor", handoff_investment_advisor_schema, handoff_investment_advisor, is_handoff=True, tags={"banking", "handoff"})
    register_tool("handoff_erica_concierge", handoff_erica_concierge_schema, handoff_erica_concierge, is_handoff=True, tags={"banking", "handoff"})
    register_tool("handoff_merrill_advisor", handoff_merrill_advisor_schema, handoff_merrill_advisor, is_handoff=True, tags={"banking", "handoff"})


def _register_investment_tools() -> None:
    """Register investment-specific tools."""
    from apps.rtagent.backend.src.agents.vlagent.tool_store.investment_tools import (
        get_account_routing_info,
        get_401k_details,
        get_rollover_options,
        calculate_tax_impact,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.schemas import (
        get_account_routing_info_schema,
        get_401k_details_schema,
        get_rollover_options_schema,
        calculate_tax_impact_schema,
    )

    register_tool("get_account_routing_info", get_account_routing_info_schema, get_account_routing_info, tags={"investment"})
    register_tool("get_401k_details", get_401k_details_schema, get_401k_details, tags={"investment", "retirement"})
    register_tool("get_rollover_options", get_rollover_options_schema, get_rollover_options, tags={"investment", "retirement"})
    register_tool("calculate_tax_impact", calculate_tax_impact_schema, calculate_tax_impact, tags={"investment"})


def _register_financial_tools() -> None:
    """Register financial tools (PayPal, knowledge base, etc.)."""
    from apps.rtagent.backend.src.agents.vlagent.financial_tools import (
        _execute_search_knowledge_base,
    )
    from apps.rtagent.backend.src.agents.vlagent.tool_store.schemas import (
        get_paypal_account_summary_schema,
        search_knowledge_base_schema,
    )

    # Knowledge base search
    register_tool("search_knowledge_base", search_knowledge_base_schema, _execute_search_knowledge_base, tags={"knowledge_base", "search"})


__all__ = [
    "register_tool",
    "get_tool_schema",
    "get_tool_executor",
    "get_tool_definition",
    "is_handoff_tool",
    "list_tools",
    "get_tools_for_agent",
    "execute_tool",
    "initialize_tools",
    # Legacy compatibility
    "get_legacy_tool_registry",
    "get_legacy_function_mapping",
    "get_legacy_available_tools",
    # Types
    "ToolDefinition",
    "ToolExecutor",
]
