"""
Session Agent Registry
======================

Centralized storage for session-scoped dynamic agents created via Agent Builder.
This module is the single source of truth for session agent state.

Both the agent_builder endpoints and the unified orchestrator import from here,
avoiding circular import issues.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Callable

from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from apps.artagent.backend.agents.base import UnifiedAgent

logger = get_logger(__name__)

# Session-scoped dynamic agents: session_id -> UnifiedAgent
_session_agents: Dict[str, "UnifiedAgent"] = {}

# Callback for notifying the orchestrator adapter of updates
# Set by the unified orchestrator module at import time
_adapter_update_callback: Optional[Callable[[str, "UnifiedAgent"], bool]] = None


def register_adapter_update_callback(callback: Callable[[str, "UnifiedAgent"], bool]) -> None:
    """
    Register a callback to be invoked when a session agent is updated.
    
    This is called by the unified orchestrator to inject updates into live adapters.
    """
    global _adapter_update_callback
    _adapter_update_callback = callback
    logger.debug("Adapter update callback registered")


def get_session_agent(session_id: str) -> Optional["UnifiedAgent"]:
    """Get dynamic agent for a session."""
    return _session_agents.get(session_id)


def set_session_agent(session_id: str, agent: "UnifiedAgent") -> None:
    """
    Set dynamic agent for a session.
    
    This is the single integration point - it both:
    1. Stores the agent in the local cache
    2. Notifies the orchestrator adapter (if callback registered)
    
    All downstream components (voice, model, prompt) will automatically
    use the updated configuration.
    """
    _session_agents[session_id] = agent
    
    # Notify the orchestrator adapter if callback is registered
    adapter_updated = False
    if _adapter_update_callback:
        try:
            adapter_updated = _adapter_update_callback(session_id, agent)
        except Exception as e:
            logger.warning("Failed to update adapter: %s", e)
    
    logger.info(
        "Session agent set | session=%s agent=%s voice=%s adapter_updated=%s",
        session_id,
        agent.name,
        agent.voice.name if agent.voice else None,
        adapter_updated,
    )


def remove_session_agent(session_id: str) -> bool:
    """Remove dynamic agent for a session, returns True if removed."""
    if session_id in _session_agents:
        del _session_agents[session_id]
        logger.info("Session agent removed | session=%s", session_id)
        return True
    return False


def list_session_agents() -> Dict[str, "UnifiedAgent"]:
    """Return a copy of all session agents."""
    return dict(_session_agents)
