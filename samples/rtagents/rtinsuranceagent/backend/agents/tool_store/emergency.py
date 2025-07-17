from typing import Any, Dict, TypedDict

from rtagents.RTInsuranceAgent.backend.agents.tool_store.functions_helper import _json

from utils.ml_logging import get_logger

logger = get_logger()


class EscalateEmergencyArgs(TypedDict):
    reason: str


async def escalate_emergency(args: EscalateEmergencyArgs) -> str:
    """
    Escalate the call to a human insurance agent for urgent/emergency situations.
    This is for insurance context: may be medical, accident, injury, fire, or any urgent claim scenario.
    Always routes to a live human agent for immediate assistance.
    """
    reason = args["reason"].strip()
    if not reason:
        return _json(False, "Reason for escalation is required.")
    # Log escalation and return a message indicating human handoff
    logger.info(f"Escalating to human insurance agent: {reason}")
    return _json(
        True,
        "Escalation to human insurance agent triggered.",
        reason=reason,
        handoff="human_agent",
    )
