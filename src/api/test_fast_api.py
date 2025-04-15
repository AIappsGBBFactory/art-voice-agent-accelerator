# test_websocket_client.py

import asyncio
import websockets
import os
import time

# FastAPI WebSocket URL
WS_URL = "ws://localhost:8010/ws/audio-stream/testsession123"

async def simulate_audio_stream():
    async with websockets.connect(WS_URL) as websocket:
        print("[Client] Connected to server!")

        # Simulate sending random dummy audio chunks
        for i in range(10):
            fake_audio_chunk = os.urandom(2048)  # 2KB of fake random bytes (simulate audio frames)
            await websocket.send(fake_audio_chunk)
            print(f"[Client] Sent fake audio chunk {i+1}")
            await asyncio.sleep(0.1)  # wait 100ms between sends

        print("[Client] Finished sending audio chunks, keeping connection open for AI response...")

        # Now listen for AI-generated audio chunks (from GPT-4o)
        try:
            while True:
                incoming_audio = await websocket.recv()
                print(f"[Client] Received {len(incoming_audio)} bytes of AI audio")
        except websockets.ConnectionClosed:
            print("[Client] WebSocket closed by server.")

if __name__ == "__main__":
    asyncio.run(simulate_audio_stream())
