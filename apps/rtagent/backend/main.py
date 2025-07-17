"""
voice_agent.main
================
Entrypoint that stitches everything together:

• config / CORS
• shared objects on `app.state`  (Speech, Redis, ACS, TTS, dashboard-clients)
• route registration (routers package)
"""

from __future__ import annotations

import os

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.rtagent.backend.src.routers import router as api_router
from apps.rtagent.backend.src.agents.prompt_store.prompt_manager import PromptManager
from apps.rtagent.backend.src.services.acs.acs_caller import (
    initialize_acs_caller_instance,
)
from apps.rtagent.backend.src.services.openai_services import (
    client as azure_openai_client,
)
from apps.rtagent.backend.settings import (
    ALLOWED_ORIGINS,
    AZURE_COSMOS_COLLECTION_NAME,
    AZURE_COSMOS_CONNECTION_STRING,
    AZURE_COSMOS_DATABASE_NAME,
    SILENCE_DURATION_MS,
    VOICE_TTS,
    RECOGNIZED_LANGUAGE,
    AUDIO_FORMAT,
    AGENT_AUTH_CONFIG,
    AGENT_CLAIM_INTAKE_CONFIG,
)
from apps.rtagent.backend.src.services import (
    AzureRedisManager,
    CosmosDBMongoCoreManager,
    SpeechSynthesizer,
    StreamingSpeechRecognizerFromBytes,
)

from src.agents.base import RTAgent
from utils.ml_logging import get_logger

logger = get_logger("main")


# --------------------------------------------------------------------------- #
#  Lifecycle Management
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown events."""
    # Startup
    logger.info("🚀 startup…")

    # Initialize app state
    app.state.clients = set()  # /relay dashboard sockets
    app.state.greeted_call_ids = set()  # to avoid double greetings

    # Speech SDK
    app.state.tts_client = SpeechSynthesizer(voice=VOICE_TTS, 
                                             playback="always")
    app.state.stt_client = StreamingSpeechRecognizerFromBytes(
        vad_silence_timeout_ms=SILENCE_DURATION_MS,
        candidate_languages=RECOGNIZED_LANGUAGE,
        audio_format=AUDIO_FORMAT,
    )

    # Redis connection
    app.state.redis = AzureRedisManager()

    # Cosmos DB connection
    app.state.cosmos = CosmosDBMongoCoreManager(
        connection_string=AZURE_COSMOS_CONNECTION_STRING,
        database_name=AZURE_COSMOS_DATABASE_NAME,
        collection_name=AZURE_COSMOS_COLLECTION_NAME,
    )
    app.state.azureopenai_client = azure_openai_client
    app.state.promptsclient = PromptManager()

    # Outbound ACS caller (may be None if env vars missing)
    app.state.acs_caller = initialize_acs_caller_instance()
    app.state.auth_agent = RTAgent(config_path=AGENT_AUTH_CONFIG)
    app.state.claim_intake_agent = RTAgent(config_path=AGENT_CLAIM_INTAKE_CONFIG)

    logger.info("startup complete")

    # Yield control to the application
    yield

    # Shutdown
    logger.info("🛑 shutdown…")
    # Close Redis, ACS sessions, etc. if your helpers expose close() methods
    # Add any cleanup logic here as needed


# --------------------------------------------------------------------------- #
#  App factory
# --------------------------------------------------------------------------- #
app = FastAPI(lifespan=lifespan)

# ---------------- Middleware ------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=86400,
)

# ---------------- Routers ---------------------------------------------------
app.include_router(api_router)

# --------------------------------------------------------------------------- #
#  CLI entry-point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8010))
    uvicorn.run(
        "main:app",  # Use import string to support reload
        host="0.0.0.0",
        port=port,
        reload=True,
    )
