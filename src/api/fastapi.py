# /src/api/fastapi.py

import asyncio
import base64
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
from src.realtime_client.client import RealtimeClient
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fastapi_app")

# Create FastAPI app
app = FastAPI()

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active sessions
sessions = {}

@app.websocket("/ws/audio-stream/{session_id}")
async def audio_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info(f"Client connected: {session_id}")

    client = RealtimeClient(system_prompt="You are a helpful assistant.")
    sessions[session_id] = client

    try:
        await client.connect()

        # Forward only AUDIO delta events back to frontend
        def forward_audio(event: dict):
            try:
                if event.get("type") == "server.response.audio.delta" and event.get("delta"):
                    audio_bytes = base64.b64decode(event["delta"])
                    if websocket.client_state == WebSocketState.CONNECTED:
                        asyncio.create_task(websocket.send_bytes(audio_bytes))
            except Exception as e:
                logger.error(f"Error decoding or sending audio delta: {e}")

        client.on("server.response.audio.delta", forward_audio)

        # Main audio receiving loop
        while True:
            audio_data = await websocket.receive_bytes()
            await client.append_input_audio(audio_data)

    except WebSocketDisconnect:
        logger.info(f"Client {session_id} disconnected.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        try:
            if client and client.is_connected():
                await client.disconnect()
        except Exception as e:
            logger.error(f"Error during client disconnect: {e}")
        sessions.pop(session_id, None)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception as e:
            logger.error(f"Error closing websocket: {e}")
        logger.info(f"Session cleaned up: {session_id}")

@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": len(sessions)}
