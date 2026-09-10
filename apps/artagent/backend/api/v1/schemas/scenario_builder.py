"""Scenario Builder configurations and read-only authoring draft contracts."""

from __future__ import annotations

import json
from typing import Annotated, Any, get_args, get_origin

from apps.artagent.backend.api.v1.schemas.agent_builder import DynamicAgentConfig
from apps.artagent.backend.registries.definitions import definition_fields
from apps.artagent.backend.registries.scenariostore.loader import (
    AgentOverride,
    GenericHandoffConfig,
    HandoffConfig,
    ScenarioConfig,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model, model_validator

MAX_DRAFT_BYTES = 96_000
MAX_DRAFT_AGENTS = 8
MAX_DRAFT_HANDOFFS = 32
MAX_DRAFT_TOOLS = 64


class HandoffConfigSchema(
    create_model("HandoffDefinitionSchema", __base__=BaseModel, **definition_fields(HandoffConfig))
):
    """A directed scenario handoff edge."""

    from_agent: str
    to_agent: str
    tool: str
    context_vars: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional business context only. Prefer {}. Never repeat routing fields "
        "such as target_agent, from_agent, to_agent, type, or tool here.",
    )


class AgentOverrideSchema(
    create_model(
        "AgentOverrideDefinitionSchema", __base__=BaseModel, **definition_fields(AgentOverride)
    )
):
    """Overrides applied to agents by the existing scenario runtime."""


class GenericHandoffConfigSchema(
    create_model(
        "GenericHandoffDefinitionSchema",
        __base__=BaseModel,
        **definition_fields(GenericHandoffConfig),
    )
):
    """Configuration for the shared handoff_to_agent tool."""


class DynamicScenarioConfig(
    create_model(
        "ScenarioDefinitionSchema", __base__=BaseModel, **definition_fields(ScenarioConfig)
    )
):
    """Configuration for creating a dynamic scenario."""

    name: str = Field(..., min_length=1, max_length=64, description="Scenario display name")
    description: str = Field(default=ScenarioConfig.description, max_length=512)
    icon: str = Field(default=ScenarioConfig.icon, max_length=8)
    agents: list[str] = Field(
        default_factory=list, description="Agent names (empty means all for legacy Builder)"
    )
    handoffs: list[HandoffConfigSchema] = Field(default_factory=list)
    agent_defaults: AgentOverrideSchema | None = None
    generic_handoff: GenericHandoffConfigSchema | None = None


class SessionScenarioResponse(BaseModel):
    """Response for session scenario operations."""

    session_id: str
    scenario_name: str
    status: str
    config: dict[str, Any]
    created_at: float | None = None
    modified_at: float | None = None


def _check_draft_fields(value: Any, annotation: Any, path: str = "draft") -> None:
    """Reject extra config fields in drafts without changing legacy Builder parsing."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if isinstance(value, BaseModel):
            value = value.model_dump()
        if not isinstance(value, dict):
            return
        extra = set(value) - annotation.model_fields.keys()
        if extra:
            raise ValueError(f"Unknown fields at {path}: {', '.join(sorted(extra))}")
        for name, item in value.items():
            _check_draft_fields(item, annotation.model_fields[name].annotation, f"{path}.{name}")
    elif get_origin(annotation) is list and isinstance(value, list):
        for index, item in enumerate(value):
            _check_draft_fields(item, get_args(annotation)[0], f"{path}[{index}]")
    elif get_origin(annotation) is not dict:
        for member in get_args(annotation):
            _check_draft_fields(value, member, path)


def _check_json_size(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("Draft configuration nesting must not exceed 12 levels")
    if isinstance(value, dict):
        for item in value.values():
            _check_json_size(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_json_size(item, depth=depth + 1)


MetadataText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
InputKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]


class ScenarioDraft(BaseModel):
    """An editable draft; only ``apply-draft`` may publish its domain configuration."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1, max_length=2048)
    scenario: DynamicScenarioConfig
    agents: list[DynamicAgentConfig] = Field(default_factory=list, max_length=MAX_DRAFT_AGENTS)
    warnings: list[MetadataText] = Field(default_factory=list, max_length=32)
    missing_capabilities: list[MetadataText] = Field(default_factory=list, max_length=32)
    required_inputs: list[InputKey] = Field(default_factory=list, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def _validate_draft_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        _check_draft_fields(value, cls)
        encoded = json.dumps(
            value,
            default=lambda item: item.model_dump() if isinstance(item, BaseModel) else item,
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > MAX_DRAFT_BYTES:
            raise ValueError(f"Draft must be no larger than {MAX_DRAFT_BYTES} bytes")
        _check_json_size(value)
        return value


class ScenarioGenerateRequest(BaseModel):
    """A prompt and optional draft to refine, constrained to the actual tool catalog."""

    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    draft: ScenarioDraft | None = None
    allowed_tools: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] | None = (
        Field(default=None, max_length=256)
    )
