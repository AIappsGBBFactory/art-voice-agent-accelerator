# /app/gradio_app/main.py

import asyncio
import websockets
import threading
import queue
import sounddevice as sd
import numpy as np
import gradio as gr
import uuid

# Configuration
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
FASTAPI_WS_URL = "ws://localhost:8010/ws/audio-stream/"  # Change port if needed

# Unique session per user
session_id = str(uuid.uuid4())

# Queues
mic_audio_queue = queue.Queue()
ai_audio_queue = queue.Queue()

# --- Microphone capture ---
def capture_microphone():
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SIZE,
    ) as stream:
        while True:
            frames, _ = stream.read(CHUNK_SIZE)
            mic_audio_queue.put(frames.copy())

# --- AI audio playback ---
def playback_ai_audio():
    with sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SIZE,
    ) as stream:
        while True:
            if not ai_audio_queue.empty():
                audio_frame = ai_audio_queue.get()
                stream.write(audio_frame)

# --- WebSocket client ---
async def websocket_handler():
    try:
        async with websockets.connect(FASTAPI_WS_URL + session_id) as websocket:
            print("[Gradio Client] Connected to FastAPI server!")

            send_task = asyncio.create_task(send_mic_audio(websocket))
            receive_task = asyncio.create_task(receive_ai_audio(websocket))

            await asyncio.gather(send_task, receive_task)

    except Exception as e:
        print(f"[Gradio Client] WebSocket connection error: {e}")

async def send_mic_audio(websocket):
    while True:
        frame = await asyncio.to_thread(mic_audio_queue.get)
        await websocket.send(frame.tobytes())

async def receive_ai_audio(websocket):
    while True:
        audio_bytes = await websocket.recv()
        if audio_bytes:
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
            ai_audio_queue.put(audio_np)

# --- Background startup ---
def start_websocket_background():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_handler())

# --- Start everything automatically ---
def start_voice_chat():
    if not websocket_thread.is_alive():
        websocket_thread.start()
    return None  # <-- Important: no output!

# Threads for audio
mic_thread = threading.Thread(target=capture_microphone, daemon=True)
mic_thread.start()

playback_thread = threading.Thread(target=playback_ai_audio, daemon=True)
playback_thread.start()

websocket_thread = threading.Thread(target=start_websocket_background, daemon=True)

# --- Gradio App ---
with gr.Blocks() as app:
    with gr.Row():
        gr.Markdown("## 🎤 Listening... Speak anytime", elem_id="status-text")

    app.load(start_voice_chat)

app.launch()