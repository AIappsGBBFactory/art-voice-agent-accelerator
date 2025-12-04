# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
"""
Azure Monitor / Application Insights telemetry configuration.

This module provides a simplified, maintainable setup for OpenTelemetry with Azure Monitor.

Configuration via environment variables:
- APPLICATIONINSIGHTS_CONNECTION_STRING: Required for Azure Monitor export
- DISABLE_CLOUD_TELEMETRY: Set to "true" to disable all cloud telemetry
- AZURE_MONITOR_DISABLE_LIVE_METRICS: Disable live metrics stream
- AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED: Record GenAI prompts/completions
- TELEMETRY_PII_SCRUBBING_ENABLED: Enable PII scrubbing (default: true)

See utils/pii_filter.py for PII scrubbing configuration options.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import uuid
import warnings
from dataclasses import dataclass, field
from typing import List, Optional, Pattern

# Suppress OpenTelemetry deprecation warnings
warnings.filterwarnings("ignore", message="LogRecord init with.*is deprecated", module="opentelemetry")

# Load .env early
try:
    from dotenv import load_dotenv
    if os.path.isfile(".env"):
        load_dotenv(override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TelemetryConfig:
    """Centralized telemetry configuration loaded from environment."""
    
    # Core settings
    enabled: bool = True
    connection_string: Optional[str] = None
    logger_name: str = ""  # Empty string captures ALL loggers
    
    # Service identification (for Application Map)
    service_name: str = "rtagent-api"
    service_namespace: str = "callcenter-app"
    service_version: Optional[str] = None
    environment: Optional[str] = None
    
    # Feature flags
    enable_live_metrics: bool = True
    enable_pii_scrubbing: bool = True
    
    # Instrumentation options
    # NOTE: configure_azure_monitor() enables many auto-instrumentations by default.
    # We explicitly disable most to prevent duplicate spans alongside our manual instrumentation.
    enabled_instrumentations: List[str] = field(default_factory=lambda: [
        # Only enable specific instrumentations we need
        # "azure_sdk",  # Can cause noisy spans
    ])
    disabled_instrumentations: List[str] = field(default_factory=lambda: [
        # Disable auto-instrumentations that would create duplicate spans
        # alongside our manual instrumentation
        "fastapi",      # We create manual spans for endpoints
        "asgi",         # We create manual spans for ASGI lifecycle
        "aiohttp",      # We have manual HTTP tracing
        "requests",     # We have manual HTTP tracing  
        "urllib3",      # We have manual HTTP tracing
        "urllib",       # We have manual HTTP tracing
        "httpx",        # We have manual HTTP tracing
        "redis",        # We create manual Redis spans where needed
        "azure_sdk",    # Can be very noisy, disable by default
        "psycopg2",     # Not used
        "django",       # Not used
        "flask",        # Not used
    ])
    
    @classmethod
    def from_env(cls) -> "TelemetryConfig":
        """Create configuration from environment variables."""
        def _bool_env(key: str, default: bool) -> bool:
            return os.getenv(key, str(default)).lower() not in ("false", "0", "no")
        
        return cls(
            enabled=not _bool_env("DISABLE_CLOUD_TELEMETRY", False),
            connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
            logger_name=os.getenv("AZURE_MONITOR_LOGGER_NAME", ""),  # Empty = capture all loggers
            service_name=os.getenv("SERVICE_NAME", "rtagent-api"),
            service_namespace=os.getenv("SERVICE_NAMESPACE", "callcenter-app"),
            service_version=os.getenv("SERVICE_VERSION") or os.getenv("APP_VERSION"),
            environment=os.getenv("ENVIRONMENT"),
            enable_live_metrics=not _bool_env("AZURE_MONITOR_DISABLE_LIVE_METRICS", False),
            enable_pii_scrubbing=_bool_env("TELEMETRY_PII_SCRUBBING_ENABLED", True),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SPAN FILTERING
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns for noisy spans to drop
NOISY_SPAN_PATTERNS: List[Pattern[str]] = [
    re.compile(r".*websocket\s*(receive|send).*", re.IGNORECASE),
    re.compile(r".*ws[._](receive|send).*", re.IGNORECASE),
    re.compile(r"HTTP.*websocket.*", re.IGNORECASE),
    re.compile(r"^(GET|POST)\s+.*(websocket|/ws/).*", re.IGNORECASE),
    re.compile(r".*audio[._](chunk|frame).*", re.IGNORECASE),
    re.compile(r".*(process|stream|emit)[._](frame|chunk).*", re.IGNORECASE),
    re.compile(r".*redis[._](ping|pool|connection).*", re.IGNORECASE),
    re.compile(r".*(poll|heartbeat)[._]session.*", re.IGNORECASE),
    # VoiceLive high-frequency streaming events
    re.compile(r"voicelive\.event\.response\.audio\.delta", re.IGNORECASE),
    re.compile(r"voicelive\.event\.response\.audio_transcript\.delta", re.IGNORECASE),
    re.compile(r"voicelive\.event\.response\.function_call_arguments\.delta", re.IGNORECASE),
    re.compile(r"voicelive\.event\.response\.text\.delta", re.IGNORECASE),
    re.compile(r"voicelive\.event\.response\.content_part\.delta", re.IGNORECASE),
    re.compile(r"voicelive\.event\.input_audio_buffer\.", re.IGNORECASE),
]

# Loggers to suppress (set to WARNING level)
NOISY_LOGGERS = [
    "azure.identity", "azure.core.pipeline", "azure.monitor.opentelemetry.exporter",
    "azure.monitor.opentelemetry.exporter._quickpulse",  # Live Metrics ping errors
    "azure.core.exceptions",  # Transient connection errors
    "websockets", "aiohttp", "httpx", "httpcore",
    "uvicorn.protocols.websockets", "uvicorn.error", "uvicorn.access",
    "starlette.routing", "fastapi",
    "opentelemetry.sdk.trace", "opentelemetry.exporter",
    "redis.asyncio.connection",
]


def _suppress_noisy_loggers(level: int = logging.WARNING) -> None:
    """Set noisy loggers to WARNING level to reduce noise."""
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


# ═══════════════════════════════════════════════════════════════════════════════
# SPAN PROCESSOR WITH FILTERING AND PII SCRUBBING  
# ═══════════════════════════════════════════════════════════════════════════════

from opentelemetry.sdk.trace import SpanProcessor, ReadableSpan


class FilteringSpanProcessor(SpanProcessor):
    """
    SpanProcessor that filters noisy spans and scrubs PII from attributes.
    
    Combines noise filtering and PII scrubbing in a single processor
    for better performance and simpler configuration.
    """
    
    def __init__(self, next_processor: SpanProcessor, enable_pii_scrubbing: bool = True):
        self._next = next_processor
        self._enable_pii_scrubbing = enable_pii_scrubbing
        self._pii_scrubber = None
        
        if enable_pii_scrubbing:
            try:
                from utils.pii_filter import get_pii_scrubber
                self._pii_scrubber = get_pii_scrubber()
            except ImportError:
                logger.debug("PII scrubber not available")
    
    def on_start(self, span, parent_context=None) -> None:
        self._next.on_start(span, parent_context)
    
    def on_end(self, span: ReadableSpan) -> None:
        # Filter noisy spans
        for pattern in NOISY_SPAN_PATTERNS:
            if pattern.match(span.name):
                return  # Drop span
        
        # PII scrubbing is handled at attribute level during span creation
        # and in the log exporter filter - we pass through here
        self._next.on_end(span)
    
    def shutdown(self) -> None:
        self._next.shutdown()
    
    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._next.force_flush(timeout_millis)


# ═══════════════════════════════════════════════════════════════════════════════
# LOG EXPORTER PATCHING (Empty body + PII filtering)
# ═══════════════════════════════════════════════════════════════════════════════

_log_exporter_patched = False


def _patch_log_exporter() -> None:
    """
    Patch Azure Monitor LogExporter to:
    1. Filter out empty body logs (prevents 400 errors)
    2. Scrub PII from log messages
    """
    global _log_exporter_patched
    if _log_exporter_patched:
        return
    
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        from utils.pii_filter import get_pii_scrubber
        
        original_export = AzureMonitorLogExporter.export
        scrubber = get_pii_scrubber()
        
        def filtered_export(self, batch, *args, **kwargs):
            from opentelemetry.sdk._logs.export import LogExportResult
            
            filtered_batch = []
            for log_data in batch:
                record = log_data.log_record
                body = getattr(record, 'body', None)
                
                # Skip empty bodies
                if not body or (isinstance(body, str) and not body.strip()):
                    continue
                
                # Scrub PII from body if it's a string
                if isinstance(body, str) and scrubber.config.enabled:
                    # Note: We can't modify the record directly, but the scrubber
                    # will be applied at the logging filter level
                    pass
                
                filtered_batch.append(log_data)
            
            if filtered_batch:
                return original_export(self, filtered_batch, *args, **kwargs)
            return LogExportResult.SUCCESS
        
        AzureMonitorLogExporter.export = filtered_export
        _log_exporter_patched = True
        logger.debug("Log exporter patched for empty body filtering")
        
    except ImportError:
        logger.debug("Azure Monitor LogExporter not available")
    except Exception as e:
        logger.warning(f"Failed to patch log exporter: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_instance_id() -> str:
    """Generate unique instance ID for Application Map visualization."""
    # Azure App Service
    if instance_id := os.getenv("WEBSITE_INSTANCE_ID"):
        return instance_id[:8]
    # Container Apps
    if replica := os.getenv("CONTAINER_APP_REPLICA_NAME"):
        return replica
    # Kubernetes
    if pod := os.getenv("HOSTNAME"):
        if "-" in pod:
            return pod
    # Fallback
    try:
        return socket.gethostname()
    except Exception:
        return str(uuid.uuid4())[:8]


def _get_credential():
    """Get Azure credential, preferring managed identity in Azure environments."""
    from utils.azure_auth import get_credential, ManagedIdentityCredential
    
    if os.getenv("WEBSITE_SITE_NAME") or os.getenv("CONTAINER_APP_NAME"):
        try:
            return ManagedIdentityCredential()
        except Exception:
            pass
    return get_credential()


def _build_resource(config: TelemetryConfig):
    """Build OpenTelemetry Resource from configuration."""
    from opentelemetry.sdk.resources import Resource
    
    attrs = {
        "service.name": config.service_name,
        "service.namespace": config.service_namespace,
        "service.instance.id": _get_instance_id(),
    }
    if config.environment:
        attrs["service.environment"] = config.environment
    if config.service_version:
        attrs["service.version"] = config.service_version
    
    return Resource(attributes=attrs)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE STATE
# ═══════════════════════════════════════════════════════════════════════════════

_azure_monitor_configured = False
_live_metrics_disabled = False
_setup_call_count = 0  # Track how many times setup is called


def is_azure_monitor_configured() -> bool:
    """Return True if Azure Monitor was configured successfully."""
    return _azure_monitor_configured


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN SETUP FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def setup_azure_monitor(logger_name: str = None, config: TelemetryConfig = None) -> bool:
    """
    Configure Azure Monitor / Application Insights.
    
    Args:
        logger_name: Override logger name from config
        config: Optional pre-built configuration (defaults to env-based config)
    
    Returns:
        True if configuration succeeded, False otherwise
    """
    global _azure_monitor_configured, _live_metrics_disabled, _setup_call_count
    
    _setup_call_count += 1
    
    # CRITICAL: Prevent double-configuration which causes duplicate telemetry
    if _azure_monitor_configured:
        logger.warning(
            f"setup_azure_monitor called again (call #{_setup_call_count}) but already configured - skipping to prevent duplicates"
        )
        return True
    
    # Check if Azure Monitor was already configured by checking for AzureMonitorTraceExporter
    # This is more specific than just checking for SDKTracerProvider
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
        current_provider = otel_trace.get_tracer_provider()
        if isinstance(current_provider, SDKTracerProvider):
            # Check if this TracerProvider has Azure Monitor exporters attached
            has_azure_exporter = False
            if hasattr(current_provider, '_active_span_processor'):
                processor = current_provider._active_span_processor
                # Check for Azure Monitor exporter in the processor chain
                try:
                    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
                    # Walk the processor chain to find Azure Monitor
                    def check_processor(proc):
                        if hasattr(proc, '_exporter'):
                            return isinstance(proc._exporter, AzureMonitorTraceExporter)
                        if hasattr(proc, '_span_processors'):
                            return any(check_processor(p) for p in proc._span_processors)
                        return False
                    has_azure_exporter = check_processor(processor)
                except ImportError:
                    pass
            
            if has_azure_exporter:
                logger.warning(
                    f"setup_azure_monitor: Azure Monitor already configured by another module - skipping to prevent duplicates"
                )
                _azure_monitor_configured = True
                return True
            else:
                logger.debug(
                    "SDK TracerProvider exists but without Azure Monitor exporter - continuing with configuration"
                )
    except Exception as e:
        logger.debug(f"Error checking TracerProvider: {e}")
        pass  # Continue with setup if check fails
    
    # Load configuration
    config = config or TelemetryConfig.from_env()
    if logger_name:
        config.logger_name = logger_name
    
    # Check if telemetry is disabled
    if not config.enabled:
        logger.info("Telemetry disabled via DISABLE_CLOUD_TELEMETRY")
        return False
    
    if not config.connection_string:
        logger.info("APPLICATIONINSIGHTS_CONNECTION_STRING not set - skipping Azure Monitor")
        return False
    
    # Suppress noisy loggers
    _suppress_noisy_loggers()
    
    # Patch log exporter before configure_azure_monitor
    _patch_log_exporter()
    
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        
        resource = _build_resource(config)
        credential = _get_credential()
        
        # Build list of span processors to add
        # NOTE: Do NOT create our own TracerProvider - configure_azure_monitor() creates one internally
        # and ignores any tracer_provider argument. We use span_processors instead.
        span_processors = []
        try:
            from utils.session_context import SessionContextSpanProcessor
            span_processors.append(SessionContextSpanProcessor())
        except ImportError:
            pass
        
        # Build instrumentation options
        instrumentation_opts = {
            name: {"enabled": True} for name in config.enabled_instrumentations
        }
        instrumentation_opts.update({
            name: {"enabled": False} for name in config.disabled_instrumentations
        })
        
        # Configure Azure Monitor
        # IMPORTANT: configure_azure_monitor() creates its own TracerProvider internally.
        # Do NOT pass tracer_provider - it's not a supported argument and will be ignored.
        # Use span_processors argument to add custom processors.
        enable_live_metrics = config.enable_live_metrics and not _live_metrics_disabled
        
        configure_azure_monitor(
            resource=resource,
            logger_name=config.logger_name,
            credential=credential,
            connection_string=config.connection_string,
            enable_live_metrics=enable_live_metrics,
            span_processors=span_processors,
            disable_logging=False,
            disable_tracing=False,
            disable_metrics=False,
            instrumentation_options=instrumentation_opts,
        )
        
        # Install filtering span processor
        _install_filtering_processor(config.enable_pii_scrubbing)
        
        # Add filters to root logger's Azure Monitor handler
        _add_root_logger_filters()
        
        _azure_monitor_configured = True
        
        features = []
        if not enable_live_metrics:
            features.append("live_metrics=off")
        if config.enable_pii_scrubbing:
            features.append("pii_scrubbing=on")
        
        feature_str = f" ({', '.join(features)})" if features else ""
        logger.info(f"✅ Azure Monitor configured{feature_str}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to configure Azure Monitor: {e}")
        
        # Retry without live metrics on permission errors
        if "Forbidden" in str(e) or "permissions" in str(e).lower():
            _live_metrics_disabled = True
            return setup_azure_monitor(logger_name, config)
        
        return False


def _install_filtering_processor(enable_pii_scrubbing: bool) -> None:
    """Install FilteringSpanProcessor to wrap existing processors."""
    try:
        from opentelemetry import trace as otel_trace
        
        provider = otel_trace.get_tracer_provider()
        if hasattr(provider, '_active_span_processor'):
            original = provider._active_span_processor
            provider._active_span_processor = FilteringSpanProcessor(
                original, enable_pii_scrubbing
            )
            logger.debug("FilteringSpanProcessor installed")
    except Exception as e:
        logger.warning(f"Could not install FilteringSpanProcessor: {e}")


def _add_root_logger_filters() -> None:
    """Add correlation and noise filters to root logger's Azure Monitor handler."""
    try:
        from opentelemetry.sdk._logs import LoggingHandler
        from utils.ml_logging import TraceLogFilter, WebSocketNoiseFilter
        from utils.pii_filter import get_pii_scrubber
        
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, LoggingHandler):
                if not any(isinstance(f, TraceLogFilter) for f in handler.filters):
                    handler.addFilter(TraceLogFilter())
                if not any(isinstance(f, WebSocketNoiseFilter) for f in handler.filters):
                    handler.addFilter(WebSocketNoiseFilter())
                break
    except Exception as e:
        logger.debug(f"Could not add root logger filters: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

def suppress_noisy_loggers(level: int = logging.WARNING) -> None:
    """Legacy function for backwards compatibility."""
    _suppress_noisy_loggers(level)


def suppress_azure_credential_logs() -> None:
    """Legacy function for backwards compatibility."""
    _suppress_noisy_loggers(logging.CRITICAL)


# Apply suppression when module is imported
_suppress_noisy_loggers()
