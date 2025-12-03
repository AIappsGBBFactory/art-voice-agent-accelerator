"""
Agent Configuration Loader
==========================

Auto-discovers and loads agents from the modular folder structure.
Integrates with the shared tool registry for tool schemas and executors.

Usage:
    from apps.rtagent.agents.loader import discover_agents, build_handoff_map

    agents = discover_agents()
    handoffs = build_handoff_map(agents)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from apps.rtagent.agents.base import (
    UnifiedAgent,
    HandoffConfig,
    VoiceConfig,
    ModelConfig,
)
from utils.ml_logging import get_logger

logger = get_logger("agents.loader")

# Default path to agents directory
AGENTS_DIR = Path(__file__).parent

# Legacy alias for backward compatibility
AgentConfig = UnifiedAgent


# Legacy alias for backward compatibility
AgentConfig = UnifiedAgent


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge override into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_defaults(agents_dir: Path = AGENTS_DIR) -> Dict[str, Any]:
    """Load default configuration from _defaults.yaml."""
    defaults_file = agents_dir / "_defaults.yaml"
    if defaults_file.exists():
        with open(defaults_file, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_prompt(agent_dir: Path, prompt_value: str) -> str:
    """
    Load prompt content.

    If prompt_value ends with .jinja, .md, or .txt, load from file.
    Otherwise, treat as inline prompt.
    """
    if not prompt_value:
        return ""
    
    if prompt_value.endswith((".jinja", ".md", ".txt")):
        prompt_file = agent_dir / prompt_value
        if prompt_file.exists():
            return prompt_file.read_text()
        logger.warning("Prompt file not found: %s", prompt_file)
        return ""
    return prompt_value


def _extract_agent_identity(raw: Dict[str, Any], agent_dir: Path) -> Dict[str, Any]:
    """Extract agent identity fields from raw YAML, handling nested 'agent:' key."""
    # Support both flat and nested 'agent:' key
    agent_block = raw.get("agent", {})
    
    return {
        "name": agent_block.get("name") or raw.get("name") or agent_dir.name,
        "description": agent_block.get("description") or raw.get("description", ""),
        "greeting": agent_block.get("greeting") or raw.get("greeting", ""),
        "return_greeting": agent_block.get("return_greeting") or raw.get("return_greeting", ""),
    }


def _extract_prompt(raw: Dict[str, Any], agent_dir: Path) -> str:
    """Extract prompt from raw YAML, handling multiple formats."""
    # Check 'prompts:' block first
    prompts_block = raw.get("prompts", {})
    if prompts_block:
        # Check for 'content' (inline prompt)
        if prompts_block.get("content"):
            return prompts_block["content"]
        # Check for 'path' (file reference)
        if prompts_block.get("path"):
            return load_prompt(agent_dir, prompts_block["path"])
    
    # Check top-level 'prompt:' key
    if raw.get("prompt"):
        return load_prompt(agent_dir, raw["prompt"])
    
    return ""


def _extract_handoff_config(raw: Dict[str, Any]) -> HandoffConfig:
    """Extract handoff configuration from raw YAML."""
    # New-style: handoff: block
    if "handoff" in raw:
        return HandoffConfig.from_dict(raw["handoff"])
    
    # Legacy: handoff_trigger at top level
    if "handoff_trigger" in raw:
        return HandoffConfig(trigger=raw["handoff_trigger"])
    
    return HandoffConfig()


def load_agent(
    agent_file: Path,
    defaults: Dict[str, Any],
) -> UnifiedAgent:
    """Load a single agent from its agent.yaml file."""
    with open(agent_file, "r") as f:
        raw = yaml.safe_load(f) or {}

    agent_dir = agent_file.parent
    
    # Extract identity (handles nested 'agent:' block)
    identity = _extract_agent_identity(raw, agent_dir)

    # Merge with defaults for model, voice, session
    model_raw = _deep_merge(defaults.get("model", {}), raw.get("model", {}))
    voice_raw = _deep_merge(defaults.get("voice", {}), raw.get("voice", {}))
    session_raw = _deep_merge(defaults.get("session", {}), raw.get("session", {}))
    template_vars = _deep_merge(defaults.get("template_vars", {}), raw.get("template_vars", {}))
    
    # Handle voice inside session block (VoiceLive style)
    if "voice" in session_raw:
        voice_raw = _deep_merge(voice_raw, session_raw.pop("voice"))

    # Load prompt (handles multiple formats)
    prompt_template = _extract_prompt(raw, agent_dir)
    
    # Extract handoff config
    handoff = _extract_handoff_config(raw)

    return UnifiedAgent(
        name=identity["name"],
        description=identity["description"],
        greeting=identity["greeting"],
        return_greeting=identity["return_greeting"],
        handoff=handoff,
        model=ModelConfig.from_dict(model_raw),
        voice=VoiceConfig.from_dict(voice_raw),
        session=session_raw,
        prompt_template=prompt_template,
        tool_names=raw.get("tools", []),
        template_vars=template_vars,
        metadata=raw.get("metadata", {}),
        source_dir=agent_dir,
    )


def discover_agents(agents_dir: Path = AGENTS_DIR) -> Dict[str, UnifiedAgent]:
    """
    Auto-discover agents by scanning for agent.yaml files.

    Structure:
        agents/
          fraud_agent/agent.yaml  → FraudAgent
          auth_agent/agent.yaml   → AuthAgent
          ...

    Returns:
        Dict of agent_name → UnifiedAgent
    """
    agents: Dict[str, UnifiedAgent] = {}

    # Load shared config
    defaults = load_defaults(agents_dir)

    # Scan for agent folders
    for item in agents_dir.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("_") or item.name.startswith("."):
            continue
        if item.name in ("tools", "store", "__pycache__"):
            continue

        agent_file = item / "agent.yaml"
        if agent_file.exists():
            try:
                config = load_agent(agent_file, defaults)
                agents[config.name] = config
                logger.debug("Loaded agent: %s from %s", config.name, item.name)
            except Exception as e:
                logger.error("Failed to load agent from %s: %s", item, e)

    logger.info("Discovered %d agents: %s", len(agents), list(agents.keys()))
    return agents


def build_handoff_map(agents: Dict[str, UnifiedAgent]) -> Dict[str, str]:
    """
    Build handoff map from agent declarations.

    Each agent can declare a `handoff.trigger` which is the tool name
    that other agents use to transfer to this agent.

    Returns:
        Dict of tool_name → agent_name
    """
    handoff_map: Dict[str, str] = {}

    for agent in agents.values():
        if agent.handoff.trigger:
            handoff_map[agent.handoff.trigger] = agent.name

    logger.debug("Built handoff map: %s", handoff_map)
    return handoff_map


def get_agent(name: str, agents_dir: Path = AGENTS_DIR) -> Optional[UnifiedAgent]:
    """Load a single agent by name."""
    agents = discover_agents(agents_dir)
    return agents.get(name)


def list_agent_names(agents_dir: Path = AGENTS_DIR) -> List[str]:
    """List all discovered agent names."""
    agents = discover_agents(agents_dir)
    return list(agents.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def render_prompt(config: UnifiedAgent, context: Dict[str, Any]) -> str:
    """
    Render an agent's prompt template with context.

    Args:
        config: Agent configuration
        context: Runtime context (caller_name, customer_intelligence, etc.)

    Returns:
        Rendered prompt string
    """
    return config.render_prompt(context)


def get_agents_by_handoff_strategy(
    agents: Dict[str, UnifiedAgent],
    strategy: str,
) -> Dict[str, UnifiedAgent]:
    """
    Filter agents by handoff strategy.
    
    Args:
        agents: Dict of agents
        strategy: "auto", "tool_based", or "state_based"
    
    Returns:
        Filtered dict of agents
    """
    from apps.rtagent.agents.base import HandoffStrategy
    
    target_strategy = HandoffStrategy(strategy.lower())
    return {
        name: agent
        for name, agent in agents.items()
        if agent.handoff.strategy == target_strategy or agent.handoff.strategy == HandoffStrategy.AUTO
    }


__all__ = [
    "UnifiedAgent",
    "AgentConfig",  # Legacy alias
    "HandoffConfig",
    "discover_agents",
    "build_handoff_map",
    "get_agent",
    "list_agent_names",
    "load_defaults",
    "render_prompt",
    "get_agents_by_handoff_strategy",
]
