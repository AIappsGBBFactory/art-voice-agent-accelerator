"""
Browser WebSocket Media Handler.
=================================

Unified handler for browser-based voice conversations supporting:
- Voice Live SDK (built-in VAD, STT, and AOAI orchestration)
- Speech Cascade (3-thread speech processing with Speech SDK)

This handler follows the ACSMediaHandler pattern where factory methods handle
ALL session setup including resource acquisition, callback wiring, and greeting.

Architecture:
    WebSocket Endpoint (realtime.py)
           │
           ▼
    MediaHandler.create_*()  ← Factory handles ALL setup
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
  Voice       Speech
   Live       Cascade
  Handler     Handler

Usage:
    # Voice Live mode:
    handler = await MediaHandler.create_voice_live(config, app_state)
    await handler.run()

    # Speech Cascade mode:
    handler = await MediaHandler.create_speech_cascade(config, app_state)
    await handler.run()
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from config import GREETING
from apps.rtagent.backend.src.orchestration.artagent.orchestrator import route_turn
from apps.rtagent.backend.src.orchestration.artagent.cm_utils import cm_get, cm_set
from apps.rtagent.backend.src.ws_helpers.barge_in import (
    BargeInController as LegacyBargeInController,
)
from apps.rtagent.backend.src.ws_helpers.envelopes import (
    make_envelope,
    make_event_envelope,
    make_status_envelope,
)
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
    _get_connection_metadata,
    _set_connection_metadata,
    send_tts_audio,
)
from apps.rtagent.backend.src.helpers import check_for_stopwords
from src.pools.session_manager import SessionContext
from src.stateful.state_managment import MemoManager
from src.tools.latency_tool import LatencyTool
from utils.ml_logging import get_logger

from .voice_live_sdk_handler import VoiceLiveSDKHandler

if TYPE_CHECKING:
    pass

logger = get_logger("api.v1.handlers.media_handler")
tracer = trace.get_tracer(__name__)

# ============================================================================
# Audio Utilities & Constants
# ============================================================================

RMS_SILENCE_THRESHOLD: int = 300
SILENCE_GAP_MS: int = 500
VOICE_LIVE_PCM_SAMPLE_RATE: int = 24000
VOICE_LIVE_SPEECH_RMS_THRESHOLD: int = 200
VOICE_LIVE_SILENCE_GAP_SECONDS: float = 0.5

_STATE_SENTINEL = object()


def pcm16le_rms(pcm_bytes: bytes) -> float:
    """
    Calculate RMS of PCM16LE audio for silence detection.

    Args:
        pcm_bytes: Raw PCM16 little-endian audio bytes.

    Returns:
        RMS value. Higher values = louder audio.
    """
    if len(pcm_bytes) < 2:
        return 0.0
    sample_count = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm_bytes[: sample_count * 2])
    sum_sq = sum(s * s for s in samples)
    return (sum_sq / sample_count) ** 0.5 if sample_count else 0.0


# ============================================================================
# Handler Mode Enum
# ============================================================================


class MediaHandlerMode(str, Enum):
    """Mode for MediaHandler audio processing."""

    VOICE_LIVE = "voice_live"
    SPEECH_CASCADE = "speech_cascade"


# ============================================================================
# Configuration Dataclass
# ============================================================================


@dataclass
class MediaHandlerConfig:
    """
    Configuration for MediaHandler creation.

    Attributes:
        session_id: Unique session identifier for correlation.
        websocket: Active WebSocket connection.
        conn_id: Connection manager ID.
        user_email: Optional user email for profile loading.
        orchestrator: Optional custom orchestrator function.
    """

    session_id: str
    websocket: WebSocket
    conn_id: str
    user_email: Optional[str] = None
    orchestrator: Optional[Callable] = None


# ============================================================================
# MediaHandler - Main Class
# ============================================================================


class MediaHandler:
    """
    Unified browser WebSocket media handler.

    Factory methods handle ALL session setup including:
    - Resource pool acquisition (STT/TTS)
    - Barge-in controller setup
    - STT callback wiring
    - Greeting synthesis

    This keeps the endpoint focused only on WebSocket lifecycle.
    """

    def __init__(
        self,
        config: MediaHandlerConfig,
        mode: MediaHandlerMode,
        memory_manager: MemoManager,
    ) -> None:
        """
        Initialize MediaHandler (use factory methods instead).

        Args:
            config: Handler configuration.
            mode: Processing mode (voice_live or speech_cascade).
            memory_manager: Conversation state manager.
        """
        self.config = config
        self.mode = mode
        self._websocket = config.websocket
        self._session_id = config.session_id
        self._conn_id = config.conn_id
        self.memory_manager = memory_manager

        # Mode-specific handlers (set by factory methods)
        self._voice_live_handler: Optional[VoiceLiveSDKHandler] = None

        # Resources (set by factory methods for Speech Cascade)
        self._tts_client: Any = None
        self._stt_client: Any = None
        self._latency_tool: Optional[LatencyTool] = None
        self._barge_in_controller: Optional[LegacyBargeInController] = None
        self._tts_cancel_event: Optional[asyncio.Event] = None
        self._orchestration_tasks: set = set()

        # State
        self._running = False
        self._greeting_sent = False
        self._user_buffer = ""

    # ------------------------------------------------------------------------
    # Factory: Voice Live SDK
    # ------------------------------------------------------------------------

    @classmethod
    async def create_voice_live(
        cls,
        config: MediaHandlerConfig,
        app_state: Any,
    ) -> "MediaHandler":
        """
        Create MediaHandler for Voice Live SDK mode.

        Handles ALL setup:
        1. Creates MemoManager from Redis
        2. Sets up session context
        3. Creates VoiceLiveSDKHandler
        4. Configures barge-in controller

        Args:
            config: Handler configuration.
            app_state: FastAPI app.state with redis, conn_manager, etc.

        Returns:
            Configured MediaHandler ready for run().
        """
        redis_mgr = app_state.redis
        memory_manager = MemoManager.from_redis(config.session_id, redis_mgr)

        handler = cls(config, MediaHandlerMode.VOICE_LIVE, memory_manager)

        # Set up session context on websocket state
        session_context = SessionContext(
            session_id=config.session_id,
            memory_manager=memory_manager,
            websocket=config.websocket,
        )
        config.websocket.state.session_context = session_context
        config.websocket.state.cm = memory_manager
        config.websocket.state.session_id = config.session_id

        # Initialize cancel event
        handler._tts_cancel_event = asyncio.Event()
        try:
            config.websocket.state._loop = asyncio.get_running_loop()
        except RuntimeError:
            config.websocket.state._loop = None

        # Set metadata on session context
        metadata = {
            "cm": memory_manager,
            "session_id": config.session_id,
            "stream_mode": "voice_live",
            "greeting_sent": True,  # Voice Live handles its own greeting
            "tts_client": None,
            "lt": None,
            "is_synthesizing": False,
            "audio_playing": False,
            "tts_cancel_requested": False,
            "tts_cancel_event": handler._tts_cancel_event,
        }
        for key, value in metadata.items():
            session_context.set_metadata_nowait(key, value)
            setattr(config.websocket.state, key, value)

        # Set up barge-in controller
        handler._setup_barge_in_controller(app_state, metadata)

        # Create Voice Live handler
        handler._voice_live_handler = VoiceLiveSDKHandler(
            websocket=config.websocket,
            session_id=config.session_id,
            call_connection_id=config.session_id,
            transport="realtime",
            user_email=config.user_email,
        )

        logger.info(
            "MediaHandler created (Voice Live mode)",
            extra={"session_id": config.session_id},
        )
        return handler

    # ------------------------------------------------------------------------
    # Factory: Speech Cascade
    # ------------------------------------------------------------------------

    @classmethod
    async def create_speech_cascade(
        cls,
        config: MediaHandlerConfig,
        app_state: Any,
    ) -> "MediaHandler":
        """
        Create MediaHandler for Speech Cascade mode.

        Handles ALL setup:
        1. Creates MemoManager from Redis
        2. Acquires STT/TTS from pools
        3. Sets up session context
        4. Configures barge-in controller
        5. Wires STT callbacks
        6. Starts STT recognizer
        7. Sends greeting if needed

        Args:
            config: Handler configuration.
            app_state: FastAPI app.state with redis, pools, conn_manager, etc.

        Returns:
            Configured MediaHandler ready for run().
        """
        from fastapi import WebSocketDisconnect

        redis_mgr = app_state.redis
        memory_manager = MemoManager.from_redis(config.session_id, redis_mgr)

        handler = cls(config, MediaHandlerMode.SPEECH_CASCADE, memory_manager)

        # Acquire TTS client from pool
        tts_pool = app_state.tts_pool
        try:
            tts_client, tts_tier = await tts_pool.acquire_for_session(config.session_id)
            handler._tts_client = tts_client
        except TimeoutError as exc:
            logger.error("[%s] TTS pool acquire timeout", config.session_id)
            if config.websocket.client_state == WebSocketState.CONNECTED:
                try:
                    await config.websocket.close(
                        code=1013, reason="TTS capacity temporarily unavailable"
                    )
                except Exception:
                    pass
            raise WebSocketDisconnect(code=1013) from exc

        # Acquire STT client from pool
        stt_pool = app_state.stt_pool
        try:
            stt_client, stt_tier = await stt_pool.acquire_for_session(config.session_id)
            handler._stt_client = stt_client
        except TimeoutError as exc:
            logger.error("[%s] STT pool acquire timeout", config.session_id)
            if config.websocket.client_state == WebSocketState.CONNECTED:
                try:
                    await config.websocket.close(
                        code=1013, reason="STT capacity temporarily unavailable"
                    )
                except Exception:
                    pass
            raise WebSocketDisconnect(code=1013) from exc

        logger.info(
            "[%s] Acquired STT (tier=%s) and TTS (tier=%s)",
            config.session_id,
            stt_tier,
            tts_tier,
        )

        # Set up session context
        session_context = SessionContext(
            session_id=config.session_id,
            memory_manager=memory_manager,
            websocket=config.websocket,
        )
        config.websocket.state.session_context = session_context

        # Create latency tool
        handler._latency_tool = LatencyTool(memory_manager)

        # Initialize state
        handler._tts_cancel_event = asyncio.Event()
        greeting_sent = memory_manager.get_value_from_corememory("greeting_sent", False)
        handler._greeting_sent = greeting_sent
        handler._orchestration_tasks = set()

        try:
            config.websocket.state._loop = asyncio.get_running_loop()
        except RuntimeError:
            config.websocket.state._loop = None

        # Build metadata
        metadata = {
            "cm": memory_manager,
            "session_id": config.session_id,
            "tts_client": tts_client,
            "stt_client": stt_client,
            "lt": handler._latency_tool,
            "is_synthesizing": False,
            "audio_playing": False,
            "tts_cancel_requested": False,
            "tts_cancel_event": handler._tts_cancel_event,
            "greeting_sent": greeting_sent,
            "user_buffer": "",
            "orchestration_tasks": handler._orchestration_tasks,
        }
        for key, value in metadata.items():
            session_context.set_metadata_nowait(key, value)
            setattr(config.websocket.state, key, value)

        # Set up barge-in controller
        handler._setup_barge_in_controller(app_state, metadata)

        # Set up STT callbacks
        handler._setup_stt_callbacks(app_state, metadata)

        # Start STT
        try:
            stt_client.set_call_connection_id(config.session_id)
        except Exception:
            pass
        stt_client.start()

        # Send greeting if needed
        await handler._send_greeting_if_needed(app_state)

        # Persist initial state
        await memory_manager.persist_to_redis_async(redis_mgr)

        logger.info(
            "MediaHandler created (Speech Cascade mode)",
            extra={"session_id": config.session_id},
        )
        return handler

    # ------------------------------------------------------------------------
    # Setup Helpers
    # ------------------------------------------------------------------------

    def _setup_barge_in_controller(
        self,
        app_state: Any,
        metadata: dict,
    ) -> None:
        """Set up barge-in controller for TTS interruption."""
        websocket = self._websocket

        def get_metadata(key: str, default=None):
            return _get_connection_metadata(websocket, key, default)

        def set_metadata(key: str, value):
            if not _set_connection_metadata(websocket, key, value):
                setattr(websocket.state, key, value)

        def signal_tts_cancel():
            cancel_event = get_metadata("tts_cancel_event")
            if not cancel_event:
                return
            loop = getattr(websocket.state, "_loop", None)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(cancel_event.set)
            else:
                try:
                    cancel_event.set()
                except Exception:
                    pass

        self._barge_in_controller = LegacyBargeInController(
            websocket=websocket,
            session_id=self._session_id,
            conn_id=self._conn_id,
            get_metadata=get_metadata,
            set_metadata=set_metadata,
            signal_tts_cancel=signal_tts_cancel,
            logger=logger,
        )
        websocket.state.barge_in_controller = self._barge_in_controller
        metadata["request_barge_in"] = self._barge_in_controller.request
        set_metadata("request_barge_in", self._barge_in_controller.request)

    def _setup_stt_callbacks(
        self,
        app_state: Any,
        metadata: dict,
    ) -> None:
        """Configure STT callbacks for partial/final results."""
        websocket = self._websocket
        session_id = self._session_id
        conn_id = self._conn_id
        stt_client = self._stt_client

        def get_metadata(key: str, default=None):
            return _get_connection_metadata(websocket, key, default)

        def set_metadata(key: str, value):
            if not _set_connection_metadata(websocket, key, value):
                setattr(websocket.state, key, value)

        def set_metadata_threadsafe(key: str, value):
            loop = getattr(websocket.state, "_loop", None)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(set_metadata, key, value)
            else:
                set_metadata(key, value)

        def signal_tts_cancel():
            cancel_event = get_metadata("tts_cancel_event")
            if cancel_event:
                loop = getattr(websocket.state, "_loop", None)
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(cancel_event.set)

        def on_partial(txt: str, lang: str, speaker_id: str):
            if not txt or not txt.strip():
                return
            txt = txt.strip()
            logger.info("[%s] User (partial): %s", session_id, txt)

            # Send partial to frontend
            partial_payload = {
                "type": "streaming",
                "streaming_type": "stt_partial",
                "content": txt,
                "language": lang,
                "session_id": session_id,
                "is_final": False,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            partial_envelope = make_event_envelope(
                event_type="stt_partial",
                event_data=partial_payload,
                sender="STT",
                topic="session",
                session_id=session_id,
            )

            conn_manager = getattr(app_state, "conn_manager", None)
            loop = getattr(websocket.state, "_loop", None)
            if conn_manager and loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    conn_manager.send_to_connection(conn_id, partial_envelope),
                    loop,
                )

            # Trigger barge-in if TTS is playing
            request_barge_in = get_metadata("request_barge_in")
            is_synth = get_metadata("is_synthesizing", False)
            audio_playing = get_metadata("audio_playing", False)

            if is_synth or audio_playing:
                signal_tts_cancel()
                set_metadata_threadsafe("tts_cancel_requested", True)
                set_metadata_threadsafe("audio_playing", False)
                set_metadata_threadsafe("is_synthesizing", False)

            if callable(request_barge_in):
                request_barge_in("stt_partial", "partial")

        def on_final(txt: str, lang: str, speaker_id: Optional[str] = None):
            logger.info("[%s] User (final): %s", session_id, txt)
            current_buffer = get_metadata("user_buffer", "")
            set_metadata("user_buffer", current_buffer + txt.strip() + "\n")

        def on_cancel(evt):
            try:
                details = getattr(evt.result, "cancellation_details", None)
                reason = getattr(details, "reason", None) if details else None
                logger.warning("[%s] STT cancellation: %s", session_id, reason)
            except Exception:
                pass

        stt_client.set_partial_result_callback(on_partial)
        stt_client.set_final_result_callback(on_final)
        stt_client.set_cancel_callback(on_cancel)

    async def _send_greeting_if_needed(self, app_state: Any) -> None:
        """Send greeting TTS if not already sent."""
        if self._greeting_sent:
            # Resume message
            active_agent = cm_get(self.memory_manager, "active_agent", None)
            active_agent_voice = cm_get(self.memory_manager, "active_agent_voice", None)
            voice_name = (
                active_agent_voice.get("voice")
                if isinstance(active_agent_voice, dict)
                else active_agent_voice
            )

            resume_text = (
                f'Specialist "{active_agent}" is ready to continue assisting you.'
                if active_agent
                else "Session resumed with your previous assistant."
            )
            await send_tts_audio(
                resume_text,
                self._websocket,
                latency_tool=self._latency_tool,
                voice_name=voice_name,
            )

            resume_envelope = make_status_envelope(
                resume_text,
                sender=active_agent or "System",
                topic="session",
                session_id=self._session_id,
            )
            await app_state.conn_manager.send_to_connection(
                self._conn_id, resume_envelope
            )
        else:
            # Send greeting
            greeting_envelope = make_status_envelope(
                GREETING,
                sender="System",
                topic="session",
                session_id=self._session_id,
            )
            await app_state.conn_manager.send_to_connection(
                self._conn_id, greeting_envelope
            )

            # Add to history
            auth_agent = app_state.auth_agent
            self.memory_manager.append_to_history(auth_agent.name, "assistant", GREETING)

            # Send TTS
            await send_tts_audio(
                GREETING, self._websocket, latency_tool=self._latency_tool
            )

            # Persist
            _set_connection_metadata(self._websocket, "greeting_sent", True)
            cm_set(self.memory_manager, greeting_sent=True)
            self._greeting_sent = True

    # ------------------------------------------------------------------------
    # Main Run Method
    # ------------------------------------------------------------------------

    async def run(self, app_state: Any) -> None:
        """
        Run the handler message loop until connection closes.

        Args:
            app_state: FastAPI app.state for connection manager access.
        """
        self._running = True
        try:
            if self.mode == MediaHandlerMode.VOICE_LIVE:
                await self._run_voice_live(app_state)
            else:
                await self._run_speech_cascade(app_state)
        finally:
            self._running = False

    # ------------------------------------------------------------------------
    # Voice Live Processing
    # ------------------------------------------------------------------------

    async def _run_voice_live(self, app_state: Any) -> None:
        """Process Voice Live messages."""
        from fastapi import WebSocketDisconnect

        handler = self._voice_live_handler
        speech_active = False
        silence_started_at: Optional[float] = None

        with tracer.start_as_current_span(
            "media_handler.run_voice_live",
            attributes={"session_id": self._session_id},
        ) as span:
            try:
                await handler.start()
                self._websocket.state.voice_live_handler = handler

                # Register handler in connection metadata
                conn_meta = await app_state.conn_manager.get_connection_meta(
                    self._conn_id
                )
                if conn_meta:
                    if not conn_meta.handler:
                        conn_meta.handler = {}
                    conn_meta.handler["voice_live_handler"] = handler

                # Send readiness status
                try:
                    ready_envelope = make_status_envelope(
                        "Voice Live orchestration connected",
                        sender="System",
                        topic="session",
                        session_id=self._session_id,
                    )
                    await app_state.conn_manager.send_to_connection(
                        self._conn_id, ready_envelope
                    )
                except Exception:
                    logger.debug(
                        "[%s] Unable to send Voice Live readiness status",
                        self._session_id,
                    )

                # Message processing loop
                while self._is_connected():
                    raw_message = await self._websocket.receive()
                    msg_type = raw_message.get("type")

                    if msg_type in {"websocket.close", "websocket.disconnect"}:
                        raise WebSocketDisconnect(code=raw_message.get("code", 1000))

                    if msg_type != "websocket.receive":
                        continue

                    # Handle audio bytes
                    audio_bytes = raw_message.get("bytes")
                    if audio_bytes:
                        await handler.handle_pcm_chunk(
                            audio_bytes, sample_rate=VOICE_LIVE_PCM_SAMPLE_RATE
                        )

                        # RMS-based speech detection
                        rms_value = pcm16le_rms(audio_bytes)
                        now = time.perf_counter()

                        if rms_value >= VOICE_LIVE_SPEECH_RMS_THRESHOLD:
                            speech_active = True
                            silence_started_at = None
                        elif speech_active:
                            if silence_started_at is None:
                                silence_started_at = now
                            elif now - silence_started_at >= VOICE_LIVE_SILENCE_GAP_SECONDS:
                                await handler.commit_audio_buffer()
                                speech_active = False
                                silence_started_at = None
                        continue

                    # Handle text messages
                    text_payload = raw_message.get("text")
                    if text_payload and text_payload.strip():
                        try:
                            payload = json.loads(text_payload)
                            kind = payload.get("kind") or payload.get("type")
                            if kind == "StopAudio":
                                await handler.commit_audio_buffer()
                        except json.JSONDecodeError:
                            await handler.send_text_message(text_payload)

                span.set_status(Status(StatusCode.OK))

            except WebSocketDisconnect:
                raise
            except Exception as exc:
                logger.error(
                    "[%s] Voice Live error: %s", self._session_id, exc, exc_info=True
                )
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            finally:
                if speech_active:
                    try:
                        await handler.commit_audio_buffer()
                    except Exception:
                        pass
                await handler.stop()
                if (
                    getattr(self._websocket.state, "voice_live_handler", None)
                    is handler
                ):
                    self._websocket.state.voice_live_handler = None

    # ------------------------------------------------------------------------
    # Speech Cascade Processing
    # ------------------------------------------------------------------------

    async def _run_speech_cascade(self, app_state: Any) -> None:
        """Process Speech Cascade messages."""
        from fastapi import WebSocketDisconnect

        with tracer.start_as_current_span(
            "media_handler.run_speech_cascade",
            attributes={"session_id": self._session_id},
        ) as span:
            try:
                session_context = getattr(self._websocket.state, "session_context", None)

                def get_metadata(key: str, default=None):
                    if session_context:
                        value = session_context.get_metadata_nowait(key, _STATE_SENTINEL)
                        if value is not _STATE_SENTINEL:
                            return value
                    return _get_connection_metadata(self._websocket, key, default)

                def set_metadata(key: str, value):
                    if session_context:
                        session_context.set_metadata_nowait(key, value)
                    if not _set_connection_metadata(self._websocket, key, value):
                        setattr(self._websocket.state, key, value)

                message_count = 0
                while self._is_connected():
                    msg = await self._websocket.receive()
                    message_count += 1

                    msg_type = msg.get("type")
                    if msg_type == "websocket.disconnect":
                        break

                    if msg_type != "websocket.receive":
                        continue

                    # Handle text input
                    text_data = msg.get("text")
                    if text_data is not None:
                        set_metadata(
                            "user_buffer", get_metadata("user_buffer", "") + text_data + "\n"
                        )

                    # Handle audio bytes
                    audio_bytes = msg.get("bytes")
                    if audio_bytes:
                        stt_client = get_metadata("stt_client")
                        if stt_client and getattr(stt_client, "push_stream", None):
                            try:
                                stt_client.write_bytes(audio_bytes)
                            except Exception as e:
                                logger.error(
                                    "[%s] STT write error: %s", self._session_id, e
                                )

                    # Process user buffer
                    user_buffer = get_metadata("user_buffer", "")
                    if user_buffer.strip():
                        prompt = user_buffer.strip()
                        set_metadata("user_buffer", "")

                        # Broadcast user message
                        user_envelope = make_envelope(
                            etype="event",
                            sender="User",
                            payload={"sender": "User", "message": prompt},
                            topic="session",
                            session_id=self._session_id,
                        )
                        await app_state.conn_manager.broadcast_session(
                            self._session_id, user_envelope
                        )

                        # Check stopwords
                        if check_for_stopwords(prompt):
                            goodbye = "Thank you for using our service. Goodbye."
                            goodbye_envelope = make_envelope(
                                etype="exit",
                                sender="System",
                                payload={"type": "exit", "message": goodbye},
                                topic="session",
                                session_id=self._session_id,
                            )
                            await app_state.conn_manager.broadcast_session(
                                self._session_id, goodbye_envelope
                            )
                            await send_tts_audio(
                                goodbye,
                                self._websocket,
                                latency_tool=self._latency_tool,
                            )
                            break

                        # Run orchestration in background
                        async def run_orchestration():
                            try:
                                await route_turn(
                                    self.memory_manager,
                                    prompt,
                                    self._websocket,
                                    is_acs=False,
                                )
                            except Exception as e:
                                logger.error(
                                    "[%s] Orchestration error: %s", self._session_id, e
                                )
                            finally:
                                self._orchestration_tasks.discard(asyncio.current_task())

                        task = asyncio.create_task(run_orchestration())
                        self._orchestration_tasks.add(task)

                span.set_attribute("messages.processed", message_count)
                span.set_status(Status(StatusCode.OK))

            except WebSocketDisconnect:
                span.set_status(Status(StatusCode.OK, "Normal disconnect"))
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error("[%s] Speech Cascade error: %s", self._session_id, e)
                raise

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------

    def _is_connected(self) -> bool:
        """Check if WebSocket is still connected."""
        return (
            self._websocket.client_state == WebSocketState.CONNECTED
            and self._websocket.application_state == WebSocketState.CONNECTED
        )

    # ------------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------------

    async def cleanup(self, app_state: Any) -> None:
        """
        Release all resources.

        Args:
            app_state: FastAPI app.state with pools and managers.
        """
        session_id = self._session_id

        # Cancel orchestration tasks
        for task in list(self._orchestration_tasks):
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        self._orchestration_tasks.clear()

        # Release TTS client
        if self._tts_client:
            tts_pool = getattr(app_state, "tts_pool", None)
            if tts_pool:
                try:
                    self._tts_client.stop_speaking()
                    await tts_pool.release_for_session(session_id, self._tts_client)
                except Exception as e:
                    logger.error("[%s] TTS release error: %s", session_id, e)

        # Release STT client
        if self._stt_client:
            stt_pool = getattr(app_state, "stt_pool", None)
            if stt_pool:
                try:
                    self._stt_client.stop()
                    await stt_pool.release_for_session(session_id, self._stt_client)
                except Exception as e:
                    logger.error("[%s] STT release error: %s", session_id, e)

        logger.info("[%s] MediaHandler cleanup complete", session_id)

    @property
    def metadata(self) -> dict:
        """Get handler metadata for session manager registration."""
        return {
            "cm": self.memory_manager,
            "session_id": self._session_id,
            "stream_mode": str(self.mode.value),
            "greeting_sent": self._greeting_sent,
            "tts_client": self._tts_client,
            "stt_client": self._stt_client,
            "lt": self._latency_tool,
        }


__all__ = [
    "MediaHandler",
    "MediaHandlerConfig",
    "MediaHandlerMode",
    "pcm16le_rms",
    "RMS_SILENCE_THRESHOLD",
    "SILENCE_GAP_MS",
    "VOICE_LIVE_PCM_SAMPLE_RATE",
    "VOICE_LIVE_SPEECH_RMS_THRESHOLD",
    "VOICE_LIVE_SILENCE_GAP_SECONDS",
]
