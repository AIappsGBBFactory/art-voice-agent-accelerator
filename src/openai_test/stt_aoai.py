import os
import asyncio
import base64
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
import sounddevice as sd
import numpy as np
from textual.app import App, ComposeResult
from textual.widgets import Static

# Load environment variables from .env
load_dotenv()
# Azure Speech config
SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
# Azure OpenAI (GPT-4o) config
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")  # e.g. "my-resource.openai.azure.com"
OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # e.g. deployment name for gpt-4o-realtime-preview


# Set up Azure Speech SDK for microphone input with continuous recognition
speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
speech_config.set_profanity(speechsdk.ProfanityOption.Raw)  # optional: do not mask profanity
audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

# We'll connect event handlers for real-time transcription
def on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs):
    """Handler for partial (mid-utterance) speech recognition results."""
    text = evt.result.text
    if text:
        # Update partial transcription in the UI (scheduled on main thread)
        app.loop.call_soon_threadsafe(app.handle_partial_user, text)

def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs):
    """Handler for final speech recognition results (end of utterance)."""
    result = evt.result
    if result.text:
        # Stop further recognition until we handle this utterance
        speech_recognizer.stop_continuous_recognition()
        # Send the final recognized text to be processed (on the main async loop)
        app.loop.call_soon_threadsafe(asyncio.create_task, app.handle_user_final(result.text))

speech_recognizer.recognizing.connect(on_recognizing)
speech_recognizer.recognized.connect(on_recognized)

import json
import websockets

class VoiceAssistantApp(App):
    CSS_PATH = None  # (We could add some basic styling here if needed)

    def __init__(self):
        super().__init__()
        # Conversation state
        self.conversation_history = []   # list of (speaker, text) for final messages
        self.partial_user = ""           # current user speech (partial)
        self.partial_assistant = ""      # current assistant reply (streaming)
        # Placeholder for assistant voice audio stream (we'll initialize when needed)
        self.audio_stream = None
        # Event loop reference for scheduling from threads
        self.loop = asyncio.get_event_loop()
        # Open log file for conversation
        self.log_file = open("conversation.log", "w", encoding="utf-8")
        # WebSocket connection will be established in on_mount
        self.ws = None
        # A future to signal when the assistant's response is done (for turn management)
        self.assistant_done_future = None

    async def on_mount(self) -> None:
        """Initialize the WebSocket connection and start speech recognition."""
        # 1. Connect to Azure OpenAI GPT-4o Realtime WebSocket
        api_version = "2024-10-01-preview"
        url = f"wss://{OPENAI_ENDPOINT}/openai/realtime?api-version={api_version}&deployment={OPENAI_DEPLOYMENT}"
        # Append API key as query or header. We'll use header for security.
        self.ws = await websockets.connect(
            url
        )
        print("Connected to Azure OpenAI Realtime API...")

        # 2. Update session configuration (modalities, voice, system prompt, etc.)
        session_config = {
            "modalities": ["text", "audio"],
            "voice": "Shimmer",
            "input_audio_format": "pcm16",      # our audio format; using 16-bit PCM
            "instructions": "You are a helpful AI assistant that answers verbally.",
            "temperature": 0.7
        }
        session_update_event = {
            "type": "session.update",
            "session": session_config
        }
        await self.ws.send(json.dumps(session_update_event))
        # We can await a confirmation event (session.updated), but for brevity we proceed.

        # 3. Start listening for speech input
        speech_recognizer.start_continuous_recognition()
        # 4. Launch background task to listen for model responses
        asyncio.create_task(self.listen_to_assistant())
        # (The UI is now ready to go; waiting for user speech to trigger conversation.)

    async def on_close(self) -> None:
        """Cleanup on app exit."""
        # Stop recognition and close websocket on exit
        speech_recognizer.stop_continuous_recognition()
        if self.ws:
            await self.ws.close()
        if self.log_file:
            self.log_file.close()

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        # A single Static widget to display the conversation log
        self.history_display = Static("")
        yield self.history_display

    def refresh_display(self):
        """Render the conversation (including any partial text) to the UI."""
        output_lines = []
        for speaker, text in self.conversation_history:
            if speaker == "User":
                output_lines.append(f"[bold blue]User:[/bold blue] {text}")
            else:
                output_lines.append(f"[bold green]Assistant:[/bold green] {text}")
        # Show partial lines if present
        if self.partial_user:
            output_lines.append(f"[bold blue]User:[/bold blue] {self.partial_user}…")
        if self.partial_assistant:
            output_lines.append(f"[bold green]Assistant:[/bold green] {self.partial_assistant}")
        # Join lines and update the Static widget
        conversation_text = "\n".join(output_lines)
        self.history_display.update(conversation_text)

    def handle_partial_user(self, text: str):
        """Update partial user transcript (called from speech thread)."""
        self.partial_user = text  # update live transcription
        self.refresh_display()

    async def handle_user_final(self, text: str):
        """Handle a final user utterance: update log, send to GPT-4o, and await response."""
        # Clear partial user text and add final user message to history
        self.partial_user = ""
        self.conversation_history.append(("User", text))
        self.refresh_display()
        # Log the user message with role
        self.log_file.write(f"User: {text}\n"); self.log_file.flush()

        # 1. Send user's message to GPT-4o (as a new conversation item)
        user_message_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [ {"type": "input_text", "text": text} ]
            }
        }
        await self.ws.send(json.dumps(user_message_event))
        # 2. Trigger the model to generate a response
        response_event = { "type": "response.create", "response": {} }
        await self.ws.send(json.dumps(response_event))

        # Prepare for receiving assistant answer
        self.partial_assistant = ""  # clear any leftover partial assistant text
        # Create a Future to signal when assistant response is fully done
        self.assistant_done_future = self.loop.create_future()

        # Wait until the assistant finishes responding (audio + text done)
        await self.assistant_done_future

        # At this point, the assistant's full reply is in conversation_history (and spoken)
        # Re-enable speech recognition for the next user turn
        speech_recognizer.start_continuous_recognition()

    async def listen_to_assistant(self):
        """Background task: receive events from GPT-4o and handle them."""
        try:
            # We'll use an output audio stream for continuous playback of assistant voice
            # Assuming 24 kHz, mono, 16-bit PCM as the output audio format&#8203;:contentReference[oaicite:8]{index=8}
            sample_rate = 24000
            self.audio_stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype='int16')
            self.audio_stream.start()
            async for msg in self.ws:
                # The API may send both text and binary frames; handle accordingly
                event = None
                if isinstance(msg, bytes):
                    # If audio chunks come as binary frames, we play them directly
                    audio_data = np.frombuffer(msg, dtype=np.int16)
                    self.audio_stream.write(audio_data.tobytes())
                    # (In this case, a separate JSON event might describe the chunk, but we handle direct binary)
                    continue
                else:
                    # Text frame: parse JSON event
                    event = json.loads(msg)

                event_type = event.get("type")
                if event_type == "response.audio_transcript.delta":
                    # Received a chunk of the assistant's transcribed text (as the audio is being generated)
                    delta_text = event.get("delta", "")
                    if delta_text:
                        # Append delta to the assistant's partial text and update display
                        self.partial_assistant += delta_text
                        # If this is the first chunk of a new assistant turn, add an entry to history
                        if not self.conversation_history or self.conversation_history[-1][0] != "Assistant":
                            self.conversation_history.append(("Assistant", self.partial_assistant))
                        else:
                            # Update the last assistant entry
                            self.conversation_history[-1] = ("Assistant", self.partial_assistant)
                        self.refresh_display()
                elif event_type == "response.audio.delta":
                    # Model-generated audio chunk (base64-encoded PCM data)&#8203;:contentReference[oaicite:9]{index=9} 
                    audio_b64 = event.get("audio")
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        # Play the audio chunk
                        self.audio_stream.write(audio_bytes)
                elif event_type == "response.audio_transcript.done":
                    # The assistant's text response streaming is complete&#8203;:contentReference[oaicite:10]{index=10} 
                    # (We might use this to mark end of text, but we'll wait for audio.done to finish audio)
                    pass
                elif event_type == "response.audio.done":
                    # The assistant's audio response is complete (all audio chunks sent)&#8203;:contentReference[oaicite:11]{index=11}
                    # Finalize the assistant's response turn
                    full_text = self.conversation_history[-1][1] if self.conversation_history else ""
                    # Log the assistant's answer
                    self.log_file.write(f"Assistant: {full_text}\n"); self.log_file.flush()
                    # Signal that the assistant is done responding
                    if self.assistant_done_future and not self.assistant_done_future.done():
                        self.assistant_done_future.set_result(True)
                elif event_type == "error":
                    # Handle errors (print or log as needed)
                    err = event.get("error", {})
                    print(f"Error from GPT-4o: {err}")
        except Exception as e:
            print("Exception in assistant listener:", e)
        finally:
            if self.audio_stream:
                self.audio_stream.stop()
                self.audio_stream.close()

if __name__ == "__main__":
    app = VoiceAssistantApp()
    app.run()
