import json
import os
from typing import Callable, List, Optional, Final

import azure.cognitiveservices.speech as speechsdk
from utils.azure_auth import get_credential
from dotenv import load_dotenv

# OpenTelemetry imports for tracing
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

# Import centralized span attributes enum
from src.enums.monitoring import SpanAttr
from utils.ml_logging import get_logger

# Set up logger
logger = get_logger(__name__)

# Load environment variables from .env file
load_dotenv()


class StreamingSpeechRecognizerFromBytes:
    """
    Real-time streaming speech recognizer using Azure Speech SDK with PushAudioInputStream.

    Authentication:
    - If key is provided: Uses API key authentication
    - If key is None: Uses Azure Default Credentials (managed identity, service principal, etc.)

    Supports:
    - PCM 16kHz 16-bit mono audio in bytes
    - Compressed audio (webm, mp3, ogg) via GStreamer
    - Auto language detection
    - Real-time callbacks for partial and final recognition
    - Azure Monitor OpenTelemetry tracing with call correlation
    """

    _DEFAULT_LANGS: Final[List[str]] = [
        "en-US",
        "es-ES",
        "fr-FR",
        "de-DE",
        "it-IT",
    ]

    def __init__(
        self,
        *,
        key: Optional[str] = None,
        region: Optional[str] = None,
        # Behaviour -----------------------------------------------------
        candidate_languages: List[str] | None = None,
        vad_silence_timeout_ms: int = 800,
        use_semantic_segmentation: bool = True,
        audio_format: str = "pcm",  # "pcm" | "any"
        # Advanced features --------------------------------------------
        enable_neural_fe: bool = False,
        enable_diarisation: bool = True,
        speaker_count_hint: int = 2,
        # Observability -------------------------------------------------
        call_connection_id: str | None = None,
        enable_tracing: bool = True,
    ):
        """
        Initialize the StreamingSpeechRecognizerFromBytes.

        Args:
            key: Azure Speech API key. If None, will use Azure Default Credentials
            region: Azure region (required for both API key and credential authentication)
            candidate_languages: List of language codes for auto-detection
            vad_silence_timeout_ms: Voice activity detection silence timeout
            audio_format: "pcm" for raw PCM audio or "any" for compressed formats
            call_connection_id: Call connection ID for correlation in Azure Monitor
            enable_tracing: Whether to enable Azure Monitor tracing
        """
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.candidate_languages = candidate_languages or self._DEFAULT_LANGS
        self.vad_silence_timeout_ms = vad_silence_timeout_ms
        self.audio_format = audio_format  # either "pcm" or "any"
        self.use_semantic = use_semantic_segmentation

        self.call_connection_id = call_connection_id or "unknown"
        self.enable_tracing = enable_tracing

        self.partial_callback: Optional[Callable[[str, str, str | None], None]] = None
        self.final_callback: Optional[Callable[[str, str, str | None], None]] = None
        self.cancel_callback: Optional[
            Callable[[speechsdk.SessionEventArgs], None]
        ] = None

        # Advanced feature flags
        self._enable_neural_fe = enable_neural_fe
        self._enable_diarisation = enable_diarisation
        self._speaker_hint = max(0, min(speaker_count_hint, 16))

        self.push_stream = None
        self.speech_recognizer = None

        # Initialize tracing
        self.tracer = None
        self._session_span = None
        if self.enable_tracing:
            try:
                # Initialize Azure Monitor if not already done
                # init_logging_and_monitoring("speech_recognizer")
                self.tracer = trace.get_tracer(__name__)
                logger.info("Azure Monitor tracing initialized for speech recognizer")
            except Exception as e:
                logger.warning(f"Failed to initialize Azure Monitor tracing: {e}")
                self.enable_tracing = False

        self.cfg = self._create_speech_config()

    def set_call_connection_id(self, call_connection_id: str) -> None:
        """
        Set the call connection ID for correlation in tracing and logging.
        """
        self.call_connection_id = call_connection_id

    def _create_speech_config(self) -> speechsdk.SpeechConfig:
        """
        Create SpeechConfig using either API key or Azure Default Credentials
        Following Azure best practices for authentication
        """
        if self.key:
            # Use API key authentication if provided
            logger.info("Creating SpeechConfig with API key authentication")
            return speechsdk.SpeechConfig(subscription=self.key, region=self.region)
        else:
            # Use Azure Default Credentials (managed identity, service principal, etc.)
            logger.info("Creating SpeechConfig with Azure Default Credentials")
            if not self.region:
                raise ValueError(
                    "Region must be specified when using Azure Default Credentials"
                )

            endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
            credential = get_credential()

            if endpoint:
                # Use endpoint if provided
                speech_config = speechsdk.SpeechConfig(endpoint=endpoint)
            else:
                speech_config = speechsdk.SpeechConfig(region=self.region)

            # Set the authorization token
            try:
                # Get token for Cognitive Services scope
                token_result = credential.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
                speech_config.authorization_token = token_result.token
                logger.info(
                    "Successfully configured SpeechConfig with Azure Default Credentials"
                )
            except Exception as e:
                logger.error(
                    f"Failed to get Azure token: {e}. Ensure that the required RBAC role, such as 'Cognitive Services User', is assigned to your identity."
                )
                raise ValueError(
                    f"Failed to authenticate with Azure Default Credentials: {e}. Ensure that the required RBAC role, such as 'Cognitive Services User', is assigned to your identity."
                )

            return speech_config

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
        """Start speech recognition with Azure Monitor tracing"""
        if self.enable_tracing and self.tracer:
            # Start a session-level span for the entire speech recognition session
            self._session_span = self.tracer.start_span(
                "speech_recognition_session", kind=SpanKind.CLIENT
            )

            # Set session attributes for correlation
            self._session_span.set_attribute(
                "rt.call.connection_id", self.call_connection_id
            )
            self._session_span.set_attribute("rt.session.id", self.call_connection_id)
            self._session_span.set_attribute("ai.operation.id", self.call_connection_id)
            self._session_span.set_attribute("speech.region", self.region)

            # Help App Map recognize this as an external service dependency
            self._session_span.set_attribute("peer.service", "azure-cognitive-speech")
            self._session_span.set_attribute(
                "net.peer.name", f"{self.region}.stt.speech.microsoft.com"
            )
            # Make it look like an HTTP/WebSocket dependency
            self._session_span.set_attribute(
                "server.address", f"{self.region}.stt.speech.microsoft.com"
            )
            self._session_span.set_attribute("server.port", 443)
            self._session_span.set_attribute("network.protocol.name", "websocket")
            # Let the exporter classify as HTTP if it prefers http.* (belt & suspenders)
            self._session_span.set_attribute("http.method", "POST")
            # Set http.url using endpoint if provided, else construct from region
            endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
            if endpoint:
                self._session_span.set_attribute(
                    "http.url",
                    f"{endpoint.rstrip('/')}/speech/recognition/conversation/cognitiveservices/v1",
                )
            else:
                self._session_span.set_attribute(
                    "http.url",
                    f"https://{self.region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1",
                )
            self._session_span.set_attribute("speech.audio_format", self.audio_format)
            self._session_span.set_attribute(
                "speech.candidate_languages", ",".join(self.candidate_languages)
            )
            self._session_span.set_attribute(
                "speech.vad_timeout_ms", self.vad_silence_timeout_ms
            )

            # Set standard attributes if available
            self._session_span.set_attribute(
                SpanAttr.SERVICE_NAME, "azure-speech-recognition"
            )
            self._session_span.set_attribute(SpanAttr.SERVICE_VERSION, "1.0.0")

            # Make this span current for the duration of setup
            with trace.use_span(self._session_span):
                self._start_recognition()
        else:
            self._start_recognition()

    def _start_recognition(self) -> None:
        """
        Build the Speech SDK recogniser **and start it** in one shot.
        """
        logger.info("Starting recognition from byte stream…")

        self.prepare_start()
        self.speech_recognizer.start_continuous_recognition_async().get()

        logger.info("Recognition started.")
        if self._session_span:
            self._session_span.add_event("speech_recognition_started")

    def prepare_start(self) -> None:
        """
        Allocate PushAudioInputStream + SpeechRecognizer.

        • Neural front-end (noise-suppression / AEC / AGC) is enabled
        when `self.` is *True*.
        • Speaker diarisation is enabled when `self.enable_diarisation` is *True*.
        • All other behaviour (LID, semantic segmentation, VAD, etc.)
        follows the class-level settings.
        """
        logger.info(
            "Speech-SDK prepare_start – format=%s  neuralFE=%s  diar=%s",
            self.audio_format,
            self._enable_neural_fe,
            self._enable_diarisation,
        )

        # ------------------------------------------------------------------ #
        # 1. SpeechConfig – global properties
        # ------------------------------------------------------------------ #
        speech_config = self.cfg

        if self.use_semantic:
            speech_config.set_property(
                speechsdk.PropertyId.Speech_SegmentationStrategy, "Semantic"
            )

        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
        )

        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_StablePartialResultThreshold, "1"
        )

        # ── Speaker diarisation (if requested) ────────────────────────────
        if self._enable_diarisation:
            speech_config.set_property(
                property_id=speechsdk.PropertyId.SpeechServiceResponse_DiarizeIntermediateResults,
                value="true",
            )
            # speech_config.set_property(
            #     speechsdk.PropertyId.SpeechServiceConnection_SpeakerDiarizationSpeakerCount,
            #     str(self._speaker_hint))

        # ------------------------------------------------------------------ #
        # 2. PushAudioInputStream – container vs. raw PCM
        # ------------------------------------------------------------------ #
        if self.audio_format == "pcm":
            stream_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1
            )
        elif self.audio_format == "any":
            stream_format = speechsdk.audio.AudioStreamFormat(
                compressed_stream_format=speechsdk.AudioStreamContainerFormat.ANY
            )
        else:
            raise ValueError(f"Unsupported audio_format: {self.audio_format!r}")

        self.push_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=stream_format
        )

        # ------------------------------------------------------------------ #
        # 3. Optional neural audio front-end
        # ------------------------------------------------------------------ #
        if self._enable_neural_fe:
            proc_opts = speechsdk.audio.AudioProcessingOptions(
                speechsdk.audio.AudioProcessingConstants.AUDIO_INPUT_PROCESSING_ENABLE_DEFAULT,
                speechsdk.audio.AudioProcessingConstants.AUDIO_INPUT_PROCESSING_MODE_DEFAULT,
            )
            audio_config = speechsdk.audio.AudioConfig(
                stream=self.push_stream, audio_processing_options=proc_opts
            )
        else:
            audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)

        # ------------------------------------------------------------------ #
        # 4. LID configuration
        # ------------------------------------------------------------------ #
        lid_cfg = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.candidate_languages
        )

        # ------------------------------------------------------------------ #
        # 5. Build recogniser (still no network traffic)
        # ------------------------------------------------------------------ #
        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=lid_cfg,
        )

        if not self.use_semantic:
            self.speech_recognizer.properties.set_property(
                speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
                str(self.vad_silence_timeout_ms),
            )

        # ------------------------------------------------------------------ #
        # 6. Wire callbacks / health telemetry
        # ------------------------------------------------------------------ #
        logger.debug(
            f"🔗 Setting up callbacks: partial={self.partial_callback is not None}, final={self.final_callback is not None}, cancel={self.cancel_callback is not None}"
        )

        if self.partial_callback:
            self.speech_recognizer.recognizing.connect(self._on_recognizing)
            logger.debug("✅ Connected partial callback (_on_recognizing)")
        if self.final_callback:
            self.speech_recognizer.recognized.connect(self._on_recognized)
            logger.debug("✅ Connected final callback (_on_recognized)")
        if self.cancel_callback:
            self.speech_recognizer.canceled.connect(self.cancel_callback)
            logger.debug("✅ Connected cancel callback")

        self.speech_recognizer.canceled.connect(self._on_canceled)
        self.speech_recognizer.session_stopped.connect(self._on_session_stopped)

        logger.info(
            "Speech-SDK ready " "(neuralFE=%s, diarisation=%s, speakers=%s)",
            self._enable_neural_fe,
            self._enable_diarisation,
            self._speaker_hint,
        )

    def write_bytes(self, audio_chunk: bytes) -> None:
        """Write audio bytes to the stream; avoid per-chunk spans to keep overhead low.
        Emits an event on the session span instead for coarse visibility.
        """
        logger.debug(
            f"🎤 write_bytes called: {len(audio_chunk)} bytes, has_push_stream={self.push_stream is not None}"
        )
        if self.push_stream:
            if self.enable_tracing and self._session_span:
                try:
                    self._session_span.add_event(
                        "audio_chunk", {"size": len(audio_chunk)}
                    )
                except Exception:
                    pass
            self.push_stream.write(audio_chunk)
            logger.debug(f"✅ Audio chunk written to push_stream")
        else:
            logger.warning(
                f"⚠️ write_bytes called but push_stream is None! {len(audio_chunk)} bytes discarded"
            )

    def stop(self) -> None:
        """Stop recognition with tracing cleanup"""
        if self.speech_recognizer:
            # Add event to session span before stopping
            if self._session_span:
                self._session_span.add_event("speech_recognition_stopping")

            # Stop recognition asynchronously without blocking
            future = self.speech_recognizer.stop_continuous_recognition_async()
            logger.debug(
                "🛑 Speech recognition stop initiated asynchronously (non-blocking)"
            )
            logger.info("Recognition stopped.")

            # Finish session span if it's still active
            if self._session_span:
                self._session_span.add_event("speech_recognition_stopped")
                self._session_span.set_status(Status(StatusCode.OK))
                self._session_span.end()
                self._session_span = None

    def close_stream(self) -> None:
        """Close the audio stream with tracing"""
        if self.push_stream:
            # Add event to session span before closing
            if self._session_span:
                self._session_span.add_event("audio_stream_closing")

            self.push_stream.close()

            # Final cleanup of session span if still active
            if self._session_span:
                self._session_span.add_event("audio_stream_closed")
                self._session_span.end()
                self._session_span = None

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

    def _extract_speaker_id(self, evt):
        blob = evt.result.properties.get(
            speechsdk.PropertyId.SpeechServiceResponse_JsonResult, ""
        )
        if blob:
            try:
                return str(json.loads(blob).get("SpeakerId"))
            except Exception:
                pass
        return None

    # callbacks → wrap user callbacks with tracing
    def _on_recognizing(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        """Handle partial recognition results with tracing"""
        txt = evt.result.text
        speaker_id = self._extract_speaker_id(evt)

        # Extract language outside the tracing block to avoid scope issues
        detected = (
            speechsdk.AutoDetectSourceLanguageResult(evt.result).language
            or self.candidate_languages[0]
        )

        logger.debug(
            f"🔍 _on_recognizing called: text='{txt}', detected_lang='{detected}', has_callback={self.partial_callback is not None}"
        )

        if txt and self.partial_callback:
            # Create a span for partial recognition
            if self.enable_tracing and self.tracer:
                with self.tracer.start_as_current_span(
                    "speech_partial_recognition",
                    kind=SpanKind.CLIENT,
                    attributes={
                        "speech.result.type": "partial",
                        "speech.result.text_length": len(txt),
                        "rt.call.connection_id": self.call_connection_id,
                    },
                ) as span:
                    span.set_attribute("speech.detected_language", detected)

                    # Add event to session span
                    if self._session_span:
                        self._session_span.add_event(
                            "partial_recognition_received",
                            {"text_length": len(txt), "detected_language": detected},
                        )

            logger.debug(
                f"🔥 Calling partial_callback with: '{txt}', '{detected}', '{speaker_id}'"
            )
            self.partial_callback(txt, detected, speaker_id)
        elif txt:
            logger.debug(f"⚠️ Got text but no partial_callback: '{txt}'")
        else:
            logger.debug(f"🔇 Empty text in recognizing event")

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        """Handle final recognition results with tracing"""
        logger.debug(
            f"🔍 _on_recognized called: reason={evt.result.reason}, text='{evt.result.text}', has_callback={self.final_callback is not None}"
        )

        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            detected_lang = (
                speechsdk.AutoDetectSourceLanguageResult(evt.result).language
                or self.candidate_languages[0]
            )

            logger.debug(
                f"🔍 Recognition successful: text='{evt.result.text}', detected_lang='{detected_lang}'"
            )

            if self.enable_tracing and self.tracer and evt.result.text:
                with self.tracer.start_as_current_span(
                    "speech_final_recognition",
                    kind=SpanKind.CLIENT,
                    attributes={
                        "speech.result.type": "final",
                        "speech.result.text_length": len(evt.result.text),
                        "speech.detected_language": detected_lang,
                        "rt.call.connection_id": self.call_connection_id,
                        "speech.result.reason": str(evt.result.reason),
                    },
                ) as span:
                    # Add event to session span
                    if self._session_span:
                        self._session_span.add_event(
                            "final_recognition_received",
                            {
                                "text_length": len(evt.result.text),
                                "detected_language": detected_lang,
                                "text_preview": (
                                    evt.result.text[:50] + "..."
                                    if len(evt.result.text) > 50
                                    else evt.result.text
                                ),
                            },
                        )

            if self.final_callback and evt.result.text:
                logger.debug(
                    f"🔥 Calling final_callback with: '{evt.result.text}', '{detected_lang}'"
                )
                self.final_callback(evt.result.text, detected_lang)
            elif evt.result.text:
                logger.debug(
                    f"⚠️ Got final text but no final_callback: '{evt.result.text}'"
                )
        else:
            logger.debug(
                f"🚫 Recognition result reason not RecognizedSpeech: {evt.result.reason}"
            )

    def _on_canceled(self, evt: speechsdk.SessionEventArgs) -> None:
        """Handle cancellation events with tracing"""
        logger.warning("Recognition canceled: %s", evt)

        # Add error event to session span
        if self._session_span:
            self._session_span.set_status(
                Status(StatusCode.ERROR, "Recognition canceled")
            )
            self._session_span.add_event(
                "recognition_canceled", {"event_details": str(evt)}
            )

        if evt.result and evt.result.cancellation_details:
            details = evt.result.cancellation_details
            error_msg = f"Reason: {details.reason}, Error: {details.error_details}"
            logger.warning(error_msg)

            # Add detailed error information to span
            if self._session_span:
                self._session_span.add_event(
                    "cancellation_details",
                    {
                        "cancellation_reason": str(details.reason),
                        "error_details": details.error_details,
                    },
                )

    def _on_session_stopped(self, evt: speechsdk.SessionEventArgs) -> None:
        """Handle session stopped events with tracing"""
        logger.info("Session stopped.")

        # Add event to session span and finish it
        if self._session_span:
            self._session_span.add_event("speech_session_stopped")
            self._session_span.set_status(Status(StatusCode.OK))
            self._session_span.end()
            self._session_span = None
