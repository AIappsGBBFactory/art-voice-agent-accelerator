import os
from typing import Callable, Optional, Tuple, List

import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import SpeechRecognitionResult
from dotenv import load_dotenv

from utils.ml_logging import get_logger
import json

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
        *,
        key: Optional[str] = None,
        region: Optional[str] = None,
        candidate_languages: Optional[List[str]] = None,
        language: str = "en-US",
        vad_silence_timeout_ms: int = 1200,
    ):
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")

        self.language = language
        self.candidate_languages = candidate_languages or ["en-US", "es-ES", "fr-FR"]
        self.vad_silence_timeout_ms = vad_silence_timeout_ms

        # user callbacks → (text:str, lang_code:str)
        self.partial_callback: Optional[Callable[[str, str], None]] = None
        self.final_callback: Optional[Callable[[str, str], None]] = None

        self.speech_recognizer: Optional[speechsdk.SpeechRecognizer] = None

    def set_partial_result_callback(
        self, callback: Callable[[str, str], None]
    ) -> None:
        """Set callback invoked on every partial hypothesis."""
        self.partial_callback = callback

    def set_final_result_callback(
        self, callback: Callable[[str, str], None]
    ) -> None:
        """Set callback invoked on every finalized utterance."""
        self.final_callback = callback

    def start(self) -> None:
        """Start continuous recognition with continuous language-ID."""
        logger.info("Starting continuous recognition …")

        speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)

        # switch to continuous LID mode
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
        )

        audio_cfg = speechsdk.audio.AudioConfig(use_default_microphone=True)

        lid_cfg = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.candidate_languages
        )

        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=lid_cfg,
            audio_config=audio_cfg,
        )

        # server-side VAD
        self.speech_recognizer.properties.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
            str(self.vad_silence_timeout_ms),
        )

        # attach events
        if self.partial_callback:
            self.speech_recognizer.recognizing.connect(self._on_recognizing)
        if self.final_callback:
            self.speech_recognizer.recognized.connect(self._on_recognized)

        self.speech_recognizer.canceled.connect(self._on_canceled)
        self.speech_recognizer.session_stopped.connect(self._on_session_stopped)

        self.speech_recognizer.start_continuous_recognition_async().get()
        logger.info(
            "Recognition started with languages=%s (fallback=%s)",
            self.candidate_languages,
            self.language,
        )

    def stop(self) -> None:
        """Gracefully stop recognition."""
        if self.speech_recognizer:
            logger.info("Stopping recognition …")
            self.speech_recognizer.stop_continuous_recognition_async().get()
            logger.info("Recognition stopped.")

    @staticmethod
    def _extract_lang(evt) -> str:
        """
        Return detected language code regardless of LID mode.

        Priority:
        1. evt.result.language   (direct field, works in Continuous)
        2. AutoDetectSourceLanguageResult property
        3. fallback ''  (caller will switch to default)
        """
        if getattr(evt.result, "language", None):
            return evt.result.language

        prop = evt.result.properties.get(
            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult,
            "")
        if prop:
            return prop

        return ""

    # callbacks → wrap user callbacks
    def _on_recognizing(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        txt = evt.result.text
        if txt and self.partial_callback:
            lang = self._extract_lang(evt) or self.language
            self.partial_callback(txt, lang)

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        txt = evt.result.text
        if txt and self.final_callback:
            lang = self._extract_lang(evt) or self.language
            self.final_callback(txt, lang)

    def _on_canceled(self, evt: speechsdk.SessionEventArgs) -> None:
        logger.warning("Recognition canceled: %s", evt)

    def _on_session_stopped(self, evt: speechsdk.SessionEventArgs) -> None:
        logger.info("Session stopped: %s", evt)
