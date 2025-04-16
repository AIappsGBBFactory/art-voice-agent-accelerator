import os
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
from utils.ml_logging import get_logger

# Load environment variables from a .env file if present
load_dotenv()

# Initialize logger
logger = get_logger()

class SpeechSynthesizer:
    def __init__(
        self,
        key: str = None,
        region: str = None,
        language: str = "en-US",
        voice: str = "en-US-JennyMultilingualNeural"
    ):
        # Retrieve Azure Speech credentials from parameters or environment variables
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.language = language
        self.voice = voice

        # Initialize the speech synthesizer for speaker playback
        self.speaker_synthesizer = self._create_speaker_synthesizer()

    def _create_speech_config(self):
        """
        Helper method to create and configure the SpeechConfig object.
        """
        speech_config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
        speech_config.speech_synthesis_language = self.language
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
        return speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    def start_speaking_text(self, text: str) -> None:
        """
        Asynchronously play synthesized speech through the server's default speaker.
        """
        try:
            logger.info(f"[🔊] Speaking text (server speaker): {text[:30]}...")
            self.speaker_synthesizer.start_speaking_text_async(text)
        except Exception as e:
            logger.error(f"[❗] Error starting speech synthesis: {e}")

    def stop_speaking(self) -> None:
        """
        Stop any ongoing speech synthesis playback on the server's speaker.
        """
        try:
            logger.info("[🛑] Stopping speech synthesis on server speaker...")
            self.speaker_synthesizer.stop_speaking_async()
        except Exception as e:
            logger.error(f"[❗] Error stopping speech synthesis: {e}")

    def synthesize_speech(self, text: str) -> bytes:
        """
        Synthesizes text to speech in memory (returning WAV bytes).
        Does NOT play audio on server speakers.
        """
        try:
            speech_config = speechsdk.SpeechConfig(
                subscription=self.key,
                region=self.region
            )
            speech_config.speech_synthesis_language = self.language
            speech_config.speech_synthesis_voice_name = self.voice
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm
            )

            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config,
                audio_config=None
            )

            result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                audio_data_stream = speechsdk.AudioDataStream(result)
                wav_bytes = audio_data_stream.read_data()  # ✅ USE read_data()
                return bytes(wav_bytes)  # ✅ Ensure it's converted from bytearray to bytes
            else:
                logger.error(f"Speech synthesis failed: {result.reason}")
                return b""
        except Exception as e:
            logger.error(f"Error synthesizing speech: {e}")
            return b""

