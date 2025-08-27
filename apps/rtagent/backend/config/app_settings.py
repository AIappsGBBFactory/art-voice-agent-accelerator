"""
Application Settings
===================

Core application-level configuration for the real-time voice agent.
Focused on app behavior, performance, and scalability settings.

Separated from infrastructure settings for better organization.
"""

import os
import yaml
from typing import List, Dict, Any
from .constants import (
    SUPPORTED_LANGUAGES,
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_VAD_SEMANTIC_SEGMENTATION,
    DEFAULT_SILENCE_DURATION_MS,
    DEFAULT_DTMF_VALIDATION_ENABLED,
    DEFAULT_ENABLE_AUTH_VALIDATION,
    ACS_CALL_CALLBACK_PATH,
    ACS_WEBSOCKET_PATH,
)

# ==============================================================================
# AGENT CONFIGURATIONS
# ==============================================================================

# Agent configuration file paths
AGENT_AUTH_CONFIG: str = os.getenv(
    "AGENT_AUTH_CONFIG",
    "apps/rtagent/backend/src/agents/agent_store/auth_agent.yaml"
)

AGENT_CLAIM_INTAKE_CONFIG: str = os.getenv(
    "AGENT_CLAIM_INTAKE_CONFIG", 
    "apps/rtagent/backend/src/agents/agent_store/claim_intake_agent.yaml"
)

AGENT_GENERAL_INFO_CONFIG: str = os.getenv(
    "AGENT_GENERAL_INFO_CONFIG",
    "apps/rtagent/backend/src/agents/agent_store/general_info_agent.yaml"
)

# ==============================================================================
# SPEECH SERVICE CONFIGURATION
# ==============================================================================

# Speech service pool sizes - Phase 1 optimized for 100-200 connections
POOL_SIZE_TTS = int(os.getenv("POOL_SIZE_TTS", "50"))
POOL_SIZE_STT = int(os.getenv("POOL_SIZE_STT", "50"))

# Pool monitoring and warnings
POOL_LOW_WATER_MARK = int(os.getenv("POOL_LOW_WATER_MARK", "10"))
POOL_HIGH_WATER_MARK = int(os.getenv("POOL_HIGH_WATER_MARK", "45"))
POOL_ACQUIRE_TIMEOUT = float(os.getenv("POOL_ACQUIRE_TIMEOUT", "5.0"))

# Speech processing timeouts
STT_PROCESSING_TIMEOUT = float(os.getenv("STT_PROCESSING_TIMEOUT", "10.0"))
TTS_PROCESSING_TIMEOUT = float(os.getenv("TTS_PROCESSING_TIMEOUT", "8.0"))

# Speech recognition settings
VAD_SEMANTIC_SEGMENTATION = os.getenv("VAD_SEMANTIC_SEGMENTATION", str(DEFAULT_VAD_SEMANTIC_SEGMENTATION).lower()).lower() == "true"
SILENCE_DURATION_MS = int(os.getenv("SILENCE_DURATION_MS", str(DEFAULT_SILENCE_DURATION_MS)))
AUDIO_FORMAT = os.getenv("AUDIO_FORMAT", DEFAULT_AUDIO_FORMAT)

# Recognized languages for multi-language support
RECOGNIZED_LANGUAGE = os.getenv("RECOGNIZED_LANGUAGE", ",".join(SUPPORTED_LANGUAGES)).split(",")

# ==============================================================================
# VOICE AND TTS SETTINGS
# ==============================================================================

# Voice configuration cache to avoid repeated file reads
_voice_cache = {}

def get_agent_voice(agent_config_path: str) -> str:
    """Extract voice from agent YAML configuration. Cached to avoid repeated file reads."""
    if agent_config_path in _voice_cache:
        return _voice_cache[agent_config_path]
    
    try:
        with open(agent_config_path, 'r', encoding='utf-8') as file:
            agent_config = yaml.safe_load(file)
            voice_config = agent_config.get("voice", {})
            if isinstance(voice_config, dict):
                voice_name = voice_config.get("voice_name") or voice_config.get("name")
                if voice_name:
                    _voice_cache[agent_config_path] = voice_name
                    return voice_name
            elif isinstance(voice_config, str):
                _voice_cache[agent_config_path] = voice_config
                return voice_config
                
        # If no valid voice configuration found, use default
        _voice_cache[agent_config_path] = "en-US-AvaMultilingualNeural"
        return "en-US-AvaMultilingualNeural"
        
    except Exception as e:
        # If can't load agent config, use default voice and cache it
        try:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to load voice from {agent_config_path}: {e}")
        except:
            pass
        
        _voice_cache[agent_config_path] = "en-US-AvaMultilingualNeural"
        return "en-US-AvaMultilingualNeural"

# Get voice from environment variable or auth agent config
GREETING_VOICE_TTS = os.getenv("GREETING_VOICE_TTS") or get_agent_voice(AGENT_AUTH_CONFIG)

# TTS settings
DEFAULT_VOICE_STYLE = os.getenv("DEFAULT_VOICE_STYLE", "neutral")
DEFAULT_VOICE_RATE = os.getenv("DEFAULT_VOICE_RATE", "0%")
TTS_SAMPLE_RATE_UI = int(os.getenv("TTS_SAMPLE_RATE_UI", "48000"))
TTS_SAMPLE_RATE_ACS = int(os.getenv("TTS_SAMPLE_RATE_ACS", "16000"))
TTS_CHUNK_SIZE = int(os.getenv("TTS_CHUNK_SIZE", "1024"))

# ==============================================================================
# WEBSOCKET CONNECTION MANAGEMENT
# ==============================================================================

# Connection limits - Phase 1 scaling
MAX_WEBSOCKET_CONNECTIONS = int(os.getenv("MAX_WEBSOCKET_CONNECTIONS", "200"))
CONNECTION_QUEUE_SIZE = int(os.getenv("CONNECTION_QUEUE_SIZE", "50"))
ENABLE_CONNECTION_LIMITS = os.getenv("ENABLE_CONNECTION_LIMITS", "true").lower() == "true"

# Connection monitoring thresholds
CONNECTION_WARNING_THRESHOLD = int(os.getenv("CONNECTION_WARNING_THRESHOLD", "150"))  # 75%
CONNECTION_CRITICAL_THRESHOLD = int(os.getenv("CONNECTION_CRITICAL_THRESHOLD", "180"))  # 90%

# Connection timeout settings
CONNECTION_TIMEOUT_SECONDS = int(os.getenv("CONNECTION_TIMEOUT_SECONDS", "300"))  # 5 minutes
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "30"))

# ==============================================================================
# SESSION MANAGEMENT
# ==============================================================================

# Session lifecycle settings
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))  # 30 minutes
SESSION_CLEANUP_INTERVAL = int(os.getenv("SESSION_CLEANUP_INTERVAL", "300"))  # 5 minutes
MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "1000"))

# Session state management
ENABLE_SESSION_PERSISTENCE = os.getenv("ENABLE_SESSION_PERSISTENCE", "true").lower() == "true"
SESSION_STATE_TTL = int(os.getenv("SESSION_STATE_TTL", "3600"))  # 1 hour

# ==============================================================================
# FEATURE FLAGS
# ==============================================================================

# Custom Validation Flow Feature Flags
DTMF_VALIDATION_ENABLED = os.getenv("DTMF_VALIDATION_ENABLED", str(DEFAULT_DTMF_VALIDATION_ENABLED).lower()).lower() in ("true", "1", "yes", "on")

# Authentication settings
ENABLE_AUTH_VALIDATION = os.getenv("ENABLE_AUTH_VALIDATION", str(DEFAULT_ENABLE_AUTH_VALIDATION).lower()).lower() in ("true", "1", "yes", "on")

# ==============================================================================
# AI AND AZURE OPENAI SETTINGS  
# ==============================================================================

# Azure OpenAI configuration
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "500"))
AOAI_REQUEST_TIMEOUT = float(os.getenv("AOAI_REQUEST_TIMEOUT", "30.0"))

# ==============================================================================
# DATA STORAGE SETTINGS
# ==============================================================================

# Azure Cosmos DB configuration
AZURE_COSMOS_CONNECTION_STRING = os.getenv("AZURE_COSMOS_CONNECTION_STRING", "")
AZURE_COSMOS_DATABASE_NAME = os.getenv("AZURE_COSMOS_DATABASE_NAME", "")
AZURE_COSMOS_COLLECTION_NAME = os.getenv("AZURE_COSMOS_COLLECTION_NAME", "")

# ==============================================================================
# CORS AND SECURITY SETTINGS
# ==============================================================================

# CORS configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",") if os.getenv("ALLOWED_ORIGINS") else ["*"]

# Entra ID exempt paths (paths that don't require authentication)
ENTRA_EXEMPT_PATHS = [
    ACS_CALL_CALLBACK_PATH,
    ACS_WEBSOCKET_PATH,
    "/health",
    "/readiness",
    "/docs", 
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/v1/health"
]

# ==============================================================================
# DOCUMENTATION AND ENVIRONMENT SETTINGS
# ==============================================================================

# Environment configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
DEBUG_MODE = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes", "on")

# Swagger/OpenAPI Documentation Configuration
_enable_docs_raw = os.getenv("ENABLE_DOCS", "auto").lower()

# Auto-detect docs enablement based on environment if not explicitly set
if _enable_docs_raw == "auto":
    ENABLE_DOCS = ENVIRONMENT in ("development", "dev", "testing", "test", "staging")
elif _enable_docs_raw in ("true", "1", "yes", "on"):
    ENABLE_DOCS = True
else:
    ENABLE_DOCS = False

# OpenAPI endpoints configuration
DOCS_URL = "/docs" if ENABLE_DOCS else None
REDOC_URL = "/redoc" if ENABLE_DOCS else None
OPENAPI_URL = "/openapi.json" if ENABLE_DOCS else None

# Alternative secure docs URL for production access (if needed)
SECURE_DOCS_URL = os.getenv("SECURE_DOCS_URL") if ENABLE_DOCS else None

# ==============================================================================
# MONITORING AND LOGGING SETTINGS
# ==============================================================================

# Performance monitoring
ENABLE_PERFORMANCE_LOGGING = os.getenv("ENABLE_PERFORMANCE_LOGGING", "true").lower() == "true"
ENABLE_TRACING = os.getenv("ENABLE_TRACING", "true").lower() == "true"

# Metrics collection intervals
METRICS_COLLECTION_INTERVAL = int(os.getenv("METRICS_COLLECTION_INTERVAL", "60"))  # seconds
POOL_METRICS_INTERVAL = int(os.getenv("POOL_METRICS_INTERVAL", "30"))  # seconds

# ==============================================================================
# VALIDATION FUNCTIONS
# ==============================================================================

def validate_app_settings() -> Dict[str, Any]:
    """
    Validate current application settings and return validation results.
    
    Returns:
        Dict containing validation status, issues, warnings, and settings count
    """
    issues = []
    warnings = []
    
    # Check critical pool settings
    if POOL_SIZE_TTS < 1:
        issues.append("POOL_SIZE_TTS must be at least 1")
    elif POOL_SIZE_TTS < 10:
        warnings.append(f"POOL_SIZE_TTS ({POOL_SIZE_TTS}) is quite low for production")
        
    if POOL_SIZE_STT < 1:
        issues.append("POOL_SIZE_STT must be at least 1")
    elif POOL_SIZE_STT < 10:
        warnings.append(f"POOL_SIZE_STT ({POOL_SIZE_STT}) is quite low for production")
    
    # Check connection settings
    if MAX_WEBSOCKET_CONNECTIONS < 1:
        issues.append("MAX_WEBSOCKET_CONNECTIONS must be at least 1")
    elif MAX_WEBSOCKET_CONNECTIONS > 1000:
        warnings.append(f"MAX_WEBSOCKET_CONNECTIONS ({MAX_WEBSOCKET_CONNECTIONS}) is very high")
    
    # Check timeout settings
    if CONNECTION_TIMEOUT_SECONDS < 60:
        warnings.append(f"CONNECTION_TIMEOUT_SECONDS ({CONNECTION_TIMEOUT_SECONDS}) is quite short")
    
    # Check voice settings
    if not GREETING_VOICE_TTS:
        issues.append("GREETING_VOICE_TTS is empty")
    
    # Count all settings
    settings_count = len([name for name in globals() if name.isupper() and not name.startswith('_')])
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "settings_count": settings_count
    }

if __name__ == "__main__":
    # Quick validation check
    result = validate_app_settings()
    print(f"App Settings Validation: {'✅ VALID' if result['valid'] else '❌ INVALID'}")
    
    if result['issues']:
        print("Issues:")
        for issue in result['issues']:
            print(f"  ❌ {issue}")
    
    if result['warnings']:
        print("Warnings:")
        for warning in result['warnings']:
            print(f"  ⚠️  {warning}")
    
    print(f"Total settings: {result['settings_count']}")
