"""
settings.py
This module contains configuration constants and environment variable retrievals
for the backend of the browser_RTMedAgent application. It defines base URLs,
Azure Communication Services (ACS) connection details, API paths, and lists of
text-to-speech (TTS) sentence-ending punctuation and stop words for conversation
handling.
Constants:
    BASE_URL (str): The base URL for the application, defaulting to a local dev tunnel if not set.
    ACS_CONNECTION_STRING (str): The connection string for Azure Communication Services, retrieved from environment variables.
    ACS_SOURCE_PHONE_NUMBER (str): The source phone number for ACS, retrieved from environment variables.
    ACS_CALLBACK_PATH (str): The API path for ACS callback events.
    ACS_WEBSOCKET_PATH (str): The WebSocket path for real-time ACS communication.
    ACS_CALL_PATH (str): The API path for initiating calls.
    TTS_END (List[str]): List of punctuation marks and characters that denote the end of a TTS sentence.
    STOP_WORDS (List[str]): List of words or phrases that signal the end of a conversation.
"""
import os
from typing import List

# --- Constants ---
BASE_URL = os.getenv("BASE_URL", "https://<your local devtunnel>.use.devtunnels.ms")
ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
ACS_SOURCE_PHONE_NUMBER = os.getenv("ACS_SOURCE_PHONE_NUMBER")
ACS_CALLBACK_PATH = "/api/acs/callback"
ACS_WEBSOCKET_PATH = "/realtime-acs"
ACS_CALL_PATH = "/api/call"
TTS_END: List[str] = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]
STOP_WORDS: List[str] = ["goodbye", "exit", "see you later", "bye"]
