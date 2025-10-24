# main.py
from __future__ import annotations

import asyncio
import logging
import platform
import sys
from typing import Union

from azure.ai.voicelive.aio import connect
from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.identity.aio import DefaultAzureCredential

from orchestrator import LiveOrchestrator
from registry import HANDOFF_MAP, load_registry
from settings import get_settings

# Initialize settings and configure logging
settings = get_settings()

# Import get_logger from utils (handles both console and telemetry)
sys.path.insert(0, str(__file__.rsplit('/', 4)[0] if '/' in __file__ else __file__.rsplit('\\', 4)[0]))
from src.utils.ml_logging import get_logger

log = get_logger("voicelive.main", level=getattr(logging, settings.log_level.upper()))

# Optional audio
HAS_AUDIO = False
if settings.enable_audio:
    try:
        import pyaudio  # noqa
        HAS_AUDIO = True
        from windows_audio import WindowsAudioProcessor as AudioProcessor
    except Exception:
        log.warning("pyaudio not available; running without audio (no mic/speaker)")

async def run():
    """Run the VoiceLive multi-agent system."""
    log.info("Starting VoiceLive Multi-Agent System")
    log.info(f"Endpoint: {settings.azure_voicelive_endpoint}")
    log.info(f"Model: {settings.voicelive_model}")
    log.info(f"Start Agent: {settings.start_agent}")
    
    # Configure credential
    credential: Union[AzureKeyCredential, TokenCredential]
    if settings.has_api_key_auth:
        credential = AzureKeyCredential(settings.azure_voicelive_api_key)
        log.info("Using API key credential")
    else:
        credential = DefaultAzureCredential()
        log.info("Using DefaultAzureCredential")

    # Load agents
    log.info(f"Loading agents from: {settings.agents_path}")
    agents = load_registry(str(settings.agents_path))

    # WebSocket connection options
    connection_options = {
        "max_msg_size": settings.ws_max_msg_size,
        "heartbeat": settings.ws_heartbeat,
        "timeout": settings.ws_timeout,
    }

    async with connect(
        endpoint=settings.azure_voicelive_endpoint,
        credential=credential,
        model=settings.voicelive_model,
        connection_options=connection_options
    ) as conn:
        audio = AudioProcessor(conn) if HAS_AUDIO else None

        orch = LiveOrchestrator(
            conn=conn,
            agents=agents,
            handoff_map=HANDOFF_MAP,
            start_agent=settings.start_agent,
            audio_processor=audio,
        )
        await orch.start()

        try:
            async for evt in conn:
                await orch.handle_event(evt)
        finally:
            if audio:
                await audio.cleanup()

if __name__ == "__main__":
    if platform.system() == "Windows":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
        except Exception:
            pass

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Shutdown requested by user")
        print("\nExiting...")
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        sys.exit(1)
