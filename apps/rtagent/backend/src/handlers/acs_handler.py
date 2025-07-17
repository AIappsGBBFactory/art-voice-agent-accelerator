"""
handlers/acs_handler.py
=======================
Business logic handlers for Azure Communication Services operations.

This module contains the core business logic extracted from the ACS router,
following the separation of concerns principle. The router handles HTTP/WebSocket
routing while this handler manages the actual ACS business operations.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from azure.communication.callautomation import TextSource
from azure.core.exceptions import HttpResponseError
from azure.core.messaging import CloudEvent
from fastapi import HTTPException, WebSocket
from fastapi.responses import JSONResponse
from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.src.orchestration.orchestrator import route_turn
from apps.rtagent.backend.settings import ACS_STREAMING_MODE
from apps.rtagent.backend.src.shared_ws import broadcast_message

from src.enums.stream_modes import StreamMode
from utils.ml_logging import get_logger

logger = get_logger("handlers.acs_handler")


class ACSHandler:
    """
    Handles Azure Communication Services business logic operations.

    This class encapsulates the core business logic for:
    - Call initiation and management
    - Event processing from ACS callbacks
    - WebSocket transcription handling
    - Media event processing
    """

    @staticmethod
    async def initiate_call(
        acs_caller, target_number: str, redis_mgr, call_id: str = None
    ) -> Dict[str, Any]:
        """
        Initiate an outbound call through Azure Communication Services.

        Args:
            acs_caller: The ACS caller instance
            target_number: The phone number to call
            redis_mgr: Redis manager instance
            call_id: Optional call ID for tracking

        Returns:
            Dict containing call initiation result

        Raises:
            HTTPException: If call initiation fails
        """
        if not acs_caller:
            raise HTTPException(503, "ACS Caller not initialised")

        try:
            # TODO: Add logic to reject multiple requests for the same target number
            result = await acs_caller.initiate_call(
                target_number, stream_mode=ACS_STREAMING_MODE
            )
            if result.get("status") != "created":
                return {"status": "failed", "message": "Call initiation failed"}

            call_id = result["call_id"]

            # Initialize conversation state
            cm = MemoManager.from_redis(
                session_id=call_id,
                redis_mgr=redis_mgr,
            )
            cm.update_context("target_number", target_number)
            cm.persist_to_redis(redis_mgr)

            logger.info("Call initiated – ID=%s", call_id)
            return {"status": "success", "message": "Call initiated", "callId": call_id}

        except (HttpResponseError, RuntimeError) as exc:
            logger.error("ACS error: %s", exc, exc_info=True)
            raise HTTPException(500, str(exc)) from exc

    @staticmethod
    async def handle_inbound_call(
        request_body: Dict[str, Any], acs_caller
    ) -> JSONResponse:
        """
        Handle inbound call events and subscription validation.

        Args:
            request_body: The request body containing events
            acs_caller: The ACS caller instance

        Returns:
            JSONResponse with appropriate status
        """
        if not acs_caller:
            raise HTTPException(503, "ACS Caller not initialised")

        try:
            for event in request_body:
                event_type = event.get("eventType")
                if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                    # Handle subscription validation event
                    validation_code = event.get("data", {}).get("validationCode")
                    if validation_code:
                        return JSONResponse(
                            {"validationResponse": validation_code}, status_code=200
                        )
                    else:
                        raise HTTPException(
                            400, "Validation code not found in event data"
                        )
                elif event_type == "Microsoft.Communication.IncomingCall":
                    # Convert CloudEvent to dict for processing
                    event = dict(event)
                    event_data = event.get("data", {})
                    # logger.info("Incoming call received: data=%s", event_data)

                    if event_data["from"]["kind"] == "phoneNumber":
                        caller_id = event_data["from"]["phoneNumber"]["value"]
                    else:
                        caller_id = event_data["from"]["rawId"]
                    logger.info("incoming call handler caller id: %s", caller_id)

                    incoming_call_context = event_data["incomingCallContext"]
                    # query_parameters = urlencode({"callerId": caller_id})
                    answer_call_result = await acs_caller.answer_incoming_call(
                        incoming_call_context=incoming_call_context,
                        stream_mode=ACS_STREAMING_MODE,
                    )
                    # participants = event.data.get("participants", [])
                    # target_number = cm.get_context("target_number")
                    # target_joined = any(
                    #     p.get("identifier", {}).get("rawId", "").endswith(target_number or "")
                    #     for p in participants
                    # ) if target_number else False
                    # cm.update_context("target_participant_joined", target_joined)
                    # cm.persist_to_redis(redis_mgr)
                    if answer_call_result:
                        call_connection_id = getattr(
                            answer_call_result, "call_connection_id", None
                        )
                        if call_connection_id:
                            logger.info("Call answered: %s", call_connection_id)
                        else:
                            logger.warning(
                                "Call answered but no call_connection_id available: %s",
                                answer_call_result,
                            )
                else:
                    logger.info(f"Received event of type {event_type}: {event}")

            return JSONResponse({"status": "call answered"}, status_code=200)

        except (HttpResponseError, RuntimeError) as exc:
            logger.error("ACS error: %s", exc, exc_info=True)
            raise HTTPException(500, str(exc)) from exc
        except Exception as exc:
            logger.error("Error processing inbound call: %s", exc, exc_info=True)
            raise HTTPException(400, "Invalid request body") from exc

    @staticmethod
    async def process_callback_events(events: list, request) -> Dict[str, str]:
        """
        Process callback events from Azure Communication Services.

        Args:
            events: List of ACS events to process
            request: FastAPI request object containing app state

        Returns:
            Dict with processing status
        """
        # Derive dependencies from request app state
        acs_caller = request.app.state.acs_caller
        stt_client = request.app.state.stt_client
        redis_mgr = request.app.state.redis
        clients = request.app.state.clients

        # Event handler mapping for cleaner code organization
        event_handlers = {
            "Microsoft.Communication.ParticipantsUpdated": ACSHandler._handle_participants_updated,
            "Microsoft.Communication.CallConnected": ACSHandler._handle_call_connected,
            "Microsoft.Communication.TranscriptionFailed": ACSHandler._handle_transcription_failed,
            "Microsoft.Communication.CallDisconnected": ACSHandler._handle_call_disconnected,
        }

        # Media events that update bot_speaking context
        media_events = {
            "Microsoft.Communication.PlayStarted": True,
            "Microsoft.Communication.PlayCompleted": False,
            "Microsoft.Communication.PlayFailed": False,
            "Microsoft.Communication.PlayCanceled": False,
            "Microsoft.Communication.MediaStreamingFailed": False,
        }

        try:
            for raw in events:
                event = CloudEvent.from_dict(raw)
                etype = event.type
                cid = event.data.get("callConnectionId")
                cm = MemoManager.from_redis(cid, redis_mgr)

                # Handle specific events with dedicated handlers
                if etype in event_handlers:
                    handler = event_handlers[etype]
                    if etype == "Microsoft.Communication.CallConnected":
                        await handler(
                            event, cm, redis_mgr, clients, cid, acs_caller, stt_client
                        )
                    elif etype in ["Microsoft.Communication.ParticipantsUpdated"]:
                        await handler(event, cm, redis_mgr, clients, cid)
                    elif etype == "Microsoft.Communication.TranscriptionFailed":
                        await handler(event, cm, redis_mgr, cid, acs_caller)
                    elif etype == "Microsoft.Communication.CallDisconnected":
                        await handler(event, cm, redis_mgr, cid)

                # Handle media events that affect bot_speaking state
                elif etype in media_events:
                    cm.update_context("bot_speaking", media_events[etype])
                    action = "Set" if media_events[etype] else "Set"
                    logger.info(
                        f"{etype.split('.')[-1]}: {action} bot_speaking={media_events[etype]} for call {cm.session_id}"
                    )

                    # Log errors for failed events
                    if "Failed" in etype:
                        reason = event.data.get("resultInformation", "Unknown reason")
                        logger.error(
                            f"⚠️ {etype.split('.')[-1]} for call {cid}: {reason}"
                        )

                # Handle other failed events
                elif "Failed" in etype:
                    reason = event.data.get("resultInformation", "Unknown reason")
                    logger.error("⚠️ %s for call %s: %s", etype, cid, reason)

                # Log unhandled events
                else:
                    logger.info("Unhandled event: %s for call %s", etype, cid)

                cm.persist_to_redis(redis_mgr)

            return {"status": "callback received"}

        except Exception as exc:
            logger.error("Callback error: %s", exc, exc_info=True)
            return {"error": str(exc)}

    @staticmethod
    async def _handle_participants_updated(
        event: CloudEvent, cm: MemoManager, redis_mgr, clients: list, cid: str
    ) -> None:
        """Handle participant updates in the call."""
        participants = event.data.get("participants", [])
        target_number = cm.get_context("target_number")
        target_joined = (
            any(
                p.get("identifier", {}).get("rawId", "").endswith(target_number or "")
                for p in participants
            )
            if target_number
            else False
        )
        cm.update_context("target_participant_joined", target_joined)
        cm.persist_to_redis(redis_mgr)

        logger.info(f"Target participant joined: {target_joined} for call {cid}")
        participants_info = [
            p.get("identifier", {}).get("rawId", "unknown") for p in participants
        ]
        await broadcast_message(
            clients,
            f"\tParticipants updated for call {cid}: {participants_info}",
            "System",
        )

    @staticmethod
    async def _handle_call_connected(
        event: CloudEvent,
        cm: MemoManager,
        redis_mgr,
        clients: list,
        cid: str,
        acs_caller,
        stt_client,
        stream_mode: StreamMode = ACS_STREAMING_MODE,
    ) -> None:
        """Handle call connected event and play greeting."""
        await broadcast_message(clients, f"Call Connected: {cid}", "System")

        # # If using real-time bidirectional media streaming, start speech recognition
        # if stream_mode == StreamMode.MEDIA:

        #     stt_client.start()

        # If using real-time transcription, play greeting
        if stream_mode == StreamMode.TRANSCRIPTION:
            greeting = (
                "Hello, thank you for calling XMYX Insurance Company. "
                "Before I can assist you, let's verify your identity. "
                "How may I address you today? Please state your full name clearly after the tone, "
                "and let me know how I can help you with your insurance needs."
            )

            try:
                text_source = TextSource(
                    text=greeting, source_locale="en-US", voice_name="en-US-JennyNeural"
                )
                call_conn = acs_caller.get_call_connection(cid)
                call_conn.play_media(play_source=text_source)
                await cm.set_live_context_value(redis_mgr, "greeted", True)
                logger.info(f"Greeting played for call {cid}")
            # if stream_mode == StreamMode.MEDIA:
            #     call_conn.start_media_streaming(
            #         operation_context="startMediaStreamingContext"
            #     )
            except Exception as e:
                logger.error(
                    f"Error playing greeting for call {cid}: {e}", exc_info=True
                )

    @staticmethod
    async def _handle_transcription_failed(
        event: CloudEvent, cm: MemoManager, redis_mgr, cid: str, acs_caller
    ) -> None:
        """Handle transcription failure events."""
        reason = event.data.get("resultInformation", "Unknown reason")
        logger.error(f"⚠️ Transcription failed for call {cid}: {reason}")

        # Log detailed error information
        if "transcriptionUpdate" in event.data:
            transcription_update = event.data["transcriptionUpdate"]
            logger.info(f"TranscriptionUpdate attributes for call {cid}:")
            for key, value in transcription_update.items():
                logger.info(f"  {key}: {value}")

        # Handle specific error codes
        if isinstance(reason, dict):
            error_code = reason.get("code", "Unknown")
            sub_code = reason.get("subCode", "Unknown")
            message = reason.get("message", "No message")
            logger.error(
                f"   Error details - Code: {error_code}, SubCode: {sub_code}, Message: {message}"
            )

            # Check for WebSocket URL issues
            if sub_code == 8581:
                logger.error("🔴 WebSocket connection issue detected!")
                logger.error("   This usually means:")
                logger.error(
                    "   1. Your WebSocket endpoint is not accessible from Azure"
                )
                logger.error(
                    "   2. Your BASE_URL is incorrect or not publicly accessible"
                )
                logger.error("   3. Your WebSocket server is not running or crashed")

        # Attempt to restart transcription
        try:
            if acs_caller and hasattr(acs_caller, "call_automation_client"):
                call_connection_client = acs_caller.get_call_connection(cid)
                if call_connection_client:
                    call_connection_client.start_transcription()
                    logger.info(f"✅ Attempted to restart transcription for call {cid}")
                else:
                    logger.error(
                        f"❌ Could not get call connection for {cid} to restart transcription"
                    )
        except Exception as e:
            logger.error(
                f"❌ Failed to restart transcription for call {cid}: {e}", exc_info=True
            )

    @staticmethod
    async def _handle_call_disconnected(
        event: CloudEvent, cm: MemoManager, redis_mgr, cid: str
    ) -> None:
        """Handle call disconnection events."""
        logger.info(f"❌ Call disconnected for call {cid}")

        # Log additional details for debugging
        disconnect_reason = event.data.get(
            "resultInformation", "No resultInformation provided"
        )
        participants = event.data.get("participants", [])
        logger.info(f"Disconnect reason: {disconnect_reason}")
        logger.info(f"Participants at disconnect: {participants}")

        # Clean up conversation state
        try:
            cm.persist_to_redis(redis_mgr)
            logger.info(f"Persisted conversation state after disconnect for call {cid}")
        except Exception as e:
            logger.error(
                f"Failed to persist conversation state after disconnect for call {cid}: {e}"
            )

    # @staticmethod
    # async def _handle_media_events(
    #     event: CloudEvent,
    #     cm: MemoManager,
    #     redis_mgr,
    #     etype: str
    # ) -> None:
    #     """Handle media-related events (play started/completed/failed/canceled)."""
    #     if etype == "Microsoft.Communication.PlayStarted":
    #         cm.update_context("bot_speaking", True)
    #         logger.info(f"PlayStarted: Set bot_speaking=True for call {cm.session_id}")
    #     elif etype == "Microsoft.Communication.PlayCompleted":
    #         cm.update_context("bot_speaking", False)
    #         logger.info(f"PlayCompleted: Set bot_speaking=False for call {cm.session_id}")
    #     elif etype == "Microsoft.Communication.PlayFailed":
    #         reason = event.data.get("resultInformation", "Unknown reason")
    #         logger.error(f"⚠️ PlayFailed for call {cm.session_id}: {reason}")
    #         cm.update_context("bot_speaking", False)
    #         logger.info(f"PlayFailed: Set bot_speaking=False for call {cm.session_id}")
    #     elif etype == "Microsoft.Communication.PlayCanceled":
    #         cm.update_context("bot_speaking", False)
    #         logger.info(f"PlayCanceled: Set bot_speaking=False for call {cm.session_id}")

    @staticmethod
    async def process_media_callbacks(
        events: list, cm: MemoManager, redis_mgr
    ) -> Dict[str, str]:
        """
        Process media callback events.

        Args:
            events: List of media events to process
            cm: MemoManager instance
            redis_mgr: Redis manager instance

        Returns:
            Dict with processing status
        """
        try:
            for event in events:
                data = event.get("data", {})
                etype = event.get("type", "")
                logger.info("Media callback received: %s\n\tEventType: %s", data, etype)

                if etype == "Microsoft.Communication.PlayStarted":
                    cm.update_context("bot_speaking", True)
                    logger.info(
                        f"PlayStarted: Set bot_speaking=True for call {cm.session_id}"
                    )
                elif etype == "Microsoft.Communication.PlayCompleted":
                    cm.update_context("bot_speaking", False)
                    logger.info(
                        f"PlayCompleted: Set bot_speaking=False for call {cm.session_id}"
                    )
                elif etype == "Microsoft.Communication.PlayFailed":
                    reason = data.get("resultInformation", "Unknown reason")
                    logger.error(f"⚠️ PlayFailed for call {cm.session_id}: {reason}")
                    cm.update_context("bot_speaking", False)
                    logger.info(
                        f"PlayFailed: Set bot_speaking=False for call {cm.session_id}"
                    )
                elif etype == "Microsoft.Communication.PlayCanceled":
                    cm.update_context("bot_speaking", False)
                    logger.info(
                        f"PlayCanceled: Set bot_speaking=False for call {cm.session_id}"
                    )
                elif etype == "Microsoft.Communication.MediaStreamingFailed":
                    reason = data.get("resultInformation", "Unknown reason")
                    logger.error(
                        f"⚠️ MediaStreamingFailed for call {cm.session_id}: {reason}"
                    )
                    cm.update_context("bot_speaking", False)
                    logger.info(
                        f"MediaStreamingFailed: Set bot_speaking=False for call {cm.session_id}"
                    )
                else:
                    logger.info("Media callback event not handled: %s", etype)

            await cm.persist_to_redis_async(redis_mgr)
            return {"status": "media callback processed"}

        except Exception as exc:
            logger.error("Media callback error: %s", exc, exc_info=True)
            return {"error": str(exc)}

    @staticmethod
    async def handle_websocket_transcription(
        ws: WebSocket,
        message: Dict[str, Any],
        cm: MemoManager,
        redis_mgr,
        call_conn,
        clients: list,
    ) -> None:
        """
        Handle WebSocket transcription messages.

        Args:
            ws: WebSocket connection
            message: Transcription message from ACS
            cm: MemoManager instance
            redis_mgr: Redis manager instance
            call_conn: Call connection client
            clients: List of connected WebSocket clients
        """
        try:
            if message.get("kind") != "TranscriptionData":
                return

            bot_speaking = await cm.get_live_context_value(redis_mgr, "bot_speaking")
            td = message["transcriptionData"]
            text = td["text"].strip()
            words = text.split()
            status = td["resultStatus"]  # "Intermediate" or "Final"

            logger.info(
                "🎤📝 Transcription received : '%s' (status: %s, bot_speaking: %s)",
                text,
                status,
                bot_speaking,
            )

            # Handle interruptions during bot speech
            if status == "Intermediate" and bot_speaking:
                logger.info(
                    "🔊 Intermediate transcription received while bot is speaking, "
                    "cancelling queue and ongoing media: '%s'",
                    text,
                )
                call_conn.cancel_all_media_operations()
                await cm.reset_queue_on_interrupt()

                interrupt_cnt = cm.context.get("interrupt_count", 0)
                cm.update_context("interrupt_count", interrupt_cnt + 1)
                await cm.persist_to_redis_async(redis_mgr)

            # Handle final transcription
            if status == "Final":
                cm.update_context("interrupt_count", 0)
                await cm.persist_to_redis_async(redis_mgr)

                # Broadcast and route user text
                await broadcast_message(clients, text, "User")
                logger.info("🎤📝 Final transcription received: '%s'", text)

                # Route to orchestrator for processing
                await route_turn(cm, text, ws, is_acs=True)

        except Exception as e:
            logger.error(f"Error processing transcription message: {e}", exc_info=True)
            # Continue processing rather than breaking the connection

    # @staticmethod
    # async def handle_websocket_media_stream(
    #     ws: WebSocket,
    #     # acs_caller,
    #     # redis_mgr,
    #     # clients: list,
    #     # cid: str,
    #     # speech_client: StreamingSpeechRecognizerFromBytes
    # ) -> None:
    #     """
    #     Handle WebSocket media streaming for ACS calls.

    #     This method includes the core logic from the original acs_media_ws method but
    #     with cleaner error handling, better separation of concerns, and improved modularity.

    #     Args:
    #         ws: WebSocket connection
    #         acs_caller: ACS caller instance
    #         redis_mgr: Redis manager instance
    #         clients: List of connected WebSocket clients
    #         cid: Call connection ID
    #         speech_client: Speech-to-text client for audio processing
    #     """
    #     try:
    #         await ws.accept()
    #         # while True:
    #         #     msg = await ws.receive_text()
    #         #     await ws.send_text("ok")

    #         """Handle ACS WebSocket media streaming."""
    #         acs_caller = ws.app.state.acs_caller
    #         redis_mgr = ws.app.state.redis
    #         speech_client = ws.app.state.stt_client
    #         clients = ws.app.state.clients

    #         def on_partial(text, lang):
    #             """Handle partial transcription."""
    #             if cm.is_tts_interrupted():
    #                 logger.info("TTS already interrupted, skipping further actions.")
    #                 return

    #             logger.info(f"🗣️ User (partial) in {lang}: {text}")
    #             cm.set_tts_interrupted(True)
    #             cm.persist_to_redis(redis_mgr)

    #         def on_final(text, lang):
    #             """Handle final transcription."""
    #             logger.info(f"🧾 User (final) in {lang}: {text}")
    #             cm.set_tts_interrupted(False)
    #             cm.persist_to_redis(redis_mgr)

    #         if not speech_client or not acs_caller:
    #             await ws.close(code=1011)
    #             return

    #         cid = ws.headers["x-ms-call-connection-id"]
    #         cm = MemoManager.from_redis(cid, redis_mgr)
    #         target_phone_number = cm.get_context("target_number")
    #         ws.app.state.target_participant = PhoneNumberIdentifier(target_phone_number)

    #         # Speech Recognition Config for audio stream handling
    #         speech_client.set_partial_result_callback(on_partial)
    #         speech_client.set_final_result_callback(on_final)
    #         speech_client.start()

    #         # Global state for tracking call participants
    #         if not hasattr(ws.app.state, 'call_user_raw_ids'):
    #             ws.app.state.call_user_raw_ids = {}
    #         call_user_raw_ids = ws.app.state.call_user_raw_ids

    #         logger.info("▶ media WS connected - %s", cid)

    #         # Initialize speech recognition components
    #         queue: asyncio.Queue[str] = asyncio.Queue()
    #         push_stream = None
    #         recognizer = None

    #         # # Handle greeting logic asynchronously
    #         # if not cm.get_context("greeted", False):
    #         #     async def send_greeting():
    #         #         greeting = (
    #         #             "Hello from XMYX Healthcare Company! Before I can assist you, "
    #         #             "let's verify your identity. How may I address you?"
    #         #         )
    #         #         await broadcast_message(clients, greeting, "Assistant")

    #         #         # Import the function at the module level to avoid issues
    #         #         await send_response_to_acs(ws, greeting)

    #         #         cm.append_to_history("wss_media_stream", "assistant", greeting)
    #         #         cm.update_context("greeted", True)
    #         #         await cm.persist_to_redis_async(redis_mgr)

    #         #     # Start greeting task and store reference for cleanup
    #         #     # Option 1: Fire immediately and await it (recommended for greeting)
    #         #     await send_greeting()

    #         #     # Option 2: If you need it non-blocking but with higher priority scheduling
    #         #     greeting_task = asyncio.create_task(send_greeting())
    #         #     await asyncio.sleep(0)  # Yield control to allow task to start immediately

    #         #     # Option 3: If you want to ensure it runs before other tasks
    #         #     async def send_greeting_immediately():
    #         #         await send_greeting()

    #         #     greeting_task = asyncio.create_task(send_greeting_immediately())
    #         #     # Force immediate scheduling
    #         #     greeting_task.add_done_callback(lambda t: logger.info("Greeting sent successfully") if not t.exception() else logger.error(f"Greeting failed: {t.exception()}"))
    #         #     # Don't await here to avoid blocking the main loop

    #         # Track user participant ID
    #         user_raw_id = call_user_raw_ids.get(cid)

    #         # Main processing loop
    #         while True:
    #             # Handle WebSocket messages
    #             try:
    #                 raw = await ws.receive_text()
    #                 data = json.loads(raw)
    #             except Exception as e:
    #                 logger.error(f"Unexpected WebSocket error for call {cid}: {e}", exc_info=True)
    #                 break

    #             # Process different message types
    #             await ACSHandler._process_websocket_message(
    #                 data=data,
    #                 cid=cid,
    #                 user_raw_id=user_raw_id,
    #                 call_user_raw_ids=call_user_raw_ids,
    #                 stt_client=speech_client
    #             )

    #             # Update user_raw_id if it was set during message processing
    #             if cid in call_user_raw_ids:
    #                 user_raw_id = call_user_raw_ids[cid]

    #     except Exception as e:
    #         logger.error(f"Error in media WebSocket handler for call {cid}: {e}", exc_info=True)
    #     finally:
    #         # Clean up resources
    #         try:
    #             if recognizer:
    #                 recognizer.stop_continuous_recognition_async()
    #             if push_stream:
    #                 push_stream.close()
    #             # call_user_raw_ids.pop(cid, None)
    #             # cm.persist_to_redis(redis_mgr)
    #             logger.info(f"◀ media WS closed – {cid}")
    #         except Exception as e:
    #             logger.error(f"Error during cleanup for call {cid}: {e}")
