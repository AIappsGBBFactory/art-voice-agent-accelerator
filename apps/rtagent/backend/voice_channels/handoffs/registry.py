"""
Handoff Registry
================

Central configuration for handoff tool → agent mappings.

This registry maps LLM tool names to agent names in the system.
When the LLM calls a handoff tool, the orchestrator looks up the
target agent here.

Usage:
    from voice_channels.handoffs import HANDOFF_MAP, ToolBasedHandoff

    strategy = ToolBasedHandoff(handoff_map=HANDOFF_MAP)

Adding New Handoffs:
    1. Add the tool to the agent's YAML file under `tools:`
    2. Add the mapping here: "tool_name": "AgentName"
    3. Ensure the target agent exists in the agents/ directory

Note:
    Agent names must match the `name` field in the agent YAML files.
    Tool names must match the function names defined in agent tools.
"""

from __future__ import annotations

from typing import Dict

# =============================================================================
# HANDOFF_MAP: Tool name → Agent name mappings
# =============================================================================
#
# This is the central registry for all handoff tool mappings.
# The keys are tool names that the LLM can call, and the values
# are the agent names to switch to.
#
# Categories:
# - Auth/Security agents
# - Banking specialists
# - Investment/Trading agents
# - External service integrations

HANDOFF_MAP: Dict[str, str] = {
    # ─────────────────────────────────────────────────────────────────
    # Auth & Security
    # ─────────────────────────────────────────────────────────────────
    "handoff_to_auth": "AuthAgent",
    "handoff_fraud_agent": "FraudAgent",
    "create_fraud_case": "FraudAgent",
    # ─────────────────────────────────────────────────────────────────
    # Banking Specialists
    # ─────────────────────────────────────────────────────────────────
    "handoff_card_recommendation": "CardRecommendation",
    "handoff_investment_advisor": "InvestmentAdvisor",
    "handoff_erica_concierge": "EricaConcierge",
    "handoff_transfer_agency_agent": "TransferAgencyAgent",
    # ─────────────────────────────────────────────────────────────────
    # Trading & Compliance
    # ─────────────────────────────────────────────────────────────────
    "handoff_to_trading": "TradingDesk",
    "handoff_to_compliance": "ComplianceDesk",
    # ─────────────────────────────────────────────────────────────────
    # External Integrations
    # ─────────────────────────────────────────────────────────────────
    "handoff_paypal_agent": "PayPalAgent",
}


def get_handoff_target(tool_name: str) -> str | None:
    """
    Get the target agent for a handoff tool.

    Args:
        tool_name: Name of the handoff tool

    Returns:
        Agent name if found, None otherwise
    """
    return HANDOFF_MAP.get(tool_name)


def is_handoff_tool(tool_name: str) -> bool:
    """
    Check if a tool name is a registered handoff.

    Args:
        tool_name: Name of the tool to check

    Returns:
        True if tool is in HANDOFF_MAP
    """
    return tool_name in HANDOFF_MAP


def register_handoff(tool_name: str, agent_name: str) -> None:
    """
    Register a new handoff mapping at runtime.

    Args:
        tool_name: Name of the handoff tool
        agent_name: Target agent name

    Example:
        register_handoff("handoff_new_specialist", "NewSpecialistAgent")
    """
    HANDOFF_MAP[tool_name] = agent_name


def list_handoffs() -> Dict[str, str]:
    """
    Get a copy of all registered handoffs.

    Returns:
        Copy of HANDOFF_MAP
    """
    return dict(HANDOFF_MAP)


__all__ = [
    "HANDOFF_MAP",
    "get_handoff_target",
    "is_handoff_tool",
    "register_handoff",
    "list_handoffs",
]
