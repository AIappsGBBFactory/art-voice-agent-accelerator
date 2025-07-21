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
import base64
import json
from typing import Optional, Set

from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from apps.rtagent.backend.src.latency.latency_tool import LatencyTool
from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.src.services.acs.acs_helpers import (
    broadcast_message,
    play_response_with_queue,
)
from apps.rtagent.backend.src.services.speech_services import SpeechSynthesizer
from apps.rtagent.backend.settings import ACS_STREAMING_MODE

from src.enums.stream_modes import StreamMode
from utils.ml_logging import get_logger

logger = get_logger("shared_ws")


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
    stream_mode: StreamMode = ACS_STREAMING_MODE,
) -> Optional[asyncio.Task]:
    """
    Synthesizes speech and sends it as audio data to the ACS WebSocket.

    Adds latency tracking for TTS step.
    """

    if latency_tool:
        latency_tool.start("tts")
        latency_tool.start("tts:synthesis")

    async def stop_latency(task):
        if latency_tool:
            latency_tool.stop("tts", ws.app.state.redis)
        ws.app.state.tts_tasks.discard(task)

    if stream_mode == StreamMode.MEDIA:
        synth: SpeechSynthesizer = ws.app.state.tts_client

        try:
            # Add timeout and retry logic for TTS synthesis
            pcm_bytes = synth.synthesize_to_pcm(text)
            latency_tool.stop("tts:synthesis", ws.app.state.redis)

        except asyncio.TimeoutError:
            logger.error(f"TTS synthesis timed out for texphat: {text[:50]}...")
            raise RuntimeError("TTS synthesis timed out")
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
        frames = SpeechSynthesizer.split_pcm_to_base64_frames(
            pcm_bytes, sample_rate=16000
        )

        for frame in frames:
            await ws.send_json(
                {"kind": "AudioData", "AudioData": {"data": frame}, "StopAudio": None}
            )

        if latency_tool:
            latency_tool.stop("tts", ws.app.state.redis)

    elif stream_mode == StreamMode.TRANSCRIPTION:
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
