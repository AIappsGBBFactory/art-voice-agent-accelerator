from __future__ import annotations

"""
rt_agent.py – YAML-driven agents with per-agent memory, model params, tools, and
a configurable *prompt template path*, with context-aware slot + tool output sharing.
"""

from pathlib import Path
from textwrap import shorten
from typing import Any, Dict, Optional

import yaml
from fastapi import WebSocket
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from apps.rtagent.backend.src.agents.artagent.prompt_store.prompt_manager import PromptManager
from apps.rtagent.backend.src.agents.artagent.tool_store import tool_registry as tool_store
from apps.rtagent.backend.src.orchestration.artagent.gpt_flow import process_gpt_response
from utils.ml_logging import get_logger

logger = get_logger("rt_agent")

# Tracer for agent instrumentation
tracer = trace.get_tracer(__name__)


class ARTAgent:
    CONFIG_PATH: str | Path = "agent.yaml"

    def __init__(
        self,
        *,
        config_path: Optional[str | Path] = None,
        template_dir: str = "templates",
    ) -> None:
        """
        Initialize YAML-driven agent with configuration and prompt templates.

        :param config_path: Path to agent configuration YAML file
        :type config_path: Optional[str | Path]
        :param template_dir: Directory containing prompt templates
        :type template_dir: str
        :raises Exception: When YAML config loading fails
        :raises ValueError: When required configuration is missing
        :raises TypeError: When tool configuration is invalid
        """
        cfg_path = Path(config_path or self.CONFIG_PATH).expanduser().resolve()
        try:
            self._cfg = self._load_yaml(cfg_path)
        except Exception:
            logger.exception("Error loading YAML config: %s", cfg_path)
            raise
        self._validate_cfg()

        self.name: str = self._cfg["agent"]["name"]
        self.creator: str = self._cfg["agent"].get("creator", "Unknown")
        self.organization: str = self._cfg["agent"].get("organization", "")
        self.description: str = self._cfg["agent"].get("description", "")

        m = self._cfg["model"]
        self.model_id: str = m["deployment_id"]
        self.temperature: float = float(m.get("temperature", 0.7))
        self.top_p: float = float(m.get("top_p", 1.0))
        self.max_tokens: int = int(m.get("max_tokens", 4096))

        # Voice configuration (optional)
        voice_cfg = self._cfg.get("voice", {})
        self.voice_name: Optional[str] = voice_cfg.get("name")
        self.voice_style: str = voice_cfg.get("style", "chat")
        self.voice_rate: str = voice_cfg.get("rate", "+3%")

        self.prompt_path: str = self._cfg.get("prompts", {}).get(
            "path", "voice_agent_authentication.jinja"
        )
        logger.debug("Agent '%s' prompt template: %s", self.name, self.prompt_path)

        self.tools: list[dict[str, Any]] = []
        for entry in self._cfg.get("tools", []):
            if isinstance(entry, str):
                if entry not in tool_store.TOOL_REGISTRY:
                    raise ValueError(
                        f"Unknown tool name '{entry}' in YAML for {self.name}"
                    )
                self.tools.append(tool_store.TOOL_REGISTRY[entry])
            elif isinstance(entry, dict):
                self.tools.append(entry)
            else:
                raise TypeError("Each tools entry must be a str or dict")

        self.pm: PromptManager = PromptManager(template_dir=template_dir)
        self._log_loaded_summary()

    async def respond(
        self,
        cm,
        user_prompt: str,
        ws: WebSocket,
        *,
        is_acs: bool = False,
        **prompt_kwargs,
    ) -> Any:
        """
        Generate agent response using GPT with context-aware prompting.

        :param cm: Conversation memory manager
        :param user_prompt: User input text
        :type user_prompt: str
        :param ws: WebSocket connection for communication
        :type ws: WebSocket
        :param is_acs: Whether this is an ACS call context
        :type is_acs: bool
        :param prompt_kwargs: Additional template variables for prompt rendering
        :return: GPT response processing result
        :rtype: Any
        """
        # Create invoke_agent span with GenAI semantic conventions
        # This is required for App Insights Agents blade to show Agent Runs
        # See: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/
        with tracer.start_as_current_span(
            f"invoke_agent {self.name}",
            kind=SpanKind.INTERNAL,
            attributes={
                # Required GenAI semantic conventions for Agent Runs
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": self.name,
                "gen_ai.agent.description": self.description or f"Voice agent: {self.name}",
                "gen_ai.provider.name": "azure.ai.openai",
                "gen_ai.request.model": self.model_id,
                # Additional context
                "gen_ai.request.temperature": self.temperature,
                "gen_ai.request.top_p": self.top_p,
                "gen_ai.request.max_tokens": self.max_tokens,
                # Session correlation
                "session.id": cm.session_id if cm else None,
                "agent.tools_count": len(self.tools),
                "agent.is_acs": is_acs,
            },
        ) as span:
            try:
                # For context-rich prompting
                system_prompt = self.pm.get_prompt(self.prompt_path, **prompt_kwargs)
                cm.ensure_system_prompt(
                    self.name,
                    system_prompt=system_prompt,
                )

                result = await process_gpt_response(
                    cm,
                    user_prompt,
                    ws,
                    agent_name=self.name,
                    is_acs=is_acs,
                    model_id=self.model_id,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    max_tokens=self.max_tokens,
                    available_tools=self.tools,
                    session_id=cm.session_id,  # Pass session_id for AOAI client pooling
                )

                span.set_status(Status(StatusCode.OK))
                return result
                
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.record_exception(e)
                raise

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        """
        Load YAML configuration from file path.

        :param path: Path to YAML configuration file
        :type path: Path
        :return: Parsed YAML configuration dictionary
        :rtype: Dict[str, Any]
        """
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _validate_cfg(self) -> None:
        """
        Validate required configuration sections and keys.

        :raises ValueError: When required configuration is missing
        """
        required = [("agent", ["name"]), ("model", ["deployment_id"])]
        for section, keys in required:
            if section not in self._cfg:
                raise ValueError(f"Missing '{section}' section in YAML config.")
            for key in keys:
                if key not in self._cfg[section]:
                    raise ValueError(f"Missing '{section}.{key}' in YAML config.")
        if "prompts" in self._cfg and "path" not in self._cfg["prompts"]:
            raise ValueError("If 'prompts' is declared, it must include 'path'")

    def _log_loaded_summary(self) -> None:
        """
        Log summary of loaded agent configuration for debugging.
        """
        desc_preview = shorten(self.description, width=60, placeholder="…")
        tool_names = [t["function"]["name"] for t in self.tools]
        voice_info = (
            f"voice={self.voice_name or 'default'}"
            + (f"/{self.voice_style}" if self.voice_name else "")
            + (f"@{self.voice_rate}" if hasattr(self, "voice_rate") else "")
        )
        logger.info(
            "Agent loaded successfully",
            extra={
            "agent_name": self.name,
            "organization": self.organization or "unspecified",
            "description": desc_preview,
            "model_id": self.model_id,
            "voice_config": voice_info,
            "prompt_template": self.prompt_path,
            "available_tools": tool_names or [],
            "tool_count": len(self.tools)
            }
        )
