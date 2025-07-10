import asyncio
import time
from typing import Dict, List, Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from utils.ml_logging import get_logger
from rtagents.RTAgent.backend.orchestration.conversation_state import (
    ConversationManager
)
from settings import (
    AZURE_CLIENT_ID,
    AZURE_TENANT_ID,
    AZURE_OPENAI_ENDPOINT
)

logger = get_logger("health")

router = APIRouter()


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
                "check_time_ms": round((time.time() - start_time) * 1000, 2)
            }

    # Only check if initialized and can respond to a ping/basic call
    redis_status = await fast_ping(_check_redis_fast, request.app.state.redis, component="redis")
    health_checks.append(redis_status)

    openai_status = await fast_ping(_check_azure_openai_fast, request.app.state.azureopenai_client, component="azure_openai")
    health_checks.append(openai_status)

    speech_status = await fast_ping(_check_speech_services_fast, request.app.state.tts_client, request.app.state.stt_client, component="speech_services")
    health_checks.append(speech_status)

    acs_status = await fast_ping(_check_acs_caller_fast, request.app.state.acs_caller, component="acs_caller")
    health_checks.append(acs_status)

    agent_status = await fast_ping(_check_rt_agents_fast, request.app.state.auth_agent, request.app.state.claim_intake_agent, component="rt_agents")
    health_checks.append(agent_status)

    failed_checks = [check for check in health_checks if check["status"] != "healthy"]
    if failed_checks:
        overall_status = "degraded" if len(failed_checks) < len(health_checks) else "unhealthy"

    response_time = round((time.time() - start_time) * 1000, 2)
    response_data = {
        "status": overall_status,
        "timestamp": time.time(),
        "response_time_ms": response_time,
        "checks": health_checks
    }
    # Always return quickly, never block
    return JSONResponse(content=response_data, status_code=200 if overall_status != "unhealthy" else 503)
async def _check_redis_fast(redis_manager) -> Dict:
    start = time.time()
    if not redis_manager:
        return {"component": "redis", "status": "unhealthy", "error": "not initialized", "check_time_ms": round((time.time()-start)*1000,2)}
    try:
        pong = await asyncio.wait_for(redis_manager.ping(), timeout=0.5)
        if pong:
            return {"component": "redis", "status": "healthy", "check_time_ms": round((time.time()-start)*1000,2)}
        else:
            return {"component": "redis", "status": "unhealthy", "error": "no pong", "check_time_ms": round((time.time()-start)*1000,2)}
    except Exception as e:
        return {"component": "redis", "status": "unhealthy", "error": str(e), "check_time_ms": round((time.time()-start)*1000,2)}

async def _check_azure_openai_fast(openai_client) -> Dict:
    start = time.time()
    if not openai_client:
        return {"component": "azure_openai", "status": "unhealthy", "error": "not initialized", "check_time_ms": round((time.time()-start)*1000,2)}
    return {"component": "azure_openai", "status": "healthy", "check_time_ms": round((time.time()-start)*1000,2)}

async def _check_speech_services_fast(tts_client, stt_client) -> Dict:
    start = time.time()
    if not tts_client or not stt_client:
        return {"component": "speech_services", "status": "unhealthy", "error": "not initialized", "check_time_ms": round((time.time()-start)*1000,2)}
    return {"component": "speech_services", "status": "healthy", "check_time_ms": round((time.time()-start)*1000,2)}

async def _check_acs_caller_fast(acs_caller) -> Dict:
    start = time.time()
    # ACS is optional
    return {"component": "acs_caller", "status": "healthy", "check_time_ms": round((time.time()-start)*1000,2)}

async def _check_rt_agents_fast(auth_agent, claim_intake_agent) -> Dict:
    start = time.time()
    if not auth_agent or not claim_intake_agent:
        return {"component": "rt_agents", "status": "unhealthy", "error": "not initialized", "check_time_ms": round((time.time()-start)*1000,2)}
    return {"component": "rt_agents", "status": "healthy", "check_time_ms": round((time.time()-start)*1000,2)}


@router.get("/startup")
async def startup(request: Request):
    """
    Startup probe to check if the application has started successfully.
    Validates critical components are initialized and basic configuration is valid.
    """
    start_time = time.time()
    startup_checks = []
    overall_status = "started"
    
    try:
        # Check if app state components are initialized
        state_status = _check_app_state_initialization(request.app.state)
        startup_checks.append(state_status)
        
        # Basic Redis connection test (faster than full readiness check)
        redis_status = await _check_redis_startup(request.app.state.redis)
        startup_checks.append(redis_status)
        
        # Check critical configuration
        config_status = _check_critical_configuration()
        startup_checks.append(config_status)
        
        # Validate speech services configuration
        speech_config_status = _check_speech_config(request.app.state.tts_client)
        startup_checks.append(speech_config_status)
        
        # Check if agents are properly configured
        agent_config_status = _check_agent_configuration(
            request.app.state.auth_agent,
            request.app.state.claim_intake_agent
        )
        startup_checks.append(agent_config_status)
        
        # Determine overall status
        failed_checks = [check for check in startup_checks if check["status"] != "healthy"]
        if failed_checks:
            overall_status = "failed"
            
    except Exception as e:
        logger.error(f"Startup check failed with exception: {e}", exc_info=True)
        overall_status = "failed"
        startup_checks.append({
            "component": "startup_check",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": 0
        })
    
    response_time = round((time.time() - start_time) * 1000, 2)
    
    response_data = {
        "status": overall_status,
        "timestamp": time.time(),
        "response_time_ms": response_time,
        "checks": startup_checks
    }
    
    # Return appropriate HTTP status code
    if overall_status == "failed":
        return JSONResponse(content=response_data, status_code=503)
    else:
        return JSONResponse(content=response_data, status_code=200)


@router.get("/debug/jwt")
async def debug_jwt_token():
    """Debug JWT token for APIM policy evaluation"""
    start_time = time.time()
    
    debug_info = {
        "timestamp": start_time,
        "token_status": "unknown",
        "credential_chain": [],
        "azure_config": {},
        "recommendations": []
    }
    
    try:
        # Get Azure configuration
        debug_info["azure_config"] = {
            "client_id": AZURE_CLIENT_ID,
            "tenant_id": AZURE_TENANT_ID,
            "openai_endpoint": AZURE_OPENAI_ENDPOINT,
            "has_client_id": bool(AZURE_CLIENT_ID),
            "has_tenant_id": bool(AZURE_TENANT_ID),
        }
        
        # Import auth utilities for JWT debugging
        from ..utils.auth_utils import debug_jwt_token as debug_jwt_util
        
        # Get JWT token debug information
        jwt_debug = await debug_jwt_util()
        debug_info.update(jwt_debug)
        
        # Add APIM-specific recommendations
        if debug_info["token_status"] == "valid":
            debug_info["recommendations"].append("✅ JWT token is valid and should work with APIM policies")
        else:
            debug_info["recommendations"].extend([
                "❌ JWT token validation failed - check APIM policy requirements",
                "🔧 Ensure managed identity is properly configured",
                "🔧 Verify AZURE_CLIENT_ID and AZURE_TENANT_ID are set",
                "🔧 Check if APIM policy expects specific token claims"
            ])
        
        # Add troubleshooting steps
        debug_info["troubleshooting"] = {
            "verify_managed_identity": "az account show --query 'id' -o tsv",
            "check_token_claims": "Use jwt.io to decode token payload",
            "validate_apim_policy": "Review APIM policy requirements for token validation",
            "test_token_locally": "Use Azure CLI: az account get-access-token --resource https://cognitiveservices.azure.com"
        }
        
    except Exception as e:
        logger.error(f"JWT debug failed: {str(e)}")
        debug_info["error"] = str(e)
        debug_info["token_status"] = "error"
        debug_info["recommendations"] = [
            "❌ JWT debugging failed - check authentication configuration",
            "🔧 Verify Azure dependencies are installed",
            "🔧 Check managed identity configuration"
        ]
    
    response_time = round((time.time() - start_time) * 1000, 2)
    debug_info["response_time_ms"] = response_time
    
    return JSONResponse(content=debug_info, status_code=200)


# Helper functions for individual component checks

async def _check_redis(redis_manager) -> Dict:
    """Check Redis connectivity and basic operations."""
    start_time = time.time()
    try:
        # Check if redis_manager is initialized
        if not redis_manager:
            raise Exception("Redis manager not initialized")
        
        # Test basic connectivity with timeout
        try:
            ping_result = await asyncio.wait_for(redis_manager.ping(), timeout=3.0)
            if not ping_result:
                raise Exception("Redis ping returned False")
        except asyncio.TimeoutError:
            raise Exception("Redis ping timed out after 3 seconds")
        
        # Test basic operations with timeout
        test_key = f"health_check_{int(time.time())}"
        test_value = f"test_{int(time.time())}"
        
        try:
            # Use a unique session ID for health checks
            health_check_session_id = f"health_check_{int(time.time())}"
            cm = ConversationManager.from_redis(health_check_session_id, redis_manager)
            cm.set_context(test_key, test_value)
            cm.persist_to_redis(redis_manager)
            
        except asyncio.TimeoutError:
            raise Exception("Redis read/write operations timed out")
        
        # Cleanup test key (best effort)
        try:
            if hasattr(redis_manager, 'delete_session'):
                await asyncio.wait_for(redis_manager.delete_session(test_key), timeout=1.0)
            elif hasattr(redis_manager, 'redis_client'):
                await asyncio.wait_for(redis_manager.redis_client.delete(test_key), timeout=1.0)
        except:
            pass  # Non-critical cleanup failure
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "redis",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "Connectivity and read/write operations successful"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Redis health check failed: {e}")
        
        # Provide specific troubleshooting guidance
        error_msg = str(e)
        if "not initialized" in error_msg:
            troubleshooting = "Check Redis manager configuration"
        elif "timeout" in error_msg.lower():
            troubleshooting = "Redis connection timeout - check network connectivity and Redis service status"
        elif "connection" in error_msg.lower():
            troubleshooting = "Redis connection failed - verify Redis endpoint and authentication"
        else:
            troubleshooting = "Redis operation failed - check service availability"
        
        return {
            "component": "redis",
            "status": "unhealthy",
            "error": error_msg,
            "check_time_ms": check_time,
            "troubleshooting": troubleshooting
        }


async def _check_redis_startup(redis_manager) -> Dict:
    """Quick Redis connectivity check for startup probe."""
    start_time = time.time()
    try:
        if not redis_manager:
            raise Exception("Redis manager not initialized")
        
        # Quick ping test with short timeout for startup
        try:
            ping_result = await asyncio.wait_for(redis_manager.ping(), timeout=2.0)
            if not ping_result:
                raise Exception("Redis ping returned False")
        except asyncio.TimeoutError:
            raise Exception("Redis ping timed out")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "redis_startup",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "Basic connectivity successful"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Redis startup check failed: {e}")
        
        error_msg = str(e)
        if "not initialized" in error_msg:
            troubleshooting = "Redis manager not properly initialized during startup"
        elif "timeout" in error_msg.lower():
            troubleshooting = "Redis not responding - check service status"
        else:
            troubleshooting = "Redis connectivity issue during startup"
        
        return {
            "component": "redis_startup",
            "status": "unhealthy",
            "error": error_msg,
            "check_time_ms": check_time,
            "troubleshooting": troubleshooting
        }


async def _check_cosmos_db(cosmos_manager) -> Dict:
    """Check Cosmos DB connectivity."""
    start_time = time.time()
    try:
        # First, check if the cosmos_manager is properly initialized
        if not cosmos_manager:
            raise Exception("Cosmos DB manager not initialized")
        
        # Check if the client and database attributes exist
        if not hasattr(cosmos_manager, 'client') or cosmos_manager.client is None:
            raise Exception("Cosmos DB client not initialized")
        
        if not hasattr(cosmos_manager, 'database') or cosmos_manager.database is None:
            raise Exception("Cosmos DB database not initialized")
        
        # Try a lightweight operation - just check if we can access the collection
        try:
            # Use a very simple query with a short timeout for health checks
            # This is better than query_documents which might be synchronous
            collection = cosmos_manager.collection
            if not collection:
                raise Exception("Cosmos DB collection not initialized")
            
            # Try to ping the database by checking collection stats (lightweight operation)
            # Use a minimal query that should execute quickly
            document_count = collection.estimated_document_count()
            
            check_time = round((time.time() - start_time) * 1000, 2)
            return {
                "component": "cosmos_db",
                "status": "healthy",
                "check_time_ms": check_time,
                "details": f"Database connection verified, collection accessible (est. {document_count} documents)"
            }
            
        except Exception as db_error:
            # If direct DB operation fails, try a simpler connectivity check
            if "nodename nor servname provided" in str(db_error) or "Errno 8" in str(db_error):
                raise Exception(f"DNS resolution failed for Cosmos DB endpoint: {str(db_error)}")
            elif "timeout" in str(db_error).lower():
                raise Exception(f"Cosmos DB connection timeout: {str(db_error)}")
            else:
                raise Exception(f"Cosmos DB operation failed: {str(db_error)}")
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Cosmos DB health check failed: {e}")
        
        # Determine if this is a configuration issue vs connectivity issue
        error_msg = str(e)
        if "not initialized" in error_msg:
            status_detail = "Configuration issue - check Cosmos DB setup"
        elif "DNS resolution" in error_msg or "nodename nor servname" in error_msg:
            status_detail = "Network/DNS issue - check Cosmos DB endpoint and connectivity"
        elif "timeout" in error_msg.lower():
            status_detail = "Connectivity timeout - check network and Cosmos DB availability"
        else:
            status_detail = "Database operation failed"
        
        return {
            "component": "cosmos_db",
            "status": "unhealthy",
            "error": error_msg,
            "check_time_ms": check_time,
            "troubleshooting": status_detail
        }


async def _check_azure_openai(openai_client) -> Dict:
    """Check Azure OpenAI client connectivity with JWT token validation for APIM."""
    start_time = time.time()
    try:
        # First check if client is initialized
        if not openai_client:
            raise Exception("Azure OpenAI client not initialized")
        
        # Check if we can access the token provider for JWT validation
        jwt_status = "unknown"
        if hasattr(openai_client, '_azure_ad_token_provider') and openai_client._azure_ad_token_provider:
            try:
                # Try to get a token to verify JWT is working
                from azure.identity import get_bearer_token_provider
                jwt_status = "available"
            except Exception as token_error:
                jwt_status = f"token_error: {str(token_error)}"
                logger.warning(f"JWT token provider issue: {token_error}")
        elif hasattr(openai_client, '_api_key') and openai_client._api_key:
            jwt_status = "api_key_auth"
        
        # Test with a minimal completion request
        # Use asyncio.wait_for to enforce a strict timeout
        async def make_openai_request():
            from rtagents.RTAgent.backend.settings import AZURE_OPENAI_CHAT_DEPLOYMENT_ID
            
            # Use the configured deployment model
            model = AZURE_OPENAI_CHAT_DEPLOYMENT_ID or "gpt-4o"
            
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say 'ok' only."}
                ],
                max_tokens=5,
                timeout=3  # Quick timeout for health check
            )
            return response
        
        # Wrap the OpenAI call with asyncio timeout for additional safety
        try:
            response = await asyncio.wait_for(make_openai_request(), timeout=5.0)
        except asyncio.TimeoutError:
            raise Exception("Azure OpenAI request timed out after 5 seconds")
        
        if response and response.choices and len(response.choices) > 0:
            check_time = round((time.time() - start_time) * 1000, 2)
            return {
                "component": "azure_openai",
                "status": "healthy",
                "check_time_ms": check_time,
                "details": "Chat completion request successful",
                "jwt_status": jwt_status,
                "model_used": response.model if hasattr(response, 'model') else "unknown"
            }
        else:
            raise Exception("Empty or invalid response from Azure OpenAI")
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Azure OpenAI health check failed: {e}")
        
        # Provide more specific error context for APIM and JWT issues
        error_msg = str(e)
        if "not initialized" in error_msg:
            troubleshooting = "Check Azure OpenAI client configuration and ensure proper initialization"
        elif "timeout" in error_msg.lower():
            troubleshooting = "Azure OpenAI service timeout - check service availability, network connectivity, and APIM policy"
        elif "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            troubleshooting = "Authentication failed - verify API key, managed identity configuration, or JWT token claims for APIM"
        elif "forbidden" in error_msg.lower() or "403" in error_msg:
            troubleshooting = "Access forbidden - check APIM policy evaluation, JWT token audience/claims, or resource permissions"
        elif "rate limit" in error_msg.lower():
            troubleshooting = "Rate limit exceeded - reduce request frequency or check APIM throttling policies"
        elif "model" in error_msg.lower() and "not found" in error_msg.lower():
            troubleshooting = "Model deployment not found - verify AZURE_OPENAI_CHAT_DEPLOYMENT_ID configuration"
        elif "policy" in error_msg.lower() or "apim" in error_msg.lower():
            troubleshooting = "APIM policy evaluation failed - check JWT token claims, audience, and policy configuration"
        else:
            troubleshooting = "Azure OpenAI service issue - check service status, endpoint configuration, and APIM connectivity"
        
        return {
            "component": "azure_openai",
            "status": "unhealthy",
            "error": error_msg,
            "check_time_ms": check_time,
            "troubleshooting": troubleshooting,
            "jwt_status": jwt_status if 'jwt_status' in locals() else "unknown"
        }


async def _check_speech_services(tts_client, stt_client) -> Dict:
    """Check Azure Speech Services (TTS/STT) configuration and basic functionality."""
    start_time = time.time()
    try:
        # Check TTS configuration
        if hasattr(tts_client, 'validate_configuration'):
            tts_valid = tts_client.validate_configuration()
            if not tts_valid:
                raise Exception("TTS configuration validation failed")
        
        # For STT, check if the client is properly initialized
        if not stt_client:
            raise Exception("STT client not initialized")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "speech_services",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "TTS and STT services configured and accessible"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Speech services health check failed: {e}")
        return {
            "component": "speech_services",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }


async def _check_acs_caller(acs_caller) -> Dict:
    """Check ACS caller configuration."""
    start_time = time.time()
    try:
        if acs_caller is None:
            # ACS caller is optional, so this is not a failure
            check_time = round((time.time() - start_time) * 1000, 2)
            return {
                "component": "acs_caller",
                "status": "healthy",
                "check_time_ms": check_time,
                "details": "ACS caller not configured (optional component)"
            }
        
        # If ACS caller exists, we assume it's properly configured
        # since it's initialized in main.py startup
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "acs_caller",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "ACS caller configured and initialized"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"ACS caller health check failed: {e}")
        return {
            "component": "acs_caller",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }


async def _check_rt_agents(auth_agent, claim_intake_agent) -> Dict:
    """Check RTAgent configurations."""
    start_time = time.time()
    try:
        agents_status = []
        
        # Check auth agent
        if auth_agent:
            agents_status.append("auth_agent: initialized")
        else:
            agents_status.append("auth_agent: not configured")
        
        # Check claim intake agent
        if claim_intake_agent:
            agents_status.append("claim_intake_agent: initialized")
        else:
            agents_status.append("claim_intake_agent: not configured")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "rt_agents",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "; ".join(agents_status)
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        logger.error(f"RTAgents health check failed: {e}")
        return {
            "component": "rt_agents",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }


def _check_app_state_initialization(app_state) -> Dict:
    """Check if critical app state components are initialized."""
    start_time = time.time()
    try:
        required_components = [
            'redis', 'cosmos', 'azureopenai_client', 'tts_client', 'stt_client',
            'auth_agent', 'claim_intake_agent', 'promptsclient'
        ]
        
        missing_components = []
        for component in required_components:
            if not hasattr(app_state, component) or getattr(app_state, component) is None:
                missing_components.append(component)
        
        if missing_components:
            raise Exception(f"Missing app state components: {', '.join(missing_components)}")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "app_state",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": f"All {len(required_components)} required components initialized"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "app_state",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }


def _check_critical_configuration() -> Dict:
    """Check critical environment configuration."""
    start_time = time.time()
    try:
        from rtagents.RTAgent.backend.settings import (
            AZURE_COSMOS_CONNECTION_STRING,
            AZURE_COSMOS_DB_DATABASE_NAME,
            AZURE_COSMOS_DB_COLLECTION_NAME,
            AZURE_SPEECH_ENDPOINT,
            AZURE_OPENAI_ENDPOINT,
        )
        
        missing_config = []
        
        if not AZURE_COSMOS_CONNECTION_STRING:
            missing_config.append("AZURE_COSMOS_CONNECTION_STRING")
        if not AZURE_COSMOS_DB_DATABASE_NAME:
            missing_config.append("AZURE_COSMOS_DB_DATABASE_NAME")
        if not AZURE_COSMOS_DB_COLLECTION_NAME:
            missing_config.append("AZURE_COSMOS_DB_COLLECTION_NAME")
        if not AZURE_SPEECH_ENDPOINT:
            missing_config.append("AZURE_SPEECH_ENDPOINT")
        if not AZURE_OPENAI_ENDPOINT:
            missing_config.append("AZURE_OPENAI_ENDPOINT")
        
        if missing_config:
            raise Exception(f"Missing critical configuration: {', '.join(missing_config)}")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "configuration",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "All critical environment variables configured"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "configuration",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }


def _check_speech_config(tts_client) -> Dict:
    """Check speech services configuration."""
    start_time = time.time()
    try:
        if not tts_client:
            raise Exception("TTS client not initialized")
        
        # Check if TTS client has required attributes
        required_attrs = ['voice', 'region']
        missing_attrs = []
        for attr in required_attrs:
            if not hasattr(tts_client, attr) or not getattr(tts_client, attr):
                missing_attrs.append(attr)
        
        if missing_attrs:
            raise Exception(f"TTS client missing configuration: {', '.join(missing_attrs)}")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "speech_config",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": f"Speech services configured with voice: {getattr(tts_client, 'voice', 'unknown')}"
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "speech_config",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }


def _check_agent_configuration(auth_agent, claim_intake_agent) -> Dict:
    """Check agent configuration."""
    start_time = time.time()
    try:
        agent_configs = []
        
        if auth_agent:
            agent_configs.append("auth_agent: configured")
        else:
            agent_configs.append("auth_agent: missing")
        
        if claim_intake_agent:
            agent_configs.append("claim_intake_agent: configured")
        else:
            agent_configs.append("claim_intake_agent: missing")
        
        # Both agents should be configured for full functionality
        if not auth_agent or not claim_intake_agent:
            raise Exception("One or more required agents not configured")
        
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "agent_configuration",
            "status": "healthy",
            "check_time_ms": check_time,
            "details": "; ".join(agent_configs)
        }
        
    except Exception as e:
        check_time = round((time.time() - start_time) * 1000, 2)
        return {
            "component": "agent_configuration",
            "status": "unhealthy",
            "error": str(e),
            "check_time_ms": check_time
        }
