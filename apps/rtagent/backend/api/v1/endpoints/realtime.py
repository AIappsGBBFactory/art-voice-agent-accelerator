"""
V1 Realtime API Endpoints - Enterprise Architecture
===================================================

WebSocket endpoints for real-time browser communication.

Endpoint Architecture:
- /status: Service health and connection statistics
- /dashboard/relay: Dashboard client connections for monitoring
- /conversation: Browser-based voice conversations (Voice Live or Speech Cascade)

Separation of Concerns:
- Endpoints: WebSocket lifecycle, session registration, cleanup orchestration
- Handlers: ALL audio processing, protocol handling, orchestration delegation
  - MediaHandler: Browser audio (Voice Live + Speech Cascade)
  - ACSMediaHandler: ACS telephony audio

The endpoint is THIN - it only handles:
1. WebSocket accept/close
2. Session registration/cleanup
3. Delegating to handler.run()
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.websockets import WebSocketState
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from apps.rtagent.backend.src.services.acs.session_terminator import (
    TerminationReason,
    terminate_session,
)
from apps.rtagent.backend.src.utils.tracing import log_with_context
from src.enums.stream_modes import StreamMode
from src.postcall.push import build_and_flush
from utils.ml_logging import get_logger

from ..dependencies.orchestrator import get_orchestrator
from ..handlers.media_handler import (
    MediaHandler,
    MediaHandlerConfig,
    MediaHandlerMode,
)
from ..schemas.realtime import RealtimeStatusResponse

logger = get_logger("api.v1.endpoints.realtime")
tracer = trace.get_tracer(__name__)

router = APIRouter()


# =============================================================================
# Status Endpoint
# =============================================================================


@router.get(
    "/status",
    response_model=RealtimeStatusResponse,
    summary="Get Realtime Service Status",
    tags=["Realtime Status"],
)
async def get_realtime_status(request: Request) -> RealtimeStatusResponse:
    """Retrieve service status and active connection counts."""
    session_count = await request.app.state.session_manager.get_session_count()
    conn_stats = await request.app.state.conn_manager.stats()
    dashboard_clients = conn_stats.get("by_topic", {}).get("dashboard", 0)

    return RealtimeStatusResponse(
        status="available",
        websocket_endpoints={
            "dashboard_relay": "/api/v1/realtime/dashboard/relay",
            "conversation": "/api/v1/realtime/conversation",
        },
        features={
            "dashboard_broadcasting": True,
            "conversation_streaming": True,
            "orchestrator_support": True,
            "session_management": True,
            "audio_interruption": True,
            "precise_routing": True,
            "connection_queuing": True,
        },
        active_connections={
            "dashboard_clients": dashboard_clients,
            "conversation_sessions": session_count,
            "total_connections": conn_stats.get("connections", 0),
        },
        protocols_supported=["WebSocket"],
        version="v1",
    )


# =============================================================================
# Dashboard Relay Endpoint
# =============================================================================


@router.websocket("/dashboard/relay")
async def dashboard_relay_endpoint(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
) -> None:
    """WebSocket endpoint for dashboard clients to receive real-time updates."""
    client_id = str(uuid.uuid4())[:8]
    conn_id = None

    try:
        with tracer.start_as_current_span(
            "api.v1.realtime.dashboard_relay_connect",
            kind=SpanKind.SERVER,
            attributes={
                "api.version": "v1",
                "realtime.client_id": client_id,
                "network.protocol.name": "websocket",
            },
        ) as span:
            conn_id = await websocket.app.state.conn_manager.register(
                websocket,
                client_type="dashboard",
                topics={"dashboard"},
                session_id=session_id,
                accept_already_done=False,
            )

            if hasattr(websocket.app.state, "session_metrics"):
                await websocket.app.state.session_metrics.increment_connected()

            span.set_status(Status(StatusCode.OK))
            log_with_context(
                logger,
                "info",
                "Dashboard client connected",
                operation="dashboard_connect",
                client_id=client_id,
                conn_id=conn_id,
            )

        # Keep-alive loop
        while _is_connected(websocket):
            await websocket.receive_text()

    except WebSocketDisconnect as e:
        _log_disconnect("dashboard", client_id, e)
    except Exception as e:
        _log_error("dashboard", client_id, e)
        raise
    finally:
        await _cleanup_dashboard(websocket, client_id, conn_id)


# =============================================================================
# Conversation Endpoint
# =============================================================================


@router.websocket("/conversation")
async def browser_conversation_endpoint(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
    streaming_mode: Optional[str] = Query(None),
    user_email: Optional[str] = Query(None),
    orchestrator: Optional[callable] = Depends(get_orchestrator),
) -> None:
    """
    WebSocket endpoint for browser-based voice conversations.

    This endpoint is THIN - it only handles:
    1. Connection registration
    2. Session resolution
    3. Handler creation (which does ALL setup)
    4. Cleanup orchestration
    """
    handler: Optional[MediaHandler] = None
    conn_id: Optional[str] = None

    # Parse streaming mode
    stream_mode = _parse_stream_mode(streaming_mode)
    websocket.state.stream_mode = str(stream_mode)

    try:
        # Resolve session ID
        session_id = _resolve_session_id(websocket, session_id)

        with tracer.start_as_current_span(
            "api.v1.realtime.conversation_connect",
            kind=SpanKind.SERVER,
            attributes={
                "api.version": "v1",
                "realtime.session_id": session_id,
                "stream.mode": str(stream_mode),
                "network.protocol.name": "websocket",
            },
        ) as span:
            # Register connection
            conn_id = await _register_connection(websocket, session_id)
            websocket.state.conn_id = conn_id

            # Create handler (handles ALL setup)
            config = MediaHandlerConfig(
                session_id=session_id,
                websocket=websocket,
                conn_id=conn_id,
                user_email=user_email,
                orchestrator=orchestrator,
            )

            if stream_mode == StreamMode.VOICE_LIVE:
                handler = await MediaHandler.create_voice_live(
                    config, websocket.app.state
                )
            else:
                handler = await MediaHandler.create_speech_cascade(
                    config, websocket.app.state
                )

            # Register with session manager
            await websocket.app.state.session_manager.add_session(
                session_id,
                handler.memory_manager,
                websocket,
                metadata=handler.metadata,
            )

            if hasattr(websocket.app.state, "session_metrics"):
                await websocket.app.state.session_metrics.increment_connected()

            span.set_status(Status(StatusCode.OK))
            log_with_context(
                logger,
                "info",
                "Conversation session initialized",
                operation="conversation_connect",
                session_id=session_id,
                stream_mode=str(stream_mode),
            )

        # Run handler (processes all messages)
        await handler.run(websocket.app.state)

    except WebSocketDisconnect as e:
        _log_disconnect("conversation", session_id, e)
    except Exception as e:
        _log_error("conversation", session_id, e)
        raise
    finally:
        await _cleanup_conversation(websocket, session_id, handler, conn_id)


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_stream_mode(streaming_mode: Optional[str]) -> StreamMode:
    """Parse streaming mode from query parameter."""
    if not streaming_mode:
        return StreamMode.REALTIME
    try:
        return StreamMode.from_string(streaming_mode.strip().lower())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _resolve_session_id(websocket: WebSocket, session_id: Optional[str]) -> str:
    """Resolve session ID from query param, headers, or generate new UUID."""
    header_call_id = websocket.headers.get("x-ms-call-connection-id")

    if session_id:
        return session_id
    if header_call_id:
        websocket.state.call_connection_id = header_call_id
        websocket.state.acs_bridged_call = True
        return header_call_id

    websocket.state.acs_bridged_call = False
    return str(uuid.uuid4())


async def _register_connection(websocket: WebSocket, session_id: str) -> str:
    """Register WebSocket with connection manager."""
    header_call_id = websocket.headers.get("x-ms-call-connection-id")
    conn_id = await websocket.app.state.conn_manager.register(
        websocket,
        client_type="conversation",
        session_id=session_id,
        call_id=header_call_id,
        topics={"conversation"},
        accept_already_done=False,
    )

    if header_call_id:
        await _bind_call_session(
            websocket.app.state, header_call_id, session_id, conn_id
        )

    return conn_id


async def _bind_call_session(
    app_state: Any,
    call_connection_id: str,
    session_id: str,
    conn_id: str,
) -> None:
    """Persist association between ACS call and browser session."""
    ttl_seconds = 60 * 60 * 24  # 24 hours
    redis_mgr = getattr(app_state, "redis", None)

    if redis_mgr and hasattr(redis_mgr, "set_value_async"):
        for redis_key in (
            f"call_session_map:{call_connection_id}",
            f"call_session_mapping:{call_connection_id}",
        ):
            try:
                await redis_mgr.set_value_async(
                    redis_key, session_id, ttl_seconds=ttl_seconds
                )
            except Exception:
                pass

    conn_manager = getattr(app_state, "conn_manager", None)
    if conn_manager:
        try:
            context = await conn_manager.get_call_context(call_connection_id) or {}
            context.update({
                "session_id": session_id,
                "browser_session_id": session_id,
                "connection_id": conn_id,
            })
            await conn_manager.set_call_context(call_connection_id, context)
        except Exception:
            pass


def _is_connected(websocket: WebSocket) -> bool:
    """Check if WebSocket is still connected."""
    return (
        websocket.client_state == WebSocketState.CONNECTED
        and websocket.application_state == WebSocketState.CONNECTED
    )


# =============================================================================
# Logging Helpers
# =============================================================================


def _log_disconnect(endpoint: str, identifier: Optional[str], e: WebSocketDisconnect) -> None:
    """Log WebSocket disconnect."""
    level = "info" if e.code == 1000 else "warning"
    log_with_context(
        logger,
        level,
        f"{endpoint.capitalize()} disconnected",
        operation=f"{endpoint}_disconnect",
        identifier=identifier,
        disconnect_code=e.code,
    )


def _log_error(endpoint: str, identifier: Optional[str], e: Exception) -> None:
    """Log WebSocket error."""
    log_with_context(
        logger,
        "error",
        f"{endpoint.capitalize()} error",
        operation=f"{endpoint}_error",
        identifier=identifier,
        error=str(e),
        error_type=type(e).__name__,
    )


# =============================================================================
# Cleanup Functions
# =============================================================================


async def _cleanup_dashboard(
    websocket: WebSocket,
    client_id: Optional[str],
    conn_id: Optional[str],
) -> None:
    """Clean up dashboard connection resources."""
    with tracer.start_as_current_span(
        "api.v1.realtime.cleanup_dashboard",
        attributes={"client_id": client_id},
    ) as span:
        try:
            if conn_id:
                await websocket.app.state.conn_manager.unregister(conn_id)

            if hasattr(websocket.app.state, "session_metrics"):
                await websocket.app.state.session_metrics.increment_disconnected()

            if _is_connected(websocket):
                await websocket.close()

            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error("Dashboard cleanup error: %s", e)


async def _cleanup_conversation(
    websocket: WebSocket,
    session_id: Optional[str],
    handler: Optional[MediaHandler],
    conn_id: Optional[str],
) -> None:
    """Clean up conversation session resources."""
    with tracer.start_as_current_span(
        "api.v1.realtime.cleanup_conversation",
        attributes={"session_id": session_id},
    ) as span:
        try:
            # Terminate Voice Live ACS session if needed
            await _terminate_voice_live_if_needed(websocket, session_id)

            # Handler cleanup (releases STT/TTS, cancels tasks)
            if handler:
                await handler.cleanup(websocket.app.state)

            # Unregister connection
            if conn_id:
                await websocket.app.state.conn_manager.unregister(conn_id)

            # Remove from session manager
            if session_id:
                await websocket.app.state.session_manager.remove_session(session_id)

            # Track disconnect metrics
            if hasattr(websocket.app.state, "session_metrics"):
                await websocket.app.state.session_metrics.increment_disconnected()

            # Close WebSocket
            if _is_connected(websocket):
                await websocket.close()

            # Persist analytics
            if handler and handler.memory_manager and hasattr(websocket.app.state, "cosmos"):
                try:
                    await build_and_flush(
                        handler.memory_manager, websocket.app.state.cosmos
                    )
                except Exception as e:
                    logger.error("[%s] Analytics persist error: %s", session_id, e)

            span.set_status(Status(StatusCode.OK))
            logger.info("[%s] Conversation cleanup complete", session_id)

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error("[%s] Conversation cleanup error: %s", session_id, e)


async def _terminate_voice_live_if_needed(
    websocket: WebSocket,
    session_id: Optional[str],
) -> None:
    """Terminate ACS Voice Live call if browser disconnects."""
    try:
        stream_mode = str(getattr(websocket.state, "stream_mode", "")).lower()
        is_voice_live = stream_mode == str(StreamMode.VOICE_LIVE).lower()

        if not is_voice_live:
            return
        if not getattr(websocket.state, "acs_bridged_call", False):
            return
        if getattr(websocket.state, "acs_session_terminated", False):
            return

        call_connection_id = getattr(websocket.state, "call_connection_id", None)
        if not call_connection_id:
            return

        await terminate_session(
            websocket,
            is_acs=True,
            call_connection_id=call_connection_id,
            reason=TerminationReason.NORMAL,
        )
        logger.info("[%s] ACS session terminated on frontend disconnect", session_id)
    except Exception as e:
        logger.warning("[%s] ACS termination failed: %s", session_id, e)
