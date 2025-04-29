"""
Real-time voice agent backend.

Exposes:
  • /realtime   – bi-directional WebSocket for STT/LLM/TTS
  • /health     – simple liveness probe
"""
import os
import json
import asyncio
import uuid
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import AzureOpenAI

from src.speech.text_to_speech import SpeechSynthesizer
from usecases.browser_RTMedAgent.backend.functions import (
    authenticate_user,
    escalate_emergency,
    evaluate_prior_authorization,
    lookup_medication_info,
    refill_prescription,
    schedule_appointment,
    fill_new_prescription,
    lookup_side_effects,
    get_current_prescriptions,
    check_drug_interactions,
)
from usecases.browser_RTMedAgent.backend.prompt_manager import PromptManager
from usecases.browser_RTMedAgent.backend.tools import available_tools
from utils.ml_logging import get_logger

# ----------------------------- App & Middleware -----------------------------
app: FastAPI = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STOP_WORDS: List[str] = ["goodbye", "exit", "see you later", "bye"]
TTS_END: List[str] = [".", "!", "?", ";", "。", "！", "？", "；", "\n"]

logger = get_logger()
prompt_manager: PromptManager = PromptManager()
az_openai_client: AzureOpenAI = AzureOpenAI(
    api_version="2025-02-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
    api_key=os.getenv("AZURE_OPENAI_KEY", ""),
)
az_speech_synthesizer_client: SpeechSynthesizer = SpeechSynthesizer()

function_mapping: Dict[str, Callable[..., Any]] = {
    "schedule_appointment": schedule_appointment,
    "refill_prescription": refill_prescription,
    "lookup_medication_info": lookup_medication_info,
    "evaluate_prior_authorization": evaluate_prior_authorization,
    "escalate_emergency": escalate_emergency,
    "authenticate_user": authenticate_user,
    "fill_new_prescription": fill_new_prescription,
    "lookup_side_effects": lookup_side_effects,
    "get_current_prescriptions": get_current_prescriptions,
    "check_drug_interactions": check_drug_interactions,
}


class ConversationManager:
    """
    Manages conversation history and context for the voice agent.

    Attributes
    ----------
    pm : PromptManager
        Prompt factory.
    cid : str
        Short conversation ID.
    hist : List[Dict[str, Any]]
        OpenAI chat history.
    """

    def __init__(self, auth: bool = True) -> None:
        self.pm: PromptManager = PromptManager()
        self.cid: str = str(uuid.uuid4())[:8]
        prompt_key: str = (
            "voice_agent_authentication.jinja"
            if auth
            else "voice_agent_system.jinja"
        )
        if auth:
            # TODO: add dynamic prompt once patient metadata is supported
            system_prompt: str = self.pm.get_prompt(prompt_key)
        else:
            system_prompt: str = self.pm.create_prompt_system_main()

        self.hist: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]


def check_for_stopwords(prompt: str) -> bool:
    """Return ``True`` iff the message contains an exit keyword."""
    return any(stop in prompt.lower() for stop in STOP_WORDS)


def check_for_interrupt(prompt: str) -> bool:
    """Return ``True`` iff the message is an interrupt control frame."""
    return "interrupt" in prompt.lower()


async def send_tts_audio(text: str, websocket: WebSocket) -> None:
    """Fire-and-forget TTS synthesis and log enqueue latency."""
    start = time.perf_counter()
    try:
        az_speech_synthesizer_client.start_speaking_text(text)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error synthesizing TTS: {exc}")
    logger.info(f"🗣️ TTS enqueue time: {(time.perf_counter() - start)*1000:.1f} ms")


async def receive_and_filter(websocket: WebSocket) -> Optional[str]:
    """Receive one WS frame; swallow interrupts; return raw payload."""
    start = time.perf_counter()
    raw: str = await websocket.receive_text()
    logger.info(f"📥 WS receive time: {(time.perf_counter() - start)*1000:.1f} ms")
    try:
        msg: Dict[str, Any] = json.loads(raw)
        if msg.get("type") == "interrupt":
            logger.info("🛑 Interrupt received – stopping TTS")
            az_speech_synthesizer_client.stop_speaking()
            return None
    except json.JSONDecodeError:
        pass
    return raw

# --------------------------------------------------------------------------- #
#  Helper to send final event
# --------------------------------------------------------------------------- #
async def push_final(websocket: WebSocket, role: str, content: str) -> None:
    """Emit a single non-streaming message so the UI can close the bubble."""
    await websocket.send_text(json.dumps({"type": role, "content": content}))

def _add_space(text: str) -> str:
    """
    Ensure the chunk ends with a single space or newline.

    This prevents “...assistance.Could” from appearing when we flush on '.'.
    """
    if text and text[-1] not in [" ", "\n"]:
        return text + " "
    return text
# --------------------------------------------------------------------------- #
#  WebSocket entry points
# --------------------------------------------------------------------------- #
@app.websocket("/realtime")
async def websocket_endpoint(websocket: WebSocket) -> None:  # noqa: D401
    """Handle authentication flow, then main conversation."""
    await websocket.accept()
    cm = ConversationManager(auth=True)
    caller_ctx = await authentication_conversation(websocket, cm)
    if caller_ctx:
        cm = ConversationManager(auth=False)
        await main_conversation(websocket, cm)


async def authentication_conversation(
    websocket: WebSocket, cm: ConversationManager
) -> Optional[Dict[str, Any]]:
    """Run the authentication sub-dialogue."""
    greeting = (
        "Hello from XMYX Healthcare Company! Before I can assist you, "
        "let’s verify your identity. How may I address you?"
    )
    await websocket.send_text(json.dumps({"type": "status", "message": greeting}))
    await send_tts_audio(greeting, websocket)
    cm.hist.append({"role": "assistant", "content": greeting})

    while True:
        raw = await receive_and_filter(websocket)
        if raw is None:
            continue
        try:
            prompt = json.loads(raw).get("text", raw)
        except json.JSONDecodeError:
            prompt = raw.strip()
        if not prompt:
            continue
        if check_for_stopwords(prompt):
            bye = "Thank you for calling. Goodbye."
            await websocket.send_text(json.dumps({"type": "exit", "message": bye}))
            await send_tts_audio(bye, websocket)
            return None

        auth_start = time.perf_counter()
        result = await process_gpt_response(cm, prompt, websocket)
        logger.info(
            f"[Latency Summary] phase:auth | cid:{cm.cid} | "
            f"total:{(time.perf_counter() - auth_start)*1000:.1f}ms"
        )
        if result and result.get("authenticated"):
            return result


async def main_conversation(websocket: WebSocket, cm: ConversationManager) -> None:
    """Main multi-turn loop after authentication."""
    while True:
        raw = await receive_and_filter(websocket)
        if raw is None:
            continue
        try:
            prompt = json.loads(raw).get("text", raw)
        except json.JSONDecodeError:
            prompt = raw.strip()
        if not prompt:
            continue
        if check_for_stopwords(prompt):
            goodbye = "Thank you for using our service. Goodbye."
            await websocket.send_text(json.dumps({"type": "exit", "message": goodbye}))
            await send_tts_audio(goodbye, websocket)
            return

        total_start = time.perf_counter()
        await process_gpt_response(cm, prompt, websocket)
        logger.info(
            f"📊 phase:main | cid:{cm.cid} | "
            f"total:{(time.perf_counter() - total_start)*1000:.1f}ms"
        )


# --------------------------------------------------------------------------- #
#  GPT handling
# --------------------------------------------------------------------------- #
async def process_gpt_response(
    cm: ConversationManager, user_prompt: str, websocket: WebSocket
) -> Optional[Dict[str, Any]]:
    """
    Stream GPT response, TTS chunks, handle tools.

    Returns
    -------
    dict | None
        Tool output (only for ``authenticate_user``) or ``None``.
    """
    cm.hist.append({"role": "user", "content": user_prompt})
    logger.info(f"🎙️ Processing prompt: {user_prompt}")

    try:
        stream_start = time.perf_counter()
        response = az_openai_client.chat.completions.create(
            stream=True,
            messages=cm.hist,
            tools=available_tools,
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.5,
            top_p=1.0,
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID", ""),
        )

        collected: List[str] = []
        final_collected: List[str] = []
        prev_ts = stream_start
        tool_started = False
        tool_name = tool_id = args = ""

        for chunk in response:
            now = time.perf_counter()
            logger.info(f"🔸 Chunk arrived after: {(now - prev_ts)*1000:.1f} ms")
            prev_ts = now

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.tool_calls:
                tc = delta.tool_calls[0]
                tool_id = tc.id or tool_id
                tool_name = tc.function.name or tool_name
                args += tc.function.arguments or ""
                tool_started = True
                continue

            if delta.content:
                collected.append(delta.content)
                if delta.content in TTS_END:
                    text_streaming = _add_space("".join(collected).strip())
                    await send_tts_audio(text_streaming, websocket)
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "assistant_streaming",
                                "content": text_streaming,
                            }
                        )
                    )
                    final_collected.append(text_streaming)
                    collected.clear()

        # ── flush any residual text ───────────────────────────────────────────
        if collected:
            pending = "".join(collected).strip()
            await send_tts_audio(pending, websocket)
            await websocket.send_text(
                json.dumps({"type": "assistant_streaming", "content": pending})
            )
            final_collected.append(pending)

        logger.info(
            f"💬 GPT full stream time: "
            f"{(time.perf_counter() - stream_start)*1000:.1f} ms"
        )

        text = "".join(final_collected).strip()
        if text:
            cm.hist.append({"role": "assistant", "content": text})
            await push_final(websocket, "assistant", text)
            logger.info(f"🧠 Assistant responded: {text}")

        if tool_started:
            cm.hist.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {"name": tool_name, "arguments": args},
                        }
                    ],
                }
            )
            return await handle_tool_call(tool_name, tool_id, args, cm, websocket)

    except asyncio.CancelledError:
        logger.info(
            f"🔚 process_gpt_response cancelled for input: '{user_prompt[:40]}'"
        )
        raise

    return None


# --------------------------------------------------------------------------- #
#  Tool life-cycle helpers
# --------------------------------------------------------------------------- #
async def push_tool_start(
    ws: WebSocket,
    call_id: str,
    name: str,
    args: dict,
) -> None:
    """Notify UI that a tool just kicked off."""
    await ws.send_text(json.dumps({
        "type": "tool_start",
        "callId": call_id,
        "tool": name,
        "args": args,          # keep it PHI-free
        "ts": time.time(),
    }))


async def push_tool_progress(
    ws: WebSocket,
    call_id: str,
    pct: int,
    note: str | None = None,
) -> None:
    """Optional: stream granular progress for long-running tools."""
    await ws.send_text(json.dumps({
        "type": "tool_progress",
        "callId": call_id,
        "pct": pct,     # 0-100
        "note": note,
        "ts": time.time(),
    }))


async def push_tool_end(
    ws: WebSocket,
    call_id: str,
    name: str,
    status: str,
    elapsed_ms: float,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Finalise the life-cycle (status = success|error)."""
    await ws.send_text(json.dumps({
        "type": "tool_end",
        "callId": call_id,
        "tool": name,
        "status": status,
        "elapsedMs": round(elapsed_ms, 1),
        "result": result,
        "error": error,
        "ts": time.time(),
    }))


async def handle_tool_call(          # unchanged signature
    tool_name: str,
    tool_id: str,
    function_call_arguments: str,
    cm: ConversationManager,
    websocket: WebSocket,
) -> Any:
    """
    Execute the mapped function tool, stream life-cycle events, preserve
    legacy timing logs, and follow up with GPT.
    """
    call_id = str(uuid.uuid4())[:8]                          # for UI tracking

    try:
        # -------- arguments & lookup -------------------------------------------------
        params = json.loads(function_call_arguments.strip() or "{}")
        fn = function_mapping.get(tool_name)
        if fn is None:
            raise ValueError(f"Unknown tool '{tool_name}'")

        # -------- notify UI that we’re starting --------------------------------------
        await push_tool_start(websocket, call_id, tool_name, params)

        # -------- run the tool (your original timing log preserved) -----------------
        t0 = time.perf_counter()
        result_json = await fn(params)                  # async/await OK
        t1 = time.perf_counter()
        elapsed_ms = (t1 - t0) * 1000

        logger.info(f"⚙️ Tool '{tool_name}' exec time: {elapsed_ms:.1f} ms")

        result = (
            json.loads(result_json) if isinstance(result_json, str) else result_json
        )

        # -------- record in chat history --------------------------------------------
        cm.hist.append(
            {
                "tool_call_id": tool_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result),
            }
        )

        # -------- notify UI that we’re done ------------------------------------------
        await push_tool_end(
            websocket,
            call_id,
            tool_name,
            "success",
            elapsed_ms,
            result=result,
        )

        # -------- ask GPT to follow up with the result ------------------------------
        await process_tool_followup(cm, websocket)
        return result

    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - t0) * 1000 if "t0" in locals() else 0.0
        logger.error(f"Tool '{tool_name}' error: {exc}")

        # tell the UI the tool failed
        await push_tool_end(
            websocket,
            call_id,
            tool_name,
            "error",
            elapsed_ms,
            error=str(exc),
        )
        return {}


async def process_tool_followup(
    cm: ConversationManager, websocket: WebSocket
) -> None:
    """Stream follow-up after tool execution."""
    collected: List[str] = []
    final_collected: List[str] = []

    try:
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
            if getattr(delta, "content", None):
                collected.append(delta.content)
                if delta.content in TTS_END:
                    text_streaming = _add_space("".join(collected).strip())
                    await send_tts_audio(text_streaming, websocket)
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "assistant_streaming",
                                "content": text_streaming,
                            }
                        )
                    )
                    final_collected.append(text_streaming)
                    collected.clear()

        # ── flush tail chunk ─────────────────────────────────────────────────
        if collected:
            pending = "".join(collected).strip()
            await send_tts_audio(pending, websocket)
            await websocket.send_text(
                json.dumps({"type": "assistant_streaming", "content": pending})
            )
            final_collected.append(pending)

        final_text = "".join(final_collected).strip()
        if final_text:
            cm.hist.append({"role": "assistant", "content": final_text})
            await push_final(websocket, "assistant", final_text)
            logger.info(f"🧠 Assistant said: {final_text}")

    except asyncio.CancelledError:
        logger.info("🔚 process_tool_followup cancelled")
        raise


# --------------------------------------------------------------------------- #
#  Health probe
# --------------------------------------------------------------------------- #
@app.get("/health")
async def read_health() -> Dict[str, str]:
    """Kubernetes-friendly liveness endpoint."""
    return {"message": "Server is running!"}


# --------------------------------------------------------------------------- #
#  local dev entry-point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
