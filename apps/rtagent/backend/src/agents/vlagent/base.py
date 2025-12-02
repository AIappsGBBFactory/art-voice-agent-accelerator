# agents.py
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import Template
from azure.ai.voicelive.models import (
    ServerVad,
    AzureSemanticVad,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    FunctionTool,
    ResponseCreateParams,
    TurnDetection,
    AzureStandardVoice,
    AzurePersonalVoice,
    AzureCustomVoice,
    OpenAIVoice,
    RequestSession,
    AudioInputTranscriptionOptions,
)
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from .prompts import PromptManager
from .financial_tools import build_function_tools
from src.speech.phrase_list_manager import get_global_phrase_snapshot
from src.enums.monitoring import SpanAttr, GenAIProvider, GenAIOperation
from utils.ml_logging import get_logger

logger = get_logger("voicelive.agents")
tracer = trace.get_tracer(__name__)

_REQUEST_SESSION_FIELDS = set(getattr(RequestSession, "_attribute_map", {}).keys())
_SUPPORTS_AUDIO_TRANSCRIPTION_OPTIONS = "audio_input_transcription_options" in _REQUEST_SESSION_FIELDS

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

        return AzureSemanticVad(**common_kwargs)

    raise ValueError(
        "Unsupported turn_detection.type '{0}'. Expected 'semantic' or 'server'.".format(vad_type)
    )

class AzureVoiceLiveAgent:
    """
    YAML-driven agent for Azure AI VoiceLive (production-ready).
    
    Each agent can have its own configuration for:
    - Voice selection (voice name and type)
    - VAD settings (turn detection sensitivity and timing)
    - Audio formats
    - Tools and capabilities
    - System prompts
    
    These settings are applied when the agent becomes active via session.update().
    
    Agent Observability:
    - GenAI semantic conventions for App Insights Agents blade
    - invoke_agent spans track each agent activation
    - Tool execution spans for agent capabilities
    """
    def __init__(self, *, config_path: str | Path) -> None:
        path = Path(config_path).expanduser().resolve()
        self._cfg = self._load_yaml(path)
        self._validate_cfg()

        self.name: str = self._cfg["agent"]["name"]
        
        # Render greeting templates with environment variables
        greeting_raw = self._cfg["agent"].get("greeting")
        return_greeting_raw = self._cfg["agent"].get("return_greeting")
        
        # Get environment variables with defaults
        agent_name_env = os.getenv("AGENT_NAME", "ARTAgent")
        institution_name_env = os.getenv("INSTITUTION_NAME", "Contoso Financial Institution")
        
        # Render greetings as Jinja2 templates
        if greeting_raw:
            try:
                template = Template(greeting_raw)
                self.greeting: Optional[str] = template.render(
                    agent_name=agent_name_env,
                    institution_name=institution_name_env
                )
            except Exception as exc:
                logger.warning(
                    "Failed to render greeting template for %s: %s. Using raw greeting.",
                    self.name, exc
                )
                self.greeting = greeting_raw
        else:
            self.greeting = None
            
        if return_greeting_raw:
            try:
                template = Template(return_greeting_raw)
                self.return_greeting: Optional[str] = template.render(
                    agent_name=agent_name_env,
                    institution_name=institution_name_env
                )
            except Exception as exc:
                logger.warning(
                    "Failed to render return_greeting template for %s: %s. Using raw greeting.",
                    self.name, exc
                )
                self.return_greeting = return_greeting_raw
        else:
            self.return_greeting = None
        
        prompts = self._cfg.get("prompts", {}) or {}
        self.prompt_path: str = prompts.get("path") or prompts.get("system_template_path") or ""

        # Load per-agent session configuration
        sess = self._cfg.get("session", {}) or {}
        self.modalities = _mods(sess.get("modalities"))
        self.input_audio_format = _in_fmt(sess.get("input_audio_format"))
        self.output_audio_format = _out_fmt(sess.get("output_audio_format"))

        transcription_cfg = sess.get("input_audio_transcription_settings") or {}
        if not isinstance(transcription_cfg, dict):
            raise ValueError("'session.input_audio_transcription_settings' must be an object when provided")
        self.input_transcription_cfg: Dict[str, Any] = transcription_cfg

        
        # Per-agent VAD configuration (updated on each agent switch)
        self.turn_detection = _vad(sess.get("turn_detection"))
        self.tool_choice: Optional[str] = sess.get("tool_choice", "auto")

        # Per-agent voice configuration (updated on each agent switch)
        voice_cfg = sess.get("voice") or {}
        self.voice_name: Optional[str] = voice_cfg.get("name")
        self.voice_type: str = (voice_cfg.get("type") or "azure-standard").lower()
        self.voice_cfg: Dict[str, Any] = voice_cfg

        # Per-agent tools configuration
        self.tools_cfg = self._cfg.get("tools", []) or []
        self.tools: List[FunctionTool] = build_function_tools(self.tools_cfg)

        # PromptManager will auto-load templates_path from settings
        self.pm = PromptManager()
        
        # Extract description for GenAI semantic conventions
        self.description: str = self._cfg["agent"].get("description", f"VoiceLive agent: {self.name}")

    async def apply_session(
        self,
        conn,
        *,
        system_vars: Dict[str, Any] | None = None,
        say: Optional[str] = None,
        session_id: Optional[str] = None,
        call_connection_id: Optional[str] = None,
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
        
        GenAI Tracing:
        - Creates invoke_agent span for App Insights Agents blade
        - Records agent metadata per OpenTelemetry GenAI semantic conventions
        """
        # Create invoke_agent span with GenAI semantic conventions
        # This is required for App Insights Agents blade to show Agent Runs
        # Format matches the expected App Insights Agents trace format
        with tracer.start_as_current_span(
            f"invoke_agent {self.name}",
            kind=SpanKind.INTERNAL,
            attributes={
                # Component identifier
                "component": "voicelive",
                
                # Session correlation (ai.* prefix for App Insights)
                "ai.session.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: call_connection_id or "",
                
                # Required GenAI semantic conventions for Agent Runs
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.INVOKE_AGENT,
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                "gen_ai.agent.name": self.name,
                "gen_ai.agent.description": self.description,
                
                # VoiceLive-specific agent context
                "voicelive.agent_name": self.name,
                
                # Agent configuration
                "agent.tools_count": len(self.tools),
                "agent.voice_name": self.voice_name or "default",
                "agent.voice_type": self.voice_type,
                "agent.has_greeting": say is not None,
            },
        ) as agent_span:
            try:
                await self._apply_session_internal(
                    conn,
                    system_vars=system_vars,
                    say=say,
                    agent_span=agent_span,
                )
                agent_span.set_status(Status(StatusCode.OK))
            except Exception as e:
                agent_span.set_status(Status(StatusCode.ERROR, str(e)))
                agent_span.set_attribute(SpanAttr.ERROR_TYPE.value, type(e).__name__)
                agent_span.record_exception(e)
                raise

    async def _apply_session_internal(
        self,
        conn,
        *,
        system_vars: Dict[str, Any] | None = None,
        say: Optional[str] = None,
        agent_span: Optional[trace.Span] = None,
    ) -> None:
        """Internal session application logic (extracted for tracing wrapper)."""
        template_vars = dict(system_vars or {})
        template_vars.setdefault("active_agent", self.name)
        if not isinstance(template_vars.get("customer_intelligence"), dict):
            template_vars["customer_intelligence"] = {}

        overrides = template_vars.get("session_overrides") if isinstance(template_vars.get("session_overrides"), dict) else {}
        voice_payload = self._build_voice_payload(overrides.get("voice") if overrides else None)
        instructions = self.pm.get_prompt(self.prompt_path, **template_vars)

        
        # Build session update with per-agent configuration
        phrase_snapshot: List[str] = []
        try:
            phrase_snapshot = await get_global_phrase_snapshot()
        except Exception:
            logger.debug("[%s] Unable to load phrase bias snapshot", self.name, exc_info=True)

        phrase_options = None
        transcription_kwargs: Dict[str, Any] = {
            "model": self.input_transcription_cfg.get("model") or "gpt-4o-transcribe",
        }

        language_override = self.input_transcription_cfg.get("language") or "en-US"
        if language_override:
            transcription_kwargs["language"] = language_override

        custom_speech = self.input_transcription_cfg.get("custom_speech")
        if custom_speech:
            transcription_kwargs["custom_speech"] = custom_speech

        # Only azure-speech and azure-fast-transcription support phrase lists currently
        if transcription_kwargs.get("model", "").startswith("azure-"):
            configured_phrases = self.input_transcription_cfg.get("phrase_list") or []
            if configured_phrases and not isinstance(configured_phrases, list):
                raise ValueError("'session.input_audio_transcription_settings.phrase_list' must be a list when provided")

            combined_phrases: List[str] = []
            if configured_phrases:
                combined_phrases.extend(configured_phrases)
            if phrase_snapshot:
                logger.info(
                    "[%s] Applying %s phrase bias entries to transcription",
                    self.name,
                    len(phrase_snapshot),
                )
                combined_phrases.extend(phrase_snapshot)

            if combined_phrases:
                deduped_phrases = list(dict.fromkeys(filter(None, combined_phrases)))
                if deduped_phrases:
                    transcription_kwargs["phrase_list"] = deduped_phrases

        try:
            pretty_transcription_kwargs = yaml.safe_dump(transcription_kwargs, sort_keys=True).strip()
            logger.info("[%s] input_audio_transcription_settings kwargs:\n%s", self.name, pretty_transcription_kwargs)
        except Exception:
            pretty_transcription_kwargs = repr(transcription_kwargs)
        logger.debug("[%s] input_audio_transcription_settings kwargs:\n%s", self.name, pretty_transcription_kwargs)

        input_audio_transcription_settings = AudioInputTranscriptionOptions(**transcription_kwargs)
        
        kwargs: Dict[str, Any] = dict(
            modalities=self.modalities,
            instructions=instructions,
            input_audio_format=self.input_audio_format,
            output_audio_format=self.output_audio_format,
            turn_detection=self.turn_detection,  # Per-agent VAD settings
            input_audio_transcription=input_audio_transcription_settings
        )

        if phrase_options:
            if _SUPPORTS_AUDIO_TRANSCRIPTION_OPTIONS:
                kwargs["audio_input_transcription_options"] = phrase_options
            else:
                logger.debug(
                    "[%s] VoiceLive SDK lacks audio_input_transcription_options; skipping phrase bias",
                    self.name,
                )
        
        if voice_payload:
            kwargs["voice"] = voice_payload  # Per-agent voice
        
        if self.tools:
            kwargs["tools"] = self.tools  # Per-agent tools
            if self.tool_choice:
                kwargs["tool_choice"] = self.tool_choice
        
        # Apply all per-agent settings to the session
        session_payload = RequestSession(**kwargs)
        def _preview(value: Any, limit: int = 50) -> str:
            if isinstance(value, AudioInputTranscriptionOptions):
                try:
                    phrases = value.phrase_list  # type: ignore[attr-defined]
                except AttributeError:
                    phrases = []
                count = len(phrases or [])
                return f"AudioInputTranscriptionOptions(phrases={count})"
            text = repr(value)
            return text if len(text) <= limit else f"{text[:limit - 3]}..."
        payload_preview = "\n".join(
            f"  {key}: {_preview(value)}" for key, value in kwargs.items()
        ) or "  <empty>"
        logger.info("[%s] Session update payload:\n%s", self.name, payload_preview)

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
            logger.debug("[%s] Greeting deferred by orchestrator", self.name)

    def _build_voice_payload(self, override: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Return a VoiceLive-compatible voice payload honoring overrides when provided."""
        cfg: Dict[str, Any] = dict(self.voice_cfg)
        if override:
            cfg.update({k: v for k, v in override.items() if v not in (None, "")})

        name = cfg.get("name") or self.voice_name
        if not name:
            return None

        voice_type = (cfg.get("type") or self.voice_type or "").lower().strip()

        # Azure voices
        if voice_type in {"azure-standard", "azure_standard", "azure"}:
            optionals = {
                key: cfg[key]
                for key in ("temperature", "custom_lexicon_url", "prefer_locales", "locale", "style", "pitch", "rate", "volume")
                if cfg.get(key) is not None
            }
            return AzureStandardVoice(name=name, **optionals)

        if voice_type in {"azure-personal", "azure_personal"}:
            model = cfg.get("model")
            if not model:
                logger.warning(
                    "[%s] azure-personal voice requires 'model'; falling back to raw name",
                    self.name,
                )
                return AzureStandardVoice(name=name)
            optionals = {key: cfg[key] for key in ("temperature",) if cfg.get(key) is not None}
            return AzurePersonalVoice(name=name, model=model, **optionals)

        if voice_type in {"azure-custom", "azure_custom"}:
            endpoint_id = cfg.get("endpoint_id")
            if not endpoint_id:
                logger.warning(
                    "[%s] azure-custom voice requires 'endpoint_id'; falling back to raw name",
                    self.name,
                )
                return AzureStandardVoice(name=name)
            optionals = {
                key: cfg[key]
                for key in ("temperature", "custom_lexicon_url", "prefer_locales", "locale", "style", "pitch", "rate", "volume")
                if cfg.get(key) is not None
            }
            return AzureCustomVoice(name=name, endpoint_id=endpoint_id, **optionals)

        # For OpenAI voices, return the rich OpenAIVoice model so the SDK can serialize correctly.
        if voice_type in {"openai", "gpt", ""}:
            openai_name = cfg.get("openai_name") or name
            return OpenAIVoice(name=openai_name)

        # Unknown type – safest fallback is to return the raw name string (the service treats it as default handling).
        logger.warning("[%s] Unknown voice.type '%s'; defaulting to AzureStandardVoice", self.name, voice_type)
        return AzureStandardVoice(name=name)

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

def load_agents_from_folder(folder: str = "agents") -> dict[str, AzureVoiceLiveAgent]:
    """
    Load all agent YAML files from the specified folder and its subdirectories.
    
    Searches recursively for *.yaml files, supporting organized folder structures
    like agents/banking/, agents/healthcare/, etc.
    """
    out: dict[str, AzureVoiceLiveAgent] = {}
    folder_path = Path(folder)
    
    # Search recursively for all .yaml files (including subdirectories)
    for p in folder_path.rglob("*.yaml"):
        try:
            agent = AzureVoiceLiveAgent(config_path=p)
            out[agent.name] = agent
            logger.info("Loaded agent '%s' from %s", agent.name, p.relative_to(folder_path))
        except Exception as exc:
            logger.error("Failed to load agent from %s: %s", p, exc, exc_info=True)
    
    if not out:
        raise RuntimeError(f"No agent YAML files found in {folder} or its subdirectories")
    
    return out
