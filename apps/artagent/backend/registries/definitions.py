"""Lossless definition records shared by loaders, builders and session storage."""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, get_type_hints

from pydantic import TypeAdapter

T = TypeVar("T")
if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent

TURN_DETECTION_ALIASES = {
    "turn_detection_type": "type",
    "turn_detection_threshold": "threshold",
    "silence_duration_ms": "silence_duration_ms",
    "prefix_padding_ms": "prefix_padding_ms",
}


def definition_payload(value: Any) -> Any:
    """Project declared fields only, preserving nulls, empty values and provenance."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: definition_payload(getattr(value, field.name))
            for field in fields(value)
            if field.init
            and not field.name.startswith("_")
            and not (
                field.metadata.get("omit_default") and getattr(value, field.name) == field.default
            )
        }
    if isinstance(value, dict):
        return {key: definition_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [definition_payload(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


@lru_cache
def _adapter(cls: type[T]) -> TypeAdapter[T]:
    return TypeAdapter(cls)


def decode_definition(cls: type[T], data: dict[str, Any]) -> T:
    """Validate/coerce a canonical record using its dataclass field definitions."""
    return _adapter(cls).validate_python(data)


def definition_fields(cls: type) -> dict[str, tuple[Any, Any]]:
    """Expose the same fields/defaults to Pydantic API schemas."""
    from pydantic import Field

    hints = get_type_hints(cls)
    return {
        field.name: (
            hints[field.name],
            (
                Field(default_factory=field.default_factory)
                if field.default_factory is not MISSING
                else field.default if field.default is not MISSING else ...
            ),
        )
        for field in fields(cls)
        if field.init and not field.name.startswith("_")
    }


def agent_from_payload(data: dict[str, Any]) -> UnifiedAgent:
    """Decode canonical, YAML-projected or API-aliased agent definitions."""
    from apps.artagent.backend.registries.agentstore.base import (
        ModelConfig,
        SpeechConfig,
        UnifiedAgent,
    )

    data = dict(data)
    for external, canonical in (("prompt", "prompt_template"), ("tools", "tool_names")):
        if canonical not in data and external in data:
            data[canonical] = data[external]
    for name in ("model", "cascade_model", "voicelive_model"):
        if data.get(name) is not None:
            if isinstance(data[name], dict):
                data[name] = ModelConfig.from_dict(data[name])
    if isinstance(data.get("speech"), dict):
        data["speech"] = SpeechConfig.from_dict(data["speech"])
    return decode_definition(UnifiedAgent, data)


def agent_api_payload(agent: UnifiedAgent) -> dict[str, Any]:
    """Thin API aliases over the complete canonical agent projection."""
    data = definition_payload(agent)
    data["tools"] = data.pop("tool_names")
    prompt = data.pop("prompt_template")
    data.update(
        prompt=prompt,
        prompt_full=prompt,
        prompt_preview=prompt[:200] + "..." if len(prompt) > 200 else prompt,
        handoff_trigger=agent.handoff.trigger,
        is_entry_point=agent.handoff.is_entry_point,
    )
    return data
