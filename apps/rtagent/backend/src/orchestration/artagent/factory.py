"""
Orchestrator Factory
====================

Dynamic orchestrator routing based on use case selection.
Routes conversation turns to the appropriate orchestrator based on DTMF selection.

Flow:
1. User presses DTMF code (1=Insurance, 2=Healthcare, 3=Finance)
2. Factory imports and caches the corresponding orchestrator
3. All subsequent turns route through selected orchestrator
4. Each orchestrator has its own agents, tools, and routing logic

Architecture:
- Lazy loading: Orchestrators only imported when needed
- Caching: Once imported, orchestrator is reused for performance
- Isolation: Each use case has completely independent agent ecosystem
"""

import importlib
from typing import Dict, Optional, Callable, TYPE_CHECKING
from fastapi import WebSocket

from apps.rtagent.backend.src.config.use_cases import (
    UseCase,
    UseCaseConfig,
    get_use_case_config,
    get_use_case_from_dtmf,
    USE_CASE_SELECTED_KEY,
    USE_CASE_TYPE_KEY,
)
from src.utils.ml_logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager

logger = get_logger(__name__)


class OrchestratorFactory:
    """
    Factory for loading and routing to use case-specific orchestrators.
    
    Manages dynamic import and caching of orchestrator modules based on
    user's DTMF selection. Each orchestrator is a complete, independent
    conversation engine with its own agents, tools, and routing logic.
    """
    
    # Cache for loaded orchestrator functions
    _orchestrator_cache: Dict[UseCase, Callable] = {}
    
    @classmethod
    def get_orchestrator(cls, use_case: UseCase) -> Optional[Callable]:
        """
        Get orchestrator function for a specific use case.
        
        Lazy loads and caches the orchestrator module's route_turn function.
        Once loaded, the orchestrator is reused for all subsequent calls.
        
        Args:
            use_case: UseCase enum (INSURANCE, HEALTHCARE, FINANCE)
            
        Returns:
            The route_turn function from the orchestrator module, or None if loading fails
            
        Example:
            >>> orchestrator = OrchestratorFactory.get_orchestrator(UseCase.INSURANCE)
            >>> await orchestrator(cm, transcript, ws, is_acs=True)
        """
        # Check cache first
        if use_case in cls._orchestrator_cache:
            logger.debug(f"Using cached orchestrator for {use_case.value}")
            return cls._orchestrator_cache[use_case]
        
        try:
            # Get configuration
            config = get_use_case_config(use_case)
            logger.info(f"Loading orchestrator for {use_case.value} from {config.orchestrator_module}")
            
            # Dynamically import the orchestrator module
            module = importlib.import_module(config.orchestrator_module)
            
            # Get the route_turn function (standard interface)
            route_turn_func = getattr(module, "route_turn", None)
            
            if not route_turn_func:
                logger.error(f"Orchestrator module {config.orchestrator_module} missing route_turn function")
                return None
            
            # Cache for future use
            cls._orchestrator_cache[use_case] = route_turn_func
            logger.info(f"✅ Successfully loaded orchestrator for {use_case.value}")
            
            return route_turn_func
            
        except Exception as e:
            logger.error(f"Failed to load orchestrator for {use_case.value}: {e}", exc_info=True)
            return None
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear the orchestrator cache. Useful for testing or hot-reload scenarios."""
        cls._orchestrator_cache.clear()
        logger.info("Orchestrator cache cleared")
    
    @classmethod
    async def route_with_dtmf_selection(
        cls,
        cm: "MemoManager",
        transcript: str,
        ws: WebSocket,
        dtmf_code: Optional[str] = None,
        *,
        is_acs: bool,
    ) -> bool:
        """
        Route conversation turn with DTMF-based use case selection.
        
        Handles the use case selection flow:
        1. If no use case selected yet, wait for DTMF input
        2. Once DTMF received, select and cache the orchestrator
        3. Route all subsequent turns to the selected orchestrator
        
        Args:
            cm: MemoManager for conversation state
            transcript: User's transcribed speech (or empty if DTMF-only)
            ws: WebSocket connection
            dtmf_code: DTMF digit pressed by user (1, 2, or 3)
            is_acs: Whether this is an ACS call
            
        Returns:
            bool: True if routing succeeded, False if selection still pending
        """
        # Check if use case already selected
        use_case_selected = cm.get_context(USE_CASE_SELECTED_KEY, False)
        
        if not use_case_selected:
            # Use case not yet selected - need DTMF input
            if not dtmf_code:
                logger.debug("Waiting for DTMF use case selection...")
                return False
            
            # Process DTMF selection
            use_case = get_use_case_from_dtmf(dtmf_code)
            
            if not use_case:
                logger.warning(f"Invalid DTMF code received: {dtmf_code}")
                return False
            
            # Store selection in memory
            cm.set_context(USE_CASE_SELECTED_KEY, True)
            cm.set_context(USE_CASE_TYPE_KEY, use_case.value)
            
            config = get_use_case_config(use_case)
            logger.info(f"✅ Use case selected via DTMF {dtmf_code}: {config.display_name}")
            
            # Set entry agent for this use case
            cm.set_context("active_agent", config.entry_agent)
        
        # Get the selected use case
        use_case_value = cm.get_context(USE_CASE_TYPE_KEY)
        if not use_case_value:
            logger.error("Use case selected but type not found in context")
            return False
        
        use_case = UseCase(use_case_value)
        
        # Get and execute the orchestrator
        orchestrator = cls.get_orchestrator(use_case)
        
        if not orchestrator:
            logger.error(f"Failed to load orchestrator for {use_case.value}")
            return False
        
        # Route to the use case-specific orchestrator
        logger.debug(f"Routing to {use_case.value} orchestrator")
        await orchestrator(cm=cm, transcript=transcript, ws=ws, is_acs=is_acs)
        
        return True


async def route_turn_with_selection(
    cm: "MemoManager",
    transcript: str,
    ws: WebSocket,
    *,
    is_acs: bool,
    dtmf_code: Optional[str] = None,
) -> None:
    """
    Main entry point for orchestration with use case selection.
    
    This function replaces the direct route_turn call in the dependency injection.
    It handles the DTMF-based use case selection flow and routes to the
    appropriate orchestrator.
    
    Args:
        cm: MemoManager for conversation state
        transcript: User's transcribed speech
        ws: WebSocket connection
        is_acs: Whether this is an ACS call
        dtmf_code: Optional DTMF code from user selection
    """
    await OrchestratorFactory.route_with_dtmf_selection(
        cm=cm,
        transcript=transcript,
        ws=ws,
        dtmf_code=dtmf_code,
        is_acs=is_acs,
    )
