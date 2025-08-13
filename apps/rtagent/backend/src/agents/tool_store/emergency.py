from typing import Any, Dict, TypedDict

from apps.rtagent.backend.src.agents.tool_store.functions_helper import _json
from utils.ml_logging import get_logger

logger = get_logger("tool_store.emergency")


class EscalateEmergencyArgs(TypedDict):
    reason: str


async def escalate_emergency(args: EscalateEmergencyArgs) -> str:
    """
    Escalate the call to a live insurance agent and stop the bot session.
    """
    reason = args["reason"].strip()
    if not reason:
        return _json(False, "Reason for escalation is required.")

    logger.info("🔴 Escalating to human agent – %s", reason)

    # The sentinel that upstream code will look for
    return {
        "escalated": True,
        "escalation_reason": f"Escalation to human insurance agent triggered {reason}.",
        "handoff": "human_agent",
    }