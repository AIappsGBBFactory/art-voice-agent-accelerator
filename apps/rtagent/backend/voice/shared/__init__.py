"""
Voice Shared Modules
=====================

Shared data classes and configuration utilities for voice channel orchestrators.

Contents:
    - OrchestratorContext: Context passed to orchestrator for each turn
    - OrchestratorResult: Result from an orchestrator turn
    - resolve_orchestrator_config: Scenario-aware configuration resolution
    - resolve_from_app_state: Configuration from FastAPI app.state

Usage:
    from apps.rtagent.backend.voice.shared import (
        OrchestratorContext,
        OrchestratorResult,
        resolve_orchestrator_config,
        DEFAULT_START_AGENT,
    )
"""

# Shared dataclasses
from .base import (
    OrchestratorContext,
    OrchestratorResult,
)

# Config resolution
from .config_resolver import (
    DEFAULT_START_AGENT,
    SCENARIO_ENV_VAR,
    OrchestratorConfigResult,
    resolve_orchestrator_config,
    resolve_from_app_state,
    get_scenario_greeting,
)

__all__ = [
    # Context/Result (shared data classes)
    "OrchestratorContext",
    "OrchestratorResult",
    # Config Resolution
    "DEFAULT_START_AGENT",
    "SCENARIO_ENV_VAR",
    "OrchestratorConfigResult",
    "resolve_orchestrator_config",
    "resolve_from_app_state",
    "get_scenario_greeting",
]
