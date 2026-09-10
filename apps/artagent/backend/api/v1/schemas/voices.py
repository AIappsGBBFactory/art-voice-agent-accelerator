"""Speech voice catalog metadata shared by authoring clients."""

from __future__ import annotations

from typing import ClassVar, Literal

from apps.artagent.backend.api.v1.models.base import BaseModel
from pydantic import Field


class VoiceInfo(BaseModel):
    """A Speech voice's service identifier and discoverable capabilities."""

    id: ClassVar[None] = None
    name: str
    display_name: str
    category: str
    language: str = "en-US"
    local_name: str = ""
    gender: str = ""
    voice_type: str = ""
    styles: list[str] = Field(default_factory=list)
    status: str = ""


class VoiceCatalogResponse(BaseModel):
    """A full regional snapshot or an explicitly limited fallback catalog."""

    id: ClassVar[None] = None
    status: Literal["success", "degraded"]
    total: int
    total_available: int
    voices: list[VoiceInfo]
    by_category: dict[str, list[VoiceInfo]]
    runtime_transcription_models: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Backend transcription routing support by orchestration mode, "
            "not regional model or voice availability."
        ),
    )
    default_voice: str
    verified_against_region: bool
    catalog_complete: bool
    source: str
    region: str | None = None
    resource_host: str | None = None
    cached: bool = False
    stale: bool = False
    retrieved_at: float | None = None
    warnings: list[str] = Field(default_factory=list)
    response_time_ms: float
