"""Orchestrator factory - dynamically loads use case orchestrators."""

import importlib
from typing import Optional, Callable, TYPE_CHECKING, Dict

from apps.rtagent.backend.src.config.use_cases import (
    UseCase,
    get_use_case_config,
    USE_CASE_SELECTED_KEY,
    USE_CASE_TYPE_KEY,
)
from src.utils.ml_logging import get_logger

if TYPE_CHECKING:
    from src.stateful.state_managment import MemoManager

logger = get_logger(__name__)

# Module-level cache for orchestrator functions (shared across all sessions)
# This is safe because the orchestrator function is stateless and session-independent
_ORCHESTRATOR_CACHE: Dict[str, Callable] = {}


def get_orchestrator(cm: "MemoManager") -> Optional[Callable]:
    """
    Get orchestrator for the selected use case.
    
    The orchestrator function is cached at module level (shared across sessions)
    because it's stateless. Session state is passed via MemoManager parameter.
    
    Returns the route_turn function for the use case selected in this session.
    """
    # Check if use case selected (session-specific)
    if not cm.get_context(USE_CASE_SELECTED_KEY, False):
        logger.warning(f"[{cm.session_id}] No use case selected")
        return None
    
    use_case_value = cm.get_context(USE_CASE_TYPE_KEY)
    if not use_case_value:
        logger.error(f"[{cm.session_id}] Use case selected but type missing")
        return None
    
    # Check module-level cache (safe because orchestrator is stateless)
    if use_case_value in _ORCHESTRATOR_CACHE:
        return _ORCHESTRATOR_CACHE[use_case_value]
    
    # Load orchestrator (only happens once per use case type)
    try:
        use_case = UseCase(use_case_value)
        config = get_use_case_config(use_case)
        
        module = importlib.import_module(config.orchestrator_module)
        route_turn_func = getattr(module, "route_turn", None)
        
        if not route_turn_func:
            logger.error(f"[{cm.session_id}] No route_turn in {config.orchestrator_module}")
            return None
        
        # Cache at module level (NOT in session - function is shared)
        _ORCHESTRATOR_CACHE[use_case_value] = route_turn_func
        logger.info(f"[{cm.session_id}] Loaded and cached {use_case.value} orchestrator")
        
        return route_turn_func
        
    except Exception as e:
        logger.error(f"[{cm.session_id}] Failed to load orchestrator: {e}", exc_info=True)
        return None
