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

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from apps.rtagent.backend.src.helpers import check_for_stopwords, receive_and_filter
from apps.rtagent.backend.src.latency.latency_tool import LatencyTool
from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.src.orchestration.orchestrator import route_turn
from src.postcall.push import build_and_flush
from apps.rtagent.backend.settings import GREETING
from apps.rtagent.backend.src.shared_ws import broadcast_message, send_tts_audio
import asyncio

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
    finally:
        await ws.close()


# --------------------------------------------------------------------------- #
#  /realtime  – browser conversation
# --------------------------------------------------------------------------- #
@router.websocket("/realtime")
async def realtime_ws(ws: WebSocket):
    """
    Browser/WebRTC client sends STT text; we stream GPT + TTS back.
    The shared `route_turn` handles auth vs. main dialog.
    """
    try:
        await ws.accept()
        session_id = ws.headers.get("x-ms-call-connection-id") or uuid.uuid4().hex[:8]

        redis_mgr = ws.app.state.redis
        cm = MemoManager.from_redis(session_id, redis_mgr)
        ws.state.cm = cm
        ws.state.session_id = session_id
        ws.state.lt = LatencyTool(cm)
        ws.state.is_synthesizing = False
        ws.state.user_buffer = ""
        await ws.send_text(json.dumps({"type": "status", "message": GREETING}))
        await send_tts_audio(GREETING, ws, latency_tool=ws.state.lt)
        await broadcast_message(ws.app.state.clients, GREETING, "Assistant")
        cm.append_to_history("system", "assistant", GREETING)
        cm.persist_to_redis(redis_mgr)

        def on_partial(txt: str, lang: str):
            logger.info(f"🗣️ User (partial) in {lang}: {txt}")
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

        ws.app.state.stt_client.set_partial_result_callback(on_partial)

        def on_final(txt: str, lang: str):
            logger.info(f"🧾 User (final) in {lang}: {txt}")
            ws.state.user_buffer += txt.strip() + "\n"

        ws.app.state.stt_client.set_final_result_callback(on_final)
        ws.app.state.stt_client.start()
        logger.info("STT recognizer started for session %s", session_id)

        while True:
            msg = await ws.receive()  # can be text or bytes
            if msg.get("type") == "websocket.receive" and msg.get("bytes") is not None:
                ws.app.state.stt_client.write_bytes(msg["bytes"])
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
        ws.app.state.tts_client.stop_speaking()
        await ws.close()
        try:
            cm = getattr(ws.state, "cm", None)
            cosmos = getattr(ws.app.state, "cosmos", None)
            if cm and cosmos:
                build_and_flush(cm, cosmos)
        except Exception as e:
            logger.error(f"Error persisting analytics: {e}", exc_info=True)
