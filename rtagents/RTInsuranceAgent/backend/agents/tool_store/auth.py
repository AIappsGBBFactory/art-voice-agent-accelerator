from typing import Any, Dict, List, TypedDict
from utils.ml_logging import get_logger

logger = get_logger("acme_auth")

policyholders_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {
        "zip":  "60601",
        "ssn4": "1234",
        "policy4": "4321",
        "claim4": "9876",
        "phone4": "1078",
        "policy_id": "POL-A10001"
    },
    "Amelia Johnson": {
        "zip":  "60601",
        "ssn4": "5566",
        "policy4": "2211",
        "claim4": "3344",
        "phone4": "4555",
        "policy_id": "POL-B20417"
    },
    "Carlos Rivera": {
        "zip":  "77002",
        "ssn4": "7788",
        "policy4": "4455",
        "claim4": "1122",
        "phone4": "9200",
        "policy_id": "POL-C88230"
    },
    # … add more as needed
}

class AuthenticateArgs(TypedDict):
    full_name: str     # required
    zip_code: str      # required
    last4_id: str      # required – caller chooses which ID to supply

async def authenticate_caller(args: AuthenticateArgs) -> Dict[str, Any]:
    """
    Validates caller using (name, zip, last-4 of SSN / policy / claim / phone).

    Returns
    -------
    {
        "authenticated": bool,
        "message": str,
        "policy_id": str | None,
        "caller_name": str | None
    }
    """
    full_name = args["full_name"].strip().title()
    zip_code  = args["zip_code"].strip()
    last4     = args["last4_id"].strip()

    logger.info(f"🔎 Authenticating {full_name} – ZIP {zip_code}, last-4 {last4}")

    rec = policyholders_db.get(full_name)
    if not rec:
        logger.warning(f"❌ Name not found: {full_name}")
        return {
            "authenticated": False,
            "message": f"Name '{full_name}' not found.",
            "policy_id": None,
            "caller_name": None,
        }

    # last-4 may match ANY of the stored identifiers
    last4_fields: List[str] = ["ssn4", "policy4", "claim4", "phone4"]
    last4_match = last4 in [rec[f] for f in last4_fields]
    zip_match = rec["zip"] == zip_code

    # Approve if either (name + zip) or (name + last-4) matches
    if zip_match or last4_match:
        logger.info(f"✅ Authentication succeeded for {full_name}")
        return {
            "authenticated": True,
            "message": f"Authenticated {full_name}.",
            "policy_id": rec["policy_id"],
            "caller_name": full_name,
        }
    else:
        logger.warning(f"❌ Neither ZIP nor last-4 matched for {full_name}")
        return {
            "authenticated": False,
            "message": "Authentication failed – neither ZIP nor last-4 digits matched.",
            "policy_id": None,
            "caller_name": None,
        }
