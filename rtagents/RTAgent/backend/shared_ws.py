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
import base64
import asyncio
import json
from fastapi import WebSocket
from fastapi.websockets import WebSocketState

from rtagents.RTAgent.backend.orchestration.conversation_state import ConversationManager
from rtagents.RTAgent.backend.services.speech_services import SpeechSynthesizer
from rtagents.RTAgent.backend.latency.latency_tool import LatencyTool
from rtagents.RTAgent.backend.services.acs.acs_helpers import (
    broadcast_message,
    send_pcm_frames,
    play_response_with_queue,
)
from typing import Optional, Set
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
    synth.start_speaking_text(text)
    if latency_tool:
        latency_tool.stop("tts", ws.app.state.redis)


async def send_response_to_acs(
    ws: WebSocket,
    text: str,
    *,
    blocking: bool = False,
    latency_tool: Optional[LatencyTool] = None,
    stream_mode: str = "media"
) -> Optional[asyncio.Task]:
    """
    Synthesizes speech and sends it as audio data to the ACS WebSocket.

    Adds latency tracking for TTS step.
    """


    if latency_tool:
        latency_tool.start("tts")
        latency_tool.start("tts:synthesis")
    # synth: SpeechSynthesizer = ws.app.state.tts_client
    # pcm = synth.synthesize_to_base64_frames(text, sample_rate=16000)
    # coro = send_pcm_frames(ws, pcm_bytes=pcm, sample_rate=16000)

    # if blocking:
    #     await coro
    #     if latency_tool:
    #         latency_tool.stop("tts", ws.app.state.redis)
    #     return None
    async def stop_latency(task):
        if latency_tool:
            latency_tool.stop("tts", ws.app.state.redis)
        ws.app.state.tts_tasks.discard(task)

    if stream_mode == "media":
        synth: SpeechSynthesizer = ws.app.state.tts_client

        try:
            
            # Add timeout and retry logic for TTS synthesis
            pcm_bytes = synth.synthesize_to_pcm(text)
            latency_tool.stop("tts:synthesis", ws.app.state.redis)


        except asyncio.TimeoutError:
            logger.error(f"TTS synthesis timed out for text: {text[:50]}...")
            raise RuntimeError("TTS synthesis timed out")
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            # Try to reinitialize the synthesizer if it failed
            # # try:
            # #     synth = SpeechSynthesizer()
            # #     ws.app.state.tts_client = synth
            # #     pcm_bytes = synth.synthesize_to_pcm(text)

            # # except Exception as retry_error:
            # #     logger.error(f"TTS retry also failed: {retry_error}")
            # #     raise RuntimeError(f"TTS failed after retry: {retry_error}")
        frames = SpeechSynthesizer.split_pcm_to_base64_frames(pcm_bytes, sample_rate=16000)

        for frame in frames:
            await ws.send_json({
                "kind": "AudioData",
                "AudioData": {"data": frame},
                "StopAudio": None
            })
        
        if latency_tool:
            latency_tool.stop("tts", ws.app.state.redis)

        # # frame_size = 320  # 10ms @ 16kHz PCM mono for smoother streaming

        # # for i in range(0, len(pcm_bytes), frame_size):
        # #     frame = pcm_bytes[i:i + frame_size]
        # #     if len(frame) < frame_size:
        # #         frame = frame + b'\x00' * (frame_size - len(frame))

        # #     try:
        # #         if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
        # #             logger.warning(f"WebSocket disconnected during TTS streaming at frame {i//frame_size}")
        # #             break

        # #         # Check the in-memory flag instead of querying Redis
        # #         # interrupted = ws.state.cm.is_tts_interrupted()
        # #         # if interrupted and interrupted != "false":  # Handle both boolean True and truthy strings
        # #         #     logger.info("TTS interrupted, stopping media streaming.")
        # #         #     await ws.send_json({
        # #         #         "Kind": "StopAudio",
        # #         #         "AudioData": None,
        # #         #         "StopAudio": {}
        # #         #     })
        # #         #     break

        # #         b64 = base64.b64encode(frame).decode("utf-8")
        # #         await ws.send_json({
        # #             "kind": "AudioData",
        # #             "AudioData": {"data": b64}
        # #         })
        # #         # Small yield to allow barge-in detection and other tasks
        # #         # await asyncio.sleep(0.005)  # 5ms - balance between streaming speed and responsiveness
        # #     except Exception as e:
        # #         if ws.application_state != WebSocketState.CONNECTED:
        # #             logger.warning(f"WebSocket disconnected during TTS streaming: {e}")
        # #             break
        # #         continue
        # # try:
        # #     if ws.client_state != WebSocketState.CONNECTED:
        # #         logger.warning("WebSocket no longer connected, stopping TTS.")
        # #         return
        # #     await task
        # # except asyncio.CancelledError:
        # #     logger.info("TTS task was cancelled cleanly.")
        # # except Exception as e:
        # #     logger.warning(f"TTS task failed: {e}")
        # # pcm_bytes_array = synth.synthesize_to_base64_frames(text, sample_rate=16000)
        # # await send_pcm_frames(ws, b64_frames=pcm_bytes_array, sample_rate=16000)

    if stream_mode == "transcription":
        acs_caller = ws.app.state.acs_caller
        if not acs_caller:
            raise RuntimeError("ACS caller is not initialized in WebSocket state.")
        
        coro = play_response_with_queue(
            ws=ws,
            response_text=text,
            participants=[ws.app.state.target_participant]
        )

    #     if not hasattr(ws.app.state, "tts_tasks"):
    #         ws.app.state.tts_tasks = set()

    # task = asyncio.create_task(coro)
    # ws.app.state.tts_tasks.add(task)
    # task.add_done_callback(stop_latency)

    # return task


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
