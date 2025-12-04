"""
Configuration Package
====================

Centralized configuration for the real-time voice agent.

Structure (4 files):
  - settings.py   : All environment-loaded settings (flat, organized by domain)
  - constants.py  : Hard-coded values that never change
  - types.py      : Dataclass config objects for structured access  
  - __init__.py   : This file (exports everything)

Usage:
    # Direct settings access
    from config import POOL_SIZE_TTS, AZURE_OPENAI_ENDPOINT
    
    # Structured config object
    from config import AppConfig
    config = AppConfig()
    print(config.speech_pools.tts_pool_size)
    
    # Validation
    from config import validate_settings
    result = validate_settings()
"""

# =============================================================================
# SETTINGS - All environment-loaded configuration
# =============================================================================
from .settings import (
    # Azure Identity
    AZURE_CLIENT_ID,
    AZURE_TENANT_ID,
    BACKEND_AUTH_CLIENT_ID,
    ALLOWED_CLIENT_IDS,
    ENTRA_JWKS_URL,
    ENTRA_ISSUER,
    ENTRA_AUDIENCE,
    
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_CHAT_DEPLOYMENT_ID,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    AOAI_REQUEST_TIMEOUT,
    
    # Azure Speech
    AZURE_SPEECH_REGION,
    AZURE_SPEECH_ENDPOINT,
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_RESOURCE_ID,
    AZURE_VOICE_LIVE_ENDPOINT,
    AZURE_VOICE_API_KEY,
    AZURE_VOICE_LIVE_MODEL,
    
    # Azure Communication Services
    ACS_ENDPOINT,
    ACS_CONNECTION_STRING,
    ACS_SOURCE_PHONE_NUMBER,
    BASE_URL,
    ACS_STREAMING_MODE,
    ACS_JWKS_URL,
    ACS_ISSUER,
    ACS_AUDIENCE,
    
    # Azure Storage & Cosmos
    AZURE_STORAGE_CONTAINER_URL,
    AZURE_COSMOS_CONNECTION_STRING,
    AZURE_COSMOS_DATABASE_NAME,
    AZURE_COSMOS_COLLECTION_NAME,
    
    # Voice & TTS (per-agent voice is defined in agent.yaml)
    DEFAULT_TTS_VOICE,
    GREETING_VOICE_TTS,  # Deprecated alias for DEFAULT_TTS_VOICE
    DEFAULT_VOICE_STYLE,
    DEFAULT_VOICE_RATE,
    TTS_SAMPLE_RATE_UI,
    TTS_SAMPLE_RATE_ACS,
    TTS_CHUNK_SIZE,
    TTS_PROCESSING_TIMEOUT,
    
    # Speech Recognition
    VAD_SEMANTIC_SEGMENTATION,
    SILENCE_DURATION_MS,
    AUDIO_FORMAT,
    STT_PROCESSING_TIMEOUT,
    RECOGNIZED_LANGUAGE,
    
    # Connection Management
    MAX_WEBSOCKET_CONNECTIONS,
    CONNECTION_QUEUE_SIZE,
    ENABLE_CONNECTION_LIMITS,
    CONNECTION_WARNING_THRESHOLD,
    CONNECTION_CRITICAL_THRESHOLD,
    CONNECTION_TIMEOUT_SECONDS,
    HEARTBEAT_INTERVAL_SECONDS,
    
    # Session Management
    SESSION_TTL_SECONDS,
    SESSION_CLEANUP_INTERVAL,
    MAX_CONCURRENT_SESSIONS,
    ENABLE_SESSION_PERSISTENCE,
    SESSION_STATE_TTL,
    
    # Pool Settings
    POOL_SIZE_TTS,
    POOL_SIZE_STT,
    POOL_LOW_WATER_MARK,
    POOL_HIGH_WATER_MARK,
    POOL_ACQUIRE_TIMEOUT,
    
    # Feature Flags
    DTMF_VALIDATION_ENABLED,
    ENABLE_AUTH_VALIDATION,
    ENABLE_ACS_CALL_RECORDING,
    DEBUG_MODE,
    ENVIRONMENT,
    
    # Documentation
    ENABLE_DOCS,
    DOCS_URL,
    REDOC_URL,
    OPENAPI_URL,
    SECURE_DOCS_URL,
    
    # Monitoring
    ENABLE_PERFORMANCE_LOGGING,
    ENABLE_TRACING,
    METRICS_COLLECTION_INTERVAL,
    POOL_METRICS_INTERVAL,
    
    # Security
    ALLOWED_ORIGINS,
    ENTRA_EXEMPT_PATHS,
    
    # Validation
    validate_settings,
    validate_app_settings,  # Backward compat alias
)

# =============================================================================
# CONSTANTS - Hard-coded values
# =============================================================================
from .constants import (
    # API Paths
    ACS_CALL_OUTBOUND_PATH,
    ACS_CALL_INBOUND_PATH,
    ACS_CALL_CALLBACK_PATH,
    ACS_WEBSOCKET_PATH,
    
    # Audio
    RATE,
    CHANNELS,
    FORMAT,
    CHUNK,
    
    # Voice
    AVAILABLE_VOICES,
    TTS_END,
    STOP_WORDS,
    
    # Messages
    GREETING,
    
    # Languages
    SUPPORTED_LANGUAGES,
    DEFAULT_AUDIO_FORMAT,
)

# =============================================================================
# TYPES - Structured config objects
# =============================================================================
from .types import (
    AppConfig,
    SpeechPoolConfig,
    ConnectionConfig,
    SessionConfig,
    VoiceConfig,
    AIConfig,
    MonitoringConfig,
    SecurityConfig,
)

# =============================================================================
# CONVENIENCE
# =============================================================================

# Global config instance
app_config = AppConfig()
config = app_config  # Alias


def get_app_config() -> AppConfig:
    """Get the application configuration object."""
    return app_config


def reload_app_config() -> AppConfig:
    """Reload configuration (useful for testing)."""
    global app_config, config
    app_config = AppConfig()
    config = app_config
    return app_config


# =============================================================================
# EXPORTS
# =============================================================================
__all__ = [
    # Config objects
    "AppConfig",
    "SpeechPoolConfig",
    "ConnectionConfig",
    "SessionConfig",
    "VoiceConfig",
    "AIConfig",
    "MonitoringConfig",
    "SecurityConfig",
    "app_config",
    "config",
    "get_app_config",
    "reload_app_config",
    
    # Validation
    "validate_settings",
    "validate_app_settings",
    
    # Most-used settings (alphabetical)
    "ACS_CONNECTION_STRING",
    "ACS_ENDPOINT",
    "ACS_SOURCE_PHONE_NUMBER",
    "ALLOWED_ORIGINS",
    "DEFAULT_TTS_VOICE",
    "AOAI_REQUEST_TIMEOUT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_SPEECH_REGION",
    "BASE_URL",
    "DEBUG_MODE",
    "ENABLE_AUTH_VALIDATION",
    "ENABLE_DOCS",
    "ENVIRONMENT",
    "GREETING_VOICE_TTS",
    "MAX_WEBSOCKET_CONNECTIONS",
    "POOL_SIZE_TTS",
    "POOL_SIZE_STT",
    "SESSION_TTL_SECONDS",
]

