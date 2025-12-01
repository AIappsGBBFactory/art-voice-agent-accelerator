"""
OpenAI Instrumentation - MUST BE IMPORTED BEFORE ANY OPENAI USAGE

This module sets up OpenTelemetry instrumentation for the OpenAI Python client.
It MUST be imported before any code that imports `openai` or `AzureOpenAI`.

The instrumentation adds GenAI semantic convention spans for:
- chat.completions API calls
- Token usage (gen_ai.usage.input_tokens, gen_ai.usage.output_tokens)
- Model information (gen_ai.request.model)
- Time to first token (when streaming)

Usage:
    # At the very top of your main.py, BEFORE other imports:
    import utils.openai_instrumentation  # noqa: F401
    
    # Then continue with normal imports
    from utils.telemetry_config import setup_azure_monitor
    ...
"""

import logging
import os

logger = logging.getLogger(__name__)

_instrumented = False


def instrument_openai(tracer_provider=None) -> bool:
    """
    Instrument the OpenAI Python client for automatic tracing.
    
    IMPORTANT: This MUST be called BEFORE importing openai or creating any clients.
    
    Note: The opentelemetry-instrumentation-openai-v2 library imports openai internally
    to patch it, so openai will be in sys.modules after instrumentation. This is expected.
    
    Args:
        tracer_provider: Optional TracerProvider. If None, uses the global one.
    
    Returns:
        True if instrumentation succeeded, False otherwise.
    """
    global _instrumented
    
    if _instrumented:
        return True
    
    # Skip if telemetry is disabled
    if os.getenv("DISABLE_CLOUD_TELEMETRY", "false").lower() == "true":
        logger.debug("OpenAI instrumentation skipped (DISABLE_CLOUD_TELEMETRY=true)")
        return False
    
    try:
        # Check if openai was imported by USER CODE before instrumentation
        # (The instrumentor itself will import openai, which is expected)
        import sys
        openai_already_imported = "openai" in sys.modules
        
        from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
        
        # Enable content recording if configured
        content_recording = os.getenv(
            "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "false"
        ).lower() == "true"
        
        if content_recording:
            os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
            logger.info("GenAI content recording enabled (prompts/completions will be traced)")
        
        # Instrument OpenAI
        instrumentor = OpenAIInstrumentor()
        if tracer_provider:
            instrumentor.instrument(tracer_provider=tracer_provider)
        else:
            instrumentor.instrument()
        
        _instrumented = True
        
        if openai_already_imported:
            logger.warning(
                "⚠️ OpenAI module was imported before this module! "
                "GenAI spans may not work correctly. Import utils.openai_instrumentation earlier."
            )
        else:
            logger.info(
                "✅ OpenAI client instrumentation enabled (GenAI semantic conventions)",
                extra={"content_recording": content_recording}
            )
        return True
        
    except ImportError as e:
        logger.debug(f"opentelemetry-instrumentation-openai-v2 not available: {e}")
        return False
    except Exception as e:
        logger.warning(f"Failed to instrument OpenAI client: {e}")
        return False


def is_instrumented() -> bool:
    """Check if OpenAI instrumentation is enabled."""
    return _instrumented


# Auto-instrument when this module is imported (early init pattern)
# This ensures instrumentation happens before any openai imports
instrument_openai()
