"""
V1 Call Event Handlers
======================

Event handlers migrated from legacy acs_event_handlers.py and adapted for V1 Event Processor pattern.
Focuses on core business logic without complex event registration overhead.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from azure.core.messaging import CloudEvent

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from apps.rtagent.backend.src.shared_ws import broadcast_message
from utils.ml_logging import get_logger
from .types import CallEventContext, ACSEventTypes

logger = get_logger("v1.events.handlers")
tracer = trace.get_tracer(__name__)


class CallEventHandlers:
    """
    Event handlers for Azure Communication Services call events.

    Centralized handlers for ALL call lifecycle events including:
    - API-initiated operations (call initiation, answering)
    - ACS webhook events (connected, disconnected, etc.)
    - Media and recognition events
    """

    @staticmethod
    async def handle_call_initiated(context: CallEventContext) -> None:
        """Handle call initiation events from API operations."""
        with tracer.start_as_current_span(
            "v1.handle_call_initiated",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            logger.info(f"🚀 Call initiated: {context.call_connection_id}")

            # Log call initiation details
            event_data = context.get_event_data()
            target_number = event_data.get("target_number")
            api_version = event_data.get("api_version", "unknown")

            logger.info(f"   Target: {target_number}, API: {api_version}")

            # Initialize call tracking and state
            if context.memo_manager:
                try:
                    context.memo_manager.update_context("call_initiated_via", "api")
                    context.memo_manager.update_context("api_version", api_version)
                    context.memo_manager.update_context("call_direction", "outbound")
                    if target_number:
                        context.memo_manager.update_context(
                            "target_number", target_number
                        )
                    if context.redis_mgr:
                        context.memo_manager.persist_to_redis(context.redis_mgr)
                except Exception as e:
                    logger.error(f"Failed to update call state: {e}")

    @staticmethod
    async def handle_inbound_call_received(context: CallEventContext) -> None:
        """Handle inbound call events from Event Grid webhooks."""
        with tracer.start_as_current_span(
            "v1.handle_inbound_call_received",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            event_data = context.get_event_data()
            caller_info = event_data.get("from", {})
            caller_id = CallEventHandlers._extract_caller_id(caller_info)

            logger.info(f"📞 Inbound call received from {caller_id}")

            # Initialize inbound call state
            if context.memo_manager:
                try:
                    context.memo_manager.update_context("call_direction", "inbound")
                    context.memo_manager.update_context("caller_id", caller_id)
                    context.memo_manager.update_context("caller_info", caller_info)
                    context.memo_manager.update_context("api_version", "v1")
                    if context.redis_mgr:
                        context.memo_manager.persist_to_redis(context.redis_mgr)
                except Exception as e:
                    logger.error(f"Failed to initialize inbound call state: {e}")

    @staticmethod
    async def handle_call_answered(context: CallEventContext) -> None:
        """Handle call answered events (both inbound and outbound)."""
        with tracer.start_as_current_span(
            "v1.handle_call_answered",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            logger.info(f"📞 Call answered: {context.call_connection_id}")

            # Update call state with answer information
            if context.memo_manager:
                try:
                    from datetime import datetime

                    context.memo_manager.update_context("call_answered", True)
                    context.memo_manager.update_context(
                        "answered_at", datetime.utcnow().isoformat() + "Z"
                    )
                    if context.redis_mgr:
                        context.memo_manager.persist_to_redis(context.redis_mgr)
                except Exception as e:
                    logger.error(f"Failed to update call answer state: {e}")

    @staticmethod
    async def handle_webhook_events(context: CallEventContext) -> None:
        """
        Handle all ACS webhook events that come through callbacks endpoint.

        This is the central handler for events from /callbacks endpoint,
        routing them to specific handlers based on event type.
        """
        with tracer.start_as_current_span(
            "v1.handle_webhook_events",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
                "event.source": "acs_webhook",
            },
        ):
            logger.info(f"🔗 Processing webhook event: {context.event_type}")

            # Route to specific handlers based on event type
            from .types import ACSEventTypes

            if context.event_type == ACSEventTypes.CALL_CONNECTED:
                await CallEventHandlers.handle_call_connected(context)
            elif context.event_type == ACSEventTypes.CALL_DISCONNECTED:
                await CallEventHandlers.handle_call_disconnected(context)
            elif context.event_type == ACSEventTypes.PARTICIPANTS_UPDATED:
                await CallEventHandlers.handle_participants_updated(context)
            elif context.event_type == ACSEventTypes.DTMF_TONE_RECEIVED:
                await CallEventHandlers.handle_dtmf_tone_received(context)
            elif context.event_type == ACSEventTypes.PLAY_COMPLETED:
                await CallEventHandlers.handle_play_completed(context)
            elif context.event_type == ACSEventTypes.PLAY_FAILED:
                await CallEventHandlers.handle_play_failed(context)
            elif context.event_type == ACSEventTypes.RECOGNIZE_COMPLETED:
                await CallEventHandlers.handle_recognize_completed(context)
            elif context.event_type == ACSEventTypes.RECOGNIZE_FAILED:
                await CallEventHandlers.handle_recognize_failed(context)
            elif context.event_type == ACSEventTypes.CREATE_CALL_FAILED:
                await CallEventHandlers.handle_create_call_failed(context)
            elif context.event_type == ACSEventTypes.ANSWER_CALL_FAILED:
                await CallEventHandlers.handle_answer_call_failed(context)
            else:
                logger.info(
                    f"🔍 No specific handler for event type: {context.event_type}"
                )

            # Update general webhook processing stats
            if context.memo_manager:
                try:
                    webhook_count = context.memo_manager.get_context(
                        "webhook_events_processed", 0
                    )
                    context.memo_manager.update_context(
                        "webhook_events_processed", webhook_count + 1
                    )
                    context.memo_manager.update_context(
                        "last_webhook_event", context.event_type
                    )
                    if context.redis_mgr:
                        context.memo_manager.persist_to_redis(context.redis_mgr)
                except Exception as e:
                    logger.error(f"Failed to update webhook stats: {e}")

    @staticmethod
    async def handle_call_connected(context: CallEventContext) -> None:
        """Handle call connected event - broadcast status and play greeting."""
        with tracer.start_as_current_span(
            "v1.handle_call_connected",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            logger.info(f"📞 Call connected: {context.call_connection_id}")

            # Broadcast connection status to WebSocket clients
            try:
                if context.clients:
                    await broadcast_message(
                        context.clients,
                        json.dumps(
                            {
                                "type": "call_connected",
                                "call_connection_id": context.call_connection_id,
                                "timestamp": context.get_event_data()
                                .get("callConnectionProperties", {})
                                .get("connectedTime"),
                            }
                        ),
                    )
            except Exception as e:
                logger.error(f"Failed to broadcast call connected: {e}")

            # Play greeting if in transcription mode
            if context.memo_manager:
                stream_mode = context.memo_manager.get_context("stream_mode", "media")
                if stream_mode == "transcription":
                    await CallEventHandlers._play_greeting(context)

    @staticmethod
    async def handle_call_disconnected(context: CallEventContext) -> None:
        """Handle call disconnected event - log reason and cleanup."""
        with tracer.start_as_current_span(
            "v1.handle_call_disconnected",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            disconnect_reason = context.get_event_field(
                "resultInformation", "No reason provided"
            )
            logger.info(
                f"📞 Call disconnected: {context.call_connection_id}, reason: {disconnect_reason}"
            )

            # Cleanup call state
            if context.memo_manager:
                await CallEventHandlers._cleanup_call_state(context)

    @staticmethod
    async def handle_create_call_failed(context: CallEventContext) -> None:
        """Handle create call failed event - log error details."""
        with tracer.start_as_current_span(
            "v1.handle_create_call_failed",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            result_info = context.get_event_field("resultInformation", {})
            error_code = result_info.get("code", "Unknown")
            error_message = result_info.get("message", "No details provided")

            logger.error(f"❌ Create call failed: {context.call_connection_id}")
            logger.error(f"   Error Code: {error_code}")
            logger.error(f"   Error Message: {error_message}")

            # Update context with failure information
            if context.memo_manager:
                try:
                    context.memo_manager.update_context("call_creation_failed", True)
                    context.memo_manager.update_context("failure_reason", error_message)
                    context.memo_manager.update_context("failure_code", error_code)
                    if context.redis_mgr:
                        context.memo_manager.persist_to_redis(context.redis_mgr)
                except Exception as e:
                    logger.error(f"Failed to update failure state: {e}")

    @staticmethod
    async def handle_answer_call_failed(context: CallEventContext) -> None:
        """Handle answer call failed event - log error details."""
        with tracer.start_as_current_span(
            "v1.handle_answer_call_failed",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            result_info = context.get_event_field("resultInformation", {})
            error_code = result_info.get("code", "Unknown")
            error_message = result_info.get("message", "No details provided")

            logger.error(f"❌ Answer call failed: {context.call_connection_id}")
            logger.error(f"   Error Code: {error_code}")
            logger.error(f"   Error Message: {error_message}")

            # Update context with failure information
            if context.memo_manager:
                try:
                    context.memo_manager.update_context("call_answer_failed", True)
                    context.memo_manager.update_context("failure_reason", error_message)
                    context.memo_manager.update_context("failure_code", error_code)
                    if context.redis_mgr:
                        context.memo_manager.persist_to_redis(context.redis_mgr)
                except Exception as e:
                    logger.error(f"Failed to update answer failure state: {e}")

    @staticmethod
    async def handle_participants_updated(context: CallEventContext) -> None:
        """Handle participant updates and start DTMF recognition."""
        with tracer.start_as_current_span(
            "v1.handle_participants_updated",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            logger.info(f"👥 Participants updated: {context.call_connection_id}")

            try:
                # Extract participant phone number
                target_phone = CallEventHandlers._get_participant_phone(
                    context.event, context.memo_manager
                )

                # if target_phone and context.acs_caller:
                #     # Start DTMF recognition as background task
                #     asyncio.create_task(
                #         CallEventHandlers._start_dtmf_recognition(context, target_phone)
                #     )
                #     logger.info(f"🎯 Started DTMF recognition for {target_phone}")

            except Exception as e:
                logger.error(f"Error in participants updated handler: {e}")

    @staticmethod
    async def handle_dtmf_tone_received(context: CallEventContext) -> None:
        """Handle DTMF tone with sequence validation."""
        with tracer.start_as_current_span(
            "v1.handle_dtmf_tone_received",
            kind=SpanKind.INTERNAL,
            attributes={
                "call.connection.id": context.call_connection_id,
                "event.type": context.event_type,
            },
        ):
            tone = context.get_event_field("tone")
            sequence_id = context.get_event_field("sequenceId")

            logger.info(f"🔢 DTMF tone received: {tone}, sequence_id: {sequence_id}")

            # Normalize and process tone
            normalized_tone = CallEventHandlers._normalize_tone(tone)
            if normalized_tone and context.memo_manager:
                CallEventHandlers._update_dtmf_sequence(
                    context, normalized_tone, sequence_id
                )

    @staticmethod
    async def handle_play_completed(context: CallEventContext) -> None:
        """Handle play completed event."""
        logger.info(f"🎵 Play completed: {context.call_connection_id}")

    @staticmethod
    async def handle_play_failed(context: CallEventContext) -> None:
        """Handle play failed event."""
        result_info = context.get_event_field("resultInformation", {})
        logger.error(
            f"🎵 Play failed: {context.call_connection_id}, reason: {result_info}"
        )

    @staticmethod
    async def handle_recognize_completed(context: CallEventContext) -> None:
        """Handle recognize completed event."""
        logger.info(f"🎤 Recognize completed: {context.call_connection_id}")

    @staticmethod
    async def handle_recognize_failed(context: CallEventContext) -> None:
        """Handle recognize failed event."""
        result_info = context.get_event_field("resultInformation", {})
        logger.error(
            f"🎤 Recognize failed: {context.call_connection_id}, reason: {result_info}"
        )

    # ============================================================================
    # Helper Methods (adapted from legacy implementation)
    # ============================================================================

    @staticmethod
    def _extract_caller_id(caller_info: Dict[str, Any]) -> str:
        """Extract caller ID from caller information."""
        if caller_info.get("kind") == "phoneNumber":
            return caller_info.get("phoneNumber", {}).get("value", "unknown")
        return caller_info.get("rawId", "unknown")

    @staticmethod
    async def _play_greeting(context: CallEventContext) -> None:
        """Play greeting to connected call."""
        try:
            if not context.acs_caller or not context.memo_manager:
                return

            from apps.rtagent.backend.settings import GREETING, GREETING_VOICE_TTS
            from azure.communication.callautomation import TextSource

            # Create greeting source
            text_source = TextSource(
                text=GREETING,
                voice_name=GREETING_VOICE_TTS,
                custom_voice_endpoint_id=None,
            )

            # Play greeting
            await context.acs_caller.play_to_all(
                context.call_connection_id, text_source
            )

            logger.info(f"🎵 Greeting played to call {context.call_connection_id}")

        except Exception as e:
            logger.error(f"Failed to play greeting: {e}")

    @staticmethod
    async def _cleanup_call_state(context: CallEventContext) -> None:
        """Clean up call state when call disconnects."""
        try:
            if context.memo_manager and context.redis_mgr:
                # Persist final state before cleanup
                context.memo_manager.persist_to_redis(context.redis_mgr)
                logger.info(f"🧹 Call state cleaned up for {context.call_connection_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup call state: {e}")

    @staticmethod
    def _get_participant_phone(
        event: CloudEvent, memo_manager: Optional[Any]
    ) -> Optional[str]:
        """Extract participant phone number from event."""
        try:
            event_data = CallEventHandlers._safe_get_event_data(event)
            participants = event_data.get("participants", [])

            def digits_tail(s: Optional[str], n: int = 10) -> str:
                return "".join(ch for ch in (s or "") if ch.isdigit())[-n:]

            # Get target number from context
            target_number = None
            if memo_manager:
                target_number = memo_manager.get_context("target_number")
            target_tail = digits_tail(target_number) if target_number else ""

            # Find PSTN participants
            pstn_candidates = []
            for participant in participants:
                identifier = participant.get("identifier", {})

                # Try phoneNumber field first
                phone = identifier.get("phoneNumber", {}).get("value")

                # Fallback to rawId parsing (format: "4:+12345678901")
                if not phone:
                    raw_id = identifier.get("rawId", "")
                    if isinstance(raw_id, str) and raw_id.startswith("4:"):
                        phone = raw_id[2:]  # Remove "4:" prefix

                if phone:
                    pstn_candidates.append(phone)

            if not pstn_candidates:
                return None

            # Match with target number if available
            if target_tail:
                for phone in pstn_candidates:
                    if digits_tail(phone) == target_tail:
                        return phone

            # Return first PSTN participant
            return pstn_candidates[0]

        except Exception as e:
            logger.error(f"Error extracting participant phone: {e}")
            return None

    @staticmethod
    async def _start_dtmf_recognition(
        context: CallEventContext, target_phone: str
    ) -> None:
        """Start DTMF recognition for participant."""
        try:
            if context.acs_caller:
                call_conn = context.acs_caller.get_call_connection(
                    context.call_connection_id
                )
                if not call_conn:
                    logger.error(
                        "Call connection not found for %s", context.call_connection_id
                    )
                    return

                await call_conn.start_continuous_dtmf_recognition(
                    context.call_connection_id, target_phone
                )
                logger.info(f"🔢 DTMF recognition started for {target_phone}")
        except Exception as e:
            logger.error(f"Failed to start DTMF recognition: {e}")

    @staticmethod
    def _normalize_tone(tone: str) -> Optional[str]:
        """Normalize DTMF tone to standard format."""
        if not tone:
            return None

        tone_str = str(tone).strip().lower()

        tone_map = {
            "0": "0",
            "zero": "0",
            "1": "1",
            "one": "1",
            "2": "2",
            "two": "2",
            "3": "3",
            "three": "3",
            "4": "4",
            "four": "4",
            "5": "5",
            "five": "5",
            "6": "6",
            "six": "6",
            "7": "7",
            "seven": "7",
            "8": "8",
            "eight": "8",
            "9": "9",
            "nine": "9",
            "*": "*",
            "star": "*",
            "asterisk": "*",
            "#": "#",
            "pound": "#",
            "hash": "#",
        }

        normalized = tone_map.get(tone_str)
        return (
            normalized
            if normalized
            in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#"}
            else None
        )

    @staticmethod
    def _update_dtmf_sequence(
        context: CallEventContext, tone: str, sequence_id: Optional[int]
    ) -> None:
        """Update DTMF sequence in memory."""
        if not context.memo_manager:
            return

        current_sequence = context.memo_manager.get_context("dtmf_sequence", "")

        # Handle special tones
        if tone == "#":
            # End sequence - validate
            if current_sequence:
                CallEventHandlers._validate_sequence(context, current_sequence)
            return
        elif tone == "*":
            # Clear sequence
            context.memo_manager.update_context("dtmf_sequence", "")
            if context.redis_mgr:
                context.memo_manager.persist_to_redis(context.redis_mgr)
            logger.info(f"🔢 DTMF sequence cleared for {context.call_connection_id}")
            return

        # Handle sequence ordering
        if sequence_id is not None:
            seq_index = sequence_id - 1  # 1-based to 0-based
            dtmf_list = list(current_sequence)

            # Expand list if needed
            while len(dtmf_list) <= seq_index:
                dtmf_list.append("")

            dtmf_list[seq_index] = tone
            new_sequence = "".join(dtmf_list)
        else:
            # Append to end
            new_sequence = current_sequence + tone

        # Update context
        context.memo_manager.update_context("dtmf_sequence", new_sequence)
        if context.redis_mgr:
            context.memo_manager.persist_to_redis(context.redis_mgr)

        logger.info(f"🔢 DTMF sequence updated: {new_sequence}")

    @staticmethod
    def _validate_sequence(context: CallEventContext, sequence: str) -> None:
        """Validate DTMF sequence."""
        if not context.memo_manager:
            return

        # Simple validation - 4-digit PIN
        is_valid = len(sequence) == 4 and sequence.isdigit()

        # Update context
        context.memo_manager.update_context("dtmf_sequence", "")
        context.memo_manager.update_context("dtmf_validated", is_valid)
        context.memo_manager.update_context(
            "entered_pin", sequence if is_valid else None
        )

        if context.redis_mgr:
            context.memo_manager.persist_to_redis(context.redis_mgr)

        logger.info(
            f"🔢 DTMF sequence {'validated' if is_valid else 'rejected'}: {sequence}"
        )

    @staticmethod
    def _safe_get_event_data(event: CloudEvent) -> Dict[str, Any]:
        """Safely extract event data as dictionary."""
        try:
            data = event.data
            if isinstance(data, dict):
                return data
            elif isinstance(data, str):
                return json.loads(data)
            elif isinstance(data, bytes):
                return json.loads(data.decode("utf-8"))
            elif hasattr(data, "__dict__"):
                return data.__dict__
            else:
                return {}
        except Exception:
            return {}
