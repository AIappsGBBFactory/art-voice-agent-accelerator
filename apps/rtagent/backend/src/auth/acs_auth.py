# from fastapi import Request, WebSocket, HTTPException
# from .shared import validate_jwt_token
# from settings import ACS_JWKS_URL, ACS_ISSUER, ACS_AUDIENCE

# class ACSAuthError(Exception):
#     """ACS authentication error."""
#     pass
# def validate_acs_http_auth(auth_header: str) -> dict:
#     if not auth_header or not auth_header.startswith("Bearer "):
#         raise HTTPException(401, "Missing/invalid Authorization header")
#     token = auth_header.split()[1]
#     return validate_jwt_token(token, ACS_JWKS_URL, ACS_ISSUER, ACS_AUDIENCE)

# async def validate_acs_ws_auth(ws: WebSocket) -> dict:
#     auth_header = ws.headers.get("Authorization")
#     if not auth_header or not auth_header.startswith("Bearer "):
#         await ws.close(code=1008)
#         raise HTTPException(401, "Missing/invalid WebSocket auth header")
#     token = auth_header.split()[1]
#     return validate_jwt_token(token, ACS_JWKS_URL, ACS_ISSUER, ACS_AUDIENCE)



"""
auth/acs_auth.py
=========================
Simple Azure Communication Services (ACS) JWT authentication.
"""

import jwt
from fastapi import HTTPException, WebSocket, Request
from fastapi.websockets import WebSocketState
from utils.ml_logging import get_logger
from apps.rtagent.backend.settings import (
    ACS_JWKS_URL,
    ACS_ISSUER,
    ACS_AUDIENCE
)
logger = get_logger("orchestration.acs_auth")

import base64
import json

def get_easyauth_identity(request: Request) -> dict:
    encoded = request.headers.get("x-ms-client-principal")
    if not encoded:
        raise HTTPException(status_code=401, detail="Missing EasyAuth headers")

    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        principal = json.loads(decoded)
        return principal
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid EasyAuth header encoding")
    
class ACSAuthError(Exception):
    """ACS authentication error."""
    pass

def validate_jwt_token(
    token: str,
    jwks_url: str = ACS_JWKS_URL,
    issuer: str = ACS_ISSUER,
    audience: str = ACS_AUDIENCE
) -> dict:
    """Validate JWT token against ACS JWKS."""
    try:
        jwks_client = jwt.PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
        )
    except jwt.InvalidTokenError as e:
        raise ACSAuthError(f"Invalid token: {e}")
    except Exception as e:
        raise ACSAuthError(f"Token validation failed: {e}")


def validate_http_auth(
    authorization_header: str,
    jwks_url: str = ACS_JWKS_URL,
    issuer: str = ACS_ISSUER,
    audience: str = ACS_AUDIENCE
) -> dict:
    """Validate HTTP authorization header."""
    if not authorization_header:
        raise HTTPException(401, "Authorization header missing")
    
    if not authorization_header.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization format")
    
    try:
        token = authorization_header.split()[1]
        decoded = validate_jwt_token(token, jwks_url, issuer, audience)
        logger.info("HTTP request authenticated")
        return decoded
    except ACSAuthError as e:
        if "Invalid token" in str(e):
            raise HTTPException(401, "Invalid token")
        raise HTTPException(500, "Authentication failed")


async def validate_websocket_auth(
    ws: WebSocket,
    jwks_url: str = ACS_JWKS_URL,
    issuer: str = ACS_ISSUER,
    audience: str = ACS_AUDIENCE
) -> dict:
    """Validate WebSocket authorization header."""
    auth_header = ws.headers.get("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("WebSocket: Missing or invalid auth header")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1008)
        raise ACSAuthError("Missing or invalid authorization header")
    
    try:
        token = auth_header.split()[1]
        decoded = validate_jwt_token(token, jwks_url, issuer, audience)
        logger.info("WebSocket authenticated")
        return decoded
    except ACSAuthError as e:
        logger.error(f"WebSocket auth failed: {e}")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1011)
        raise
