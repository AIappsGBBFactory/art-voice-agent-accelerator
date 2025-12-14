"""
UnifiedAgent Base Class
=======================

Orchestrator-agnostic agent that works with both:
- SpeechCascade (gpt_flow) → State-based handoffs
- VoiceLive (LiveOrchestrator) → Tool-based handoffs

The agent itself doesn't know which orchestrator will run it.
The orchestrator adapter handles the translation.

Usage:
    from apps.artagent.agents.base import UnifiedAgent, HandoffConfig

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

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Template
from utils.ml_logging import get_logger

logger = get_logger("agents.base")


@dataclass
class HandoffConfig:
    """
    Handoff configuration for an agent.

    Attributes:
        trigger: Tool name that routes TO this agent (e.g., "handoff_fraud_agent")
        is_entry_point: Whether this agent is the default starting agent
    """

    trigger: str = ""
    is_entry_point: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffConfig:
        """Create HandoffConfig from dict (YAML parsing)."""
        if not data:
            return cls()

        return cls(
            trigger=data.get("trigger", ""),
            is_entry_point=data.get("is_entry_point", False),
        )


@dataclass
class VoiceConfig:
    """Voice configuration for TTS."""

    name: str = "en-US-ShimmerTurboMultilingualNeural"
    type: str = "azure-standard"
    style: str = "chat"
    rate: str = "+0%"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceConfig:
        """Create VoiceConfig from dict."""
        if not data:
            return cls()
        return cls(
            name=data.get("name", cls.name),
            type=data.get("type", cls.type),
            style=data.get("style", cls.style),
            rate=data.get("rate", cls.rate),
        )

    def to_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "deployment_id": self.deployment_id,
            "name": self.name,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }


@dataclass
class SpeechConfig:
    """
    Speech recognition (STT) configuration for the agent.

    Controls VAD, segmentation, language detection, and other speech processing settings.
    These settings affect how the speech recognizer processes incoming audio.
    """

    # VAD (Voice Activity Detection)
    vad_silence_timeout_ms: int = 800  # Silence duration before finalizing recognition
    use_semantic_segmentation: bool = False  # Enable semantic sentence boundary detection

    # Language settings
    candidate_languages: list[str] = field(
        default_factory=lambda: ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT"]
    )

    # Advanced features
    enable_diarization: bool = False  # Speaker diarization for multi-speaker scenarios
    speaker_count_hint: int = 2  # Hint for number of speakers in diarization

    # Default languages constant for from_dict
    _DEFAULT_LANGS: list[str] = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self):
        """Initialize default languages constant."""
        object.__setattr__(self, "_DEFAULT_LANGS", ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeechConfig:
        """Create SpeechConfig from dict."""
        if not data:
            return cls()
        default_langs = ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT"]
        return cls(
            vad_silence_timeout_ms=int(data.get("vad_silence_timeout_ms", 800)),
            use_semantic_segmentation=bool(data.get("use_semantic_segmentation", False)),
            candidate_languages=data.get("candidate_languages", default_langs),
            enable_diarization=bool(data.get("enable_diarization", False)),
            speaker_count_hint=int(data.get("speaker_count_hint", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "vad_silence_timeout_ms": self.vad_silence_timeout_ms,
            "use_semantic_segmentation": self.use_semantic_segmentation,
            "candidate_languages": self.candidate_languages,
            "enable_diarization": self.enable_diarization,
            "speaker_count_hint": self.speaker_count_hint,
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
    
    # Mode-specific model overrides (if both are set, orchestrator picks)
    cascade_model: ModelConfig | None = None
    voicelive_model: ModelConfig | None = None

    # ─────────────────────────────────────────────────────────────────
    # Voice Settings (TTS)
    # ─────────────────────────────────────────────────────────────────
    voice: VoiceConfig = field(default_factory=VoiceConfig)

    # ─────────────────────────────────────────────────────────────────
    # Speech Recognition Settings (STT)
    # ─────────────────────────────────────────────────────────────────
    speech: SpeechConfig = field(default_factory=SpeechConfig)

    # ─────────────────────────────────────────────────────────────────
    # Session Settings (VoiceLive-specific)
    # ─────────────────────────────────────────────────────────────────
    session: dict[str, Any] = field(default_factory=dict)

    # ─────────────────────────────────────────────────────────────────
    # Prompt
    # ─────────────────────────────────────────────────────────────────
    prompt_template: str = ""

    # ─────────────────────────────────────────────────────────────────
    # Tools
    # ─────────────────────────────────────────────────────────────────
    tool_names: list[str] = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────
    # Template Variables (for prompt rendering)
    # ─────────────────────────────────────────────────────────────────
    template_vars: dict[str, Any] = field(default_factory=dict)

    # ─────────────────────────────────────────────────────────────────
    # Metadata
    # ─────────────────────────────────────────────────────────────────
    metadata: dict[str, Any] = field(default_factory=dict)
    source_dir: Path | None = None
    _custom_tools_loaded: bool = field(default=False, init=False, repr=False)

    # ═══════════════════════════════════════════════════════════════════
    # TOOL INTEGRATION (via shared registry)
    # ═══════════════════════════════════════════════════════════════════

    def _load_custom_tools(self) -> None:
        """
        Load agent-scoped tools from tools.py in the agent directory.

        If present, this file can register tools with override=True to take
        precedence over shared tool configs. An optional TOOL_NAMES iterable
        in that module will replace the agent's tool list.
        """
        if self._custom_tools_loaded or not self.source_dir:
            return

        tools_file = self.source_dir / "tools.py"
        if not tools_file.exists():
            return

        module_name = f"agent_tools_{self.name}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, tools_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Optional: let tools.py specify the tool set explicitly
                tool_names_override = getattr(module, "TOOL_NAMES", None)
                if tool_names_override:
                    self.tool_names = list(tool_names_override)

                # Optional: call register_tools if provided
                register_fn = getattr(module, "register_tools", None)
                if callable(register_fn):
                    try:
                        register_fn()
                    except TypeError as exc:
                        logger.warning(
                            "register_tools signature unexpected for %s: %s",
                            self.name,
                            exc,
                        )

                logger.info(
                    "Loaded custom tools for agent %s from %s",
                    self.name,
                    tools_file,
                )
                self._custom_tools_loaded = True
        except Exception as exc:  # pragma: no cover - defensive log only
            logger.warning(
                "Failed to load custom tools for %s from %s: %s",
                self.name,
                tools_file,
                exc,
            )

    def get_tools(self) -> list[dict[str, Any]]:
        """
        Get OpenAI-compatible tool schemas from shared registry.

        Returns:
            List of {"type": "function", "function": {...}} dicts
        """
        from apps.artagent.backend.registries.toolstore import get_tools_for_agent, initialize_tools

        initialize_tools()
        self._load_custom_tools()
        return get_tools_for_agent(self.tool_names)

    def get_tool_executor(self, tool_name: str) -> Callable | None:
        """Get the executor function for a specific tool."""
        from apps.artagent.backend.registries.toolstore import get_tool_executor, initialize_tools

        initialize_tools()
        self._load_custom_tools()
        return get_tool_executor(tool_name)

    async def execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name with the given arguments."""
        from apps.artagent.backend.registries.toolstore import execute_tool, initialize_tools

        initialize_tools()
        return await execute_tool(tool_name, args)

    # ═══════════════════════════════════════════════════════════════════
    # PROMPT RENDERING
    # ═══════════════════════════════════════════════════════════════════

    def render_prompt(self, context: dict[str, Any]) -> str:
        """
        Render prompt template with runtime context.

        Args:
            context: Runtime context (caller_name, customer_intelligence, etc.)

        Returns:
            Rendered prompt string
        """
        import os

        # Provide sensible defaults for common template variables
        defaults = {
            "agent_name": self.name or os.getenv("AGENT_NAME", "Erica"),
            "institution_name": os.getenv("INSTITUTION_NAME", "Contoso Bank"),
        }

        # Filter out None values from context - Jinja2 default filter only
        # works for undefined variables, not None values
        filtered_context = {}
        if context:
            for k, v in context.items():
                if v is not None and v != "None":
                    filtered_context[k] = v

        # Merge: defaults < template_vars < filtered runtime context
        full_context = {**defaults, **self.template_vars, **filtered_context}

        try:
            template = Template(self.prompt_template)
            return template.render(**full_context)
        except Exception as e:
            logger.error("Failed to render prompt for %s: %s", self.name, e)
            return self.prompt_template

    # ═══════════════════════════════════════════════════════════════════
    # GREETING RENDERING
    # ═══════════════════════════════════════════════════════════════════

    def _get_greeting_context(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Build context for greeting template rendering.

        Provides default values for common greeting variables from
        environment variables, with optional overrides from context.

        Note: This method filters out None values from context to ensure
        Jinja2 default filters work correctly (they only apply to undefined,
        not None values).

        Args:
            context: Optional runtime overrides

        Returns:
            Dict with agent_name, institution_name, and any overrides
        """
        import os

        # Use agent's own name as fallback for agent_name
        agent_display_name = self.name or os.getenv("AGENT_NAME", "Erica")

        defaults = {
            "agent_name": agent_display_name,
            "institution_name": os.getenv("INSTITUTION_NAME", "Contoso Bank"),
        }

        # Filter out None values from context - Jinja2 default filter only
        # works for undefined variables, not None values
        filtered_context = {}
        if context:
            for k, v in context.items():
                if v is not None and v != "None":
                    filtered_context[k] = v

        # Merge with template_vars and filtered runtime context
        return {**defaults, **self.template_vars, **filtered_context}

    def render_greeting(self, context: dict[str, Any] | None = None) -> str | None:
        """
        Render the greeting template with context.

        Uses Jinja2 templating to render greeting with variables like:
        - {{ agent_name | default('Erica') }}
        - {{ institution_name | default('Contoso Bank') }}

        Args:
            context: Optional runtime context overrides

        Returns:
            Rendered greeting string, or None if no greeting configured
        """
        if not self.greeting:
            return None

        try:
            template = Template(self.greeting)
            rendered = template.render(**self._get_greeting_context(context))
            return rendered.strip() or None
        except Exception as e:
            logger.error("Failed to render greeting for %s: %s", self.name, e)
            return self.greeting.strip() or None

    def render_return_greeting(self, context: dict[str, Any] | None = None) -> str | None:
        """
        Render the return greeting template with context.

        Args:
            context: Optional runtime context overrides

        Returns:
            Rendered return greeting string, or None if not configured
        """
        if not self.return_greeting:
            return None

        try:
            template = Template(self.return_greeting)
            rendered = template.render(**self._get_greeting_context(context))
            return rendered.strip() or None
        except Exception as e:
            logger.error("Failed to render return_greeting for %s: %s", self.name, e)
            return self.return_greeting.strip() or None

    # ═══════════════════════════════════════════════════════════════════
    # HANDOFF HELPERS
    # ═══════════════════════════════════════════════════════════════════

    def get_handoff_tools(self) -> list[str]:
        """Get list of handoff tool names this agent can call."""
        return [t for t in self.tool_names if t.startswith("handoff_")]

    def can_handoff_to(self, agent_name: str) -> bool:
        """Check if this agent has a handoff tool for the target."""
        trigger = f"handoff_{agent_name.lower()}"
        return any(trigger in t.lower() for t in self.tool_names)

    def is_handoff_target(self, tool_name: str) -> bool:
        """Check if the given tool name routes to this agent."""
        return self.handoff.trigger == tool_name

    def get_model_for_mode(self, mode: str) -> ModelConfig:
        """
        Get the appropriate model config for the given orchestration mode.
        
        Args:
            mode: "cascade" or "voicelive"
            
        Returns:
            The mode-specific model if defined, otherwise falls back to self.model
        """
        if mode == "cascade" and self.cascade_model is not None:
            return self.cascade_model
        if mode == "voicelive" and self.voicelive_model is not None:
            return self.voicelive_model
        return self.model

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


def build_handoff_map(agents: dict[str, UnifiedAgent]) -> dict[str, str]:
    """
    Build handoff map from agent declarations.

    Each agent can declare a `handoff.trigger` which is the tool name
    that other agents use to transfer to this agent.

    Args:
        agents: Dict of agent_name → UnifiedAgent

    Returns:
        Dict of tool_name → agent_name
    """
    handoff_map: dict[str, str] = {}
    for agent in agents.values():
        if agent.handoff.trigger:
            handoff_map[agent.handoff.trigger] = agent.name
    return handoff_map


__all__ = [
    "UnifiedAgent",
    "HandoffConfig",
    "VoiceConfig",
    "ModelConfig",
    "build_handoff_map",
]
