"""
routers/acs.py
==============
Outbound phone-call flow via Azure Communication Services.

• POST  /call             – start a phone call
• POST  /call/callbacks   – receive ACS events
• WS    /call/stream      – bidirectional PCM audio stream
"""
from __future__ import annotations

import asyncio
import json
import time
from base64 import b64decode
from typing import Dict

from azure.core.exceptions import HttpResponseError
from azure.core.messaging import CloudEvent
from azure.cognitiveservices.speech.audio import AudioStreamFormat, PushAudioInputStream
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketState
from pydantic import BaseModel

from conversation_state import ConversationManager
from helpers import check_for_stopwords
from orchestration.gpt_flow import route_turn
from shared_ws import (                       
    broadcast_message,
    send_response_to_acs,
)
from settings import ACS_CALL_PATH, ACS_CALLBACK_PATH, ACS_WEBSOCKET_PATH
from utils.ml_logging import get_logger

logger = get_logger("routers.acs")
router = APIRouter()

# --------------------------------------------------------------------------- #
#  1. Call initiation  (POST /call)
# --------------------------------------------------------------------------- #
class CallRequest(BaseModel):
    target_number: str


@router.post(ACS_CALL_PATH)
async def initiate_call(call: CallRequest, request: Request):
    acs = request.app.state.acs_caller
    if not acs:
        raise HTTPException(503, "ACS Caller not initialised")

    try:
        result = await acs.initiate_call(call.target_number)
        if result.get("status") != "created":
            return JSONResponse({"status": "failed"}, status_code=400)

        call_id = result["call_id"]
        logger.info("Call initiated – ID=%s", call_id)
        return {"message": "Call initiated", "callId": call_id}
    except (HttpResponseError, RuntimeError) as exc:
        logger.error("ACS error: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc)) from exc


# --------------------------------------------------------------------------- #
#  2. Callback events  (POST /call/callbacks)
# --------------------------------------------------------------------------- #
@router.post(ACS_CALLBACK_PATH)
async def callbacks(request: Request):
    if not request.app.state.acs_caller:
        return JSONResponse({"error": "ACS not initialised"}, status_code=503)

    try:
        events = await request.json()
        for raw in events:
            event = CloudEvent.from_dict(raw)
            etype = event.type
            cid = event.data.get("callConnectionId")
            emoji = {
                "Microsoft.Communication.CallConnected": "📞",
                "Microsoft.Communication.CallDisconnected": "❌",
                "Microsoft.Communication.MediaStreamingStarted": "🎙️",
                "Microsoft.Communication.MediaStreamingStopped": "🛑",
            }.get(etype, "ℹ️")

            await broadcast_message(request.app.state.clients, f"{emoji} {etype}")
            logger.info("%s %s", etype, cid)
        return {"status": "callback received"}
    except Exception as exc:        # pylint: disable=broad-except
        logger.error("Callback error: %s", exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


# --------------------------------------------------------------------------- #
#  3. Media-streaming WebSocket  (WS /call/stream)
# --------------------------------------------------------------------------- #
call_user_raw_ids: Dict[str, str] = {}


@router.websocket(ACS_WEBSOCKET_PATH)
async def acs_media_ws(ws: WebSocket):
    speech = ws.app.state.stt_client
    acs = ws.app.state.acs_caller
    if not speech or not acs:
        await ws.close(code=1011)
        return

    await ws.accept()
    cid = ws.headers.get("x-ms-call-connection-id", "UnknownCall")
    logger.info("▶ media WS connected – %s", cid)

    # ----------------------------------------------------------------------- #
    #  Local objects
    # ----------------------------------------------------------------------- #
    queue: asyncio.Queue[str] = asyncio.Queue()
    push_stream = PushAudioInputStream(
        stream_format=AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
    )
    recogniser = speech.create_realtime_recognizer(
        push_stream=push_stream,
        loop=asyncio.get_event_loop(),
        message_queue=queue,
        language="en-US",
        vad_silence_timeout_ms=500,       
    )
    recogniser.start_continuous_recognition_async()

    redis_mgr = ws.app.state.redis
    cm = ConversationManager.from_redis(cid, redis_mgr)

    clients = ws.app.state.clients
    greeted: set[str] = ws.app.state.greeted_call_ids
    if cid not in greeted:
        greet = (
            "Hello from XMYX Healthcare Company! Before I can assist you, "
            "let’s verify your identity. How may I address you?"
        )
        await broadcast_message(clients, greet, "Assistant")
        await send_response_to_acs(ws, greet)
        cm.append_to_history("assistant", greet)
        greeted.add(cid)

    user_raw_id = call_user_raw_ids.get(cid)

    try:
        # --- inside acs_media_ws ---------------------------------------------------
        while True:
            spoken: str | None = None
            try:
                while True:
                    item = queue.get_nowait()
                    spoken = f"{spoken} {item}".strip() if spoken else item
                    queue.task_done()
            except asyncio.QueueEmpty:
                pass

            if spoken:
                ws.app.state.tts_client.stop_speaking()
                for t in list(getattr(ws.app.state, "tts_tasks", [])):
                    t.cancel()

                await broadcast_message(clients, spoken, "User")

                if check_for_stopwords(spoken):
                    await broadcast_message(clients, "Goodbye!", "Assistant")
                    await send_response_to_acs(ws, "Goodbye!", blocking=True)
                    await asyncio.sleep(1)
                    await acs.disconnect_call(cid)
                    break

                await route_turn(cm, spoken, ws, is_acs=True)
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
                data = json.loads(raw)
            except asyncio.TimeoutError:
                if ws.client_state != WebSocketState.CONNECTED:
                    break           
                continue            
            except (WebSocketDisconnect, json.JSONDecodeError):
                break

            kind = data.get("kind")
            if kind == "AudioData":
                # dynamically learn / confirm the caller’s participantRawID
                if not user_raw_id and cid in call_user_raw_ids:
                    user_raw_id = call_user_raw_ids[cid]

                if user_raw_id and data["audioData"]["participantRawID"] != user_raw_id:
                    continue        # discard bot’s own audio

                try:
                    push_stream.write(b64decode(data["audioData"]["data"]))
                except Exception:
                    # keep going even if decode glitches
                    continue

            elif kind == "CallConnected":
                pid = data["callConnected"]["participant"]["rawID"]
                call_user_raw_ids[cid] = pid
                user_raw_id = pid

    finally:
        try:
            recogniser.stop_continuous_recognition_async()
        except Exception:  # pylint: disable=broad-except
            pass
        push_stream.close()
        await ws.close()
        call_user_raw_ids.pop(cid, None)
        cm.persist_to_redis(redis_mgr)
        logger.info("◀ media WS closed – %s", cid)