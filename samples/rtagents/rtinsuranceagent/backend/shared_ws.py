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
from typing import Optional, Set

from fastapi import WebSocket
from rtagents.RTInsuranceAgent.backend.latency.latency_tool import LatencyTool
from rtagents.RTInsuranceAgent.backend.services.acs.acs_helpers import (
    broadcast_message,
    play_response_with_queue,
    send_pcm_frames,
)
from rtagents.RTInsuranceAgent.backend.services.speech_services import SpeechSynthesizer


async def send_tts_audio(
    text: str, ws: WebSocket, latency_tool: Optional[LatencyTool] = None
) -> None:
    """
    Fire-and-forget speech for browser clients.

    Uses the synthesiser cached on FastAPI `app.state.tts_client`.
    Adds latency tracking for TTS step.
    """
    if latency_tool:
        latency_tool.start("tts")
    synth: SpeechSynthesizer = ws.app.state.tts_client
    ws.state.is_synthesizing = True  # type: ignore[attr-defined]
    synth.start_speaking_text(text)
    if latency_tool:
        latency_tool.stop("tts", ws.app.state.redis)


async def send_response_to_acs(
    ws: WebSocket,
    text: str,
    *,
    blocking: bool = False,
    latency_tool: Optional[LatencyTool] = None,
) -> Optional[asyncio.Task]:
    """
    Synthesizes speech and sends it as audio data to the ACS WebSocket.

    Adds latency tracking for TTS step.
    """
    if latency_tool:
        latency_tool.start("tts")
    # synth: SpeechSynthesizer = ws.app.state.tts_client
    # pcm = synth.synthesize_to_base64_frames(text, sample_rate=16000)
    # coro = send_pcm_frames(ws, pcm_bytes=pcm, sample_rate=16000)

    # if blocking:
    #     await coro
    #     if latency_tool:
    #         latency_tool.stop("tts", ws.app.state.redis)
    #     return None

    acs_caller = ws.app.state.acs_caller
    if not acs_caller:
        raise RuntimeError("ACS caller is not initialized in WebSocket state.")

    coro = play_response_with_queue(
        ws=ws, response_text=text, participants=[ws.app.state.target_participant]
    )

    if not hasattr(ws.app.state, "tts_tasks"):
        ws.app.state.tts_tasks = set()

    task = asyncio.create_task(coro)
    ws.app.state.tts_tasks.add(task)

    async def stop_latency(_):
        if latency_tool:
            latency_tool.stop("tts", ws.app.state.redis)
        ws.app.state.tts_tasks.discard(task)

    task.add_done_callback(stop_latency)
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
