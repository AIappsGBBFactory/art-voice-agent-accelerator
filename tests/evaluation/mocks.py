"""
Evaluation Mocks
=================

Minimal mocks for running evaluation scenarios without full system dependencies.

Design principles:
- Keep it simple - just enough to run scenarios
- No duplication of production code
- Easy to understand and maintain
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Context Builder
# =============================================================================


@dataclass
class MockOrchestratorContext:
    """
    Minimal mock context for orchestrator turns.

    This is a simplified version of OrchestratorContext
    with just the fields needed for evaluation.
    """

    session_id: str
    user_text: str = ""
    turn_id: str | None = None
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    websocket: Any = None  # Not needed for eval
    metadata: dict[str, Any] = field(default_factory=dict)
    system_prompt: str | None = None
    tools: list[dict[str, Any]] | None = None
    call_connection_id: str | None = None


def build_context(
    session_id: str,
    user_text: str,
    turn_id: str,
    conversation_history: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> MockOrchestratorContext:
    """
    Build orchestrator context for evaluation.

    Args:
        session_id: Session ID
        user_text: User input text
        turn_id: Turn identifier
        conversation_history: Previous conversation
        metadata: Additional metadata

    Returns:
        MockOrchestratorContext ready for orchestrator
    """
    return MockOrchestratorContext(
        session_id=session_id,
        user_text=user_text,
        turn_id=turn_id,
        conversation_history=conversation_history or [],
        metadata=metadata or {},
        websocket=None,  # Not needed for eval
    )


__all__ = [
    "MockOrchestratorContext",
    "build_context",
]
