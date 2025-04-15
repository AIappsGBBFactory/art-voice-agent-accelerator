import asyncio
import os
import threading
import queue
import pyaudio
import numpy as np
import base64
import logging
from scipy.signal import resample_poly
from src.realtime_client.client import RealtimeClient
from src.realtime_copy.tools import tools
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Audio Configuration
CHUNK_SIZE = 512
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
OUTPUT_RATE = 48000

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoiceAgent:
    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
        self.client = RealtimeClient(system_prompt=self.system_prompt)
        self.audio_interface = pyaudio.PyAudio()
        self.running = False
        self.mic_stream = None
        self.speaker_stream = None
        self.playback_queue = queue.Queue()
        self.loop = None

    async def setup(self):
        self.client.clear_event_handlers()

        # Event handlers
        self.client.realtime.on("server.response.audio.delta", self.on_audio_delta)
        self.client.realtime.on("server.error", self.on_error)

        for tool_def, tool_handler in tools:
            await self.client.add_tool(tool_def, tool_handler)

        await self.client.connect()

    async def start(self):
        await self.setup()

        self.running = True
        self.mic_stream = self.audio_interface.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )

        self.speaker_stream = self.audio_interface.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=OUTPUT_RATE,
            output=True
        )

        logger.info(f"AudioManager: Microphone and Speaker started. Speaker config: channels={self.speaker_stream._channels}, rate={self.speaker_stream._rate}")

        self.playback_thread = threading.Thread(target=self._playback_audio, daemon=True)
        self.playback_thread.start()

        try:
            while self.running:
                data = self.mic_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                np_data = np.frombuffer(data, dtype=np.int16)
                if np.linalg.norm(np_data) > 1000:
                    logger.info("🎙️ Captured audio from mic, sending to GPT...")
                    await self.client.append_input_audio(np_data)
                await asyncio.sleep(0.005)  # faster sampling
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            await self.stop()

    async def stop(self):
        if not self.running:
            return
        logger.info("Stopping VoiceAgent...")
        self.running = False

        try:
            if self.mic_stream:
                self.mic_stream.stop_stream()
                self.mic_stream.close()
            if self.speaker_stream:
                self.speaker_stream.stop_stream()
                self.speaker_stream.close()
            self.audio_interface.terminate()

            await self.client.create_response()
            await self.client.disconnect()
        except Exception as e:
            logger.error(f"Error during stop: {e}")

    def _playback_audio(self):
        """
        Continuously play audio from the playback queue.
        """
        while self.running:
            try:
                data = self.playback_queue.get(timeout=1)
                if data:
                    audio_np = np.frombuffer(data, dtype=np.int16)

                    # RESAMPLE from 16kHz to 44.1kHz (if needed)
                    # Instead of resampling 44100
                    resampled_audio = resample_poly(audio_np, up=OUTPUT_RATE, down=RATE).astype(np.int16)


                    self.speaker_stream.write(resampled_audio.tobytes())
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error during audio playback: {e}")

    async def on_audio_delta(self, event):
        try:
            delta = event.get("delta")
            if delta:
                decoded_audio = base64.b64decode(delta)
                logger.info(f"🔈 Received {len(decoded_audio)} bytes of AI audio response.")
                self.playback_queue.put(decoded_audio)
        except Exception as e:
            logger.error(f"Error handling audio delta: {e}")

    async def on_error(self, event):
        logger.error(f"Realtime API error: {event}")

def main():
    system_prompt = """You are a helpful AI assistant speaking to a user. Be friendly and concise."""
    agent = VoiceAgent(system_prompt=system_prompt)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def run():
        try:
            loop.run_until_complete(agent.start())
        except Exception as e:
            logger.error(f"Agent main loop error: {e}")
        finally:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()

    try:
        while True:
            cmd = input("Type 'exit' to stop the agent: ")
            if cmd.lower() == 'exit':
                break
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run_coroutine_threadsafe(agent.stop(), loop)
        t.join()

if __name__ == "__main__":
    main()
