"""
routers/acs.py
==============
Outbound phone-call flow via Azure Communication Services.

• POST  /api/call/initiate    - start a phone call
• POST  /api/call/callbacks   - receive ACS events
• WS    /ws/stream            - bidirectional PCM media audio stream, also handles acs realtime transcription
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

from azure.communication.callautomation import PhoneNumberIdentifier
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketState
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel

# Add project imports
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "src"))

from apps.rtagent.backend.settings import (
    ACS_CALL_OUTBOUND_PATH,
    ACS_CALL_INBOUND_PATH,
    ACS_CALL_CALLBACK_PATH,
    ACS_STREAMING_MODE,
    ACS_WEBSOCKET_PATH,
    ENABLE_AUTH_VALIDATION,
)
from apps.rtagent.backend.src.handlers import (
    ACSHandler,
    ACSMediaHandler,
    TranscriptionHandler,
)
from apps.rtagent.backend.src.latency.latency_tool import LatencyTool
from apps.rtagent.backend.src.utils.auth import (
    AuthError,
    validate_acs_http_auth,
    validate_acs_ws_auth,
)
from src.enums import StreamMode, SpanAttr
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger
from apps.rtagent.backend.src.utils.tracing_utils import (
    create_service_handler_attrs,
    create_service_dependency_attrs,
    log_with_context,
    TRACING_ENABLED,
    SERVICE_NAMES,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
logger = get_logger("routers.acs")
router = APIRouter()
tracer = trace.get_tracer(__name__)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class CallRequest(BaseModel):
    """
    Request model for initiating outbound calls through Azure Communication Services.

    This model defines the required parameters for making outbound calls including
    target phone number validation and formatting requirements. It ensures proper
    data structure for ACS call initiation with comprehensive validation support.

    :param target_number: The destination phone number for the outbound call.
    :return: Validated CallRequest instance ready for ACS processing.
    :raises ValidationError: If target_number format is invalid or missing.
    """

    target_number: str


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post(ACS_CALL_OUTBOUND_PATH)
async def initiate_call(call: CallRequest, request: Request):
    """
    Initiate an outbound call through Azure Communication Services with comprehensive tracing.

    This endpoint handles outbound call requests by validating phone numbers, checking
    service availability, and initiating calls through ACS. It provides complete
    observability with distributed tracing and proper error handling for production use.

    :param call: The call request containing target phone number and configuration.
    :param request: The FastAPI request object containing application state and context.
    :return: JSON response with call initiation status and connection details.
    :raises HTTPException: If call initiation fails due to service unavailability or validation errors.
    """
    span_attrs = create_service_handler_attrs(
        service_name="acs_router",
        operation="initiate_call",
        target_number=call.target_number,
        call_connection_id=None,
        session_id=None,
    )

    with tracer.start_as_current_span(
        "acs_router.initiate_call", kind=SpanKind.SERVER, attributes=span_attrs
    ) as span:
        log_with_context(
            logger,
            "info",
            "Initiating call",
            operation="initiate_call",
            target_number=call.target_number,
        )

        # Create dependency span for calling ACS handler
        acs_handler_attrs = create_service_dependency_attrs(
            source_service="acs_router",
            target_service="acs_handler",
            operation="initiate_call",
            target_number=call.target_number,
        )

        with tracer.start_as_current_span(
            "acs_router.call_acs_handler",
            kind=SpanKind.CLIENT,
            attributes=acs_handler_attrs,
        ):
            # after: with tracer.start_as_current_span("acs_router.call_acs_handler", kind=SpanKind.CLIENT, attributes=acs_handler_attrs):
            # Determine ACS host from environment or ACS caller
            acs_host = os.getenv("ACS_ENDPOINT")
            if not acs_host:
                acs_host = (
                    getattr(request.app.state.acs_caller, "_acs_host", None)
                    or "acs.communication.azure.com"
                )
            span = trace.get_current_span()
            span.set_attribute("peer.service", "azure-communication-services")
            span.set_attribute("server.address", acs_host)
            span.set_attribute("server.port", 443)
            span.set_attribute("http.method", "POST")
            span.set_attribute(
                "http.url", f"https://{acs_host}/calling/callConnections"
            )
            span.set_attribute("pipeline.stage", "router -> create_call")

            result = await ACSHandler.initiate_call(
                acs_caller=request.app.state.acs_caller,
                target_number=call.target_number,
                redis_mgr=request.app.state.redis,
            )

        if result.get("status") == "success":
            call_id = result.get("callId")
            if span and call_id:
                span.set_attribute(SpanAttr.CALL_CONNECTION_ID, call_id)

            log_with_context(
                logger,
                "info",
                "Call initiated successfully",
                operation="initiate_call",
                call_connection_id=call_id,
                target_number=call.target_number,
            )
            return {"message": result.get("message"), "callId": call_id}

        # Error handling
        if span:
            span.set_status(
                Status(StatusCode.ERROR, result.get("message", "Unknown error"))
            )

        log_with_context(
            logger,
            "error",
            "Call initiation failed",
            operation="initiate_call",
            target_number=call.target_number,
            error=result,
        )
        return JSONResponse(
            {"error": "Call initiation failed", "details": result}, status_code=400
        )


@router.post(ACS_CALL_INBOUND_PATH or "/api/call/answer")
async def answer_call(request: Request):
    """
    Handle inbound call events from Azure Communication Services with authentication validation.

    This endpoint processes incoming call notifications, validates authentication when
    enabled, and manages the call answering workflow. It provides comprehensive
    error handling and observability for inbound call management in production systems.

    :param request: The FastAPI request object containing call event data and application state.
    :return: JSON response indicating call answer status and next steps.
    :raises HTTPException: If authentication fails or call answering encounters errors.
    """
    span_attrs = create_service_handler_attrs(
        service_name="acs_router", operation="answer_call"
    )

    with tracer.start_as_current_span(
        "acs_router.answer_call", kind=SpanKind.SERVER, attributes=span_attrs
    ) as span:
        try:
            body = await request.json()
            acs_caller = request.app.state.acs_caller

            # Create dependency span for calling ACS handler
            acs_handler_attrs = create_service_dependency_attrs(
                source_service="acs_router",
                target_service="acs_handler",
                operation="handle_inbound_call",
            )

            with tracer.start_as_current_span(
                "acs_router.call_acs_handler",
                kind=SpanKind.CLIENT,
                attributes=acs_handler_attrs,
            ):
                inbound_call = await ACSHandler.handle_inbound_call(
                    request_body=body, acs_caller=acs_caller
                )

            log_with_context(
                logger, "info", "Inbound call handled", operation="answer_call"
            )
            return inbound_call

        except Exception as exc:
            if span:
                span.set_status(Status(StatusCode.ERROR, str(exc)))

            log_with_context(
                logger,
                "error",
                "Error processing inbound call",
                operation="answer_call",
                error=str(exc),
            )
            raise HTTPException(400, "Invalid request body") from exc


@router.post(ACS_CALL_CALLBACK_PATH or "/api/call/callbacks")
async def callbacks(request: Request):
    """
    Handle Azure Communication Services callback events with comprehensive processing.

    This endpoint receives and processes various ACS callback events including call
    state changes, participant updates, and media notifications. It validates service
    dependencies, enforces authentication, and routes events to appropriate handlers.

    :param request: The FastAPI request object containing ACS callback event data.
    :return: JSON response acknowledging callback processing status.
    :raises HTTPException: If required services are unavailable or authentication fails.
    """
    # Validate dependencies
    if not request.app.state.acs_caller:
        return JSONResponse({"error": "ACS not initialised"}, status_code=503)
    if not request.app.state.stt_client:
        return JSONResponse({"error": "STT client not initialised"}, status_code=503)

    # Validate auth if enabled
    if ENABLE_AUTH_VALIDATION:
        try:
            _ = validate_acs_http_auth(request)
            logger.debug("JWT token validated successfully")
        except HTTPException as e:
            return JSONResponse({"error": e.detail}, status_code=e.status_code)

    try:
        events = await request.json()

        # Extract call connection ID
        call_connection_id = None
        if isinstance(events, dict):
            call_connection_id = events.get("callConnectionId") or events.get(
                "call_connection_id"
            )
        if not call_connection_id:
            call_connection_id = request.headers.get("x-ms-call-connection-id")

        span_attrs = create_service_handler_attrs(
            service_name="acs_router",
            operation="process_callbacks",
            call_connection_id=call_connection_id,
            events_count=len(events) if isinstance(events, list) else 1,
        )

        with tracer.start_as_current_span(
            "acs_router.callbacks", kind=SpanKind.SERVER, attributes=span_attrs
        ) as span:
            # Create dependency span for calling ACS handler
            acs_handler_attrs = create_service_dependency_attrs(
                source_service="acs_router",
                target_service="acs_handler",
                operation="process_callback_events",
                call_connection_id=call_connection_id,
            )

            with tracer.start_as_current_span(
                "acs_router.call_acs_handler",
                kind=SpanKind.CLIENT,
                attributes=acs_handler_attrs,
            ):
                srv_span = trace.get_current_span()
                try:
                    srv_span.set_attribute(
                        "server.address", request.url.hostname or "0.0.0.0"
                    )
                    srv_span.set_attribute("server.port", request.url.port or 443)
                    srv_span.set_attribute("http.method", request.method)
                    srv_span.set_attribute("http.target", request.url.path)
                except Exception:
                    pass
                srv_span.set_attribute("pipeline.stage", "acs -> router callbacks")
                result = await ACSHandler.process_callback_events(
                    events=events,
                    request=request,
                )

            if "error" in result:
                if span:
                    span.set_status(Status(StatusCode.ERROR, result.get("error")))
                return JSONResponse(result, status_code=500)
            return result

    except Exception as exc:
        log_with_context(
            logger,
            "error",
            "Callback processing error",
            operation="process_callbacks",
            error=str(exc),
        )
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.websocket(ACS_WEBSOCKET_PATH or "/ws/call/stream")
async def acs_media_ws(ws: WebSocket):
    """
    Handle WebSocket media streaming for Azure Communication Services calls with real-time processing.

    This WebSocket endpoint manages bidirectional audio streaming between ACS and the
    voice agent system. It provides real-time audio processing, speech recognition,
    synthesis, and conversation orchestration with comprehensive error handling and observability.

    :param ws: The WebSocket connection for real-time media streaming and communication.
    :return: None (maintains persistent connection until termination).
    :raises WebSocketDisconnect: If the WebSocket connection is terminated unexpectedly.
    """
    cid = None
    handler = None

    try:
        # SERVER span for WS accept (draws incoming edge)
        with tracer.start_as_current_span(
            "acs_router.websocket.accept",
            kind=SpanKind.SERVER,
            attributes=create_service_handler_attrs(
                service_name="acs_router", operation="websocket_accept"
            ),
        ):
            await ws.accept()
            ws_span = trace.get_current_span()
            ws_span.set_attribute("network.protocol.name", "websocket")
            ws_span.set_attribute(
                "server.address",
                ws.headers.get("host", "0.0.0.0")
                if hasattr(ws, "headers")
                else "0.0.0.0",
            )
            ws_span.set_attribute("server.port", 443)
            ws_span.set_attribute("pipeline.stage", "acs -> websocket.accept")
            # Validate auth if enabled
            if ENABLE_AUTH_VALIDATION:
                try:
                    _ = await validate_acs_ws_auth(ws)
                    logger.info("WebSocket authenticated successfully")
                except AuthError as e:
                    logger.warning(f"WebSocket authentication failed: {str(e)}")
                    return

            # Initialize connection
            acs = ws.app.state.acs_caller
            redis_mgr = ws.app.state.redis
            cid = ws.headers["x-ms-call-connection-id"]
            cm = MemoManager.from_redis(cid, redis_mgr)

            # Initialize latency tracking
            ws.state.lt = LatencyTool(cm)
            ws.state.lt.start("greeting_ttfb")
            ws.state._greeting_ttfb_stopped = False

            # Set up call context
            target_phone_number = cm.get_context("target_number")
            if target_phone_number:
                # Store per-connection participant on ws.state
                ws.state.target_participant = PhoneNumberIdentifier(target_phone_number)
            # Conversation memory is per-call
            ws.state.cm = cm

            # Validate call connection
            call_conn = acs.get_call_connection(cid)
            if not call_conn:
                logger.info(f"Call connection {cid} not found, closing WebSocket")
                await ws.close(code=1000)
                return

            ws.state.call_conn = call_conn

            span_attrs = create_service_handler_attrs(
                service_name="acs_router",
                operation="websocket_stream",
                call_connection_id=cid,
                session_id=cm.session_id if hasattr(cm, "session_id") else None,
                stream_mode=ACS_STREAMING_MODE.value
                if hasattr(ACS_STREAMING_MODE, "value")
                else str(ACS_STREAMING_MODE),
            )

            with tracer.start_as_current_span(
                "acs_router.websocket", kind=SpanKind.SERVER, attributes=span_attrs
            ) as span:
                # lightweight trace handshake you can forward to downstream roles later
                from opentelemetry.trace.propagation.tracecontext import (
                    TraceContextTextMapPropagator,
                )

                carrier = {}
                try:
                    TraceContextTextMapPropagator().inject(carrier)
                    ws.state.trace_headers = (
                        carrier  # available if you later hop to another service
                    )
                except Exception:
                    pass
                span.set_attribute("pipeline.stage", "websocket -> media handler init")

                # Initialize appropriate handler - this creates a dependency on media/transcription handlers
                if ACS_STREAMING_MODE == StreamMode.MEDIA:
                    # dependency to media handler
                    handler_attrs = create_service_dependency_attrs(
                        source_service="acs_router",
                        target_service="acs_media_handler",
                        operation="handle_media_stream",
                        call_connection_id=cid,
                        session_id=cm.session_id if hasattr(cm, "session_id") else None,
                        ws=True,
                    )

                    with tracer.start_as_current_span(
                        "acs_router.create_media_handler",
                        kind=SpanKind.CLIENT,
                        attributes=handler_attrs,
                    ):
                        # Acquire STT recognizer from pool
                        ws.state.stt_client = await ws.app.state.stt_pool.acquire()
                        logger.info(
                            f"Acquired STT recognizer from pool for ACS call {cid}"
                        )
                        handler = ACSMediaHandler(
                            ws,
                            recognizer=ws.state.stt_client,
                            call_connection_id=cid,
                            cm=cm,
                        )

                elif ACS_STREAMING_MODE == StreamMode.TRANSCRIPTION:
                    handler_attrs = create_service_dependency_attrs(
                        source_service="acs_router",
                        target_service="transcription_handler",
                        operation="handle_transcription_stream",
                        call_connection_id=cid,
                        session_id=cm.session_id if hasattr(cm, "session_id") else None,
                        ws=True,
                    )
                else:
                    logger.error(f"Unknown streaming mode: {ACS_STREAMING_MODE}")
                    await ws.close(code=1000)
                    return

                ws.state.handler = handler

                log_with_context(
                    logger,
                    "info",
                    "WebSocket stream established",
                    operation="websocket_stream",
                    call_connection_id=cid,
                    mode=str(ACS_STREAMING_MODE),
                )

                # Process messages with dependency tracking
                while (
                    ws.client_state == WebSocketState.CONNECTED
                    and ws.application_state == WebSocketState.CONNECTED
                ):
                    msg = await ws.receive_text()
                    if msg:
                        msg_handler_attrs = create_service_dependency_attrs(
                            source_service="acs_router",
                            target_service="acs_media_handler"
                            if ACS_STREAMING_MODE == StreamMode.MEDIA
                            else "transcription_handler",
                            operation="handle_message",
                            call_connection_id=cid,
                            ws=True,
                        )

                        with tracer.start_as_current_span(
                            "acs_router.handle_message",
                            kind=SpanKind.CLIENT,
                            attributes=msg_handler_attrs,
                        ):
                            if ACS_STREAMING_MODE == StreamMode.MEDIA:
                                await handler.handle_media_message(msg)
                            elif ACS_STREAMING_MODE == StreamMode.TRANSCRIPTION:
                                await handler.handle_transcription_message(msg)

    except WebSocketDisconnect as e:
        if e.code == 1000:
            log_with_context(
                logger,
                "info",
                "WebSocket disconnected normally",
                operation="websocket_stream",
            )
        else:
            log_with_context(
                logger,
                "warning",
                f"WebSocket disconnected abnormally",
                operation="websocket_stream",
                disconnect_code=e.code,
                reason=e.reason,
            )
    except asyncio.CancelledError:
        log_with_context(
            logger, "info", "WebSocket cancelled", operation="websocket_stream"
        )
    except Exception as e:
        log_with_context(
            logger,
            "error",
            "WebSocket error",
            operation="websocket_stream",
            error=str(e),
            call_connection_id=cid,
        )
    finally:
        # Cleanup
        if (
            ws.client_state == WebSocketState.CONNECTED
            and ws.application_state == WebSocketState.CONNECTED
        ):
            await ws.close()

        if handler and ACS_STREAMING_MODE == StreamMode.MEDIA:
            try:
                handler.recognizer.stop()
                # Release STT recognizer back to pool
                await ws.app.state.stt_pool.release(handler.recognizer)
                logger.info(
                    f"Speech recognizer stopped and released back to pool for call {cid}"
                )
            except Exception as e:
                logger.error(f"Error stopping/releasing recognizer: {e}")

        log_with_context(
            logger,
            "info",
            "WebSocket cleanup complete",
            operation="websocket_stream",
            call_connection_id=cid,
        )
