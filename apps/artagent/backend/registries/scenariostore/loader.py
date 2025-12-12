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
class HandoffConfig:
    """Configuration for a handoff route - a directed edge in the agent graph.

    Each handoff is a complete edge definition:
    - FROM which agent initiates the handoff
    - TO which agent receives the handoff
    - TOOL what tool name triggers this route
    - TYPE discrete (silent) or announced (greeting)

    This allows different behavior for the same tool depending on context.
    Example: handoff_concierge from FraudAgent might be discrete (returning),
    but from AuthAgent might be announced (first routing).

    Attributes:
        from_agent: Source agent initiating the handoff
        to_agent: Target agent receiving the handoff
        tool: The handoff tool name that triggers this route
        type: "discrete" (silent) or "announced" (greet on switch)
        share_context: Whether to pass conversation context (default True)
    """

    from_agent: str = ""
    to_agent: str = ""
    tool: str = ""
    type: str = "announced"  # "discrete" or "announced"
    share_context: bool = True

    @property
    def greet_on_switch(self) -> bool:
        """Convenience property - announced means greet on switch."""
        return self.type == "announced"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffConfig:
        """Create from dictionary."""
        # Handle 'type' field - can be "discrete" or "announced"
        handoff_type = data.get("type", "announced")
        # Also support greet_on_switch for backward compatibility
        if "greet_on_switch" in data and "type" not in data:
            handoff_type = "announced" if data["greet_on_switch"] else "discrete"

        return cls(
            from_agent=data.get("from", data.get("from_agent", "")),
            to_agent=data.get("to", data.get("to_agent", "")),
            tool=data.get("tool", data.get("tool_name", "")),
            type=handoff_type,
            share_context=data.get("share_context", True),
        )


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

    # Default handoff behavior for this scenario
    # "announced" = target agent greets/announces transfer (default)
    # "discrete" = silent handoff, agent continues naturally
    handoff_type: str = "announced"

    # Handoff configurations - list of directed edges (from → to via tool)
    handoffs: list[HandoffConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ScenarioConfig:
        """Create from dictionary."""
        agent_defaults = None
        if "agent_defaults" in data:
            agent_defaults = AgentOverride.from_dict(data.get("agent_defaults") or {})

        # Parse handoff configurations as list of edges
        handoffs: list[HandoffConfig] = []
        raw_handoffs = data.get("handoffs", [])
        if isinstance(raw_handoffs, list):
            # New format: list of {from, to, tool, type, share_context}
            for h in raw_handoffs:
                if isinstance(h, dict) and h.get("from") and h.get("to"):
                    handoffs.append(HandoffConfig.from_dict(h))

        return cls(
            name=name,
            description=data.get("description", ""),
            agents=data.get("agents", []),
            agent_defaults=agent_defaults,
            global_template_vars=data.get("template_vars", {}),
            tools=data.get("tools", []),
            start_agent=data.get("start_agent"),
            handoff_type=data.get("handoff_type", "announced"),
            handoffs=handoffs,
        )

    def get_handoff_config(
        self,
        from_agent: str,
        tool_name: str | None = None,
        to_agent: str | None = None,
    ) -> HandoffConfig:
        """
        Get handoff config for a specific route.

        Lookup priority:
        1. Match by (from_agent, tool_name) - most specific
        2. Match by (from_agent, to_agent) - if tool not specified
        3. Match by tool_name only - fallback
        4. Return default based on scenario's handoff_type
        """
        # Priority 1: Match by from + tool
        if tool_name:
            for h in self.handoffs:
                if h.from_agent == from_agent and h.tool == tool_name:
                    return h

        # Priority 2: Match by from + to
        if to_agent:
            for h in self.handoffs:
                if h.from_agent == from_agent and h.to_agent == to_agent:
                    return h

        # Priority 3: Match by tool only (any source)
        if tool_name:
            for h in self.handoffs:
                if h.tool == tool_name:
                    return h

        # Default based on scenario's handoff_type
        return HandoffConfig(
            from_agent=from_agent,
            to_agent=to_agent or "",
            tool=tool_name or "",
            type=self.handoff_type,
            share_context=True,
        )

    def build_handoff_map(self) -> dict[str, str]:
        """Build tool→agent routing map from handoff configurations."""
        handoff_map: dict[str, str] = {}
        for h in self.handoffs:
            if h.tool and h.to_agent:
                # Note: If same tool appears multiple times, last one wins
                # This is fine since tool→agent mapping should be consistent
                handoff_map[h.tool] = h.to_agent
        return handoff_map


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

_SCENARIOS: dict[str, ScenarioConfig] = {}
_SCENARIOS_DIR = Path(__file__).parent


def _load_scenario_file(scenario_dir: Path) -> ScenarioConfig | None:
    """Load a scenario from its directory."""
    # Support both naming conventions: scenario.yaml and orchestration.yaml
    config_path = scenario_dir / "scenario.yaml"
    if not config_path.exists():
        config_path = scenario_dir / "orchestration.yaml"
    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        scenario = ScenarioConfig.from_dict(scenario_dir.name, data)
        logger.debug("Loaded scenario: %s from %s", scenario.name, config_path.name)
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


def get_handoff_config(
    scenario_name: str | None,
    from_agent: str,
    tool_name: str,
) -> HandoffConfig:
    """
    Get handoff configuration for a specific handoff route.

    Looks up the handoff config by (from_agent, tool_name) to find the
    exact route behavior. Falls back to scenario defaults if not found.

    Args:
        scenario_name: Active scenario name (or None)
        from_agent: The agent initiating the handoff
        tool_name: The handoff tool name being called

    Returns:
        HandoffConfig with from_agent, to_agent, type, share_context
    """
    if not scenario_name:
        # No scenario - use default announced behavior
        return HandoffConfig(
            from_agent=from_agent,
            tool=tool_name,
            type="announced",
            share_context=True,
        )

    scenario = load_scenario(scenario_name)
    if not scenario:
        return HandoffConfig(
            from_agent=from_agent,
            tool=tool_name,
            type="announced",
            share_context=True,
        )

    return scenario.get_handoff_config(from_agent=from_agent, tool_name=tool_name)


def build_handoff_map_from_scenario(scenario_name: str | None) -> dict[str, str]:
    """
    Build handoff_map (tool_name → agent_name) from scenario configuration.

    This replaces the agent-level handoff.trigger approach. The scenario
    is now the single source of truth for handoff routing.

    Args:
        scenario_name: Active scenario name (or None for empty map)

    Returns:
        Dict mapping handoff tool names to target agent names
    """
    if not scenario_name:
        return {}

    scenario = load_scenario(scenario_name)
    if not scenario:
        return {}

    return scenario.build_handoff_map()


__all__ = [
    "load_scenario",
    "list_scenarios",
    "get_scenario_agents",
    "get_scenario_start_agent",
    "get_scenario_template_vars",
    "get_handoff_config",
    "build_handoff_map_from_scenario",
    "ScenarioConfig",
    "AgentOverride",
    "HandoffConfig",
]
