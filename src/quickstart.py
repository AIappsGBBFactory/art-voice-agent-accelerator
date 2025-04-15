#!/usr/bin/env python3

import os
import asyncio
import base64
import logging

from dotenv import load_dotenv
from openai import AsyncAzureOpenAI

# Local imports (adjust to match your directory structure)
from src.speech.speech_recognizer import StreamingSpeechRecognizer
from src.openai_test.audio_util import CHANNELS, SAMPLE_RATE, AudioPlayerAsync

load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Globals
client = None
connection = None
last_final_text = None
assistant_speaking = False  # Tracks if the assistant is currently speaking/outputting TTS

# Async Queue for sending recognized text to GPT-4
send_queue = asyncio.Queue()

# Audio player for assistant TTS
audio_player = AudioPlayerAsync()

async def main() -> None:
    """
    Use StreamingSpeechRecognizer to capture final speech,
    then send it to Azure OpenAI Realtime, with barge-in support.
    """

    global client, connection

    # Initialize Azure OpenAI client
    client = AsyncAzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-10-01-preview",  # Adjust if your Azure service uses a different version
    )

    # Connect to GPT-4 (or your chosen Azure model) in Realtime mode
    async with client.beta.realtime.connect(model=os.getenv("AZURE_OPENAI_DEPLOYMENT")) as conn:
        connection = conn

        # Configure session parameters
        await conn.session.update(session={
            # 1) "modalities": ["text", "audio"] means the model will handle both text I/O and audio I/O.
            #    This is why we can stream audio to the model AND receive audio TTS from it.
            "modalities": ["text", "audio"],

            # 2) "instructions" is the system prompt that sets the overall style and context of the assistant.
            "instructions": (
                "You are a pharmacy assistant named PharmaHero. "
                "Greet the user warmly. Assist with appointments, prescriptions, and medication advice. "
                "Listen carefully, avoid interrupting your own speech. Be concise, empathetic, and helpful."
            ),

            # 3) "temperature" controls how creative or deterministic the responses are.
            #    - Higher values (~1.0) => more creative/varied answers, slightly more latency in generation.
            #    - Lower values (~0.2-0.3) => more deterministic, more consistent style, can be marginally faster.
            "temperature": 1,

            # 4) "input_audio_transcription" tells the service to transcribe incoming audio using the "whisper-1" model.
            #    - If you never send audio to the server, it won't matter.
            #    - If your use case is purely text-based, you could omit this or set modalities to just ["text"].
            "input_audio_transcription": {"model": "whisper-1"},

            # 5) "turn_detection" configures how the server decides when the user has finished speaking.
            "turn_detection": {
                "type": "server_vad",          # VAD (Voice Activity Detection) is handled by the server.
                "threshold": 1,                # Sensitivity of speech detection (0.0 -> highly sensitive, 1.0 -> least sensitive).
                "prefix_padding_ms": 300,       # How much preceding audio (in ms) to keep to avoid clipping the start of speech.
                "silence_duration_ms": 1200,    # After 1200 ms (1.2s) of silence, assume the user has finished speaking.
                "create_response": True,        # Once the user is done speaking, automatically generate a response.
            },
        })
        logger.info("Connected to Azure OpenAI Realtime with updated session parameters.")

        # Setup local Azure Speech recognizer (for capturing user speech + turning it to text)
        recognizer = StreamingSpeechRecognizer(
            vad_silence_timeout_ms=1000  # Local end-of-speech timeout. Not the same as the LLM’s server_vad.
        )
        recognizer.set_partial_result_callback(on_partial)
        recognizer.set_final_result_callback(on_final)
        recognizer.start()  # Start continuous recognition

        # Create tasks to send recognized text to GPT-4 and to receive the assistant's responses
        consumer = asyncio.create_task(consume_queue())
        listener = asyncio.create_task(receive_assistant())

        await asyncio.gather(consumer, listener)

def on_partial(text: str):
    """
    Callback for partial speech recognition events from Azure Speech SDK.
    If the assistant is speaking, we interrupt (barge-in) by canceling the TTS playback
    and instructing the LLM to stop sending more audio.
    """
    global assistant_speaking
    print(f"🟦 Partial: {text}")

    # Barge-in logic:
    if assistant_speaking and text.strip():
        asyncio.create_task(interrupt_assistant())

def on_final(text: str):
    """
    Callback for final speech recognized from Azure Speech SDK.
    We enqueue that recognized text to be sent to the GPT-4 conversation.
    """
    global last_final_text

    if text == last_final_text:
        return

    last_final_text = text
    print(f"🟩 Final: {text}")
    send_queue.put_nowait(text)

async def consume_queue():
    """
    Task that takes recognized user text from the queue and sends it to GPT-4 in realtime.
    """
    while True:
        text = await send_queue.get()
        await send_to_openai(text)
        send_queue.task_done()

async def send_to_openai(text: str):
    """
    Sends a user message (recognized text) to GPT-4 Realtime.
    """
    if connection:
        # Create a conversation item with the user's text
        await connection.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            }
        )
        # Trigger the model to generate a response
        await connection.response.create()

async def receive_assistant():
    """
    Listens to the GPT-4 Realtime connection for:
      - partial text,
      - audio TTS chunks,
      - final "response.done" signals, etc.
    """
    global assistant_speaking

    try:
        async for event in connection:
            if event.type == "response.text.delta":
                # Partial text from the assistant
                assistant_speaking = True
                print(event.delta, end="", flush=True)

            elif event.type == "response.audio.delta":
                # Assistant TTS audio stream
                assistant_speaking = True
                audio_bytes = base64.b64decode(event.delta)
                audio_player.add_data(audio_bytes)

            elif event.type == "response.audio_transcript.delta":
                # Transcribed text of the TTS
                print(f"\n📝 Assistant: {event.delta}")

            elif event.type == "response.text.done":
                # The assistant's text is done
                print()

            elif event.type == "response.done":
                # Assistant finished speaking entirely
                assistant_speaking = False
                print("\n✅ Assistant finished.")

    except Exception as e:
        logger.error(f"Error receiving assistant response: {e}")

async def interrupt_assistant():
    """
    Cancels ongoing TTS from the assistant and stops local audio playback (barge-in).
    """
    global assistant_speaking

    logger.info("User speech detected during assistant speech—cancelling TTS.")
    try:
        if connection:
            # Instruct the LLM to stop sending more TTS/data
            await connection.send({"type": "response.cancel"})
    except Exception as e:
        logger.error(f"Error sending response.cancel: {e}")

    # Force stop any local audio still queued
    audio_player.stop()

    # Update our flag
    assistant_speaking = False

if __name__ == "__main__":
    asyncio.run(main())
