import asyncio
import logging

from aiohttp import web
from azure.communication.callautomation import (
    CallAutomationClient,
    CallConnectionClient,
    PhoneNumberIdentifier,
    SsmlSource,
    TextSource,
    AudioFormat,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    TranscriptionOptions, 
    StreamingTransportType,
    RecordingChannel,
    RecordingContent,
    RecordingFormat,
    AzureBlobContainerRecordingStorage
)

from azure.core.exceptions import HttpResponseError
from azure.core.messaging import CloudEvent
from azure.identity import DefaultAzureCredential
from src.enums.stream_modes import StreamMode

logger = logging.getLogger(__name__)

class AcsCaller:
    """
    Azure Communication Services call automation helper.
    
    Manages outbound calls, live transcription, and call recording using Azure Communication Services.
    Supports both connection string and managed identity authentication.
    
    Args:
        source_number: Phone number to use as caller ID (E.164 format, e.g., '+1234567890')
        callback_url: Base URL for ACS event callbacks
        recording_callback_url: Optional URL for recording-specific callbacks (defaults to callback_url)
        websocket_url: Optional WebSocket URL for live transcription transport
        acs_connection_string: Optional ACS connection string for authentication
        acs_endpoint: Optional ACS endpoint URL (used with managed identity)
        cognitive_services_endpoint: Optional Cognitive Services endpoint for TTS/STT
        speech_recognition_model_endpoint_id: Optional custom speech model endpoint ID
        recording_configuration: Optional dict with recording-specific settings
        recording_storage_container_url: Optional Azure Blob container URL for storing recordings
        
    Raises:
        ValueError: If neither acs_connection_string nor acs_endpoint is provided
        
    Example:
        # Using connection string
        caller = AcsCaller(
            source_number='+1234567890',
            callback_url='https://myapp.azurewebsites.net/api/acs-callback',
            acs_connection_string='endpoint=https://...',
            websocket_url='wss://myapp.azurewebsites.net/ws/transcription'
        )
        
        # Using ACS's managed identity (on ACS service, integrating with Azure Speech)
        caller = AcsCaller(
            source_number='+1234567890',
            callback_url='https://myapp.azurewebsites.net/api/acs-callback',
            acs_endpoint='https://myacs.communication.azure.com',
            cognitive_services_endpoint='https://mycognitive.cognitiveservices.azure.com'
        )
    """
    
    def __init__(
        self,
        source_number: str,
        callback_url: str,
        recording_callback_url: str = None,
        websocket_url: str = None,
        acs_connection_string: str = None,
        acs_endpoint: str = None,
        cognitive_services_endpoint: str = None,
        speech_recognition_model_endpoint_id: str = None,
        recording_configuration: dict = None,
        recording_storage_container_url: str = None,
    ):
        # Required
        if not (acs_connection_string or acs_endpoint):
            raise ValueError("Provide either acs_connection_string or acs_endpoint")

        self.source_number = source_number
        self.callback_url = callback_url
        self.cognitive_services_endpoint = cognitive_services_endpoint
        self.speech_recognition_model_endpoint_id = speech_recognition_model_endpoint_id

        # Recording Settings
        if not recording_callback_url: 
            recording_callback_url = callback_url
        self.recording_callback_url = recording_callback_url
        self.recording_configuration = recording_configuration or {}
        self.recording_storage_container_url = recording_storage_container_url

        # Live Transcription Settings (ACS <--> STT/TTS)
        self.transcription_opts = (
            TranscriptionOptions(
                transport_url=websocket_url,
                transport_type=StreamingTransportType.WEBSOCKET,
                locale="en-US",
                start_transcription=True,
                enable_intermediate_results=True,
            )
            if websocket_url
            else None
        )


        self.media_streaming_options = MediaStreamingOptions(
            transport_url=websocket_url,
            transport_type=StreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
            start_media_streaming=True,
            enable_bidirectional=True,
            enable_dtmf_tones=True,
            audio_format=AudioFormat.PCM16_K_MONO  # Ensure this matches what your STT expects
        )

        # Initialize ACS client
        self.client = (
            CallAutomationClient.from_connection_string(acs_connection_string)
            if acs_connection_string
            else CallAutomationClient(endpoint=acs_endpoint, credential=DefaultAzureCredential())
        )
        
        # Validate configuration
        self._validate_configuration(websocket_url, acs_connection_string, acs_endpoint)
        logger.info("AcsCaller initialized")

    def _validate_configuration(self, websocket_url: str, acs_connection_string: str, acs_endpoint: str):
        """Validate configuration and log warnings for common misconfigurations."""
        # Log configuration status
        if websocket_url:
            logger.info(f"Transcription transport_url (WebSocket): {websocket_url}")
        else:
            logger.warning("No websocket_url provided for transcription transport")
            
        if not self.source_number:
            logger.warning("ACS source_number is not set")
            
        if not self.callback_url:
            logger.warning("ACS callback_url is not set")
            
        if not (acs_connection_string or acs_endpoint):
            logger.warning("Neither ACS connection string nor endpoint is set")
            
        if not self.cognitive_services_endpoint:
            logger.warning("No cognitive_services_endpoint provided (TTS/STT may not work)")
            
        if not self.recording_storage_container_url:
            logger.warning("No recording_storage_container_url provided (recordings may not be saved)")

    async def initiate_call(self, target_number: str, stream_mode: StreamMode = StreamMode.MEDIA) -> dict:
        """Start a new call with live transcription over websocket."""
        call = self.client
        src = PhoneNumberIdentifier(self.source_number)
        dest = PhoneNumberIdentifier(target_number)

        try:
            # Determine which capabilities to enable based on stream_mode
            transcription = None
            cognitive_services_endpoint = None
            media_streaming = None

            if stream_mode == StreamMode.TRANSCRIPTION:
                transcription = self.transcription_opts
                cognitive_services_endpoint = self.cognitive_services_endpoint

            if stream_mode == StreamMode.MEDIA:
                media_streaming = self.media_streaming_options
                
            # Default to transcription if no valid mode specified
            if stream_mode not in [StreamMode.TRANSCRIPTION, StreamMode.MEDIA]:
                logger.warning(f"Invalid stream_mode '{stream_mode}', defaulting to transcription")
                transcription = self.transcription_opts

            logger.debug("Creating call to %s via callback %s", target_number, self.callback_url)
            result = call.create_call(
                target_participant=dest,
                source_caller_id_number=src,
                callback_url=self.callback_url,
                cognitive_services_endpoint=cognitive_services_endpoint,
                transcription=transcription,
                media_streaming=media_streaming
            )
            logger.info("Call created: %s", result.call_connection_id)
            return {"status": "created", "call_id": result.call_connection_id}

        except HttpResponseError as e:
            logger.error("ACS call failed [%s]: %s", e.status_code, e.message)
            raise
        except Exception:
            logger.exception("Unexpected error in initiate_call")
            raise

    async def answer_incoming_call(self, incoming_call_context: str, redis_mgr=None,  stream_mode: StreamMode = StreamMode.MEDIA) -> object:
        """
        Answer an incoming call and set up live transcription.
        
        Args:
            incoming_call_context: The incoming call context from the event
            redis_mgr: Optional Redis manager for caching call state
            
        Returns:
            Call connection result object
        """
        try:
            logger.info(f"Answering incoming call: {incoming_call_context}")
            transcription = None
            cognitive_services_endpoint = None
            media_streaming = None

            if stream_mode == StreamMode.TRANSCRIPTION:
                transcription = self.transcription_opts
                cognitive_services_endpoint = self.cognitive_services_endpoint

            if stream_mode == StreamMode.MEDIA:
                media_streaming = self.media_streaming_options
                
            # Default to transcription if no valid mode specified
            if stream_mode not in [StreamMode.TRANSCRIPTION, StreamMode.MEDIA]:
                logger.warning(f"Invalid stream_mode '{stream_mode}', defaulting to transcription")
                transcription = self.transcription_opts

            # Answer the call with transcription enabled
            result = self.client.answer_call(
                incoming_call_context=incoming_call_context,
                callback_url=self.callback_url,
                cognitive_services_endpoint=cognitive_services_endpoint,
                transcription=transcription,
                media_streaming=media_streaming
            )
            
            logger.info(f"Incoming call answered: {result.call_connection_id}")
            
            # # Cache call state if Redis manager is available
            # if redis_mgr:
            #     await redis_mgr.set_call_state(
            #         call_connection_id=result.call_connection_id,
            #         state="answered",
            #         call_id=result.call_connection_id
            #     )
            
            # return result
            
        except HttpResponseError as e:
            logger.error(f"Failed to answer call [status: {e.status_code}]: {e.message}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error answering call: {e}", exc_info=True)
            raise

    def get_call_connection(self, call_connection_id: str) -> CallConnectionClient:
        """
        Retrieve the CallConnectionClient for the given call_connection_id.
        """
        try:
            return self.client.get_call_connection(call_connection_id)
        except Exception as e:
            logger.error(f"Error retrieving CallConnectionClient: {e}", exc_info=True)
            return None

    def start_recording(self, server_call_id: str):
        """
        Start recording the call.
        """
        try:
            self.client.start_recording(
                server_call_id=server_call_id,
                recording_state_callback_url=self.recording_callback_url,
                recording_content_type=RecordingContent.AUDIO,
                recording_channel_type=RecordingChannel.UNMIXED,
                recording_format_type=RecordingFormat.WAV,
                recording_storage=AzureBlobContainerRecordingStorage(
                    container_url=self.recording_storage_container_url,
                ),

            )
            logger.info(f"🎤 Started recording for call {server_call_id}")
        except Exception as e:
            logger.error(f"Error starting recording for call {server_call_id}: {e}")

    def stop_recording(self, server_call_id: str):
        """
        Stop recording the call.
        """
        try:
            self.client.stop_recording(server_call_id=server_call_id)
            logger.info(f"🎤 Stopped recording for call {server_call_id}")
        except Exception as e:
            logger.error(f"Error stopping recording for call {server_call_id}: {e}")

