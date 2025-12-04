"""
Orchestrator Data Classes
==========================

Shared data classes for orchestrator context and results.
Used by CascadeOrchestratorAdapter and LiveOrchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


@dataclass
class OrchestratorContext:
    """Context passed to orchestrator for each turn."""
    
    session_id: str
    websocket: Optional["WebSocket"] = None
    call_connection_id: Optional[str] = None
    user_text: str = ""
    turn_id: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorResult:
    """Result from an orchestrator turn."""
    
    response_text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    agent_name: Optional[str] = None
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    interrupted: bool = False
    error: Optional[str] = None


__all__ = [
    "OrchestratorContext",
    "OrchestratorResult",
]
