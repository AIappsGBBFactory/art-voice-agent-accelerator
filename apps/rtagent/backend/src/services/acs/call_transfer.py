"""ACS call transfer helpers centralised for VoiceLive and ACS handlers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from azure.communication.callautomation import (
    CallAutomationClient,
    CallConnectionClient,
    CommunicationIdentifier,
    PhoneNumberIdentifier,
)
from azure.core.exceptions import HttpResponseError
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from apps.rtagent.backend.src.services.acs.acs_caller import initialize_acs_caller_instance
from src.acs.acs_helper import AcsCaller
from utils.ml_logging import get_logger

logger = get_logger("services.acs.call_transfer")
tracer = trace.get_tracer(__name__)


@dataclass(frozen=True)
class TransferRequest:
    """Normalized payload for initiating an ACS call transfer."""

    call_connection_id: str
    target_address: str
    operation_context: Optional[str] = None
    operation_callback_url: Optional[str] = None
    transferee: Optional[str] = None
    sip_headers: Optional[Mapping[str, str]] = None
    voip_headers: Optional[Mapping[str, str]] = None
    source_caller_id: Optional[str] = None


def _build_target_identifier(target: str) -> CommunicationIdentifier:
    """Convert a transfer target string into the appropriate ACS identifier."""

    normalized = (target or "").strip()
    if not normalized:
        raise ValueError("Transfer target must be a non-empty string.")
    if normalized.lower().startswith("sip:"):
        return PhoneNumberIdentifier(normalized)
    return PhoneNumberIdentifier(normalized)


def _build_optional_phone(number: Optional[str]) -> Optional[PhoneNumberIdentifier]:
    if not number:
        return None
    return PhoneNumberIdentifier(number)


def _build_optional_target(target: Optional[str]) -> Optional[CommunicationIdentifier]:
    if not target:
        return None
    return _build_target_identifier(target)


def _prepare_transfer_args(request: TransferRequest) -> Tuple[str, Dict[str, Any]]:
    identifier = _build_target_identifier(request.target_address)
    kwargs: Dict[str, Any] = {}
    if request.operation_context:
        kwargs["operation_context"] = request.operation_context
    if request.operation_callback_url:
        kwargs["operation_callback_url"] = request.operation_callback_url
    transferee_identifier = _build_optional_target(request.transferee)
    if transferee_identifier:
        kwargs["transferee"] = transferee_identifier
    if request.sip_headers:
        kwargs["sip_headers"] = dict(request.sip_headers)
    if request.voip_headers:
        kwargs["voip_headers"] = dict(request.voip_headers)
    source_identifier = _build_optional_phone(request.source_caller_id)
    if source_identifier:
        kwargs["source_caller_id_number"] = source_identifier
    return request.call_connection_id, {"target": identifier, "kwargs": kwargs}


async def _invoke_transfer(
    *,
    call_conn: CallConnectionClient,
    identifier: CommunicationIdentifier,
    kwargs: Dict[str, Any],
) -> Any:
    return await asyncio.to_thread(call_conn.transfer_call_to_participant, identifier, **kwargs)


async def transfer_call(
    *,
    call_connection_id: str,
    target_address: str,
    operation_context: Optional[str] = None,
    operation_callback_url: Optional[str] = None,
    transferee: Optional[str] = None,
    sip_headers: Optional[Mapping[str, str]] = None,
    voip_headers: Optional[Mapping[str, str]] = None,
    source_caller_id: Optional[str] = None,
    acs_caller: Optional[AcsCaller] = None,
    acs_client: Optional[CallAutomationClient] = None,
    call_connection: Optional[CallConnectionClient] = None,
) -> Dict[str, Any]:
    """Transfer the active ACS call to the specified target participant."""

    if not call_connection_id:
        return {"success": False, "message": "call_connection_id is required for call transfer."}
    if not target_address:
        return {"success": False, "message": "target address is required for call transfer."}

    caller = acs_caller or initialize_acs_caller_instance()
    client = acs_client or (caller.client if caller else None)
    if not client and not call_connection:
        return {"success": False, "message": "ACS CallAutomationClient is not configured."}

    conn = call_connection or client.get_call_connection(call_connection_id)
    if conn is None:
        return {"success": False, "message": f"Call connection '{call_connection_id}' is not available."}

    request = TransferRequest(
        call_connection_id=call_connection_id,
        target_address=target_address,
        operation_context=operation_context,
        operation_callback_url=operation_callback_url,
        transferee=transferee,
        sip_headers=sip_headers,
        voip_headers=voip_headers,
        source_caller_id=source_caller_id,
    )

    try:
        connection_id, prepared = _prepare_transfer_args(request)
    except ValueError as exc:
        logger.warning("Invalid call transfer parameters: %s", exc)
        return {"success": False, "message": str(exc)}

    attributes = {
        "call.connection.id": connection_id,
        "transfer.target": target_address,
    }
    if request.transferee:
        attributes["transfer.transferee"] = request.transferee

    with tracer.start_as_current_span(
        "acs.transfer_call",
        kind=SpanKind.CLIENT,
        attributes=attributes,
    ) as span:
        try:
            result = await _invoke_transfer(
                call_conn=conn,
                identifier=prepared["target"],
                kwargs=prepared["kwargs"],
            )
        except HttpResponseError as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.error(
                "ACS transfer failed | call=%s target=%s error=%s",
                connection_id,
                target_address,
                exc,
            )
            return {
                "success": False,
                "message": "Call transfer failed due to an ACS error.",
                "error": str(exc),
            }
        except Exception as exc:  # pragma: no cover - defensive
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception(
                "Unexpected error during ACS transfer | call=%s target=%s",
                connection_id,
                target_address,
            )
            return {
                "success": False,
                "message": "Call transfer encountered an unexpected error.",
                "error": str(exc),
            }

        status_value = getattr(result, "status", "unknown")
        operation_context_value = getattr(result, "operation_context", operation_context)
        span.set_status(Status(StatusCode.OK))

        logger.info(
            "ACS transfer initiated | call=%s target=%s status=%s",
            connection_id,
            target_address,
            status_value,
        )

        return {
            "success": True,
            "message": f"Transferring the caller to {target_address}.",
            "call_transfer": {
                "status": str(status_value),
                "operation_context": operation_context_value,
                "target": target_address,
                "transferee": transferee,
            },
            "should_interrupt_playback": True,
            "terminate_session": True,
        }


__all__ = ["transfer_call"]
