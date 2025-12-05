"""
Configuration Types
===================

Structured dataclass configuration objects for type-safe access.
These wrap the flat settings from settings.py into organized objects.

Usage:
    from config import AppConfig
    
    config = AppConfig()
    print(config.speech_pools.tts_pool_size)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List

from .settings import (
    # Speech pools
    POOL_SIZE_TTS,
    POOL_SIZE_STT,
    POOL_LOW_WATER_MARK,
    POOL_HIGH_WATER_MARK,
    POOL_ACQUIRE_TIMEOUT,
    STT_PROCESSING_TIMEOUT,
    TTS_PROCESSING_TIMEOUT,
    # Warm pool
    WARM_POOL_ENABLED,
    WARM_POOL_TTS_SIZE,
    WARM_POOL_STT_SIZE,
    WARM_POOL_BACKGROUND_REFRESH,
    WARM_POOL_REFRESH_INTERVAL,
    WARM_POOL_SESSION_MAX_AGE,
    # Connections
    MAX_WEBSOCKET_CONNECTIONS,
    CONNECTION_QUEUE_SIZE,
    ENABLE_CONNECTION_LIMITS,
    CONNECTION_WARNING_THRESHOLD,
    CONNECTION_CRITICAL_THRESHOLD,
    CONNECTION_TIMEOUT_SECONDS,
    # Sessions
    SESSION_TTL_SECONDS,
    SESSION_CLEANUP_INTERVAL,
    MAX_CONCURRENT_SESSIONS,
    ENABLE_SESSION_PERSISTENCE,
    SESSION_STATE_TTL,
    # Voice
    GREETING_VOICE_TTS,
    DEFAULT_VOICE_STYLE,
    DEFAULT_VOICE_RATE,
    TTS_SAMPLE_RATE_UI,
    TTS_SAMPLE_RATE_ACS,
    TTS_CHUNK_SIZE,
    # AI
    AOAI_REQUEST_TIMEOUT,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    # Monitoring
    METRICS_COLLECTION_INTERVAL,
    POOL_METRICS_INTERVAL,
    ENABLE_PERFORMANCE_LOGGING,
    ENABLE_TRACING,
    # Security
    ENABLE_AUTH_VALIDATION,
    DTMF_VALIDATION_ENABLED,
    ALLOWED_ORIGINS,
    ENTRA_EXEMPT_PATHS,
)


@dataclass
class SpeechPoolConfig:
    """Speech service pool configuration."""
    tts_pool_size: int = POOL_SIZE_TTS
    stt_pool_size: int = POOL_SIZE_STT
    low_water_mark: int = POOL_LOW_WATER_MARK
    high_water_mark: int = POOL_HIGH_WATER_MARK
    acquire_timeout: float = POOL_ACQUIRE_TIMEOUT
    stt_timeout: float = STT_PROCESSING_TIMEOUT
    tts_timeout: float = TTS_PROCESSING_TIMEOUT
    # Warm pool settings
    warm_pool_enabled: bool = WARM_POOL_ENABLED
    warm_pool_tts_size: int = WARM_POOL_TTS_SIZE
    warm_pool_stt_size: int = WARM_POOL_STT_SIZE
    warm_pool_background_refresh: bool = WARM_POOL_BACKGROUND_REFRESH
    warm_pool_refresh_interval: float = WARM_POOL_REFRESH_INTERVAL
    warm_pool_session_max_age: float = WARM_POOL_SESSION_MAX_AGE

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class ConnectionConfig:
    """WebSocket connection management configuration."""
    max_connections: int = MAX_WEBSOCKET_CONNECTIONS
    queue_size: int = CONNECTION_QUEUE_SIZE
    enable_limits: bool = ENABLE_CONNECTION_LIMITS
    warning_threshold: int = CONNECTION_WARNING_THRESHOLD
    critical_threshold: int = CONNECTION_CRITICAL_THRESHOLD
    timeout_seconds: float = CONNECTION_TIMEOUT_SECONDS

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class SessionConfig:
    """Session management configuration."""
    ttl_seconds: int = SESSION_TTL_SECONDS
    cleanup_interval: int = SESSION_CLEANUP_INTERVAL
    max_concurrent_sessions: int = MAX_CONCURRENT_SESSIONS
    enable_persistence: bool = ENABLE_SESSION_PERSISTENCE
    state_ttl: int = SESSION_STATE_TTL

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class VoiceConfig:
    """Voice and TTS configuration."""
    default_voice: str = GREETING_VOICE_TTS
    default_style: str = DEFAULT_VOICE_STYLE
    default_rate: str = DEFAULT_VOICE_RATE
    sample_rate_ui: int = TTS_SAMPLE_RATE_UI
    sample_rate_acs: int = TTS_SAMPLE_RATE_ACS
    chunk_size: int = TTS_CHUNK_SIZE
    processing_timeout: float = TTS_PROCESSING_TIMEOUT

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class AIConfig:
    """AI/LLM processing configuration."""
    request_timeout: float = AOAI_REQUEST_TIMEOUT
    default_temperature: float = DEFAULT_TEMPERATURE
    default_max_tokens: int = DEFAULT_MAX_TOKENS

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class MonitoringConfig:
    """Monitoring and observability configuration."""
    metrics_interval: int = METRICS_COLLECTION_INTERVAL
    pool_metrics_interval: int = POOL_METRICS_INTERVAL
    enable_performance_logging: bool = ENABLE_PERFORMANCE_LOGGING
    enable_tracing: bool = ENABLE_TRACING

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class SecurityConfig:
    """Security and authentication configuration."""
    enable_auth_validation: bool = ENABLE_AUTH_VALIDATION
    enable_dtmf_validation: bool = DTMF_VALIDATION_ENABLED
    allowed_origins: List[str] = field(default_factory=lambda: list(ALLOWED_ORIGINS))
    exempt_paths: List[str] = field(default_factory=lambda: list(ENTRA_EXEMPT_PATHS))

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class AppConfig:
    """
    Complete application configuration.
    
    Provides structured access to all configuration sections with validation.
    """
    speech_pools: SpeechPoolConfig = field(default_factory=SpeechPoolConfig)
    connections: ConnectionConfig = field(default_factory=ConnectionConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {
            "speech_pools": self.speech_pools.to_dict(),
            "connections": self.connections.to_dict(),
            "sessions": self.sessions.to_dict(),
            "voice": self.voice.to_dict(),
            "ai": self.ai.to_dict(),
            "monitoring": self.monitoring.to_dict(),
            "security": self.security.to_dict(),
        }

    def validate(self) -> Dict[str, Any]:
        """Validate configuration and return results."""
        issues = []
        warnings = []

        # Speech pools
        if self.speech_pools.tts_pool_size < 1:
            issues.append("TTS pool size must be at least 1")
        elif self.speech_pools.tts_pool_size < 10:
            warnings.append(f"TTS pool size ({self.speech_pools.tts_pool_size}) is low")

        if self.speech_pools.stt_pool_size < 1:
            issues.append("STT pool size must be at least 1")
        elif self.speech_pools.stt_pool_size < 10:
            warnings.append(f"STT pool size ({self.speech_pools.stt_pool_size}) is low")

        # Connections
        if self.connections.max_connections < 1:
            issues.append("Max connections must be at least 1")
        elif self.connections.max_connections > 1000:
            warnings.append(f"Max connections ({self.connections.max_connections}) is very high")

        # Capacity check
        total_pool = self.speech_pools.tts_pool_size + self.speech_pools.stt_pool_size
        if self.connections.max_connections > total_pool:
            warnings.append(
                f"Connection limit ({self.connections.max_connections}) exceeds pool capacity ({total_pool})"
            )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "config_summary": {
                "phase": "Phase 1" if self.connections.max_connections <= 200 else "Phase 2+",
                "tts_pool": self.speech_pools.tts_pool_size,
                "stt_pool": self.speech_pools.stt_pool_size,
                "max_connections": self.connections.max_connections,
            },
        }

    def get_capacity_info(self) -> Dict[str, Any]:
        """Get capacity planning information."""
        effective = min(self.speech_pools.tts_pool_size, self.speech_pools.stt_pool_size)
        return {
            "effective_capacity": effective,
            "tts_capacity": self.speech_pools.tts_pool_size,
            "stt_capacity": self.speech_pools.stt_pool_size,
            "max_connections": self.connections.max_connections,
            "bottleneck": "TTS" if self.speech_pools.tts_pool_size < self.speech_pools.stt_pool_size else "STT",
        }
