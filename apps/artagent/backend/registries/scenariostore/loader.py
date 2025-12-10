"""
Scenario Loader
===============

Loads scenario configurations and applies agent overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from utils.ml_logging import get_logger

logger = get_logger("agents.scenarios.loader")


@dataclass
class AgentOverride:
    """Override settings for a specific agent in a scenario."""

    # Core overrides
    greeting: str | None = None
    return_greeting: str | None = None
    description: str | None = None

    # Template variable overrides for Jinja prompts
    template_vars: dict[str, Any] = field(default_factory=dict)

    # Voice overrides
    voice_name: str | None = None
    voice_rate: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentOverride:
        """Create from dictionary.

        Unknown top-level keys are treated as template vars for convenience.
        """
        known_keys = {
            "greeting",
            "return_greeting",
            "description",
            "template_vars",
            "voice",
        }

        template_vars = dict(data.get("template_vars") or {})
        extra_template_vars = {k: v for k, v in data.items() if k not in known_keys}
        template_vars.update(extra_template_vars)
        return cls(
            greeting=data.get("greeting"),
            return_greeting=data.get("return_greeting"),
            description=data.get("description"),
            template_vars=template_vars,
            voice_name=data.get("voice", {}).get("name"),
            voice_rate=data.get("voice", {}).get("rate"),
        )


@dataclass
class ScenarioConfig:
    """Complete scenario configuration."""

    name: str
    description: str = ""

    # Which agents to include (if empty, include all)
    agents: list[str] = field(default_factory=list)

    # Global overrides applied to every agent
    agent_defaults: AgentOverride | None = None

    # Global template variables (applied to all agents)
    global_template_vars: dict[str, Any] = field(default_factory=dict)

    # Scenario-specific tools to register
    tools: list[str] = field(default_factory=list)

    # Starting agent override
    start_agent: str | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ScenarioConfig:
        """Create from dictionary."""
        agent_defaults = None
        if "agent_defaults" in data:
            agent_defaults = AgentOverride.from_dict(data.get("agent_defaults") or {})

        return cls(
            name=name,
            description=data.get("description", ""),
            agents=data.get("agents", []),
            agent_defaults=agent_defaults,
            global_template_vars=data.get("template_vars", {}),
            tools=data.get("tools", []),
            start_agent=data.get("start_agent"),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

_SCENARIOS: dict[str, ScenarioConfig] = {}
_SCENARIOS_DIR = Path(__file__).parent


def _load_scenario_file(scenario_dir: Path) -> ScenarioConfig | None:
    """Load a scenario from its directory."""
    config_path = scenario_dir / "scenario.yaml"
    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        scenario = ScenarioConfig.from_dict(scenario_dir.name, data)
        logger.debug("Loaded scenario: %s", scenario.name)
        return scenario

    except Exception as e:
        logger.error("Failed to load scenario %s: %s", scenario_dir.name, e)
        return None


def _discover_scenarios() -> None:
    """Discover and load all scenario configurations."""
    global _SCENARIOS

    if _SCENARIOS:
        return  # Already loaded

    for item in _SCENARIOS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            scenario = _load_scenario_file(item)
            if scenario:
                _SCENARIOS[scenario.name] = scenario

    logger.info("Discovered %d scenarios", len(_SCENARIOS))


def load_scenario(name: str) -> ScenarioConfig | None:
    """
    Load a scenario configuration by name.

    Args:
        name: Scenario name (directory name)

    Returns:
        ScenarioConfig or None if not found
    """
    _discover_scenarios()
    return _SCENARIOS.get(name)


def list_scenarios() -> list[str]:
    """List available scenario names."""
    _discover_scenarios()
    return list(_SCENARIOS.keys())


def get_scenario_agents(
    scenario_name: str,
    base_agents: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Get agents with scenario overrides applied.

    Args:
        scenario_name: Name of the scenario
        base_agents: Base agent registry (if None, loads from discover_agents)

    Returns:
        Dictionary of agents with overrides applied
    """
    scenario = load_scenario(scenario_name)
    if not scenario:
        logger.warning("Scenario '%s' not found", scenario_name)
        return base_agents or {}

    # Load base agents if not provided
    if base_agents is None:
        from apps.artagent.backend.registries.agentstore.loader import discover_agents

        base_agents = discover_agents()

    # Filter agents if scenario specifies a subset
    if scenario.agents:
        requested = set(scenario.agents)
        agents = {k: v for k, v in base_agents.items() if k in requested}

        # Warn if requested agents are missing and fall back to base registry
        if not agents:
            logger.warning(
                "Scenario '%s' agents not found in registry; using base agents instead",
                scenario_name,
                extra={"requested_agents": sorted(requested)},
            )
            agents = dict(base_agents)
        else:
            missing = requested - set(agents.keys())
            if missing:
                logger.warning(
                    "Scenario '%s' missing agents not found in registry: %s",
                    scenario_name,
                    sorted(missing),
                )
    else:
        agents = dict(base_agents)

    # Apply global defaults (no per-agent overrides)
    for agent in agents.values():
        merged = dict(scenario.global_template_vars)

        if scenario.agent_defaults:
            override = scenario.agent_defaults

            if override.greeting is not None:
                agent.greeting = override.greeting
            if override.return_greeting is not None:
                agent.return_greeting = override.return_greeting
            if override.description is not None:
                agent.description = override.description

            if override.voice_name is not None and hasattr(agent, "voice"):
                agent.voice["name"] = override.voice_name
            if override.voice_rate is not None and hasattr(agent, "voice"):
                agent.voice["rate"] = override.voice_rate

            merged.update(override.template_vars)

        if hasattr(agent, "template_vars"):
            merged.update(agent.template_vars or {})
            agent.template_vars = merged
        else:
            agent.template_vars = merged

    return agents


def get_scenario_start_agent(scenario_name: str) -> str | None:
    """Get the starting agent for a scenario."""
    scenario = load_scenario(scenario_name)
    if not scenario:
        return None

    if scenario.start_agent and scenario.agents:
        if scenario.start_agent in scenario.agents:
            return scenario.start_agent
        logger.warning(
            "start_agent '%s' is not in declared agents %s; using first agent",
            scenario.start_agent,
            scenario.agents,
        )
        return scenario.agents[0]

    return scenario.start_agent or (scenario.agents[0] if scenario.agents else None)


def get_scenario_template_vars(scenario_name: str) -> dict[str, Any]:
    """Get global template variables for a scenario."""
    scenario = load_scenario(scenario_name)
    return scenario.global_template_vars if scenario else {}


__all__ = [
    "load_scenario",
    "list_scenarios",
    "get_scenario_agents",
    "get_scenario_start_agent",
    "get_scenario_template_vars",
    "ScenarioConfig",
    "AgentOverride",
]
