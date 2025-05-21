import asyncio
import json
import logging
import os
from typing import Optional

import websockets
from azure.communication.callautomation import (
    AudioFormat,
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    MediaStreamingTransportType,
    PhoneNumberIdentifier,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
app = FastAPI()

# ENV VARS
ACS_CONNECTION_STRING = os.environ["ACS_CONNECTION_STRING"]
ACS_SOURCE_PHONE_NUMBER = os.environ["ACS_SOURCE_PHONE_NUMBER"]
TARGET_PHONE_NUMBER = os.environ["TARGET_PHONE_NUMBER"]
BASE_URL = os.environ["BASE_URL"]  # e.g. https://xyz-8010.use.devtunnels.ms
ACS_WEBSOCKET_PATH = "/acs-ws"
AZURE_TRANSCRIBE_WS = os.environ["AZURE_TRANSCRIBE_WS"]  # See above
AZURE_TRANSCRIBE_KEY = os.environ["AZURE_TRANSCRIBE_KEY"]


# -- Helper: build ACS WebSocket URL
def construct_websocket_url(base_url: str, path: str) -> str:
    url = base_url.rstrip("/") + path
    if url.startswith("https://"):
        url = "wss://" + url[8:]
    elif url.startswith("http://"):
        url = "ws://" + url[7:]
    return url


ACS_WEBSOCKET_URL = construct_websocket_url(BASE_URL, ACS_WEBSOCKET_PATH)


# =========================================
# 1. Endpoint to trigger ACS call
# =========================================
@app.post("/call")
async def initiate_call():
    client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)
    source = PhoneNumberIdentifier(ACS_SOURCE_PHONE_NUMBER)
    target = PhoneNumberIdentifier(TARGET_PHONE_NUMBER)
    media_streaming = MediaStreamingOptions(
        transport_url=ACS_WEBSOCKET_URL,
        transport_type=MediaStreamingTransportType.WEBSOCKET,
        content_type=MediaStreamingContentType.AUDIO,
        audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
        start_media_streaming=True,
        enable_bidirectional=False,
        audio_format=AudioFormat.PCM16_K_MONO,
    )
    response = client.create_call(
        target_participant=target,
        callback_url=BASE_URL + "/dummy-callback",
        media_streaming=media_streaming,
        source_caller_id_number=source,
    )
    logging.info(f"Calling {TARGET_PHONE_NUMBER} (ID: {response.call_connection_id})")
    return JSONResponse({"status": "created", "call_id": response.call_connection_id})


# =========================================
# 2. ACS Media WebSocket: Relay PCM to Azure GPT-4o Transcribe WS
# =========================================
@app.websocket(ACS_WEBSOCKET_PATH)
async def acs_ws(ws: WebSocket):
    await ws.accept()
    logging.info(
        "ACS Media WebSocket connected. Connecting to Azure GPT-4o Transcribe..."
    )

    # -- Open GPT-4o WS session
    headers = {"api-key": AZURE_TRANSCRIBE_KEY}
    session_config = {
        "input_audio_format": "pcm16",
        "input_audio_transcription": {
            "model": "gpt-4o-transcribe",
            "prompt": "Transcribe clearly. Respond in English.",
        },
        "input_audio_noise_reduction": {"type": "near_field"},
        "turn_detection": {"type": "server_vad"},
    }

    async with websockets.connect(
        AZURE_TRANSCRIBE_WS, extra_headers=headers
    ) as azure_ws:
        # 1. Configure session and audio start
        await azure_ws.send(
            json.dumps(
                {"type": "transcription_session.update", "session": session_config}
            )
        )
        await azure_ws.send(
            json.dumps(
                {
                    "type": "audio_start",
                    "data": {"encoding": "pcm", "sample_rate": 16000, "channels": 1},
                }
            )
        )
        print("🔄 Session/config sent to Azure GPT-4o Transcribe")

        # 2. Relay audio ACS → GPT-4o, print transcriptions
        relay_task = asyncio.create_task(relay_acs_to_azure(ws, azure_ws))
        receive_task = asyncio.create_task(print_gpt4o_results(azure_ws))
        await asyncio.gather(relay_task, receive_task)


# -- Helper: Relay ACS PCM audio chunks to Azure
async def relay_acs_to_azure(acs_ws, azure_ws):
    while True:
        try:
            msg = await acs_ws.receive_text()
            b64 = extract_pcm_base64(msg)
            if b64:
                await azure_ws.send(
                    json.dumps({"type": "input_audio_buffer.append", "audio": b64})
                )
        except WebSocketDisconnect:
            print("ACS WebSocket disconnected")
            break


# -- Helper: Extract PCM from ACS media JSON
def extract_pcm_base64(ws_json: str) -> Optional[str]:
    try:
        msg = json.loads(ws_json)
        if msg.get("kind") == "AudioData":
            return msg["audioData"]["data"]
    except Exception:
        pass
    return None


# -- Helper: Print real-time results from Azure GPT-4o Transcribe
async def print_gpt4o_results(azure_ws):
    async for message in azure_ws:
        try:
            data = json.loads(message)
            event_type = data.get("type", "")
            if event_type == "conversation.item.input_audio_transcription.delta":
                delta = data.get("delta", "")
                if delta:
                    print("[TRANSCRIBE DELTA]:", delta)
            elif event_type == "conversation.item.input_audio_transcription.completed":
                transcript = data.get("transcript", "")
                if transcript:
                    print("[FINAL TRANSCRIPT]:", transcript)
            elif event_type == "conversation.item.created":
                item = data.get("item", "")
                if isinstance(item, dict) and "content" in item and item["content"]:
                    t = item["content"][0].get("transcript")
                    if t:
                        print("[ITEM TRANSCRIPT]:", t)
        except Exception as e:
            print("Error parsing Azure message:", e)


# =========================================
# 3. Run with Uvicorn
# =========================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
