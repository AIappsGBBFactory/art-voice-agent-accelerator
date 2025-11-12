# registry.py
from __future__ import annotations
from typing import Dict
from apps.rtagent.backend.src.agents.vlagent.base import AzureLiveVoiceAgent, load_agents_from_folder

def load_registry(agents_dir: str = "agents") -> Dict[str, AzureLiveVoiceAgent]:
    """Load all agent YAMLs into a dict keyed by agent.name."""
    return load_agents_from_folder(agents_dir)

# Map function names → agent names in the registry
HANDOFF_MAP: Dict[str, str] = {
    "handoff_to_scheduler": "Scheduler",
    "handoff_to_insurance": "Insurance",
    "handoff_to_auth": "AuthAgent",
}
