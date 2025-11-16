from __future__ import annotations

"""VoiceLive handoff helpers that generate orchestrator-friendly payloads."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, TypedDict

from utils.ml_logging import get_logger

logger = get_logger("voicelive.handoffs")


def _cleanup_context(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value for key, value in (data or {}).items()
        if value not in (None, "", [], {}, False)
    }


def _build_handoff_payload(
    *,
    target_agent: str,
    message: str,
    summary: str,
    context: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "handoff": True,
        "target_agent": target_agent,
        "message": message,
        "handoff_summary": summary,
        "handoff_context": _cleanup_context(context),
    }
    if extra:
        payload.update(extra)
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HandoffGeneralArgs(TypedDict, total=False):
    topic: str
    caller_name: str
    details: str


async def handoff_general_agent(args: HandoffGeneralArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("handoff_general_agent expects a dict of arguments")

    topic = (args.get("topic") or "").strip()
    caller_name = (args.get("caller_name") or "").strip()
    details = (args.get("details") or "").strip()
    if not topic or not caller_name:
        raise ValueError("Both 'topic' and 'caller_name' must be provided")

    logger.info(
        "🤖 Hand-off to GeneralInfoAgent | topic=%s caller=%s",
        topic,
        caller_name,
    )

    context = {
        "topic": topic,
        "caller_name": caller_name,
        "details": details,
    }
    return _build_handoff_payload(
        target_agent="GeneralInfoAgent",
        message="",
        summary=topic,
        context=context,
        extra={"should_interrupt_playback": True},
    )


class HandoffClaimArgs(TypedDict, total=False):
    caller_name: str
    policy_id: str
    claim_intent: str
    details: str


async def handoff_claim_agent(args: HandoffClaimArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("handoff_claim_agent expects a dict of arguments")

    caller_name = (args.get("caller_name") or "").strip()
    policy_id = (args.get("policy_id") or "").strip()
    claim_intent = (args.get("claim_intent") or "").strip()
    details = (args.get("details") or "").strip()
    if not caller_name or not policy_id:
        raise ValueError("'caller_name' and 'policy_id' are required for claim handoff")

    logger.info(
        "📂 Hand-off to ClaimsIntake | caller=%s policy=%s intent=%s",
        caller_name,
        policy_id,
        claim_intent or "unspecified",
    )

    context = {
        "caller_name": caller_name,
        "policy_id": policy_id,
        "claim_intent": claim_intent or "unspecified",
        "details": details,
        "timestamp": _utc_now(),
    }
    return _build_handoff_payload(
        target_agent="ClaimsIntake",
        message="",
        summary=claim_intent or "claims_support",
        context=context,
        extra={"should_interrupt_playback": True},
    )


class EscalateHumanArgs(TypedDict, total=False):
    route_reason: str
    caller_name: str
    policy_id: str


async def escalate_human(args: EscalateHumanArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("escalate_human expects a dict of arguments")

    route_reason = (args.get("route_reason") or "").strip()
    caller_name = (args.get("caller_name") or "").strip()
    policy_id = (args.get("policy_id") or "").strip() or "financial_services"

    if not route_reason or not caller_name:
        raise ValueError("'route_reason' and 'caller_name' are required for escalation")

    logger.info(
        "🤝 Human escalation requested | caller=%s reason=%s policy=%s",
        caller_name,
        route_reason,
        policy_id,
    )

    return {
        "success": True,
        "message": "Thanks for waiting. A human specialist will join now.",
        "handoff": "human_agent",
        "route_reason": route_reason,
        "caller_name": caller_name,
        "policy_id": policy_id,
        "timestamp": _utc_now(),
    }


class HandoffFraudArgs(TypedDict, total=False):
    caller_name: str
    client_id: str
    institution_name: str
    service_type: str
    summary: str
    message: str
    session_overrides: Dict[str, Any]


async def handoff_fraud_agent(args: HandoffFraudArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("handoff_fraud_agent expects a dict of arguments")

    caller_name = (args.get("caller_name") or "").strip()
    client_id = (args.get("client_id") or "").strip()
    institution_name = (args.get("institution_name") or "").strip()
    service_type = (args.get("service_type") or "fraud_reporting").strip()
    summary = (args.get("summary") or "").strip()
    message = (args.get("message") or "").strip()
    session_overrides = args.get("session_overrides")

    if not caller_name or not client_id:
        raise ValueError("'caller_name' and 'client_id' are required for fraud handoff")
    if not institution_name:
        raise ValueError("'institution_name' is required for fraud handoff verification")

    logger.info(
        "🛡️ Hand-off to FraudAgent | client_id=%s caller=%s institution=%s",
        client_id,
        caller_name,
        institution_name or "n/a",
    )

    context = {
        "caller_name": caller_name,
        "client_id": client_id,
        "institution_name": institution_name,
        "service_type": service_type,
    }

    readable_service = (service_type or "fraud support").replace("_", " ")
    if not summary:
        summary = readable_service
    if not message:
        message = (
            f"I'm taking over as your fraud specialist for {institution_name}."
            if institution_name
            else "I'm taking over as your fraud specialist."
        )

    effective_greeting: Optional[str] = None
    if caller_name and institution_name:
        effective_greeting = (
            f"Hi {caller_name}, thanks for waiting. I'm the fraud specialist for {institution_name}. Let's secure your account together."
        )
    elif caller_name:
        effective_greeting = f"Hi {caller_name}, thanks for waiting. I'm your fraud specialist."
    elif institution_name:
        effective_greeting = (
            f"Thanks for holding. I'm the fraud specialist for {institution_name}."
        )

    extra: Dict[str, Any] = {"should_interrupt_playback": True}
    merged_overrides: Dict[str, Any] = {}
    if isinstance(session_overrides, dict):
        merged_overrides.update(session_overrides)
    if effective_greeting and not merged_overrides.get("greeting"):
        merged_overrides["greeting"] = effective_greeting
    if merged_overrides:
        extra["session_overrides"] = merged_overrides

    payload = _build_handoff_payload(
        target_agent="FraudAgent",
        message=message,
        summary=summary,
        context=context,
        extra=extra,
    )
    payload["success"] = True
    return payload


class HandoffTransferAgencyArgs(TypedDict, total=False):
    caller_name: str
    client_id: str
    institution_name: str
    service_type: str
    summary: str
    message: str
    session_overrides: Dict[str, Any]


async def handoff_transfer_agency_agent(args: HandoffTransferAgencyArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("handoff_transfer_agency_agent expects a dict of arguments")

    caller_name = (args.get("caller_name") or "").strip()
    client_id = (args.get("client_id") or "").strip()
    institution_name = (args.get("institution_name") or "").strip()
    service_type = (args.get("service_type") or "transfer_agency").strip()
    summary = (args.get("summary") or "").strip()
    message = (args.get("message") or "").strip()
    session_overrides = args.get("session_overrides")

    if not caller_name or not client_id:
        raise ValueError("'caller_name' and 'client_id' are required for transfer handoff")

    logger.info(
        "🏦 Hand-off to TransferAgency | client_id=%s caller=%s institution=%s",
        client_id,
        caller_name,
        institution_name or "n/a",
    )

    context = {
        "caller_name": caller_name,
        "client_id": client_id,
        "institution_name": institution_name,
        "service_type": service_type,
    }
    extra: Dict[str, Any] = {"should_interrupt_playback": True}
    if session_overrides:
        extra["session_overrides"] = session_overrides

    payload = _build_handoff_payload(
        target_agent="TransferAgency",
        message=message,
        summary=summary,
        context=context,
        extra=extra,
    )
    payload["success"] = True
    return payload


class HandoffPayPalArgs(TypedDict, total=False):
    caller_name: str
    client_id: str
    issue_summary: str
    inquiry_type: str
    institution_name: str
    details: str
    user_last_utterance: str
    session_overrides: Dict[str, Any]


async def handoff_paypal_agent(args: HandoffPayPalArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("handoff_paypal_agent expects a dict of arguments")

    caller_name = (args.get("caller_name") or "").strip()
    client_id = (args.get("client_id") or "").strip()
    issue_summary = (args.get("issue_summary") or "PayPal or Venmo support request").strip()
    inquiry_type = (args.get("inquiry_type") or "general_support").strip()
    institution_name = (args.get("institution_name") or "").strip()
    details = (args.get("details") or "").strip()
    user_last_utterance = (args.get("user_last_utterance") or "").strip()
    session_overrides = args.get("session_overrides")

    # if not caller_name:
    #     raise ValueError("'caller_name' is required for PayPal/Venmo handoff")

    logger.info(
        "💸 Hand-off to PayPalAgent | client_id=%s caller=%s issue=%s",
        client_id,
        caller_name,
        issue_summary,
    )

    context = {
        "caller_name": caller_name,
        "issue_summary": issue_summary,
        "inquiry_type": inquiry_type,
        "institution_name": institution_name,
    }
    if client_id:
        context["client_id"] = client_id
    if details:
        context.setdefault("details", details)
    if user_last_utterance:
        context.setdefault("user_last_utterance", user_last_utterance)
        if not context.get("details"):
            context["details"] = user_last_utterance
    extra: Dict[str, Any] = {"should_interrupt_playback": True}
    if isinstance(session_overrides, dict) and session_overrides:
        extra["session_overrides"] = session_overrides

    payload = _build_handoff_payload(
        target_agent="PayPalAgent",
        message="",
        summary=details or user_last_utterance or issue_summary,
        context=context,
        extra=extra,
    )
    payload["success"] = True
    return payload


class HandoffToAuthArgs(TypedDict, total=False):
    caller_name: str
    reason: str
    details: str
    user_last_utterance: str
    session_overrides: Dict[str, Any]


async def handoff_to_auth(args: HandoffToAuthArgs) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise TypeError("handoff_to_auth expects a dict of arguments")

    caller_name = (args.get("caller_name") or "").strip()
    reason = (args.get("reason") or "additional_support").strip()
    details = (args.get("details") or "").strip()
    user_last_utterance = (args.get("user_last_utterance") or "").strip()
    session_overrides = args.get("session_overrides")

    if not caller_name:
        raise ValueError("'caller_name' is required for auth handoff")

    logger.info(
        "🔁 Hand-off to AuthAgent | caller=%s reason=%s",
        caller_name,
        reason,
    )

    context = {
        "caller_name": caller_name,
        "handoff_reason": reason,
        "details": details or user_last_utterance,
    }
    if user_last_utterance:
        context.setdefault("user_last_utterance", user_last_utterance)
    extra: Dict[str, Any] = {"should_interrupt_playback": True}
    if isinstance(session_overrides, dict) and session_overrides:
        extra["session_overrides"] = session_overrides

    payload = _build_handoff_payload(
        target_agent="AuthAgent",
        message="",
        summary=reason,
        context=context,
        extra=extra,
    )
    payload["success"] = True
    return payload
