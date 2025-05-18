import os
from typing import Callable, Optional, Tuple

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
    A class for continuously recognizing speech from the microphone using Azure Cognitive Services Speech SDK,
    optimized for reduced latency. This implementation applies the following improvements:

    - Uses asynchronous start/stop methods (start_continuous_recognition_async / stop_continuous_recognition_async)
      to prevent blocking and reduce initialization latency.
    - Sets the default recognition language immediately to avoid time overhead from language detection.
    - Configures a server-side VAD (Voice Activity Detection) using a silence timeout.
    - Attaches callback functions to relay partial and final results in real time.
    - Provides enhanced error handling via logging on cancellation and session stop events.

    Environment Variables (if not provided in __init__):
    - AZURE_SPEECH_KEY:     Your Azure Cognitive Services Speech key
    - AZURE_SPEECH_REGION:  Your Azure Cognitive Services Speech region
    """

    def __init__(
        self,
        key: Optional[str] = None,
        region: Optional[str] = None,
        language: str = "en-US",
        vad_silence_timeout_ms: int = 1200,
    ):
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.language = language
        self.vad_silence_timeout_ms = vad_silence_timeout_ms

        # These callbacks can be set by the user of this class
        self.partial_callback: Optional[Callable[[str], None]] = None
        self.final_callback: Optional[Callable[[str], None]] = None

        # This will hold the actual SpeechRecognizer instance
        self.speech_recognizer: Optional[speechsdk.SpeechRecognizer] = None

    def set_partial_result_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set a callback function to handle partial (in-progress) recognized text.
        The callback should accept a single string argument.
        """
        self.partial_callback = callback

    def set_final_result_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set a callback function to handle finalized recognized text.
        The callback should accept a single string argument.
        """
        self.final_callback = callback

    def start(self) -> None:
        """
        Start continuous speech recognition using asynchronous methods to reduce latency.
        This method sets up the speech configuration, attaches event handlers,
        and initializes asynchronous recognition.
        """
        logger.info(
            "Starting continuous speech recognition with VAD using asynchronous call..."
        )
        logger.debug(
            "Configuration: key=%s, region=%s, language=%s, VAD timeout=%d ms",
            self.key,
            self.region,
            self.language,
            self.vad_silence_timeout_ms,
        )

        # Set up the Speech SDK configuration with the default recognition language.
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region
        )
        speech_config.speech_recognition_language = self.language

        # Use the default microphone as audio input.
        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

        # Initialize the SpeechRecognizer.
        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )

        # Configure server-side Voice Activity Detection (silence timeout).
        self.speech_recognizer.properties.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
            str(self.vad_silence_timeout_ms),
        )

        # Attach event handlers if callbacks have been set.
        if self.partial_callback:
            self.speech_recognizer.recognizing.connect(self._on_recognizing)
        if self.final_callback:
            self.speech_recognizer.recognized.connect(self._on_recognized)

        # Attach additional handlers for cancellation and session stop events.
        self.speech_recognizer.canceled.connect(self._on_canceled)
        self.speech_recognizer.session_stopped.connect(self._on_session_stopped)

        # Start the continuous recognition asynchronously and wait for initialization.
        start_future = self.speech_recognizer.start_continuous_recognition_async()
        start_future.get()  # Blocks until the asynchronous initialization completes.
        logger.info("Continuous speech recognition started.")

    def stop(self) -> None:
        """
        Stop the continuous speech recognition asynchronously.
        """
        if self.speech_recognizer:
            logger.info(
                "Stopping continuous speech recognition using asynchronous call..."
            )
            stop_future = self.speech_recognizer.stop_continuous_recognition_async()
            stop_future.get()  # Blocks until the recognition process has fully stopped.
            logger.info("Continuous speech recognition stopped.")

    def _on_recognizing(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        """
        Internal handler for partial recognition events. Forwards the partial text
        to the user-provided partial callback.
        """
        text = evt.result.text
        if text and self.partial_callback:
            logger.debug("Partial recognized text: %s", text)
            self.partial_callback(text)

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        """
        Internal handler for final recognition events. Forwards the final text
        to the user-provided final callback.
        """
        text = evt.result.text
        if text and self.final_callback:
            logger.debug("Final recognized text: %s", text)
            self.final_callback(text)

    def _on_canceled(self, evt: speechsdk.SessionEventArgs) -> None:
        logger.warning("Speech recognition canceled: %s", evt)
        if evt.result is not None and evt.result.cancellation_details is not None:
            details = evt.result.cancellation_details
            logger.warning(f"Cancellation reason: {details.reason}")
            logger.warning(f"Cancellation error code: {details.error_code}")
            logger.warning(f"Cancellation message: {details.error_details}")

    def _on_session_stopped(self, evt: speechsdk.SessionEventArgs) -> None:
        """
        Internal handler for session-stopped events, indicating the end of a recognition session.
        """
        logger.info("Speech recognition session stopped: %s", evt)
