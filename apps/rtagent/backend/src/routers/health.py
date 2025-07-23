import asyncio
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from src.stateful.state_managment import MemoManager
from settings import AZURE_CLIENT_ID, AZURE_OPENAI_ENDPOINT, AZURE_TENANT_ID

from utils.ml_logging import get_logger
from settings import (
    AZURE_CLIENT_ID,
    AZURE_TENANT_ID,
    AZURE_OPENAI_ENDPOINT,
    ACS_SOURCE_PHONE_NUMBER,
    ACS_CONNECTION_STRING,
)

logger = get_logger("health")

router = APIRouter()


def _validate_phone_number(phone_number: str) -> tuple[bool, str]:
    """
    Validate ACS phone number format.
    Returns (is_valid, error_message_if_invalid)
    """
    if not phone_number or phone_number == "null":
        return False, "Phone number not provided"

    if not phone_number.startswith("+"):
        return False, f"Phone number must start with '+': {phone_number}"

    if not phone_number[1:].isdigit():
        return False, f"Phone number must contain only digits after '+': {phone_number}"

    if len(phone_number) < 8 or len(phone_number) > 16:  # Basic length validation
        return (
            False,
            f"Phone number length invalid (8-15 digits expected): {phone_number}",
        )

    return True, ""


@router.get("/health")
async def health():
    """
    Basic health check endpoint - always returns 200 if server is running.
    Used by load balancers for basic liveness checks.
    """
    return {"status": "healthy", "message": "Server is running!"}


@router.get("/readiness")
async def readiness(request: Request):
    """
    Fast readiness probe: checks only that core dependencies are initialized and responsive within 1-5s.
    No deep or blocking checks. Returns degraded if any are not ready.
    """
    start_time = time.time()
    health_checks = []
    overall_status = "ready"
    timeout = 1.0  # seconds per check

    async def fast_ping(check_fn, *args, component=None):
        try:
            result = await asyncio.wait_for(check_fn(*args), timeout=timeout)
            return result
        except Exception as e:
            return {
                "component": component or check_fn.__name__,
                "status": "unhealthy",
                "error": str(e),
                "check_time_ms": round((time.time() - start_time) * 1000, 2),
            }

    # Only check if initialized and can respond to a ping/basic call
    redis_status = await fast_ping(
        _check_redis_fast, request.app.state.redis, component="redis"
    )
    health_checks.append(redis_status)

    openai_status = await fast_ping(
        _check_azure_openai_fast,
        request.app.state.azureopenai_client,
        component="azure_openai",
    )
    health_checks.append(openai_status)

    speech_status = await fast_ping(
        _check_speech_services_fast,
        request.app.state.tts_client,
        request.app.state.stt_client,
        component="speech_services",
    )
    health_checks.append(speech_status)

    acs_status = await fast_ping(
        _check_acs_caller_fast, request.app.state.acs_caller, component="acs_caller"
    )
    health_checks.append(acs_status)

    agent_status = await fast_ping(
        _check_rt_agents_fast,
        request.app.state.auth_agent,
        request.app.state.claim_intake_agent,
        component="rt_agents",
    )
    health_checks.append(agent_status)

    failed_checks = [check for check in health_checks if check["status"] != "healthy"]
    if failed_checks:
        overall_status = (
            "degraded" if len(failed_checks) < len(health_checks) else "unhealthy"
        )

    response_time = round((time.time() - start_time) * 1000, 2)
    response_data = {
        "status": overall_status,
        "timestamp": time.time(),
        "response_time_ms": response_time,
        "checks": health_checks,
    }
    # Always return quickly, never block
    return JSONResponse(
        content=response_data, status_code=200 if overall_status != "unhealthy" else 503
    )


async def _check_redis_fast(redis_manager) -> Dict:
    start = time.time()
    if not redis_manager:
        return {
            "component": "redis",
            "status": "unhealthy",
            "error": "not initialized",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }
    try:
        pong = await asyncio.wait_for(redis_manager.ping(), timeout=0.5)
        if pong:
            return {
                "component": "redis",
                "status": "healthy",
                "check_time_ms": round((time.time() - start) * 1000, 2),
            }
        else:
            return {
                "component": "redis",
                "status": "unhealthy",
                "error": "no pong",
                "check_time_ms": round((time.time() - start) * 1000, 2),
            }
    except Exception as e:
        return {
            "component": "redis",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }


async def _check_azure_openai_fast(openai_client) -> Dict:
    start = time.time()
    if not openai_client:
        return {
            "component": "azure_openai",
            "status": "unhealthy",
            "error": "not initialized",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }
    return {
        "component": "azure_openai",
        "status": "healthy",
        "check_time_ms": round((time.time() - start) * 1000, 2),
    }


async def _check_speech_services_fast(tts_client, stt_client) -> Dict:
    start = time.time()
    if not tts_client or not stt_client:
        return {
            "component": "speech_services",
            "status": "unhealthy",
            "error": "not initialized",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }
    return {
        "component": "speech_services",
        "status": "healthy",
        "check_time_ms": round((time.time() - start) * 1000, 2),
    }


async def _check_acs_caller_fast(acs_caller) -> Dict:
    """Fast ACS caller check with comprehensive phone number and config validation."""
    start = time.time()

    # Check if ACS phone number is provided
    if not ACS_SOURCE_PHONE_NUMBER or ACS_SOURCE_PHONE_NUMBER == "null":
        return {
            "component": "acs_caller",
            "status": "unhealthy",
            "error": "ACS_SOURCE_PHONE_NUMBER not provided",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }

    # Validate phone number format
    is_valid, error_msg = _validate_phone_number(ACS_SOURCE_PHONE_NUMBER)
    if not is_valid:
        return {
            "component": "acs_caller",
            "status": "unhealthy",
            "error": f"ACS phone number validation failed: {error_msg}",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }

    # Check ACS connection string or endpoint id
    acs_conn_missing = not ACS_CONNECTION_STRING
    acs_endpoint_missing = not AZURE_OPENAI_ENDPOINT
    if acs_conn_missing and acs_endpoint_missing:
        return {
            "component": "acs_caller",
            "status": "unhealthy",
            "error": "Neither ACS_CONNECTION_STRING nor AZURE_OPENAI_ENDPOINT is configured",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }

    # If ACS caller is not initialized, treat as optional but log config status
    if not acs_caller:
        return {
            "component": "acs_caller",
            "status": "healthy",
            "check_time_ms": round((time.time() - start) * 1000, 2),
            "details": "ACS caller not configured (optional component)",
        }

    return {
        "component": "acs_caller",
        "status": "healthy",
        "check_time_ms": round((time.time() - start) * 1000, 2),
        "details": f"ACS caller configured with phone: {ACS_SOURCE_PHONE_NUMBER}",
    }
async def _check_rt_agents_fast(auth_agent, claim_intake_agent) -> Dict:
    start = time.time()
    if not auth_agent or not claim_intake_agent:
        return {
            "component": "rt_agents",
            "status": "unhealthy",
            "error": "not initialized",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }
    return {
        "component": "rt_agents",
        "status": "healthy",
        "check_time_ms": round((time.time() - start) * 1000, 2),
    }
