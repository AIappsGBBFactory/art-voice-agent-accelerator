"""
Use Case Configuration System
==============================

Defines available use cases and DTMF-based selection mechanism.
Each use case maps to a specific orchestrator with its own agents and tools.

DTMF Selection:
- Press 1: Insurance Claims
- Press 2: Healthcare Services  
- Press 3: Financial Services

Architecture:
- Each use case has its own orchestrator module in src/orchestration/
- Each use case has its own agents in src/agents/
- Factory pattern routes to appropriate orchestrator based on DTMF selection
"""

from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass


class UseCase(str, Enum):
    """Available use case scenarios."""
    
    INSURANCE = "insurance"
    HEALTHCARE = "healthcare"
    FINANCE = "finance"


@dataclass
class UseCaseConfig:
    """Configuration for a single use case."""
    
    use_case: UseCase
    dtmf_code: str
    display_name: str
    description: str
    orchestrator_module: str
    agents_module: str
    entry_agent: str
    greeting_text: str


# Use Case Registry
USE_CASE_REGISTRY: Dict[UseCase, UseCaseConfig] = {
    UseCase.INSURANCE: UseCaseConfig(
        use_case=UseCase.INSURANCE,
        dtmf_code="1",
        display_name="Insurance Claims",
        description="Handle insurance claims, policy inquiries, and general insurance questions",
        orchestrator_module="apps.rtagent.backend.src.orchestration.artagent.insuranceagents.orchestrator",
        agents_module="apps.rtagent.backend.src.agents.artagent.insuranceagents",
        entry_agent="AuthAgent",
        greeting_text="For Insurance Claims and Policy Services"
    ),
    UseCase.HEALTHCARE: UseCaseConfig(
        use_case=UseCase.HEALTHCARE,
        dtmf_code="2",
        display_name="Healthcare Services",
        description="Schedule appointments, check insurance benefits, and manage prescriptions",
        orchestrator_module="apps.rtagent.backend.src.orchestration.healthcareagent.orchestrator",
        agents_module="apps.rtagent.backend.src.agents.healthcareagent",
        entry_agent="AuthAgent",
        greeting_text="For Healthcare Appointments and Insurance Benefits"
    ),
    UseCase.FINANCE: UseCaseConfig(
        use_case=UseCase.FINANCE,
        dtmf_code="3",
        display_name="Financial Services",
        description="Manage accounts, loans, investments, and financial planning",
        orchestrator_module="apps.rtagent.backend.src.orchestration.financeagent.orchestrator",
        agents_module="apps.rtagent.backend.src.agents.financeagent",
        entry_agent="AuthAgent",
        greeting_text="For Banking, Loans, and Investment Services"
    ),
}


# DTMF to UseCase mapping
DTMF_TO_USE_CASE: Dict[str, UseCase] = {
    config.dtmf_code: use_case
    for use_case, config in USE_CASE_REGISTRY.items()
}


def get_use_case_from_dtmf(dtmf_code: str) -> Optional[UseCase]:
    """
    Get UseCase from DTMF code.
    
    Args:
        dtmf_code: DTMF digit pressed by user (1, 2, or 3)
        
    Returns:
        UseCase enum or None if invalid code
    """
    return DTMF_TO_USE_CASE.get(dtmf_code)


def get_use_case_config(use_case: UseCase) -> UseCaseConfig:
    """
    Get configuration for a use case.
    
    Args:
        use_case: UseCase enum
        
    Returns:
        UseCaseConfig with orchestrator paths and settings
        
    Raises:
        KeyError: If use case not found in registry
    """
    return USE_CASE_REGISTRY[use_case]


def get_selection_greeting() -> str:
    """
    Generate the initial greeting with DTMF selection menu.
    
    Returns:
        Greeting text with all available use case options
    """
    options = []
    for use_case in [UseCase.INSURANCE, UseCase.HEALTHCARE, UseCase.FINANCE]:
        config = USE_CASE_REGISTRY[use_case]
        options.append(f"Press {config.dtmf_code} {config.greeting_text}")
    
    greeting = (
        "Welcome to our automated service center. "
        "Please select from the following options: " +
        ", ".join(options) + "."
    )
    
    return greeting


# Memory context keys for use case tracking
USE_CASE_SELECTED_KEY = "use_case_selected"
USE_CASE_TYPE_KEY = "use_case_type"
USE_CASE_GREETING_SENT_KEY = "use_case_greeting_sent"
