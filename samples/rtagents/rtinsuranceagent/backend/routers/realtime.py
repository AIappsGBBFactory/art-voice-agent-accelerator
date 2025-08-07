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
from helpers import check_for_stopwords, receive_and_filter
from rtagents.RTInsuranceAgent.backend.latency.latency_tool import LatencyTool
from rtagents.RTInsuranceAgent.backend.orchestration.orchestrator import route_turn
from rtagents.RTInsuranceAgent.backend.postcall.push import build_and_flush
from rtagents.RTInsuranceAgent.backend.settings import GREETING
from rtagents.RTInsuranceAgent.backend.src.stateful.state_managment import MemoManager
from shared_ws import broadcast_message, send_tts_audio

from utils.ml_logging import get_logger

logger = get_logger("realtime_router")


router = APIRouter()


# --------------------------------------------------------------------------- #
#  /relay  – simple fan-out to connected dashboards
# --------------------------------------------------------------------------- #
@router.websocket("/relay")
async def relay_ws(ws: WebSocket):
    """Dashboards connect here to receive broadcasted text."""
    clients: set[WebSocket] = ws.app.state.clients
    if ws not in clients:
        await ws.accept()
        clients.add(ws)

    try:
        while True:
            await ws.receive_text()  # keep ping/pong alive
    except WebSocketDisconnect:
        clients.remove(ws)


# --------------------------------------------------------------------------- #
#  /realtime  – browser conversation
# --------------------------------------------------------------------------- #
@router.websocket("/realtime")
async def realtime_ws(ws: WebSocket):
    await ws.accept()
    session_id = ws.headers.get("x-ms-call-connection-id") or uuid.uuid4().hex[:8]

    redis_mgr = ws.app.state.redis
    cm = MemoManager.from_redis(session_id, redis_mgr)
    ws.state.cm = cm
    ws.state.lt = LatencyTool(cm)
    ws.state.is_synthesizing = False
    ws.state.user_buffer = ""

    greeting = GREETING
    await ws.send_text(json.dumps({"type": "status", "message": greeting}))
    await send_tts_audio(greeting, ws, latency_tool=ws.state.lt)
    cm.append_to_history("system", "assistant", greeting)
    cm.persist_to_redis(redis_mgr)

    def on_partial(txt: str, lang: str):
        logger.info(f"[STT Partial] {txt} (lang={lang})")
        if ws.state.is_synthesizing:
            try:
                ws.app.state.tts_client.stop_speaking()
                ws.state.is_synthesizing = False
                logger.info("🛑 TTS interrupted due to user speech (server VAD)")
            except Exception as e:
                logger.error(f"Error stopping TTS: {e}", exc_info=True)
        asyncio.create_task(
            ws.send_text(json.dumps({"type": "assistant_streaming", "content": txt}))
        )

    ws.app.state.stt_bytes_client.set_partial_result_callback(on_partial)

    def on_final(txt: str, lang: str):
        logger.info(f"[STT Final] {txt} (lang={lang})")
        ws.state.user_buffer += txt.strip() + "\n"

    ws.app.state.stt_bytes_client.set_final_result_callback(on_final)
    ws.app.state.stt_bytes_client.start()
    logger.info("STT recognizer started for session %s", session_id)

    try:
        while True:
            msg = await ws.receive()  # can be text or bytes
            if msg.get("type") == "websocket.receive" and msg.get("bytes") is not None:
                logger.info(
                    f"Received audio bytes from frontend: {len(msg['bytes'])} bytes"
                )
                ws.app.state.stt_bytes_client.write_bytes(msg["bytes"])
                logger.debug(f"First 8 bytes: {msg['bytes'][:8].hex()}")
                if ws.state.user_buffer.strip():
                    prompt = ws.state.user_buffer.strip()
                    ws.state.user_buffer = ""
                    await broadcast_message(ws.app.state.clients, prompt, "User")

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

                    # pass to GPT orchestrator
                    await route_turn(cm, prompt, ws, is_acs=False)
                continue

            # —— handle disconnect ——
            if msg.get("type") == "websocket.disconnect":
                break

    finally:
        ws.app.state.stt_bytes_client.close_stream()
        ws.app.state.stt_bytes_client.stop()
        logger.info("STT recognizer stopped for session %s", session_id)
        try:
            cosmos = getattr(ws.app.state, "cosmos", None)
            if cm and cosmos:
                build_and_flush(cm, cosmos)
        except Exception as e:
            logger.error(f"Error persisting analytics: {e}", exc_info=True)
