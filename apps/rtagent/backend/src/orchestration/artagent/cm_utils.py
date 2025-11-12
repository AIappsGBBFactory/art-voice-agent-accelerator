from __future__ import annotations

from typing import Any, Dict, Tuple, TYPE_CHECKING

from fastapi import WebSocket
from utils.ml_logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager


def get_correlation_context(ws: WebSocket, cm: "MemoManager") -> Tuple[str, str]:
    """Extract (call_connection_id, session_id) from WebSocket and memory."""
    if cm is None:
        logger.warning("MemoManager is None in get_correlation_context, using fallbacks")
        call_connection_id = (
            getattr(ws.state, "call_connection_id", None)
            or ws.headers.get("x-ms-call-connection-id")
            or ws.headers.get("x-call-connection-id")
            or "unknown"
        )
        session_id = (
            getattr(ws.state, "session_id", None)
            or ws.headers.get("x-session-id")
            or "unknown"
        )
        return call_connection_id, session_id

    call_connection_id = (
        getattr(ws.state, "call_connection_id", None)
        or ws.headers.get("x-ms-call-connection-id")
        or ws.headers.get("x-call-connection-id")
        or cm.session_id
    )
    
    session_id = (
        cm.session_id
        or getattr(ws.state, "session_id", None)
        or ws.headers.get("x-session-id")
        or call_connection_id
    )
    return call_connection_id, session_id


def cm_get(cm: "MemoManager", key: str, default: Any = None) -> Any:
    """Safe getter from CoreMemory."""
    if cm is None:
        logger.warning("MemoManager is None; cm_get('%s') -> default(%s)", key, default)
        return default
    return cm.get_value_from_corememory(key, default)


def cm_set(cm: "MemoManager", **kwargs: Any) -> None:
    """Bulk update CoreMemory."""
    if cm is None:
        logger.warning("MemoManager is None; cm_set skipped: %s", kwargs)
        return
    for k, v in kwargs.items():
        cm.update_corememory(k, v)

def sync_voice_from_agent(cm: "MemoManager", ws: WebSocket, agent_name: str) -> None:
    """Update CoreMemory voice based on the agent instance (if available)."""
    from .bindings import get_agent_instance
    
    agent = get_agent_instance(ws, agent_name)
    voice_name = getattr(agent, "voice_name", None) if agent else None
    voice_style = getattr(agent, "voice_style", "chat") if agent else "chat"
    voice_rate = getattr(agent, "voice_rate", "+3%") if agent else "+3%"
    cm_set(
        cm,
        current_agent_voice=voice_name,
        current_agent_voice_style=voice_style,
        current_agent_voice_rate=voice_rate,
    )
