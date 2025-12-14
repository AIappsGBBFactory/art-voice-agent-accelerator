"""
Voice Shared Modules
=====================

Shared data classes and configuration utilities for voice channel orchestrators.

Contents:
    - OrchestratorContext: Context passed to orchestrator for each turn
    - OrchestratorResult: Result from an orchestrator turn
    - resolve_orchestrator_config: Scenario-aware configuration resolution
    - resolve_from_app_state: Configuration from FastAPI app.state
    - SessionStateKeys: Standard keys for MemoManager state
    - sync_state_from_memo: Load session state from MemoManager
    - sync_state_to_memo: Persist session state to MemoManager

Usage:
    from apps.artagent.backend.voice.shared import (
        OrchestratorContext,
        OrchestratorResult,
        resolve_orchestrator_config,
        SessionStateKeys,
        sync_state_from_memo,
        sync_state_to_memo,
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
    get_scenario_greeting,
    resolve_from_app_state,
    resolve_orchestrator_config,
)

# Session state sync (shared between orchestrators)
from .session_state import (
    SessionState,
    SessionStateKeys,
    sync_state_from_memo,
    sync_state_to_memo,
)

# Handoff service (unified handoff resolution)
from .handoff_service import (
    HandoffResolution,
    HandoffService,
    create_handoff_service,
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
    # Session State Sync
    "SessionStateKeys",
    "SessionState",
    "sync_state_from_memo",
    "sync_state_to_memo",
    # Handoff Service
    "HandoffService",
    "HandoffResolution",
    "create_handoff_service",
]
