"""
Orchestrator Configuration Resolver
=====================================

Shared configuration resolution for voice channel orchestrators.
Provides scenario-aware agent and handoff map resolution.

CascadeOrchestratorAdapter and LiveOrchestrator use this resolver for:
- Start agent selection
- Agent registry loading
- Handoff map building
- Greeting configuration

Usage:
    from apps.rtagent.backend.voice.shared import (
        resolve_orchestrator_config,
        OrchestratorConfigResult,
    )
    
    # Resolve config (will use scenario if AGENT_SCENARIO is set)
    config = resolve_orchestrator_config()
    
    # Use resolved values
    adapter = CascadeOrchestratorAdapter.create(
        start_agent=config.start_agent,
        agents=config.agents,
        handoff_map=config.handoff_map,
    )
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from apps.rtagent.backend.agents.base import UnifiedAgent
    from apps.rtagent.backend.agents.scenarios.loader import ScenarioConfig

try:
    from utils.ml_logging import get_logger
    logger = get_logger("voice.shared.config_resolver")
except ImportError:
    import logging
    logger = logging.getLogger("voice.shared.config_resolver")


# ─────────────────────────────────────────────────────────────────────
# Default Configuration
# ─────────────────────────────────────────────────────────────────────

# Unified default start agent name (used by both adapters)
DEFAULT_START_AGENT = "Concierge"

# Environment variable for scenario selection
SCENARIO_ENV_VAR = "AGENT_SCENARIO"


# ─────────────────────────────────────────────────────────────────────
# Configuration Result
# ─────────────────────────────────────────────────────────────────────

@dataclass
class OrchestratorConfigResult:
    """
    Resolved orchestrator configuration.
    
    Contains all the configuration needed to initialize an orchestrator
    with scenario-aware defaults.
    
    Attributes:
        start_agent: Name of the starting agent
        agents: Registry of agent definitions
        handoff_map: Tool name → agent name mapping
        scenario: Optional loaded scenario config
        scenario_name: Name of the active scenario (if any)
        template_vars: Global template variables from scenario
    """
    
    start_agent: str = DEFAULT_START_AGENT
    agents: Dict[str, Any] = field(default_factory=dict)
    handoff_map: Dict[str, str] = field(default_factory=dict)
    scenario: Optional["ScenarioConfig"] = None
    scenario_name: Optional[str] = None
    template_vars: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def has_scenario(self) -> bool:
        """Whether a scenario is active."""
        return self.scenario is not None
    
    def get_agent(self, name: str) -> Optional[Any]:
        """Get an agent by name."""
        return self.agents.get(name)
    
    def get_start_agent_config(self) -> Optional[Any]:
        """Get the starting agent configuration."""
        return self.agents.get(self.start_agent)


# ─────────────────────────────────────────────────────────────────────
# Resolution Functions
# ─────────────────────────────────────────────────────────────────────

def _load_base_agents() -> Dict[str, Any]:
    """Load agents from the unified agent registry."""
    try:
        from apps.rtagent.backend.agents.loader import discover_agents
        return discover_agents()
    except ImportError as e:
        logger.warning("Failed to import discover_agents: %s", e)
        return {}


def _build_base_handoff_map(agents: Dict[str, Any]) -> Dict[str, str]:
    """Build handoff map from agent declarations."""
    try:
        from apps.rtagent.backend.agents.loader import build_handoff_map
        return build_handoff_map(agents)
    except ImportError as e:
        logger.warning("Failed to import build_handoff_map: %s", e)
        return {}


def _load_scenario(scenario_name: str) -> Optional["ScenarioConfig"]:
    """Load a scenario configuration."""
    try:
        from apps.rtagent.backend.agents.scenarios import load_scenario
        return load_scenario(scenario_name)
    except ImportError as e:
        logger.warning("Failed to import load_scenario: %s", e)
        return None


def _get_scenario_agents(scenario_name: str) -> Dict[str, Any]:
    """Get agents with scenario overrides applied."""
    try:
        from apps.rtagent.backend.agents.scenarios import get_scenario_agents
        return get_scenario_agents(scenario_name)
    except ImportError as e:
        logger.warning("Failed to import get_scenario_agents: %s", e)
        return _load_base_agents()


def resolve_orchestrator_config(
    *,
    scenario_name: Optional[str] = None,
    start_agent: Optional[str] = None,
    agents: Optional[Dict[str, Any]] = None,
    handoff_map: Optional[Dict[str, str]] = None,
) -> OrchestratorConfigResult:
    """
    Resolve orchestrator configuration with scenario support.
    
    Resolution order:
    1. Explicit parameters (if provided)
    2. Scenario configuration (if AGENT_SCENARIO env var is set)
    3. Default values
    
    Args:
        scenario_name: Override scenario name (defaults to AGENT_SCENARIO env var)
        start_agent: Override start agent (defaults to scenario or DEFAULT_START_AGENT)
        agents: Override agent registry (defaults to scenario-aware loading)
        handoff_map: Override handoff map (defaults to building from agents)
        
    Returns:
        OrchestratorConfigResult with resolved configuration
    """
    result = OrchestratorConfigResult()
    
    # Determine scenario name
    effective_scenario = scenario_name or os.getenv(SCENARIO_ENV_VAR, "").strip()
    
    if effective_scenario:
        # Load scenario
        scenario = _load_scenario(effective_scenario)
        
        if scenario:
            result.scenario = scenario
            result.scenario_name = effective_scenario
            result.template_vars = scenario.global_template_vars.copy()
            
            # Use scenario start_agent if not explicitly overridden
            if start_agent is None and scenario.start_agent:
                result.start_agent = scenario.start_agent
            
            # Load agents with scenario overrides if not explicitly provided
            if agents is None:
                result.agents = _get_scenario_agents(effective_scenario)
            
            logger.info(
                "Resolved config with scenario",
                extra={
                    "scenario": effective_scenario,
                    "start_agent": result.start_agent,
                    "agent_count": len(result.agents),
                },
            )
        else:
            logger.warning(
                "Scenario '%s' not found, using defaults",
                effective_scenario,
            )
            # Fall back to base agents
            if agents is None:
                result.agents = _load_base_agents()
    else:
        # No scenario - use base agents
        if agents is None:
            result.agents = _load_base_agents()
    
    # Apply explicit overrides
    if agents is not None:
        result.agents = agents
    
    if start_agent is not None:
        result.start_agent = start_agent
    
    # Build handoff map if not provided
    if handoff_map is not None:
        result.handoff_map = handoff_map
    else:
        result.handoff_map = _build_base_handoff_map(result.agents)
    
    # Validate start agent exists
    if result.start_agent and result.agents and result.start_agent not in result.agents:
        available = list(result.agents.keys())[:5]
        logger.warning(
            "Start agent '%s' not found in registry. Available: %s",
            result.start_agent,
            available,
        )
        # Fall back to first available or default
        if available:
            result.start_agent = available[0]
            logger.info("Falling back to start agent: %s", result.start_agent)
    
    return result


def get_scenario_greeting(
    agent_name: str,
    config: OrchestratorConfigResult,
    is_first_visit: bool = True,
) -> Optional[str]:
    """
    Get greeting for an agent from scenario config.
    
    Args:
        agent_name: Name of the agent
        config: Resolved orchestrator config
        is_first_visit: Whether this is the first visit to this agent
        
    Returns:
        Greeting string or None if not configured
    """
    agent = config.get_agent(agent_name)
    if not agent:
        return None
    
    if is_first_visit:
        return getattr(agent, "greeting", None)
    return getattr(agent, "return_greeting", None)


# ─────────────────────────────────────────────────────────────────────
# App State Integration
# ─────────────────────────────────────────────────────────────────────

def resolve_from_app_state(app_state: Any) -> OrchestratorConfigResult:
    """
    Resolve configuration from FastAPI app.state.
    
    Uses pre-loaded agents and scenario from main.py startup.
    
    Args:
        app_state: FastAPI app.state object
        
    Returns:
        OrchestratorConfigResult from app state
    """
    result = OrchestratorConfigResult()
    
    # Get unified agents from app.state
    result.agents = getattr(app_state, "unified_agents", None) or {}
    
    # Get handoff map from app.state
    result.handoff_map = getattr(app_state, "handoff_map", None) or {}
    
    # Get scenario from app.state
    result.scenario = getattr(app_state, "scenario", None)
    if result.scenario:
        result.scenario_name = result.scenario.name
        result.template_vars = result.scenario.global_template_vars.copy()
    
    # Get start agent from app.state
    result.start_agent = getattr(app_state, "start_agent", DEFAULT_START_AGENT)
    
    # Build handoff map if not available
    if not result.handoff_map and result.agents:
        result.handoff_map = _build_base_handoff_map(result.agents)
    
    return result


__all__ = [
    "DEFAULT_START_AGENT",
    "SCENARIO_ENV_VAR",
    "OrchestratorConfigResult",
    "resolve_orchestrator_config",
    "resolve_from_app_state",
    "get_scenario_greeting",
]
