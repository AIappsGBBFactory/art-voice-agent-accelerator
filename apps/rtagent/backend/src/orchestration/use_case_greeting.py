"""
Use Case Selection Greeting
============================

Handles the initial greeting that prompts users to select their use case via DTMF.
This module provides the entry point for the multi-use-case orchestration system.

Flow:
1. On call connect, send selection greeting with DTMF options
2. Start DTMF recognition
3. Wait for user to press 1 (Insurance), 2 (Healthcare), or 3 (Finance)
4. Once selected, route to appropriate orchestrator
"""

from typing import TYPE_CHECKING
from fastapi import WebSocket

from apps.rtagent.backend.src.config.use_cases import (
    get_selection_greeting,
    USE_CASE_GREETING_SENT_KEY,
)
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
    send_response_to_acs,
    broadcast_message,
)
from apps.rtagent.backend.src.orchestration.artagent.cm_utils import (
    cm_get,
    cm_set,
    get_correlation_context,
)
from src.utils.ml_logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager

logger = get_logger(__name__)


async def send_use_case_selection_greeting(
    cm: "MemoManager",
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """
    Send the initial use case selection greeting.
    
    Prompts the user to select their desired service by pressing:
    - 1 for Insurance Claims
    - 2 for Healthcare Services
    - 3 for Financial Services
    
    Args:
        cm: MemoManager for conversation state
        ws: WebSocket connection
        is_acs: Whether this is an ACS call (determines greeting delivery method)
    """
    # Check if greeting already sent
    if cm_get(cm, USE_CASE_GREETING_SENT_KEY, False):
        logger.debug("Use case selection greeting already sent")
        return
    
    # Generate the greeting text
    greeting = get_selection_greeting()
    
    # Mark as sent
    cm_set(cm, **{USE_CASE_GREETING_SENT_KEY: True})
    
    # Add to conversation history
    cm.append_to_history("system", "assistant", greeting)
    
    _, session_id = get_correlation_context(ws, cm)
    
    if is_acs:
        logger.info(f"Sending ACS use case selection greeting: {greeting}")
        
        # Broadcast to monitoring systems
        await broadcast_message(
            None,
            greeting,
            "System",
            app_state=ws.app.state,
            session_id=session_id
        )
        
        # Send via ACS with default voice
        try:
            await send_response_to_acs(
                ws=ws,
                text=greeting,
                blocking=False,
                latency_tool=ws.state.lt,
                voice_name="en-US-JennyNeural",
                voice_style="chat",
                rate="+3%",
            )
            logger.info("✅ Use case selection greeting sent via ACS")
        except Exception as e:
            logger.error(f"Failed to send ACS greeting: {e}", exc_info=True)
    else:
        logger.info(f"Sending WebSocket use case selection greeting: {greeting}")
        
        # For non-ACS WebSocket connections
        await broadcast_message(
            None,
            greeting,
            "System",
            app_state=ws.app.state,
            session_id=session_id
        )


def should_send_selection_greeting(cm: "MemoManager") -> bool:
    """
    Check if the use case selection greeting should be sent.
    
    Returns True if:
    - Greeting not yet sent
    - No use case selected yet
    
    Args:
        cm: MemoManager for conversation state
        
    Returns:
        bool: True if greeting should be sent, False otherwise
    """
    from apps.rtagent.backend.src.config.use_cases import USE_CASE_SELECTED_KEY
    
    greeting_sent = cm_get(cm, USE_CASE_GREETING_SENT_KEY, False)
    use_case_selected = cm.get_context(USE_CASE_SELECTED_KEY, False)
    
    return not greeting_sent and not use_case_selected
