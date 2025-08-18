"""
voice_agent.main
================
Entrypoint that stitches everything together:

• config / CORS
• shared objects on `app.state`  (Speech pools, Redis, ACS, dashboard-clients)
• route registration (routers package)
"""

from __future__ import annotations

import sys
import os

# Add parent directories to sys.path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))

from utils.telemetry_config import setup_azure_monitor

# ---------------- Monitoring ------------------------------------------------
setup_azure_monitor(logger_name="rtagent")

from utils.ml_logging import get_logger

logger = get_logger("main")

import time
import asyncio
from datetime import datetime
from typing import Awaitable, Callable, TypeVar
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from src.pools.async_pool import AsyncPool
from src.pools.websocket_manager import ThreadSafeWebSocketManager
from src.pools.session_metrics import ThreadSafeSessionMetrics

from apps.rtagent.backend.settings import (
    AGENT_AUTH_CONFIG,
    AGENT_CLAIM_INTAKE_CONFIG,
    AGENT_GENERAL_INFO_CONFIG,
    ALLOWED_ORIGINS,
    AUDIO_FORMAT,
    AZURE_COSMOS_COLLECTION_NAME,
    AZURE_COSMOS_CONNECTION_STRING,
    AZURE_COSMOS_DATABASE_NAME,
    RECOGNIZED_LANGUAGE,
    SILENCE_DURATION_MS,
    VAD_SEMANTIC_SEGMENTATION,
    GREETING_VOICE_TTS,
    ENTRA_EXEMPT_PATHS,
    ENABLE_AUTH_VALIDATION,
)

from apps.rtagent.backend.src.agents.base import ARTAgent
from apps.rtagent.backend.src.utils.auth import validate_entraid_token
from apps.rtagent.backend.src.agents.prompt_store.prompt_manager import PromptManager

# from apps.rtagent.backend.src.routers import router as api_router
from apps.rtagent.backend.api.v1.router import v1_router
from apps.rtagent.backend.src.services import (
    AzureRedisManager,
    CosmosDBMongoCoreManager,
    SpeechSynthesizer,
    StreamingSpeechRecognizerFromBytes,
)
from apps.rtagent.backend.src.services.acs.acs_caller import (
    initialize_acs_caller_instance,
)
from apps.rtagent.backend.src.services.openai_services import (
    client as azure_openai_client,
)
from apps.rtagent.backend.api.v1.events.registration import register_default_handlers


# --------------------------------------------------------------------------- #
#  Lifecycle Management
# --------------------------------------------------------------------------- #
async def lifespan(app: FastAPI):
    """
    Manage complete application lifecycle including startup and shutdown events.

    This function handles the initialization and cleanup of all application components
    including speech pools, Redis connections, Cosmos DB, Azure OpenAI clients, and
    ACS agents. It provides comprehensive resource management with proper tracing and
    error handling for production deployment.

    :param app: The FastAPI application instance requiring lifecycle management.
    :return: AsyncGenerator yielding control to the application runtime.
    :raises RuntimeError: If critical startup components fail to initialize.
    """
    tracer = trace.get_tracer(__name__)

    # ---- Startup ----
    with tracer.start_as_current_span("startup-lifespan") as span:
        logger.info("🚀 startup…")
        start_time = time.perf_counter()

        span.set_attributes(
            {
                "service.name": "rtagent-api",
                "service.version": "1.0.0",
                "startup.stage": "initialization",
            }
        )

        # ------------------------ Process-wide shared state -------------------
        # Dashboard sockets & greeted set
        # Thread-safe WebSocket client management
        from src.pools.session_manager import ThreadSafeSessionManager

        app.state.websocket_manager = ThreadSafeWebSocketManager()
        app.state.session_manager = ThreadSafeSessionManager()

        app.state.greeted_call_ids = set()  # avoid double greetings

        # Thread-safe session metrics for visibility
        app.state.session_metrics = ThreadSafeSessionMetrics()

        # ------------------------ Speech Pools (TTS / STT) -------------------
        span.set_attribute("startup.stage", "speech_pools")

        # Pool sizes via env; tune to expected per-worker concurrency
        POOL_SIZE_TTS = int(os.getenv("POOL_SIZE_TTS", "8"))
        POOL_SIZE_STT = int(os.getenv("POOL_SIZE_STT", "8"))

        async def make_tts() -> SpeechSynthesizer:
            """
            Create and configure a new Text-to-Speech synthesizer instance.

            This factory function creates a properly configured SpeechSynthesizer
            with the appropriate voice settings and playback configuration for
            real-time audio generation in the voice agent system.

            :param: None (uses configuration from environment variables).
            :return: Configured SpeechSynthesizer instance ready for audio generation.
            :raises SpeechServiceError: If TTS service initialization fails.
            """
            # If SDK benefits from a warm-up, you can synth a short phrase here.
            return SpeechSynthesizer(voice=GREETING_VOICE_TTS, playback="always")

        async def make_stt() -> StreamingSpeechRecognizerFromBytes:
            """
            Create and configure a new Speech-to-Text recognizer instance.

            This factory function creates a properly configured streaming speech
            recognizer with semantic segmentation, VAD settings, and language
            configuration for real-time audio processing and transcription.

            :param: None (uses configuration from environment variables).
            :return: Configured StreamingSpeechRecognizerFromBytes instance ready for transcription.
            :raises SpeechServiceError: If STT service initialization fails.
            """
            return StreamingSpeechRecognizerFromBytes(
                use_semantic_segmentation=VAD_SEMANTIC_SEGMENTATION,
                vad_silence_timeout_ms=SILENCE_DURATION_MS,
                candidate_languages=RECOGNIZED_LANGUAGE,
                audio_format=AUDIO_FORMAT,
            )

        app.state.tts_pool = AsyncPool(make_tts, POOL_SIZE_TTS)
        app.state.stt_pool = AsyncPool(make_stt, POOL_SIZE_STT)

        # Warm both pools concurrently
        await asyncio.gather(
            app.state.tts_pool.prepare(),
            app.state.stt_pool.prepare(),
        )

        # ------------------------ Other singletons ---------------------------
        span.set_attribute("startup.stage", "redis")
        app.state.redis = AzureRedisManager()

        span.set_attribute("startup.stage", "cosmos_db")
        app.state.cosmos = CosmosDBMongoCoreManager(
            connection_string=AZURE_COSMOS_CONNECTION_STRING,
            database_name=AZURE_COSMOS_DATABASE_NAME,
            collection_name=AZURE_COSMOS_COLLECTION_NAME,
        )

        span.set_attribute("startup.stage", "openai_clients")
        app.state.azureopenai_client = azure_openai_client
        app.state.promptsclient = PromptManager()

        span.set_attribute("startup.stage", "acs_agents")
        app.state.acs_caller = initialize_acs_caller_instance()
        app.state.auth_agent = ARTAgent(config_path=AGENT_AUTH_CONFIG)
        app.state.claim_intake_agent = ARTAgent(config_path=AGENT_CLAIM_INTAKE_CONFIG)
        app.state.general_info_agent = ARTAgent(config_path=AGENT_GENERAL_INFO_CONFIG)

        # ------------------------ Events / Orchestrator -----------------------
        span.set_attribute("startup.stage", "v1_event_handlers")
        register_default_handlers()
        logger.info("✅ V1 event handlers registered at startup")

        span.set_attribute("startup.stage", "orchestrator")
        orchestrator_preset = os.getenv("ORCHESTRATOR_PRESET", "production")
        logger.info(f"Initializing orchestrator with preset: {orchestrator_preset}")

        elapsed = time.perf_counter() - start_time
        logger.info(f"startup complete in {elapsed:.2f}s")
        span.set_attributes(
            {
                "startup.duration_sec": elapsed,
                "startup.stage": "complete",
                "startup.success": True,
            }
        )

    # ---- Run app ----
    yield

    # ---- Shutdown ----
    with tracer.start_as_current_span("shutdown-lifespan") as span:
        logger.info("🛑 shutdown…")
        span.set_attributes(
            {"service.name": "rtagent-api", "shutdown.stage": "cleanup"}
        )
        span.set_attribute("shutdown.success", True)


# --------------------------------------------------------------------------- #
#  App factory with Dynamic Documentation
# --------------------------------------------------------------------------- #
def create_app() -> FastAPI:
    """
    Create and configure the main FastAPI application instance with comprehensive settings.

    This function initializes the FastAPI application with complete documentation,
    contact information, license details, OpenAPI tags, and lifecycle management.
    It provides the foundation for the real-time voice agent API with proper
    documentation generation capabilities.

    :param: None (uses configuration from imported modules and environment).
    :return: Fully configured FastAPI application instance ready for deployment.
    :raises ImportError: If required documentation modules cannot be imported.
    """
    from apps.rtagent.backend.api.swagger_docs import get_tags, get_description

    tags = get_tags()
    description = get_description()

    app = FastAPI(
        title="Real-Time Voice Agent API",
        description=description,
        version="1.0.0",
        contact={"name": "Real-Time Voice Agent Team", "email": "support@example.com"},
        license_info={
            "name": "MIT License",
            "url": "https://opensource.org/licenses/MIT",
        },
        openapi_tags=tags,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    return app


# --------------------------------------------------------------------------- #
#  App Initialization with Dynamic Documentation
# --------------------------------------------------------------------------- #
def setup_app_middleware_and_routes(app: FastAPI):
    """
    Configure comprehensive middleware stack and route registration for the application.

    This function sets up CORS middleware for cross-origin requests, implements
    authentication middleware for Entra ID validation, and registers all API
    routers including v1 endpoints for health, calls, media, and real-time features.

    :param app: The FastAPI application instance to configure with middleware and routes.
    :return: None (modifies the application instance in place).
    :raises HTTPException: If authentication validation fails during middleware setup.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        max_age=86400,
    )

    if ENABLE_AUTH_VALIDATION:

        @app.middleware("http")
        async def entraid_auth_middleware(request: Request, call_next):
            """
            Validate Entra ID authentication tokens for protected API endpoints.

            This middleware function checks incoming requests for valid authentication
            tokens, exempts specified paths from validation, and ensures proper
            security enforcement across the API surface area.

            :param request: The incoming HTTP request requiring authentication validation.
            :param call_next: The next middleware or endpoint handler in the chain.
            :return: HTTP response from the next handler or authentication error response.
            :raises HTTPException: If authentication token validation fails.
            """
            path = request.url.path
            if any(path.startswith(p) for p in ENTRA_EXEMPT_PATHS):
                return await call_next(request)
            try:
                await validate_entraid_token(request)
            except HTTPException as e:
                return JSONResponse(
                    content={"error": e.detail}, status_code=e.status_code
                )
            return await call_next(request)

    # app.include_router(api_router)  # legacy, if needed
    app.include_router(v1_router)

    # Health endpoints are now included in v1_router at /api/v1/health


# Create the app
app = None


def initialize_app():
    """
    Initialize the complete application with comprehensive configuration and setup.

    This function creates the FastAPI application instance and applies all necessary
    middleware, routes, and configuration settings. It serves as the main entry
    point for application initialization in production and development environments.

    :param: None (uses global configuration and imported settings).
    :return: Fully initialized FastAPI application instance ready for deployment.
    :raises RuntimeError: If application initialization fails at any stage.
    """
    global app
    app = create_app()
    setup_app_middleware_and_routes(app)
    return app


# Initialize the app
app = initialize_app()

# --------------------------------------------------------------------------- #
#  CLI entry-point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8010))
    # For development with reload, use the import string instead of app object
    uvicorn.run(
        "main:app",  # Use import string for reload to work
        host="0.0.0.0",  # nosec: B104
        port=port,
        reload=True,
    )
