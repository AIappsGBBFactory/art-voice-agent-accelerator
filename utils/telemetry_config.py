# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
import logging
import os
import re
import warnings

# Suppress OpenTelemetry deprecation warnings about LogRecord init
# This warning was fixed in opentelemetry-instrumentation-openai-v2>=2.2b0
# Keep suppression as fallback for users with older versions
warnings.filterwarnings(
    "ignore",
    message="LogRecord init with.*is deprecated",
    module="opentelemetry"
)

# Ensure environment variables from .env are available BEFORE we check DISABLE_CLOUD_TELEMETRY.
try:  # minimal, silent if python-dotenv missing
    from dotenv import load_dotenv  # type: ignore

    # Only load if it looks like a .env file exists and variables not already present
    if os.path.isfile(".env"):
        load_dotenv(override=False)
except Exception:
    pass

from azure.core.exceptions import HttpResponseError, ServiceResponseError
from utils.azure_auth import get_credential, ManagedIdentityCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.sdk.resources import Resource, ResourceAttributes
from opentelemetry.trace import SpanKind

# Set up logger for this module (needs to be before functions that use it)
logger = logging.getLogger(__name__)
_live_metrics_permanently_disabled = False
_azure_monitor_configured = False

# ═══════════════════════════════════════════════════════════════════════════════
# OPENAI CLIENT INSTRUMENTOR (opentelemetry-instrumentation-openai-v2)
# Auto-instruments OpenAI Python client for GenAI semantic conventions
# ═══════════════════════════════════════════════════════════════════════════════

_openai_instrumentor_enabled = False

def _setup_openai_instrumentation(tracer_provider=None) -> bool:
    """
    Enable OpenAI client instrumentation for automatic tracing.
    
    IMPORTANT: This MUST be called BEFORE creating any OpenAI/AzureOpenAI clients.
    The instrumentor monkey-patches the openai module at import time.
    
    This uses opentelemetry-instrumentation-openai-v2 which automatically creates
    spans with GenAI semantic conventions for:
    - chat.completions API calls (including AzureOpenAI)
    - Token usage tracking (gen_ai.usage.input_tokens, gen_ai.usage.output_tokens)
    - Model information (gen_ai.request.model)
    - Streaming completions
    
    Content recording (prompts/completions) can be enabled via:
    - AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true environment variable
    
    Args:
        tracer_provider: Optional TracerProvider. If None, uses the global one.
    
    Returns:
        True if instrumentor was enabled successfully, False otherwise.
    """
    global _openai_instrumentor_enabled
    
    if _openai_instrumentor_enabled:
        return True
    
    # Check if early-init module already instrumented OpenAI
    try:
        from utils.openai_instrumentation import is_instrumented
        if is_instrumented():
            _openai_instrumentor_enabled = True
            logger.debug("OpenAI instrumentation already enabled via early-init module")
            return True
    except ImportError:
        pass  # Early-init module not available
    
    try:
        from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
        from opentelemetry import trace as otel_trace
        
        # Check if openai module was already imported (late instrumentation warning)
        import sys
        if "openai" in sys.modules:
            logger.warning(
                "⚠️ OpenAI module was imported before instrumentation setup! "
                "GenAI spans may not work correctly. Import utils.openai_instrumentation first."
            )
        
        # Enable content recording if configured
        # This captures gen_ai.request.messages and gen_ai.response.choices
        content_recording = os.getenv(
            "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "false"
        ).lower() == "true"
        
        if content_recording:
            # Ensure environment variable is set for SDK to pick up
            os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
            logger.info("GenAI content recording enabled (prompts/completions will be traced)")
        
        # Use provided tracer_provider or get the global one
        tp = tracer_provider or otel_trace.get_tracer_provider()
        OpenAIInstrumentor().instrument(tracer_provider=tp)
        
        _openai_instrumentor_enabled = True
        logger.info(
            "✅ OpenAI client instrumentation enabled (openai-v2)",
            extra={"content_recording": content_recording}
        )
        return True
        
    except ImportError:
        logger.debug(
            "opentelemetry-instrumentation-openai-v2 not available - "
            "install with: pip install opentelemetry-instrumentation-openai-v2"
        )
        return False
    except Exception as e:
        logger.warning(f"Failed to enable OpenAI client instrumentation: {e}")
        return False


def is_openai_instrumented() -> bool:
    """Check if OpenAI client instrumentation is enabled."""
    return _openai_instrumentor_enabled


# ═══════════════════════════════════════════════════════════════════════════════
# NOISY SPAN FILTERING - Filter high-frequency spans at export time
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# SPAN FILTERING CONFIGURATION
# Define patterns for spans to drop (used by NoisySpanFilterProcessor)
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns for span names that should ALWAYS be dropped (pure noise)
NOISY_SPAN_PATTERNS = [
    re.compile(r".*websocket\s*(receive|send).*", re.IGNORECASE),
    re.compile(r".*ws[._](receive|send).*", re.IGNORECASE),
    re.compile(r"HTTP.*websocket.*", re.IGNORECASE),
    re.compile(r"^(GET|POST)\s+.*(websocket|/ws/).*", re.IGNORECASE),
    # Internal frame/chunk processing (high frequency, low value)
    re.compile(r".*audio[._]chunk.*", re.IGNORECASE),
    re.compile(r".*audio[._]frame.*", re.IGNORECASE),
    re.compile(r".*process[._]frame.*", re.IGNORECASE),
    re.compile(r".*stream[._]chunk.*", re.IGNORECASE),
    re.compile(r".*emit[._]chunk.*", re.IGNORECASE),
    # Redis polling/connection maintenance
    re.compile(r".*redis[._](ping|pool|connection).*", re.IGNORECASE),
    # Session polling
    re.compile(r".*poll[._]session.*", re.IGNORECASE),
    re.compile(r".*session[._]heartbeat.*", re.IGNORECASE),
]

# URL patterns that indicate noisy operations (used by NoisySpanFilterProcessor)
NOISY_URL_PATTERNS = [
    "/api/v1/browser/conversation",
    "/api/v1/acs/media", 
    "/ws/",
    "/api/v1/health",
    "/api/v1/readiness",
]


# ═══════════════════════════════════════════════════════════════════════════════
# NOISY SPAN FILTER PROCESSOR
# SpanProcessor that filters noisy spans at export time
# This catches spans created by auto-instrumentation that bypass the sampler
# ═══════════════════════════════════════════════════════════════════════════════

from opentelemetry.sdk.trace import SpanProcessor, ReadableSpan

class NoisySpanFilterProcessor(SpanProcessor):
    """
    SpanProcessor that filters noisy spans at export time.
    
    Auto-instrumented spans (from FastAPI, ASGI, etc.) may bypass the sampler
    if they inherit sampling decisions from parent spans. This processor
    filters those spans before they are exported to Azure Monitor.
    """
    
    def __init__(self, next_processor: SpanProcessor):
        self._next = next_processor
    
    def on_start(self, span, parent_context=None):
        """Called when span starts - pass through."""
        self._next.on_start(span, parent_context)
    
    def on_end(self, span: ReadableSpan):
        """Filter noisy spans before passing to next processor."""
        span_name = span.name
        
        # Check against noisy patterns
        for pattern in NOISY_SPAN_PATTERNS:
            if pattern.match(span_name):
                # Drop this span - don't pass to next processor
                return
        
        # Pass non-noisy spans to next processor
        self._next.on_end(span)
    
    def shutdown(self):
        self._next.shutdown()
    
    def force_flush(self, timeout_millis=30000):
        return self._next.force_flush(timeout_millis)


# ═══════════════════════════════════════════════════════════════════════════════
# EMPTY BODY LOG RECORD FILTER
# Patches the Azure Monitor LogExporter to filter out empty body logs
# which cause 400 errors: "Field 'message' on type 'MessageData' is required"
# ═══════════════════════════════════════════════════════════════════════════════

_log_exporter_patched = False


def _patch_azure_monitor_log_exporter():
    """
    Patch the Azure Monitor LogExporter to filter out log records with empty bodies.
    
    Azure Monitor's Application Insights requires a non-empty 'message' field 
    for MessageData records. This patch wraps the exporter's export method to
    filter out log records that would cause 400 errors.
    """
    global _log_exporter_patched
    
    if _log_exporter_patched:
        return
    
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        
        original_export = AzureMonitorLogExporter.export
        
        def filtered_export(self, batch, *args, **kwargs):
            """Export logs, filtering out those with empty bodies."""
            # Filter out log records with empty bodies
            filtered_batch = []
            for log_data in batch:
                log_record = log_data.log_record
                body = getattr(log_record, 'body', None)
                
                # Skip if body is empty/None/whitespace-only
                if body is None:
                    continue
                if isinstance(body, str) and body.strip() == "":
                    continue
                if isinstance(body, (dict, list)) and len(body) == 0:
                    continue
                    
                filtered_batch.append(log_data)
            
            # Only export if we have logs to send
            if filtered_batch:
                return original_export(self, filtered_batch, *args, **kwargs)
            
            # Return success if all logs were filtered
            from opentelemetry.sdk._logs.export import LogExportResult
            return LogExportResult.SUCCESS
        
        AzureMonitorLogExporter.export = filtered_export
        _log_exporter_patched = True
        logger.debug("Azure Monitor LogExporter patched to filter empty body logs")
        
    except ImportError:
        logger.debug("Azure Monitor LogExporter not available for patching")
    except Exception as e:
        logger.warning(f"Failed to patch Azure Monitor LogExporter: {e}")


def _add_empty_body_log_filter():
    """
    Apply the empty body log filter by patching the Azure Monitor LogExporter.
    
    This must be called AFTER configure_azure_monitor() to ensure the exporter
    class is available. The patch filters out log records with empty bodies
    that would cause Azure Monitor 400 errors.
    """
    _patch_azure_monitor_log_exporter()


# ═══════════════════════════════════════════════════════════════════════════════
# NOISY LOGGER SUPPRESSION
# ═══════════════════════════════════════════════════════════════════════════════

# List of loggers that generate excessive noise during normal operation
NOISY_LOGGERS = [
    # Azure Identity - credential probing noise
    "azure.identity",
    "azure.identity._credentials.managed_identity",
    "azure.identity._credentials.app_service",
    "azure.identity._internal.msal_managed_identity_client",
    # Azure Core - HTTP pipeline noise
    "azure.core.pipeline.policies._authentication",
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.core.pipeline",
    # Azure Monitor - exporter noise
    "azure.monitor.opentelemetry.exporter.export._base",
    "azure.monitor.opentelemetry.exporter",
    # WebSocket/HTTP - connection chatter (CRITICAL for noise reduction)
    "websockets.protocol",
    "websockets.client",
    "websockets.server",
    "websockets",
    "aiohttp.access",
    "aiohttp.client",
    "httpx",
    "httpcore",
    # Uvicorn/Starlette WebSocket noise
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl", 
    "uvicorn.error",
    "uvicorn.access",
    "starlette.routing",
    # FastAPI internals
    "fastapi",
    # OpenTelemetry SDK - internal noise
    "opentelemetry.sdk.trace",
    "opentelemetry.exporter",
    "opentelemetry.instrumentation.asgi",
    # Redis - connection pool noise
    "redis.asyncio.connection",
    # Azure Speech SDK - verbose debug
    "azure.cognitiveservices.speech",
]


def suppress_noisy_loggers(level: int = logging.WARNING):
    """
    Suppress noisy loggers that generate excessive output during normal operation.
    
    Args:
        level: Minimum log level for suppressed loggers. Default WARNING.
    """
    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)
    
    # Also apply WebSocket noise filter to root logger
    try:
        from utils.ml_logging import WebSocketNoiseFilter
        root_logger = logging.getLogger()
        has_noise_filter = any(isinstance(f, WebSocketNoiseFilter) for f in root_logger.filters)
        if not has_noise_filter:
            root_logger.addFilter(WebSocketNoiseFilter())
    except ImportError:
        pass  # ml_logging not yet available


# Legacy function name for backwards compatibility
def suppress_azure_credential_logs():
    """Suppress noisy Azure credential logs that occur during DefaultAzureCredential attempts."""
    suppress_noisy_loggers(logging.CRITICAL)


# Apply suppression when module is imported
suppress_noisy_loggers()


def _get_instance_id() -> str:
    """
    Generate a unique instance identifier for Application Map visualization.
    
    Priority order:
    1. WEBSITE_INSTANCE_ID (Azure App Service)
    2. CONTAINER_APP_REPLICA_NAME (Azure Container Apps)
    3. HOSTNAME environment variable
    4. Socket hostname
    5. Random UUID fallback
    
    Returns:
        Unique identifier string for this service instance.
    """
    import socket
    import uuid
    
    # Azure App Service
    instance_id = os.getenv("WEBSITE_INSTANCE_ID")
    if instance_id:
        return instance_id[:8]  # Truncate for readability
    
    # Azure Container Apps
    replica_name = os.getenv("CONTAINER_APP_REPLICA_NAME")
    if replica_name:
        return replica_name
    
    # Kubernetes pod name
    pod_name = os.getenv("HOSTNAME")
    if pod_name and "-" in pod_name:  # Looks like a k8s pod name
        return pod_name
    
    # Fallback to socket hostname
    try:
        hostname = socket.gethostname()
        if hostname:
            return hostname
    except Exception:
        pass
    
    # Final fallback: random UUID
    return str(uuid.uuid4())[:8]


def is_azure_monitor_configured() -> bool:
    """Return True when Azure Monitor finished configuring successfully."""

    return _azure_monitor_configured


def setup_azure_monitor(logger_name: str = None):
    """
    Configure Azure Monitor / Application Insights if connection string is available.
    Implements fallback authentication and graceful degradation for live metrics.

    Args:
        logger_name (str, optional): Name for the Azure Monitor logger. Defaults to environment variable or 'default'.
    """
    global _live_metrics_permanently_disabled, _azure_monitor_configured

    # CRITICAL: Prevent double-configuration which causes duplicate telemetry
    if _azure_monitor_configured:
        logger.warning("setup_azure_monitor already configured - skipping to prevent duplicates")
        return
    
    # Also check if OpenTelemetry SDK TracerProvider is already set (e.g., by v2 module)
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
        current_provider = otel_trace.get_tracer_provider()
        if isinstance(current_provider, SDKTracerProvider):
            logger.warning(
                "setup_azure_monitor: SDK TracerProvider already configured by another module - skipping"
            )
            _azure_monitor_configured = True
            return
    except Exception:
        pass

    # Allow hard opt-out for local dev or debugging.
    if os.getenv("DISABLE_CLOUD_TELEMETRY", "true").lower() == "true":
        logger.info(
            "Telemetry disabled (DISABLE_CLOUD_TELEMETRY=true) – skipping Azure Monitor setup"
        )
        return

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    logger_name = logger_name or os.getenv("AZURE_MONITOR_LOGGER_NAME", "default")

    # Check if we should disable live metrics due to permission issues
    disable_live_metrics_env = (
        os.getenv("AZURE_MONITOR_DISABLE_LIVE_METRICS", "false").lower() == "true"
    )
    # Build resource attributes for Application Map visualization
    # service.name -> Cloud Role Name in App Insights
    # service.instance.id -> Cloud Role Instance (distinguishes replicas)
    resource_attrs = {
        "service.name": "rtagent-api",
        "service.namespace": "callcenter-app",
        "service.instance.id": _get_instance_id(),
    }
    env_name = os.getenv("ENVIRONMENT")
    if env_name:
        resource_attrs["service.environment"] = env_name
    
    # Add service version if available
    service_version = os.getenv("SERVICE_VERSION") or os.getenv("APP_VERSION")
    if service_version:
        resource_attrs["service.version"] = service_version
        
    resource = Resource.create(resource_attrs)

    if not connection_string:
        logger.info(
            "ℹ️ APPLICATIONINSIGHTS_CONNECTION_STRING not found, skipping Azure Monitor configuration"
        )
        return

    logger.info(f"Setting up Azure Monitor with logger_name: {logger_name}")
    logger.info(f"Connection string found: {connection_string[:50]}...")
    logger.info(f"Resource attributes: {resource_attrs}")

    try:
        # Try to get appropriate credential
        credential = _get_azure_credential()

        # Configure with live metrics initially disabled if environment variable is set
        # or if we're in a development environment
        enable_live_metrics = (
            not disable_live_metrics_env
            and not _live_metrics_permanently_disabled
            # and _should_enable_live_metrics()
        )

        logger.info(
            "Configuring Azure Monitor with live metrics: %s (env_disable=%s, permanent_disable=%s)",
            enable_live_metrics,
            disable_live_metrics_env,
            _live_metrics_permanently_disabled,
        )

        resource = Resource(attributes=resource_attrs)
        
        # Patch Azure Monitor LogExporter to filter empty body logs BEFORE configure_azure_monitor
        # creates the exporter instance. This prevents 400 errors from empty message bodies.
        _patch_azure_monitor_log_exporter()
        
        # Build list of span processors to add
        # NOTE: Do NOT create our own TracerProvider - configure_azure_monitor() creates one internally
        # and ignores any tracer_provider argument. We use span_processors instead.
        span_processors = []
        try:
            from utils.session_context import SessionContextSpanProcessor
            span_processors.append(SessionContextSpanProcessor())
            logger.info("SessionContextSpanProcessor added for automatic correlation")
        except ImportError:
            logger.debug("SessionContextSpanProcessor not available")
        
        configure_azure_monitor(
            resource=resource,
            logger_name=logger_name,
            credential=credential,
            connection_string=connection_string,
            enable_live_metrics=enable_live_metrics,
            span_processors=span_processors,
            disable_logging=False,
            disable_tracing=False,
            disable_metrics=False,
            logging_formatter=None,  # Explicitly set logging_formatter to None or provide a custom formatter if needed
            instrumentation_options={
                "azure_sdk": {"enabled": True},
                "redis": {"enabled": True},
                "aiohttp": {"enabled": True},
                "fastapi": {"enabled": True},
                "flask": {"enabled": True},
                "requests": {"enabled": True},
                "urllib3": {"enabled": True},
                "psycopg2": {"enabled": False},  # Disable psycopg2 since we use MongoDB
                "django": {"enabled": False},  # Disable django since we use FastAPI
            },
        )
        
        # Wrap existing span processors with NoisySpanFilterProcessor
        # This catches auto-instrumented spans that bypass the sampler
        try:
            from opentelemetry import trace as otel_trace
            provider = otel_trace.get_tracer_provider()
            if hasattr(provider, '_active_span_processor'):
                original_processor = provider._active_span_processor
                filter_processor = NoisySpanFilterProcessor(original_processor)
                provider._active_span_processor = filter_processor
                logger.info("NoisySpanFilterProcessor installed for WebSocket span filtering")
        except Exception as e:
            logger.warning(f"Could not install NoisySpanFilterProcessor: {e}")

        # ═══════════════════════════════════════════════════════════════════════════
        # ADD FILTERS TO ROOT LOGGER'S AZURE MONITOR HANDLER
        # configure_azure_monitor() adds a LoggingHandler to the root logger.
        # We need to add our filters (TraceLogFilter, WebSocketNoiseFilter) to ensure
        # correlation IDs are injected and noisy logs are filtered before export.
        # ═══════════════════════════════════════════════════════════════════════════
        try:
            from opentelemetry.sdk._logs import LoggingHandler
            from utils.ml_logging import TraceLogFilter, WebSocketNoiseFilter
            
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if isinstance(handler, LoggingHandler):
                    # Add filters if not already present
                    has_trace_filter = any(isinstance(f, TraceLogFilter) for f in handler.filters)
                    has_noise_filter = any(isinstance(f, WebSocketNoiseFilter) for f in handler.filters)
                    
                    if not has_trace_filter:
                        handler.addFilter(TraceLogFilter())
                    if not has_noise_filter:
                        handler.addFilter(WebSocketNoiseFilter())
                    
                    logger.info("Filters added to root logger's Azure Monitor handler")
                    break
        except Exception as e:
            logger.debug(f"Could not add filters to root logger's Azure Monitor handler: {e}")

        status_msg = "✅ Azure Monitor configured successfully"
        if not enable_live_metrics:
            status_msg += " (live metrics disabled)"
        status_msg += " (noisy WebSocket span filter enabled)"
        status_msg += " (empty body log filter enabled)"
        logger.info(status_msg)
        _azure_monitor_configured = True
        
        # Enable OpenAI client instrumentation - uses the global tracer provider set by configure_azure_monitor
        # NOTE: This must happen BEFORE any openai.AzureOpenAI clients are created
        _setup_openai_instrumentation()  # No tracer_provider arg - uses global

    except ImportError:
        logger.warning(
            "⚠️ Azure Monitor OpenTelemetry not available. Install azure-monitor-opentelemetry package."
        )
    except HttpResponseError as e:
        if "Forbidden" in str(e) or "permissions" in str(e).lower():
            logger.warning(
                "⚠️ Insufficient permissions for Application Insights. Retrying with live metrics disabled..."
            )
            _retry_without_live_metrics(logger_name, connection_string)
        else:
            logger.error(f"⚠️ HTTP error configuring Azure Monitor: {e}")
    except ServiceResponseError as e:
        _disable_live_metrics_permanently(
            "Live metrics ping failed during setup", exc_info=e
        )
        _retry_without_live_metrics(logger_name, connection_string)
    except Exception as e:
        logger.error(f"⚠️ Failed to configure Azure Monitor: {e}")
        import traceback

        logger.error(f"⚠️ Full traceback: {traceback.format_exc()}")


def _get_azure_credential():
    """
    Get the appropriate Azure credential based on the environment.
    Prioritizes managed identity in Azure-hosted environments.
    """
    try:
        # Try managed identity first if we're in Azure
        if os.getenv("WEBSITE_SITE_NAME") or os.getenv("CONTAINER_APP_NAME"):
            logger.debug("Using ManagedIdentityCredential for Azure-hosted environment")
            return ManagedIdentityCredential()
    except Exception as e:
        logger.debug(f"ManagedIdentityCredential not available: {e}")

    # Fall back to DefaultAzureCredential
    logger.debug("Using DefaultAzureCredential")
    return get_credential()


def _should_enable_live_metrics():
    """
    Determine if live metrics should be enabled based on environment.
    """
    # Disable in development environments by default
    if os.getenv("ENVIRONMENT", "").lower() in ["dev", "development", "local"]:
        return False

    # Enable in production environments
    if os.getenv("ENVIRONMENT", "").lower() in ["prod", "production"]:
        return True

    # For other environments, check if we're in Azure
    return bool(os.getenv("WEBSITE_SITE_NAME") or os.getenv("CONTAINER_APP_NAME"))


def _retry_without_live_metrics(logger_name: str, connection_string: str):
    """
    Retry Azure Monitor configuration without live metrics if permission errors occur.
    """
    if not connection_string:
        return

    global _azure_monitor_configured

    try:
        credential = _get_azure_credential()

        configure_azure_monitor(
            logger_name=logger_name,
            credential=credential,
            connection_string=connection_string,
            enable_live_metrics=False,  # Disable live metrics
            disable_logging=False,
            disable_tracing=False,
            disable_metrics=False,
            instrumentation_options={
                "azure_sdk": {"enabled": True},
                "aiohttp": {"enabled": True},
                "fastapi": {"enabled": True},
                "flask": {"enabled": True},
                "requests": {"enabled": True},
                "urllib3": {"enabled": True},
                "psycopg2": {"enabled": False},  # Disable psycopg2 since we use MongoDB
                "django": {"enabled": False},  # Disable django since we use FastAPI
            },
        )
        logger.info(
            "✅ Azure Monitor configured successfully (live metrics disabled due to permissions)"
        )
        _azure_monitor_configured = True

    except Exception as e:
        logger.error(
            f"⚠️ Failed to configure Azure Monitor even without live metrics: {e}"
        )
        _azure_monitor_configured = False


def _disable_live_metrics_permanently(reason: str, exc_info: Exception | None = None):
    """Set a module-level guard and environment flag to stop future QuickPulse attempts."""
    global _live_metrics_permanently_disabled
    if _live_metrics_permanently_disabled:
        return

    _live_metrics_permanently_disabled = True
    os.environ["AZURE_MONITOR_DISABLE_LIVE_METRICS"] = "true"

    if exc_info:
        logger.warning(
            "⚠️ %s. Live metrics disabled for remainder of process.",
            reason,
            exc_info=exc_info,
        )
    else:
        logger.warning(
            "⚠️ %s. Live metrics disabled for remainder of process.", reason
        )
