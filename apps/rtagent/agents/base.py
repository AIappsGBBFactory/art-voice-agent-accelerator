"""
UnifiedAgent Base Class
=======================

Orchestrator-agnostic agent that works with both:
- SpeechCascade (gpt_flow) → State-based handoffs
- VoiceLive (LiveOrchestrator) → Tool-based handoffs

The agent itself doesn't know which orchestrator will run it.
The orchestrator adapter handles the translation.

Usage:
    from apps.rtagent.agents.base import UnifiedAgent, HandoffConfig
    
    agent = UnifiedAgent(
        name="FraudAgent",
        description="Fraud detection specialist",
        handoff=HandoffConfig(trigger="handoff_fraud_agent"),
        tool_names=["analyze_transactions", "block_card"],
    )
    
    # Get tools from shared registry
    tools = agent.get_tools()
    
    # Render prompt with runtime context
    prompt = agent.render_prompt({"caller_name": "John", "client_id": "123"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from jinja2 import Template

from utils.ml_logging import get_logger

logger = get_logger("agents.base")


class HandoffStrategy(str, Enum):
    """
    Handoff strategy determines how agent transfers are handled.
    
    - AUTO: Works with any orchestrator (recommended)
    - TOOL_BASED: LLM calls handoff tools (VoiceLive pattern)
    - STATE_BASED: Code updates MemoManager state (SpeechCascade pattern)
    """
    AUTO = "auto"
    TOOL_BASED = "tool_based"
    STATE_BASED = "state_based"


@dataclass
class HandoffConfig:
    """
    Handoff configuration for an agent.
    
    Attributes:
        trigger: Tool name that routes TO this agent (e.g., "handoff_fraud_agent")
        strategy: How handoffs are executed (auto, tool_based, state_based)
        state_key: MemoManager key for state-based handoffs
    """
    trigger: str = ""
    strategy: HandoffStrategy = HandoffStrategy.AUTO
    state_key: str = "pending_handoff"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HandoffConfig":
        """Create HandoffConfig from dict (YAML parsing)."""
        if not data:
            return cls()
        
        strategy_str = data.get("strategy", "auto").lower()
        try:
            strategy = HandoffStrategy(strategy_str)
        except ValueError:
            logger.warning("Unknown handoff strategy '%s', defaulting to auto", strategy_str)
            strategy = HandoffStrategy.AUTO
        
        return cls(
            trigger=data.get("trigger", ""),
            strategy=strategy,
            state_key=data.get("state_key", "pending_handoff"),
        )


@dataclass
class VoiceConfig:
    """Voice configuration for TTS."""
    name: str = "en-US-ShimmerTurboMultilingualNeural"
    type: str = "azure-standard"
    style: str = "chat"
    rate: str = "+0%"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceConfig":
        """Create VoiceConfig from dict."""
        if not data:
            return cls()
        return cls(
            name=data.get("name", cls.name),
            type=data.get("type", cls.type),
            style=data.get("style", cls.style),
            rate=data.get("rate", cls.rate),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "name": self.name,
            "type": self.type,
            "style": self.style,
            "rate": self.rate,
        }


@dataclass
class ModelConfig:
    """Model configuration for LLM."""
    deployment_id: str = "gpt-4o"
    name: str = "gpt-4o"  # Alias for deployment_id
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 4096
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        """Create ModelConfig from dict."""
        if not data:
            return cls()
        deployment_id = data.get("deployment_id", data.get("name", cls.deployment_id))
        return cls(
            deployment_id=deployment_id,
            name=data.get("name", deployment_id),
            temperature=float(data.get("temperature", cls.temperature)),
            top_p=float(data.get("top_p", cls.top_p)),
            max_tokens=int(data.get("max_tokens", cls.max_tokens)),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "deployment_id": self.deployment_id,
            "name": self.name,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }


@dataclass
class UnifiedAgent:
    """
    Orchestrator-agnostic agent configuration.
    
    Works with both:
    - SpeechCascade (gpt_flow) → State-based handoffs
    - VoiceLive (LiveOrchestrator) → Tool-based handoffs
    
    The agent itself doesn't know which orchestrator will run it.
    The orchestrator adapter handles the translation.
    """
    
    # ─────────────────────────────────────────────────────────────────
    # Identity
    # ─────────────────────────────────────────────────────────────────
    name: str
    description: str = ""
    
    # ─────────────────────────────────────────────────────────────────
    # Greetings
    # ─────────────────────────────────────────────────────────────────
    greeting: str = ""
    return_greeting: str = ""
    
    # ─────────────────────────────────────────────────────────────────
    # Handoff Configuration
    # ─────────────────────────────────────────────────────────────────
    handoff: HandoffConfig = field(default_factory=HandoffConfig)
    
    # ─────────────────────────────────────────────────────────────────
    # Model Settings
    # ─────────────────────────────────────────────────────────────────
    model: ModelConfig = field(default_factory=ModelConfig)
    
    # ─────────────────────────────────────────────────────────────────
    # Voice Settings (TTS)
    # ─────────────────────────────────────────────────────────────────
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    
    # ─────────────────────────────────────────────────────────────────
    # Session Settings (VoiceLive-specific)
    # ─────────────────────────────────────────────────────────────────
    session: Dict[str, Any] = field(default_factory=dict)
    
    # ─────────────────────────────────────────────────────────────────
    # Prompt
    # ─────────────────────────────────────────────────────────────────
    prompt_template: str = ""
    
    # ─────────────────────────────────────────────────────────────────
    # Tools
    # ─────────────────────────────────────────────────────────────────
    tool_names: List[str] = field(default_factory=list)
    
    # ─────────────────────────────────────────────────────────────────
    # Template Variables (for prompt rendering)
    # ─────────────────────────────────────────────────────────────────
    template_vars: Dict[str, Any] = field(default_factory=dict)
    
    # ─────────────────────────────────────────────────────────────────
    # Metadata
    # ─────────────────────────────────────────────────────────────────
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_dir: Optional[Path] = None
    
    # ═══════════════════════════════════════════════════════════════════
    # TOOL INTEGRATION (via shared registry)
    # ═══════════════════════════════════════════════════════════════════
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        Get OpenAI-compatible tool schemas from shared registry.
        
        Returns:
            List of {"type": "function", "function": {...}} dicts
        """
        from apps.rtagent.agents.tools import get_tools_for_agent, initialize_tools
        initialize_tools()
        return get_tools_for_agent(self.tool_names)
    
    def get_tool_executor(self, tool_name: str) -> Optional[Callable]:
        """Get the executor function for a specific tool."""
        from apps.rtagent.agents.tools import get_tool_executor, initialize_tools
        initialize_tools()
        return get_tool_executor(tool_name)
    
    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name with the given arguments."""
        from apps.rtagent.agents.tools import execute_tool, initialize_tools
        initialize_tools()
        return await execute_tool(tool_name, args)
    
    # ═══════════════════════════════════════════════════════════════════
    # PROMPT RENDERING
    # ═══════════════════════════════════════════════════════════════════
    
    def render_prompt(self, context: Dict[str, Any]) -> str:
        """
        Render prompt template with runtime context.
        
        Args:
            context: Runtime context (caller_name, customer_intelligence, etc.)
        
        Returns:
            Rendered prompt string
        """
        # Merge template_vars with runtime context
        full_context = {**self.template_vars, **context}
        
        try:
            template = Template(self.prompt_template)
            return template.render(**full_context)
        except Exception as e:
            logger.error("Failed to render prompt for %s: %s", self.name, e)
            return self.prompt_template
    
    # ═══════════════════════════════════════════════════════════════════
    # HANDOFF HELPERS
    # ═══════════════════════════════════════════════════════════════════
    
    def get_handoff_tools(self) -> List[str]:
        """Get list of handoff tool names this agent can call."""
        return [t for t in self.tool_names if t.startswith("handoff_")]
    
    def can_handoff_to(self, agent_name: str) -> bool:
        """Check if this agent has a handoff tool for the target."""
        trigger = f"handoff_{agent_name.lower()}"
        return any(trigger in t.lower() for t in self.tool_names)
    
    def is_handoff_target(self, tool_name: str) -> bool:
        """Check if the given tool name routes to this agent."""
        return self.handoff.trigger == tool_name
    
    # ═══════════════════════════════════════════════════════════════════
    # CONVENIENCE PROPERTIES
    # ═══════════════════════════════════════════════════════════════════
    
    @property
    def model_id(self) -> str:
        """Alias for model.deployment_id for backward compatibility."""
        return self.model.deployment_id
    
    @property
    def temperature(self) -> float:
        """Alias for model.temperature for backward compatibility."""
        return self.model.temperature
    
    @property
    def voice_name(self) -> str:
        """Alias for voice.name for backward compatibility."""
        return self.voice.name
    
    @property
    def handoff_trigger(self) -> str:
        """Alias for handoff.trigger for backward compatibility."""
        return self.handoff.trigger
    
    def __repr__(self) -> str:
        return (
            f"UnifiedAgent(name={self.name!r}, "
            f"tools={len(self.tool_names)}, "
            f"handoff_trigger={self.handoff.trigger!r})"
        )


def build_handoff_map(agents: Dict[str, "UnifiedAgent"]) -> Dict[str, str]:
    """
    Build handoff map from agent declarations.
    
    Each agent can declare a `handoff.trigger` which is the tool name
    that other agents use to transfer to this agent.
    
    Args:
        agents: Dict of agent_name → UnifiedAgent
        
    Returns:
        Dict of tool_name → agent_name
    """
    handoff_map: Dict[str, str] = {}
    for agent in agents.values():
        if agent.handoff.trigger:
            handoff_map[agent.handoff.trigger] = agent.name
    return handoff_map


__all__ = [
    "UnifiedAgent",
    "HandoffConfig",
    "HandoffStrategy",
    "VoiceConfig",
    "ModelConfig",
    "build_handoff_map",
]
