import os
import time
import json
from typing import List, Dict

from openai import AzureOpenAI
from src.speech.speech_recognizer import StreamingSpeechRecognizer
from src.speech.text_to_speech import SpeechSynthesizer
from app.backend.tools import available_tools
from app.backend.functions import (
    schedule_appointment,
    refill_prescription,
    lookup_medication_info,
    evaluate_prior_authorization,
    escalate_emergency,
    authenticate_user
)
from app.backend.prompt_manager import PromptManager
from utils.ml_logging import get_logger

# === Conversation Settings ===
STOP_WORDS = ["goodbye", "exit", "stop", "see you later", "bye"]
SILENCE_THRESHOLD = 10

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
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
)
az_speech_recognizer_client = StreamingSpeechRecognizer(vad_silence_timeout_ms=1400)
az_speech_synthesizer_client = SpeechSynthesizer()

SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

tts_sentence_end = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]

def check_for_stopwords(prompt: str) -> bool:
    return any(stop_word in prompt.lower() for stop_word in STOP_WORDS)

def handle_speech_recognition() -> str:
    global all_text_live, final_transcripts, last_final_text

    logger.info("Starting microphone recognition...")
    final_transcripts.clear()
    all_text_live = ""
    last_final_text = None

    def on_partial(text: str) -> None:
        global all_text_live
        all_text_live = text
        logger.debug(f"Partial recognized: {text}")
        az_speech_synthesizer_client.stop_speaking()

    def on_final(text: str) -> None:
        global all_text_live, final_transcripts, last_final_text
        if text and text != last_final_text:
            final_transcripts.append(text)
            last_final_text = text
            all_text_live = ""
            logger.info(f"Finalized text: {text}")

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
                last_speech_time = time.time()
                consecutive_silences = 0
                logger.info(f"User said: {prompt}")

                if check_for_stopwords(prompt):
                    logger.info("Detected stop word, exiting...")
                    az_speech_synthesizer_client.start_speaking_text(
                        "Thank you for using our service. Have a great day! Goodbye."
                    )
                    time.sleep(8)
                    break

                conversation_history.append({"role": "user", "content": prompt})

                collected_messages: List[str] = []
                function_call_name = None
                function_call_arguments = ""
                tool_call_id = None

                # FIRST GPT CALL
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

                            # Capture tool call information
                            if hasattr(delta, "tool_calls") and delta.tool_calls:
                                for tool_call in delta.tool_calls:
                                    if tool_call.function:
                                        function_call_name = tool_call.function.name
                                        function_call_arguments += tool_call.function.arguments or ""
                                        tool_call_id = tool_call.id

                            # If no tool call, collect text and optionally synthesize
                            elif hasattr(delta, "content") and delta.content:
                                chunk_message = delta.content
                                collected_messages.append(chunk_message)
                                if chunk_message.strip() in tts_sentence_end:
                                    text = ''.join(collected_messages).strip()
                                    if text:
                                        print(f"🗣 Synthesizing: {text}")
                                        az_speech_synthesizer_client.start_speaking_text(text)
                                        collected_messages.clear()

                # 🧠 If tool call was detected, execute it
                if function_call_name:
                    try:
                        parsed_args = json.loads(function_call_arguments.strip())
                        function_to_call = function_mapping.get(function_call_name)

                        if function_to_call:
                            result = await function_to_call(parsed_args)

                            print(f"✅ Function `{function_call_name}` executed. Result: {result}")

                            conversation_history.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": function_call_name,
                                "content": result,
                            })

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
                                            text = ''.join(collected_messages).strip()
                                            if text:
                                                print(f"🗣 Synthesizing (follow-up): {text}")
                                                az_speech_synthesizer_client.start_speaking_text(text)
                                                collected_messages.clear()

                            final_text = ''.join(collected_messages).strip()
                            if final_text:
                                conversation_history.append({"role": "assistant", "content": final_text})

                    except json.JSONDecodeError as e:
                        print(f"❌ Error parsing function arguments: {e}")

                else:
                    # Append the assistant message if no function call was made
                    final_text = ''.join(collected_messages).strip()
                    if final_text:
                        conversation_history.append({"role": "assistant", "content": final_text})
                        print(f"✅ Final assistant message: {final_text}")

            # elif (time.time() - last_speech_time) > SILENCE_THRESHOLD:
            #     consecutive_silences += 1
            #     if consecutive_silences >= 3:
            #         az_speech_synthesizer_client.start_speaking_text(
            #             "I'm sorry, I couldn't hear you. It seems we've been disconnected. Please feel free to call again anytime. Goodbye."
            #         )
            #         time.sleep(11)
            #         break
            #     else:
            #         az_speech_synthesizer_client.start_speaking_text(
            #             "I'm sorry, I couldn't hear you. Are you still there?"
            #         )
            #         time.sleep(4)
            #         last_speech_time = time.time()

    except Exception as e:
        logger.exception("An error occurred in main().")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
