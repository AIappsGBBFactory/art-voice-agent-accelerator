import os
import time
from typing import List, Dict

from openai import AzureOpenAI
from src.speech.speech_recognizer import StreamingSpeechRecognizer
from src.speech.text_to_speech import SpeechSynthesizer
from utils.ml_logging import get_logger

# Set up logger
logger = get_logger()

# Initialize Azure OpenAI client
az_openai_client = AzureOpenAI(
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
)

# Streaming Speech Recognizer and Speech Synthesizer
VAD_SILENCE_TIMEOUT_MS = 1200  # 1.2 ms of silence for VAD
az_speech_recognizer_client = StreamingSpeechRecognizer(vad_silence_timeout_ms=VAD_SILENCE_TIMEOUT_MS)
az_speach_synthesizer_client = SpeechSynthesizer()

# Environment variables (if needed for references)
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

# Stop words, threshold, and text buffers
STOP_WORDS = ["goodbye", "exit", "stop", "see you later", "bye"]
SILENCE_THRESHOLD = 10  # seconds of inactivity
all_text_live: str = ""
final_transcripts: List[str] = []
last_final_text: str = None  # To avoid duplicate final transcripts


def check_for_stopwords(prompt: str) -> bool:
    """
    Checks whether the user's recognized speech (prompt)
    contains any predefined stop words that should end the conversation.

    Args:
        prompt (str): The recognized speech text to analyze.

    Returns:
        bool: True if the prompt contains a stop word, otherwise False.
    """
    return any(stop_word in prompt.lower() for stop_word in STOP_WORDS)


def handle_speech_recognition() -> str:
    """
    Handles streaming speech recognition from the microphone using the
    StreamingSpeechRecognizer. It:
      - Collects partial transcripts (live updates) in `all_text_live`.
      - Collects final transcripts in `final_transcripts`.
      - Stops any ongoing TTS immediately when new speech is detected (on_partial).
      - Waits up to SILENCE_THRESHOLD seconds for a final transcript before timing out.

    Returns:
        str: A concatenation of the final transcripts and any remaining partial text.
    """
    global all_text_live, final_transcripts, last_final_text

    logger.info("Starting microphone recognition...")
    final_transcripts.clear()
    all_text_live = ""
    last_final_text = None

    def on_partial(text: str) -> None:
        """
        Callback for partial recognition events. Updates partial text buffer
        and stops TTS so the user can speak immediately.
        """
        global all_text_live
        all_text_live = text
        logger.debug(f"Partial recognized: {text}")
        # Interrupt ongoing speech synthesis
        az_speach_synthesizer_client.stop_speaking()

    def on_final(text: str) -> None:
        """
        Callback for final recognition events. Adds the final text to the
        final transcripts buffer and resets the partial buffer.
        """
        global all_text_live, final_transcripts, last_final_text
        if text and text != last_final_text:
            final_transcripts.append(text)
            last_final_text = text
            all_text_live = ""
            logger.info(f"Finalized text: {text}")

    # Attach the callbacks to the recognizer
    az_speech_recognizer_client.set_partial_result_callback(on_partial)
    az_speech_recognizer_client.set_final_result_callback(on_final)

    # Begin continuous recognition
    az_speech_recognizer_client.start()
    logger.info("🎤 Listening... (speak now)")

    start_time = time.time()

    # Wait for a final transcript or time out
    while not final_transcripts and (time.time() - start_time < SILENCE_THRESHOLD):
        time.sleep(0.1)

    # Stop recognition
    az_speech_recognizer_client.stop()
    logger.info("🛑 Recognition stopped.")

    # Return the combined final transcripts plus partial text
    return " ".join(final_transcripts) + " " + all_text_live


def main() -> None:
    """
    Main function that orchestrates:
      1. Speech recognition from the microphone (handle_speech_recognition).
      2. Checks for stop words to decide if the conversation should end.
      3. Sends recognized text to Azure OpenAI for a streaming chat response.
      4. Streams the AI response back to the user via TTS, speaking chunks as they're received.
      5. Ends if a stop word is recognized or if the user is silent for 40 seconds
         three times in a row. If silent once or twice, politely asks "Are you still there?"
         and continues.

    Note:
      - This is a synchronous approach, but extended with extra logic
        to handle repeated silence in a row.
    """
    try:
        intro_text = "   "
        az_speach_synthesizer_client.start_speaking_text(intro_text)
        # Speak an introduction phrase first
        intro_text = (
            "   Hello from XMYX Healthcare Company! "
            "We are here to assist you with appointments, advice, and more. "
            "How can I help you today?"
        )
        az_speach_synthesizer_client.start_speaking_text(intro_text)
        # Sleep briefly so the introduction is clearly heard before recognition starts
        time.sleep(10)
        # Conversation context
        conversation_history: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

        last_speech_time = time.time()
        # Tracks how many times we've hit the 40s silence threshold in a row
        consecutive_silences = 0

        while True:
            # Perform one cycle of speech recognition
            prompt = handle_speech_recognition()

            # If we got any recognized text, process it
            if prompt.strip():
                last_speech_time = time.time()
                # User spoke, reset consecutive silence count
                consecutive_silences = 0
                logger.info(f"User said: {prompt}")

                # If it includes a stop word, say goodbye and end
                if check_for_stopwords(prompt):
                    logger.info("Detected stop word, exiting...")
                    az_speach_synthesizer_client.start_speaking_text(
                        "Thank you for using our service. Have a great day! Goodbye."
                    )
                    time.sleep(8)  # Give time for TTS to finish
                    break

                # Add user text to conversation and call Azure OpenAI
                conversation_history.append({"role": "user", "content": prompt})

                # Stream GPT response
                response = az_openai_client.chat.completions.create(
                    stream=True,
                    messages=conversation_history,
                    max_tokens=4096,
                    temperature=1.0,
                    top_p=1.0,
                    model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
                )

                # We'll accumulate chunks and speak them as they end in punctuation
                tts_sentence_end = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]
                collected_messages: List[str] = []
                full_response_text = ""

                # Process streaming chunks
                for chunk in response:
                    if chunk.choices:
                        chunk_text = chunk.choices[0].delta.content or ""
                        if chunk_text:
                            # Print partial chunk to console
                            print(chunk_text, end="", flush=True)

                            # Accumulate chunk
                            collected_messages.append(chunk_text)
                            full_response_text += chunk_text

                            # If chunk ends with punctuation, speak it
                            if chunk_text[-1:] in tts_sentence_end:
                                text_to_speak = "".join(collected_messages).strip()
                                if text_to_speak:
                                    az_speach_synthesizer_client.start_speaking_text(text_to_speak)
                                collected_messages.clear()

                # Print a final newline for neatness
                print()

                # Once all chunks are done, add to conversation
                if full_response_text:
                    conversation_history.append(
                        {"role": "assistant", "content": full_response_text}
                    )
                    logger.info(f"Assistant response: {full_response_text}")
            # If no new recognized text, check if we've been silent for too long
            elif (time.time() - last_speech_time) > SILENCE_THRESHOLD:
                consecutive_silences += 1
                logger.info(
                    f"No speech detected for {SILENCE_THRESHOLD} seconds. "
                    f"Consecutive silences: {consecutive_silences}"
                )

                if consecutive_silences >= 3:
                    # On the 3rd time of being silent for 40s, exit
                    logger.info("User was silent 3 times in a row. Exiting now...")
                    az_speach_synthesizer_client.start_speaking_text(
                        "I'm sorry, I couldn't hear you. It seems we've been disconnected. Please feel free to call again anytime. Goodbye."
                    )
                    time.sleep(11)  # Give time for TTS to finish
                    break
                else:
                    # If it's the 1st or 2nd time, politely ask if they're still there
                    az_speach_synthesizer_client.start_speaking_text("I'm sorry, I couldn't hear you. Are you still there?")
                    time.sleep(4)  # A short pause to let TTS speak before continuing
                    # We'll loop again to see if user responds
                    last_speech_time = time.time()
            else:
                # Possibly user didn't speak in time, let's try again
                logger.warning("No prompt recognized, listening again...")

    except Exception as e:
        logger.error(f"An error occurred in main(): {e}")


if __name__ == "__main__":
    main()
