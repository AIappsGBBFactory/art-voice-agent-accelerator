# registry.py
from __future__ import annotations

import warnings
from typing import Dict

from apps.rtagent.backend.src.agents.vlagent.base import AzureVoiceLiveAgent, load_agents_from_folder

def load_registry(agents_dir: str = "agents") -> Dict[str, AzureVoiceLiveAgent]:
    """Load all agent YAMLs into a dict keyed by agent.name."""
    return load_agents_from_folder(agents_dir)

# HANDOFF_MAP has moved to voice_channels.handoffs.registry
# Re-export for backward compatibility
from apps.rtagent.backend.voice_channels.handoffs.registry import HANDOFF_MAP

# Note: For new code, import directly from the canonical location:
#   from apps.rtagent.backend.voice_channels.handoffs import HANDOFF_MAP
