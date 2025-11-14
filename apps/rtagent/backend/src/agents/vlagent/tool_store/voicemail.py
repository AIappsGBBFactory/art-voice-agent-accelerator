from __future__ import annotations

"""
Voicemail detection helper for the AutoAuth agent.

When the agent is confident the caller is a voicemail greeting or an answering
machine, it can invoke this tool to signal that the call should be ended
gracefully. The orchestration layer will handle the actual termination once it
sees the structured response returned here.
"""

from typing import Any, Dict, Optional, TypedDict

from utils.ml_logging import get_logger

logger = get_logger("tool_store.voicemail")


class VoicemailDetectionArgs(TypedDict, total=False):
    """Input schema for :pyfunc:`detect_voicemail_and_end_call`."""

    voicemail_cues: str
    confidence: float
    confirmation_message: str  # Optional custom confirmation message


async def detect_voicemail_and_end_call(
    args: VoicemailDetectionArgs,
) -> Dict[str, Any]:
    """
    Signal that the current interaction appears to be a voicemail and request confirmation
    before terminating the call.

    Returns a structured payload consumed by the orchestration layer. The tool
    requests one final confirmation attempt before call termination.
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for voicemail tool: %s", type(args))
        return {
            "voicemail_detected": False,
            "terminate_session": False,
            "error": "Invalid request format. Expected an object with voicemail cues.",
        }

    cues = (args.get("voicemail_cues") or "").strip()
    confidence_raw: Optional[float] = args.get("confidence")
    confirmation_message = (args.get("confirmation_message") or "").strip()

    confidence: Optional[float] = None
    if confidence_raw is not None:
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            logger.debug(
                "Unable to coerce voicemail confidence '%s' to float; ignoring.",
                confidence_raw,
            )

    if not cues:
        cues = "No explicit cues provided."

    # Generate a default confirmation message if none provided
    if not confirmation_message:
        confirmation_message = (
            "I want to make sure I'm speaking with a person. "
            "If you're there, please say hello or let me know how I can help you today. "
            "If not, I'll end this call in a moment."
        )

    logger.info(
        "Voicemail detection signalled with confirmation request – cues='%s' confidence=%s",
        cues,
        confidence,
    )

    return {
        "voicemail_detected": True,
        "confirmation_requested": True,
        "confirmation_message": confirmation_message,
        "terminate_session": False,  # Don't terminate immediately - wait for confirmation
        "termination_reason": "voicemail_detected",
        "summary": cues,
        "confidence": confidence,
    }


class VoicemailConfirmationArgs(TypedDict, total=False):
    """Input schema for :pyfunc:`confirm_voicemail_and_end_call`."""
    
    confirmation_reason: str


async def confirm_voicemail_and_end_call(
    args: VoicemailConfirmationArgs,
) -> Dict[str, Any]:
    """
    Confirm voicemail detection and terminate the call after giving the user 
    opportunity to respond.
    
    This should be called when:
    1. No human response received after voicemail confirmation request
    2. Clear indication that this is indeed a voicemail/answering machine
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for voicemail confirmation tool: %s", type(args))
        return {
            "voicemail_detected": False,
            "terminate_session": False,
            "error": "Invalid request format. Expected an object with confirmation reason.",
        }

    confirmation_reason = (args.get("confirmation_reason") or "").strip()
    
    if not confirmation_reason:
        confirmation_reason = "No human response received after confirmation request."

    logger.info(
        "Voicemail confirmed and call termination requested – reason='%s'",
        confirmation_reason,
    )

    return {
        "voicemail_detected": True,
        "voicemail_confirmed": True,
        "terminate_session": True,
        "termination_reason": "voicemail_confirmed",
        "summary": confirmation_reason,
    }
