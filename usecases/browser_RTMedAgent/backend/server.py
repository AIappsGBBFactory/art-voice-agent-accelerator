import os
import json
import asyncio
import uuid
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import AzureOpenAI

from src.speech.text_to_speech import SpeechSynthesizer
from usecases.browser_RTMedAgent.backend.tools import available_tools
from usecases.browser_RTMedAgent.backend.functions import (
    schedule_appointment,
    refill_prescription,
    lookup_medication_info,
    evaluate_prior_authorization,
    escalate_emergency,
    authenticate_user,
)
from usecases.browser_RTMedAgent.backend.prompt_manager import PromptManager
from utils.ml_logging import get_logger

# ----------------------------- App & Middleware -----------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STOP_WORDS = ["goodbye", "exit", "see you later", "bye"]
logger = get_logger()
prompt_manager = PromptManager()
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

# ----------------------------- Conversation Manager -----------------------------
class ConversationManager:
    def __init__(self, auth: bool = True):
        self.pm = PromptManager()
        self.cid = str(uuid.uuid4())[:8]
        prompt = self.pm.get_prompt("voice_agent_authentication.jinja" if auth else "voice_agent_system.jinja")
        self.hist = [{"role": "system", "content": prompt}]

# ----------------------------- Utils -----------------------------
def check_for_stopwords(prompt: str) -> bool:
    return any(stop_word in prompt.lower() for stop_word in STOP_WORDS)

def check_for_interrupt(prompt: str) -> bool:
    return any(interrupt in prompt.lower() for interrupt in ["interrupt"])

async def send_tts_audio(text: str, websocket: WebSocket):
    try:
        az_speech_synthesizer_client.start_speaking_text(text)
    except Exception as e:
        logger.error(f"Error synthesizing TTS: {e}")

async def receive_and_filter(websocket: WebSocket) -> Optional[str]:
    """
    Receive one WebSocket frame, stop TTS & return None if it's an interrupt.
    Otherwise return raw text.
    """
    raw = await websocket.receive_text()
    try:
        msg = json.loads(raw)
        if msg.get("type") == "interrupt":
            logger.info("🛑 Interrupt received, stopping TTS")
            az_speech_synthesizer_client.stop_speaking()
            return None
    except json.JSONDecodeError:
        pass
    return raw

# ----------------------------- WebSocket Flow -----------------------------
@app.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    cm = ConversationManager(auth=True)
    caller_ctx = await authentication_conversation(websocket, cm)
    if caller_ctx:
        cm = ConversationManager(auth=False)
        await main_conversation(websocket, cm)

# ----------------------------- Auth Flow -----------------------------
async def authentication_conversation(websocket: WebSocket, cm: ConversationManager) -> Optional[Dict[str, Any]]:
    greeting = "Hello from XMYX Healthcare Company! Before I can assist you, let’s verify your identity. How may I address you?"
    await websocket.send_text(json.dumps({"type": "status", "message": greeting}))
    await send_tts_audio(greeting, websocket)
    cm.hist.append({"role": "assistant", "content": greeting})

    while True:
        try:
            # <-- receive one frame raw
            prompt_raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return

        # <-- interrupt filter
        try:
            msg = json.loads(prompt_raw)
            if msg.get("type") == "interrupt":
                logger.info("🛑 Interrupt received; stopping TTS and skipping GPT")
                az_speech_synthesizer_client.stop_speaking()
                continue
        except json.JSONDecodeError:
            pass

        # <-- now parse true user text
        try:
            prompt = json.loads(prompt_raw).get("text", prompt_raw)
        except json.JSONDecodeError:
            prompt = prompt_raw.strip()

        if not prompt:
            continue
        if check_for_stopwords(prompt):
            bye = "Thank you for calling. Goodbye."
            await websocket.send_text(json.dumps({"type": "exit", "message": bye}))
            await send_tts_audio(bye, websocket)
            return None

        result = await process_gpt_response(cm, prompt, websocket)
        if result and result.get("authenticated"):
            return result


# ----------------------------- Main Flow -----------------------------
async def main_conversation(websocket: WebSocket, cm: ConversationManager):
    while True:
        try:
            # <-- receive one frame raw
            prompt_raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return

        # <-- interrupt filter
        try:
            msg = json.loads(prompt_raw)
            if msg.get("type") == "interrupt":
                logger.info("🛑 Interrupt received; stopping TTS and skipping GPT")
                az_speech_synthesizer_client.stop_speaking()
                continue
        except json.JSONDecodeError:
            pass

        # <-- now parse true user text
        try:
            prompt = json.loads(prompt_raw).get("text", prompt_raw)
        except json.JSONDecodeError:
            prompt = prompt_raw.strip()

        if not prompt:
            continue
        if check_for_stopwords(prompt):
            goodbye = "Thank you for using our service. Goodbye."
            await websocket.send_text(json.dumps({"type": "exit", "message": goodbye}))
            await send_tts_audio(goodbye, websocket)
            return

        await process_gpt_response(cm, prompt, websocket)

# ----------------------------- GPT Processing -----------------------------
async def process_gpt_response(cm: ConversationManager, user_prompt: str, websocket: WebSocket):
    cm.hist.append({"role": "user", "content": user_prompt})
    logger.info(f"🎙️ User input received: {user_prompt}")
    tool_name = tool_call_id = function_call_arguments = ""
    collected_messages = []

    try:
        response = az_openai_client.chat.completions.create(
            stream=True,
            messages=cm.hist,
            tools=available_tools,
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.5,
            top_p=1.0,
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
        )

        full_response = ""
        tool_call_started = False

        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.tool_calls:
                tool_call = delta.tool_calls[0]
                tool_call_id = tool_call.id or tool_call_id
                if tool_call.function.name:
                    tool_name = tool_call.function.name
                if tool_call.function.arguments:
                    function_call_arguments += tool_call.function.arguments
                tool_call_started = True
                continue

            if delta.content:
                chunk_text = delta.content
                collected_messages.append(chunk_text)
                full_response += chunk_text

        final_text = "".join(collected_messages).strip()
        if final_text:
            await websocket.send_text(json.dumps({"type": "assistant", "content": final_text}))
            await send_tts_audio(final_text, websocket)
            cm.hist.append({"role": "assistant", "content": final_text})
            logger.info(f"🧠 Assistant said: {final_text}")

        if tool_call_started and tool_call_id and tool_name and function_call_arguments:
            cm.hist.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": function_call_arguments
                        }
                    }
                ]
            })
            tool_result = await handle_tool_call(tool_name, tool_call_id, function_call_arguments, cm, websocket)
            return tool_result if tool_name == "authenticate_user" else None

    except asyncio.CancelledError:
        logger.info(f"🔚 process_gpt_response cancelled for input: '{user_prompt[:40]}'")
        raise

    return None

# ----------------------------- Tool Handler -----------------------------
async def handle_tool_call(tool_name, tool_id, function_call_arguments, cm: ConversationManager, websocket: WebSocket):
    try:
        parsed_args = json.loads(function_call_arguments.strip() or "{}")
        function_to_call = function_mapping.get(tool_name)
        if function_to_call:
            result_json = await function_to_call(parsed_args)
            result = json.loads(result_json) if isinstance(result_json, str) else result_json

            cm.hist.append({
                "tool_call_id": tool_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result),
            })

            await process_tool_followup(cm, websocket)
            return result
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing function arguments: {e}")
    return {}

# ----------------------------- Follow-Up -----------------------------
async def process_tool_followup(cm: ConversationManager, websocket: WebSocket):
    collected_messages = []
    response = az_openai_client.chat.completions.create(
        stream=True,
        messages=cm.hist,
        temperature=0.5,
        top_p=1.0,
        max_tokens=4096,
        model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
    )

    for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if hasattr(delta, "content") and delta.content:
            chunk_message = delta.content
            collected_messages.append(chunk_message)

    final_text = "".join(collected_messages).strip()
    if final_text:
        await websocket.send_text(json.dumps({"type": "assistant", "content": final_text}))
        await send_tts_audio(final_text, websocket)
        cm.hist.append({"role": "assistant", "content": final_text})
        logger.info(f"🧠 Assistant said: {final_text}")

# ----------------------------- Health -----------------------------
@app.get("/health")
async def read_health():
    return {"message": "Server is running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
