import html
import os
import re
import asyncio
import time
from typing import Callable, Dict, List, Optional

import azure.cognitiveservices.speech as speechsdk
from utils.azure_auth import get_credential
from dotenv import load_dotenv
from langdetect import LangDetectException, detect

# OpenTelemetry imports for tracing
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

# Import centralized span attributes enum
from src.enums.monitoring import SpanAttr
from utils.ml_logging import get_logger

# Load environment variables from a .env file if present
load_dotenv()

# Initialize logger
logger = get_logger(__name__)

_SENTENCE_END = re.compile(r"([.!?；？！。]+|\n)")


def split_sentences(text: str) -> List[str]:
    """Very small sentence splitter that keeps delimiters."""
    parts, buf = [], []
    for ch in text:
        buf.append(ch)
        if _SENTENCE_END.match(ch):
            parts.append("".join(buf).strip())
            buf.clear()
    if buf:
        parts.append("".join(buf).strip())
    return parts


def auto_style(lang_code: str) -> Dict[str, str]:
    """Return style / rate tweaks per language family."""
    if lang_code.startswith(("es", "fr", "it")):
        return {"style": "chat", "rate": "+3%"}
    if lang_code.startswith("en"):
        return {"style": "chat", "rate": "+3%"}
    return {}


def ssml_voice_wrap(
    voice: str,
    language: str,
    sentences: List[str],
    sanitizer: Callable[[str], str],
    style: str = None,
    rate: str = None,
) -> str:
    """Build one SSML doc with a single <voice> tag for efficiency.

    Args:
        voice: Voice name to use
        language: Language code
        sentences: List of text sentences
        sanitizer: Function to sanitize text for XML
        style: Optional voice style
        rate: Optional speech rate
    """
    body = []
    for seg in sentences:
        try:
            lang = detect(seg)
        except LangDetectException:
            lang = language
        attrs = auto_style(lang)
        inner = sanitizer(seg)

        # Apply custom rate or auto-detected rate
        prosody_rate = rate or attrs.get("rate")
        if prosody_rate:
            inner = f'<prosody rate="{prosody_rate}">{inner}</prosody>'

        # Apply custom style or auto-detected style
        voice_style = style or attrs.get("style")
        if voice_style:
            inner = (
                f'<mstts:express-as style="{voice_style}">{inner}</mstts:express-as>'
            )

        # optional language switch
        if lang != language:
            inner = f'<lang xml:lang="{lang}">{inner}</lang>'

        body.append(inner)

    joined = "".join(body)
    return (
        '<speak version="1.0" '
        'xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" '
        f'xml:lang="{language}">'
        f'<voice name="{voice}">{joined}</voice>'
        "</speak>"
    )


def _is_headless() -> bool:
    """
    Very light‑weight heuristics:
      • Linux & no DISPLAY   ➜ container / server
      • CI env variable set  ➜ pipeline runner
    Extend if you need Windows detection (e.g. `%SESSIONNAME%`)
    """
    import sys

    return (sys.platform.startswith("linux") and not os.environ.get("DISPLAY")) or bool(
        os.environ.get("CI")
    )


class SpeechSynthesizer:
    # Limit concurrent server-side TTS synth requests to avoid SDK/service hiccups
    _synth_semaphore = asyncio.Semaphore(4)

    def __init__(
        self,
        key: str = None,
        region: str = None,
        language: str = "en-US",
        voice: str = "en-US-JennyMultilingualNeural",
        format: speechsdk.SpeechSynthesisOutputFormat = speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,
        playback: str = "auto",  # "auto" | "always" | "never"
        call_connection_id: Optional[str] = None,
        enable_tracing: bool = True,
    ):
        # Retrieve Azure Speech credentials from parameters or environment variables
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.language = language
        self.voice = voice
        self.format = format
        self.playback = playback
        self.enable_tracing = enable_tracing
        self.call_connection_id = call_connection_id or "unknown"

        # Initialize tracing components (matching speech_recognizer pattern)
        self.tracer = None
        self._session_span = None

        if self.enable_tracing:
            try:
                # Use same pattern as speech_recognizer
                self.tracer = trace.get_tracer(__name__)
                logger.info("Azure Monitor tracing initialized for speech synthesizer")
            except Exception as e:
                logger.warning(f"Failed to initialize Azure Monitor tracing: {e}")
                self.enable_tracing = False
                # Temporarily disable to avoid startup errors
                logger.info("Continuing without Azure Monitor tracing")

        # DON'T initialize speaker synthesizer during __init__ to avoid audio library issues
        # Only create it when actually needed for speaker playback
        self._speaker = None

        # Create base speech config for other operations
        self.cfg = None
        try:
            self.cfg = self._create_speech_config()
            logger.info("Speech synthesizer initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize speech config: {e}")
            # Don't fail completely - allow for memory-only synthesis

    def set_call_connection_id(self, call_connection_id: str) -> None:
        """
        Set the call connection ID for correlation in tracing and logging.
        """
        self.call_connection_id = call_connection_id

    def _create_speech_config(self):
        """
        Helper method to create and configure the SpeechConfig object.
        Creates a fresh config each time to handle token expiration.
        """
        if self.key:
            # Use API key authentication if provided
            logger.info("Creating SpeechConfig with API key authentication")
            speech_config = speechsdk.SpeechConfig(
                subscription=self.key, region=self.region
            )
        else:
            # Use Azure Default Credentials (managed identity, service principal, etc.)
            logger.info("Creating SpeechConfig with Azure Default Credentials")
            if not self.region:
                raise ValueError(
                    "Region must be specified when using Azure Default Credentials"
                )

            endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
            credential = get_credential()

            # Use default Azure credential for authentication
            # Get a fresh token each time to handle token expiration
            try:
                logger.debug(
                    "Attempting to use DefaultAzureCredential for Azure Speech"
                )
                credential = get_credential()
                speech_resource_id = os.getenv("AZURE_SPEECH_RESOURCE_ID")
                token = credential.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
                auth_token = "aad#" + speech_resource_id + "#" + token.token
                speech_config = speechsdk.SpeechConfig(
                    auth_token=auth_token, region=self.region
                )

                logger.debug("Successfully authenticated with DefaultAzureCredential")
            except Exception as e:
                logger.error(f"Failed to get Azure credential token: {e}")
                raise RuntimeError(
                    f"Failed to authenticate with Azure Speech. Please set AZURE_SPEECH_KEY environment variable or ensure proper Azure credentials are configured: {e}"
                )

        if not speech_config:
            raise RuntimeError(
                "Failed to create speech config - no valid authentication method found"
            )

        speech_config.speech_synthesis_language = self.language
        speech_config.speech_synthesis_voice_name = self.voice
        # Set the output format to 24kHz 16-bit mono PCM WAV
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )
        return speech_config

    def _create_speaker_synthesizer(self):
        """
        Build a SpeechSynthesizer for speaker playback, honoring the `playback` flag.

            playback = "never"   ➜ always return None (no attempt)
            playback = "auto"    ➜ create only if a speaker is likely present
            playback = "always"  ➜ always create (falls back to null‑sink in head‑less env)

        Returns:
            speechsdk.SpeechSynthesizer | None
        """
        # 1. Never mode: do not create a speaker synthesizer
        if self.playback == "never":
            logger.debug("playback='never' – speaker creation skipped")
            return None

        # 2. If already created, return cached instance
        if self._speaker is not None:
            return self._speaker

        # 3. Create the speaker synthesizer according to playback mode
        try:
            speech_config = self.cfg
            headless = _is_headless()

            if self.playback == "always":
                # Always create, use null sink if headless
                if headless:
                    audio_config = speechsdk.audio.AudioOutputConfig(filename=None)
                    logger.debug(
                        "playback='always' – headless: using null audio output"
                    )
                else:
                    audio_config = speechsdk.audio.AudioOutputConfig(
                        use_default_speaker=True
                    )
                    logger.debug(
                        "playback='always' – using default system speaker output"
                    )
                self._speaker = speechsdk.SpeechSynthesizer(
                    speech_config=speech_config, audio_config=audio_config
                )
            elif self.playback == "auto":
                # Only create if not headless
                if headless:
                    logger.debug("playback='auto' – headless: speaker not created")
                    self._speaker = None
                else:
                    audio_config = speechsdk.audio.AudioOutputConfig(
                        use_default_speaker=True
                    )
                    logger.debug(
                        "playback='auto' – using default system speaker output"
                    )
                    self._speaker = speechsdk.SpeechSynthesizer(
                        speech_config=speech_config, audio_config=audio_config
                    )
        except Exception as exc:
            logger.warning("Could not create speaker synthesizer: %s", exc)
            self._speaker = None  # fall back to memory-only synthesis

        return self._speaker

    @staticmethod
    def _sanitize(text: str) -> str:
        """
        Escape XML-significant characters (&, <, >, ", ') so the text
        can be inserted inside an SSML <prosody> block safely.
        """
        return html.escape(text, quote=True)

    def start_speaking_text(
        self, text: str, voice: str = None, rate: str = "15%", style: str = None
    ) -> None:
        """
        Synthesize and play text through the server's speakers (if available).
        In headless environments, this will log a warning and skip playback.

        Args:
            text: Text to synthesize
            voice: Voice name (defaults to self.voice)
            rate: Speech rate (defaults to "15%")
            style: Voice style (defaults to None)
        """
        # Check environment variable to determine if playback is enabled
        playback_env = os.getenv("TTS_ENABLE_LOCAL_PLAYBACK", "true").lower()
        voice = voice or self.voice
        if playback_env not in ("1", "true", "yes"):
            logger.info(
                "TTS_ENABLE_LOCAL_PLAYBACK is set to false; skipping audio playback."
            )
            return
        # Start session-level span for speaker synthesis if tracing is enabled
        if self.enable_tracing and self.tracer:
            self._session_span = self.tracer.start_span(
                "tts_speaker_synthesis_session", kind=SpanKind.CLIENT
            )

            # Correlation keys
            self._session_span.set_attribute(
                "rt.call.connection_id", self.call_connection_id
            )
            self._session_span.set_attribute("rt.session.id", self.call_connection_id)

            # Service specific attributes
            self._session_span.set_attribute("tts.region", self.region)
            self._session_span.set_attribute("tts.voice", voice or self.voice)
            self._session_span.set_attribute("tts.language", self.language)
            self._session_span.set_attribute("tts.text_length", len(text))
            self._session_span.set_attribute("tts.operation_type", "speaker_synthesis")
            self._session_span.set_attribute(
                "server.address", f"{self.region}.tts.speech.microsoft.com"
            )
            self._session_span.set_attribute("server.port", 443)
            self._session_span.set_attribute("http.method", "POST")
            # Use endpoint if set, otherwise default to region-based URL
            endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
            if endpoint:
                self._session_span.set_attribute(
                    "http.url", f"{endpoint}/cognitiveservices/v1"
                )
            else:
                self._session_span.set_attribute(
                    "http.url",
                    f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1",
                )
            # External dependency identification for App Map
            self._session_span.set_attribute("peer.service", "azure-cognitive-speech")
            self._session_span.set_attribute(
                "net.peer.name", f"{self.region}.tts.speech.microsoft.com"
            )

            # Set standard attributes if available
            self._session_span.set_attribute(
                SpanAttr.SERVICE_NAME, "azure-speech-synthesis"
            )
            self._session_span.set_attribute(SpanAttr.SERVICE_VERSION, "1.0.0")

            # Make this span current for the duration
            with trace.use_span(self._session_span):
                self._start_speaking_text_internal(text, voice, rate, style)
        else:
            self._start_speaking_text_internal(text, voice, rate, style)

    def _start_speaking_text_internal(
        self, text: str, voice: str = None, rate: str = "15%", style: str = None
    ) -> None:
        """Internal method to perform speaker synthesis with tracing events"""
        voice = voice or self.voice
        try:
            # Add event for speaker synthesis start
            if self._session_span:
                self._session_span.add_event(
                    "tts_speaker_synthesis_started",
                    {"text_length": len(text), "voice": voice},
                )

            speaker = self._create_speaker_synthesizer()
            if speaker is None:
                if self._session_span:
                    self._session_span.add_event(
                        "tts_speaker_unavailable", {"reason": "headless_environment"}
                    )

                logger.warning(
                    "Speaker not available in headless environment, skipping playback"
                )
                return

            if self._session_span:
                self._session_span.add_event("tts_speaker_synthesizer_created")

            logger.info(
                "[🔊] Starting streaming speech synthesis for text: %s",
                text[:50] + "...",
            )

            # Build SSML with consistent voice, rate, and style support
            sanitized_text = self._sanitize(text)
            inner_content = (
                f'<prosody rate="{rate}" pitch="default">{sanitized_text}</prosody>'
            )

            if style:
                inner_content = f'<mstts:express-as style="{style}">{inner_content}</mstts:express-as>'

            ssml = f"""
                <speak version="1.0" xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">
                    <voice name="{voice}">
                        {inner_content}
                    </voice>
                </speak>"""

            if self._session_span:
                self._session_span.add_event("tts_speaker_ssml_created")

            speaker.speak_ssml_async(ssml)

            if self._session_span:
                self._session_span.add_event("tts_speaker_synthesis_initiated")
                self._session_span.set_status(Status(StatusCode.OK))

        except Exception as exc:
            error_msg = f"TTS playback not available in this environment: {exc}"

            if self._session_span:
                self._session_span.add_event(
                    "tts_speaker_synthesis_error",
                    {"error_type": type(exc).__name__, "error_message": str(exc)},
                )
                self._session_span.set_status(Status(StatusCode.ERROR, error_msg))

            logger.warning(error_msg)

        finally:
            # Close session span
            if self._session_span:
                self._session_span.end()
                self._session_span = None

    def stop_speaking(self) -> None:
        """Stop current playback (if any)."""
        if self._speaker:
            try:
                logger.info("[🛑] Stopping speech synthesis...")
                self._speaker.stop_speaking_async()
            except Exception as e:
                logger.warning(f"Could not stop speech synthesis: {e}")

    def synthesize_speech(
        self, text: str, voice: str = None, style: str = None, rate: str = None
    ) -> bytes:
        """
        Synthesizes text to speech in memory (returning WAV bytes).
        Does NOT play audio on server speakers.

        Args:
            text: Text to synthesize
            voice: Voice name (defaults to self.voice)
            style: Voice style
            rate: Speech rate
        """
        voice = voice or self.voice
        # Start session-level span for synthesis if tracing is enabled
        if self.enable_tracing and self.tracer:
            self._session_span = self.tracer.start_span(
                "tts_synthesis_session", kind=SpanKind.CLIENT
            )

            # Set session attributes for correlation (matching speech_recognizer pattern)
            self._session_span.set_attribute("ai.operation.id", self.call_connection_id)
            self._session_span.set_attribute("tts.session.id", self.call_connection_id)
            self._session_span.set_attribute("tts.region", self.region)
            self._session_span.set_attribute("tts.voice", self.voice)
            self._session_span.set_attribute("tts.language", self.language)
            self._session_span.set_attribute("tts.text_length", len(text))

            # Set standard attributes if available
            self._session_span.set_attribute(
                SpanAttr.SERVICE_NAME, "azure-speech-synthesis"
            )
            self._session_span.set_attribute(SpanAttr.SERVICE_VERSION, "1.0.0")

            # Make this span current for the duration
            with trace.use_span(self._session_span):
                return self._synthesize_speech_internal(text, voice, style, rate)
        else:
            return self._synthesize_speech_internal(text, voice, style, rate)

    def _synthesize_speech_internal(
        self, text: str, voice: str = None, style: str = None, rate: str = None
    ) -> bytes:
        """Internal method to perform synthesis with tracing events"""
        voice = voice or self.voice
        try:
            # Add event for synthesis start
            if self._session_span:
                self._session_span.add_event(
                    "tts_synthesis_started",
                    {"text_length": len(text), "voice": voice},
                )

            # Create speech config for memory synthesis
            speech_config = self.cfg
            speech_config.speech_synthesis_language = self.language
            speech_config.speech_synthesis_voice_name = voice
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm
            )

            if self._session_span:
                self._session_span.add_event("tts_config_created")

            # Use None for audio_config to synthesize to memory
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, audio_config=None
            )

            if self._session_span:
                self._session_span.add_event("tts_synthesizer_created")

            # Build SSML if style or rate are specified, otherwise use plain text
            if style or rate:
                sanitized_text = self._sanitize(text)
                inner_content = sanitized_text

                if rate:
                    inner_content = f'<prosody rate="{rate}">{inner_content}</prosody>'

                if style:
                    inner_content = f'<mstts:express-as style="{style}">{inner_content}</mstts:express-as>'

                ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">
    <voice name="{voice}">
        {inner_content}
    </voice>
</speak>"""
                result = synthesizer.speak_ssml_async(ssml).get()
            else:
                result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                if self._session_span:
                    self._session_span.add_event("tts_synthesis_completed")

                audio_data_stream = speechsdk.AudioDataStream(result)
                wav_bytes = audio_data_stream.read_data()

                if self._session_span:
                    self._session_span.add_event(
                        "tts_audio_data_extracted", {"audio_size_bytes": len(wav_bytes)}
                    )
                    self._session_span.set_status(Status(StatusCode.OK))
                    self._session_span.end()
                    self._session_span = None

                return bytes(wav_bytes)
            else:
                error_msg = f"Speech synthesis failed: {result.reason}"
                logger.error(error_msg)

                if self._session_span:
                    self._session_span.add_event(
                        "tts_synthesis_failed", {"failure_reason": str(result.reason)}
                    )
                    self._session_span.set_status(Status(StatusCode.ERROR, error_msg))
                    self._session_span.end()
                    self._session_span = None
                return b""
        except Exception as e:
            error_msg = f"Error synthesizing speech: {e}"
            logger.error(error_msg)

            if self._session_span:
                self._session_span.add_event(
                    "tts_synthesis_exception",
                    {"error_type": type(e).__name__, "error_message": str(e)},
                )
                self._session_span.set_status(Status(StatusCode.ERROR, error_msg))
                self._session_span.end()
                self._session_span = None
            return b""

    def synthesize_to_base64_frames(
        self,
        text: str,
        sample_rate: int = 16000,
        voice: str = None,
        style: str = None,
        rate: str = None,
    ) -> list[str]:
        """
        Synthesize `text` via Azure TTS into raw 16-bit PCM mono at either 16 kHz or 24 kHz,
        then split into 20 ms frames (50 fps), returning each frame as a base64 string.

        Args:
            text: Text to synthesize
            sample_rate: 16000 or 24000
            voice: Voice name (defaults to self.voice)
            style: Voice style
            rate: Speech rate

        Returns:
            List of base64-encoded audio frames
        """
        voice = voice or self.voice
        # Start session-level span for frame synthesis if tracing is enabled
        if self.enable_tracing and self.tracer:
            self._session_span = self.tracer.start_span(
                "tts_frame_synthesis_session", kind=SpanKind.CLIENT
            )

            # Set session attributes for correlation (matching speech_recognizer pattern)
            self._session_span.set_attribute("ai.operation.id", self.call_connection_id)
            self._session_span.set_attribute("tts.session.id", self.call_connection_id)
            self._session_span.set_attribute("tts.region", self.region)
            self._session_span.set_attribute("tts.voice", self.voice)
            self._session_span.set_attribute("tts.language", self.language)
            self._session_span.set_attribute("tts.text_length", len(text))
            self._session_span.set_attribute("tts.sample_rate", sample_rate)

            # Set standard attributes if available
            self._session_span.set_attribute(
                SpanAttr.SERVICE_NAME, "azure-speech-synthesis"
            )
            self._session_span.set_attribute(SpanAttr.SERVICE_VERSION, "1.0.0")

            # Make this span current for the duration
            with trace.use_span(self._session_span):
                return self._synthesize_to_base64_frames_internal(
                    text, sample_rate, voice, style, rate
                )
        else:
            return self._synthesize_to_base64_frames_internal(
                text, sample_rate, voice, style, rate
            )

    def _synthesize_to_base64_frames_internal(
        self,
        text: str,
        sample_rate: int,
        voice: str = None,
        style: str = None,
        rate: str = None,
    ) -> list[str]:
        """Internal method to perform frame synthesis with tracing events"""
        voice = voice or self.voice
        try:
            # Add event for synthesis start
            if self._session_span:
                self._session_span.add_event(
                    "tts_frame_synthesis_started",
                    {
                        "text_length": len(text),
                        "voice": voice,
                        "sample_rate": sample_rate,
                    },
                )

            # Select SDK output format and packet size
            fmt_map = {
                16000: speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
                24000: speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm,
            }
            sdk_format = fmt_map.get(sample_rate)
            if not sdk_format:
                raise ValueError("sample_rate must be 16000 or 24000")

            # 1) Configure Speech SDK using class attributes with fresh auth
            logger.debug(f"Creating speech config for TTS synthesis")
            speech_config = self.cfg
            speech_config.speech_synthesis_language = self.language
            speech_config.speech_synthesis_voice_name = voice
            speech_config.set_speech_synthesis_output_format(sdk_format)

            if self._session_span:
                self._session_span.add_event("tts_frame_config_created")

            # 2) Synthesize to memory (audio_config=None) - NO AUDIO HARDWARE NEEDED
            synth = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, audio_config=None
            )

            if self._session_span:
                self._session_span.add_event("tts_frame_synthesizer_created")

            logger.debug(
                f"Synthesizing text with Azure TTS (voice: {voice}): {text[:100]}..."
            )

            # Build SSML if style or rate are specified, otherwise use plain text
            if style or rate:
                sanitized_text = self._sanitize(text)
                inner_content = sanitized_text

                if rate:
                    inner_content = f'<prosody rate="{rate}">{inner_content}</prosody>'

                if style:
                    inner_content = f'<mstts:express-as style="{style}">{inner_content}</mstts:express-as>'

                ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">
    <voice name="{voice}">
        {inner_content}
    </voice>
</speak>"""
                result = synth.speak_ssml_async(ssml).get()
            else:
                result = synth.speak_text_async(text).get()

            # 3) Check result
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                raw_bytes = result.audio_data

                if self._session_span:
                    self._session_span.add_event(
                        "tts_frame_synthesis_completed",
                        {"audio_data_size": len(raw_bytes), "synthesis_success": True},
                    )
            else:
                error_msg = f"TTS failed. Reason: {result.reason}"
                if result.reason == speechsdk.ResultReason.Canceled:
                    error_msg += f" Details: {result.cancellation_details.reason}"

                if self._session_span:
                    self._session_span.add_event(
                        "tts_frame_synthesis_failed",
                        {
                            "error_reason": str(result.reason),
                            "error_details": error_msg,
                        },
                    )

                logger.error(error_msg)
                raise Exception(error_msg)

            logger.debug(f"Got {len(raw_bytes)} bytes of raw audio data")

            # 4) Split into frames
            import base64

            frame_size_bytes = int(0.02 * sample_rate * 2)  # 20 ms of samples
            base64_frames = []

            for i in range(0, len(raw_bytes), frame_size_bytes):
                frame = raw_bytes[i : i + frame_size_bytes]
                if len(frame) == frame_size_bytes:
                    b64_frame = base64.b64encode(frame).decode("utf-8")
                    base64_frames.append(b64_frame)

            if self._session_span:
                self._session_span.add_event(
                    "tts_frame_processing_completed",
                    {
                        "total_frames": len(base64_frames),
                        "frame_size_bytes": frame_size_bytes,
                    },
                )

            logger.debug(f"Created {len(base64_frames)} base64 frames")
            return base64_frames

        except Exception as e:
            if self._session_span:
                self._session_span.add_event(
                    "tts_frame_synthesis_error",
                    {"error_type": type(e).__name__, "error_message": str(e)},
                )
                self._session_span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(f"Error in synthesize_to_base64_frames: {e}")
            raise

        finally:
            # Close session span
            if self._session_span:
                self._session_span.end()
                self._session_span = None

    def validate_configuration(self) -> bool:
        """
        Validate the Azure Speech configuration and return True if valid.
        """
        try:
            logger.info("Validating Azure Speech configuration...")
            logger.info(f"Region: {self.region}")
            logger.info(f"Language: {self.language}")
            logger.info(f"Voice: {self.voice}")
            logger.info(
                f"Using subscription key: {'Yes' if self.key else 'No (using DefaultAzureCredential)'}"
            )

            if not self.region:
                logger.error("Azure Speech region is not configured")
                return False

            if not self.key:
                # Test DefaultAzureCredential
                try:
                    credential = get_credential()
                    token = credential.get_token(
                        "https://cognitiveservices.azure.com/.default"
                    )
                    logger.info("DefaultAzureCredential authentication successful")
                except Exception as e:
                    logger.error(f"DefaultAzureCredential authentication failed: {e}")
                    return False

            # Test a simple synthesis to validate configuration
            try:
                test_result = self.synthesize_to_base64_frames(
                    "test", sample_rate=16000
                )
                if test_result:
                    logger.info("Configuration validation successful")
                    return True
                else:
                    logger.error(
                        "Configuration validation failed - no audio data returned"
                    )
                    return False
            except Exception as e:
                logger.error(f"Configuration validation failed: {e}")
                return False

        except Exception as e:
            logger.error(f"Error during configuration validation: {e}")
            return False

    ## Cleaned up methods
    def synthesize_to_pcm(
        self,
        text: str,
        voice: str = None,
        sample_rate: int = 16000,
        style: str = None,
        rate: str = None,
    ) -> bytes:
        """
        Synthesize text to PCM bytes with consistent voice parameter support.

        Args:
            text: Text to synthesize
            voice: Voice name (defaults to self.voice)
            sample_rate: Sample rate (16000 or 24000)
            style: Voice style
            rate: Speech rate
        """
        voice = voice or self.voice
        style = style or "chat"
        rate = rate or "+3%"

        speech_config = self.cfg
        speech_config.speech_synthesis_voice_name = voice
        speech_config.set_speech_synthesis_output_format(
            {
                16000: speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
                24000: speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm,
            }[sample_rate]
        )

        # Build SSML with consistent style support
        sanitized_text = self._sanitize(text)
        inner_content = sanitized_text

        # Apply prosody rate if specified
        if rate:
            inner_content = f'<prosody rate="{rate}">{inner_content}</prosody>'

        # Apply style if specified
        if style:
            inner_content = (
                f'<mstts:express-as style="{style}">{inner_content}</mstts:express-as>'
            )

        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">
    <voice name="{voice}">
        {inner_content}
    </voice>
</speak>"""

        # Use audio_config=None for memory synthesis - NO AUDIO HARDWARE NEEDED
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None
        )
        result = synthesizer.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            print("Cancellation reason:", cancellation.reason)
            print("Error details:", cancellation.error_details)

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"TTS failed: {result.reason}")

        return result.audio_data  # raw PCM bytes

    @staticmethod
    def split_pcm_to_base64_frames(
        pcm_bytes: bytes, sample_rate: int = 16000
    ) -> list[str]:
        import base64

        frame_size = int(0.02 * sample_rate * 2)  # 20ms * sample_rate * 2 bytes/sample
        return [
            base64.b64encode(pcm_bytes[i : i + frame_size]).decode("utf-8")
            for i in range(0, len(pcm_bytes), frame_size)
            if len(pcm_bytes[i : i + frame_size]) == frame_size
        ]
