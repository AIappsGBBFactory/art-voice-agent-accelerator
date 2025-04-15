import os
from typing import Optional, Tuple, Callable

import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import SpeechRecognitionResult
from dotenv import load_dotenv

from utils.ml_logging import get_logger

# Set up logger
logger = get_logger()

# Load environment variables from .env file
load_dotenv()


class SpeechRecognizer:
    """
    A class that encapsulates the Azure Cognitive Services Speech SDK functionality for recognizing speech.
    """

    def __init__(self, key: str = None, region: str = None, language: str = "en-US"):
        """
        Initializes a new instance of the SpeechRecognizer class.

        Args:
            key (str, optional): The subscription key for the Speech service. Defaults to the SPEECH_KEY environment variable.
            region (str, optional): The region for the Speech service. Defaults to the SPEECH_REGION environment variable.
            language (str, optional): The language for the Speech service. Defaults to "en-US".
        """
        self.key = key if key is not None else os.getenv("AZURE_SPEECH_KEY")
        self.region = region if region is not None else os.getenv("AZURE_SPEECH_REGION")
        self.language = language

    def recognize_from_microphone(
        self,
    ) -> Tuple[str, Optional[SpeechRecognitionResult]]:
        """
        Recognizes speech from the microphone.

        Returns:
            Tuple[str, Optional[SpeechRecognitionResult]]: The recognized text and the result object.
        """
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region
        )
        speech_config.speech_recognition_language = self.language

        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )

        logger.info("Speak into your microphone.")
        speech_recognition_result = speech_recognizer.recognize_once_async().get()

        if speech_recognition_result.reason == speechsdk.ResultReason.RecognizedSpeech:
            logger.info("Recognized: {}".format(speech_recognition_result.text))
        elif speech_recognition_result.reason == speechsdk.ResultReason.NoMatch:
            logger.warning(
                "No speech could be recognized: {}".format(
                    speech_recognition_result.no_match_details
                )
            )
        elif speech_recognition_result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = speech_recognition_result.cancellation_details
            logger.error(
                "Speech Recognition canceled: {}".format(cancellation_details.reason)
            )
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                logger.error(
                    "Error details: {}".format(cancellation_details.error_details)
                )
                logger.error("Did you set the speech resource key and region values?")

        # Return the recognized text and the result object
        return speech_recognition_result.text, speech_recognition_result


class StreamingSpeechRecognizer:
    """
    A class for continuously recognizing speech from the microphone using Azure Cognitive Services Speech SDK.
    
    Features:
    - Continuous microphone listening
    - Server-side VAD based on silence timeout
    - Real-time partial results
    - Final results when user stops speaking
    - Best-practice event handling for errors and session stops
    
    Environment Variables (loaded automatically if not provided in init):
    - AZURE_SPEECH_KEY:     Your Azure Cognitive Services Speech key
    - AZURE_SPEECH_REGION:  Your Azure Cognitive Services Speech region
    
    Args:
        key (Optional[str]): Azure Speech subscription key (defaults to env var if None).
        region (Optional[str]): Azure Speech service region (defaults to env var if None).
        language (str): The language code for recognition (default: 'en-US').
        vad_silence_timeout_ms (int): Silence duration (ms) after which speech is considered ended.
    """

    def __init__(
        self,
        key: Optional[str] = None,
        region: Optional[str] = None,
        language: str = "en-US",
        vad_silence_timeout_ms: int = 1200
    ):
        self.key = key if key is not None else os.getenv("AZURE_SPEECH_KEY")
        self.region = region if region is not None else os.getenv("AZURE_SPEECH_REGION")
        self.language = language
        self.vad_silence_timeout_ms = vad_silence_timeout_ms

        self.speech_recognizer: Optional[speechsdk.SpeechRecognizer] = None
        self.partial_callback: Optional[Callable[[str], None]] = None
        self.final_callback: Optional[Callable[[str], None]] = None

    def set_partial_result_callback(self, callback: Callable[[str], None]) -> None:
        """
        Attach a callback function to handle partial (in-progress) recognized text.
        
        Args:
            callback (Callable[[str], None]): Function that receives partial recognized text.
        """
        self.partial_callback = callback

    def set_final_result_callback(self, callback: Callable[[str], None]) -> None:
        """
        Attach a callback function to handle finalized recognized text.
        
        Args:
            callback (Callable[[str], None]): Function that receives the final recognized text.
        """
        self.final_callback = callback

    def start(self) -> None:
        """
        Start continuous speech recognition from the microphone using VAD settings.
        """
        logger.info("Starting continuous speech recognition with VAD...")
        logger.debug(
            "Recognizer config: key=%s region=%s language=%s silence_timeout_ms=%d",
            self.key, self.region, self.language, self.vad_silence_timeout_ms
        )

        # Set up Azure Speech config
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key,
            region=self.region
        )
        speech_config.speech_recognition_language = self.language

        # Audio input from microphone
        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

        # Initialize the recognizer
        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        # Configure server-side Voice Activity Detection (silence timeout)
        self.speech_recognizer.properties.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
            str(self.vad_silence_timeout_ms)
        )

        # Connect event handlers
        if self.partial_callback:
            self.speech_recognizer.recognizing.connect(self._on_recognizing)
        if self.final_callback:
            self.speech_recognizer.recognized.connect(self._on_recognized)

        # Additional recommended handlers
        self.speech_recognizer.canceled.connect(self._on_canceled)
        self.speech_recognizer.session_stopped.connect(self._on_session_stopped)

        # Start listening
        self.speech_recognizer.start_continuous_recognition()

    def stop(self) -> None:
        """
        Stop continuous speech recognition if running.
        """
        if self.speech_recognizer:
            logger.info("Stopping continuous speech recognition...")
            self.speech_recognizer.stop_continuous_recognition()

    def _on_recognizing(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        """
        Internal handler triggered for partial recognition events.
        """
        if evt.result.text and self.partial_callback:
            logger.debug("Partial recognized text: %s", evt.result.text)
            self.partial_callback(evt.result.text)

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        """
        Internal handler triggered for final recognition events.
        """
        if evt.result.text and self.final_callback:
            logger.debug("Final recognized text: %s", evt.result.text)
            self.final_callback(evt.result.text)

    def _on_canceled(self, evt: speechsdk.SessionEventArgs) -> None:
        """
        Handler for canceled events, such as network issues or runtime errors.
        """
        logger.warning("Recognition canceled. Reason: %s", evt)
        

    def _on_session_stopped(self, evt: speechsdk.SessionEventArgs) -> None:
        """
        Handler for session-stopped events (end of the session).
        """
        logger.info("Session stopped: %s", evt)
    
