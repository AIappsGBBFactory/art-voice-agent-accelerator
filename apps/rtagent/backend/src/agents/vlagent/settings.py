# settings.py
"""Production-ready configuration management for VoiceLive Multi-Agent System."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceLiveSettings(BaseSettings):
    """Application settings with environment variable loading."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Azure VoiceLive Configuration
    azure_voicelive_endpoint: str = Field(..., description="Azure VoiceLive endpoint URL")
    voicelive_model: str = Field(default="gpt-4o-realtime-preview", description="Model deployment name")
    azure_voicelive_api_key: Optional[str] = Field(default=None, description="API key for authentication")
    
    # Azure AD Authentication (alternative to API key)
    azure_client_id: Optional[str] = Field(default=None, description="Azure AD client ID")
    azure_tenant_id: Optional[str] = Field(default=None, description="Azure AD tenant ID")
    azure_client_secret: Optional[str] = Field(default=None, description="Azure AD client secret")
    
    # Application Configuration
    start_agent: str = Field(default="AuthAgent", description="Initial agent to start with")
    agents_dir: str = Field(default="agents", description="Directory containing agent YAML files")
    templates_dir: str = Field(default="templates", description="Directory containing prompt templates")
    
    # WebSocket Configuration
    ws_max_msg_size: int = Field(default=10 * 1024 * 1024, description="Max WebSocket message size")
    ws_heartbeat: int = Field(default=20, description="WebSocket heartbeat interval (seconds)")
    ws_timeout: int = Field(default=20, description="WebSocket timeout (seconds)")
    
    # Logging Configuration
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    log_format: str = Field(
        default="%(asctime)s %(levelname)s %(name)s: %(message)s",
        description="Log message format"
    )
    
    # Audio Configuration
    enable_audio: bool = Field(default=True, description="Enable audio capture/playback")
    
    @property
    def agents_path(self) -> Path:
        """Get absolute path to agents directory."""
        base = Path(__file__).parent
        agents = Path(self.agents_dir)
        return agents if agents.is_absolute() else base / agents
    
    @property
    def templates_path(self) -> Path:
        """Get absolute path to templates directory."""
        base = Path(__file__).parent
        templates = Path(self.templates_dir)
        return templates if templates.is_absolute() else base / templates
    
    @property
    def has_api_key_auth(self) -> bool:
        """Check if API key authentication is configured."""
        return bool(self.azure_voicelive_api_key)
    
    @property
    def has_azure_ad_auth(self) -> bool:
        """Check if Azure AD authentication is configured."""
        return bool(self.azure_client_id)
    
    def validate_auth(self) -> None:
        """Validate that at least one authentication method is configured."""
        if not (self.has_api_key_auth or self.has_azure_ad_auth):
            raise ValueError(
                "Authentication required: Set AZURE_VOICELIVE_API_KEY or "
                "Azure AD credentials (AZURE_CLIENT_ID)"
            )


# Global settings instance
_settings: Optional[VoiceLiveSettings] = None


def get_settings() -> VoiceLiveSettings:
    """Get or create settings instance (singleton pattern)."""
    global _settings
    if _settings is None:
        # Auto-discover .env file in project root
        env_path = Path(__file__).parent.parent.parent.parent / ".env"
        if env_path.exists():
            os.environ.setdefault("ENV_FILE", str(env_path))
        
        _settings = VoiceLiveSettings()
        _settings.validate_auth()
    
    return _settings


def reload_settings() -> VoiceLiveSettings:
    """Force reload of settings (useful for testing)."""
    global _settings
    _settings = None
    return get_settings()
