import os
from dotenv import load_dotenv
from typing import Any, Dict

# Load environment vars from .env at project root
load_dotenv()

# Azure Realtime transcription API
AZURE_KEY: str = os.getenv("AZURE_OPENAI_STT_TTS_KEY", "")
AZURE_ENDPOINT: str = os.getenv("AZURE_OPENAI_STT_TTS_ENDPOINT", "")

if not AZURE_KEY or not AZURE_ENDPOINT:
    raise RuntimeError("AZURE_OPENAI_STT_TTS_KEY / ENDPOINT must be set in env")

# Build WS URL
AZURE_WS_URL: str = (
    AZURE_ENDPOINT.replace("https://", "wss://").rstrip("/")
    + "/openai/realtime"
    + "?api-version=2025-04-01-preview&intent=transcription"
)

# Headers for the Azure WS
AZURE_HEADERS = [("api-key", AZURE_KEY)]

# Audio parameters (must match client)
RATE: int = 24000
CHANNELS: int = 1

# JSON messages to kick off the session
SESSION_CONFIG: Dict[str, Any] = {
    "type": "transcription_session.update",
    "session": {
        "input_audio_format": "pcm16",
        "input_audio_transcription": {
            "model": "gpt-4o-transcribe",
            "prompt": ("Respond in English. "),
        },
        "input_audio_noise_reduction": {"type": "near_field"},
        "turn_detection": {"type": "server_vad"},
    },
}

AUDIO_START: Dict[str, Any] = {
    "type": "audio_start",
    "data": {"encoding": "pcm", "sample_rate": RATE, "channels": CHANNELS},
}
