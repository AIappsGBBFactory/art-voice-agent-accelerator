"""
utils/settings.py
=================
Central place for every environment variable, constant path, and
used by the voice-agent service.
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import List
from dotenv import load_dotenv
from src.enums.stream_modes import StreamMode
# Load environment variables from .env file
load_dotenv(override=True)

# ------------------------------------------------------------------------------
# Azure OpenAI
# ------------------------------------------------------------------------------
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY: str = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_CHAT_DEPLOYMENT_ID: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID", "")

# ------------------------------------------------------------------------------
# Azure Identity / Authentication
# ------------------------------------------------------------------------------
AZURE_CLIENT_ID: str = os.getenv("AZURE_CLIENT_ID", "")
AZURE_TENANT_ID: str = os.getenv("AZURE_TENANT_ID", "")

# ------------------------------------------------------------------------------
# Azure Speech Services
# ------------------------------------------------------------------------------
AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "")
AZURE_SPEECH_ENDPOINT: str = os.getenv("AZURE_SPEECH_ENDPOINT") or os.environ.get("AZURE_OPENAI_STT_TTS_ENDPOINT", "")
AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY") or os.environ.get("AZURE_OPENAI_STT_TTS_KEY", "")
AZURE_SPEECH_RESOURCE_ID: str = os.getenv("AZURE_SPEECH_RESOURCE_ID", "")
# ------------------------------------------------------------------------------
# Azure Communication Services (ACS)
# ------------------------------------------------------------------------------
ACS_ENDPOINT: str = os.getenv("ACS_ENDPOINT", "")
ACS_CONNECTION_STRING: str = os.getenv("ACS_CONNECTION_STRING", "")
ACS_SOURCE_PHONE_NUMBER: str = os.getenv("ACS_SOURCE_PHONE_NUMBER", "")
BASE_URL: str = os.getenv("BASE_URL", "")

# Blob Container URL for recording storage
AZURE_STORAGE_CONTAINER_URL: str = os.getenv("AZURE_STORAGE_CONTAINER_URL", "")

# ACS_STREAMING_MODE: StreamMode = StreamMode.MEDIA
ACS_STREAMING_MODE: StreamMode = StreamMode(os.getenv("ACS_STREAMING_MODE", "media").lower())

# API route fragments (keep them in one place so routers can import)
ACS_CALL_PATH = "/api/call"
ACS_CALLBACK_PATH: str = "/call/callbacks"
ACS_WEBSOCKET_PATH: str = "/call/stream"

# Cosmos DB
AZURE_COSMOS_CONNECTION_STRING: str = os.getenv("AZURE_COSMOS_CONNECTION_STRING", "")
AZURE_COSMOS_DATABASE_NAME: str = os.getenv("AZURE_COSMOS_DATABASE_NAME", "")
AZURE_COSMOS_COLLECTION_NAME: str = os.getenv("AZURE_COSMOS_COLLECTION_NAME", "")

# ------------------------------------------------------------------------------
# SST behaviour
# ------------------------------------------------------------------------------
# Transcribe Audio Configuration
RATE: int = 16000  # Sample rate for audio processing
# Channels for audio processing
CHANNELS: int = 1  # Mono audio
FORMAT: int = 16  # PCM16 format for audio
# Chunk size for audio processing
CHUNK: int = 1024  # Size of audio chunks to process
# ------------------------------------------------------------------------------
# VAD (Voice Activity Detection) settings
VAD_THRESHOLD: float = 0.5  # Threshold for VAD to detect speech
# Prefix padding in milliseconds to avoid cutting off speech
PREFIX_PADDING_MS: int = 400  # Padding before speech starts
# Silence duration in milliseconds to consider the end of speech
SILENCE_DURATION_MS: int = 1300  # Duration of silence to end speech detection

# ------------------------------------------------------------------------------
# TTS behaviour
# ------------------------------------------------------------------------------
VOICE_TTS = "en-US-Ava:DragonHDLatestNeural"

# ------------------------------------------------------------------------------
STOP_WORDS: List[str] = ["goodbye", "exit", "see you later", "bye"]
# Character(s) that mark a chunk boundary for TTS streaming:
TTS_END: set[str] = { ";" }

# Allowed CORS origins for the FastAPI app:
ALLOWED_ORIGINS: list[str] = [
    "*"
    # "http://localhost",
    # "http://127.0.0.1",
    # "https://localhost",
    # "https://127.0.0.1",
    # "http://localhost:5173",
    # "http://127.0.0.1:5173",
    # "https://localhost:5173",
    # "https://127.0.0.1:5173",
]
