import json
import os
from typing import Callable, List, Optional, Tuple

import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import SpeechRecognitionResult
from azure.cognitiveservices.speech.audio import AudioStreamFormat
from dotenv import load_dotenv

from utils.ml_logging import get_logger

# Set up logger
logger = get_logger()

# Load environment variables from .env file
load_dotenv()


class StreamingSpeechRecognizerFromBytes:
    """
    Real-time streaming speech recognizer using Azure Speech SDK with PushAudioInputStream.
    Supports:
    - PCM 16kHz 16-bit mono audio in bytes
    - Compressed audio (webm, mp3, ogg) via GStreamer
    - Auto language detection
    - Real-time callbacks for partial and final recognition
    """

    def __init__(
        self,
        *,
        key: Optional[str] = None,
        region: Optional[str] = None,
        candidate_languages: Optional[List[str]] = None,
        use_semantic_segmentation: bool = True,
        vad_silence_timeout_ms: int = 800,
        audio_format: str = "pcm",  # "pcm" or "any"
    ):
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.candidate_languages = candidate_languages or ["en-US", "es-ES", "fr-FR"]
        self.vad_silence_timeout_ms = vad_silence_timeout_ms
        self.audio_format = audio_format  # either "pcm" or "any"
        self.use_semantic = use_semantic_segmentation

        self.final_callback: Optional[Callable[[str, str], None]] = None
        self.partial_callback: Optional[Callable[[str, str], None]] = None
        self.cancel_callback: Optional[Callable[[speechsdk.SessionEventArgs], None]] = (
            None
        )

        self.push_stream = None
        self.speech_recognizer = None

    def set_partial_result_callback(self, callback: Callable[[str, str], None]) -> None:
        self.partial_callback = callback

    def set_final_result_callback(self, callback: Callable[[str, str], None]) -> None:
        self.final_callback = callback

    def set_cancel_callback(
        self, callback: Callable[[speechsdk.SessionEventArgs], None]
    ) -> None:
        """
        Set a callback to handle cancellation events.
        This can be used to log or handle errors when recognition is canceled.
        """
        self.cancel_callback = callback

    def prepare_stream(self) -> None:
        """
        Prepare the audio stream for recognition.
        This method initializes the PushAudioInputStream based on the specified audio format.
        """
        if self.audio_format == "pcm":
            stream_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        elif self.audio_format == "any":
            stream_format = speechsdk.audio.AudioStreamFormat(
                compressed_stream_format=speechsdk.AudioStreamContainerFormat.ANY
            )
        else:
            raise ValueError(f"Unsupported audio_format: {self.audio_format}")

        self.push_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=stream_format
        )

    def start(self) -> None:
        logger.info("Starting recognition from byte stream...")

        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region
        )
        # --- segmentation strategy -------------------------------------- #
        if self.use_semantic:
            speech_config.set_property(
                speechsdk.PropertyId.Speech_SegmentationStrategy, "Semantic")

        # switch to continuous LID mode
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
        )
        lid_cfg = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.candidate_languages
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_StablePartialResultThreshold, "1"
        )

        # PCM format: for raw PCM/linear audio
        if self.audio_format == "pcm":
            stream_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        # ANY format: for browser/native/mobile compressed formats (webm, ogg, mp3, etc)
        elif self.audio_format == "any":
            stream_format = speechsdk.audio.AudioStreamFormat(
                compressed_stream_format=speechsdk.AudioStreamContainerFormat.ANY
            )
        else:
            raise ValueError(f"Unsupported audio_format: {self.audio_format}")

        self.push_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=stream_format
        )
        audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)

        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=lid_cfg,
        )
        if not self.use_semantic:
            # classic silence guard (100-5 000 ms). 800 ms default
            self.speech_recognizer.properties.set_property(
                speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
                str(self.vad_silence_timeout_ms))
            
        if self.partial_callback:
            self.speech_recognizer.recognizing.connect(self._on_recognizing)
        if self.final_callback:
            self.speech_recognizer.recognized.connect(self._on_recognized)
        if self.cancel_callback:
            self.speech_recognizer.canceled.connect(self.cancel_callback)

        self.speech_recognizer.canceled.connect(self._on_canceled)
        self.speech_recognizer.session_stopped.connect(self._on_session_stopped)

        self.speech_recognizer.start_continuous_recognition_async().get()
        # self.speech_recognizer.start_continuous_recognition()
        logger.info("Recognition started.")

    def prepare_start(self) -> None:
        logger.info("Starting recognition from byte stream...")

        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region
        )
         # --- segmentation strategy -------------------------------------- #
        if self.use_semantic:
            speech_config.set_property(
                speechsdk.PropertyId.Speech_SegmentationStrategy, "Semantic")
            
        # switch to continuous LID mode
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
        )
        lid_cfg = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.candidate_languages
        )

        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_StablePartialResultThreshold, "1"
        )

        # PCM format: for raw PCM/linear audio
        if self.audio_format == "pcm":
            stream_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        # ANY format: for browser/native/mobile compressed formats (webm, ogg, mp3, etc)
        elif self.audio_format == "any":
            stream_format = speechsdk.audio.AudioStreamFormat(
                compressed_stream_format=speechsdk.AudioStreamContainerFormat.ANY
            )
        else:
            raise ValueError(f"Unsupported audio_format: {self.audio_format}")

        self.push_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=stream_format
        )
        audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)

        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=lid_cfg,
        )

        if not self.use_semantic:
            # classic silence guard (100-5 000 ms). 800 ms default
            self.speech_recognizer.properties.set_property(
                speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
                str(self.vad_silence_timeout_ms))

        if self.partial_callback:
            self.speech_recognizer.recognizing.connect(self._on_recognizing)
        if self.final_callback:
            self.speech_recognizer.recognized.connect(self._on_recognized)
        if self.cancel_callback:
            self.speech_recognizer.canceled.connect(self.cancel_callback)

        self.speech_recognizer.canceled.connect(self._on_canceled)
        self.speech_recognizer.session_stopped.connect(self._on_session_stopped)

        logger.info("Recognition ready to start.")

    def write_bytes(self, audio_chunk: bytes) -> None:
        if self.push_stream:
            self.push_stream.write(audio_chunk)

    def stop(self) -> None:
        if self.speech_recognizer:
            self.speech_recognizer.stop_continuous_recognition_async().get()
            # self.speech_recognizer.stop_continuous_recognition()
            logger.info("Recognition stopped.")

    def close_stream(self) -> None:
        if self.push_stream:
            self.push_stream.close()

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
            "",
        )
        if prop:
            return prop

        return ""

    # callbacks → wrap user callbacks
    def _on_recognizing(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        txt = evt.result.text
        if txt and self.partial_callback:
            # extract whatever lang Azure selected (or fallback to first candidate)
            detected = (
                speechsdk.AutoDetectSourceLanguageResult(evt.result).language
                or self.candidate_languages[0]
            )
            self.partial_callback(txt, detected)

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            detected_lang = speechsdk.AutoDetectSourceLanguageResult(
                evt.result
            ).language
            if self.final_callback and evt.result.text:
                self.final_callback(evt.result.text, detected_lang)

    def _on_canceled(self, evt: speechsdk.SessionEventArgs) -> None:
        logger.warning("Recognition canceled: %s", evt)
        if evt.result and evt.result.cancellation_details:
            details = evt.result.cancellation_details
            logger.warning(f"Reason: {details.reason}, Error: {details.error_details}")

    def _on_session_stopped(self, evt: speechsdk.SessionEventArgs) -> None:
        logger.info("Session stopped.")
