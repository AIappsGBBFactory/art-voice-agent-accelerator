"""XYMZ Insurance • Minimal 12-field FNOL recorder"""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict

from apps.rtagent.backend.src.agents.tool_store.functions_helper import _json

from utils.ml_logging import get_logger

log = get_logger("fnol_tools_min")

policyholders_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {"policy_id": "POL-A10001", "zip": "60601"},
    "Amelia Johnson": {"policy_id": "POL-B20417", "zip": "60601"},
    "Carlos Rivera": {"policy_id": "POL-C88230", "zip": "77002"},
}

claims_db: List[Dict[str, Any]] = []
emergency_log: List[Dict[str, Any]] = []


class LossLocation(TypedDict, total=False):
    street: str | None
    city: str | None
    state: str | None
    zipcode: str | None


class ClaimIntakeMinimal(TypedDict, total=False):
    caller_name: str
    caller_role: str
    policy_id: str
    date_reported: str  # YYYY-MM-DD (auto-filled if absent)
    date_of_loss: str
    time_of_loss: str | None
    collision: bool
    bodily_injury: bool
    property_damage: bool
    glass_damage: bool
    comprehensive_loss: bool
    narrative: str  # ≤ 400 chars
    loss_location: LossLocation
    location_description: str | None  # optional free-text


class EscalateArgs(TypedDict):
    reason: str
    caller_name: str
    policy_id: str


def _new_claim_id() -> str:
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"CLA-{datetime.utcnow().year}-{rand}"


_REQUIRED_SLOTS = {
    "caller_role",
    "date_of_loss",
    "narrative",
    "collision",
    "bodily_injury",
    "property_damage",
    "glass_damage",
    "comprehensive_loss",
    "loss_location.street",
    "loss_location.city",
    "loss_location.state",
    "loss_location.zipcode",
}


def _validate(data: ClaimIntakeMinimal) -> tuple[bool, str]:
    """
    Ensures every required slot is present & non-empty.
    Returns (False, "Missing: …") when validation fails.
    """
    missing: list[str] = []
    # flat-check top-level fields first
    for field in _REQUIRED_SLOTS:
        if field.startswith("loss_location."):
            # nested field
            _, sub = field.split(".", 1)
            if not data.get("loss_location", {}).get(sub):
                missing.append(field)
        elif not data.get(field):
            missing.append(field)

    if missing:
        return False, "Missing: " + ", ".join(missing)
    return True, ""


async def record_fnol(args: ClaimIntakeMinimal) -> str:
    args.setdefault("date_reported", datetime.now(timezone.utc).date().isoformat())
    ok, msg = _validate(args)
    if not ok:
        return {
            "claim_success": False,
            "missing_data": f"{msg}.",
        }
    claim_id = _new_claim_id()
    claims_db.append({**args, "claim_id": claim_id, "status": "OPEN"})
    log.info("📄 FNOL recorded (%s) for %s", claim_id, args["caller_name"])
    return {
        "claim_success": True,
        "claim_id": claim_id,
    }


async def escalate_emergency(args: EscalateArgs) -> str:
    emergency_log.append({**args, "timestamp": datetime.utcnow().isoformat()})
    log.warning(
        "🚨 Emergency escalation for %s (%s): %s",
        args["caller_name"],
        args["policy_id"],
        args["reason"],
    )
    return _json(True, "Emergency dispatched.")
