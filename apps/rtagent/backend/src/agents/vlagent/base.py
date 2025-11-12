# agents.py
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureSemanticVad,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    FunctionTool,
    ResponseCreateParams,
    TurnDetection,
    AzureStandardVoice
)
from .prompts import PromptManager
from .tools import build_function_tools
from utils.ml_logging import get_logger

logger = get_logger("voicelive.agents")

def _mods(values: List[str] | None) -> List[Modality]:
    vals = [v.lower() for v in (values or ["TEXT", "AUDIO"])]
    out: List[Modality] = []
    for v in vals:
        if v in ("text", "TEXT"):
            out.append(Modality.TEXT)
        elif v in ("audio", "AUDIO"):
            out.append(Modality.AUDIO)
        else:
            raise ValueError(f"Unknown modality '{v}'")
    return out

def _in_fmt(s: Optional[str]) -> InputAudioFormat:
    s = (s or "PCM16").lower()
    if s == "pcm16": return InputAudioFormat.PCM16
    raise ValueError(f"Unsupported input audio format '{s}'")

def _out_fmt(s: Optional[str]) -> OutputAudioFormat:
    s = (s or "PCM16").lower()
    if s == "pcm16": return OutputAudioFormat.PCM16
    raise ValueError(f"Unsupported output audio format '{s}'")


def _vad(cfg: Dict[str, Any] | None) -> TurnDetection | None:
    """Build ServerVad configuration from agent YAML settings.
    
    Each agent can have custom VAD (Voice Activity Detection) settings:
    - threshold: Sensitivity for detecting speech (0.0-1.0)
    - prefix_padding_ms: Audio to include before speech starts
    - silence_duration_ms: Silence duration to consider speech ended
    
    This allows per-agent tuning for different conversation styles.
    """
    if not cfg: 
        return None
    vad_type = (cfg.get("type") or cfg.get("provider") or cfg.get("kind") or "semantic").lower()

    def _float(name: str, default: Optional[float] = None) -> Optional[float]:
        if name not in cfg and default is None:
            return None
        try:
            return float(cfg.get(name, default))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid float value for turn_detection.{name}") from None

    def _int(name: str, default: Optional[int] = None) -> Optional[int]:
        if name not in cfg and default is None:
            return None
        try:
            return int(cfg.get(name, default))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid int value for turn_detection.{name}") from None

    common_kwargs: Dict[str, Any] = {}
    threshold = _float("threshold")
    if threshold is not None:
        common_kwargs["threshold"] = threshold
    prefix_padding = _int("prefix_padding_ms")
    if prefix_padding is not None:
        common_kwargs["prefix_padding_ms"] = prefix_padding
    silence_duration = _int("silence_duration_ms")
    if silence_duration is not None:
        common_kwargs["silence_duration_ms"] = silence_duration

    if vad_type in {"semantic", "azure_semantic_vad", "semantic_vad"}:
        # Optional semantic VAD extensions
        languages = cfg.get("languages")
        if languages:
            if not isinstance(languages, list):
                raise ValueError("turn_detection.languages must be a list of locale strings")
            common_kwargs["languages"] = languages

        speech_duration = _int("speech_duration_ms")
        if speech_duration is not None:
            common_kwargs["speech_duration_ms"] = speech_duration

        remove_filler = cfg.get("remove_filler_words")
        if remove_filler is not None:
            common_kwargs["remove_filler_words"] = bool(remove_filler)

        auto_truncate = cfg.get("auto_truncate")
        if auto_truncate is not None:
            common_kwargs["auto_truncate"] = bool(auto_truncate)

        interrupt_response = cfg.get("interrupt_response")
        if interrupt_response is not None:
            common_kwargs["interrupt_response"] = bool(interrupt_response)

        create_response = cfg.get("create_response")
        if create_response is not None:
            common_kwargs["create_response"] = bool(create_response)

        return AzureSemanticVad(**common_kwargs)

    if vad_type in {"server", "server_vad"}:
        auto_truncate = cfg.get("auto_truncate")
        if auto_truncate is not None:
            common_kwargs["auto_truncate"] = bool(auto_truncate)

        interrupt_response = cfg.get("interrupt_response")
        if interrupt_response is not None:
            common_kwargs["interrupt_response"] = bool(interrupt_response)

        create_response = cfg.get("create_response")
        if create_response is not None:
            common_kwargs["create_response"] = bool(create_response)

        return ServerVad(**common_kwargs)

    raise ValueError(
        "Unsupported turn_detection.type '{0}'. Expected 'semantic' or 'server'.".format(vad_type)
    )

class AzureLiveVoiceAgent:
    """
    YAML-driven agent for Azure AI VoiceLive (production-ready).
    
    Each agent can have its own configuration for:
    - Voice selection (voice name and type)
    - VAD settings (turn detection sensitivity and timing)
    - Audio formats
    - Tools and capabilities
    - System prompts
    
    These settings are applied when the agent becomes active via session.update().
    """
    def __init__(self, *, config_path: str | Path) -> None:
        path = Path(config_path).expanduser().resolve()
        self._cfg = self._load_yaml(path)
        self._validate_cfg()

        self.name: str = self._cfg["agent"]["name"]
        self.greeting: Optional[str] = self._cfg["agent"].get("greeting")
        self.return_greeting: Optional[str] = self._cfg["agent"].get("return_greeting")

        prompts = self._cfg.get("prompts", {}) or {}
        self.prompt_path: str = prompts.get("path") or prompts.get("system_template_path") or ""

        # Load per-agent session configuration
        sess = self._cfg.get("session", {}) or {}
        self.modalities = _mods(sess.get("modalities"))
        self.input_audio_format = _in_fmt(sess.get("input_audio_format"))
        self.output_audio_format = _out_fmt(sess.get("output_audio_format"))
        
        # Per-agent VAD configuration (updated on each agent switch)
        self.turn_detection = _vad(sess.get("turn_detection"))
        self.tool_choice: Optional[str] = sess.get("tool_choice", "auto")

        # Per-agent voice configuration (updated on each agent switch)
        voice_cfg = sess.get("voice") or {}
        self.voice_name: Optional[str] = voice_cfg.get("name")
        self.voice_type: str = (voice_cfg.get("type") or "azure-standard").lower()

        # Per-agent tools configuration
        self.tools_cfg = self._cfg.get("tools", []) or []
        self.tools: List[FunctionTool] = build_function_tools(self.tools_cfg)

        # PromptManager will auto-load templates_path from settings
        self.pm = PromptManager()

    async def apply_session(
        self,
        conn,
        *,
        system_vars: Dict[str, Any] | None = None,
        say: Optional[str] = None,
    ) -> None:
        """
        Apply this agent's configuration to the VoiceLive session.
        
        This updates:
        - Voice: Each agent can have a different voice (e.g., en-US-AvaNeural vs en-US-EmmaNeural)
        - VAD settings: Per-agent turn detection sensitivity and timing
        - Instructions: Agent-specific system prompt
        - Tools: Agent-specific capabilities
        - Audio formats and modalities
        
        Optionally triggers an initial greeting if 'say' is provided.
        
        Called automatically when switching between agents.
        """
        instructions = self.pm.get_prompt(self.prompt_path, **(system_vars or {}))

        # Configure per-agent voice
        voice = None
        if self.voice_name:
            if self.voice_type == "azure-standard" or "-" in self.voice_name:
                voice = AzureStandardVoice(name=self.voice_name, type="azure-standard")
            else:
                voice = self.voice_name
            logger.info("[%s] Applying voice: %s", self.name, self.voice_name)
        else:
            logger.debug("[%s] No explicit voice configured", self.name)
        
        # Build session update with per-agent configuration
        kwargs: Dict[str, Any] = dict(
            modalities=self.modalities,
            instructions=instructions,
            input_audio_format=self.input_audio_format,
            output_audio_format=self.output_audio_format,
            turn_detection=self.turn_detection,  # Per-agent VAD settings
        )
        
        if voice is not None:
            kwargs["voice"] = voice  # Per-agent voice
        
        if self.tools:
            kwargs["tools"] = self.tools  # Per-agent tools
            if self.tool_choice:
                kwargs["tool_choice"] = self.tool_choice
        
        # Apply all per-agent settings to the session
        session_payload = RequestSession(**kwargs)
        logger.debug("[%s] Session update payload: %s", self.name, session_payload)
        await conn.session.update(session=session_payload)
        logger.info("[%s] Session updated successfully", self.name)
        
        # Trigger initial greeting if provided
        if say:
            logger.info(
                "[%s] Triggering greeting: %s",
                self.name,
                say[:50] + "..." if len(say) > 50 else say,
            )
            await self.trigger_response(conn, say=say)
        else:
            logger.warning("[%s] No greeting provided - agent will not speak first", self.name)

    async def trigger_response(self, conn, *, say: Optional[str] = None) -> None:
        params = ResponseCreateParams(
            instructions=f"Please say the following message exactly: '{say}'"
        ) if say else ResponseCreateParams()
        await conn.response.create(response=params)

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _validate_cfg(self) -> None:
        if "agent" not in self._cfg or "name" not in self._cfg["agent"]:
            raise ValueError("Missing 'agent.name' in YAML.")
        if "prompts" not in self._cfg or not (
            self._cfg["prompts"].get("path") or self._cfg["prompts"].get("system_template_path")
        ):
            raise ValueError("Missing 'prompts.path' (or 'system_template_path') in YAML.")
        sess = self._cfg.get("session", {}) or {}
        if "turn_detection" in sess and not isinstance(sess["turn_detection"], dict):
            raise ValueError("'session.turn_detection' must be an object")

def load_agents_from_folder(folder: str = "agents") -> dict[str, AzureLiveVoiceAgent]:
    out: dict[str, AzureLiveVoiceAgent] = {}
    for p in Path(folder).glob("*.yaml"):
        agent = AzureLiveVoiceAgent(config_path=p)
        out[agent.name] = agent
    if not out:
        raise RuntimeError(f"No agent YAML files found in {folder}")
    return out
