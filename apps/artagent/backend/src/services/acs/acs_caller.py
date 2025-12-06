"""
services/acs_caller.py
----------------------
Thin wrapper that creates (or returns) the AcsCaller helper you already
have in `src.acs.acs_helper`.  Splitting it out lets `main.py`
initialise it once during startup and any router import it later.
"""

from __future__ import annotations

import os

from apps.artagent.backend.src.services.acs.acs_helpers import construct_websocket_url

# Import constants that don't come from App Configuration
from config.constants import (
    ACS_CALL_CALLBACK_PATH,
    ACS_WEBSOCKET_PATH,
)
from src.acs.acs_helper import AcsCaller
from utils.ml_logging import get_logger

logger = get_logger("services.acs_caller")

# Singleton instance (created on first call)
_instance: AcsCaller | None = None


def _get_config_dynamic() -> dict:
    """
    Read ACS configuration dynamically from environment variables.

    This is called at runtime (not module import time) to ensure
    App Configuration values have been loaded into the environment.
    """
    return {
        "ACS_CONNECTION_STRING": os.getenv("ACS_CONNECTION_STRING", ""),
        "ACS_ENDPOINT": os.getenv("ACS_ENDPOINT", ""),
        "ACS_SOURCE_PHONE_NUMBER": os.getenv("ACS_SOURCE_PHONE_NUMBER", ""),
        "AZURE_SPEECH_ENDPOINT": os.getenv("AZURE_SPEECH_ENDPOINT", ""),
        "AZURE_STORAGE_CONTAINER_URL": os.getenv("AZURE_STORAGE_CONTAINER_URL", ""),
        "BASE_URL": os.getenv("BASE_URL", ""),
    }


def initialize_acs_caller_instance() -> AcsCaller | None:
    """
    Initialize and cache Azure Communication Services caller instance for telephony operations.

    This function creates a singleton AcsCaller instance configured with environment
    variables for outbound calling capabilities. It validates required configuration
    parameters and constructs appropriate callback and WebSocket URLs for ACS
    integration with the voice agent system.

    :return: Configured AcsCaller instance if environment variables are properly set, None otherwise.
    :raises ValueError: If required ACS configuration parameters are missing or invalid.
    """
    global _instance  # noqa: PLW0603
    if _instance:
        return _instance

    # Read config dynamically to get App Configuration values
    cfg = _get_config_dynamic()
    acs_source_phone = cfg["ACS_SOURCE_PHONE_NUMBER"]
    base_url = cfg["BASE_URL"]
    acs_connection_string = cfg["ACS_CONNECTION_STRING"]
    acs_endpoint = cfg["ACS_ENDPOINT"]
    speech_endpoint = cfg["AZURE_SPEECH_ENDPOINT"]
    storage_url = cfg["AZURE_STORAGE_CONTAINER_URL"]

    # Check if required ACS configuration is present
    if not all([acs_source_phone, base_url]):
        logger.warning(
            "⚠️  ACS TELEPHONY DISABLED: Missing required environment variables "
            "(ACS_SOURCE_PHONE_NUMBER=%s, BASE_URL=%s). "
            "📞 Dial-in and dial-out calling will not work. "
            "🔌 WebSocket conversation endpoint remains available for direct connections.",
            acs_source_phone[:4] + "..." if acs_source_phone else "<not set>",
            base_url[:30] + "..." if base_url else "<not set>",
        )
        return None

    callback_url = f"{base_url.rstrip('/')}{ACS_CALL_CALLBACK_PATH}"
    ws_url = construct_websocket_url(base_url, ACS_WEBSOCKET_PATH)
    if not ws_url:
        logger.error("Could not build ACS media WebSocket URL; disabling outbound calls")
        return None

    try:
        _instance = AcsCaller(
            source_number=acs_source_phone,
            acs_connection_string=acs_connection_string,
            acs_endpoint=acs_endpoint,
            callback_url=callback_url,
            websocket_url=ws_url,
            cognitive_services_endpoint=speech_endpoint,
            recording_storage_container_url=storage_url,
        )
        logger.info(
            "AcsCaller initialised with phone: %s...",
            acs_source_phone[:4] if acs_source_phone else "???",
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to initialise AcsCaller: %s", exc, exc_info=True)
        _instance = None
    return _instance
