from __future__ import annotations

"""
Caller authentication helper for XYMZ Insurance's ARTAgent.

Validates the caller using *(full_name, ZIP, last-4 of SSN / policy / claim / phone)*.

### Invocation contract
The LLM must call **`authenticate_caller`** exactly **once** per conversation, passing a
five-field payload **plus** an optional ``attempt`` counter if the backend is tracking
retries:

```jsonc
{
  "full_name": "Chris Lee",
  "zip_code": "60601",            // Empty string allowed if caller gave last-4
  "last4_id": "",                 // Empty string allowed if caller gave ZIP
  "intent": "claims",            // "claims" | "general"
  "claim_intent": "new_claim",   // "new_claim" | "existing_claim" | "unknown" | null
  "attempt": 2                    // (Optional) nth authentication attempt
}
```

### Return value
`authenticate_caller` *always* echoes the ``attempt`` count.  On **success** it also
echoes back ``intent`` and ``claim_intent`` so the caller can continue routing without
extra look-ups.  On **failure** these two keys are returned as ``null``.

```jsonc
{
  "authenticated": false,
  "message": "Authentication failed - ZIP and last-4 did not match.",
  "client_id": null,
  "caller_name": null,
  "attempt": 2,
  "intent": null,
  "claim_intent": null
}
```
"""

import asyncio
import time
from typing import Any, Dict, List, Literal, Optional, TypedDict

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger
from pymongo.errors import NetworkTimeout

logger = get_logger("tools.acme_auth")

# ────────────────────────────────────────────────────────────────
# Cosmos DB manager for policyholder data
# ────────────────────────────────────────────────────────────────
def _get_cosmos_manager() -> CosmosDBMongoCoreManager:
    """Get Cosmos DB manager for user authentication data."""
    return CosmosDBMongoCoreManager(
        database_name="financial_services_db",
        collection_name="users"
    )

async def _get_policyholder_by_credentials(
    full_name: str, 
    zip_code: Optional[str] = None, 
    last4_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieve a policyholder by full name AND verification credentials from Cosmos DB.
    This approach is more production-ready as it handles duplicate names properly.
    """
    query_start_time = time.time()
    try:
        cosmos = _get_cosmos_manager()
        logger.info(f"Starting authentication query for {full_name} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Build compound query with name + verification data
        query = {"full_name": full_name.strip().title()}
        
        # Add ZIP code to query if provided
        if zip_code:
            query["zip"] = zip_code.strip()
        
        # If last4_id provided, create OR query for all last4 fields
        if last4_id:
            last4_fields = ["ssn4", "policy4", "claim4", "phone4"]
            # Use MongoDB $or operator to match any of the last4 fields
            query["$or"] = [{field: last4_id.strip()} for field in last4_fields]
        
        db_query_start = time.time()
        result = await asyncio.to_thread(
            cosmos.read_document,
            query=query
        )
        db_query_duration = time.time() - db_query_start
        total_duration = time.time() - query_start_time
        
        logger.info(f"Database query completed in {db_query_duration:.3f}s, total function duration: {total_duration:.3f}s")
        
        return result  # read_document returns the document or None
            
    except NetworkTimeout as err:
        error_duration = time.time() - query_start_time
        logger.warning(f"Network timeout when querying for {full_name} after {error_duration:.3f}s: {err}")
        return None
    except Exception as e:
        error_duration = time.time() - query_start_time
        logger.error(f"Database error querying for {full_name} after {error_duration:.3f}s: {e}")
        return None


class AuthenticateArgs(TypedDict):
    """Payload expected by :pyfunc:`authenticate_caller`."""

    full_name: str  # required
    zip_code: str  # required – may be empty string
    last4_id: str  # required – may be empty string
    intent: Literal["claims", "general"]
    claim_intent: Optional[Literal["new_claim", "existing_claim", "unknown"]]
    attempt: Optional[int]


class AuthenticateResult(TypedDict):
    """Return schema from :pyfunc:`authenticate_caller`."""

    authenticated: bool
    message: str
    client_id: Optional[str]
    caller_name: Optional[str]
    attempt: int
    intent: Optional[Literal["claims", "general"]]
    claim_intent: Optional[Literal["new_claim", "existing_claim", "unknown"]]


async def authenticate_caller(
    args: AuthenticateArgs,
) -> AuthenticateResult:  # noqa: C901
    """Validate a caller.

    Parameters
    ----------
    args
        A dictionary matching :class:`AuthenticateArgs`.

    Returns
    -------
    AuthenticateResult
        Outcome of the authentication attempt.  On success the caller's
        *intent* and *claim_intent* are echoed back; on failure they are
        ``None`` so the orchestrator can decide next steps. Always returns
        a valid result dictionary - never raises exceptions to prevent
        conversation corruption.
    """
    # Input type validation to prevent 400 errors
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return {
            "authenticated": False,
            "message": "Invalid request format. Please provide authentication details.",
            "client_id": None,
            "caller_name": None,
            "attempt": 1,
            "intent": None,
            "claim_intent": None,
        }

    # ------------------------------------------------------------------
    # Sanity-check input – ensure at least one verification factor given
    # ------------------------------------------------------------------
    zip_code = args.get("zip_code", "").strip() if args.get("zip_code") else ""
    last4_id = args.get("last4_id", "").strip() if args.get("last4_id") else ""

    if not zip_code and not last4_id:
        msg = "zip_code or last4_id must be provided"
        logger.error("%s", msg)
        # Never raise exceptions from tool functions - return error result instead
        # This prevents 400 errors and conversation corruption in OpenAI API
        attempt = int(args.get("attempt", 1))
        return {
            "authenticated": False,
            "message": msg,
            "client_id": None,
            "caller_name": None,
            "attempt": attempt,
            "intent": None,
            "claim_intent": None,
        }

    # ------------------------------------------------------------------
    # Normalise inputs
    # ------------------------------------------------------------------
    full_name = (
        args.get("full_name", "").strip().title() if args.get("full_name") else ""
    )
    # Use the already safely extracted zip_code and last4_id from above
    last4 = last4_id  # Alias for consistency with existing code
    attempt = int(args.get("attempt", 1))

    if not full_name:
        logger.error("full_name is required")
        return {
            "authenticated": False,
            "message": "Full name is required for authentication.",
            "client_id": None,
            "caller_name": None,
            "attempt": attempt,
            "intent": None,
            "claim_intent": None,
        }

    intent = args.get("intent", "general")
    claim_intent = args.get("claim_intent")

    auth_start_time = time.time()
    logger.info(
        "Attempt %d – Authenticating %s | ZIP=%s | last-4=%s | intent=%s | claim_intent=%s | Started at: %s",
        attempt,
        full_name,
        zip_code or "<none>",
        last4 or "<none>",
        intent,
        claim_intent,
        time.strftime('%H:%M:%S')
    )

    # Query Cosmos DB for the policyholder using compound query
    try:
        rec = await _get_policyholder_by_credentials(
            full_name=full_name,
            zip_code=zip_code if zip_code else None,
            last4_id=last4 if last4 else None
        )
    except Exception as e:
        auth_duration = time.time() - auth_start_time
        logger.error("Database error during authentication for %s after %s: %s", full_name, f"{auth_duration:.3f}s", e)
        return {
            "authenticated": False,
            "message": "Authentication service temporarily unavailable. Please try again.",
            "client_id": None,
            "caller_name": None,
            "attempt": attempt,
            "intent": None,
            "claim_intent": None,
        }

    if not rec:
        auth_duration = time.time() - auth_start_time
        logger.warning("No matching policyholder found for %s with provided credentials (completed in %.3fs)", full_name, auth_duration)
        return {
            "authenticated": False,
            "message": f"Authentication failed - no matching record found for {full_name}.",
            "client_id": None,
            "caller_name": None,
            "attempt": attempt,
            "intent": None,
            "claim_intent": None,
        }

    # If we reach here, the compound query already verified the credentials
    # So we can directly return success
    auth_duration = time.time() - auth_start_time
    logger.info("Authentication succeeded for %s (total duration: %.3fs)", full_name, auth_duration)
    return {
        "authenticated": True,
        "message": f"Authenticated {full_name}.",
        "client_id": rec["client_id"],
        "caller_name": full_name,
        "attempt": attempt,
        "intent": intent,
        "claim_intent": claim_intent,
    }