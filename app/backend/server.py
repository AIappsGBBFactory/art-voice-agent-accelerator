import os
import time
import json
from typing import List, Dict
import asyncio
import contextlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

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

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # or ["*"] for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Mount static files from the frontend folder (adjust if needed)
app.mount("/static", StaticFiles(directory="app/frontend"), name="static")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        print(f"Received message: {data}")
        await websocket.send_text(f"Message received: {data}")
        
# Serve the HTML page at the root route.
@app.get("/", response_class=HTMLResponse)
async def get_index():
    # Get the directory of the current file (app/backend)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Construct the path to the frontend directory (assumes it is a sibling of backend)
    frontend_dir = os.path.join(current_dir, "..", "frontend")
    index_path = os.path.join(frontend_dir, "index.html")
    with open(index_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

# === Conversation Settings ===
STOP_WORDS = ["goodbye", "exit", "stop", "see you later", "bye"]
SILENCE_THRESHOLD = 10  # seconds

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
az_speech_recognizer_client = StreamingSpeechRecognizer(vad_silence_timeout_ms=3000)
az_speech_synthesizer_client = SpeechSynthesizer()

SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

tts_sentence_end = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]


def check_for_stopwords(prompt: str) -> bool:
    return any(stop_word in prompt.lower() for stop_word in STOP_WORDS)


# --- Existing Speech Recognition Logic (unchanged) ---
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


# --- Instead of local mic capture, we expect prompts from the frontend.
async def receive_prompt(websocket: WebSocket) -> str:
    data = await websocket.receive_text()
    # In production, add JSON parsing and error handling as necessary.
    return data


# --- Main Conversation Loop Wrapped for WebSocket ---
async def main_conversation(websocket: WebSocket) -> None:
    try:
        greeting = "Hello from XMYX Healthcare Company! We are here to assist you. How can I help you today?"
        await websocket.send_text(json.dumps({"type": "status", "message": greeting}))
        az_speech_synthesizer_client.start_speaking_text(greeting)
        await asyncio.sleep(2)

        conversation_history: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        processing_task = None
        last_cancelled_tokens = None

        while True:
            # Receive a prompt from the WebSocket client.
            prompt_raw = await receive_prompt(websocket)
            try:
                prompt_json = json.loads(prompt_raw)
                prompt = prompt_json.get("text", prompt_raw)
            except Exception:
                prompt = prompt_raw

            prompt = prompt.strip()
            if not prompt:
                continue

            # Cancel any ongoing TTS and processing
            az_speech_synthesizer_client.stop_speaking()
            if processing_task and not processing_task.done():
                processing_task.cancel()
                logger.info(f"🛑 Cancelled ongoing processing due to new input: '{prompt[:40]}'")
                if last_cancelled_tokens:
                    logger.info(f"🛑 Last cancelled tokens: {last_cancelled_tokens}")
                with contextlib.suppress(asyncio.CancelledError):
                    await processing_task

            logger.info(f"User said: {prompt}")

            if check_for_stopwords(prompt):
                logger.info("Detected stop word, exiting...")
                exit_text = "Thank you for using our service. Have a great day! Goodbye."
                az_speech_synthesizer_client.start_speaking_text(exit_text)
                await websocket.send_text(json.dumps({"type": "exit", "message": exit_text}))
                await asyncio.sleep(2)
                break

            conversation_history.append({"role": "user", "content": prompt})

            async def process_response(history_snapshot, user_prompt):
                nonlocal last_cancelled_tokens
                tool_name = None
                function_call_arguments = ""
                tool_id = None
                collected_messages: List[str] = []
                cancelled_tokens = []

                try:
                    response = az_openai_client.chat.completions.create(
                        stream=True,
                        messages=history_snapshot,
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
                                    tool_name = delta.tool_calls[0].function.name
                                    tool_id = delta.tool_calls[0].id
                                    history_snapshot.append(delta)
                                if delta.tool_calls[0].function.arguments:
                                    function_call_arguments += delta.tool_calls[0].function.arguments
                            elif delta.content:
                                chunk_text = delta.content
                                if chunk_text:
                                    collected_messages.append(chunk_text)
                                    cancelled_tokens.append(chunk_text)
                                    if chunk_text in tts_sentence_end:
                                        text = "".join(collected_messages).strip()
                                        az_speech_synthesizer_client.start_speaking_text(text)
                                        await websocket.send_text(json.dumps({
                                            "type": "assistant",
                                            "content": text
                                        }))
                                        collected_messages.clear()
                    last_cancelled_tokens = cancelled_tokens

                    # If a tool call was detected, execute it.
                    if tool_name:
                        logger.info(f"tool_name: {tool_name}")
                        logger.info(f"tool_id: {tool_id}")
                        logger.info(f"function_call_arguments: {function_call_arguments}")
                        try:
                            parsed_args = json.loads(function_call_arguments.strip())
                            function_to_call = function_mapping.get(tool_name)

                            if function_to_call:
                                result = await function_to_call(parsed_args)
                                logger.info(f"✅ Function `{tool_name}` executed. Result: {result}")

                                history_snapshot.append({
                                    "tool_call_id": tool_id,
                                    "role": "tool",
                                    "name": tool_name,
                                    "content": result,
                                })

                                # SECOND STREAMING RESPONSE AFTER TOOL EXECUTION
                                second_response = az_openai_client.chat.completions.create(
                                    stream=True,
                                    messages=history_snapshot,
                                    temperature=0.5,
                                    top_p=1.0,
                                    max_tokens=4096,
                                    model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
                                )

                                collected_messages = []
                                cancelled_tokens = []

                                for chunk in second_response:
                                    if chunk.choices:
                                        delta = chunk.choices[0].delta
                                        if hasattr(delta, "content") and delta.content:
                                            chunk_message = delta.content
                                            collected_messages.append(chunk_message)
                                            cancelled_tokens.append(chunk_message)
                                            if chunk_message.strip() in tts_sentence_end:
                                                text = ''.join(collected_messages).strip()
                                                if text:
                                                    az_speech_synthesizer_client.start_speaking_text(text)
                                                    await websocket.send_text(json.dumps({
                                                        "type": "assistant",
                                                        "content": text
                                                    }))
                                                    collected_messages.clear()
                                last_cancelled_tokens = cancelled_tokens

                                final_text = ''.join(collected_messages).strip()
                                if final_text:
                                    history_snapshot.append({"role": "assistant", "content": final_text})

                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Error parsing function arguments: {e}")

                    else:
                        # Append the assistant message if no tool call was made.
                        final_text = ''.join(collected_messages).strip()
                        if final_text:
                            history_snapshot.append({"role": "assistant", "content": final_text})
                            logger.info(f"✅ Final assistant message: {final_text}")
                            await websocket.send_text(json.dumps({
                                "type": "assistant",
                                "content": final_text
                            }))
                except asyncio.CancelledError:
                    logger.info(f"🛑 process_response cancelled for input: '{user_prompt[:40]}'")
                    raise

            # Start processing the new input
            processing_task = asyncio.create_task(process_response(conversation_history.copy(), prompt))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("An error occurred in main_conversation()")
@app.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await main_conversation(websocket)


@app.get("/health")
async def read_health():
    return {"message": "Server is running!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
