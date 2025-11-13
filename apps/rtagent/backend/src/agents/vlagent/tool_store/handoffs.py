from __future__ import annotations

"""
FNOL voice-agent *escalation and hand-off* utilities.

This module exposes **three** async callables that the LLM can invoke
to redirect the conversation flow:

1. ``handoff_general_agent`` – transfer to the *General Insurance Questions*
   AI agent whenever the caller seeks broad, non-claim-specific information
   (e.g., “What is covered under comprehensive?”).
2. ``handoff_claim_agent`` – transfer to the *Claims Intake* AI agent when
   the caller wants to start or update a claim.
3. ``escalate_human`` – cold-transfer to a live adjuster for fraud flags,
   repeated validation loops, backend errors, or customer frustration.

All functions follow project standards (PEP 8 typing, structured logging,
robust error handling, and JSON responses via ``_json``).
"""

from datetime import datetime, timezone
from typing import Any, Dict, TypedDict

from apps.rtagent.backend.src.agents.vlagent.tool_store.functions_helper import _json
from utils.ml_logging import get_logger

logger = get_logger("fnol_escalations")


# ────────────────────────────────────────────────────────────────
# General-info hand-off
# ────────────────────────────────────────────────────────────────
class HandoffGeneralArgs(TypedDict):
    """Input schema for :pyfunc:`handoff_general_agent`."""

    topic: str  # e.g. "coverage", "billing"
    caller_name: str


async def handoff_general_agent(args: HandoffGeneralArgs) -> Dict[str, Any]:
    """
    Transfer the caller to the **General Insurance Questions** AI agent.
    """
    # Input type validation to prevent 400 errors
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format. Please provide handoff details.")
    
    try:
        topic = (args.get("topic") or "").strip()
        caller_name = (args.get("caller_name") or "").strip()

        if not topic or not caller_name:
            return _json(False, "Both 'topic' and 'caller_name' must be provided.")

        logger.info(
            "🤖 Hand-off to General-Info agent – topic=%s caller=%s", topic, caller_name
        )
        return _json(
            True,
            "Caller transferred to General Insurance Questions agent.",
            handoff="ai_agent",
            target_agent="General Insurance Questions",
            topic=topic,
        )
    except Exception as exc:
        # Catch all exceptions to prevent 400 errors
        logger.error("General handoff failed: %s", exc, exc_info=True)
        return _json(False, "Technical error during handoff. Please try again.")


# ────────────────────────────────────────────────────────────────
# Claims-intake hand-off  🆕
# ────────────────────────────────────────────────────────────────
class HandoffClaimArgs(TypedDict):
    """Input schema for :pyfunc:`handoff_claim_agent`."""

    caller_name: str
    policy_id: str
    claim_intent: str  # e.g. "new_claim", "update_claim"


async def handoff_claim_agent(args: HandoffClaimArgs) -> Dict[str, Any]:
    """
    Transfer the caller to the **Claims Intake** AI agent.

    Parameters
    ----------
    caller_name : str
    policy_id   : str
    claim_intent: str   (free-text hint such as "new_claim")
    """
    # Input type validation to prevent 400 errors
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format. Please provide claim handoff details.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        policy_id = (args.get("policy_id") or "").strip()
        intent = (args.get("claim_intent") or "").strip()

        if not caller_name or not policy_id:
            return _json(
                False, "'caller_name' and 'policy_id' are required for claim hand-off."
            )

        logger.info(
            "📂 Hand-off to Claims agent – %s (%s) intent=%s",
            caller_name,
            policy_id,
            intent or "n/a",
        )

        return _json(
            True,
            "Caller transferred to Claims Intake agent.",
            handoff="ai_agent",
            target_agent="Claims Intake",
            claim_intent=intent or "unspecified",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        # Catch all exceptions to prevent 400 errors
        logger.error("Claim handoff failed: %s", exc, exc_info=True)
        return _json(False, "Technical error during claim handoff. Please try again.")


# ────────────────────────────────────────────────────────────────
# Human escalation
# ────────────────────────────────────────────────────────────────
class EscalateHumanArgs(TypedDict, total=False):
    """Input schema for :pyfunc:`escalate_human`."""

    route_reason: str  # Required
    caller_name: str   # Required  
    policy_id: str     # Optional for financial services


async def escalate_human(args: EscalateHumanArgs) -> Dict[str, Any]:
    """
    Escalate *non-emergency* scenarios to a human insurance adjuster.
    """
    # Input type validation to prevent 400 errors
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format. Please provide escalation details.")
    
    try:
        route_reason = (args.get("route_reason") or "").strip()
        caller_name = (args.get("caller_name") or "").strip()
        policy_id = (args.get("policy_id") or "").strip()
        
        # Check for required fields
        if not route_reason:
            return _json(False, "'route_reason' is required for human escalation.")
        if not caller_name:
            return _json(False, "'caller_name' is required for human escalation.")

        # Log with or without policy_id
        if policy_id:
            logger.info("🤝 Human hand-off – %s (%s) reason=%s", caller_name, policy_id, route_reason)
        else:
            logger.info("🤝 Human hand-off – %s (financial services) reason=%s", caller_name, route_reason)
        
        return _json(
            True,
            "Caller transferred to specialist.",
            handoff="human_agent",
            route_reason=route_reason,
            caller_name=caller_name,
            policy_id=policy_id or "financial_services",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        # Catch all exceptions to prevent 400 errors
        logger.error("Human escalation failed: %s", exc, exc_info=True)
        return _json(False, "Technical error during human escalation. Please try again.")


# ────────────────────────────────────────────────────────────────
# Financial Services Agent Handoffs  🆕
# ────────────────────────────────────────────────────────────────
class HandoffFraudArgs(TypedDict):
    """Input schema for fraud agent handoff."""
    caller_name: str
    client_id: str
    institution_name: str
    service_type: str  # "fraud_reporting"

class HandoffTransferAgencyArgs(TypedDict):
    """Input schema for transfer agency handoff."""
    caller_name: str
    client_id: str
    institution_name: str
    service_type: str  # "transfer_agency"
    

async def handoff_fraud_agent(args: HandoffFraudArgs) -> Dict[str, Any]:
    """Transfer caller to Fraud Detection specialist after MFA authentication."""
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format. Please provide handoff details.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        client_id = (args.get("client_id") or "").strip()
        institution_name = (args.get("institution_name") or "").strip()
        service_type = (args.get("service_type") or "fraud_reporting").strip()

        if not caller_name or not client_id:
            return _json(False, "Both 'caller_name' and 'client_id' must be provided.")

        logger.info(
            "🛡️ Hand-off to Fraud agent – client_id=%s caller=%s institution=%s", 
            client_id, caller_name, institution_name
        )
        
        return _json(
            True,
            "Caller transferred to Fraud Detection specialist.",
            handoff="Fraud",
            target_agent="Fraud Detection",
            caller_name=caller_name,
            client_id=client_id,
            institution_name=institution_name,
            service_type=service_type,
        )
    except Exception as exc:
        logger.error("Fraud agent handoff failed: %s", exc, exc_info=True)
        return _json(False, "Technical error during handoff. Please try again.")


async def handoff_transfer_agency_agent(args: HandoffTransferAgencyArgs) -> Dict[str, Any]:
    """Transfer caller to Transfer Agency specialist after MFA authentication."""
    if not isinstance(args, dict):
        logger.error("Invalid args type: %s. Expected dict.", type(args))
        return _json(False, "Invalid request format. Please provide handoff details.")
    
    try:
        caller_name = (args.get("caller_name") or "").strip()
        client_id = (args.get("client_id") or "").strip()
        institution_name = (args.get("institution_name") or "").strip()
        service_type = (args.get("service_type") or "transfer_agency").strip()

        if not caller_name or not client_id:
            return _json(False, "Both 'caller_name' and 'client_id' must be provided.")

        logger.info(
            "🏦 Hand-off to Transfer Agency – client_id=%s caller=%s institution=%s", 
            client_id, caller_name, institution_name
        )
        
        return _json(
            True,
            "Caller transferred to Transfer Agency specialist.",
            handoff="Transfer",  # Maps to orchestration agent binding
            target_agent="Transfer Agency",
            caller_name=caller_name,
            client_id=client_id,
            institution_name=institution_name,
            service_type=service_type,
        )
    except Exception as exc:
        logger.error("Transfer Agency handoff failed: %s", exc, exc_info=True)
        return _json(False, "Technical error during handoff. Please try again.")