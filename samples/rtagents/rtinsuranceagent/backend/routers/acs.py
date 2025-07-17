"""
routers/acs.py
==============
Outbound phone-call flow via Azure Communication Services.

• POST  /call             – start a phone call
• POST  /call/callbacks   – receive ACS events
• WS    /call/stream      – bidirectional PCM audio stream
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from base64 import b64decode
from typing import Dict, Optional

from azure.communication.callautomation import PhoneNumberIdentifier, TextSource
from azure.core.exceptions import HttpResponseError
from azure.core.messaging import CloudEvent
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketState
from helpers import check_for_stopwords
from pydantic import BaseModel
from rtagents.RTInsuranceAgent.backend.latency.latency_tool import LatencyTool
from rtagents.RTInsuranceAgent.backend.src.stateful.state_managment import (
    MemoManager,
)
from rtagents.RTInsuranceAgent.backend.orchestration.orchestrator import route_turn
from rtagents.RTInsuranceAgent.backend.postcall.push import build_and_flush
from rtagents.RTInsuranceAgent.backend.services.acs.acs_helpers import play_response
from rtagents.RTInsuranceAgent.backend.settings import (
    ACS_CALL_PATH,
    ACS_CALLBACK_PATH,
    ACS_WEBSOCKET_PATH,
    BASE_URL,
    GREETING,
)
from shared_ws import broadcast_message, send_response_to_acs

from src.aoai.manager_transcribe import AudioTranscriber
from utils.ml_logging import get_logger

logger = get_logger("routers.acs")
router = APIRouter()


class CallRequest(BaseModel):
    target_number: str


# --------------------------------------------------------------------------- #
#  1. Make Call  (POST /api/call)
# --------------------------------------------------------------------------- #
@router.post("/api/call")
async def initiate_call(call: CallRequest, request: Request):
    acs = request.app.state.acs_caller

    if not acs:
        raise HTTPException(503, "ACS Caller not initialised")

    try:
        # TODO: Add logic to reject multiple requests for the same target number
        result = await acs.initiate_call(call.target_number)
        if result.get("status") != "created":
            return JSONResponse({"status": "failed"}, status_code=400)
        call_id = result["call_id"]

        cm = MemoManager.from_redis(
            session_id=call_id,
            redis_mgr=request.app.state.redis,
        )

        cm.update_context("target_number", call.target_number)
        cm.persist_to_redis(request.app.state.redis)

        logger.info("Call initiated – ID=%s", call_id)
        return {"message": "Call initiated", "callId": call_id}
    except (HttpResponseError, RuntimeError) as exc:
        logger.error("ACS error: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc)) from exc


# --------------------------------------------------------------------------- #
#  Answer Call  (POST /api/call/inbound)
# --------------------------------------------------------------------------- #
@router.post("/api/call/inbound")
async def answer_call(request: Request):
    acs = request.app.state.acs_caller
    if not acs:
        raise HTTPException(503, "ACS Caller not initialised")

    try:
        body = await request.json()
        for event in body:
            eventType = event.get("eventType")
            if eventType == "Microsoft.EventGrid.SubscriptionValidationEvent":
                # Handle subscription validation event
                validation_code = event.get("data", {}).get("validationCode")
                if validation_code:
                    return JSONResponse(
                        {"validationResponse": validation_code}, status_code=200
                    )
                else:
                    raise HTTPException(400, "Validation code not found in event data")
            else:
                logger.info(f"Received event of type {eventType}: {event}")
                # Handle other event types as needed
                # For now, just acknowledge receipt

        return JSONResponse({"status": "call answered"}, status_code=200)

    except (HttpResponseError, RuntimeError) as exc:
        logger.error("ACS error: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc)) from exc
    except Exception as exc:
        logger.error("Error parsing request body: %s", exc, exc_info=True)
        raise HTTPException(400, "Invalid request body") from exc


# --------------------------------------------------------------------------- #
#  2. Callback events  (POST /call/callbacks)
# --------------------------------------------------------------------------- #
@router.post(ACS_CALLBACK_PATH)
async def callbacks(request: Request):
    if not request.app.state.acs_caller:
        return JSONResponse({"error": "ACS not initialised"}, status_code=503)

    try:
        events = await request.json()
        for raw in events:
            event = CloudEvent.from_dict(raw)
            etype = event.type
            cid = event.data.get("callConnectionId")
            redis_mgr = request.app.state.redis

            cm = MemoManager.from_redis(cid, redis_mgr)

            if etype == "Microsoft.Communication.ParticipantsUpdated":
                # Update the redis cache for the call connection id with participant info
                participants = event.data.get("participants", [])
                target_number = cm.get_context("target_number")
                target_joined = any(
                    p.get("identifier", {}).get("rawId", "").endswith(target_number)
                    for p in participants
                )
                cm.update_context("target_participant_joined", target_joined)
                cm.persist_to_redis(request.app.state.redis)
                logger.info(
                    f"Target participant joined: {target_joined} for call {cid}"
                )
                participants_info = [
                    p.get("identifier", {}).get("rawId", "unknown")
                    for p in participants
                ]
                await broadcast_message(
                    request.app.state.clients,
                    f"\tParticipants updated for call {cid}: {participants_info}",
                    "System",
                )
            elif etype == "Microsoft.Communication.CallConnected":
                await broadcast_message(
                    request.app.state.clients,
                    f"Call Connected: {cid}",
                    "System",
                )

                await cm.set_live_context_value(redis_mgr, "greeted", True)

                greeting = GREETING
                try:
                    text_source = TextSource(
                        text=greeting,
                        source_locale="en-US",
                        voice_name="en-US-JennyNeural",
                    )
                    call_conn = request.app.state.acs_caller.get_call_connection(cid)

                    call_conn.play_media(
                        play_source=text_source,
                        # play_to=[target_identifier],
                        # interrupt_call_media_operations=True,
                    )
                    logger.info(f"Greeting played for call {cid}")
                except Exception as e:
                    logger.error(
                        f"Error playing greeting for call {cid}: {e}", exc_info=True
                    )
                    # Optionally, handle the error (e.g., retry, log, etc.)

            elif etype == "Microsoft.Communication.TranscriptionFailed":
                reason = event.data.get("resultInformation", "Unknown reason")
                logger.error(f"⚠️ {etype} for call {cid}: {reason}")
                if "transcriptionUpdate" in event.data:
                    transcription_update = event.data["transcriptionUpdate"]
                    logger.info(f"TranscriptionUpdate attributes for call {cid}:")
                    for key, value in transcription_update.items():
                        logger.info(f"  {key}: {value}")
                # Log additional debugging information
                if isinstance(reason, dict):
                    error_code = reason.get("code", "Unknown")
                    sub_code = reason.get("subCode", "Unknown")
                    message = reason.get("message", "No message")
                    logger.error(
                        f"   Error details - Code: {error_code}, SubCode: {sub_code}, Message: {message}"
                    )

                    # Check if it's a WebSocket URL issue
                    if sub_code == 8581:
                        logger.error("🔴 WebSocket connection issue detected!")
                        logger.error("   This usually means:")
                        logger.error(
                            "   1. Your WebSocket endpoint is not accessible from Azure"
                        )
                        logger.error(
                            "   2. Your BASE_URL is incorrect or not publicly accessible"
                        )
                        logger.error(
                            "   3. Your WebSocket server is not running or crashed"
                        )

                        # Log the current configuration for debugging
                        acs_caller = request.app.state.acs_caller

                # Attempt to restart transcription if it fails
                try:
                    acs_caller = request.app.state.acs_caller
                    if acs_caller and hasattr(acs_caller, "call_automation_client"):
                        call_connection_client = acs_caller.get_call_connection(cid)
                        if call_connection_client:
                            call_connection_client.start_transcription()
                            logger.info(
                                f"✅ Attempted to restart transcription for call {cid}"
                            )
                        else:
                            logger.error(
                                f"❌ Could not get call connection for {cid} to restart transcription"
                            )
                except Exception as e:
                    logger.error(
                        f"❌ Failed to restart transcription for call {cid}: {e}",
                        exc_info=True,
                    )

            elif etype == "Microsoft.Communication.CallDisconnected":
                logger.info(f"❌ Call disconnected for call {cid}")
                # Log additional details for debugging
                disconnect_reason = event.data.get(
                    "resultInformation", "No resultInformation provided"
                )
                participants = event.data.get("participants", [])
                logger.info(f"Disconnect reason: {disconnect_reason}")
                logger.info(f"Participants at disconnect: {participants}")
                # Optionally, clean up conversation state or resources
                try:
                    cm.persist_to_redis(request.app.state.redis)
                    logger.info(
                        f"Persisted conversation state after disconnect for call {cid}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to persist conversation state after disconnect for call {cid}: {e}"
                    )

            elif etype == "Microsoft.Communication.TranscriptionFailed":
                reason = event.data.get("resultInformation", "Unknown reason")
                logger.error(f"⚠️ Transcription failed for call {cid}: {reason}")

            elif "Failed" in etype:
                reason = event.data.get("resultInformation", "Unknown reason")
                logger.error("⚠️ %s for call %s: %s", etype, cid, reason)

            # ---- Media Events ----
            elif etype == "Microsoft.Communication.PlayStarted":
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
                reason = event.data.get("resultInformation", "Unknown reason")
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
            else:
                logger.info("%s %s", etype, cid)
            cm.persist_to_redis(redis_mgr)
        return {"status": "callback received"}
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Callback error: %s", exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


# --------------------------------------------------------------------------- #
#  3. Media-streaming WebSocket  (WS /call/stream)
# --------------------------------------------------------------------------- #
# @router.post("/api/media/callbacks")
# async def media_callbacks(request: Request):
#     try:
#         cm = request.app.state.cm
#         redis_mgr = request.app.state.redis
#         events = await request.json()
#         for event in events:
#             data = event.get("data", {})
#             etype = event.get("type", "")
#             logger.info("Media callback received: %s\n\tEventType: %s", data, etype)
#             # return {"status": "callback received"}
#         # Handle PlayCompleted event: set bot_speaking to False in Redis
#             if etype == "Microsoft.Communication.PlayStarted":
#                 cm.update_context("bot_speaking", True)
#                 logger.info(f"PlayStarted: Set bot_speaking=True for call {cm.session_id}")
#             elif etype == "Microsoft.Communication.PlayCompleted":
#                 cm.update_context("bot_speaking", False)
#                 logger.info(f"PlayCompleted: Set bot_speaking=False for call {cm.session_id}")
#             elif etype == "Microsoft.Communication.PlayFailed":
#                 reason = data.get("resultInformation", "Unknown reason")
#                 logger.error(f"⚠️ PlayFailed for call {cm.session_id}: {reason}")
#                 cm.update_context("bot_speaking", False)
#                 logger.info(f"PlayFailed: Set bot_speaking=False for call {cm.session_id}")
#             elif etype == "Microsoft.Communication.PlayCanceled":
#                 cm.update_context("bot_speaking", False)
#                 logger.info(f"PlayCanceled: Set bot_speaking=False for call {cm.session_id}")
#             else:
#                 logger.info("Media callback event not handled: %s", etype)
#         await cm.persist_to_redis_async(redis_mgr)

#     except Exception as exc:  # pylint: disable=broad-except
#         logger.error("Media callback error: %s", exc, exc_info=True)
#         return JSONResponse({"error": str(exc)}, status_code=500)


@router.websocket(ACS_WEBSOCKET_PATH)
async def acs_transcription_ws(ws: WebSocket):
    await ws.accept()
    acs = ws.app.state.acs_caller
    redis_mgr = ws.app.state.redis

    cid = ws.headers["x-ms-call-connection-id"]
    cm = MemoManager.from_redis(cid, redis_mgr)
    target_phone_number = cm.get_context("target_number")

    if not target_phone_number:
        logger.debug(f"No target phone number found for session {cm.session_id}")

    ws.app.state.target_participant = PhoneNumberIdentifier(target_phone_number)
    ws.app.state.cm = cm
    ws.state.lt = LatencyTool(
        cm
    )  # Initialize latency tool without context    # 1) seed flags from Redis
    greeted = cm.context.get("greeted", False)
    bot_speaking = cm.context.get("bot_speaking", False)
    interrupt_cnt = cm.context.get("interrupt_count", 0)

    call_conn = acs.get_call_connection(cid)

    # Flag to handle greeting inside the main loop for better transcription management
    while True:
        try:
            text_data = await ws.receive_text()  # Adjust timeout as needed
            msg = json.loads(text_data)
        except asyncio.TimeoutError:
            # Continue the loop to check greeting status and handle other tasks
            continue
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected by client")
            break
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from WebSocket: {e}")
            continue
        except Exception as e:
            logger.error(
                f"Unexpected error in WebSocket receive loop: {e}", exc_info=True
            )
            break

        try:
            if msg.get("kind") != "TranscriptionData":
                continue

            bot_speaking = await cm.get_live_context_value(redis_mgr, "bot_speaking")
            td = msg["transcriptionData"]
            text = td["text"].strip()
            words = text.split()
            status = td["resultStatus"]  # "Intermediate" or "Final"
            logger.info(
                "🎤📝 Transcription received : '%s' (status: %s, bot_speaking: %s)",
                text,
                status,
                bot_speaking,
            )

            if status == "Intermediate" and bot_speaking:
                logger.info(
                    "🔊 Intermediate transcription received while bot is speaking, cancelling queue and ongoing media: '%s'",
                    text,
                )
                call_conn.cancel_all_media_operations()
                await cm.reset_queue_on_interrupt()
                cm.update_context("interrupt_count", interrupt_cnt + 1)
                await cm.persist_to_redis_async(ws.app.state.redis)

                # Additional logic to handle interruptions
                # ----
                # ok = len(words) >= 1
                # interrupt_cnt = interrupt_cnt + 1 if ok else 0
                # logger.info("🔊 Intermediate transcription during bot speech: '%s' (status: %s)", text, status)
                # cm.update_context("interrupt_count", interrupt_cnt)
                # await cm.persist_to_redis_async(ws.app.state.redis)

                # if interrupt_cnt >= 1:
                #     logger.info("🔊 User interruption detected – stopping TTS")
                #     try:
                #         call_conn.cancel_all_media_operations()
                #     except Exception as cancel_error:
                #         logger.error(f"Error canceling media operations: {cancel_error}")
                #     bot_speaking  = False
                #     interrupt_cnt = 0
                #     cm.update_context("bot_speaking", False)
                #     cm.update_context("interrupt_count", 0)
                #     cm.update_context("transcription_paused_for_media", False)
                #     cm.update_context("interrupt_count", 0)
                #     await cm.persist_to_redis_async(ws.app.state.redis)
                # continue

            # 4) on final, reset counter and handle user turn
            if status == "Final":
                interrupt_cnt = 0

                cm.update_context("interrupt_count", 0)
                await cm.persist_to_redis_async(ws.app.state.redis)

                # broadcast and route user text
                await broadcast_message(ws.app.state.clients, text, "User")
                logger.info("🎤📝 Final transcription received: '%s'", text)
                response = await route_turn(cm, text, ws, is_acs=True)

                # finally hand off to your orchestrator
                # when it TTS's again, wrap that call with setting bot_speaking=True

        except Exception as e:
            logger.error(f"Error processing transcription message: {e}", exc_info=True)
            # Continue processing other messages rather than breaking
            continue


# -------
# while True:
#     try:
#         message = await ws.receive()
#         greeted = cm.context.get("greeted") or False
#         print(f"Current greeted state: {greeted}")
#         if ws.client_state != WebSocketState.CONNECTED:
#             print("WebSocket is not connected. Closing handler loop.")
#             break

#         if message.get("type") == "websocket.disconnect":
#             print("WebSocket disconnect received. Closing connection.")
#             break
#         if "text" in message:
#             await process_websocket_message_async(ws, cm, call_conn, message["text"])
#         elif "bytes" in message:
#             await process_websocket_message_async(ws, cm, call_conn, message["bytes"].decode("utf-8"))
#         else:
#             print("Received message with unknown format:", message)
#     except Exception as e:
#         print(f"Error while receiving message: {e}")
#         break  # Close connection on error

# --------
# Handle greeting as the first task inside the main loop
# if needs_greeting and not greeting_task:
#     logger.info("🎤 Starting greeting inside main WebSocket loop for better transcription handling")
#     greeting = (
#         "Hello, thank you for calling XMYX Insurance Company. "
#         "Before I can assist you, let's verify your identity. "
#         "How may I address you today? Please state your full name clearly after the tone, "
#         "and let me know how I can help you with your insurance needs."
#     )

#     # Set bot_speaking to True before playing response
#     bot_speaking = True
#     cm.update_context("bot_speaking", True)
#     await cm.persist_to_redis_async(ws.app.state.redis)

# # Ensure no lingering TTS and start transcription
# try:
#     call_conn.cancel_all_media_operations()

#     # Start monitoring for transcription resume
#     asyncio.create_task(
#         handle_transcription_resume_timeout(cid, cm, ws.app.state.redis, timeout_seconds=30.0)
#     )
#     await play_response(
#         ws,
#         greeting,
#         participants=[ws.app.state.target_participant],
#         transcription_resume_delay=2.0,  # Short delay to allow greeting to play
#     )
#     needs_greeting = False  # Mark that we've initiated the greeting
# except Exception as e:
#     logger.error(f"Error setting up greeting for call {cid}: {e}", exc_info=True)

# # Check if greeting task is complete
# if greeting_task and greeting_task.done():
# try:
#     await greeting_task  # Ensure any exceptions are handled
#     logger.info("✅ Greeting completed successfully")
# except Exception as e:
#     logger.error(f"❌ Error during greeting: {e}", exc_info=True)

# # Mark as greeted and reset bot_speaking
# greeted = True
# bot_speaking = False
# cm.update_context("greeted", True)
# cm.update_context("bot_speaking", False)
# await cm.persist_to_redis_async(ws.app.state.redis)
# greeting_task = None  # Clear the task reference
# from azure.communication.callautomation._shared.models import identifier_from_raw_id
# import threading
# async def process_websocket_message_async(ws, cm, call_conn_client, message):

#         print("Client connected")
#         json_object = json.loads(message)
#         kind = json_object['kind']
#         print(kind)
#         if kind == 'TranscriptionMetadata':
#             print("Transcription metadata")
#             print("-------------------------")
#             print("Subscription ID:", json_object['transcriptionMetadata']['subscriptionId'])
#             print("Locale:", json_object['transcriptionMetadata']['locale'])
#             print("Call Connection ID:", json_object['transcriptionMetadata']['callConnectionId'])
#             print("Correlation ID:", json_object['transcriptionMetadata']['correlationId'])
#         if kind == 'TranscriptionData':
#             participant = identifier_from_raw_id(json_object['transcriptionData']['participantRawID'])
#             word_data_list = json_object['transcriptionData'].get('words', [])
#             print("Transcription data")
#             print("-------------------------")
#             # Use .get() with defaults to avoid KeyError if fields are missing
#             transcription_data = json_object.get('transcriptionData', {})
#             print("Text:", transcription_data.get('text', ''))
#             print("Format:", transcription_data.get('format', ''))
#             print("Confidence:", transcription_data.get('confidence', 0.0))
#             print("Offset:", transcription_data.get('offset', 0))
#             print("Duration:", transcription_data.get('duration', 0))
#             print("Participant:", getattr(participant, 'raw_id', ''))
#             print("Result Status:", transcription_data.get('resultStatus', ''))
#             for word in transcription_data.get('words', []):
#                 print("Word:", word.get('text', ''))
#                 print("Offset:", word.get('offset', 0))
#                 print("Duration:", word.get('duration', 0))

#             # Core VAD logic
#             # 1. IF intermediate data is received
#             # 2. Cancel all media being output
#             # 3. Wait until final result is received
#             # 4. Process final result, add to the conversation state
#             # 5. Play the processed result back to the user
#             # 6. repeat.
#             try:
#                 if transcription_data.get('resultStatus') == 'Intermediate':
#                     print("Intermediate transcription received. Cancelling any ongoing media operations.")
#                     # Play a dial tone to indicate interrupt has been detected
#                     try:
#                         call_conn_client.cancel_all_media_operations()
#                         print("VAD played to indicate interrupt.")
#                     except HttpResponseError as e:
#                         if hasattr(e, "status_code") and e.status_code == 8500:
#                             print("HttpResponseError 8500 encountered. Cancelling all media operations and retrying play_media.")
#                             try:
#                                 call_conn_client.cancel_all_media_operations()
#                                 print("\033[91m" + "!!! INTERRUPTION TRIGGERED !!!" + "\033[0m")
#                                 # call_conn_client.play_media(
#                                 #     play_source=TextSource(
#                                 #         text="VAD",
#                                 #         source_locale="en-US",
#                                 #         voice_name="en-US-JennyNeural"
#                                 #     ),
#                                 #     play_to=[ws.app.state.target_participant],
#                                 #     operation_callback_url="https://np4p8s90-8010.use.devtunnels.ms/api/media/callbacks",
#                                 #     interrupt_call_media_operation=True,
#                                 # )
#                                 print("VAD played after retry due to 8500 error.")
#                             except Exception as retry_e:
#                                 print(f"Retry failed: {retry_e}")
#                         else:
#                             print(f"Failed to play VAD: {e}")
#                     except Exception as e:
#                         print(f"Failed to play VAD: {e}")

#                     print("Transcription succeeded.")

#                 elif transcription_data.get('resultStatus') == 'Final':
#                     words_list = transcription_data.get('words', [])
#                     print("Final transcription received.")
#                     # Combine the list of words into a single sentence
#                     user_prompt = " ".join(word.get('text', '') for word in words_list).strip()
#                     print(f"\tFinal Text: {user_prompt}")
#                     cm.append_to_history("user", "test", user_prompt)
#                     # Offload synchronous media operations to a separate thread to avoid blocking the async event loop
#                     def play_final_media():
#                         try:
#                             result = call_conn_client.play_media(
#                                 play_source=TextSource(
#                                     text="FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL FINAL ",
#                                     source_locale="en-US",
#                                     voice_name="en-US-JennyNeural"
#                                 ),
#                                 # play_to=[ws.app.state.target_participant],
#                                 operation_callback_url="https://np4p8s90-8010.use.devtunnels.ms/api/media/callbacks",
#                                 # interrupt_call_media_operation=True,
#                             )
#                             print(result)
#                             print("Final transcription processed and played back to user.")
#                         except Exception as e:
#                             call_conn_client.cancel_all_media_operations()
#                             print(f"Error in play_final_media thread: {e}")

#                     threading.Thread(target=play_final_media, daemon=True).start()


#                     # Wait for 2 seconds before cancelling all media operations
#                     # try:
#                     #     call_conn_client.cancel_all_media_operations()
#                     #     print("Cancelled all media operations after 2 seconds.")
#                     # except Exception as e:
#                     #     print(f"Error cancelling media operations after delay: {e}")
#                     # result = await process_gpt_response(
#                     #     cm,
#                     #     user_prompt=user_prompt,
#                     #     ws=ws,
#                     #     is_acs=True,
#                     # )

#                     # print("Result from GPT processing:", result)
#             except Exception as exc:
#                 print(f"Error in transcription processing: {exc}")
