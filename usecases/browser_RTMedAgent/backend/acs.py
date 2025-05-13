import logging
import asyncio
from azure.core.exceptions import HttpResponseError

from aiohttp import web
from azure.core.messaging import CloudEvent
from azure.communication.callautomation import (
    CallAutomationClient,
    CallInvite,
    PhoneNumberIdentifier,
    MediaStreamingOptions,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    AudioFormat,
    TextSource, 
    SsmlSource
)

logger = logging.getLogger(__name__)

class AcsCaller:
    source_number: str
    acs_connection_string: str
    acs_callback_path: str
    websocket_url: str
    media_streaming_configuration: MediaStreamingOptions
    call_automation_client: CallAutomationClient

    def __init__(
            self, 
            source_number:str, 
            acs_connection_string: str, 
            acs_callback_path: str, 
            acs_media_streaming_websocket_path: str, 
            # tts_translator: SpeechCoreTranslator
            ):
        self.source_number = source_number
        self.acs_connection_string = acs_connection_string
        self.acs_callback_path = acs_callback_path # Should be the full URL
        self.websocket_url = acs_media_streaming_websocket_path # Should be the full wss:// URL
        logger.info(f"AcsCaller initialized. Callback URL: {self.acs_callback_path}, WebSocket URL: {self.websocket_url}")
        self.media_streaming_configuration = MediaStreamingOptions(
            transport_url=self.websocket_url, # Use the full websocket URL
            transport_type=MediaStreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
            start_media_streaming=True,
            enable_bidirectional=True, 
            audio_format=AudioFormat.PCM16_K_MONO # Ensure this matches what your STT expects
        )
        # Initialize CallAutomationClient here to reuse it
        try:
            # self.call_automation_client = CallAutomationClient.from_connection_string(self.acs_connection_string)
            self.call_automation_client = CallAutomationClient.from_connection_string(self.acs_connection_string)
            logger.info("CallAutomationClient initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize CallAutomationClient: {e}", exc_info=True)
            self.call_automation_client = None # Ensure it's None if init fails

    async def initiate_call(self, target_number: str):
        if not self.call_automation_client:
             logger.error("CallAutomationClient not initialized. Cannot initiate call.")
             raise RuntimeError("CallAutomationClient failed to initialize.") # Or handle appropriately

        try:
            # Ensure target and source are correctly formatted identifiers
            self.target_participant = PhoneNumberIdentifier(target_number)
            self.source_caller = PhoneNumberIdentifier(self.source_number)

            # Log the exact parameters being used for the call
            logger.info(f"Initiating call to: {target_number}")
            logger.info(f"Source phone number: {self.source_number}")
            logger.info(f"Callback URI for ACS events: {self.acs_callback_path}")
            logger.info(f"Media Streaming WebSocket URI: {self.websocket_url}")
            logger.info(f"Media Streaming Configuration: {self.media_streaming_configuration}")

            CallInvite(target=self.target_participant, source_caller_id_number=self.source_caller) 
            response = self.call_automation_client.create_call(
                target_participant=self.target_participant,
                callback_url=self.acs_callback_path, # Pass the full callback URL
                media_streaming=self.media_streaming_configuration,
                source_caller_id_number=self.source_caller
            )
            # Note: create_call is sync. Response contains call_connection_properties like callConnectionId if successful immediately,
            # but the actual connection state comes via callbacks.
            call_connection_id = response.call_connection_id
            logger.info(f"create_call request sent successfully. Call Connection ID (initial): {call_connection_id}")
            # Return the result dictionary expected by the FastAPI endpoint in server.py
            return {"status": "created", "call_id": call_connection_id}
        except HttpResponseError as e:
            # Log detailed error information from ACS
            logger.error(f"ACS HTTP Error creating call: Status Code={e.status_code}, Reason={e.reason}, Message={e.message}", exc_info=True)
            # Consider re-raising or handling specific error codes (e.g., 400 for bad request, 401/403 for auth, 500 for server error)
            raise # Re-raise the exception to be handled by the caller API endpoint
        except Exception as e:
            logger.error(f"An unexpected error occurred during initiate_call: {e}", exc_info=True)
            raise # Re-raise the exception

    async def disconnect_call(self, call_connection_id: str):
        """
        Disconnects the call associated with the given call connection ID.
        """
        if not self.call_automation_client:
            logger.error("CallAutomationClient not initialized. Cannot disconnect call.")
            return # Or raise an error

        try:
            call_connection = self.call_automation_client.get_call_connection(call_connection_id)
            if call_connection:
                logger.info(f"Attempting to hang up call with connection ID: {call_connection_id}")
                await call_connection.hang_up() # Hang up for all participants
                logger.info(f"Hang up request sent for call connection ID: {call_connection_id}")
            else:
                logger.warning(f"Could not find call connection object for ID: {call_connection_id}. Cannot hang up.")
        except HttpResponseError as e:
            logger.error(f"ACS HTTP Error hanging up call {call_connection_id}: Status Code={e.status_code}, Reason={e.reason}, Message={e.message}", exc_info=True)
            # Consider specific handling based on status code if needed
        except Exception as e:
            logger.error(f"An unexpected error occurred during disconnect_call for {call_connection_id}: {e}", exc_info=True)
            # Decide if re-raising is appropriate depending on how this method is called
    async def outbound_call_handler(self, request):
        cloudevent = await request.json() 
        handled_events = {}
        for event_dict in cloudevent:
            try:
                event = CloudEvent.from_dict(event_dict)
                if event.data is None or 'callConnectionId' not in event.data:
                    logger.warning(f"Received event without data or callConnectionId: {event_dict}")
                    continue

                call_connection_id = event.data['callConnectionId']
                logger.info(f"Processing event type: {event.type} for call connection id: {call_connection_id}")

                # Store the event dictionary under its call connection ID
                handled_events.setdefault(call_connection_id, []).append(event_dict)

                # Existing event handling logic (logging)
                if event.type == "Microsoft.Communication.CallConnected":
                    logger.info(f"Call connected event received for call connection id: {call_connection_id}")
                elif event.type == "Microsoft.Communication.ParticipantsUpdated":
                    logger.info(f"Participants updated event received for call connection id: {call_connection_id}")
                elif event.type == "Microsoft.Communication.CallDisconnected":
                    logger.info(f"Call disconnect event received for call connection id: {call_connection_id}")
                # Add handling for other relevant events like PlayAudioResult, RecognizeCompleted, etc. if needed
                else:
                    logger.info(f"Unhandled event type: {event.type} for call connection id: {call_connection_id}")

            except Exception as e:
                logger.error(f"Error processing event: {event_dict}. Error: {e}", exc_info=True)
            # Decide if you want to continue processing other events or stop

        # Return the dictionary of handled events along with a status
        return web.json_response({"status": "events processed", "handled_events": handled_events}, status=200)
        # return web.Response(status=200)

    def get_call_connection(self, call_connection_id: str):
        """
        Retrieve the call connection details using the call connection ID.
        """
        try:
            call_connection = self.call_automation_client.get_call_connection(call_connection_id)
            return call_connection
        except Exception as e:
            logger.error(f"Error retrieving call connection: {e}", exc_info=True)
            return None
        
    async def play_agent_tts(self, call_connection_id: str, text: str):
        call_conn = self.call_automation_client.get_call_connection(call_connection_id)
        tts = TextSource(text=text, voice_name="en-US-JennyNeural")
        # Always use the interrupt flag to preempt any ongoing media operation
        await call_conn.play_media_to_all(
            play_source=tts,
            loop=False,
            interrupt_call_media_operation=True
        )

    async def play_response( # Changed to async def
            self, 
            call_connection_id: str, 
            response_text: str, 
            use_ssml: bool = False, 
            voice_name: str = "en-US-JennyMultilingualNeural",
            locale: str = "en-US"
            ):
        """
        Plays `response_text` into the given ACS call, using the SpeechConfig
        :param call_connection_id: ACS callConnectionId
        :param response_text:      Plain text or SSML to speak
        :param use_ssml:           If True, wrap in SsmlSource; otherwise TextSource
        """
        # 1) Get the call-specific client
        call_conn = self.call_automation_client.get_call_connection(call_connection_id)
        if not call_conn:
            logger.error(f"Could not get call connection object for {call_connection_id}. Cannot play media.")
            return # Or raise an error
            # Check if response_text is empty or None
        if not response_text:
            logger.info(f"Skipping media playback for call {call_connection_id} because response_text is empty.")
            return
        # 2) Build the Source with the same settings
        if use_ssml:
            # Assume response_text is a full SSML document
            source = SsmlSource(ssml_text=response_text)
        else:
            source = TextSource(
                text=response_text,
                voice_name=voice_name,
                source_locale=locale
            )

        await safe_play_media_with_retry(call_conn, source, call_connection_id)

async def safe_play_media_with_retry(call_conn, play_source, call_connection_id: str, max_retries: int = 5, initial_backoff: float = 0.5):
    """
    Hardened helper to safely play media in ACS calls with retry on 8500 errors.
    
    Args:
        call_conn: CallConnection object from CallAutomationClient.get_call_connection()
        play_source: TextSource or SsmlSource to play
        call_connection_id: ID of the active call connection
        max_retries: Maximum number of retries on 8500 errors
        initial_backoff: Initial backoff time in seconds
    """
    for attempt in range(max_retries):
        try:
            call_conn.play_media(
                play_source=play_source,
                loop=False,
                interrupt_call_media_operation=True
            )
            logger.info(f"✅ Successfully played media on attempt {attempt + 1} for call {call_connection_id}")
            return
        except HttpResponseError as e:
            if e.status_code == 8500 or "Media operation is already active" in str(e.message):
                wait_time = initial_backoff * (2 ** attempt)  # Exponential backoff
                logger.warning(f"⏳ Media active (8500) error on attempt {attempt + 1} for call {call_connection_id}. Retrying after {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
                # try:
                #     await call_conn.cancel_all_media_operations()
                #     logger.info(f"🔄 Issued cancel_all_media_operations after 8500 on attempt {attempt + 1}")
                # except Exception as cancel_err:
                #     logger.warning(f"⚠️ Failed to cancel media operations during retry handling: {cancel_err}")
            else:
                logger.error(f"❌ Unexpected ACS error during play_media: {e}")
                raise  # Immediately fail on non-8500 errors
        except Exception as e:
            logger.error(f"❌ Unexpected exception during play_media: {e}")
            raise  # Immediately fail for non-HTTP errors

    logger.error(f"🚨 Failed to play media after {max_retries} retries for call {call_connection_id}")
    raise RuntimeError(f"Failed to play media after {max_retries} retries for call {call_connection_id}")