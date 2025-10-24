"""Orchestrator dependency injection for multi-use-case routing."""

import asyncio
from fastapi import WebSocket
from websockets.exceptions import ConnectionClosedError
from opentelemetry import trace

from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.src.orchestration.factory import get_orchestrator as get_orchestrator_func
from apps.rtagent.backend.src.orchestration.use_case_greeting import (
    send_use_case_selection_greeting,
    should_send_selection_greeting,
)
from apps.rtagent.backend.src.utils.tracing import trace_acs_operation
from src.utils.ml_logging import get_logger

logger = get_logger("api.v1.dependencies.orchestrator")
tracer = trace.get_tracer(__name__)


async def route_conversation_turn(
    cm: MemoManager, transcript: str, ws: WebSocket, **kwargs
) -> None:
    """Route conversation turn to selected use case orchestrator."""
    call_id = kwargs.get("call_id")
    session_id = getattr(cm, "session_id", None) if cm else None
    is_acs = kwargs.get("is_acs", True)

    with trace_acs_operation(
        tracer,
        logger,
        "route_conversation_turn",
        call_connection_id=call_id,
        session_id=session_id,
        transcript_length=len(transcript) if transcript else 0,
    ) as op:
        try:
            # Check if we should send the use case selection greeting
            if should_send_selection_greeting(cm):
                op.log_info("Sending use case selection greeting...")
                await send_use_case_selection_greeting(cm, ws, is_acs=is_acs)
                return

            op.log_info(f"Routing turn - transcript: {transcript[:50] if transcript else ''}...")

            # Get orchestrator for selected use case
            try:
                orchestrator = get_orchestrator_func(cm)
                if not orchestrator:
                    op.log_warning("No orchestrator available - use case not selected")
                    return
                
                # Route to orchestrator
                await orchestrator(cm=cm, transcript=transcript, ws=ws, is_acs=is_acs)
                op.log_info("Turn completed")

            except ConnectionClosedError:
                op.log_info("WebSocket connection closed during orchestration")
                return
            except Exception as ws_error:
                # Handle task cancellation specially (expected during barge-in)
                if isinstance(ws_error, asyncio.CancelledError):
                    op.log_debug("Orchestration cancelled (likely due to barge-in)")
                    return
                # Check if it's a WebSocket-related error
                elif (
                    "websocket" in str(ws_error).lower()
                    or "connection" in str(ws_error).lower()
                ):
                    op.log_info(f"WebSocket error during orchestration: {ws_error}")
                    return
                else:
                    # Re-raise non-WebSocket errors
                    raise

        except Exception as e:
            op.set_error(f"Failed to route conversation turn: {e}")
            raise


def get_orchestrator() -> callable:
    """FastAPI dependency for orchestrator injection."""
    return route_conversation_turn
