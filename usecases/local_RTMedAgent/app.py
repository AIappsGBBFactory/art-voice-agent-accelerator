import json
import os
import time
from typing import Dict, List

from app.backend.functions import (
    authenticate_user,
    escalate_emergency,
    evaluate_prior_authorization,
    lookup_medication_info,
    refill_prescription,
    schedule_appointment,
)
from app.backend.prompt_manager import PromptManager
from app.backend.tools import available_tools
from openai import AzureOpenAI

from src.speech.speech_recognizer import StreamingSpeechRecognizer
from src.speech.text_to_speech import SpeechSynthesizer
from utils.ml_logging import get_logger

# === Conversation Settings ===
STOP_WORDS = ["goodbye", "exit", "stop", "see you later", "bye"]
SILENCE_THRESHOLD = 90

# === Runtime Buffers ===
all_text_live = ""
final_transcripts: List[str] = []
last_final_text: str = None

# === Prompt Setup ===
prompt_manager = PromptManager()
system_prompt = prompt_manager.get_prompt("voice_agent_system.jinja")

# === Function Mapping ===
function_mapping = {
    "schedule_appointment": schedule_appointment,
    "refill_prescription": refill_prescription,
    "lookup_medication_info": lookup_medication_info,
    "evaluate_prior_authorization": evaluate_prior_authorization,
    "escalate_emergency": escalate_emergency,
    "authenticate_user": authenticate_user,
}

# === Clients Setup ===
logger = get_logger()
az_openai_client = AzureOpenAI(
    api_version="2025-02-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
)
az_speech_recognizer_client = StreamingSpeechRecognizer(vad_silence_timeout_ms=6000)
az_speech_synthesizer_client = SpeechSynthesizer()

tts_sentence_end = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]


def check_for_stopwords(prompt: str) -> bool:
    return any(stop_word in prompt.lower() for stop_word in STOP_WORDS)


def handle_speech_recognition() -> str:
    global all_text_live, final_transcripts, last_final_text

    logger.info("Starting microphone recognition...")
    final_transcripts.clear()
    all_text_live = ""
    last_final_text = None

    def on_partial(text: str):
        global all_text_live
        logger.info(f"Partial: {text}")
        all_text_live = text

    def on_final(text: str):
        global all_text_live, last_final_text
        if text == last_final_text:
            return
        last_final_text = text
        logger.info(f"Final: {text}")
        final_transcripts.append(text)
        all_text_live = ""  # Clear the live buffer

    az_speech_recognizer_client.set_partial_result_callback(on_partial)
    az_speech_recognizer_client.set_final_result_callback(on_final)

    az_speech_recognizer_client.start()
    logger.info("🎤 Listening... (speak now)")

    start_time = time.time()
    while not final_transcripts and (time.time() - start_time < SILENCE_THRESHOLD):
        time.sleep(0.05)

    az_speech_recognizer_client.stop()
    logger.info("🛑 Recognition stopped.")

    return " ".join(final_transcripts) + " " + all_text_live


async def main() -> None:
    try:
        time.sleep(1)
        az_speech_synthesizer_client.start_speaking_text(
            "Hello from XMYX Healthcare Company! We are here to assist you. How can I help you today?"
        )
        time.sleep(10)

        conversation_history: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

        last_speech_time = time.time()
        consecutive_silences = 0

        while True:
            prompt = handle_speech_recognition()
            if prompt.strip():
                logger.info(f"User said: {prompt}")

                if check_for_stopwords(prompt):
                    logger.info("Detected stop word, exiting...")
                    az_speech_synthesizer_client.start_speaking_text(
                        "Thank you for using our service. Have a great day! Goodbye."
                    )
                    time.sleep(8)
                    break

                conversation_history.append({"role": "user", "content": prompt})

                tool_name = None
                function_call_arguments = ""
                tool_id = None
                last_tts_request = None
                collected_messages: List[str] = []

                # 🔁 FIRST STREAMING RESPONSE (may include tool call)
                response = az_openai_client.chat.completions.create(
                    stream=True,
                    messages=conversation_history,
                    tools=available_tools,
                    tool_choice="auto",
                    max_tokens=4096,
                    temperature=0.5,
                    top_p=1.0,
                    model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
                )

                for chunk in response:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta.tool_calls:
                            if delta.tool_calls[0].function.name:
                                tool_name = (
                                    chunk.choices[0].delta.tool_calls[0].function.name
                                )
                                tool_id = chunk.choices[0].delta.tool_calls[0].id
                                conversation_history.append(delta)

                            if chunk.choices[0].delta.tool_calls[0].function.arguments:
                                function_call_arguments += delta.tool_calls[
                                    0
                                ].function.arguments

                        elif delta.content:
                            chunk_text = chunk.choices[0].delta.content
                            if chunk_text:
                                collected_messages.append(chunk_text)
                                if chunk_text in tts_sentence_end:
                                    text = "".join(collected_messages).strip()
                                    last_tts_request = az_speech_synthesizer_client.start_speaking_text(
                                        text
                                    )
                                    collected_messages.clear()

                # 🧠 If tool call was detected, execute it
                if tool_name:
                    logger.info(f"tool_name:{tool_name}")
                    logger.info(f"tool_id:{tool_id}")
                    logger.info(f"function_call_arguments:{function_call_arguments}")
                    try:
                        parsed_args = json.loads(function_call_arguments.strip())
                        function_to_call = function_mapping.get(tool_name)

                        if function_to_call:
                            result = await function_to_call(parsed_args)

                            logger.info(
                                f"✅ Function {tool_name} executed. Result: {result}"
                            )

                            conversation_history.append(
                                {
                                    "tool_call_id": tool_id,
                                    "role": "tool",
                                    "name": tool_name,
                                    "content": result,
                                }
                            )

                            # 🧠 SECOND STREAMING CALL AFTER TOOL EXECUTION
                            second_response = az_openai_client.chat.completions.create(
                                stream=True,
                                messages=conversation_history,
                                temperature=0.5,
                                top_p=1.0,
                                max_tokens=4096,
                                model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
                            )

                            collected_messages = []

                            for chunk in second_response:
                                if chunk.choices:
                                    delta = chunk.choices[0].delta
                                    if hasattr(delta, "content") and delta.content:
                                        chunk_message = delta.content
                                        collected_messages.append(chunk_message)
                                        if chunk_message.strip() in tts_sentence_end:
                                            text = "".join(collected_messages).strip()
                                            if text:
                                                az_speech_synthesizer_client.start_speaking_text(
                                                    text
                                                )
                                                collected_messages.clear()

                            final_text = "".join(collected_messages).strip()
                            if final_text:
                                conversation_history.append(
                                    {"role": "assistant", "content": final_text}
                                )

                    except json.JSONDecodeError as e:
                        print(f"❌ Error parsing function arguments: {e}")

                else:
                    # Append the assistant message if no function call was made
                    final_text = "".join(collected_messages).strip()
                    if final_text:
                        conversation_history.append(
                            {"role": "assistant", "content": final_text}
                        )
                        print(f"✅ Final assistant message: {final_text}")
    except Exception:
        logger.exception("An error occurred in main().")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
