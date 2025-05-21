# ✅ RTMedAgent – Production‑ready FastAPI backend
# ------------------------------------------------
# Two‑stage prompt flow:
#   1) Auth prompt  -> voice_agent_authentication.jinja
#   2) Main prompt  -> voice_agent_system.jinja   (after auth or emergency)

import asyncio
import datetime as _dt
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional

import dateparser
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import AzureOpenAI
from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings
from src.speech.text_to_speech import SpeechSynthesizer
from usecases.browser_RTMedAgent.backend.functions import (
    authenticate_user,
    escalate_emergency,
    evaluate_prior_authorization,
    lookup_medication_info,
    refill_prescription,
    schedule_appointment,
)
from usecases.browser_RTMedAgent.backend.prompt_manager import PromptManager
from usecases.browser_RTMedAgent.backend.tools import available_tools
from utils.ml_logging import get_logger

load_dotenv()
logger = get_logger()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    azure_openai_endpoint: HttpUrl = Field(..., env="AZURE_OPENAI_ENDPOINT")
    azure_openai_key: str = Field(..., env="AZURE_OPENAI_KEY")
    allowed_origins: List[HttpUrl] = Field(
        default_factory=lambda: ["http://localhost:5173"], env="ALLOWED_ORIGINS"
    )


settings = Settings()


# ---------------------------------------------------------------------------
# Caller profile & helpers
# ---------------------------------------------------------------------------
@dataclass
class CallerProfile:
    full_name: Optional[str] = None
    dob: Optional[str] = None
    phone: Optional[str] = None
    patient_id: Optional[str] = None
    authenticated: bool = False
    emergency: bool = False


PHONE_RE = re.compile(r"(\d{3})[- ]?(\d{3})[- ]?(\d{4})")


def harvest_profile(txt: str, p: CallerProfile) -> None:
    """Lightweight extraction of profile clues from the user utterance."""
    if not p.phone and (m := PHONE_RE.search(txt)):
        p.phone = "".join(m.groups())

    if not p.dob:
        dob = dateparser.parse(txt, settings={"DATE_ORDER": "MDY"})
        if dob and 1900 < dob.year < _dt.date.today().year:
            p.dob = dob.date().isoformat()

    if not p.full_name and txt.istitle() and len(txt.split()) >= 2:
        p.full_name = txt.strip()


# ---------------------------------------------------------------------------
# Conversation Manager
# ---------------------------------------------------------------------------
class ConversationManager:
    STOP_WORDS = {"goodbye", "exit", "bye", "see you later"}
    SENT_END = {".", "!", "?", "；", "。", "！", "？", "\n"}

    def __init__(
        self, ws: WebSocket, pm: PromptManager, oa: AzureOpenAI, tts: SpeechSynthesizer
    ):
        self.ws, self.pm, self.oa, self.tts = ws, pm, oa, tts
        self.profile = CallerProfile()
        self.auth_prompt_mode = True  # 🔐 start in auth layer
        self.cid = str(uuid.uuid4())[:8]

        # history starts with authentication system prompt
        self.hist: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": self.pm.get_prompt("voice_agent_authentication.jinja"),
            }
        ]

        self._buf = ""
        self._task: Optional[asyncio.Task] = None

    # ---------------- main loop ----------------
    async def run(self) -> None:
        greet = "Hello, thank you for calling XYZ Health Clinic. How may I assist you today?"
        await self._speak(greet, typ="status")
        self.hist.append({"role": "assistant", "content": greet})

        try:
            while True:
                raw = await asyncio.wait_for(self.ws.receive_text(), 180)
                msg = json.loads(raw)

                if not msg.get("is_final", True):
                    continue

                if msg.get("cancel") and self._task and not self._task.done():
                    self._task.cancel()
                    continue

                user = msg.get("text", "").strip()
                if not user:
                    continue

                if any(w in user.lower() for w in self.STOP_WORDS):
                    await self._speak("Thank you for calling. Goodbye!", typ="exit")
                    break

                harvest_profile(user, self.profile)

                if self._task and not self._task.done():
                    self._task.cancel()

                self._task = asyncio.create_task(self._turn(user))

        except WebSocketDisconnect:
            logger.info("[%s] client disconnected", self.cid)

    # ---------------- single turn ----------------
    async def _turn(self, user: str) -> None:
        self.hist.append({"role": "user", "content": user})

        pending_name = pending_id = None
        args_accum = ""
        assistant_buf = ""  # <‑‑ collect streamed assistant text

        async for chunk in self._stream_chat_async(self.hist):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.tool_calls:
                tc = delta.tool_calls[0]
                pending_name, pending_id = tc.function.name, tc.id
                if tc.function.arguments:
                    args_accum += tc.function.arguments
            elif content := getattr(delta, "content", None):
                assistant_buf += content
                await self._buffer_send(content)

        if assistant_buf and not pending_name:
            # normal assistant message (no tool) – store it
            self.hist.append({"role": "assistant", "content": assistant_buf})

        if pending_name:
            await self._invoke_tool(pending_name, args_accum or "{}", pending_id)

    # ---------------- tool handling ----------------
    async def _invoke_tool(self, name: str, arg_json: str, tool_id: str) -> None:
        self.hist.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arg_json},
                    }
                ],
            }
        )

        fn_map = {
            "schedule_appointment": schedule_appointment,
            "refill_prescription": refill_prescription,
            "lookup_medication_info": lookup_medication_info,
            "evaluate_prior_authorization": evaluate_prior_authorization,
            "authenticate_user": authenticate_user,
            "escalate_emergency": escalate_emergency,
        }
        fn = fn_map[name]

        try:
            args = json.loads(arg_json or "{}")
        except json.JSONDecodeError:
            args = {}
            logger.warning("[%s] bad JSON for %s", self.cid, name)

        result = await fn(args) if asyncio.iscoroutinefunction(fn) else fn(args)

        # ---- state update -> prompt switch if needed ----
        try:
            payload = json.loads(result)
            if name == "authenticate_user" and payload.get("ok"):
                self.profile.authenticated = True
                self.profile.patient_id = payload["data"].get("patient_id")
                self._switch_to_main_prompt()
            if name == "escalate_emergency" and payload.get("ok"):
                self.profile.emergency = True
                self._switch_to_main_prompt()
        except Exception:
            pass

        self.hist.append(
            {"tool_call_id": tool_id, "role": "tool", "name": name, "content": result}
        )

        # stream follow‑up assistant response
        assistant_buf = ""
        async for chunk in self._stream_chat_async(self.hist):
            if chunk.choices and (
                c := getattr(chunk.choices[0].delta, "content", None)
            ):
                assistant_buf += c
                await self._buffer_send(c)

        if assistant_buf:
            self.hist.append({"role": "assistant", "content": assistant_buf})

    # ---------------- switch prompt ----------------
    def _switch_to_main_prompt(self):
        if not self.auth_prompt_mode:
            return
        self.auth_prompt_mode = False
        # flush auth conversation
        self.hist = [
            {
                "role": "system",
                "content": self.pm.get_prompt("voice_agent_system.jinja"),
            },
            {
                "role": "assistant",
                "content": "Thank you for verifying your information. How can I help you today?",
            },
        ]

    # ---------------- helpers ----------------
    def _stream_chat(self, msgs):
        return self.oa.chat.completions.create(
            stream=True,
            messages=msgs,
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_ID"),
            temperature=0.5,
            top_p=1.0,
            max_tokens=4096,
            tools=available_tools,
            tool_choice="auto",
        )

    async def _stream_chat_async(self, msgs) -> AsyncGenerator[Any, None]:
        stream = await asyncio.to_thread(self._stream_chat, msgs)
        for c in stream:
            yield c

    async def _buffer_send(self, token: str):
        if token in self.SENT_END:
            sent, self._buf = self._buf.strip(), ""
            if sent:
                await self._speak(sent)
        else:
            self._buf += token

    async def _speak(self, text: str, typ: str = "assistant") -> None:
        await self.ws.send_text(json.dumps({"type": typ, "content": text}))
        await asyncio.to_thread(self.tts.start_speaking_text, text)


# ---------------------------------------------------------------------------
# FastAPI wiring
# ---------------------------------------------------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pm = PromptManager()
tts = SpeechSynthesizer()
openai_client = AzureOpenAI(
    api_version="2025-02-01-preview",
    azure_endpoint=str(settings.azure_openai_endpoint),
    api_key=settings.azure_openai_key,
)


@app.websocket("/realtime")
async def realtime(ws: WebSocket):
    await ws.accept()
    await ConversationManager(ws, pm, openai_client, tts).run()


@app.get("/health")
async def health():
    return {"message": "Server is running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
