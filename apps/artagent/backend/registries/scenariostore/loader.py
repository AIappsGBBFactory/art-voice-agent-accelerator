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

    # Tool overrides (add/remove)
    add_tools: list[str] = field(default_factory=list)
    remove_tools: list[str] = field(default_factory=list)

    # Template variable overrides for Jinja prompts
    template_vars: dict[str, Any] = field(default_factory=dict)

    # Voice overrides
    voice_name: str | None = None
    voice_rate: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentOverride:
        """Create from dictionary."""
        return cls(
            greeting=data.get("greeting"),
            return_greeting=data.get("return_greeting"),
            description=data.get("description"),
            add_tools=data.get("add_tools", []),
            remove_tools=data.get("remove_tools", []),
            template_vars=data.get("template_vars", {}),
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

    # Agent-specific overrides
    agent_overrides: dict[str, AgentOverride] = field(default_factory=dict)

    # Global template variables (applied to all agents)
    global_template_vars: dict[str, Any] = field(default_factory=dict)

    # Scenario-specific tools to register
    tools: list[str] = field(default_factory=list)

    # Starting agent override
    start_agent: str | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ScenarioConfig:
        """Create from dictionary."""
        agent_overrides = {}
        for agent_name, override_data in data.get("agent_overrides", {}).items():
            agent_overrides[agent_name] = AgentOverride.from_dict(override_data)

        return cls(
            name=name,
            description=data.get("description", ""),
            agents=data.get("agents", []),
            agent_overrides=agent_overrides,
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
        agents = {k: v for k, v in base_agents.items() if k in scenario.agents}
    else:
        agents = dict(base_agents)

    # Apply overrides
    for agent_name, override in scenario.agent_overrides.items():
        if agent_name not in agents:
            continue

        agent = agents[agent_name]

        # Apply simple overrides
        if override.greeting is not None:
            agent.greeting = override.greeting
        if override.return_greeting is not None:
            agent.return_greeting = override.return_greeting
        if override.description is not None:
            agent.description = override.description

        # Apply voice overrides
        if override.voice_name is not None:
            if hasattr(agent, "voice"):
                agent.voice["name"] = override.voice_name
        if override.voice_rate is not None:
            if hasattr(agent, "voice"):
                agent.voice["rate"] = override.voice_rate

        # Apply tool modifications
        if hasattr(agent, "tools"):
            current_tools = set(agent.tools or [])
            current_tools.update(override.add_tools)
            current_tools -= set(override.remove_tools)
            agent.tools = list(current_tools)

        # Merge template vars
        if hasattr(agent, "template_vars"):
            merged = dict(scenario.global_template_vars)
            merged.update(agent.template_vars or {})
            merged.update(override.template_vars)
            agent.template_vars = merged
        else:
            merged = dict(scenario.global_template_vars)
            merged.update(override.template_vars)
            agent.template_vars = merged

    return agents


def get_scenario_start_agent(scenario_name: str) -> str | None:
    """Get the starting agent for a scenario."""
    scenario = load_scenario(scenario_name)
    return scenario.start_agent if scenario else None


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
