"""
utils/settings.py
=================
Central place for every environment variable, constant path, and
“magic number” used by the voice-agent service.  Import these symbols
instead of hard-coding strings elsewhere.
"""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ------------------------------------------------------------------------------
# Azure OpenAI
# ------------------------------------------------------------------------------
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY: str = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_CHAT_DEPLOYMENT_ID: str = os.getenv(
    "AZURE_OPENAI_CHAT_DEPLOYMENT_ID", ""
)

# ------------------------------------------------------------------------------
# Azure Communication Services (ACS)
# ------------------------------------------------------------------------------
ACS_CONNECTION_STRING: str = os.getenv("ACS_CONNECTION_STRING", "")
ACS_SOURCE_PHONE_NUMBER: str = os.getenv("ACS_SOURCE_PHONE_NUMBER", "")
BASE_URL: str = os.getenv("BASE_URL", "")

# API route fragments (keep them in one place so routers can import)
ACS_CALL_PATH = "/api/call"
ACS_CALLBACK_PATH: str = "/call/callbacks"
ACS_WEBSOCKET_PATH: str = "/call/stream"

# ------------------------------------------------------------------------------
# Voice-agent behaviour
# ------------------------------------------------------------------------------
STOP_WORDS: List[str] = ["goodbye", "exit", "see you later", "bye"]
# Character(s) that mark a chunk boundary for TTS streaming:
TTS_END: set[str] = {".", "!", "?", ";"}

# Allowed CORS origins for the FastAPI app:
ALLOWED_ORIGINS: list[str] = [
    "http://localhost",
    "http://127.0.0.1",
    "https://localhost",
    "https://127.0.0.1",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://localhost:5173",
    "https://127.0.0.1:5173",
]

# ------------------------------------------------------------------------------
# Optional local file paths (logs, cache, etc.)
# ------------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parent
LOG_DIR: Path = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Create a new log file with date and time in the filename
LOG_FILE: Path = LOG_DIR / f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
