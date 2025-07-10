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

from azure.communication.callautomation import PhoneNumberIdentifier
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketState
from pydantic import BaseModel

from rtagents.RTAgent.backend.orchestration.conversation_state import ConversationManager
from rtagents.RTAgent.backend.handlers.acs_handler import ACSHandler
from rtagents.RTAgent.backend.handlers.acs_media_handler import ACSMediaHandler
from rtagents.RTAgent.backend.handlers.acs_transcript_handler import TranscriptionHandler
from rtagents.RTAgent.backend.latency.latency_tool import LatencyTool
from rtagents.RTAgent.backend.settings import (
    ACS_CALL_PATH,
    ACS_CALLBACK_PATH,
    ACS_WEBSOCKET_PATH,
    ACS_STREAMING_MODE
)
from src.enums.stream_modes import StreamMode
from utils.ml_logging import get_logger

logger = get_logger("routers.acs")
router = APIRouter()

class CallRequest(BaseModel):
    target_number: str

# --------------------------------------------------------------------------- #
#  1. Make Call  (POST /api/call)
# --------------------------------------------------------------------------- #
@router.post(ACS_CALL_PATH)
async def initiate_call(call: CallRequest, request: Request):
    """Initiate an outbound call through ACS."""
    logger.info(f"Initiating call to {call.target_number}")
    

    result = await ACSHandler.initiate_call(
        acs_caller=request.app.state.acs_caller,
        target_number=call.target_number,
        redis_mgr=request.app.state.redis
    )
    # Cache the call ID with target number for ongoing call tracking
    if result["status"] == "success":
        call_id = result["callId"]
        logger.info(f"Cached ongoing call {call_id} for target {call.target_number}")

        return {"message": result["message"], "callId": result["callId"]}
    else:
        return JSONResponse(result, status_code=400)


# --------------------------------------------------------------------------- #
#  Answer Call  (POST /api/call/inbound)
# --------------------------------------------------------------------------- #
@router.post("/api/call/inbound")
async def answer_call(request: Request):
    """Handle inbound call events and subscription validation."""
    try:
        body = await request.json()
        return await ACSHandler.handle_inbound_call(
            request_body=body,
            acs_caller=request.app.state.acs_caller
        )
    except Exception as exc:
        logger.error("Error parsing request body: %s", exc, exc_info=True)
        raise HTTPException(400, "Invalid request body") from exc


# --------------------------------------------------------------------------- #
#  2. Callback events  (POST /call/callbacks)
# --------------------------------------------------------------------------- #
@router.post(ACS_CALLBACK_PATH)
async def callbacks(request: Request):
    """Handle ACS callback events."""
    if not request.app.state.acs_caller:
        return JSONResponse({"error": "ACS not initialised"}, status_code=503)

    if not request.app.state.stt_client:
        return JSONResponse({"error": "STT client not initialised"}, status_code=503)

    try:
        events = await request.json()
        result = await ACSHandler.process_callback_events(
            events=events,
            request=request,
        )

        if "error" in result:
            return JSONResponse(result, status_code=500)
        return result

    except Exception as exc:
        logger.error("Callback error: %s", exc, exc_info=True)
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
            events=events,
            cm=cm,
            redis_mgr=request.app.state.redis
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
        cm: ConversationManager instance
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
        cm = ConversationManager.from_redis(cid, redis_mgr)
        target_phone_number = cm.get_context("target_number")

        if not target_phone_number:
            logger.debug(f"No target phone number found for session {cm.session_id}")

        ws.app.state.target_participant = PhoneNumberIdentifier(target_phone_number)
        ws.app.state.cm = cm
        ws.state.lt = LatencyTool(cm)  # Initialize latency tool

        call_conn = acs.get_call_connection(cid)
        if not call_conn:
            logger.info(f"Call connection {cid} not found, closing WebSocket")
            await ws.close(code=1000)
            return

        ws.app.state.call_conn = call_conn  # Store call connection in WebSocket state

        # Log call connection state for debugging
        call_state = getattr(call_conn, 'call_connection_state', 'unknown')
        logger.info(f"Call {cid} connection state: {call_state}")

        handler = None

        if ACS_STREAMING_MODE == StreamMode.MEDIA:
            # Use transcription handler for ACS streaming mode
            handler = ACSMediaHandler(
                ws,
                recognizer=ws.app.state.stt_client,
                cm=cm
            )
            # Start recognizer in background, don't block WebSocket setup
            asyncio.create_task(handler.start_recognizer())

        elif ACS_STREAMING_MODE == StreamMode.TRANSCRIPTION:
            # Use media handler for ACS media streaming
            handler = TranscriptionHandler(
                ws, 
                cm=cm, 
            )

        if not handler:
            logger.error("No handler initialized for ACS streaming mode")
            await ws.close(code=1000)
            return


        greeted: set[str] = ws.app.state.greeted_call_ids
        if cid not in greeted and ACS_STREAMING_MODE == StreamMode.MEDIA:
            greeting = (
                "Hello from XYMZ Insurance! Before I can assist you, "
                "I need to verify your identity. "
                "Could you please provide your full name, and either the last 4 digits of your Social Security Number or your ZIP code?"
            )
            handler.play_greeting(greeting)
            cm.append_to_history("media_ws", "assistant", greeting)
            greeted.add(cid)

        try:
            while True:
                # Check if WebSocket is still connected
                if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
                    logger.warning("WebSocket disconnected, stopping message processing")
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
            logger.error(f"Unexpected error in WebSocket message processing: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error starting recognizer: {e}", exc_info=True)
    finally:
        # Clean up resources when WebSocket connection ends
        await ws.close()
        logger.info("WebSocket connection ended, cleaning up resources")
        if 'handler' in locals():
            try:
                if ACS_STREAMING_MODE == StreamMode.MEDIA:
                    handler.recognizer.stop()
                logger.info("Speech recognizer stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping speech recognizer: {e}", exc_info=True)
        
        # Close WebSocket if not already closed
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close()
        except Exception as e:
            logger.error(f"Error closing WebSocket: {e}", exc_info=True)
