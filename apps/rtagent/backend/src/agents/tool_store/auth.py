from __future__ import annotations

"""
Caller‑authentication helper for XYMZ Insurance’s RTAgent.

Validates the caller using *(full_name, ZIP, last‑4 of SSN / policy / claim / phone)*.

### Invocation contract
The LLM must call **`authenticate_caller`** exactly **once** per conversation, passing a
five‑field payload **plus** an optional ``attempt`` counter if the backend is tracking
retries:

```jsonc
{
  "full_name": "Chris Lee",
  "zip_code": "60601",            // Empty string allowed if caller gave last‑4
  "last4_id": "",                 // Empty string allowed if caller gave ZIP
  "intent": "claims",            // "claims" | "general"
  "claim_intent": "new_claim",   // "new_claim" | "existing_claim" | "unknown" | null
  "attempt": 2                    // (Optional) nth authentication attempt
}
```

### Return value
`authenticate_caller` *always* echoes the ``attempt`` count.  On **success** it also
echoes back ``intent`` and ``claim_intent`` so the caller can continue routing without
extra look‑ups.  On **failure** these two keys are returned as ``null``.

```jsonc
{
  "authenticated": false,
  "message": "Authentication failed – ZIP and last‑4 did not match.",
  "policy_id": null,
  "caller_name": null,
  "attempt": 2,
  "intent": null,
  "claim_intent": null
}
```
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

from utils.ml_logging import get_logger

logger = get_logger("acme_auth")

# ────────────────────────────────────────────────────────────────
# In‑memory sample DB – replace with real store in prod
# ────────────────────────────────────────────────────────────────
policyholders_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {
        "zip": "60601",
        "ssn4": "1234",
        "policy4": "4321",
        "claim4": "9876",
        "phone4": "1078",
        "policy_id": "POL-A10001",
    },
    "Amelia Johnson": {
        "zip": "60601",
        "ssn4": "5566",
        "policy4": "2211",
        "claim4": "3344",
        "phone4": "4555",
        "policy_id": "POL-B20417",
    },
    "Carlos Rivera": {
        "zip": "60601",
        "ssn4": "1234",
        "policy4": "4455",
        "claim4": "1122",
        "phone4": "9200",
        "policy_id": "POL-C88230",
    },
    # … add more as needed
}


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
    policy_id: Optional[str]
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
        Outcome of the authentication attempt.  On success the caller’s
        *intent* and *claim_intent* are echoed back; on failure they are
        ``None`` so the orchestrator can decide next steps.

    Raises
    ------
    ValueError
        If both *zip_code* **and** *last4_id* are missing.
    """

    # ------------------------------------------------------------------
    # Sanity‑check input – ensure at least one verification factor given
    # ------------------------------------------------------------------
    if not args["zip_code"].strip() and not args["last4_id"].strip():
        msg = "zip_code or last4_id must be provided"
        logger.error("❌ %s", msg)
        raise ValueError(msg)

    # ------------------------------------------------------------------
    # Normalise inputs
    # ------------------------------------------------------------------
    full_name = args["full_name"].strip().title()
    zip_code = args["zip_code"].strip()
    last4 = args["last4_id"].strip()
    attempt = int(args.get("attempt", 1))

    logger.info(
        "🔎 Attempt %d – Authenticating %s | ZIP=%s | last‑4=%s | intent=%s | claim_intent=%s",
        attempt,
        full_name,
        zip_code or "<none>",
        last4 or "<none>",
        args["intent"],
        args["claim_intent"],
    )

    rec = policyholders_db.get(full_name)
    if not rec:
        logger.warning("❌ Name not found: %s", full_name)
        return {
            "authenticated": False,
            "message": f"Name '{full_name}' not found.",
            "policy_id": None,
            "caller_name": None,
            "attempt": attempt,
            "intent": None,
            "claim_intent": None,
        }

    # ------------------------------------------------------------------
    # Verify provided factors
    # ------------------------------------------------------------------
    last4_fields: List[str] = ["ssn4", "policy4", "claim4", "phone4"]
    last4_match = bool(last4) and last4 in (rec[f] for f in last4_fields)
    zip_match = bool(zip_code) and rec["zip"] == zip_code

    if zip_match or last4_match:
        logger.info("✅ Authentication succeeded for %s", full_name)
        return {
            "authenticated": True,
            "message": f"Authenticated {full_name}.",
            "policy_id": rec["policy_id"],
            "caller_name": full_name,
            "attempt": attempt,
            "intent": args["intent"],
            "claim_intent": args["claim_intent"],
        }

    # ------------------------------------------------------------------
    # Authentication failed
    # ------------------------------------------------------------------
    logger.warning("❌ ZIP and last‑4 both mismatched for %s", full_name)

    return {
        "authenticated": False,
        "message": "Authentication failed – ZIP and last‑4 did not match.",
        "policy_id": None,
        "caller_name": None,
        "attempt": attempt,
        "intent": None,
        "claim_intent": None,
    }
