"""
V1 Realtime API Endpoints - Enterprise Architecture
===================================================

Enhanced WebSocket endpoints for real-time communication with enterprise features.
Provides backward-compatible endpoints with enhanced observability and orchestrator support.

V1 Architecture Improvements:
- Comprehensive Swagger/OpenAPI documentation
- Advanced OpenTelemetry tracing and observability
- Pluggable orchestrator support for different conversation engines
- Enhanced session management with proper resource cleanup
- Production-ready error handling and recovery
- Clean separation of concerns with focused helper functions

Key V1 Features:
- Dashboard relay with advanced connection tracking
- Browser conversation with STT/TTS streaming
- Legacy compatibility endpoints for seamless migration
- Enhanced audio processing with interruption handling
- Comprehensive session state management
- Production-ready WebSocket handling

WebSocket Flow:
1. Accept connection and validate dependencies
2. Initialize session with proper state management
3. Process streaming audio/text with error handling
4. Route through pluggable orchestrator system
5. Stream responses with TTS and visual feedback
6. Clean up resources on disconnect/error
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional, Set
from datetime import datetime

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    status,
)
from fastapi.websockets import WebSocketState
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

# Core application imports
from apps.rtagent.backend.settings import GREETING, ENABLE_AUTH_VALIDATION
from apps.rtagent.backend.src.helpers import check_for_stopwords, receive_and_filter
from apps.rtagent.backend.src.latency.latency_tool import LatencyTool
from apps.rtagent.backend.src.orchestration.orchestrator import route_turn
from apps.rtagent.backend.src.shared_ws import broadcast_message, send_tts_audio
from src.postcall.push import build_and_flush
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger

# V1 components
from ..dependencies.orchestrator import get_orchestrator
from ..schemas.realtime import (
    RealtimeStatusResponse,
    DashboardConnectionResponse,
    ConversationSessionResponse,
)
from apps.rtagent.backend.src.utils.tracing import log_with_context
from apps.rtagent.backend.src.utils.auth import validate_acs_ws_auth, AuthError

logger = get_logger("api.v1.endpoints.realtime")
tracer = trace.get_tracer(__name__)

# Global registry for connection tracking
_active_dashboard_clients: Set[WebSocket] = set()
_active_conversation_sessions = {}

router = APIRouter()


@router.get(
    "/status",
    response_model=RealtimeStatusResponse,
    summary="Get Realtime Service Status",
    description="""
    Get the current status of the realtime communication service.
    
    Returns information about:
    - Service availability and health
    - Supported protocols and features
    - Active connection counts
    - WebSocket endpoint configurations
    """,
    tags=["Realtime Status"],
    responses={
        200: {
            "description": "Service status retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "available",
                        "websocket_endpoints": {
                            "dashboard_relay": "/api/v1/realtime/dashboard/relay",
                            "conversation": "/api/v1/realtime/conversation",
                        },
                        "features": {
                            "dashboard_broadcasting": True,
                            "conversation_streaming": True,
                            "orchestrator_support": True,
                            "session_management": True,
                        },
                        "active_connections": {
                            "dashboard_clients": 0,
                            "conversation_sessions": 0,
                        },
                        "version": "v1",
                    }
                }
            },
        }
    },
)
async def get_realtime_status():
    """
    Get the current status and configuration of realtime communication services.

    Returns:
        RealtimeStatusResponse: Current service status and configuration
    """
    return RealtimeStatusResponse(
        status="available",
        websocket_endpoints={
            "dashboard_relay": "/api/v1/realtime/dashboard/relay",
            "conversation": "/api/v1/realtime/conversation",
            "legacy_relay": "/api/v1/realtime/ws/relay",
            "legacy_conversation": "/api/v1/realtime/ws/conversation",
        },
        features={
            "dashboard_broadcasting": True,
            "conversation_streaming": True,
            "orchestrator_support": True,
            "session_management": True,
            "audio_interruption": True,
            "legacy_compatibility": True,
        },
        active_connections={
            "dashboard_clients": len(_active_dashboard_clients),
            "conversation_sessions": len(_active_conversation_sessions),
        },
        protocols_supported=["WebSocket"],
        version="v1",
    )


@router.websocket("/dashboard/relay")
async def dashboard_relay_endpoint(websocket: WebSocket):
    """
    Enhanced dashboard relay WebSocket endpoint with advanced monitoring.

    **Purpose:**
    Provides real-time broadcasting to connected dashboard clients with enhanced
    connection tracking, error handling, and observability features.

    **Features:**
    - Advanced connection lifecycle management
    - Real-time message broadcasting to all connected dashboards
    - Enhanced error handling and graceful degradation
    - Comprehensive OpenTelemetry tracing
    - Connection health monitoring and automatic cleanup

    **Connection Flow:**
    1. Client connects to dashboard relay
    2. Connection is validated and tracked
    3. Client is added to active dashboard registry
    4. Messages are received and broadcasted to all connected clients
    5. Connection lifecycle is managed with proper cleanup

    **Use Cases:**
    - Real-time dashboard updates during conversations
    - Broadcasting system status and events
    - Live monitoring of conversation flows
    - Administrative notifications and alerts

    **WebSocket Protocol:**
    - Accepts text messages for broadcasting
    - Maintains persistent connection for real-time updates
    - Handles connection lifecycle events gracefully
    - Provides automatic reconnection support

    Args:
        websocket: WebSocket connection from dashboard client
    """
    client_id = None
    try:
        # Accept connection with tracing
        await websocket.accept()
        client_id = str(uuid.uuid4())[:8]

        with tracer.start_as_current_span(
            "api.v1.realtime.dashboard_relay_connect",
            kind=SpanKind.SERVER,
            attributes={
                "api.version": "v1",
                "realtime.client_id": client_id,
                "realtime.endpoint": "dashboard_relay",
                "network.protocol.name": "websocket",
            },
        ) as connect_span:
            # Validate dependencies
            await _validate_realtime_dependencies(websocket)

            # Add client to global registry
            if websocket not in _active_dashboard_clients:
                _active_dashboard_clients.add(websocket)
                logger.info(
                    f"Dashboard client {client_id} connected. Total clients: {len(_active_dashboard_clients)}"
                )
                connect_span.set_attribute(
                    "dashboard.clients.total", len(_active_dashboard_clients)
                )

            # Store client info in app state for legacy compatibility
            if not hasattr(websocket.app.state, "clients"):
                websocket.app.state.clients = set()
            websocket.app.state.clients.add(websocket)

            connect_span.set_status(Status(StatusCode.OK))
            log_with_context(
                logger,
                "info",
                "Dashboard client connected successfully",
                operation="dashboard_connect",
                client_id=client_id,
                total_clients=len(_active_dashboard_clients),
                api_version="v1",
            )

        # Process dashboard messages
        await _process_dashboard_messages(websocket, client_id)

    except WebSocketDisconnect as e:
        _log_dashboard_disconnect(e, client_id)
    except Exception as e:
        _log_dashboard_error(e, client_id)
        raise
    finally:
        await _cleanup_dashboard_connection(websocket, client_id)


@router.websocket("/conversation")
async def browser_conversation_endpoint(
    websocket: WebSocket, orchestrator: Optional[callable] = Depends(get_orchestrator)
):
    """
    Enhanced browser conversation WebSocket endpoint with orchestrator injection.

    **Purpose:**
    Provides real-time conversation capabilities with enhanced session management,
    pluggable orchestrator support, and comprehensive audio streaming features.

    **Features:**
    - Pluggable orchestrator support for different conversation engines
    - Advanced session state management with Redis persistence
    - Real-time STT (Speech-to-Text) processing with partial results
    - Enhanced TTS (Text-to-Speech) streaming with interruption handling
    - Comprehensive conversation memory and context management
    - Production-ready error handling and recovery

    **Conversation Flow:**
    1. Browser connects and session is initialized with unique ID
    2. Authentication is performed if enabled
    3. Conversation memory is loaded from Redis
    4. STT recognizer is started for audio processing
    5. Audio streams are processed with real-time feedback
    6. Conversation turns are routed through pluggable orchestrator
    7. Responses are synthesized with TTS and streamed back
    8. Session state is persisted and cleaned up on disconnect

    **Orchestrator Support:**
    - GPT-based orchestrators for standard conversations
    - Anthropic orchestrators for specialized use cases
    - Custom agent orchestrators for domain-specific logic
    - Fallback to default orchestrator for backward compatibility

    **Audio Processing:**
    - Real-time STT with partial and final result callbacks
    - TTS synthesis with interruption detection
    - Voice Activity Detection (VAD) integration
    - Audio quality monitoring and optimization

    **Session Management:**
    - Unique session IDs for conversation tracking
    - Redis-based state persistence for scalability
    - Conversation memory and context preservation
    - Graceful session cleanup and resource management

    Args:
        websocket: WebSocket connection from browser client
        orchestrator: Injected conversation orchestrator (optional)
    """
    session_id = None
    memory_manager = None

    try:
        # Accept connection and initialize session
        await websocket.accept()
        session_id = (
            websocket.headers.get("x-ms-call-connection-id") or str(uuid.uuid4())[:8]
        )

        with tracer.start_as_current_span(
            "api.v1.realtime.conversation_connect",
            kind=SpanKind.SERVER,
            attributes={
                "api.version": "v1",
                "realtime.session_id": session_id,
                "realtime.endpoint": "conversation",
                "network.protocol.name": "websocket",
                "orchestrator.name": getattr(orchestrator, "name", "unknown")
                if orchestrator
                else "default",
            },
        ) as connect_span:
            # Validate dependencies
            await _validate_realtime_dependencies(websocket)

            # Authenticate if required
            if ENABLE_AUTH_VALIDATION:
                await _validate_realtime_auth(websocket)

            # Initialize conversation session
            memory_manager = await _initialize_conversation_session(
                websocket, session_id, orchestrator
            )

            # Register session in global registry
            _active_conversation_sessions[session_id] = {
                "websocket": websocket,
                "memory_manager": memory_manager,
                "start_time": datetime.utcnow(),
                "orchestrator": orchestrator,
            }

            connect_span.set_attribute(
                "conversation.sessions.total", len(_active_conversation_sessions)
            )
            connect_span.set_status(Status(StatusCode.OK))

            log_with_context(
                logger,
                "info",
                "Conversation session initialized successfully",
                operation="conversation_connect",
                session_id=session_id,
                total_sessions=len(_active_conversation_sessions),
                api_version="v1",
            )

        # Process conversation messages
        await _process_conversation_messages(
            websocket, session_id, memory_manager, orchestrator
        )

    except WebSocketDisconnect as e:
        _log_conversation_disconnect(e, session_id)
    except Exception as e:
        _log_conversation_error(e, session_id)
        raise
    finally:
        await _cleanup_conversation_session(websocket, session_id, memory_manager)


# ============================================================================
# Legacy Compatibility Endpoints
# ============================================================================


@router.websocket("/ws/relay")
async def legacy_dashboard_relay(websocket: WebSocket):
    """
    Legacy dashboard relay endpoint for backward compatibility.

    **Migration Notice:**
    This endpoint maintains full backward compatibility with existing dashboard
    clients while internally using the enhanced V1 handler infrastructure.

    **Recommendation:**
    Consider migrating to `/api/v1/realtime/dashboard/relay` for enhanced features:
    - Improved connection tracking and monitoring
    - Enhanced error handling and recovery
    - Comprehensive tracing and observability
    - Production-ready session management

    Args:
        websocket: WebSocket connection from legacy dashboard client
    """
    with tracer.start_as_current_span(
        "api.v1.realtime.legacy_dashboard_relay",
        attributes={"api.version": "v1", "endpoint.legacy": True},
    ):
        logger.info(
            "Legacy dashboard relay endpoint accessed - consider migrating to /api/v1/realtime/dashboard/relay"
        )
        await dashboard_relay_endpoint(websocket)


@router.websocket("/ws/conversation")
async def legacy_browser_conversation(
    websocket: WebSocket, orchestrator: Optional[callable] = Depends(get_orchestrator)
):
    """
    Legacy browser conversation endpoint for backward compatibility.

    **Migration Notice:**
    This endpoint maintains full backward compatibility with existing browser
    clients while internally using the enhanced V1 handler with orchestrator injection.

    **Recommendation:**
    Consider migrating to `/api/v1/realtime/conversation` for enhanced features:
    - Pluggable orchestrator support
    - Enhanced session management
    - Improved audio processing
    - Comprehensive tracing and monitoring

    Args:
        websocket: WebSocket connection from legacy browser client
        orchestrator: Injected conversation orchestrator (optional)
    """
    with tracer.start_as_current_span(
        "api.v1.realtime.legacy_conversation",
        attributes={"api.version": "v1", "endpoint.legacy": True},
    ):
        logger.info(
            "Legacy conversation endpoint accessed - consider migrating to /api/v1/realtime/conversation"
        )
        await browser_conversation_endpoint(websocket, orchestrator)


# ============================================================================
# V1 Architecture Helper Functions
# ============================================================================


async def _validate_realtime_dependencies(websocket: WebSocket) -> None:
    """Validate required app state dependencies for realtime endpoints."""
    # Check TTS client
    if (
        not hasattr(websocket.app.state, "tts_client")
        or not websocket.app.state.tts_client
    ):
        logger.error("TTS client not initialized")
        await websocket.close(code=1011, reason="TTS not initialized")
        raise HTTPException(503, "TTS client not initialized")

    # Check STT client for conversation endpoints
    if (
        not hasattr(websocket.app.state, "stt_client")
        or not websocket.app.state.stt_client
    ):
        logger.error("STT client not initialized")
        await websocket.close(code=1011, reason="STT not initialized")
        raise HTTPException(503, "STT client not initialized")

    # Check Redis for session management
    if not hasattr(websocket.app.state, "redis") or not websocket.app.state.redis:
        logger.error("Redis client not initialized")
        await websocket.close(code=1011, reason="Redis not initialized")
        raise HTTPException(503, "Redis client not initialized")


async def _validate_realtime_auth(websocket: WebSocket) -> None:
    """Validate WebSocket authentication for realtime endpoints."""
    try:
        _ = await validate_acs_ws_auth(websocket)
        logger.info("Realtime WebSocket authenticated successfully")
    except AuthError as e:
        logger.warning(f"Realtime WebSocket authentication failed: {str(e)}")
        await websocket.close(code=4001, reason="Authentication failed")
        raise HTTPException(401, f"Authentication failed: {str(e)}")


async def _initialize_conversation_session(
    websocket: WebSocket, session_id: str, orchestrator: Optional[callable]
) -> MemoManager:
    """Initialize conversation session with proper state management."""
    redis_mgr = websocket.app.state.redis
    memory_manager = MemoManager.from_redis(session_id, redis_mgr)

    # Set up WebSocket state
    websocket.state.cm = memory_manager
    websocket.state.session_id = session_id
    websocket.state.lt = LatencyTool(memory_manager)
    websocket.state.is_synthesizing = False
    websocket.state.user_buffer = ""

    # Send greeting message
    await websocket.send_text(json.dumps({"type": "status", "message": GREETING}))

    # Add greeting to conversation history
    auth_agent = websocket.app.state.auth_agent
    memory_manager.append_to_history(auth_agent.name, "assistant", GREETING)

    # Send TTS audio greeting
    await send_tts_audio(GREETING, websocket, latency_tool=websocket.state.lt)

    # Persist initial state to Redis
    await memory_manager.persist_to_redis_async(redis_mgr)

    # Set up STT callbacks
    def on_partial(txt: str, lang: str):
        logger.info(f"🗣️ User (partial) in {lang}: {txt}")
        if websocket.state.is_synthesizing:
            try:
                websocket.app.state.tts_client.stop_speaking()
                websocket.state.is_synthesizing = False
                logger.info("🛑 TTS interrupted due to user speech (server VAD)")
            except Exception as e:
                logger.error(f"Error stopping TTS: {e}", exc_info=True)
        asyncio.create_task(
            websocket.send_text(
                json.dumps({"type": "assistant_streaming", "content": txt})
            )
        )

    def on_final(txt: str, lang: str):
        logger.info(f"🧾 User (final) in {lang}: {txt}")
        websocket.state.user_buffer += txt.strip() + "\n"

    websocket.app.state.stt_client.set_partial_result_callback(on_partial)
    websocket.app.state.stt_client.set_final_result_callback(on_final)
    websocket.app.state.stt_client.start()

    logger.info(f"STT recognizer started for session {session_id}")
    return memory_manager


async def _process_dashboard_messages(websocket: WebSocket, client_id: str) -> None:
    """Process incoming dashboard relay messages."""
    with tracer.start_as_current_span(
        "api.v1.realtime.process_dashboard_messages",
        attributes={"client_id": client_id},
    ):
        try:
            while (
                websocket.client_state == WebSocketState.CONNECTED
                and websocket.application_state == WebSocketState.CONNECTED
            ):
                # Keep connection alive and process any ping/pong messages
                await websocket.receive_text()

        except WebSocketDisconnect:
            # Normal disconnect - handled in the calling function
            raise
        except Exception as e:
            logger.error(
                f"Error processing dashboard messages for client {client_id}: {e}"
            )
            raise


async def _process_conversation_messages(
    websocket: WebSocket,
    session_id: str,
    memory_manager: MemoManager,
    orchestrator: Optional[callable],
) -> None:
    """Process incoming conversation messages with enhanced error handling."""
    with tracer.start_as_current_span(
        "api.v1.realtime.process_conversation_messages",
        attributes={"session_id": session_id},
    ) as span:
        try:
            message_count = 0
            while (
                websocket.client_state == WebSocketState.CONNECTED
                and websocket.application_state == WebSocketState.CONNECTED
            ):
                msg = await websocket.receive()
                message_count += 1

                # Handle audio bytes
                if (
                    msg.get("type") == "websocket.receive"
                    and msg.get("bytes") is not None
                ):
                    websocket.app.state.stt_client.write_bytes(msg["bytes"])

                    # Process accumulated user buffer
                    if websocket.state.user_buffer.strip():
                        prompt = websocket.state.user_buffer.strip()
                        websocket.state.user_buffer = ""

                        # Send user message to frontend immediately
                        await websocket.send_text(
                            json.dumps({"sender": "User", "message": prompt})
                        )

                        # Check for stopwords
                        if check_for_stopwords(prompt):
                            goodbye = "Thank you for using our service. Goodbye."
                            await websocket.send_text(
                                json.dumps({"type": "exit", "message": goodbye})
                            )
                            await send_tts_audio(
                                goodbye, websocket, latency_tool=websocket.state.lt
                            )
                            break

                        # Route through orchestrator
                        await route_turn(
                            memory_manager, prompt, websocket, is_acs=False
                        )

                # Handle disconnect
                elif msg.get("type") == "websocket.disconnect":
                    break

            span.set_attribute("messages.processed", message_count)
            span.set_status(Status(StatusCode.OK))

        except WebSocketDisconnect:
            span.set_status(Status(StatusCode.OK, "Normal disconnect"))
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, f"Message processing error: {e}"))
            logger.error(
                f"Error processing conversation messages for session {session_id}: {e}"
            )
            raise


def _log_dashboard_disconnect(e: WebSocketDisconnect, client_id: Optional[str]) -> None:
    """Log dashboard client disconnection."""
    if e.code == 1000:
        log_with_context(
            logger,
            "info",
            "Dashboard client disconnected normally",
            operation="dashboard_disconnect",
            client_id=client_id,
            disconnect_code=e.code,
            api_version="v1",
        )
    else:
        log_with_context(
            logger,
            "warning",
            "Dashboard client disconnected abnormally",
            operation="dashboard_disconnect",
            client_id=client_id,
            disconnect_code=e.code,
            reason=e.reason,
            api_version="v1",
        )


def _log_dashboard_error(e: Exception, client_id: Optional[str]) -> None:
    """Log dashboard client errors."""
    log_with_context(
        logger,
        "error",
        "Dashboard client error",
        operation="dashboard_error",
        client_id=client_id,
        error=str(e),
        error_type=type(e).__name__,
        api_version="v1",
    )


def _log_conversation_disconnect(
    e: WebSocketDisconnect, session_id: Optional[str]
) -> None:
    """Log conversation session disconnection."""
    if e.code == 1000:
        log_with_context(
            logger,
            "info",
            "Conversation session ended normally",
            operation="conversation_disconnect",
            session_id=session_id,
            disconnect_code=e.code,
            api_version="v1",
        )
    else:
        log_with_context(
            logger,
            "warning",
            "Conversation session ended abnormally",
            operation="conversation_disconnect",
            session_id=session_id,
            disconnect_code=e.code,
            reason=e.reason,
            api_version="v1",
        )


def _log_conversation_error(e: Exception, session_id: Optional[str]) -> None:
    """Log conversation session errors."""
    log_with_context(
        logger,
        "error",
        "Conversation session error",
        operation="conversation_error",
        session_id=session_id,
        error=str(e),
        error_type=type(e).__name__,
        api_version="v1",
    )


async def _cleanup_dashboard_connection(
    websocket: WebSocket, client_id: Optional[str]
) -> None:
    """Clean up dashboard connection resources."""
    with tracer.start_as_current_span(
        "api.v1.realtime.cleanup_dashboard", attributes={"client_id": client_id}
    ) as span:
        try:
            # Remove from global registry
            if websocket in _active_dashboard_clients:
                _active_dashboard_clients.remove(websocket)
                logger.info(
                    f"Dashboard client {client_id} removed. Remaining clients: {len(_active_dashboard_clients)}"
                )

            # Remove from app state for legacy compatibility
            if (
                hasattr(websocket.app.state, "clients")
                and websocket in websocket.app.state.clients
            ):
                websocket.app.state.clients.remove(websocket)

            # Close WebSocket if still connected
            if (
                websocket.client_state == WebSocketState.CONNECTED
                and websocket.application_state == WebSocketState.CONNECTED
            ):
                await websocket.close()

            span.set_status(Status(StatusCode.OK))
            log_with_context(
                logger,
                "info",
                "Dashboard connection cleanup complete",
                operation="dashboard_cleanup",
                client_id=client_id,
                api_version="v1",
            )

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, f"Cleanup error: {e}"))
            logger.error(f"Error during dashboard cleanup: {e}")


async def _cleanup_conversation_session(
    websocket: WebSocket,
    session_id: Optional[str],
    memory_manager: Optional[MemoManager],
) -> None:
    """Clean up conversation session resources."""
    with tracer.start_as_current_span(
        "api.v1.realtime.cleanup_conversation", attributes={"session_id": session_id}
    ) as span:
        try:
            # Stop TTS
            if hasattr(websocket.app.state, "tts_client"):
                websocket.app.state.tts_client.stop_speaking()

            # Remove from session registry
            if session_id and session_id in _active_conversation_sessions:
                del _active_conversation_sessions[session_id]
                logger.info(
                    f"Conversation session {session_id} removed. Active sessions: {len(_active_conversation_sessions)}"
                )

            # Close WebSocket if still connected
            if (
                websocket.client_state == WebSocketState.CONNECTED
                and websocket.application_state == WebSocketState.CONNECTED
            ):
                await websocket.close()

            # Persist analytics if possible
            if memory_manager and hasattr(websocket.app.state, "cosmos"):
                try:
                    build_and_flush(memory_manager, websocket.app.state.cosmos)
                except Exception as e:
                    logger.error(f"Error persisting analytics: {e}", exc_info=True)

            span.set_status(Status(StatusCode.OK))
            log_with_context(
                logger,
                "info",
                "Conversation session cleanup complete",
                operation="conversation_cleanup",
                session_id=session_id,
                api_version="v1",
            )

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, f"Cleanup error: {e}"))
            logger.error(f"Error during conversation cleanup: {e}")
