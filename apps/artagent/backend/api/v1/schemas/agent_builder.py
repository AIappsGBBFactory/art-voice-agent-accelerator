"""Agent Builder transport schemas, shared with scenario draft authoring."""

from __future__ import annotations

from typing import Any, Literal

from apps.artagent.backend.registries.agentstore.base import (
    VOICELIVE_BYOM_MODES,
    normalize_transcription_model,
    validate_mai_customization,
)
from pydantic import BaseModel, Field, field_validator, model_validator


class ModelConfigSchema(BaseModel):
    """Model configuration schema."""

    deployment_id: str = "gpt-4o"
    name: str | None = None
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float | None = Field(default=0.9, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=4096, ge=1, le=16384)
    endpoint_preference: str = Field(
        default="auto",
        description="Endpoint selection: auto, chat, or responses",
    )
    api_version: str | None = "v1"
    model_family: str | None = None
    verbosity: int = Field(default=0, ge=0, le=2)
    min_p: float | None = Field(default=None, ge=0.0, le=1.0)
    typical_p: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning_effort: str | None = None
    include_reasoning: bool = False
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32768)
    store: bool | None = None
    metadata: dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None


class ByomConfigSchema(BaseModel):
    """Opt-in Voice Live Bring Your Own Model profile."""

    mode: str | None = Field(
        default=None,
        description="A supported Voice Live BYOM profile, or None for managed VoiceLive.",
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if value not in VOICELIVE_BYOM_MODES:
            raise ValueError(
                f"Invalid BYOM mode '{value}'. Must be one of: {', '.join(VOICELIVE_BYOM_MODES)}"
            )
        return value


class VoiceLiveModelConfigSchema(ModelConfigSchema):
    """VoiceLive generation bounds from the RequestSession service contract."""

    temperature: float | None = Field(default=0.7, ge=0.0, le=1.0)


class VoiceConfigSchema(BaseModel):
    """Voice configuration schema."""

    name: str = "en-US-AvaMultilingualNeural"
    type: str = "azure-standard"
    style: str = "chat"
    rate: str = "+0%"
    pitch: str = Field(default="+0%", description="Voice pitch: -50% to +50%")
    endpoint_id: str | None = Field(default=None, description="Custom voice endpoint ID")


class SpeechConfigSchema(BaseModel):
    """Speech recognition (STT) configuration schema."""

    transcription_model: Literal["azure-speech", "mai-transcribe"] = "azure-speech"
    vad_silence_timeout_ms: int = Field(default=800, ge=100, le=5000)
    use_semantic_segmentation: bool = False
    candidate_languages: list[str] = Field(
        default_factory=lambda: ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT"]
    )
    enable_diarization: bool = False
    speaker_count_hint: int = Field(default=2, ge=1, le=10)

    @field_validator("transcription_model", mode="before")
    @classmethod
    def _normalize_model(cls, value: Any) -> Any:
        return normalize_transcription_model(value) if isinstance(value, str) else value

    @model_validator(mode="before")
    @classmethod
    def _reject_mai_customization(cls, value: Any) -> Any:
        if isinstance(value, dict):
            model = value.get("transcription_model", "azure-speech")
            if isinstance(model, str):
                validate_mai_customization(model, value)
        return value


class SessionConfigSchema(BaseModel):
    """VoiceLive session configuration schema."""

    modalities: list[str] = Field(default_factory=lambda: ["TEXT", "AUDIO"])
    input_audio_format: str = "PCM16"
    output_audio_format: str = "PCM16"
    turn_detection_type: str = "azure_semantic_vad"
    turn_detection_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    silence_duration_ms: int = Field(default=700, ge=100, le=3000)
    prefix_padding_ms: int = Field(default=240, ge=0, le=1000)
    tool_choice: str = "auto"
    input_audio_transcription_settings: dict[str, Any] | None = None

    @field_validator("input_audio_transcription_settings")
    @classmethod
    def _normalize_transcription(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and isinstance(value.get("model"), str):
            return {**value, "model": normalize_transcription_model(value["model"])}
        return value


class DynamicAgentConfig(BaseModel):
    """Configuration for creating a dynamic agent in either orchestration mode."""

    name: str = Field(..., min_length=1, max_length=64, description="Agent display name")
    description: str = Field(default="", max_length=512)
    greeting: str = Field(default="", max_length=1024)
    return_greeting: str = Field(default="", max_length=1024)
    handoff_trigger: str = Field(default="", max_length=128)
    prompt: str = Field(..., min_length=10, description="System prompt for the agent")
    tools: list[str] = Field(default_factory=list)
    cascade_model: ModelConfigSchema | None = None
    voicelive_model: VoiceLiveModelConfigSchema | None = None
    byom: ByomConfigSchema | None = None
    model: ModelConfigSchema | None = None
    voice: VoiceConfigSchema | None = None
    speech: SpeechConfigSchema | None = None
    session: SessionConfigSchema | None = None
    template_vars: dict[str, Any] | None = None
