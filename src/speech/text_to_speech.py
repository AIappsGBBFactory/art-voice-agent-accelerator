import os
import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import SpeechConfig
from azure.cognitiveservices.speech.audio import AudioOutputConfig
from dotenv import load_dotenv
from utils.ml_logging import get_logger

# Set up logger
logger = get_logger()

# Load environment variables
load_dotenv()

class SpeechSynthesizer:
    def __init__(self, key: str = None, region: str = None):
        self.key = key if key is not None else os.getenv("AZURE_SPEECH_KEY")
        self.region = region if region is not None else os.getenv("AZURE_SPEECH_REGION")
        self.synthesizer = self.create_speech_synthesizer()

    def create_speech_synthesizer(self) -> speechsdk.SpeechSynthesizer:
        speech_config = SpeechConfig(subscription=self.key, region=self.region)

        # Important: optimize audio format to compressed PCM for faster delivery
        audio_config = AudioOutputConfig(use_default_speaker=True)

        # Select compressed format (optional, default still works fine)
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm
        )

        # Pick a low latency voice (Neural voice)
        speech_config.speech_synthesis_voice_name = "en-US-JennyNeural"

        return speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=audio_config
        )

    def start_speaking_text(self, text: str) -> None:
        """
        Start speaking text asynchronously without blocking.
        (Low latency mode: streaming starts immediately)
        """
        try:
            logger.info(f"[🔊] Starting streaming speech synthesis for text: {text[:30]}...")
            # Stream output immediately, don't wait for full text
            self.synthesizer.start_speaking_text_async(text)
        except Exception as e:
            logger.error(f"[❗] Error starting streaming speech: {e}")

    def stop_speaking(self) -> None:
        """
        Immediately stop any ongoing speech synthesis.
        """
        try:
            logger.info("[🛑] Stopping speech synthesis...")
            self.synthesizer.stop_speaking_async()
        except Exception as e:
            logger.error(f"[❗] Error stopping speech synthesis: {e}")
