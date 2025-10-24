# agents.py
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path for utils imports
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import yaml
from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    FunctionTool,
    ResponseCreateParams,
)
from prompts import PromptManager
from tools import build_function_tools
from src.utils.ml_logging import get_logger

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

def _vad(cfg: Dict[str, Any] | None) -> ServerVad | None:
    """Build ServerVad configuration from agent YAML settings.
    
    Each agent can have custom VAD (Voice Activity Detection) settings:
    - threshold: Sensitivity for detecting speech (0.0-1.0)
    - prefix_padding_ms: Audio to include before speech starts
    - silence_duration_ms: Silence duration to consider speech ended
    
    This allows per-agent tuning for different conversation styles.
    """
    if not cfg: 
        return None
    return ServerVad(
        threshold=float(cfg.get("threshold", 0.5)),
        prefix_padding_ms=int(cfg.get("prefix_padding_ms", 300)),
        silence_duration_ms=int(cfg.get("silence_duration_ms", 500)),
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

    async def apply_session(self, conn, *, system_vars: Dict[str, Any] | None = None, say: Optional[str] = None) -> None:
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
                voice = self.voice_name  # String voice id (OpenAI voices if supported)
            logger.info("[%s] Applying voice: %s", self.name, self.voice_name)
        
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
        await conn.session.update(session=RequestSession(**kwargs))
        logger.info("[%s] Session updated successfully", self.name)
        
        # Trigger initial greeting if provided
        if say:
            logger.info("[%s] Triggering greeting: %s", self.name, say[:50] + "..." if len(say) > 50 else say)
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
