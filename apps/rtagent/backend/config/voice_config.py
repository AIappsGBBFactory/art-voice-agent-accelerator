"""
Voice and TTS Configuration (DEPRECATED)
========================================

This file is deprecated. Import from config or config.settings instead.

Note: Per-agent voice settings are now defined in each agent's agent.yaml.
      These settings provide fallback defaults.
"""

from .settings import (
    DEFAULT_TTS_VOICE,
    GREETING_VOICE_TTS,  # Deprecated alias
    DEFAULT_VOICE_STYLE,
    DEFAULT_VOICE_RATE,
    TTS_SAMPLE_RATE_UI,
    TTS_SAMPLE_RATE_ACS,
    TTS_CHUNK_SIZE,
    TTS_PROCESSING_TIMEOUT,
    VAD_SEMANTIC_SEGMENTATION,
    SILENCE_DURATION_MS,
    AUDIO_FORMAT,
    STT_PROCESSING_TIMEOUT,
    RECOGNIZED_LANGUAGE,
    AZURE_VOICE_LIVE_ENDPOINT,
    AZURE_VOICE_API_KEY,
    AZURE_VOICE_LIVE_MODEL,
)
