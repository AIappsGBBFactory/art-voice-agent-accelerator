# registry.py
from __future__ import annotations
from typing import Dict
from apps.rtagent.backend.src.agents.vlagent.base import AzureVoiceLiveAgent, load_agents_from_folder

def load_registry(agents_dir: str = "agents") -> Dict[str, AzureVoiceLiveAgent]:
    """Load all agent YAMLs into a dict keyed by agent.name."""
    return load_agents_from_folder(agents_dir)

# Map function names → agent names in the registry
HANDOFF_MAP: Dict[str, str] = {
    "handoff_to_auth": "AuthAgent",
    "handoff_fraud_agent": "FraudAgent",
    "handoff_transfer_agency_agent": "TransferAgency",
    "handoff_to_compliance": "ComplianceDesk",
    "handoff_to_trading": "TradingDesk",
    "handoff_paypal_agent": "PayPalAgent",
}
