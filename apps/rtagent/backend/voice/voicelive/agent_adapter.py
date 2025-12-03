"""
VoiceLive Agent Adapter
========================

Adapts UnifiedAgent to provide VoiceLive SDK-compatible interface.
This allows unified agents to be used with the VoiceLive orchestrator.

This adapter lives in voice_channels because it's infrastructure for
bridging the generic agent definition to VoiceLive-specific protocols.

Usage:
    from apps.rtagent.backend.voice.voicelive.agent_adapter import (
        VoiceLiveAgentAdapter,
        adapt_unified_agents,
    )
    
    # Adapt a single agent
    adapted = VoiceLiveAgentAdapter(unified_agent)
    await adapted.apply_session(conn, system_vars={...})
    
    # Adapt a dict of agents for orchestrator
    agents = adapt_unified_agents(unified_agents_dict)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from jinja2 import Template
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.rtagent.backend.agents.base import UnifiedAgent

logger = get_logger("voicelive.agent_adapter")
tracer = trace.get_tracer(__name__)

# Try to import VoiceLive SDK models
try:
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
        RequestSession,
        AudioInputTranscriptionOptions,
    )
    _VOICELIVE_AVAILABLE = True
except ImportError:
    _VOICELIVE_AVAILABLE = False
    logger.debug("VoiceLive SDK not available - adapter will not function")

# Import tracing utilities
try:
    from src.enums.monitoring import SpanAttr, GenAIOperation, GenAIProvider
    _TRACING_AVAILABLE = True
except ImportError:
    _TRACING_AVAILABLE = False
    # Fallback stubs
    class SpanAttr:
        SESSION_ID = type("V", (), {"value": "session.id"})()
        CALL_CONNECTION_ID = type("V", (), {"value": "call.connection.id"})()
        GENAI_OPERATION_NAME = type("V", (), {"value": "gen_ai.operation.name"})()
        GENAI_PROVIDER_NAME = type("V", (), {"value": "gen_ai.provider.name"})()
    class GenAIOperation:
        INVOKE_AGENT = "invoke_agent"
    class GenAIProvider:
        AZURE_OPENAI = "azure_openai"


def _mods(values: List[str] | None) -> List["Modality"]:
    """Convert modality strings to VoiceLive Modality enums."""
    if not _VOICELIVE_AVAILABLE:
        return []
    vals = [v.lower() for v in (values or ["TEXT", "AUDIO"])]
    out = []
    for v in vals:
        if v in ("text", "TEXT"):
            out.append(Modality.TEXT)
        elif v in ("audio", "AUDIO"):
            out.append(Modality.AUDIO)
    return out


def _in_fmt(s: Optional[str]) -> "InputAudioFormat":
    """Convert input format string to VoiceLive enum."""
    if not _VOICELIVE_AVAILABLE:
        return None
    s = (s or "PCM16").lower()
    if s == "pcm16":
        return InputAudioFormat.PCM16
    raise ValueError(f"Unsupported input audio format '{s}'")


def _out_fmt(s: Optional[str]) -> "OutputAudioFormat":
    """Convert output format string to VoiceLive enum."""
    if not _VOICELIVE_AVAILABLE:
        return None
    s = (s or "PCM16").lower()
    if s == "pcm16":
        return OutputAudioFormat.PCM16
    raise ValueError(f"Unsupported output audio format '{s}'")


def _vad(cfg: Dict[str, Any] | None) -> Optional["TurnDetection"]:
    """Build VAD configuration from agent session settings."""
    if not _VOICELIVE_AVAILABLE or not cfg:
        return None
    
    vad_type = (cfg.get("type") or "semantic").lower()
    
    common_kwargs: Dict[str, Any] = {}
    if "threshold" in cfg:
        common_kwargs["threshold"] = float(cfg["threshold"])
    if "prefix_padding_ms" in cfg:
        common_kwargs["prefix_padding_ms"] = int(cfg["prefix_padding_ms"])
    if "silence_duration_ms" in cfg:
        common_kwargs["silence_duration_ms"] = int(cfg["silence_duration_ms"])
    
    if vad_type in ("semantic", "azure_semantic", "azure_semantic_vad"):
        return AzureSemanticVad(**common_kwargs)
    elif vad_type in ("server", "server_vad"):
        return ServerVad(**common_kwargs)
    
    return AzureSemanticVad(**common_kwargs)


class VoiceLiveAgentAdapter:
    """
    Adapter that wraps UnifiedAgent to provide VoiceLive SDK-compatible interface.
    
    This allows unified agents to be used with LiveOrchestrator.
    The adapter translates:
    - UnifiedAgent.session → VoiceLive session configuration
    - UnifiedAgent.tool_names → FunctionTool objects
    - UnifiedAgent.prompt_template → Instructions for session
    """
    
    def __init__(self, agent: "UnifiedAgent") -> None:
        """
        Initialize the adapter.
        
        Args:
            agent: UnifiedAgent to adapt
        """
        self._agent = agent
        
        # Parse session configuration
        sess = agent.session or {}
        self.modalities = _mods(sess.get("modalities"))
        self.input_audio_format = _in_fmt(sess.get("input_audio_format"))
        self.output_audio_format = _out_fmt(sess.get("output_audio_format"))
        
        # Transcription settings
        transcription_cfg = sess.get("input_audio_transcription_settings") or {}
        self.input_transcription_cfg: Dict[str, Any] = transcription_cfg
        
        # VAD configuration
        self.turn_detection = _vad(sess.get("turn_detection"))
        self.tool_choice: Optional[str] = sess.get("tool_choice", "auto")
        
        # Cache rendered greetings
        self._greeting_rendered: Optional[str] = None
        self._return_greeting_rendered: Optional[str] = None
        
        # Build tools
        self._tools: Optional[List["FunctionTool"]] = None
    
    # ═══════════════════════════════════════════════════════════════════
    # PROPERTY PASSTHROUGH
    # ═══════════════════════════════════════════════════════════════════
    
    @property
    def name(self) -> str:
        return self._agent.name
    
    @property
    def description(self) -> str:
        return self._agent.description or f"VoiceLive agent: {self._agent.name}"
    
    @property
    def greeting(self) -> Optional[str]:
        """Get rendered greeting."""
        if self._greeting_rendered is not None:
            return self._greeting_rendered
        
        if not self._agent.greeting:
            return None
        
        # Render with environment variables
        try:
            template = Template(self._agent.greeting)
            self._greeting_rendered = template.render(
                agent_name=os.getenv("AGENT_NAME", "Erica"),
                institution_name=os.getenv("INSTITUTION_NAME", "Contoso Bank"),
            )
            return self._greeting_rendered
        except Exception as e:
            logger.warning("Failed to render greeting for %s: %s", self.name, e)
            return self._agent.greeting
    
    @property
    def return_greeting(self) -> Optional[str]:
        """Get rendered return greeting."""
        if self._return_greeting_rendered is not None:
            return self._return_greeting_rendered
        
        if not self._agent.return_greeting:
            return None
        
        try:
            template = Template(self._agent.return_greeting)
            self._return_greeting_rendered = template.render(
                agent_name=os.getenv("AGENT_NAME", "Erica"),
                institution_name=os.getenv("INSTITUTION_NAME", "Contoso Bank"),
            )
            return self._return_greeting_rendered
        except Exception as e:
            logger.warning("Failed to render return_greeting for %s: %s", self.name, e)
            return self._agent.return_greeting
    
    @property
    def voice_name(self) -> Optional[str]:
        return self._agent.voice.name
    
    @property
    def voice_type(self) -> str:
        return self._agent.voice.type
    
    @property
    def voice_cfg(self) -> Dict[str, Any]:
        return self._agent.voice.to_dict()
    
    @property
    def tools(self) -> List["FunctionTool"]:
        """Get VoiceLive FunctionTool objects."""
        if self._tools is not None:
            return self._tools
        
        if not _VOICELIVE_AVAILABLE:
            return []
        
        # Build FunctionTool objects from unified tool registry
        self._tools = self._build_function_tools()
        return self._tools
    
    # ═══════════════════════════════════════════════════════════════════
    # VOICELIVE SESSION METHODS
    # ═══════════════════════════════════════════════════════════════════
    
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
        
        Updates voice, VAD settings, instructions, and tools.
        """
        if not _VOICELIVE_AVAILABLE:
            logger.error("VoiceLive SDK not available, cannot apply session")
            return
        
        with tracer.start_as_current_span(
            f"invoke_agent {self.name}",
            kind=SpanKind.INTERNAL,
            attributes={
                "component": "voicelive",
                "ai.session.id": session_id or "",
                SpanAttr.SESSION_ID.value: session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: call_connection_id or "",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.INVOKE_AGENT,
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                "gen_ai.agent.name": self.name,
                "gen_ai.agent.description": self.description,
            },
        ) as span:
            # Render instructions
            system_vars = system_vars or {}
            system_vars.setdefault("active_agent", self.name)
            instructions = self._agent.render_prompt(system_vars)
            
            # Build voice payload
            voice_payload = self._build_voice_payload()
            
            # Build transcription settings
            transcription_kwargs: Dict[str, Any] = {}
            if self.input_transcription_cfg.get("model"):
                transcription_kwargs["model"] = self.input_transcription_cfg["model"]
            if self.input_transcription_cfg.get("language"):
                transcription_kwargs["language"] = self.input_transcription_cfg["language"]
            
            input_audio_transcription = AudioInputTranscriptionOptions(**transcription_kwargs) if transcription_kwargs else None
            
            # Build session update kwargs
            kwargs: Dict[str, Any] = dict(
                modalities=self.modalities,
                instructions=instructions,
                input_audio_format=self.input_audio_format,
                output_audio_format=self.output_audio_format,
                turn_detection=self.turn_detection,
            )
            
            if input_audio_transcription:
                kwargs["input_audio_transcription"] = input_audio_transcription
            
            if voice_payload:
                kwargs["voice"] = voice_payload
            
            if self.tools:
                kwargs["tools"] = self.tools
                if self.tool_choice:
                    kwargs["tool_choice"] = self.tool_choice
            
            # Apply session
            session_payload = RequestSession(**kwargs)
            await conn.session.update(session=session_payload)
            
            logger.info("[%s] Session updated successfully", self.name)
            span.set_status(Status(StatusCode.OK))
            
            # Trigger greeting if provided
            if say:
                logger.info(
                    "[%s] Triggering greeting: %s",
                    self.name,
                    say[:50] + "..." if len(say) > 50 else say,
                )
                await self.trigger_response(conn, say=say)
    
    async def trigger_response(
        self,
        conn,
        *,
        say: Optional[str] = None,
        cancel_active: bool = True,
    ) -> None:
        """
        Trigger a response from the agent.
        
        Args:
            conn: VoiceLive connection
            say: Optional instruction text for the response
            cancel_active: If True, cancel any active response before triggering
        """
        if not _VOICELIVE_AVAILABLE:
            return
        
        if say:
            from azure.ai.voicelive.models import (
                ClientEventResponseCreate,
                ResponseCreateParams,
            )
            
            # Cancel any active response first to avoid conflicts
            if cancel_active:
                try:
                    await conn.response.cancel()
                except Exception:
                    pass  # No active response to cancel
            
            # Create response with injected text
            try:
                await conn.send(
                    ClientEventResponseCreate(
                        response=ResponseCreateParams(
                            instructions=say,
                        )
                    )
                )
            except Exception as e:
                # Log but don't fail - might still have active response
                logger.warning("trigger_response failed: %s", e)
    
    # ═══════════════════════════════════════════════════════════════════
    # PRIVATE HELPERS
    # ═══════════════════════════════════════════════════════════════════
    
    def _build_voice_payload(self) -> Optional[Any]:
        """Build VoiceLive voice configuration."""
        if not _VOICELIVE_AVAILABLE:
            return None
        
        name = self.voice_name
        if not name:
            return None
        
        voice_type = self.voice_type.lower().strip()
        
        if voice_type in {"azure-standard", "azure_standard", "azure"}:
            optionals = {}
            cfg = self.voice_cfg
            for key in ("temperature", "style", "pitch", "rate", "volume"):
                if cfg.get(key) is not None:
                    optionals[key] = cfg[key]
            return AzureStandardVoice(name=name, **optionals)
        
        # Default to standard voice
        return AzureStandardVoice(name=name)
    
    def _build_function_tools(self) -> List["FunctionTool"]:
        """Build FunctionTool objects from unified tool registry."""
        if not _VOICELIVE_AVAILABLE:
            return []
        
        tools = []
        tool_schemas = self._agent.get_tools()
        
        for schema in tool_schemas:
            if schema.get("type") != "function":
                continue
            
            func = schema.get("function", {})
            tools.append(
                FunctionTool(
                    name=func.get("name", ""),
                    description=func.get("description", ""),
                    parameters=func.get("parameters", {}),
                )
            )
        
        return tools


def adapt_unified_agents(
    agents: Dict[str, "UnifiedAgent"],
) -> Dict[str, VoiceLiveAgentAdapter]:
    """
    Adapt a dict of UnifiedAgents for use with LiveOrchestrator.
    
    Args:
        agents: Dict of agent_name → UnifiedAgent
        
    Returns:
        Dict of agent_name → VoiceLiveAgentAdapter
    """
    return {name: VoiceLiveAgentAdapter(agent) for name, agent in agents.items()}


__all__ = [
    "VoiceLiveAgentAdapter",
    "adapt_unified_agents",
]
