"""Bounded, non-persistent contracts for the Quick Tune prompt editor."""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, ClassVar, Literal

from apps.artagent.backend.api.v1.models.base import BaseModel
from apps.artagent.backend.api.v1.schemas.scenario_builder import DynamicScenarioConfig
from pydantic import ConfigDict, Field, StringConstraints, model_validator

MAX_PREVIEW_REQUEST_BYTES = 192_000
MAX_PROMPT_BYTES = 64_000
MAX_CONTEXT_BYTES = 128_000
MAX_JSON_NODES = 4096
MAX_JSON_DEPTH = 12
MAX_OUTPUT_BYTES = 128_000


def check_json_budget(value: Any, *, max_bytes: int = MAX_CONTEXT_BYTES) -> None:
    """Reject excessive or non-JSON data without calling arbitrary serializers."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("Preview JSON exceeds its structure limit.")
        if type(item) is dict:
            if len(item) > MAX_JSON_NODES:
                raise ValueError("Preview JSON exceeds its structure limit.")
            for key, child in item.items():
                if type(key) is not str or len(key) > 128:
                    raise ValueError("Preview JSON contains an invalid key.")
                pending.append((child, depth + 1))
        elif type(item) is list:
            if len(item) > MAX_JSON_NODES:
                raise ValueError("Preview JSON exceeds its structure limit.")
            pending.extend((child, depth + 1) for child in item)
        elif item is None or type(item) in (str, bool):
            if type(item) is str and len(item) > max_bytes:
                raise ValueError("Preview JSON exceeds its size limit.")
        elif type(item) in (int, float):
            if abs(item) > 10**100 or not math.isfinite(item):
                raise ValueError("Preview JSON contains an unsupported number.")
        else:
            raise ValueError("Preview accepts JSON values only.")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > max_bytes:
        raise ValueError("Preview JSON exceeds its size limit.")


class _PreviewSchema(BaseModel):
    """Preview data is not a database entity and has no generated wire identifier."""

    id: ClassVar[None] = None
    model_config = ConfigDict(extra="forbid", strict=True)


class PromptPreviewRequest(_PreviewSchema):
    """Draft fields replace authoring configuration, never session runtime values."""

    prompt: str = Field(max_length=MAX_PROMPT_BYTES)
    agent_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    template_vars: dict[str, Any] = Field(default_factory=dict)
    tools: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=256
    )
    scenario: DynamicScenarioConfig | None = None
    mode: Literal["cascade", "voicelive"]

    @model_validator(mode="before")
    @classmethod
    def _bounded_json(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            if isinstance(payload.get("scenario"), DynamicScenarioConfig):
                payload["scenario"] = payload["scenario"].model_dump()
            check_json_budget(payload, max_bytes=MAX_PREVIEW_REQUEST_BYTES)
            prompt = payload.get("prompt")
            if isinstance(prompt, str) and len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
                raise ValueError("Prompt exceeds its size limit.")
        return value


class PromptVariable(_PreviewSchema):
    """An insertable runtime path, or an explicitly unavailable/redacted path."""

    path: str
    expression: str
    source: str
    type: str
    value_preview: str
    available: bool
    sensitive: bool


class PromptPreviewError(_PreviewSchema):
    """A diagnostic that never contains a template fragment or runtime value."""

    message: str
    line: int | None = None
    kind: str


class PromptPreviewResponse(_PreviewSchema):
    """Preview diagnostics and variable metadata, including for unfinished Jinja."""

    variables: list[PromptVariable] = Field(default_factory=list)
    rendered_prompt: str | None = None
    errors: list[PromptPreviewError] = Field(default_factory=list)
    missing_variables: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    mode: Literal["cascade", "voicelive"]
    scenario_name: str | None = None
