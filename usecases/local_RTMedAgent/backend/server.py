import asyncio
import contextlib
import json
import os
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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# GPT, TTS, tools
from openai import AzureOpenAI

from src.speech.text_to_speech import SpeechSynthesizer
from utils.ml_logging import get_logger

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # <-- tighten this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/frontend"), name="static")

STOP_WORDS = ["goodbye", "exit", "see you later", "bye"]
logger = get_logger()
prompt_manager = PromptManager()
system_prompt = prompt_manager.get_prompt("voice_agent_system.jinja")

az_openai_client = AzureOpenAI(
    api_version="2025-02-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
)

az_speech_synthesizer_client = SpeechSynthesizer()

function_mapping = {
    "schedule_appointment": schedule_appointment,
    "refill_prescription": refill_prescription,
    "lookup_medication_info": lookup_medication_info,
    "evaluate_prior_authorization": evaluate_prior_authorization,
    "escalate_emergency": escalate_emergency,
    "authenticate_user": authenticate_user,
}


@app.get("/", response_class=HTMLResponse)
async def get_index():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.join(current_dir, "..", "frontend")
    index_path = os.path.join(frontend_dir, "index.html")
    with open(index_path, encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)


def check_for_stopwords(prompt: str) -> bool:
    return any(stop_word in prompt.lower() for stop_word in STOP_WORDS)


async def send_tts_audio(text: str, websocket: WebSocket):
    try:
        az_speech_synthesizer_client.start_speaking_text(text)
    except Exception as e:
        logger.error(f"Error synthesizing TTS: {e}")


@app.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await main_conversation(websocket)


async def main_conversation(websocket: WebSocket) -> None:
    try:
        greeting_text = "Hello from XMYX Healthcare Company! We are here to assist you. How can I help you today?"
        await websocket.send_text(
            json.dumps({"type": "status", "message": greeting_text})
        )
        await send_tts_audio(greeting_text, websocket)
        await asyncio.sleep(1)

        conversation_history: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

        processing_task = None
        last_cancelled_tokens = None

        while True:
            prompt_raw = await websocket.receive_text()
            try:
                prompt_json = json.loads(prompt_raw)
                prompt = prompt_json.get("text", prompt_raw)
            except Exception:
                prompt = prompt_raw

            prompt = prompt.strip()
            if not prompt:
                continue

            logger.info(f"User said: {prompt}")

            if check_for_stopwords(prompt):
                logger.info("Detected stop word, exiting...")
                exit_text = (
                    "Thank you for using our service. Have a great day! Goodbye."
                )
                await websocket.send_text(
                    json.dumps({"type": "exit", "message": exit_text})
                )
                await send_tts_audio(exit_text, websocket)
                await asyncio.sleep(1)
                break

            if processing_task and not processing_task.done():
                processing_task.cancel()
                logger.info(
                    f"🛑 Cancelled ongoing GPT response for new input: '{prompt[:40]}'"
                )
                if last_cancelled_tokens:
                    logger.info(f"🛑 Last cancelled tokens: {last_cancelled_tokens}")
                with contextlib.suppress(asyncio.CancelledError):
                    await processing_task

            conversation_history.append({"role": "user", "content": prompt})

            processing_task = asyncio.create_task(
                process_gpt_response(conversation_history.copy(), prompt, websocket)
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("An error occurred in main_conversation()")


async def process_gpt_response(history_snapshot, user_prompt, websocket: WebSocket):
    tool_name = None
    function_call_arguments = ""
    tool_id = None
    collected_messages: List[str] = []
    cancelled_tokens = []

    tts_sentence_end = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]
    global last_cancelled_tokens

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
                        function_call_arguments += delta.tool_calls[
                            0
                        ].function.arguments

                elif delta.content:
                    chunk_text = delta.content
                    if chunk_text:
                        collected_messages.append(chunk_text)
                        cancelled_tokens.append(chunk_text)

                        if chunk_text in tts_sentence_end:
                            text_to_speak = "".join(collected_messages).strip()
                            await websocket.send_text(
                                json.dumps(
                                    {"type": "assistant", "content": text_to_speak}
                                )
                            )
                            await send_tts_audio(text_to_speak, websocket)
                            collected_messages.clear()

        last_cancelled_tokens = cancelled_tokens

        final_text = "".join(collected_messages).strip()
        if final_text:
            await websocket.send_text(
                json.dumps({"type": "assistant", "content": final_text})
            )
            await send_tts_audio(final_text, websocket)
            history_snapshot.append({"role": "assistant", "content": final_text})

        if tool_name:
            await handle_tool_call(
                tool_name, tool_id, function_call_arguments, history_snapshot, websocket
            )

    except asyncio.CancelledError:
        logger.info(f"🛑 process_gpt_response cancelled for input: '{user_prompt[:40]}'")
        raise


async def handle_tool_call(
    tool_name, tool_id, function_call_arguments, history_snapshot, websocket
):
    logger.info(f"tool_name: {tool_name}")
    logger.info(f"tool_id: {tool_id}")
    logger.info(f"function_call_arguments: {function_call_arguments}")

    try:
        parsed_args = json.loads(function_call_arguments.strip())
        function_to_call = function_mapping.get(tool_name)

        if function_to_call:
            result = await function_to_call(parsed_args)
            logger.info(f"✅ Function `{tool_name}` executed. Result: {result}")

            history_snapshot.append(
                {
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": result,
                }
            )

            await process_tool_followup(history_snapshot, websocket)

    except json.JSONDecodeError as e:
        logger.error(f"❌ Error parsing function arguments: {e}")


async def process_tool_followup(history_snapshot, websocket):
    collected_messages = []
    tts_sentence_end = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]

    second_response = az_openai_client.chat.completions.create(
        stream=True,
        messages=history_snapshot,
        temperature=0.5,
        top_p=1.0,
        max_tokens=4096,
        model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
    )

    for chunk in second_response:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if hasattr(delta, "content") and delta.content:
                chunk_message = delta.content
                collected_messages.append(chunk_message)

                if chunk_message.strip() in tts_sentence_end:
                    text_to_speak = "".join(collected_messages).strip()
                    if text_to_speak:
                        await websocket.send_text(
                            json.dumps({"type": "assistant", "content": text_to_speak})
                        )
                        await send_tts_audio(text_to_speak, websocket)
                        collected_messages.clear()

    final_text = "".join(collected_messages).strip()
    if final_text:
        await websocket.send_text(
            json.dumps({"type": "assistant", "content": final_text})
        )
        await send_tts_audio(final_text, websocket)
        history_snapshot.append({"role": "assistant", "content": final_text})


@app.get("/health")
async def read_health():
    return {"message": "Server is running!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
