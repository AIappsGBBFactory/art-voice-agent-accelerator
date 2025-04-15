import asyncio
import pyaudio
import numpy as np
import base64
import logging
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from src.realtime_client.client import RealtimeClient
from src.realtime_copy.tools import tools
from voiceagents.testagent.instructions import SYSTEM_PROMPT

CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
SPEAKER_MIN_BUFFER_MS = 60
MIC_VISUALIZATION = True
session_config_path = "voiceagents/testagent/session_config.yaml"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoiceAgent:
    def __init__(self, system_prompt: str, session_config_path: str = None) -> None:
        self.system_prompt = system_prompt
        self.session_config_path = session_config_path
        self.client = RealtimeClient(system_prompt=self.system_prompt, session_config_path=self.session_config_path)
        self.audio_interface = pyaudio.PyAudio()
        self.running = False
        self.mic_stream = None
        self.speaker_stream = None
        self.speaker_buffer = bytearray()
        self.ai_is_talking = False

    async def setup(self) -> None:
        self.client.clear_event_handlers()
        self.client.realtime.on("server.response.audio.delta", self.on_audio_delta)
        self.client.realtime.on("server.response.created", self.on_ai_start)
        self.client.realtime.on("server.response.done", self.on_ai_done)
        self.client.realtime.on("server.error", self.on_error)
        for tool_def, tool_handler in tools:
            await self.client.add_tool(tool_def, tool_handler)

    async def start(self) -> None:
        await self.setup()
        await self.client.connect()

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
            rate=RATE,
            output=True
        )

        logger.info("VoiceAgent: Microphone and Speaker started.")

        await asyncio.gather(
            self._mic_capture_loop(),
            self._speaker_playback_loop()
        )

    async def _mic_capture_loop(self) -> None:
        silence_counter = 0
        SILENCE_THRESHOLD = 150  # Volume level considered silence
        SILENCE_MAX_CHUNKS = 10  # ~10 x 10ms = 100ms silence = commit

        while self.running:
            try:
                data = self.mic_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                np_data = np.frombuffer(data, dtype=np.int16)

                if MIC_VISUALIZATION:
                    rms = np.sqrt(np.mean(np_data.astype(np.float32) ** 2))
                    level = int(rms / 300)
                    print(f"[Mic Level: {'|' * level:<20}]", end="\r")

                if rms < SILENCE_THRESHOLD:
                    silence_counter += 1
                else:
                    silence_counter = 0

                if self.ai_is_talking:
                    logger.info("🛑 User interruption detected, cancelling AI...")
                    await self.client.cancel_response()
                    self.ai_is_talking = False

                await self.client.append_input_audio(np_data)
                await asyncio.sleep(0.001)

                # Force commit if silence detected for a while
                if silence_counter > SILENCE_MAX_CHUNKS:
                    logger.info("🌙 Silence detected, forcing response...")
                    await self.client.create_response()
                    silence_counter = 0

            except Exception as e:
                logger.error(f"Mic capture error: {e}")
                break

    async def _speaker_playback_loop(self) -> None:
        samples_needed = int(RATE * 2 * (SPEAKER_MIN_BUFFER_MS / 1000))

        while self.running:
            try:
                if len(self.speaker_buffer) >= samples_needed:
                    chunk = self.speaker_buffer[:CHUNK_SIZE*2]
                    self.speaker_buffer = self.speaker_buffer[CHUNK_SIZE*2:]
                    self.speaker_stream.write(chunk)
                await asyncio.sleep(0.005)
            except Exception as e:
                logger.error(f"Speaker playback error: {e}")
                break

    async def stop(self) -> None:
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

    async def on_audio_delta(self, event: dict) -> None:
        try:
            delta = event.get("delta")
            if delta:
                decoded_audio = base64.b64decode(delta)
                self.speaker_buffer.extend(decoded_audio)
        except Exception as e:
            logger.error(f"Error handling audio delta: {e}")

    async def on_ai_start(self, event: dict) -> None:
        self.ai_is_talking = True
        logger.info("🤖 AI started speaking...")

    async def on_ai_done(self, event: dict) -> None:
        self.ai_is_talking = False
        logger.info("✅ AI finished speaking.")

    async def on_error(self, event: dict) -> None:
        logger.error(f"Realtime API error: {event}")

def main():
    agent = VoiceAgent(system_prompt=SYSTEM_PROMPT, session_config_path=session_config_path)

    async def runner():
        try:
            await agent.start()
        except Exception as e:
            logger.error(f"Agent runner crashed: {e}")
        finally:
            await agent.stop()

    asyncio.run(runner())

if __name__ == "__main__":
    main()
