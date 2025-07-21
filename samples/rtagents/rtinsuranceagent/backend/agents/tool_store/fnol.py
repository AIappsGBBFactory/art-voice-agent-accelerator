"""
XYMZ Insurance • Minimal 12-field FNOL recorder  (v2 – boolean-safe)
-------------------------------------------------------------------
• Fixes: False booleans were treated as “missing”.
• Adds: parse_yes_no() + SlotTracker for conversational agents.
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict

from rtagents.RTInsuranceAgent.backend.agents.tool_store.functions_helper import (
    _json,
)  # type: ignore

from utils.ml_logging import get_logger

log = get_logger("fnol_tools_min")

# ──────────────────────────────────────────────────────────────────────
#  Demo DB stubs
# ──────────────────────────────────────────────────────────────────────
policyholders_db: Dict[str, Dict[str, str]] = {
    "Alice Brown": {"policy_id": "POL-A10001", "zip": "60601"},
    "Amelia Johnson": {"policy_id": "POL-B20417", "zip": "60601"},
    "Carlos Rivera": {"policy_id": "POL-C88230", "zip": "77002"},
}
claims_db: List[Dict[str, Any]] = []
emergency_log: List[Dict[str, Any]] = []


# ──────────────────────────────────────────────────────────────────────
#  Type definitions
# ──────────────────────────────────────────────────────────────────────
class LossLocation(TypedDict, total=False):
    street: str | None
    city: str | None
    state: str | None
    zipcode: str | None


class ClaimIntakeMinimal(TypedDict, total=False):
    caller_name: str
    caller_role: str
    policy_id: str
    date_reported: str
    date_of_loss: str
    time_of_loss: str | None
    collision: bool
    bodily_injury: bool
    property_damage: bool
    comprehensive_loss: bool
    narrative: str
    loss_location: LossLocation
    location_description: str | None


class EscalateArgs(TypedDict):
    reason: str
    caller_name: str
    policy_id: str


# ──────────────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────────────
def _new_claim_id() -> str:
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"CLA-{datetime.utcnow().year}-{rand}"


# List must match your tool schema 1-for-1
_REQUIRED_SLOTS = {
    "caller_role",
    "date_of_loss",
    "narrative",
    "collision",
    "bodily_injury",
    "property_damage",
    "comprehensive_loss",
    "loss_location.street",
    "loss_location.city",
    "loss_location.state",
    "loss_location.zipcode",
}
_BOOL_FIELDS = {"collision", "bodily_injury", "property_damage", "comprehensive_loss"}


def _is_missing(container: Dict[str, Any], key: str) -> bool:
    """
    True  -> value absent  OR  empty string / dict  (False is OK for bools)
    False -> slot present with a valid value (incl. boolean False)
    """
    if key in _BOOL_FIELDS:
        return key not in container  # Presence enough
    val = container.get(key)
    return val in (None, "", {})


def _validate(data: ClaimIntakeMinimal) -> tuple[bool, str]:
    missing: list[str] = []

    for slot in _REQUIRED_SLOTS:
        if slot.startswith("loss_location."):
            _, sub = slot.split(".", 1)
            if _is_missing(data.get("loss_location", {}), sub):
                missing.append(slot)
        elif _is_missing(data, slot):
            missing.append(slot)

    if missing:
        log.warning("❌ Missing required fields: %s", ", ".join(missing))
        return False, ", ".join(missing)
    return True, ""


# ──────────────────────────────────────────────────────────────────────
#  Public tool functions
# ──────────────────────────────────────────────────────────────────────
async def record_fnol(args: ClaimIntakeMinimal) -> Dict[str, Any]:
    """Validate & persist a minimal FNOL claim."""
    args.setdefault("date_reported", datetime.now(timezone.utc).date().isoformat())

    ok, msg = _validate(args)
    if not ok:
        return {"claim_success": False, "missing_data": f"Missing or empty: {msg}."}

    claim_id = _new_claim_id()
    claims_db.append(
        {
            **args,
            "claim_id": claim_id,
            "status": "OPEN",
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    log.info("📄 FNOL recorded (%s) for %s", claim_id, args["caller_name"])

    return {"claim_success": True, "claim_id": claim_id}


async def escalate_emergency(args: EscalateArgs) -> Dict[str, Any]:
    emergency_log.append({**args, "timestamp": datetime.utcnow().isoformat()})
    log.warning(
        "🚨 Emergency escalation for %s (%s): %s",
        args["caller_name"],
        args["policy_id"],
        args["reason"],
    )
    return _json(True, "Emergency dispatched.")


NEG = {"no", "none", "not", "zero", "false", "nil", "never"}
POS = {"yes", "yeah", "yep", "sure", "true", "absolutely", "of course"}


def parse_yes_no(text: str) -> bool | None:
    """Rough NL → boolean converter.  Returns None if unclear."""
    t = text.lower()
    if any(w in t for w in NEG):
        return False
    if any(w in t for w in POS):
        return True
    return None


class SlotTracker:
    """
    Minimal in-memory slot store.
    Example:
        tracker = SlotTracker()
        tracker.update_from_user("No one was hurt.")
        tracker.missing()   # → {...}
    """

    def __init__(self) -> None:
        self.slots: ClaimIntakeMinimal = {
            "loss_location": {}  # nested dict needs to exist
        }  # type: ignore[assignment]

    # --- update helpers ------------------------------------------------
    def update(self, **kv: Any) -> None:
        """Direct assignment: tracker.update(collision=True, bodily_injury=False)"""
        for k, v in kv.items():
            if k.startswith("loss_location."):
                _, sub = k.split(".", 1)
                self.slots.setdefault("loss_location", {})[sub] = v
            else:
                self.slots[k] = v

    def update_from_user(self, utterance: str) -> None:
        """VERY naive extractor – replace with LLM / regex as needed"""
        utt = utterance.lower()

        # booleans
        if "injur" in utt:
            val = parse_yes_no(utt)
            if val is not None:
                self.update(bodily_injury=val)
        if "property damage" in utt:
            val = parse_yes_no(utt)
            if val is not None:
                self.update(property_damage=val)
        if any(p in utt for p in ("parked", "non-collision")):
            self.update(comprehensive_loss=True)
        if "collision" in utt:
            self.update(comprehensive_loss=False, collision=True)

    # --- queries -------------------------------------------------------
    def missing(self) -> List[str]:
        """Return list of required slots that are still unfilled."""
        missing = []
        for slot in _REQUIRED_SLOTS:
            if slot.startswith("loss_location."):
                _, sub = slot.split(".", 1)
                if _is_missing(self.slots.get("loss_location", {}), sub):
                    missing.append(slot)
            elif _is_missing(self.slots, slot):
                missing.append(slot)
        return missing

    def ready_for_tool(self) -> bool:
        return not self.missing()

    # convenient stringify for debugging
    def __repr__(self) -> str:
        return json.dumps(self.slots, indent=2, default=str)
