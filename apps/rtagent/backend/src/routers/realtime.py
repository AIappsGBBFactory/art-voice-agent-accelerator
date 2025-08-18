"""
routers/realtime.py
===================
• `/relay`     – dashboard broadcast WebSocket
• `/realtime`  – browser/WebRTC conversation endpoint

Relies on:
    utils.helpers.receive_and_filter
    orchestration.gpt_flow.route_turn
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.rtagent.backend.settings import GREETING
from apps.rtagent.backend.src.helpers import check_for_stopwords, receive_and_filter
from apps.rtagent.backend.src.latency.latency_tool import LatencyTool
from apps.rtagent.backend.src.orchestration.orchestrator import route_turn
from apps.rtagent.backend.src.shared_ws import broadcast_message, send_tts_audio
from src.postcall.push import build_and_flush
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger

logger = get_logger("realtime_router")

router = APIRouter()


# --------------------------------------------------------------------------- #
#  /relay  – simple fan-out to connected dashboards
# --------------------------------------------------------------------------- #
@router.websocket("/ws/relay")
async def relay_ws(ws: WebSocket):
    """
    Establish WebSocket connection for dashboard clients to receive broadcasted messages.

    This endpoint provides a relay mechanism for dashboard applications to receive
    real-time updates and events from the voice agent system. It manages client
    connections, tracks session metrics, and ensures proper message distribution
    with comprehensive connection lifecycle management.

    :param ws: The WebSocket connection from dashboard client requesting real-time updates.
    :return: None (maintains persistent connection for real-time message relay).
    :raises WebSocketDisconnect: If the dashboard client connection is terminated.
    """
    clients: set[
        WebSocket
    ] = await ws.app.state.websocket_manager.get_clients_snapshot()
    if ws not in clients:
        await ws.accept()
        clients.add(ws)

        # Track WebSocket connection for session metrics
        if hasattr(ws.app.state, "session_metrics"):
            await ws.app.state.session_metrics.increment_connected()

    try:
        while True:
            await ws.receive_text()  # keep ping/pong alive
    except WebSocketDisconnect:
        clients.remove(ws)
    finally:
        # Track WebSocket disconnection for session metrics
        if hasattr(ws.app.state, "session_metrics"):
            await ws.app.state.session_metrics.increment_disconnected()

        if ws.application_state.name == "CONNECTED" and ws.client_state.name not in (
            "DISCONNECTED",
            "CLOSED",
        ):
            await ws.close()


# --------------------------------------------------------------------------- #
#  /realtime  – browser conversation
# --------------------------------------------------------------------------- #
@router.websocket("/realtime")
async def realtime_ws(ws: WebSocket):
    """
    Handle real-time browser WebRTC client communication with voice agent orchestration.

    This WebSocket endpoint manages bidirectional communication between browser clients
    and the voice agent system. It processes speech-to-text input, orchestrates
    conversation flow through authentication and main dialog agents, and streams
    generated responses back with text-to-speech synthesis.

    :param ws: The WebSocket connection from browser/WebRTC client for real-time conversation.
    :return: None (maintains persistent connection for conversational interaction).
    :raises WebSocketDisconnect: If the browser client connection terminates unexpectedly.
    """
    try:
        await ws.accept()
        session_id = ws.headers.get("x-ms-call-connection-id") or uuid.uuid4().hex[:8]

        redis_mgr = ws.app.state.redis
        cm = MemoManager.from_redis(session_id, redis_mgr)

        # Acquire per-connection TTS synthesizer from pool
        ws.state.tts_client = await ws.app.state.tts_pool.acquire()
        logger.info(f"Acquired TTS synthesizer from pool for session {session_id}")

        ws.state.cm = cm
        ws.state.session_id = session_id
        ws.state.lt = LatencyTool(cm)
        ws.state.is_synthesizing = False
        ws.state.user_buffer = ""
        await ws.send_text(json.dumps({"type": "status", "message": GREETING}))
        auth_agent = ws.app.state.auth_agent
        cm.append_to_history(auth_agent.name, "assistant", GREETING)
        await send_tts_audio(GREETING, ws, latency_tool=ws.state.lt)

        # Track WebSocket connection for session metrics
        if hasattr(ws.app.state, "session_metrics"):
            await ws.app.state.session_metrics.increment_connected()

        clients = await ws.app.state.websocket_manager.get_clients_snapshot()
        await broadcast_message(clients, GREETING, "Auth Agent")
        await cm.persist_to_redis_async(redis_mgr)

        def on_partial(txt: str, lang: str):
            """
            Handle partial speech-to-text transcript callbacks during real-time processing.

            This callback function processes intermediate STT results as they become available,
            allowing for real-time display of transcription progress to the browser client
            before final text completion. Also manages TTS interruption when user starts speaking.

            :param txt: The partial transcript text from speech recognition service.
            :param lang: The detected language code of the spoken content.
            :return: None (sends partial results through WebSocket for immediate display).
            """
            logger.info(f"🗣️ User (partial) in {lang}: {txt}")
            if ws.state.is_synthesizing:
                try:
                    # Stop per-connection TTS synthesizer if available
                    if hasattr(ws.state, "tts_client") and ws.state.tts_client:
                        ws.state.tts_client.stop_speaking()
                    ws.state.is_synthesizing = False
                    logger.info("🛑 TTS interrupted due to user speech (server VAD)")
                except Exception as e:
                    logger.error(f"Error stopping TTS: {e}", exc_info=True)
            asyncio.create_task(
                ws.send_text(
                    json.dumps({"type": "assistant_streaming", "content": txt})
                )
            )

        # Acquire per-connection STT recognizer from pool
        ws.state.stt_client = await ws.app.state.stt_pool.acquire()
        logger.info(f"Acquired STT recognizer from pool for session {session_id}")
        ws.state.stt_client.set_partial_result_callback(on_partial)

        def on_final(txt: str, lang: str):
            """
            Handle final speech-to-text transcript completion and buffer management.

            This callback function processes completed STT results, accumulating finalized
            text into the user buffer for conversation orchestration and agent processing.
            Triggered when speech recognition determines the user has finished speaking.

            :param txt: The final complete transcript text from speech recognition service.
            :param lang: The detected language code of the spoken content.
            :return: None (accumulates text in user buffer for agent processing).
            """
            logger.info(f"🧾 User (final) in {lang}: {txt}")
            ws.state.user_buffer += txt.strip() + "\n"

        ws.state.stt_client.set_final_result_callback(on_final)
        ws.state.stt_client.start()
        logger.info("STT recognizer started for session %s", session_id)

        while True:
            msg = await ws.receive()  # can be text or bytes
            if msg.get("type") == "websocket.receive" and msg.get("bytes") is not None:
                ws.state.stt_client.write_bytes(msg["bytes"])
                if ws.state.user_buffer.strip():
                    prompt = ws.state.user_buffer.strip()
                    ws.state.user_buffer = ""

                    # Send user message to frontend immediately
                    await ws.send_text(
                        json.dumps({"sender": "User", "message": prompt})
                    )

                    if check_for_stopwords(prompt):
                        goodbye = "Thank you for using our service. Goodbye."
                        await ws.send_text(
                            json.dumps({"type": "exit", "message": goodbye})
                        )
                        await send_tts_audio(goodbye, ws, latency_tool=ws.state.lt)
                        break

                    # Note: broadcast_message for user input is handled in the orchestrator to avoid duplication
                    # pass to GPT orchestrator
                    await route_turn(cm, prompt, ws, is_acs=False)
                continue

            # —— handle disconnect ——
            if msg.get("type") == "websocket.disconnect":
                break

    finally:
        # Stop and release per-connection TTS synthesizer back to pool
        if hasattr(ws.state, "tts_client") and ws.state.tts_client:
            try:
                ws.state.tts_client.stop_speaking()
                await ws.app.state.tts_pool.release(ws.state.tts_client)
                logger.info("Released TTS synthesizer back to pool")
            except Exception as e:
                logger.error(f"Error releasing TTS synthesizer: {e}", exc_info=True)

        # Stop and release per-connection STT recognizer back to pool
        if hasattr(ws.state, "stt_client") and ws.state.stt_client:
            try:
                ws.state.stt_client.stop()
                await ws.app.state.stt_pool.release(ws.state.stt_client)
                logger.info("Released STT recognizer back to pool")
            except Exception as e:
                logger.error(f"Error releasing STT recognizer: {e}", exc_info=True)

        # Track WebSocket disconnection for session metrics
        if hasattr(ws.app.state, "session_metrics"):
            await ws.app.state.session_metrics.increment_disconnected()

        try:
            if (
                ws.application_state.name == "CONNECTED"
                and ws.client_state.name not in ("DISCONNECTED", "CLOSED")
            ):
                await ws.close()
        except Exception as e:
            logger.warning(f"WebSocket close error: {e}", exc_info=True)
        try:
            cm = getattr(ws.state, "cm", None)
            cosmos = getattr(ws.app.state, "cosmos", None)
            if cm and cosmos:
                build_and_flush(cm, cosmos)
        except Exception as e:
            logger.error(f"Error persisting analytics: {e}", exc_info=True)
