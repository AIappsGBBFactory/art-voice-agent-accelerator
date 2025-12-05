"""
TTS Sender - Speech Cascade TTS Playback
=========================================

Handles TTS audio synthesis and streaming to WebSocket clients.
Voice configuration MUST come from agent config, not environment variables.

This module is part of the speech_cascade architecture and is designed
to work with agent-based voice configuration.

Usage:
    from apps.artagent.backend.voice.speech_cascade.tts_sender import (
        send_tts_to_browser,
        send_tts_to_acs,
    )
"""

from __future__ import annotations

import asyncio
import base64
import struct
import time
import uuid
from functools import partial
from typing import Any, Callable, Optional

from fastapi import WebSocket

from src.tools.latency_tool import LatencyTool
from utils.ml_logging import get_logger

# Audio configuration
TTS_SAMPLE_RATE_UI = 48000
TTS_SAMPLE_RATE_ACS = 16000

logger = get_logger("voice.speech_cascade.tts_sender")


def _get_connection_metadata(ws: WebSocket, key: str, default=None):
    """Get metadata from websocket state."""
    return getattr(ws.state, key, default)


def _set_connection_metadata(ws: WebSocket, key: str, value) -> bool:
    """Set metadata on websocket state."""
    try:
        setattr(ws.state, key, value)
        return True
    except Exception:
        return False


async def send_tts_to_browser(
    text: str,
    ws: WebSocket,
    voice_name: str,
    voice_style: Optional[str] = None,
    voice_rate: Optional[str] = None,
    latency_tool: Optional[LatencyTool] = None,
    on_first_audio: Optional[Callable[[], None]] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> None:
    """
    Send TTS audio to browser WebSocket client.
    
    Voice configuration MUST be provided - no fallback to environment variables.
    This ensures voice always comes from agent YAML configuration.
    
    Args:
        text: Text to synthesize
        ws: WebSocket connection
        voice_name: Azure TTS voice name (REQUIRED - e.g., "en-US-AvaMultilingualNeural")
        voice_style: Voice style (e.g., "conversational", "chat")
        voice_rate: Voice rate (e.g., "-4%", "medium")
        latency_tool: Optional latency tracking
        on_first_audio: Callback when first audio chunk is sent
        cancel_event: Event to signal cancellation
    """
    run_id = str(uuid.uuid4())[:8]
    session_id = getattr(ws.state, "session_id", None)
    
    if not voice_name:
        logger.error(
            "[%s] TTS called without voice_name - agent config missing? (run=%s)",
            session_id,
            run_id,
        )
        return
    
    # Use provided cancel_event or get from websocket state
    if cancel_event is None:
        cancel_event = _get_connection_metadata(ws, "tts_cancel_event")
    
    style = voice_style or "conversational"
    eff_rate = voice_rate or "medium"
    
    logger.debug(
        "[%s] TTS synthesis: voice=%s style=%s rate=%s (run=%s)",
        session_id,
        voice_name,
        style,
        eff_rate,
        run_id,
    )
    
    # Start latency tracking
    if latency_tool:
        try:
            if not hasattr(latency_tool, "_active_timers"):
                latency_tool._active_timers = set()
            if "tts" not in latency_tool._active_timers:
                latency_tool.start("tts")
                latency_tool._active_timers.add("tts")
            if "tts:synthesis" not in latency_tool._active_timers:
                latency_tool.start("tts:synthesis")
                latency_tool._active_timers.add("tts:synthesis")
        except Exception as e:
            logger.debug("Latency start error (run=%s): %s", run_id, e)
    
    # Acquire TTS synthesizer
    synth = None
    client_tier = None
    temp_synth = False
    
    try:
        synth, client_tier = await ws.app.state.tts_pool.acquire_for_session(session_id)
        logger.debug(
            "[%s] Using TTS client tier=%s (run=%s)",
            session_id,
            getattr(client_tier, "value", "?"),
            run_id,
        )
    except Exception as e:
        logger.error("[%s] Failed to get TTS client (run=%s): %s", session_id, run_id, e)
    
    # Fallback to legacy pool
    if not synth:
        synth = _get_connection_metadata(ws, "tts_client")
        if not synth:
            logger.warning("[%s] Falling back to legacy TTS pool (run=%s)", session_id, run_id)
            try:
                synth = await ws.app.state.tts_pool.acquire(timeout=2.0)
                temp_synth = True
            except Exception as e:
                logger.error("[%s] TTS pool exhausted (run=%s): %s", session_id, run_id, e)
                return
    
    try:
        if cancel_event and cancel_event.is_set():
            logger.info("[%s] Skipping TTS (cancelled) (run=%s)", session_id, run_id)
            cancel_event.clear()
            return
        
        now = time.monotonic()
        _set_connection_metadata(ws, "is_synthesizing", True)
        _set_connection_metadata(ws, "audio_playing", True)
        _set_connection_metadata(ws, "last_tts_start_ts", now)
        
        # Voice warm-up (one-time per voice signature)
        warm_signature = (voice_name, style, eff_rate)
        prepared_voices: set = getattr(synth, "_prepared_voices", None)
        if prepared_voices is None:
            prepared_voices = set()
            setattr(synth, "_prepared_voices", prepared_voices)
        
        if warm_signature not in prepared_voices:
            warm_partial = partial(
                synth.synthesize_to_pcm,
                text=" .",
                voice=voice_name,
                sample_rate=TTS_SAMPLE_RATE_UI,
                style=style,
                rate=eff_rate,
            )
            try:
                loop = asyncio.get_running_loop()
                executor = getattr(ws.app.state, "speech_executor", None)
                if executor:
                    await asyncio.wait_for(
                        loop.run_in_executor(executor, warm_partial), timeout=4.0
                    )
                else:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, warm_partial), timeout=4.0
                    )
                prepared_voices.add(warm_signature)
                logger.debug(
                    "[%s] Warmed TTS voice=%s (run=%s)",
                    session_id,
                    voice_name,
                    run_id,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[%s] TTS warm-up timed out for voice=%s (run=%s)",
                    session_id,
                    voice_name,
                    run_id,
                )
            except Exception as warm_exc:
                logger.warning(
                    "[%s] TTS warm-up failed for voice=%s: %s (run=%s)",
                    session_id,
                    voice_name,
                    warm_exc,
                    run_id,
                )
        
        # Synthesize audio
        async def _synthesize() -> bytes:
            loop = asyncio.get_running_loop()
            executor = getattr(ws.app.state, "speech_executor", None)
            synth_partial = partial(
                synth.synthesize_to_pcm,
                text=text,
                voice=voice_name,
                sample_rate=TTS_SAMPLE_RATE_UI,
                style=style,
                rate=eff_rate,
            )
            if executor:
                return await loop.run_in_executor(executor, synth_partial)
            return await loop.run_in_executor(None, synth_partial)
        
        synthesis_task = asyncio.create_task(_synthesize())
        cancel_wait: Optional[asyncio.Task] = None
        
        try:
            if cancel_event:
                cancel_wait = asyncio.create_task(cancel_event.wait())
                done, _ = await asyncio.wait(
                    {synthesis_task, cancel_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                
                if cancel_wait in done and cancel_event.is_set():
                    synthesis_task.cancel()
                    logger.info("[%s] TTS synthesis cancelled (run=%s)", session_id, run_id)
                    cancel_event.clear()
                    return
            
            pcm_bytes = await synthesis_task
            
        finally:
            if cancel_wait and not cancel_wait.done():
                cancel_wait.cancel()
        
        if not pcm_bytes:
            logger.warning("[%s] TTS returned empty audio (run=%s)", session_id, run_id)
            return
        
        # Record synthesis latency
        if latency_tool:
            try:
                if "tts:synthesis" in getattr(latency_tool, "_active_timers", set()):
                    latency_tool.stop("tts:synthesis")
                    latency_tool._active_timers.discard("tts:synthesis")
            except Exception:
                pass
        
        # Stream audio chunks to browser
        chunk_size = 4800  # 100ms at 48kHz mono 16-bit
        first_chunk_sent = False
        
        for i in range(0, len(pcm_bytes), chunk_size):
            if cancel_event and cancel_event.is_set():
                logger.info("[%s] TTS streaming cancelled (run=%s)", session_id, run_id)
                cancel_event.clear()
                break
            
            chunk = pcm_bytes[i:i + chunk_size]
            b64_chunk = base64.b64encode(chunk).decode("utf-8")
            
            await ws.send_json({
                "type": "audio",
                "data": b64_chunk,
                "sampleRate": TTS_SAMPLE_RATE_UI,
                "format": "pcm16",
            })
            
            if not first_chunk_sent:
                first_chunk_sent = True
                if on_first_audio:
                    try:
                        on_first_audio()
                    except Exception:
                        pass
            
            # Small yield to allow cancel checks
            await asyncio.sleep(0)
        
        # Record total TTS latency
        if latency_tool:
            try:
                if "tts" in getattr(latency_tool, "_active_timers", set()):
                    latency_tool.stop("tts")
                    latency_tool._active_timers.discard("tts")
            except Exception:
                pass
        
        logger.debug(
            "[%s] TTS complete: %d bytes, voice=%s (run=%s)",
            session_id,
            len(pcm_bytes),
            voice_name,
            run_id,
        )
        
    except asyncio.CancelledError:
        logger.debug("[%s] TTS task cancelled (run=%s)", session_id, run_id)
        raise
    except Exception as e:
        logger.error("[%s] TTS synthesis failed (run=%s): %s", session_id, run_id, e)
    finally:
        _set_connection_metadata(ws, "is_synthesizing", False)
        _set_connection_metadata(ws, "audio_playing", False)
        
        if temp_synth and synth:
            try:
                # Use release_for_session with None to avoid returning to warm pool
                # since temp synth may have accumulated session state
                await ws.app.state.tts_pool.release_for_session(None, synth)
            except Exception:
                pass


async def send_tts_to_acs(
    text: str,
    ws: WebSocket,
    voice_name: str,
    voice_style: Optional[str] = None,
    voice_rate: Optional[str] = None,
    stream_mode: Any = None,
    blocking: bool = True,
    latency_tool: Optional[LatencyTool] = None,
    on_first_audio: Optional[Callable[[], None]] = None,
) -> None:
    """
    Send TTS audio to ACS WebSocket.
    
    Voice configuration MUST be provided - no fallback to environment variables.
    
    Args:
        text: Text to synthesize
        ws: WebSocket connection
        voice_name: Azure TTS voice name (REQUIRED)
        voice_style: Voice style
        voice_rate: Voice rate
        stream_mode: ACS stream mode
        blocking: Whether to wait for playback completion
        latency_tool: Optional latency tracking
        on_first_audio: Callback when first audio is sent
    """
    run_id = str(uuid.uuid4())[:8]
    session_id = getattr(ws.state, "session_id", None)
    
    if not voice_name:
        logger.error(
            "[%s] ACS TTS called without voice_name - agent config missing? (run=%s)",
            session_id,
            run_id,
        )
        return
    
    style = voice_style or "conversational"
    eff_rate = voice_rate or "medium"
    
    logger.debug(
        "[%s] ACS TTS: voice=%s style=%s rate=%s (run=%s)",
        session_id,
        voice_name,
        style,
        eff_rate,
        run_id,
    )
    
    # Acquire TTS synthesizer
    synth = None
    client_tier = None
    temp_synth = None  # Track if we acquired a temp synth that needs releasing
    
    try:
        synth, client_tier = await ws.app.state.tts_pool.acquire_for_session(session_id)
    except Exception as e:
        logger.error("[%s] Failed to get TTS client for ACS (run=%s): %s", session_id, run_id, e)
    
    if not synth:
        synth = _get_connection_metadata(ws, "tts_client")
        if not synth:
            try:
                synth = await ws.app.state.tts_pool.acquire(timeout=2.0)
                temp_synth = synth  # Mark as temp synth needing release
            except Exception as e:
                logger.error("[%s] TTS pool exhausted for ACS (run=%s): %s", session_id, run_id, e)
                return
    
    try:
        # Synthesize audio
        loop = asyncio.get_running_loop()
        executor = getattr(ws.app.state, "speech_executor", None)
        
        synth_partial = partial(
            synth.synthesize_to_pcm,
            text=text,
            voice=voice_name,
            sample_rate=TTS_SAMPLE_RATE_ACS,
            style=style,
            rate=eff_rate,
        )
        
        if executor:
            pcm_bytes = await loop.run_in_executor(executor, synth_partial)
        else:
            pcm_bytes = await loop.run_in_executor(None, synth_partial)
        
        if not pcm_bytes:
            logger.warning("[%s] ACS TTS returned empty audio (run=%s)", session_id, run_id)
            return
        
        # Stream to ACS
        chunk_size = 640  # 40ms at 16kHz mono 16-bit
        first_chunk_sent = False
        
        for i in range(0, len(pcm_bytes), chunk_size):
            chunk = pcm_bytes[i:i + chunk_size]
            b64_chunk = base64.b64encode(chunk).decode("utf-8")
            
            await ws.send_json({
                "kind": "AudioData",
                "audioData": {
                    "data": b64_chunk,
                    "timestamp": None,
                    "participantRawID": None,
                    "silent": False,
                },
            })
            
            if not first_chunk_sent:
                first_chunk_sent = True
                if on_first_audio:
                    try:
                        on_first_audio()
                    except Exception:
                        pass
            
            if blocking:
                # Pace audio to match playback rate
                await asyncio.sleep(0.04)  # 40ms per chunk
            else:
                await asyncio.sleep(0)
        
        logger.debug(
            "[%s] ACS TTS complete: %d bytes, voice=%s (run=%s)",
            session_id,
            len(pcm_bytes),
            voice_name,
            run_id,
        )
        
    except Exception as e:
        logger.error("[%s] ACS TTS failed (run=%s): %s", session_id, run_id, e)
    finally:
        # Release temp synth if we acquired one
        if temp_synth:
            try:
                await ws.app.state.tts_pool.release_for_session(None, temp_synth)
            except Exception as e:
                logger.warning("[%s] Failed to release temp TTS synth (run=%s): %s", session_id, run_id, e)


__all__ = [
    "send_tts_to_browser",
    "send_tts_to_acs",
]
