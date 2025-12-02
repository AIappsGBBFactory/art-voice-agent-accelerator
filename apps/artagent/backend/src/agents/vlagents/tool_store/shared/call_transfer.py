"""VoiceLive tool wrappers for triggering ACS call transfers."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError
from utils.ml_logging import logging
from apps.artagent.backend.src.services.acs.call_transfer import transfer_call


TRANSFER_CALL_SCHEMA: Dict[str, Any] = {
    "name": "transfer_call_to_destination",
    "description": (
        "Transfer the active caller to a specific SIP URI or PSTN number using Azure Communication Services. "
        "Use this when the conversation must be handed to an external participant, such as a branch office or concierge desk."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Destination SIP URI (e.g. sip:agent@example.com) or E.164 phone number.",
            },
            "call_connection_id": {
                "type": "string",
                "description": "ACS call connection identifier. Defaults to the active VoiceLive session when omitted.",
            },
            "operation_context": {
                "type": "string",
                "description": "Optional context tag echoed in ACS transfer events.",
            },
            "operation_callback_url": {
                "type": "string",
                "description": "Override callback URL for this transfer operation only.",
            },
            "transferee": {
                "type": "string",
                "description": "Existing participant to transfer away (optional).",
            },
            "sip_headers": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                },
                "description": "Custom SIP headers (ACS requires keys prefixed with X-MS-Custom-).",
            },
            "voip_headers": {
                "type": "object",
                "additionalProperties": {
                    "type": "string",
                },
                "description": "Custom VOIP headers to include with the transfer.",
            },
            "source_caller_id": {
                "type": "string",
                "description": "Custom caller ID to surface to the target when transferring to PSTN.",
            },
            "session_id": {
                "type": "string",
                "description": "Active VoiceLive session identifier for logging (optional).",
            },
        },
        "required": ["target"],
        "additionalProperties": False,
    },
}


TRANSFER_CALL_CENTER_SCHEMA: Dict[str, Any] = {
    "name": "transfer_call_to_call_center",
    "description": (
        "Route the active caller to the configured call center queue using Azure Communication Services. "
        "Use this when the caller explicitly requests a live representative and no additional destination information is required."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "call_connection_id": {
                "type": "string",
                "description": "ACS call connection identifier. Defaults to the active VoiceLive session when omitted.",
            },
            "operation_context": {
                "type": "string",
                "description": "Optional context value to stamp on ACS transfer events.",
            },
            "session_id": {
                "type": "string",
                "description": "Active VoiceLive session identifier for logging (optional).",
            },
            "target_override": {
                "type": "string",
                "description": "Override the configured call center target for this invocation only (testing).",
            },
            "confirmation_context": {
                "type": "string",
                "description": (
                    "Required: short transcript or summary proving the caller explicitly requested a call center/live representative twice "
                    "and confirmed after the clarifying question. Include the caller quote(s) for auditing."
                ),
                "minLength": 12,
            },
        },
        "required": ["confirmation_context"],
        "additionalProperties": False,
    },
}


class TransferCallPayload(BaseModel):
    """Pydantic payload used by the tool executor to validate inputs."""

    target: str = Field(..., min_length=1)
    call_connection_id: Optional[str] = None
    operation_context: Optional[str] = None
    operation_callback_url: Optional[str] = None
    transferee: Optional[str] = None
    sip_headers: Optional[Dict[str, str]] = None
    voip_headers: Optional[Dict[str, str]] = None
    source_caller_id: Optional[str] = None
    session_id: Optional[str] = None

    class Config:
        extra = "forbid"

    def sanitized(self) -> "TransferCallPayload":
        data = self.model_dump()
        data["target"] = data["target"].strip()
        for key in (
            "call_connection_id",
            "transferee",
            "source_caller_id",
            "operation_context",
            "operation_callback_url",
        ):
            if data.get(key):
                data[key] = data[key].strip()
        return TransferCallPayload(**data)


class CallCenterTransferPayload(BaseModel):
    """Payload for the call center transfer tool."""

    call_connection_id: Optional[str] = None
    operation_context: Optional[str] = None
    session_id: Optional[str] = None
    target_override: Optional[str] = Field(None, min_length=1)
    confirmation_context: str = Field(..., min_length=12)

    class Config:
        extra = "forbid"

    def sanitized(self) -> "CallCenterTransferPayload":
        data = self.model_dump()
        for key in ("call_connection_id", "operation_context", "session_id", "target_override", "confirmation_context"):
            if data.get(key):
                data[key] = data[key].strip()
        return CallCenterTransferPayload(**data)


def _resolve_call_center_target(override: Optional[str]) -> Optional[str]:
    """Resolve the call center destination with optional runtime override."""

    if override:
        stripped = override.strip()
        if stripped:
            return stripped

    env_value = os.environ.get("CALL_CENTER_TRANSFER_TARGET", "").strip()
    if env_value:
        return env_value

    fallback = os.environ.get("VOICELIVE_CALL_CENTER_TARGET", "").strip()
    if fallback:
        return fallback

    return None

def _resolve_call_center_source(override: Optional[str]) -> Optional[str]:
    """Resolve the call center source with optional runtime override."""

    if override:
        stripped = override.strip()
        if stripped:
            return stripped

    env_value = os.environ.get("ACS_SOURCE_PHONE_NUMBER", "").strip()
    if env_value:
        return env_value

    return None


async def transfer_call_to_destination(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the ACS call transfer tool."""

    try:
        payload = TransferCallPayload(**(arguments or {})).sanitized()
    except ValidationError as exc:
        return {
            "success": False,
            "message": "Invalid parameters provided for call transfer.",
            "error": exc.errors(),
        }

    if not payload.call_connection_id:
        return {
            "success": False,
            "message": "No active ACS call to transfer. Try the telephony experience if you need a live representative.",
        }

    operation_context = payload.operation_context or payload.session_id or payload.call_connection_id

    return await transfer_call(
        call_connection_id=payload.call_connection_id,
        target_address=payload.target,
        operation_context=operation_context,
        operation_callback_url=payload.operation_callback_url,
        transferee=payload.transferee,
        sip_headers=payload.sip_headers,
        voip_headers=payload.voip_headers,
        source_caller_id=payload.source_caller_id,
    )


async def transfer_call_to_call_center(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Transfer the current caller to the configured call center destination."""

    try:
        payload = CallCenterTransferPayload(**(arguments or {})).sanitized()
    except ValidationError as exc:
        return {
            "success": False,
            "message": "Invalid parameters provided for call center transfer.",
            "error": exc.errors(),
        }

    if not payload.call_connection_id:
        return {
            "success": False,
            "message": "No active ACS call to route. Please use the telephony experience if you need a live representative.",
        }

    confirmation_context = (payload.confirmation_context or "").strip()
    if not confirmation_context:
        return {
            "success": False,
            "message": (
                "Call center transfer blocked: provide confirmation_context summarizing the caller's explicit request "
                "and your post-clarifier confirmation before invoking this last-resort tool."
            ),
        }

    lowered_context = confirmation_context.lower()
    if not any(
        phrase in lowered_context
        for phrase in ("call center", "live representative", "live agent", "human agent")
    ):
        return {
            "success": False,
            "message": (
                "Call center transfer blocked: confirmation_context must document that the caller insisted on a call center/live representative."
            ),
        }

    target = _resolve_call_center_target(payload.target_override)
    if not target:
        return {
            "success": False,
            "message": "Call center transfer target is not configured. Set CALL_CENTER_TRANSFER_TARGET (or VOICELIVE_CALL_CENTER_TARGET).",
        }

    operation_context = (
        payload.operation_context
        or payload.session_id
        or f"call-center-{payload.call_connection_id}"
    )

    # detemrine if ACS call, if so, then transfer. if not, make a call
    is_acs_call = payload.call_connection_id is not None   

    if is_acs_call:
        result = await transfer_call(
            call_connection_id=payload.call_connection_id,
            target_address=target,
            operation_context=operation_context,
            auto_detect_transferee=True,
        )
    else:
        logging.info("No ACS call connection ID provided; Creating a new ACS call to the contact center.")
        from apps.artagent.backend.api.v1.handlers.acs_call_lifecycle import ACSLifecycleHandler

        acs_source = _resolve_call_center_source()
        acs_handler = ACSLifecycleHandler()
        result = await acs_handler.start_outbound_call(
            target_number=target,
            acs_caller=acs_source,
            
        )

    if result.get("success"):
        result.setdefault(
            "message",
            "Routing you to a live call center representative now.",
        )

    return result


__all__ = [
    "transfer_call_to_destination",
    "transfer_call_to_call_center",
    "TRANSFER_CALL_SCHEMA",
    "TRANSFER_CALL_CENTER_SCHEMA",
]
