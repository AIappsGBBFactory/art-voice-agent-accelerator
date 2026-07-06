"""
auth/acs_auth.py
=========================
Unified authentication for Azure Communication Services (ACS) and Entra ID.
"""

import base64
import json
from functools import cache
from typing import Any

import httpx
import jwt
from config import (
    ACS_AUDIENCE,
    ACS_ISSUER,
    ACS_JWKS_URL,
    ALLOWED_CLIENT_IDS,
    ENTRA_AUDIENCE,
    ENTRA_ISSUER,
    ENTRA_JWKS_URL,
)
from fastapi import HTTPException, Request, WebSocket
from fastapi.websockets import WebSocketState
from utils.ml_logging import get_logger

logger = get_logger("orchestration.acs_auth")


class AuthError(Exception):
    """Generic authentication error."""

    pass


@cache
def get_jwks(jwks_url: str) -> list[dict]:
    resp = httpx.get(jwks_url)
    return resp.json()["keys"]


def validate_jwt_token(token: str, jwks_url: str, issuer: str, audience: str) -> dict:
    """Validates JWT using provided JWKS, issuer, and audience."""
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
        raise AuthError(f"Invalid token: {e}")
    except Exception as e:
        raise AuthError(f"Token validation failed: {e}")


def extract_bearer_token(authorization_header: str) -> str:
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    return authorization_header.split(" ")[1]


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


# ---------------------------------------------------------------------------
# EasyAuth identity extraction (non-raising, telemetry-friendly)
# ---------------------------------------------------------------------------

# AAD / EasyAuth claim types that carry the stable object id and the email/UPN.
_OID_CLAIM_TYPES: tuple[str, ...] = (
    "http://schemas.microsoft.com/identity/claims/objectidentifier",
    "oid",
)
_EMAIL_CLAIM_TYPES: tuple[str, ...] = (
    "preferred_username",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "emails",
    "email",
    "upn",
    "http://schemas.microsoft.com/identity/claims/upn",
)


def parse_easyauth_principal(encoded: str | None) -> dict | None:
    """Decode a base64 ``x-ms-client-principal`` header into a principal dict.

    Returns None on any error (missing/invalid header) rather than raising, so
    it is safe to call on unauthenticated requests and WebSocket handshakes.
    """
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def _claim_value(principal: dict, claim_types: tuple[str, ...]) -> str | None:
    """Return the first matching claim value from an EasyAuth principal."""
    by_type: dict[str, str] = {}
    for claim in principal.get("claims") or []:
        typ = claim.get("typ") or claim.get("type")
        val = claim.get("val") or claim.get("value")
        if typ and val and typ not in by_type:
            by_type[typ] = val
    for claim_type in claim_types:
        if claim_type in by_type:
            return by_type[claim_type]
    return None


def extract_client_identity(
    headers: Any,
    fallback_id: str | None = None,
    fallback_email: str | None = None,
) -> tuple[str | None, str | None]:
    """Best-effort ``(user_id, user_email)`` from EasyAuth headers.

    Resolution order:
        1. Decoded ``x-ms-client-principal`` claims (object id + email/UPN).
        2. EasyAuth convenience headers (``x-ms-client-principal-id`` / ``-name``).
        3. Caller-supplied fallbacks (e.g. query params forwarded by the SPA
           when the backend itself is not fronted by EasyAuth).

    Non-raising. Accepts any mapping-like headers object (Starlette Request or
    WebSocket ``.headers``).
    """

    def _get(key: str) -> str | None:
        try:
            return headers.get(key)
        except Exception:
            return None

    user_id: str | None = None
    user_email: str | None = None

    principal = parse_easyauth_principal(_get("x-ms-client-principal"))
    if principal:
        user_id = _claim_value(principal, _OID_CLAIM_TYPES)
        user_email = _claim_value(principal, _EMAIL_CLAIM_TYPES)

    user_id = user_id or _get("x-ms-client-principal-id") or fallback_id
    user_email = user_email or _get("x-ms-client-principal-name") or fallback_email

    return user_id, user_email


async def validate_entraid_token(request: Request) -> dict:
    """Validates bearer token for Entra ID."""
    auth_header = request.headers.get("Authorization")
    token = extract_bearer_token(auth_header)
    try:
        decoded = validate_jwt_token(
            token, jwks_url=ENTRA_JWKS_URL, issuer=ENTRA_ISSUER, audience=ENTRA_AUDIENCE
        )
        client_id = decoded.get("azp") or decoded.get("appid")
        if client_id not in ALLOWED_CLIENT_IDS:
            raise HTTPException(status_code=403, detail="Unauthorized client_id")
        logger.info("EntraID request authenticated")
        return decoded
    except AuthError as e:
        logger.warning(f"EntraID validation failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))


def validate_acs_http_auth(request: Request) -> dict:
    """Validates bearer token for ACS HTTP callbacks."""
    auth_header = request.headers.get("Authorization")
    token = extract_bearer_token(auth_header)
    try:
        decoded = validate_jwt_token(
            token, jwks_url=ACS_JWKS_URL, issuer=ACS_ISSUER, audience=ACS_AUDIENCE
        )
        logger.info("ACS HTTP request authenticated")
        return decoded
    except AuthError as e:
        logger.warning(f"ACS HTTP auth failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))


async def validate_acs_ws_auth(ws: WebSocket) -> dict:
    """Validates bearer token for ACS WebSocket handshake."""
    auth_header = ws.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("Missing or invalid WebSocket auth header")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1008)
        raise AuthError("Missing or invalid WebSocket auth header")

    token = extract_bearer_token(auth_header)
    try:
        decoded = validate_jwt_token(
            token, jwks_url=ACS_JWKS_URL, issuer=ACS_ISSUER, audience=ACS_AUDIENCE
        )
        logger.info("ACS WebSocket authenticated")
        return decoded
    except AuthError as e:
        logger.error(f"WebSocket auth failed: {e}")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1011)
        raise
