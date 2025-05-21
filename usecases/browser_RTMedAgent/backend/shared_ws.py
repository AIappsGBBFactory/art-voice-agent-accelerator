"""
shared_ws.py
============
Helpers that BOTH realtime and ACS routers rely on:

    • send_tts_audio        – browser TTS
    • send_response_to_acs  – phone-call TTS
    • push_final            – “close bubble” helper
    • broadcast_message     – relay to /relay dashboards
"""
from __future__ import annotations

import asyncio
import json
from fastapi import WebSocket

from services.speech_services import SpeechSynthesizer
from usecases.browser_RTMedAgent.backend.acs_helpers import (
    broadcast_message,
    send_pcm_frames,
)
from typing import Optional, Set


async def send_tts_audio(text: str, ws: WebSocket) -> None:
    """
    Fire-and-forget speech for browser clients.

    Uses the synthesiser cached on FastAPI `app.state.tts_client`.
    """
    synth: SpeechSynthesizer = ws.app.state.tts_client          # type: ignore[attr-defined]
    synth.start_speaking_text(text)

async def send_response_to_acs(
    ws: WebSocket,
    text: str,
    *,
    blocking: bool = False
) -> Optional[asyncio.Task]:
    synth: SpeechSynthesizer = ws.app.state.tts_client
    pcm = synth.synthesize_to_base64_frames(text, sample_rate=16000)

    coro = send_pcm_frames(ws, pcm_bytes=pcm, sample_rate=16000)

    if blocking:
        await coro
        return None

    # ---------- NEW: remember the task so we can cancel it later -----------
    if not hasattr(ws.app.state, "tts_tasks"):
        ws.app.state.tts_tasks: Set[asyncio.Task] = set()

    task = asyncio.create_task(coro)
    ws.app.state.tts_tasks.add(task)
    task.add_done_callback(lambda t: ws.app.state.tts_tasks.discard(t))
    # -----------------------------------------------------------------------
    return task

async def push_final(
    ws: WebSocket,
    role: str,
    content: str,
    *,
    is_acs: bool = False,
) -> None:
    """
    Close the streaming bubble on the front-end.

    • Browser/WebRTC – we already streamed TTS, just send the final JSON.
    • ACS            – same; streaming audio is finished, no repeat playback.
    """
    await ws.send_text(json.dumps({"type": role, "content": content}))


# --------------------------------------------------------------------------- #
# Re-export for convenience
# --------------------------------------------------------------------------- #
__all__ = [
    "send_tts_audio",
    "send_response_to_acs",
    "push_final",
    "broadcast_message",
]
