import os

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

from utils.ml_logging import get_logger
from typing import Optional, Dict, List, Callable
import html 
from langdetect import detect, LangDetectException
import re

# Load environment variables from a .env file if present
load_dotenv()

# Initialize logger
logger = get_logger()

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
        return {"style": "chat", "rate": "-10%"}
    if lang_code.startswith("en"):
        return {"style": "chat"}
    return {}

def ssml_voice_wrap(voice: str,
                    default_lang: str,
                    sentences: List[str],
                    sanitizer: Callable[[str], str]) -> str:
    """Build one SSML doc with a single <voice> tag for efficiency."""
    body = []
    for seg in sentences:
        try:
            lang = detect(seg)
        except LangDetectException:
            lang = default_lang
        attrs = auto_style(lang)
        inner  = sanitizer(seg)

        # optional prosody
        if rate := attrs.get("rate"):
            inner = f'<prosody rate="{rate}">{inner}</prosody>'

        # optional style
        if style := attrs.get("style"):
            inner = f'<mstts:express-as style="{style}">{inner}</mstts:express-as>'

        # optional language switch
        if lang != default_lang:
            inner = f'<lang xml:lang="{lang}">{inner}</lang>'

        body.append(inner)

    joined = "".join(body)
    return (
        '<speak version="1.0" '
        'xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" '
        f'xml:lang="{default_lang}">'
        f'<voice name="{voice}">{joined}</voice>'
        '</speak>'
    )

class SpeechSynthesizer:
    def __init__(
        self,
        key: str = None,
        region: str = None,
        language: str = "en-US",
        voice: str = "en-US-JennyMultilingualNeural",
        format: speechsdk.SpeechSynthesisOutputFormat = speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,

    ):
        # Retrieve Azure Speech credentials from parameters or environment variables
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.default_lang  = language
        self.voice = voice
        self.format = format

        # Initialize the speech synthesizer for speaker playback
        self._speaker = self._create_synth()

    def _create_speech_config(self):
        """
        Helper method to create and configure the SpeechConfig object.
        """
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region
        )
        speech_config.speech_synthesis_voice_name = self.voice
        # Set the output format to 24kHz 16-bit mono PCM WAV
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )
        return speech_config

    def _create_speaker_synthesizer(self):
        """
        Create a SpeechSynthesizer instance for playing audio through the server's default speaker.
        """
        speech_config = self._create_speech_config()
        audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
        return speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=audio_config
        )
    
    @staticmethod
    def _sanitize(text: str) -> str:
        """
        Escape XML-significant characters (&, <, >, ", ') so the text
        can be inserted inside an SSML <prosody> block safely.
        """
        return html.escape(text, quote=True)

    def start_speaking_text(self, text: str) -> None:
        """
        Queue `text` for playback on the server speaker.

        • If ≤100 chars AND same language as default → quick plain mode
        • Otherwise → build multi-sentence SSML with per-sentence lang/style
        """
        try:
            text = text.strip()
            if not text:
                return

            if (len(text) <= 100 and
                detect(text).startswith(self.default_lang[:2])):
                self._speaker.start_speaking_text_async(text)
                logger.debug("Quick TTS (plain) – %d chars", len(text))
                return

            # SSML path
            sentences = split_sentences(text)
            ssml = ssml_voice_wrap(self.voice, self.default_lang,
                                   sentences, self._sanitize)
            self._speaker.start_speaking_ssml_async(ssml)
            logger.debug("SSML TTS – %d sentences", len(sentences))

        except Exception as exc:
            logger.error("TTS failed: %s", exc, exc_info=False)

    def stop_speaking(self) -> None:
        """Stop current playback (if any)."""
        try:
            self._speaker.stop_speaking_async()
        except Exception as exc:
            logger.error("stop_speaking error: %s", exc, exc_info=False)

    def _create_synth(self):
        cfg = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
        cfg.speech_synthesis_voice_name = self.voice
        cfg.speech_synthesis_language = self.default_lang
        cfg.set_speech_synthesis_output_format(self.format)

        audio_cfg = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
        return speechsdk.SpeechSynthesizer(cfg, audio_cfg)

    def synthesize_speech(self, text: str) -> bytes:
        """
        Synthesizes text to speech in memory (returning WAV bytes).
        Does NOT play audio on server speakers.
        """
        try:
            speech_config = speechsdk.SpeechConfig(
                subscription=self.key, region=self.region
            )
            speech_config.speech_synthesis_language = self.language
            speech_config.speech_synthesis_voice_name = self.voice
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm
            )

            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, audio_config=None
            )

            result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                audio_data_stream = speechsdk.AudioDataStream(result)
                wav_bytes = audio_data_stream.read_data()
                return bytes(
                    wav_bytes
                ) 
            else:
                logger.error(f"Speech synthesis failed: {result.reason}")
                return b""
        except Exception as e:
            logger.error(f"Error synthesizing speech: {e}")
            return b""

    def synthesize_to_base64_frames(
        self, text: str, sample_rate: int = 16000
    ) -> list[str]:
        """
        Synthesize `text` via Azure TTS into raw 16-bit PCM mono at either 16 kHz or 24 kHz,
        then split into 20 ms frames (50 fps), returning each frame as a base64 string.

        - sample_rate: 16000 or 24000
        - frame_size:  0.02s * sample_rate * 2 bytes/sample
                    =  640 bytes @16 kHz, 960 bytes @24 kHz
        """
        # Select SDK output format and packet size
        fmt_map = {
            16000: speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm,
            24000: speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm,
        }
        sdk_format = fmt_map.get(sample_rate)
        if not sdk_format:
            raise ValueError("sample_rate must be 16000 or 24000")

        # 1) Configure Speech SDK using class attributes
        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region
        )
        speech_config.speech_synthesis_language = self.language
        speech_config.speech_synthesis_voice_name = self.voice
        speech_config.set_speech_synthesis_output_format(sdk_format)

        # 2) Synthesize to memory (audio_config=None)
        synth = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None
        )

        # 3) Build an SSML envelope with reduced rate (80%)
        ##  If you would like to speed up the speech, you can increase the `prosody rate`% accordingly.

        ssml = f"""
        <speak version="1.0" xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="en-US">
          <voice name="{speech_config.speech_synthesis_voice_name}">
            <mstts:express-as style="chat">
              <prosody rate="15%" pitch="default">
                {text}
              </prosody>
            </mstts:express-as>
          </voice>
        </speak>
        """
        # 4) Synthesize
        result = synth.speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            error_details = result.cancellation_details
            logger.error(f"TTS failed: {result.reason}")
            if error_details:
                logger.error(f"Error details: {error_details.error_details}")
                logger.error(f"Error code: {error_details.error_code}")
            raise RuntimeError(f"TTS failed: {result.reason}")

        # 5) Get raw PCM bytes from the result
        pcm_bytes = result.audio_data  # Access audio data directly from the result

        return bytes(pcm_bytes)  # Ensure it's bytes type
