"""
routers/acs.py
==============
Outbound phone-call flow via Azure Communication Services.

• POST  /call                   – start a phone call
• POST  /call/callbacks         – receive ACS events
• WS    /call/stream            – bidirectional PCM audio stream
• WS    /call/transcription     – real-time transcription from ACS <> AI Speech integration

"""

from __future__ import annotations

import asyncio
import sys
import os
from opentelemetry import trace

tracer = trace.get_tracer(__name__)
from azure.communication.callautomation import PhoneNumberIdentifier
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketState
from pydantic import BaseModel
from apps.rtagent.backend.src.handlers.acs_handler import ACSHandler
from apps.rtagent.backend.src.handlers.acs_media_handler import ACSMediaHandler
from apps.rtagent.backend.src.handlers.acs_transcript_handler import (
    TranscriptionHandler,
)
from apps.rtagent.backend.src.latency.latency_tool import LatencyTool
from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.settings import (
    ACS_CALL_PATH,
    ACS_CALLBACK_PATH,
    ACS_STREAMING_MODE,
    ACS_WEBSOCKET_PATH,
)

from src.enums.stream_modes import StreamMode
from utils.ml_logging import get_logger

# Add tracing imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'src'))
from utils.trace_context import TraceContext, NoOpTraceContext
from src.enums.monitoring import SpanAttr

logger = get_logger("routers.acs")
router = APIRouter()


# Tracing configuration for ACS operations
def _is_acs_tracing_enabled() -> bool:
    """Check if ACS tracing is enabled via environment variables."""
    return os.getenv("ACS_TRACING", os.getenv("ENABLE_TRACING", "false")).lower() == "true"

def _create_acs_trace_context(
    name: str,
    call_connection_id: str = None,
    session_id: str = None,
    metadata: dict = None
) -> TraceContext:
    """Create appropriate trace context for ACS operations."""
    if _is_acs_tracing_enabled():
        return TraceContext(
            name=name,
            call_connection_id=call_connection_id,
            session_id=session_id,
            metadata=metadata
        )
    return NoOpTraceContext()


class CallRequest(BaseModel):
    target_number: str


# --------------------------------------------------------------------------- #
#  1. Make Call  (POST /api/call)
# --------------------------------------------------------------------------- #
@router.post(ACS_CALL_PATH)
async def initiate_call(call: CallRequest, request: Request):
    """Initiate an outbound call through ACS as a parent span."""
    with tracer.start_as_current_span(
        "acs_router.initiate_call",
        attributes={
            "component": "acs_router",
            "operation_Name": "initiate_call",
            "target_number": call.target_number,
        }
    ) as span:
        logger.info(f"Initiating call to {call.target_number}")
        result = await ACSHandler.initiate_call(
            acs_caller=request.app.state.acs_caller,
            target_number=call.target_number,
            redis_mgr=request.app.state.redis,
        )

        # Cache the call ID with target number for ongoing call tracking
        if result["status"] == "success":
            call_id = result["callId"]
            if span and call_id:
                span.set_attribute("call_connection_id", call_id)
            logger.info(
                f"Cached ongoing call {call_id} for target {call.target_number}",
                extra={
                    "operation_Name": "initiate_call",
                    "session_id": call_id,
                }
            )
            return {"message": result["message"], "callId": result["callId"]}
        else:
            logger.error(
                f"Call initiation failed for {call.target_number}: {result}",
                extra={
                    "operation_Name": "initiate_call",
                    "target_number": call.target_number,
                    "result": result
                }
            )
            # Return more detailed error info in the response
            return JSONResponse(
                {
                    "error": "Call initiation failed",
                    "details": result
                },
                status_code=400
            )


# --------------------------------------------------------------------------- #
#  Answer Call  (POST /api/call/inbound)
# --------------------------------------------------------------------------- #
@router.post("/api/call/inbound")
async def answer_call(request: Request):
    """Handle inbound call events and subscription validation."""
    try:
        body = await request.json()
        return await ACSHandler.handle_inbound_call(
            request_body=body, acs_caller=request.app.state.acs_caller
        )
    except Exception as exc:
        logger.error("Error parsing request body: %s", exc, exc_info=True)
        raise HTTPException(400, "Invalid request body") from exc


# --------------------------------------------------------------------------- #
#  2. Callback events  (POST /call/callbacks)
# --------------------------------------------------------------------------- #
@router.post(ACS_CALLBACK_PATH)
async def callbacks(request: Request):
    """Handle ACS callback events with tracing linked to parent span from initiate_call."""
    if not request.app.state.acs_caller:
        return JSONResponse({"error": "ACS not initialised"}, status_code=503)

    if not request.app.state.stt_client:
        return JSONResponse({"error": "STT client not initialised"}, status_code=503)

    try:
        events = await request.json()
        # Extract call_connection_id from events or headers for span linking
        call_connection_id = None
        if isinstance(events, dict):
            call_connection_id = events.get("callConnectionId") or events.get("call_connection_id")
        if not call_connection_id:
            call_connection_id = request.headers.get("x-ms-call-connection-id")

        # Start a new span, link to parent span using call_connection_id
        # Use TraceContext as a context manager if available
        trace_context = _create_acs_trace_context(
            name="acs_router.callbacks",
            call_connection_id=call_connection_id,
            metadata={"events_count": len(events) if isinstance(events, list) else 1}
        )
        with trace_context:

            result = await ACSHandler.process_callback_events(
                events=events,
                request=request,
            )

            if "error" in result:
                trace_context.set_attribute("error", True)
                trace_context.set_attribute("error.message", result.get("error"))
                return JSONResponse(result, status_code=500)
            return result

    except Exception as exc:
        logger.error("Callback error: %s", exc, exc_info=True)
        with tracer.start_as_current_span(
            "acs_router.callbacks.error",
            attributes={
                "component": "acs_router",
                "operation_Name": "callbacks",
                "error": True,
                "error.message": str(exc),
            }
        ):
            return JSONResponse({"error": str(exc)}, status_code=500)


# --------------------------------------------------------------------------- #
#  3. Media callback events  (POST /api/media/callbacks) Currently unused
# --------------------------------------------------------------------------- #
@router.post("/api/media/callbacks")
async def media_callbacks(request: Request):
    """Handle media callback events."""
    try:
        events = await request.json()
        cm = request.app.state.cm
        result = await ACSHandler.process_media_callbacks(
            events=events, cm=cm, redis_mgr=request.app.state.redis
        )

        if "error" in result:
            return JSONResponse(result, status_code=500)
        return result

    except Exception as exc:
        logger.error("Media callback error: %s", exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


# --------------------------------------------------------------------------- #
#  4. Media-streaming/Transcription WebSocket  (WS /call/stream)
# --------------------------------------------------------------------------- #
@router.websocket(ACS_WEBSOCKET_PATH)
async def acs_media_ws(ws: WebSocket):
    """
    Handle WebSocket media streaming for ACS calls.

    Args:
        ws: WebSocket connection
        recognizer: Speech-to-text recognizer instance
        cm: MemoManager instance
        redis_mgr: Redis manager instance
        clients: List of connected WebSocket clients
        cid: Call connection ID
    """
    try:
        await ws.accept()
        # Retrieve session and check call state to avoid reconnect loops
        acs = ws.app.state.acs_caller
        redis_mgr = ws.app.state.redis
        cid = ws.headers["x-ms-call-connection-id"]
        cm = MemoManager.from_redis(cid, redis_mgr)

        # Start latency timer for "time to first byte" (TTFB) for greeting playback
        ws.state.lt = LatencyTool(cm)
        ws.state.lt.start("greeting_ttfb")
        ws.state._greeting_ttfb_stopped = False  # Track if TTFB has been stopped

        target_phone_number = cm.get_context("target_number")

        if not target_phone_number:
            logger.debug(f"No target phone number found for session {cm.session_id}")

        ws.app.state.target_participant = PhoneNumberIdentifier(target_phone_number)
        ws.app.state.cm = cm

        call_conn = acs.get_call_connection(cid)
        if not call_conn:
            logger.info(f"Call connection {cid} not found, closing WebSocket")
            await ws.close(code=1000)
            return
        
        # Create trace context for this call
        # Start a new span for the WebSocket, linked to the parent span from initiate_call
        parent_trace_context = _create_acs_trace_context(
            name="acs_router.initiate_call",
            call_connection_id=cid,
            session_id=cm.session_id if hasattr(cm, "session_id") else None,
            metadata={"ws": True}
        )
        with tracer.start_as_current_span(
            "acs_router.websocket_established",
            context=parent_trace_context.get_span_context() if hasattr(parent_trace_context, "get_span_context") else None,
            attributes={
            "call_connection_id": cid,
            "session_id": getattr(cm, "session_id", None),
            "component": "acs_router",
            "operation_Name": "websocket_established",
            }
        ) as ws_span:
            ws.app.state.call_conn = call_conn  # Store call connection in WebSocket state

            ws.app.state.call_conn = call_conn  # Store call connection in WebSocket state

            # Log call connection state for debugging
            call_state = getattr(call_conn, "call_connection_state", "unknown")
            logger.info(f"Call {cid} connection state: {call_state}")

            handler = None

            if ACS_STREAMING_MODE == StreamMode.MEDIA:
                handler = ACSMediaHandler(ws, recognizer=ws.app.state.stt_client, cm=cm)
                # Don't start recognizer here - it will be started when first AudioMetadata is received
                # This prevents race conditions with WebSocket setup

            elif ACS_STREAMING_MODE == StreamMode.TRANSCRIPTION:
                handler = TranscriptionHandler(
                    ws,
                    cm=cm,
                )

            if not handler:
                logger.error("No handler initialized for ACS streaming mode")
                await ws.close(code=1000)
                return

            try:
                # Fire greeting immediately when WebSocket is ready to receive audio
                while True:
                    # Check if WebSocket is still connected
                    if (
                        ws.client_state != WebSocketState.CONNECTED
                        or ws.application_state != WebSocketState.CONNECTED
                    ):
                        logger.warning(
                            "WebSocket disconnected, stopping message processing"
                        )
                        break

                    msg = await ws.receive_text()
                    if msg:
                        if ACS_STREAMING_MODE == StreamMode.MEDIA:
                            await handler.handle_media_message(msg)
                        elif ACS_STREAMING_MODE == StreamMode.TRANSCRIPTION:
                            await handler.handle_transcription_message(msg)

            except WebSocketDisconnect as e:
                # Handle normal disconnect (code 1000 is normal closure)
                if e.code == 1000:
                    logger.info("WebSocket disconnected normally by client")
                else:
                    logger.warning(f"WebSocket disconnected with code {e.code}: {e.reason}")
            except asyncio.CancelledError:
                logger.info("WebSocket message processing cancelled")
            except Exception as e:
                logger.error(
                    f"Unexpected error in WebSocket message processing: {e}", exc_info=True
                )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    finally:
        # Clean up resources when WebSocket connection ends
        if ws.client_state == WebSocketState.CONNECTED and ws.application_state == WebSocketState.CONNECTED:
            await ws.close()
        logger.info("WebSocket connection ended, cleaning up resources")
        if "handler" in locals():
            try:
                if ACS_STREAMING_MODE == StreamMode.MEDIA:
                    handler.recognizer.stop()
                logger.info("Speech recognizer stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping speech recognizer: {e}", exc_info=True)
