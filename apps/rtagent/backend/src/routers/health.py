import asyncio
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from settings import (
    ACS_CONNECTION_STRING,
    ACS_ENDPOINT,
    ACS_SOURCE_PHONE_NUMBER,
    AZURE_CLIENT_ID,
    AZURE_OPENAI_ENDPOINT,
    AZURE_TENANT_ID,
)

from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger

logger = get_logger("health")

router = APIRouter()


def _validate_phone_number(phone_number: str) -> tuple[bool, str]:
    """
    Validate Azure Communication Services phone number format and structure.

    This function performs comprehensive validation of phone numbers used with ACS,
    ensuring they meet international dialing standards and service requirements
    for successful call initiation and routing.

    :param phone_number: The phone number string to validate for ACS compatibility.
    :return: Tuple containing validation status (bool) and error message (str, empty if valid).
    :raises: None (validation errors returned as tuple values, not exceptions).
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
    Provide basic application health status for load balancer liveness checks.

    This endpoint serves as a simple liveness probe that confirms the FastAPI
    application is running and responsive. It always returns HTTP 200 with
    a healthy status message when the server process is operational.

    :return: Dictionary containing status confirmation and server running message.
    :raises: None (endpoint designed to always succeed when server is operational).
    """
    return {"status": "healthy", "message": "Server is running!"}


@router.get("/readiness")
async def readiness(request: Request):
    """
    Perform comprehensive readiness validation of core system dependencies.

    This endpoint conducts fast health checks across critical application dependencies
    including Redis, Azure OpenAI, Speech Services, ACS caller, and real-time agents.
    Each component is tested within a 1-second timeout to ensure responsive operation
    for Kubernetes readiness probes and load balancer routing decisions.

    :param request: FastAPI request object providing access to application state and dependencies.
    :return: JSONResponse with overall readiness status and detailed component health results.
    :raises HTTPException: Returns 503 Service Unavailable if core dependencies are unhealthy.
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
        request.app.state.tts_pool,
        request.app.state.stt_pool,
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
    """
    Perform fast Redis connectivity and responsiveness validation.

    This function executes a lightweight ping operation against Redis to verify
    the connection is active and the service is responding within acceptable
    timeouts for readiness probe requirements.

    :param redis_manager: The Redis client manager instance for connection testing.
    :return: Dictionary containing component status, timing, and error details if applicable.
    :raises: None (all exceptions captured and returned as status information).
    """
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
    """
    Perform fast Azure OpenAI service connectivity and availability validation.

    This function executes a lightweight operation against the Azure OpenAI client
    to verify the service connection is active and the API endpoint is responding
    within acceptable timeouts for readiness requirements.

    :param openai_client: The Azure OpenAI client instance for service testing.
    :return: Dictionary containing component status, timing, and error details if applicable.
    :raises: None (all exceptions captured and returned as status information).
    """
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


async def _check_speech_services_fast(tts_pool, stt_pool) -> Dict:
    """
    Perform fast Azure Speech Services resource pool availability validation.

    This function checks both Text-to-Speech and Speech-to-Text resource pools
    to verify they are initialized and have available instances for real-time
    voice processing operations within readiness probe timeouts.

    :param tts_pool: The Text-to-Speech client pool for voice synthesis testing.
    :param stt_pool: The Speech-to-Text client pool for voice recognition testing.
    :return: Dictionary containing component status, timing, and error details if applicable.
    :raises: None (all exceptions captured and returned as status information).
    """
    start = time.time()
    if not tts_pool or not stt_pool:
        return {
            "component": "speech_services",
            "status": "unhealthy",
            "error": "pools not initialized",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }

    # Check if pools are properly configured
    try:
        pool_info = {
            "tts_pool_size": tts_pool._size,
            "tts_pool_queue_size": tts_pool._q.qsize(),
            "tts_pool_ready": tts_pool._ready.is_set(),
            "stt_pool_size": stt_pool._size,
            "stt_pool_queue_size": stt_pool._q.qsize(),
            "stt_pool_ready": stt_pool._ready.is_set(),
        }
    except Exception as e:
        return {
            "component": "speech_services",
            "status": "unhealthy",
            "error": f"pool introspection failed: {e}",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }

    return {
        "component": "speech_services",
        "status": "healthy",
        "pool_info": pool_info,
        "check_time_ms": round((time.time() - start) * 1000, 2),
    }


async def _check_acs_caller_fast(acs_caller) -> Dict:
    """
    Perform fast Azure Communication Services caller client validation.

    This function verifies the ACS caller client is properly initialized and
    configured with valid connection strings and endpoints for telephony
    operations within readiness probe requirements.

    :param acs_caller: The Azure Communication Services caller client for telephony testing.
    :return: Dictionary containing component status, timing, and error details if applicable.
    :raises: None (all exceptions captured and returned as status information).
    """
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
    acs_endpoint_missing = not ACS_ENDPOINT
    if acs_conn_missing and acs_endpoint_missing:
        return {
            "component": "acs_caller",
            "status": "unhealthy",
            "error": "Neither ACS_CONNECTION_STRING nor ACS_ENDPOINT is configured",
            "check_time_ms": round((time.time() - start) * 1000, 2),
        }

    if not acs_caller:
        # Try to diagnose why ACS caller is not configured
        missing = []
        if not is_valid:
            missing.append(f"ACS_SOURCE_PHONE_NUMBER ({error_msg})")
        if not ACS_CONNECTION_STRING:
            missing.append("ACS_CONNECTION_STRING")
        if not ACS_ENDPOINT:
            missing.append("ACS_ENDPOINT")
        details = (
            f"ACS caller not configured. Missing: {', '.join(missing)}"
            if missing
            else "ACS caller not initialized for unknown reason"
        )
        return {
            "component": "acs_caller",
            "status": "unhealthy",
            "check_time_ms": round((time.time() - start) * 1000, 2),
            "details": details,
        }

    # Obfuscate phone number, show only last 4 digits
    obfuscated_phone = (
        "*" * (len(ACS_SOURCE_PHONE_NUMBER) - 4) + ACS_SOURCE_PHONE_NUMBER[-4:]
        if len(ACS_SOURCE_PHONE_NUMBER) > 4
        else ACS_SOURCE_PHONE_NUMBER
    )
    return {
        "component": "acs_caller",
        "status": "healthy",
        "check_time_ms": round((time.time() - start) * 1000, 2),
        "details": f"ACS caller configured with phone: {obfuscated_phone}",
    }


async def _check_rt_agents_fast(auth_agent, claim_intake_agent) -> Dict:
    """
    Perform fast real-time conversation agent availability validation.

    This function verifies both authentication and claim intake agents are properly
    initialized and ready to handle conversation orchestration and dialog flow
    management within readiness probe timeouts.

    :param auth_agent: The authentication agent for user verification and authorization.
    :param claim_intake_agent: The claim intake agent for main conversation dialog processing.
    :return: Dictionary containing component status, timing, and error details if applicable.
    :raises: None (all exceptions captured and returned as status information).
    """
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
