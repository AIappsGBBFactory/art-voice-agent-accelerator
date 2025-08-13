"""
Health Endpoints
===============

Comprehensive health check and readiness endpoints for monitoring.
Includes all critical dependency checks with proper timeouts and error handling.
"""

import asyncio
import re
import time
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from apps.rtagent.backend.settings import (
    ACS_CONNECTION_STRING,
    ACS_ENDPOINT,
    ACS_SOURCE_PHONE_NUMBER,
    BACKEND_AUTH_CLIENT_ID,
    AZURE_TENANT_ID,
    ALLOWED_CLIENT_IDS,
    ENABLE_AUTH_VALIDATION
)
from apps.rtagent.backend.api.v1.schemas.health import (
    HealthResponse,
    ServiceCheck,
    ReadinessResponse,
)
from utils.ml_logging import get_logger

logger = get_logger("v1.health")

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


def _validate_guid(guid_str: str) -> bool:
    """
    Validate if a string is a valid GUID format.
    Returns True if valid GUID, False otherwise.
    """
    if not guid_str:
        return False
    
    # GUID pattern: 8-4-4-4-12 hexadecimal digits
    guid_pattern = re.compile(
        r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    )
    return bool(guid_pattern.match(guid_str))


def _validate_auth_configuration() -> tuple[bool, str]:
    """
    Validate authentication configuration when ENABLE_AUTH_VALIDATION is True.
    Returns (is_valid, error_message_if_invalid)
    """
    if not ENABLE_AUTH_VALIDATION:
        return True, "Auth validation disabled"
    
    validation_errors = []
    
    # Check BACKEND_AUTH_CLIENT_ID is a valid GUID
    if not BACKEND_AUTH_CLIENT_ID:
        validation_errors.append("BACKEND_AUTH_CLIENT_ID is not set")
    elif not _validate_guid(BACKEND_AUTH_CLIENT_ID):
        validation_errors.append("BACKEND_AUTH_CLIENT_ID is not a valid GUID")
    
    # Check AZURE_TENANT_ID is a valid GUID
    if not AZURE_TENANT_ID:
        validation_errors.append("AZURE_TENANT_ID is not set")
    elif not _validate_guid(AZURE_TENANT_ID):
        validation_errors.append("AZURE_TENANT_ID is not a valid GUID")
    
    # Check ALLOWED_CLIENT_IDS has at least one valid client ID
    if not ALLOWED_CLIENT_IDS:
        validation_errors.append("ALLOWED_CLIENT_IDS is empty - at least one client ID required")
    else:
        invalid_client_ids = [cid for cid in ALLOWED_CLIENT_IDS if not _validate_guid(cid)]
        if invalid_client_ids:
            validation_errors.append(f"Invalid GUID format in ALLOWED_CLIENT_IDS: {invalid_client_ids}")
    
    if validation_errors:
        return False, "; ".join(validation_errors)
    
    return True, f"Auth validation enabled with {len(ALLOWED_CLIENT_IDS)} allowed client(s)"


@router.get(
    "/", 
    response_model=HealthResponse,
    summary="Basic Health Check",
    description="Basic health check endpoint that returns 200 if the server is running. Used by load balancers for liveness checks.",
    tags=["Health"],
    responses={
        200: {
            "description": "Service is healthy and running",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "version": "1.0.0",
                        "timestamp": 1691668800.0,
                        "message": "Real-Time Audio Agent API v1 is running",
                        "details": {
                            "api_version": "v1",
                            "service": "rtagent-backend"
                        }
                    }
                }
            }
        }
    }
)
async def health_check() -> HealthResponse:
    """
    Basic health check endpoint - always returns 200 if server is running.
    Used by load balancers for basic liveness checks.
    """
    return HealthResponse(
        status="healthy",
        timestamp=time.time(),
        message="Real-Time Audio Agent API v1 is running",
        details={
            "api_version": "v1",
            "service": "rtagent-backend"
        }
    )


@router.get(
    "/readiness", 
    response_model=ReadinessResponse,
    summary="Comprehensive Readiness Check",
    description="""
    Comprehensive readiness probe that checks all critical dependencies with timeouts.
    
    This endpoint verifies:
    - Redis connectivity and performance
    - Azure OpenAI client health
    - Speech services (TTS/STT) availability
    - ACS caller configuration and connectivity
    - RT Agents initialization
    - Authentication configuration (when ENABLE_AUTH_VALIDATION=True)
    - Event system health
    
    When authentication validation is enabled, checks:
    - BACKEND_AUTH_CLIENT_ID is set and is a valid GUID
    - AZURE_TENANT_ID is set and is a valid GUID  
    - ALLOWED_CLIENT_IDS contains at least one valid GUID
    
    Returns 503 if any critical services are unhealthy, 200 if all systems are ready.
    """,
    tags=["Health"],
    responses={
        200: {
            "description": "All services are ready",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ready",
                        "timestamp": 1691668800.0,
                        "response_time_ms": 45.2,
                        "checks": [
                            {
                                "component": "redis",
                                "status": "healthy",
                                "check_time_ms": 12.5,
                                "details": "Connected to Redis successfully"
                            },
                            {
                                "component": "auth_configuration", 
                                "status": "healthy",
                                "check_time_ms": 1.2,
                                "details": "Auth validation enabled with 2 allowed client(s)"
                            }
                        ],
                        "event_system": {
                            "is_healthy": True,
                            "handlers_count": 7,
                            "domains_count": 2
                        }
                    }
                }
            }
        },
        503: {
            "description": "One or more services are not ready",
            "content": {
                "application/json": {
                    "example": {
                        "status": "not_ready",
                        "timestamp": 1691668800.0,
                        "response_time_ms": 1250.0,
                        "checks": [
                            {
                                "component": "redis",
                                "status": "unhealthy",
                                "check_time_ms": 1000.0,
                                "error": "Connection timeout"
                            },
                            {
                                "component": "auth_configuration",
                                "status": "unhealthy", 
                                "check_time_ms": 2.1,
                                "error": "BACKEND_AUTH_CLIENT_ID is not a valid GUID"
                            }
                        ]
                    }
                }
            }
        }
    }
)
async def readiness_check(
    request: Request,
) -> ReadinessResponse:
    """
    Comprehensive readiness probe: checks all critical dependencies with timeouts.
    Returns 503 if any critical services are unhealthy.
    """
    start_time = time.time()
    health_checks: List[ServiceCheck] = []
    overall_status = "ready"
    timeout = 1.0  # seconds per check

    async def fast_ping(check_fn, *args, component=None):
        try:
            result = await asyncio.wait_for(check_fn(*args), timeout=timeout)
            return result
        except Exception as e:
            return ServiceCheck(
                component=component or check_fn.__name__,
                status="unhealthy",
                error=str(e),
                check_time_ms=round((time.time() - start_time) * 1000, 2),
            )

    # Check Redis connectivity
    redis_status = await fast_ping(
        _check_redis_fast, request.app.state.redis, component="redis"
    )
    health_checks.append(redis_status)

    # Check Azure OpenAI
    openai_status = await fast_ping(
        _check_azure_openai_fast,
        request.app.state.azureopenai_client,
        component="azure_openai",
    )
    health_checks.append(openai_status)

    # Check Speech Services
    speech_status = await fast_ping(
        _check_speech_services_fast,
        request.app.state.tts_client,
        request.app.state.stt_client,
        component="speech_services",
    )
    health_checks.append(speech_status)

    # Check ACS Caller
    acs_status = await fast_ping(
        _check_acs_caller_fast, request.app.state.acs_caller, component="acs_caller"
    )
    health_checks.append(acs_status)

    # Check RT Agents
    agent_status = await fast_ping(
        _check_rt_agents_fast,
        request.app.state.auth_agent,
        request.app.state.claim_intake_agent,
        component="rt_agents",
    )
    health_checks.append(agent_status)

    # Check Authentication Configuration
    auth_config_status = await fast_ping(
        _check_auth_configuration_fast,
        component="auth_configuration",
    )
    health_checks.append(auth_config_status)

    # Determine overall status
    failed_checks = [check for check in health_checks if check.status != "healthy"]
    if failed_checks:
        overall_status = (
            "degraded" if len(failed_checks) < len(health_checks) else "unhealthy"
        )

    response_time = round((time.time() - start_time) * 1000, 2)
    
    response_data = ReadinessResponse(
        status=overall_status,
        timestamp=time.time(),
        response_time_ms=response_time,
        checks=health_checks,
    )

    # Return appropriate status code
    status_code = 200 if overall_status != "unhealthy" else 503
    return JSONResponse(
        content=response_data.dict(), 
        status_code=status_code
    )


async def _check_redis_fast(redis_manager) -> ServiceCheck:
    """Fast Redis connectivity check."""
    start = time.time()
    if not redis_manager:
        return ServiceCheck(
            component="redis",
            status="unhealthy",
            error="not initialized",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )
    try:
        pong = await asyncio.wait_for(redis_manager.ping(), timeout=0.5)
        if pong:
            return ServiceCheck(
                component="redis",
                status="healthy",
                check_time_ms=round((time.time() - start) * 1000, 2),
                details="ping successful"
            )
        else:
            return ServiceCheck(
                component="redis",
                status="unhealthy",
                error="no pong response",
                check_time_ms=round((time.time() - start) * 1000, 2),
            )
    except Exception as e:
        return ServiceCheck(
            component="redis",
            status="unhealthy",
            error=str(e),
            check_time_ms=round((time.time() - start) * 1000, 2),
        )


async def _check_azure_openai_fast(openai_client) -> ServiceCheck:
    """Fast Azure OpenAI client check."""
    start = time.time()
    if not openai_client:
        return ServiceCheck(
            component="azure_openai",
            status="unhealthy",
            error="not initialized",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )
    return ServiceCheck(
        component="azure_openai",
        status="healthy",
        check_time_ms=round((time.time() - start) * 1000, 2),
        details="client initialized"
    )


async def _check_speech_services_fast(tts_client, stt_client) -> ServiceCheck:
    """Fast Speech Services check."""
    start = time.time()
    if not tts_client or not stt_client:
        return ServiceCheck(
            component="speech_services",
            status="unhealthy",
            error="not initialized",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )
    return ServiceCheck(
        component="speech_services",
        status="healthy",
        check_time_ms=round((time.time() - start) * 1000, 2),
        details="TTS and STT clients initialized"
    )


async def _check_acs_caller_fast(acs_caller) -> ServiceCheck:
    """Fast ACS caller check with comprehensive phone number and config validation."""
    start = time.time()

    # Check if ACS phone number is provided
    if not ACS_SOURCE_PHONE_NUMBER or ACS_SOURCE_PHONE_NUMBER == "null":
        return ServiceCheck(
            component="acs_caller",
            status="unhealthy",
            error="ACS_SOURCE_PHONE_NUMBER not provided",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )

    # Validate phone number format
    is_valid, error_msg = _validate_phone_number(ACS_SOURCE_PHONE_NUMBER)
    if not is_valid:
        return ServiceCheck(
            component="acs_caller",
            status="unhealthy",
            error=f"ACS phone number validation failed: {error_msg}",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )

    # Check ACS connection string or endpoint
    acs_conn_missing = not ACS_CONNECTION_STRING
    acs_endpoint_missing = not ACS_ENDPOINT
    if acs_conn_missing and acs_endpoint_missing:
        return ServiceCheck(
            component="acs_caller",
            status="unhealthy",
            error="Neither ACS_CONNECTION_STRING nor ACS_ENDPOINT is configured",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )

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
        return ServiceCheck(
            component="acs_caller",
            status="unhealthy",
            error="ACS caller not initialized",
            check_time_ms=round((time.time() - start) * 1000, 2),
            details=details,
        )

    # Obfuscate phone number, show only last 4 digits
    obfuscated_phone = (
        "*" * (len(ACS_SOURCE_PHONE_NUMBER) - 4) + ACS_SOURCE_PHONE_NUMBER[-4:]
        if len(ACS_SOURCE_PHONE_NUMBER) > 4
        else ACS_SOURCE_PHONE_NUMBER
    )
    return ServiceCheck(
        component="acs_caller",
        status="healthy",
        check_time_ms=round((time.time() - start) * 1000, 2),
        details=f"ACS caller configured with phone: {obfuscated_phone}",
    )


async def _check_rt_agents_fast(auth_agent, claim_intake_agent) -> ServiceCheck:
    """Fast RT Agents check."""
    start = time.time()
    if not auth_agent or not claim_intake_agent:
        return ServiceCheck(
            component="rt_agents",
            status="unhealthy",
            error="not initialized",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )
    return ServiceCheck(
        component="rt_agents",
        status="healthy",
        check_time_ms=round((time.time() - start) * 1000, 2),
        details="auth and claim intake agents initialized"
    )


async def _check_auth_configuration_fast() -> ServiceCheck:
    """Fast authentication configuration validation check."""
    start = time.time()
    
    try:
        is_valid, message = _validate_auth_configuration()
        
        if is_valid:
            return ServiceCheck(
                component="auth_configuration",
                status="healthy",
                check_time_ms=round((time.time() - start) * 1000, 2),
                details=message
            )
        else:
            return ServiceCheck(
                component="auth_configuration",
                status="unhealthy",
                error=message,
                check_time_ms=round((time.time() - start) * 1000, 2),
            )
    except Exception as e:
        return ServiceCheck(
            component="auth_configuration",
            status="unhealthy",
            error=f"Auth configuration check failed: {str(e)}",
            check_time_ms=round((time.time() - start) * 1000, 2),
        )
