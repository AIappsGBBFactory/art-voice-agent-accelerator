"""
Session Scenario Registry
=========================

Centralized storage for session-scoped dynamic scenarios created via Scenario Builder.
This module is the single source of truth for session scenario state.

Session scenarios allow runtime customization of:
- Agent orchestration graph (handoffs between agents)
- Agent overrides (greetings, template vars)
- Starting agent
- Handoff behavior (announced vs discrete)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.artagent.backend.registries.scenariostore.loader import ScenarioConfig

logger = get_logger(__name__)

# Session-scoped dynamic scenarios: session_id -> ScenarioConfig
_session_scenarios: dict[str, ScenarioConfig] = {}

# Callback for notifying the orchestrator adapter of scenario updates
_scenario_update_callback: Callable[[str, ScenarioConfig], bool] | None = None


def register_scenario_update_callback(
    callback: Callable[[str, ScenarioConfig], bool]
) -> None:
    """
    Register a callback to be invoked when a session scenario is updated.

    This is called by the unified orchestrator to inject updates into live adapters.
    """
    global _scenario_update_callback
    _scenario_update_callback = callback
    logger.debug("Scenario update callback registered")


def get_session_scenario(session_id: str) -> ScenarioConfig | None:
    """Get dynamic scenario for a session."""
    return _session_scenarios.get(session_id)


def set_session_scenario(session_id: str, scenario: ScenarioConfig) -> None:
    """
    Set dynamic scenario for a session.

    This is the single integration point - it both:
    1. Stores the scenario in the local cache
    2. Notifies the orchestrator adapter (if callback registered)

    All downstream components (handoff routing, agent overrides) will
    automatically use the updated configuration.
    """
    _session_scenarios[session_id] = scenario

    # Notify the orchestrator adapter if callback is registered
    adapter_updated = False
    if _scenario_update_callback:
        try:
            adapter_updated = _scenario_update_callback(session_id, scenario)
        except Exception as e:
            logger.warning("Failed to update adapter with scenario: %s", e)

    logger.info(
        "Session scenario set | session=%s scenario=%s start_agent=%s agents=%d handoffs=%d adapter_updated=%s",
        session_id,
        scenario.name,
        scenario.start_agent,
        len(scenario.agents),
        len(scenario.handoffs),
        adapter_updated,
    )


def remove_session_scenario(session_id: str) -> bool:
    """Remove dynamic scenario for a session, returns True if removed."""
    if session_id in _session_scenarios:
        del _session_scenarios[session_id]
        logger.info("Session scenario removed | session=%s", session_id)
        return True
    return False


def list_session_scenarios() -> dict[str, ScenarioConfig]:
    """Return a copy of all session scenarios."""
    return dict(_session_scenarios)


__all__ = [
    "get_session_scenario",
    "set_session_scenario",
    "remove_session_scenario",
    "list_session_scenarios",
    "register_scenario_update_callback",
]
