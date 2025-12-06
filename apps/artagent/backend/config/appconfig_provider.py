"""
Azure App Configuration Provider
================================

Provides seamless integration with Azure App Configuration for centralized
configuration management. Falls back to environment variables when App Config
is not available (backwards compatible).

Uses the official azure-appconfiguration-provider package for simplified
configuration loading.

Usage:
    from config.appconfig_provider import get_config_value, get_feature_flag
    
    # Get a configuration value (falls back to env var)
    endpoint = get_config_value("azure/openai/endpoint", "AZURE_OPENAI_ENDPOINT")
    
    # Get a feature flag
    if get_feature_flag("warm-pool"):
        enable_warm_pool()

Architecture:
    1. On startup, uses azure-appconfiguration-provider's load() to fetch all config
    2. Syncs fetched values to environment variables for compatibility
    3. Falls back to environment variables if App Config unavailable
"""

import os
import sys
import logging
from typing import Any, Dict, Optional, List
import threading

logger = logging.getLogger(__name__)

# Startup logging to stderr (before logging is configured)
def _log(msg):
    print(msg, file=sys.stderr, flush=True)

# ==============================================================================
# CONFIGURATION
# ==============================================================================

APPCONFIG_ENDPOINT = os.getenv("AZURE_APPCONFIG_ENDPOINT", "")
APPCONFIG_LABEL = os.getenv("AZURE_APPCONFIG_LABEL", os.getenv("ENVIRONMENT", "dev"))
APPCONFIG_ENABLED = bool(APPCONFIG_ENDPOINT)

# Global configuration dictionary (loaded from App Config)
_config: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()


# ==============================================================================
# KEY MAPPING: App Config Keys -> Environment Variable Names
# ==============================================================================

# Maps Azure App Configuration keys to their equivalent environment variables
# This enables seamless fallback when App Config is unavailable
APPCONFIG_KEY_MAP: Dict[str, str] = {
    # Azure OpenAI
    "azure/openai/endpoint": "AZURE_OPENAI_ENDPOINT",
    "azure/openai/deployment-id": "AZURE_OPENAI_CHAT_DEPLOYMENT_ID",
    "azure/openai/api-version": "AZURE_OPENAI_API_VERSION",
    "azure/openai/default-temperature": "DEFAULT_TEMPERATURE",
    "azure/openai/default-max-tokens": "DEFAULT_MAX_TOKENS",
    "azure/openai/request-timeout": "AOAI_REQUEST_TIMEOUT",
    
    # Azure Speech
    "azure/speech/endpoint": "AZURE_SPEECH_ENDPOINT",
    "azure/speech/region": "AZURE_SPEECH_REGION",
    "azure/speech/resource-id": "AZURE_SPEECH_RESOURCE_ID",
    
    # Azure Communication Services
    "azure/acs/endpoint": "ACS_ENDPOINT",
    "azure/acs/immutable-id": "ACS_IMMUTABLE_ID",
    "azure/acs/source-phone-number": "ACS_SOURCE_PHONE_NUMBER",
    "azure/acs/connection-string": "ACS_CONNECTION_STRING",
    
    # Redis
    "azure/redis/hostname": "REDIS_HOST",
    "azure/redis/port": "REDIS_PORT",
    
    # Cosmos DB
    "azure/cosmos/database-name": "AZURE_COSMOS_DATABASE_NAME",
    "azure/cosmos/collection-name": "AZURE_COSMOS_COLLECTION_NAME",
    "azure/cosmos/connection-string": "AZURE_COSMOS_CONNECTION_STRING",
    
    # Storage
    "azure/storage/account-name": "AZURE_STORAGE_ACCOUNT_NAME",
    "azure/storage/container-url": "AZURE_STORAGE_CONTAINER_URL",
    
    # Voice Live (note: VoiceLiveSettings expects AZURE_VOICELIVE_* format)
    "azure/voicelive/endpoint": "AZURE_VOICELIVE_ENDPOINT",
    "azure/voicelive/model": "AZURE_VOICELIVE_MODEL",
    
    # Application Insights
    "azure/appinsights/connection-string": "APPLICATIONINSIGHTS_CONNECTION_STRING",
    
    # Pool Settings
    "app/pools/tts-size": "POOL_SIZE_TTS",
    "app/pools/stt-size": "POOL_SIZE_STT",
    "app/pools/aoai-size": "AOAI_POOL_SIZE",
    "app/pools/low-water-mark": "POOL_LOW_WATER_MARK",
    "app/pools/high-water-mark": "POOL_HIGH_WATER_MARK",
    "app/pools/acquire-timeout": "POOL_ACQUIRE_TIMEOUT",
    "app/pools/warm-tts-size": "WARM_POOL_TTS_SIZE",
    "app/pools/warm-stt-size": "WARM_POOL_STT_SIZE",
    "app/pools/warm-refresh-interval": "WARM_POOL_REFRESH_INTERVAL",
    "app/pools/warm-session-max-age": "WARM_POOL_SESSION_MAX_AGE",
    
    # Connection Settings
    "app/connections/max-websocket": "MAX_WEBSOCKET_CONNECTIONS",
    "app/connections/queue-size": "CONNECTION_QUEUE_SIZE",
    "app/connections/warning-threshold": "CONNECTION_WARNING_THRESHOLD",
    "app/connections/critical-threshold": "CONNECTION_CRITICAL_THRESHOLD",
    "app/connections/timeout-seconds": "CONNECTION_TIMEOUT_SECONDS",
    "app/connections/heartbeat-interval": "HEARTBEAT_INTERVAL_SECONDS",
    
    # Session Settings
    "app/session/ttl-seconds": "SESSION_TTL_SECONDS",
    "app/session/cleanup-interval": "SESSION_CLEANUP_INTERVAL",
    "app/session/state-ttl": "SESSION_STATE_TTL",
    "app/session/max-concurrent": "MAX_CONCURRENT_SESSIONS",
    
    # Voice & TTS Settings
    "app/voice/tts-sample-rate-ui": "TTS_SAMPLE_RATE_UI",
    "app/voice/tts-sample-rate-acs": "TTS_SAMPLE_RATE_ACS",
    "app/voice/tts-chunk-size": "TTS_CHUNK_SIZE",
    "app/voice/tts-processing-timeout": "TTS_PROCESSING_TIMEOUT",
    "app/voice/stt-processing-timeout": "STT_PROCESSING_TIMEOUT",
    "app/voice/silence-duration-ms": "SILENCE_DURATION_MS",
    "app/voice/recognized-languages": "RECOGNIZED_LANGUAGE",
    "app/voice/default-tts-voice": "DEFAULT_TTS_VOICE",
    
    # Scaling (informational)
    "app/scaling/min-replicas": "CONTAINER_MIN_REPLICAS",
    "app/scaling/max-replicas": "CONTAINER_MAX_REPLICAS",
    
    # Monitoring
    "app/monitoring/metrics-interval": "METRICS_COLLECTION_INTERVAL",
    "app/monitoring/pool-metrics-interval": "POOL_METRICS_INTERVAL",
    
    # Environment
    "app/environment": "ENVIRONMENT",
    
    # Application URLs (set by postprovision)
    "app/backend/base-url": "BASE_URL",
    "app/frontend/backend-url": "VITE_BACKEND_BASE_URL",
    "app/frontend/ws-url": "VITE_WS_BASE_URL",
}

# Feature flag mapping: App Config feature name -> Environment variable name
FEATURE_FLAG_MAP: Dict[str, str] = {
    "dtmf-validation": "DTMF_VALIDATION_ENABLED",
    "auth-validation": "ENABLE_AUTH_VALIDATION",
    "call-recording": "ENABLE_ACS_CALL_RECORDING",
    "warm-pool": "WARM_POOL_ENABLED",
    "session-persistence": "ENABLE_SESSION_PERSISTENCE",
    "performance-logging": "ENABLE_PERFORMANCE_LOGGING",
    "tracing": "ENABLE_TRACING",
    "connection-limits": "ENABLE_CONNECTION_LIMITS",
}


# ==============================================================================
# PROVIDER-BASED CONFIGURATION LOADING
# ==============================================================================

def _load_config_from_appconfig() -> Optional[Dict[str, Any]]:
    """
    Load all configuration from Azure App Configuration using the provider package.
    
    Returns:
        Dictionary of all configuration values, or None if loading fails
    """
    global _config
    
    if not APPCONFIG_ENABLED:
        _log("   App Configuration not enabled (AZURE_APPCONFIG_ENDPOINT not set)")
        return None
    
    try:
        from azure.appconfiguration.provider import load, SettingSelector
        from azure.identity import ManagedIdentityCredential, DefaultAzureCredential
        
        _log(f"   Connecting to: {APPCONFIG_ENDPOINT}")
        _log(f"   Using label: {APPCONFIG_LABEL}")
        
        # Use ManagedIdentityCredential if AZURE_CLIENT_ID is set (user-assigned MI)
        azure_client_id = os.getenv("AZURE_CLIENT_ID")
        if azure_client_id:
            _log(f"   Using ManagedIdentityCredential with client_id: {azure_client_id[:8]}...")
            credential = ManagedIdentityCredential(client_id=azure_client_id)
        else:
            _log("   Using DefaultAzureCredential")
            credential = DefaultAzureCredential()
        
        # Use SettingSelector to filter by label
        selects = [
            SettingSelector(key_filter="*", label_filter=APPCONFIG_LABEL),
        ]
        
        # Load configuration using the provider with retry
        import time
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(1, max_retries + 1):
            try:
                _log(f"   Calling load() (attempt {attempt}/{max_retries})...")
                config = load(
                    endpoint=APPCONFIG_ENDPOINT,
                    credential=credential,
                    selects=selects,
                    # Pass credential for Key Vault reference resolution
                    keyvault_credential=credential,
                )
                
                # Convert to dict for easier access
                config_dict = dict(config)
                _log(f"   ✅ Loaded {len(config_dict)} configuration keys")
                
                # Log all keys for debugging
                if config_dict:
                    _log(f"   All keys: {list(config_dict.keys())}")
                else:
                    _log("   ⚠️  No keys loaded from App Configuration!")
                
                # Log some sample keys (first 5)
                sample_keys = list(config_dict.keys())[:5]
                for key in sample_keys:
                    value = config_dict[key]
                    display_value = str(value)[:30] + "..." if len(str(value)) > 30 else str(value)
                    _log(f"      {key}: {display_value}")
                
                with _config_lock:
                    _config = config_dict
                
                return config_dict
                
            except Exception as retry_error:
                _log(f"   ⚠️  Attempt {attempt} failed: {retry_error}")
                if attempt < max_retries:
                    _log(f"   Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise
        
    except ImportError as e:
        _log(f"   ❌ azure-appconfiguration-provider not installed: {e}")
        return None
    except Exception as e:
        _log(f"   ❌ Failed to load from App Configuration: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None


def sync_appconfig_to_env(config_dict: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Sync App Configuration values to environment variables.
    
    Args:
        config_dict: Configuration dictionary (uses global if not provided)
        
    Returns:
        Dict of synced key-value pairs (env_var_name -> value)
    """
    if config_dict is None:
        with _config_lock:
            config_dict = _config
    
    if not config_dict:
        _log("   No configuration to sync")
        return {}
    
    synced: Dict[str, str] = {}
    skipped: List[str] = []
    not_found: List[str] = []
    
    # Log all available keys for diagnostics
    _log(f"   Available config keys ({len(config_dict)}):")
    for k in sorted(config_dict.keys()):
        v = config_dict[k]
        display_v = str(v)[:40] + "..." if len(str(v)) > 40 else str(v)
        _log(f"      {k}: {display_v}")
    
    for appconfig_key, env_var_name in APPCONFIG_KEY_MAP.items():
        # Check if key exists in loaded config
        # Try exact match first, then with colon separator (App Config sometimes uses colons)
        value = None
        matched_key = None
        
        if appconfig_key in config_dict:
            value = str(config_dict[appconfig_key])
            matched_key = appconfig_key
        else:
            # Try alternative key format (colons instead of slashes)
            alt_key = appconfig_key.replace("/", ":")
            if alt_key in config_dict:
                value = str(config_dict[alt_key])
                matched_key = alt_key
        
        if value is not None:
            # Don't override existing env vars
            if os.getenv(env_var_name):
                skipped.append(env_var_name)
                continue
            
            os.environ[env_var_name] = value
            synced[env_var_name] = value
        else:
            # Track keys we expected but didn't find
            if env_var_name in ["AZURE_OPENAI_ENDPOINT", "AZURE_SPEECH_ENDPOINT", "ACS_ENDPOINT"]:
                not_found.append(f"{appconfig_key} -> {env_var_name}")
    
    if synced:
        _log(f"   ✅ Synced {len(synced)} values to environment variables")
        # Log which critical vars were synced
        critical_synced = [k for k in synced if k in ["AZURE_OPENAI_ENDPOINT", "AZURE_SPEECH_ENDPOINT", "ACS_ENDPOINT"]]
        if critical_synced:
            _log(f"   ✅ Critical vars synced: {critical_synced}")
    if skipped:
        _log(f"   ⏭️  Skipped {len(skipped)} vars (already set in environment)")
    if not_found:
        _log(f"   ⚠️  Critical keys not found in App Config: {not_found}")
    
    return synced


def bootstrap_appconfig() -> bool:
    """
    Bootstrap App Configuration at application startup.
    
    This function should be called at the very beginning of main.py,
    BEFORE any other imports that depend on environment variables.
    
    It performs:
    1. Loads all config from App Configuration using the provider
    2. Syncs values to environment variables
    
    Returns:
        True if App Config loaded successfully, False otherwise
    """
    _log("🔧 Bootstrapping App Configuration...")
    _log(f"   AZURE_APPCONFIG_ENDPOINT: {APPCONFIG_ENDPOINT or '<not set>'}")
    _log(f"   AZURE_APPCONFIG_LABEL: {APPCONFIG_LABEL}")
    client_id = os.getenv('AZURE_CLIENT_ID', '')
    _log(f"   AZURE_CLIENT_ID: {client_id[:20] + '...' if client_id else '<not set>'}")
    
    if not APPCONFIG_ENABLED:
        _log("ℹ️  App Configuration not configured, using environment variables")
        return False
    
    # Load configuration
    config_dict = _load_config_from_appconfig()
    
    if not config_dict:
        _log("⚠️  Failed to load App Configuration, falling back to environment variables")
        return False
    
    # Sync to environment
    synced = sync_appconfig_to_env(config_dict)
    
    # Log critical vars status
    _log("📋 Critical environment variables after sync:")
    critical_vars = ["AZURE_OPENAI_ENDPOINT", "AZURE_SPEECH_ENDPOINT", "ACS_ENDPOINT"]
    for var in critical_vars:
        value = os.getenv(var, "")
        status = "✓" if value else "✗"
        display = value[:50] + "..." if len(value) > 50 else value
        _log(f"   {status} {var}: {display or '<not set>'}")
    
    _log("✅ App Configuration bootstrap complete")
    return True


# ==============================================================================
# PUBLIC API - Configuration Access
# ==============================================================================

def get_config_value(
    appconfig_key: str,
    env_var_name: Optional[str] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    """
    Get a configuration value with fallback:
    1. Loaded App Configuration (in memory)
    2. Environment variable
    3. Default value
    
    Args:
        appconfig_key: Key in App Configuration (e.g., "azure/openai/endpoint")
        env_var_name: Environment variable name for fallback (auto-mapped if None)
        default: Default value if not found anywhere
        
    Returns:
        Configuration value or default
    """
    # Determine env var name
    if env_var_name is None:
        env_var_name = APPCONFIG_KEY_MAP.get(appconfig_key)
    
    # Check loaded config first
    with _config_lock:
        if _config and appconfig_key in _config:
            return str(_config[appconfig_key])
    
    # Fall back to environment variable
    if env_var_name:
        value = os.getenv(env_var_name)
        if value is not None:
            return value
    
    return default


def get_feature_flag(
    name: str,
    env_var_name: Optional[str] = None,
    default: bool = False,
) -> bool:
    """
    Get a feature flag with fallback:
    1. Loaded App Configuration feature flags
    2. Environment variable (parsed as bool)
    3. Default value
    
    Args:
        name: Feature flag name (e.g., "warm-pool")
        env_var_name: Environment variable for fallback (auto-mapped if None)
        default: Default value if not found
        
    Returns:
        Feature flag state (True/False)
    """
    # Determine env var name
    if env_var_name is None:
        env_var_name = FEATURE_FLAG_MAP.get(name)
    
    # Feature flags in App Config use a special key prefix
    feature_key = f".appconfig.featureflag/{name}"
    
    # Check loaded config
    with _config_lock:
        if _config and feature_key in _config:
            flag_data = _config[feature_key]
            if isinstance(flag_data, dict):
                return flag_data.get("enabled", default)
            return bool(flag_data)
    
    # Fall back to environment variable
    if env_var_name:
        env_value = os.getenv(env_var_name, "").lower()
        if env_value in ("true", "1", "yes", "on"):
            return True
        elif env_value in ("false", "0", "no", "off"):
            return False
    
    return default


def get_config_int(
    appconfig_key: str,
    env_var_name: Optional[str] = None,
    default: int = 0,
) -> int:
    """Get a configuration value as integer."""
    value = get_config_value(appconfig_key, env_var_name)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid int value for {appconfig_key}: {value}")
    return default


def get_config_float(
    appconfig_key: str,
    env_var_name: Optional[str] = None,
    default: float = 0.0,
) -> float:
    """Get a configuration value as float."""
    value = get_config_value(appconfig_key, env_var_name)
    if value is not None:
        try:
            return float(value)
        except ValueError:
            logger.warning(f"Invalid float value for {appconfig_key}: {value}")
    return default


def get_provider_status() -> Dict[str, Any]:
    """
    Get the status of the App Configuration provider.
    
    Returns:
        Dict with status information
    """
    with _config_lock:
        config_loaded = _config is not None
        config_count = len(_config) if _config else 0
    
    return {
        "enabled": APPCONFIG_ENABLED,
        "endpoint": APPCONFIG_ENDPOINT if APPCONFIG_ENABLED else None,
        "label": APPCONFIG_LABEL,
        "loaded": config_loaded,
        "key_count": config_count,
    }


def refresh_cache() -> None:
    """Clear the configuration and force reload."""
    global _config
    with _config_lock:
        _config = None
    logger.info("App Configuration cleared")


# ==============================================================================
# CONVENIENCE ALIASES
# ==============================================================================

refresh_appconfig_cache = refresh_cache
get_appconfig_status = get_provider_status
initialize_appconfig = bootstrap_appconfig
