"""
ACS Lifecycle Handler - Legacy implementation
==================================================

Azure Communication Services lifecycle management with simplified tracing.

This handler provides call lifecycle operations with:
- Pluggable orchestrator support for conversation engines
- Clean tracing and observability patterns
- Backward compatibility with existing call operations
- Simple error handling and logging
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, List
from datetime import datetime

from azure.communication.callautomation import TextSource, PhoneNumberIdentifier
from azure.core.exceptions import HttpResponseError
from azure.core.messaging import CloudEvent
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from apps.rtagent.backend.settings import (
    ACS_STREAMING_MODE,
    GREETING,
    GREETING_VOICE_TTS,
)
from apps.rtagent.backend.src.shared_ws import broadcast_message

from src.enums.stream_modes import StreamMode
from src.stateful.state_managment import MemoManager

from utils.ml_logging import get_logger

# V1 API specific imports
from .acs_media_lifecycle import ACSMediaHandler

logger = get_logger("api.handlers.acs_lifecycle")
tracer = trace.get_tracer(__name__)


def get_current_time() -> float:
    """Get current time for consistent timing measurements."""
    return time.time()


def safe_set_span_attributes(span, attributes: dict):
    """Safely set span attributes without errors."""
    try:
        if span and span.is_recording():
            span.set_attributes(attributes)
    except Exception as e:
        logger.debug(f"Failed to set span attributes: {e}")


def _safe_get_event_data(event: CloudEvent) -> Dict[str, Any]:
    """
    Safely extract data from CloudEvent object as a dictionary.

    CloudEvent.data can be various types (dict, str, bytes, etc.).
    This function ensures we always get a dictionary we can call .get() on.

    Args:
        event: CloudEvent object from Azure

    Returns:
        Dictionary containing event data, empty dict if parsing fails
    """
    try:
        data = event.data

        # If already a dictionary, return as-is
        if isinstance(data, dict):
            return data

        # If string, try to parse as JSON
        if isinstance(data, str):
            return json.loads(data)

        # If bytes, decode and parse as JSON
        if isinstance(data, bytes):
            return json.loads(data.decode("utf-8"))

        # For other types, try to convert to dict if it has dict-like attributes
        if hasattr(data, "__dict__"):
            return data.__dict__

        # Last resort: return empty dict
        logger.warning(
            f"Unexpected CloudEvent data type: {type(data)}, returning empty dict"
        )
        return {}

    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError) as e:
        logger.error(
            f"Error parsing CloudEvent data: {e}, data type: {type(event.data)}"
        )
        return {}


def _get_event_field(event: CloudEvent, field_name: str, default: Any = None) -> Any:
    """
    Safely get a field from CloudEvent data.

    Args:
        event: CloudEvent object
        field_name: Name of field to extract
        default: Default value if field not found

    Returns:
        Field value or default
    """
    data = _safe_get_event_data(event)
    return data.get(field_name, default)


class ACSLifecycleHandler:
    """
    Azure Communication Services call lifecycle manager.

    Provides call lifecycle operations with:
    - Pluggable orchestrator support for different conversation engines
    - Clean tracing and observability
    - Outbound/inbound call management
    - Event processing with backward compatibility
    """

    def __init__(self, orchestrator_func: Optional[callable] = None):
        """Initialize ACS lifecycle handler."""
        self.orchestrator_func = orchestrator_func
        self.logger = get_logger("api.v1.handlers.acs_lifecycle")

    async def start_outbound_call(
        self,
        acs_caller,
        target_number: str,
        redis_mgr,
        call_id: str = None,
        orchestrator_func: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Initiate an outbound call with orchestrator support.

        Args:
            acs_caller: The ACS caller instance
            target_number: The phone number to call (E.164 format)
            redis_mgr: Redis manager instance for state persistence
            call_id: Optional call ID for tracking (auto-generated if None)
            orchestrator_func: Optional orchestrator for this specific call

        Returns:
            Dict containing call initiation result
        """
        # Use provided orchestrator or fallback to instance orchestrator
        active_orchestrator = orchestrator_func or self.orchestrator_func
        orchestrator_name = (
            getattr(active_orchestrator, "name", "unknown")
            if active_orchestrator
            else "none"
        )

        if not acs_caller:
            raise HTTPException(503, "ACS Caller not initialised")

        with tracer.start_as_current_span(
            "acs_lifecycle.start_outbound_call",
            kind=SpanKind.SERVER,
            attributes={
                "acs.target_number": target_number,
                "acs.call_id": call_id or "auto_generated",
                "acs.orchestrator": orchestrator_name,
                "operation.start_time": get_current_time(),
            },
        ) as span:
            try:
                logger.info(
                    f"🚀 Starting outbound call to {target_number} with orchestrator: {orchestrator_name}"
                )

                start_time = time.perf_counter()
                result = await acs_caller.initiate_call(
                    target_number, stream_mode=ACS_STREAMING_MODE
                )
                latency = time.perf_counter() - start_time

                safe_set_span_attributes(
                    span,
                    {
                        "acs.call_initiation_latency_ms": latency * 1000,
                        "acs.result_status": result.get("status"),
                    },
                )

                if result.get("status") != "created":
                    span.set_status(Status(StatusCode.ERROR, "Call initiation failed"))
                    logger.error(f"❌ Call initiation failed: {result}")
                    return {"status": "failed", "message": "Call initiation failed"}

                call_id = result["call_id"]
                safe_set_span_attributes(
                    span,
                    {
                        "call.connection.id": call_id,
                        "acs.success": True,
                    },
                )

                # Initialize conversation state
                cm = MemoManager.from_redis(session_id=call_id, redis_mgr=redis_mgr)
                cm.update_context("target_number", target_number)
                cm.update_context("orchestrator_name", orchestrator_name)
                cm.persist_to_redis(redis_mgr)

                span.set_status(Status(StatusCode.OK))
                logger.info(
                    f"✅ Call initiated successfully: {call_id} (latency: {latency:.3f}s)"
                )

                return {
                    "status": "success",
                    "message": "Call initiated",
                    "callId": call_id,
                    "orchestrator": orchestrator_name,
                    "initiated_at": datetime.utcnow().isoformat() + "Z",
                }

            except (HttpResponseError, RuntimeError) as exc:
                safe_set_span_attributes(
                    span,
                    {
                        "error.type": type(exc).__name__,
                        "error.message": str(exc),
                    },
                )
                span.set_status(Status(StatusCode.ERROR, f"ACS error: {exc}"))
                logger.error(f"❌ ACS error during call initiation: {exc}")

                raise HTTPException(
                    500,
                    detail={
                        "error": str(exc),
                        "target_number": target_number,
                        "call_id": call_id,
                        "orchestrator": orchestrator_name,
                    },
                ) from exc

            except Exception as exc:
                safe_set_span_attributes(
                    span,
                    {
                        "error.type": type(exc).__name__,
                        "error.message": str(exc),
                    },
                )
                span.set_status(Status(StatusCode.ERROR, f"Unexpected error: {exc}"))
                logger.error(f"❌ Unexpected error during call initiation: {exc}")

                raise HTTPException(
                    400,
                    detail={
                        "error": str(exc),
                        "target_number": target_number,
                        "call_id": call_id,
                        "orchestrator": orchestrator_name,
                    },
                ) from exc

    async def accept_inbound_call(
        self,
        request_body: Dict[str, Any],
        acs_caller,
        orchestrator: Optional[callable] = None,
    ) -> JSONResponse:
        """
        Accept and process inbound call events with orchestrator support.

        Args:
            request_body: Event Grid request body containing events
            acs_caller: The ACS caller instance for call operations
            orchestrator: Optional orchestrator for conversation handling

        Returns:
            JSONResponse with validation response or call acceptance status
        """
        # Use provided orchestrator or fallback to instance orchestrator
        active_orchestrator = orchestrator or self.orchestrator_func
        orchestrator_name = (
            getattr(active_orchestrator, "name", "unknown")
            if active_orchestrator
            else "none"
        )

        with tracer.start_as_current_span(
            "acs_lifecycle.accept_inbound_call",
            kind=SpanKind.SERVER,
            attributes={
                "acs.event_count": len(request_body),
                "acs.orchestrator": orchestrator_name,
                "operation.start_time": get_current_time(),
            },
        ) as span:
            if not acs_caller:
                span.set_status(Status(StatusCode.ERROR, "ACS Caller not initialised"))
                raise HTTPException(503, "ACS Caller not initialised")

            try:
                for idx, event in enumerate(request_body):
                    event_type = event.get("eventType")
                    safe_set_span_attributes(
                        span, {f"acs.event.{idx}.type": event_type}
                    )

                    # Extract event_data from event
                    event_data = event.get("data", {})

                    if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                        # Handle subscription validation event
                        validation_code = event_data.get("validationCode")

                        if validation_code:
                            logger.info(
                                f"✅ Event Grid subscription validation successful"
                            )
                            span.set_status(Status(StatusCode.OK))
                            return JSONResponse(
                                {"validationResponse": validation_code}, status_code=200
                            )
                        else:
                            span.set_status(
                                Status(StatusCode.ERROR, "Validation code not found")
                            )
                            raise HTTPException(
                                400, "Validation code not found in event data"
                            )

                    elif event_type == "Microsoft.Communication.IncomingCall":
                        # Extract caller information from event data
                        if event_data.get("from", {}).get("kind") == "phoneNumber":
                            caller_id = event_data["from"]["phoneNumber"]["value"]
                        else:
                            caller_id = event_data["from"]["rawId"]

                        incoming_call_context = event_data.get("incomingCallContext")

                        safe_set_span_attributes(
                            span,
                            {
                                "call.caller_id": caller_id,
                                "call.from.kind": event_data["from"]["kind"],
                                "operation.subtype": "incoming_call_answer",
                            },
                        )

                        logger.info(
                            f"📞 Processing inbound call from {caller_id} with orchestrator: {orchestrator_name}"
                        )

                        # Answer the incoming call
                        answer_call_result = await acs_caller.answer_incoming_call(
                            incoming_call_context=incoming_call_context,
                            stream_mode=ACS_STREAMING_MODE,
                        )

                        if answer_call_result:
                            call_connection_id = getattr(
                                answer_call_result, "call_connection_id", None
                            )

                            if call_connection_id:
                                safe_set_span_attributes(
                                    span,
                                    {
                                        "call.connection.id": call_connection_id,
                                        "acs.call_answered": True,
                                    },
                                )

                                # Initialize conversation state
                                try:
                                    from src.stateful.state_managment import MemoManager

                                    cm = MemoManager.from_redis(
                                        session_id=call_connection_id,
                                        redis_mgr=getattr(
                                            acs_caller, "redis_mgr", None
                                        ),
                                    )

                                    cm.update_context("caller_id", caller_id)
                                    cm.update_context("call_direction", "inbound")
                                    cm.update_context(
                                        "orchestrator_name", orchestrator_name
                                    )

                                    if (
                                        hasattr(acs_caller, "redis_mgr")
                                        and acs_caller.redis_mgr
                                    ):
                                        cm.persist_to_redis(acs_caller.redis_mgr)

                                except Exception as e:
                                    logger.warning(f"Failed to initialize state: {e}")

                                logger.info(
                                    f"✅ Inbound call answered successfully: {call_connection_id}"
                                )
                            else:
                                logger.warning(
                                    "Call answered but no call_connection_id available"
                                )
                    else:
                        # Handle unhandled events
                        logger.info(f"Received event of type {event_type}: {event}")

                span.set_status(Status(StatusCode.OK))
                logger.info("✅ Inbound call processing completed")

                return JSONResponse(
                    {
                        "status": "call answered",
                        "orchestrator": orchestrator_name,
                    },
                    status_code=200,
                )

            except (HttpResponseError, RuntimeError) as exc:
                safe_set_span_attributes(
                    span,
                    {
                        "error.type": type(exc).__name__,
                        "error.message": str(exc),
                    },
                )
                span.set_status(Status(StatusCode.ERROR, f"ACS error: {exc}"))
                logger.error(f"❌ ACS error during inbound call handling: {exc}")
                raise HTTPException(500, str(exc)) from exc

            except Exception as exc:
                safe_set_span_attributes(
                    span,
                    {
                        "error.type": type(exc).__name__,
                        "error.message": str(exc),
                    },
                )
                span.set_status(Status(StatusCode.ERROR, f"Unexpected error: {exc}"))
                logger.error(
                    f"❌ Unexpected error during inbound call processing: {exc}"
                )
                raise HTTPException(400, "Invalid request body") from exc

    async def process_call_events(
        self, events: list, request, orchestrator: Optional[callable] = None
    ) -> Dict[str, str]:
        """
        Process runtime call events with orchestrator integration.

        Args:
            events: List of ACS webhook events to process
            request: FastAPI request object containing app state dependencies
            orchestrator: Optional orchestrator for event processing

        Returns:
            Dict with processing status and metadata
        """
        # Use provided orchestrator or fallback to instance orchestrator
        active_orchestrator = orchestrator or self.orchestrator_func
        orchestrator_name = (
            getattr(active_orchestrator, "name", "unknown")
            if active_orchestrator
            else "none"
        )

        with tracer.start_as_current_span(
            "acs_lifecycle.process_call_events",
            kind=SpanKind.SERVER,
            attributes={
                "events.count": len(events),
                "acs.orchestrator": orchestrator_name,
                "operation.start_time": get_current_time(),
            },
        ) as span:
            logger.info(
                f"📋 Processing {len(events)} call events with orchestrator: {orchestrator_name}"
            )

            try:
                # Import and delegate to the legacy event processor
                # This maintains backward compatibility while adding enterprise features
                from apps.rtagent.backend.src.handlers.acs_event_handlers import (
                    process_call_events,
                )

                result = await process_call_events(events, request)

                # Enhance result with metadata
                enhanced_result = {
                    **result,
                    "orchestrator_used": orchestrator_name,
                    "processed_at": datetime.utcnow().isoformat() + "Z",
                }

                safe_set_span_attributes(
                    span,
                    {
                        "events.processed": result.get("processed_events", 0),
                        "operation.success": True,
                    },
                )

                span.set_status(Status(StatusCode.OK))
                logger.info(
                    f"✅ Processed {result.get('processed_events', 0)} events successfully"
                )

                return enhanced_result

            except Exception as exc:
                safe_set_span_attributes(
                    span,
                    {
                        "error.type": type(exc).__name__,
                        "error.message": str(exc),
                    },
                )
                span.set_status(
                    Status(StatusCode.ERROR, f"Event processing error: {exc}")
                )
                logger.error(f"❌ Error processing call events: {exc}")

                return {
                    "status": "error",
                    "error": str(exc),
                    "orchestrator_used": orchestrator_name,
                    "processed_at": datetime.utcnow().isoformat() + "Z",
                }


# Utility functions for ACS operations
def get_participant_phone(event: CloudEvent, cm: MemoManager) -> Optional[str]:
    """
    Extract participant phone number from event.

    Args:
        event: CloudEvent containing participant information
        cm: MemoManager for context access

    Returns:
        Participant phone number or None if not found
    """

    def digits_tail(s: Optional[str], n: int = 10) -> str:
        return "".join(ch for ch in (s or "") if ch.isdigit())[-n:]

    participants = _get_event_field(event, "participants", []) or []
    target_number = cm.get_context("target_number")
    target_tail = digits_tail(target_number) if target_number else ""

    pstn_candidates = []
    for p in participants:
        ident = p.get("identifier", {}) or {}
        # prefer explicit phone number
        phone = (ident.get("phoneNumber") or {}).get("value")
        # fallback: rawId like "4:+12246234441"
        if not phone:
            raw = ident.get("rawId")
            if isinstance(raw, str) and raw.startswith("4:"):
                phone = raw[2:]
        if phone:
            pstn_candidates.append(phone)

    if not pstn_candidates:
        return None

    if target_tail:
        for ph in pstn_candidates:
            if digits_tail(ph) == target_tail:
                return ph

    # fallback to first PSTN participant
    return pstn_candidates[0]


def create_enterprise_media_handler(
    websocket,
    orchestrator: callable,
    call_connection_id: str,
    recognizer,
    cm: MemoManager,
    session_id: str,
) -> ACSMediaHandler:
    """
    Factory function for creating media handlers.

    Args:
        websocket: WebSocket connection
        orchestrator: Conversation orchestrator
        call_connection_id: ACS call connection ID
        recognizer: Speech recognition client
        cm: Conversation memory manager
        session_id: Session identifier

    Returns:
        Configured ACSMediaHandler instance
    """
    return ACSMediaHandler(
        ws=websocket,
        orchestrator=orchestrator,
        call_connection_id=call_connection_id,
        recognizer=recognizer,
        cm=cm,
        session_id=session_id,
    )
