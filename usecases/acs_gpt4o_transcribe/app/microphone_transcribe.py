"""
microphone_transcribe.py

Real-time audio transcription using Azure OpenAI and microphone input.

- Loads configuration from environment variables.
- Streams microphone audio to Azure OpenAI for transcription.
- Prints incremental and final transcripts to the console.

Usage:
    python microphone_transcribe.py

Environment Variables:
    AZURE_OPENAI_STT_TTS_KEY:      Azure OpenAI API key.
    AZURE_OPENAI_STT_TTS_ENDPOINT: Azure OpenAI endpoint URL.
"""

import os
import asyncio
import pyaudio
from dotenv import load_dotenv
from typing import Optional
from usecases.acs_gpt4o_transcribe.app.utils_transcribe import choose_audio_device
from usecases.acs_gpt4o_transcribe.transcribe_ws.translator import AudioTranscriber

# Audio configuration constants
RATE = 24000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024


def get_env_variable(name: str) -> str:
    """Get environment variable or raise RuntimeError if missing."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"❌ Required environment variable '{name}' is missing.")
    return value


async def main() -> None:
    """
    Main entry point for real-time transcription.
    Loads environment, configures audio, and starts transcription session.
    """
    load_dotenv()
    try:
        OPENAI_API_KEY = get_env_variable("AZURE_OPENAI_STT_TTS_KEY")
        AZURE_OPENAI_ENDPOINT = get_env_variable("AZURE_OPENAI_STT_TTS_ENDPOINT")
    except RuntimeError as e:
        print(e)
        return

    url = f"{AZURE_OPENAI_ENDPOINT.replace('https', 'wss')}/openai/realtime?api-version=2025-04-01-preview&intent=transcription"
    headers = {"api-key": OPENAI_API_KEY}
    device_index = choose_audio_device()

    transcriber = AudioTranscriber(
        url=url,
        headers=headers,
        rate=RATE,
        channels=CHANNELS,
        format_=FORMAT,
        chunk=CHUNK,
        device_index=device_index,
    )

    def print_delta(delta: str):
        """Prints incremental transcription results."""
        print(delta, end=" ", flush=True)

    def print_transcript(transcript: str):
        """Prints the final transcript."""
        print(f"\n✅ Transcript: {transcript}")

    print(">>> Starting real-time transcription session. Press Ctrl+C to stop.")
    try:
        await transcriber.transcribe(
            model="gpt-4o-transcribe",
            prompt="Respond in English. This is a medical environment.",
            noise_reduction="near_field",
            vad_type="server_vad",
            vad_config={
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 2000,
            },
            on_delta=print_delta,
            on_transcript=print_transcript,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n🛑 Interrupted by user. Exiting...")
    except Exception as ex:
        print(f"\n❌ Error: {ex}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.")
