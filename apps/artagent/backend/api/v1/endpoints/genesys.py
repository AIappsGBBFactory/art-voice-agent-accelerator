"""
Genesys AudioConnector WebSocket Endpoint
==========================================

Provides the WebSocket endpoint for Genesys Cloud AudioConnector integration.
Implements the AudioHook v2 server-side protocol, bridging Genesys telephony
to the ART VoiceLive multi-agent orchestrator.

WebSocket Flow:
    1. Genesys connects with ``audiohook-session-id`` header
    2. Handler accepts and starts outbound writer
    3. Client sends ``open`` → handler connects to VoiceLive + starts orchestrator
    4. Binary audio frames stream bidirectionally with codec conversion
    5. On ``close`` or disconnect → graceful shutdown

Endpoint:
    GET /api/v1/genesys/health  → Health check
    WS  /api/v1/genesys/stream  → AudioHook v2 WebSocket
"""

import asyncio
import uuid

from apps.artagent.backend.voice.genesys.handler import GenesysVoiceLiveHandler
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from opentelemetry import trace
from utils.ml_logging import get_logger

logger = get_logger("api.v1.endpoints.genesys")
tracer = trace.get_tracer(__name__)

router = APIRouter(tags=["Genesys AudioConnector"])


@router.get("/health")
async def genesys_health():
    """Health check for Genesys AudioConnector endpoint."""
    return {"status": "ok", "service": "genesys-audiohook"}


@router.websocket("/stream")
async def genesys_audiohook_stream(websocket: WebSocket):
    """AudioHook v2 WebSocket endpoint for Genesys Cloud AudioConnector.

    Genesys sends ``audiohook-session-id`` as a header or query parameter.
    The handler bridges the AudioHook v2 protocol to VoiceLive SDK for
    real-time AI-powered voice interactions.
    """
    # Extract session ID from Genesys headers
    session_id = websocket.headers.get("audiohook-session-id")
    if not session_id:
        # Fall back to query parameter or generate one
        session_id = websocket.query_params.get("session_id", str(uuid.uuid4()))

    logger.info("[Genesys] WebSocket connect | session=%s", session_id)

    handler = GenesysVoiceLiveHandler(websocket=websocket, session_id=session_id)

    await websocket.accept(subprotocol="audiohook-v2")

    try:
        await handler.start()

        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "text" in message:
                await handler.handle_text_message(message["text"])
            elif "bytes" in message:
                await handler.handle_binary_message(message["bytes"])

    except WebSocketDisconnect:
        logger.info("[Genesys] Client disconnected | session=%s", session_id)
    except Exception:
        logger.exception("[Genesys] WebSocket error | session=%s", session_id)
    finally:
        await _cleanup_genesys_websocket(websocket, handler)
        logger.info("[Genesys] WebSocket closed | session=%s", session_id)


async def _cleanup_genesys_websocket(
    websocket: WebSocket, handler: GenesysVoiceLiveHandler
) -> None:
    """Keep socket cleanup independent of native stop and caller cancellation."""
    task = getattr(websocket.state, "_genesys_cleanup_task", None)
    if task is None:

        async def cleanup() -> None:
            errors: list[Exception] = []
            registered_context = getattr(websocket.state, "session_context", None)
            try:
                await handler.stop()
            except Exception as exc:
                errors.append(exc)
            if registered_context is not None:
                try:
                    await websocket.app.state.session_manager.remove_session(
                        registered_context.session_id, expected_context=registered_context
                    )
                except Exception as exc:
                    errors.append(exc)
            if (
                websocket.client_state == WebSocketState.CONNECTED
                and websocket.application_state == WebSocketState.CONNECTED
            ):
                try:
                    await websocket.close()
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise ExceptionGroup("Genesys endpoint cleanup failed", errors)

        task = asyncio.create_task(cleanup(), name=f"genesys-endpoint-close-{handler.session_id}")
        websocket.state._genesys_cleanup_task = task

        def observe_cleanup(completed: asyncio.Task) -> None:
            if not completed.cancelled() and completed.exception() is not None:
                logger.error("[Genesys] Endpoint cleanup failed: %s", completed.exception())

        task.add_done_callback(observe_cleanup)
    await asyncio.shield(task)
