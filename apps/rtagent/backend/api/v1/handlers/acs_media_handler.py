"""
ACS Media Handler - Azure Communication Services Media Processing
=================================================================

Single handler for ACS WebSocket media streaming combining:
- ACS protocol parsing (AudioMetadata, AudioData, DtmfData, StopAudio)
- Three-thread speech processing via SpeechCascadeHandler
- TTS playback coordination
- UI event emission

Architecture:
    ACS WebSocket (media.py)
           |
           v
    ACSMediaHandler (this module)
           |
           v
    SpeechCascadeHandler
           |
    +------+------+
    |      |      |
    v      v      v
   STT   Turn   Barge-In
  Thread Thread Controller
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Callable, Dict, Optional

from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from config import ACS_STREAMING_MODE, GREETING
from src.enums.stream_modes import StreamMode
from src.speech.speech_recognizer import StreamingSpeechRecognizerFromBytes
from src.stateful.state_managment import MemoManager
from src.tools.latency_tool import LatencyTool
from apps.rtagent.backend.src.ws_helpers.shared_ws import (
    send_response_to_acs,
    send_user_transcript,
    send_user_partial_transcript,
    send_session_envelope,
)
from apps.rtagent.backend.src.ws_helpers.envelopes import make_status_envelope
from apps.rtagent.backend.src.services.acs.call_transfer import (
    transfer_call as transfer_call_service,
)
from apps.rtagent.backend.src.orchestration.artagent.greetings import (
    create_personalized_greeting,
)
from utils.ml_logging import get_logger

from .speech_cascade_handler import (
    SpeechCascadeHandler,
    SpeechEvent,
    SpeechEventType,
)

logger = get_logger("v1.handlers.acs_media_handler")
tracer = trace.get_tracer(__name__)


class ACSMessageKind:
    """ACS WebSocket message types."""

    AUDIO_METADATA = "AudioMetadata"
    AUDIO_DATA = "AudioData"
    DTMF_DATA = "DtmfData"
    STOP_AUDIO = "StopAudio"


class ACSMediaHandler:
    """
    ACS Media Handler - unified handler for Azure Communication Services.

    Handles:
    - ACS WebSocket protocol (AudioMetadata, AudioData, DtmfData, StopAudio)
    - Speech recognition via SpeechCascadeHandler
    - TTS playback to ACS
    - UI event emission
    - Resource lifecycle (STT/TTS pools)
    """

    # =========================================================================
    # Factory Method
    # =========================================================================

    @classmethod
    async def create(
        cls,
        websocket: WebSocket,
        orchestrator_func: Callable,
        call_connection_id: str,
        session_id: str,
        stream_mode: StreamMode = ACS_STREAMING_MODE,
    ) -> "ACSMediaHandler":
        """
        Factory method to create an ACSMediaHandler with all resources.

        Handles:
        - Memory manager loading from Redis
        - STT/TTS pool acquisition
        - Greeting derivation
        - Latency tool setup

        Args:
            websocket: WebSocket connection for ACS media streaming.
            orchestrator_func: Orchestrator function for conversation management.
            call_connection_id: ACS call connection identifier.
            session_id: Session identifier.
            stream_mode: ACS streaming mode (MEDIA/TRANSCRIPTION).

        Returns:
            Configured ACSMediaHandler instance.

        Raises:
            Exception: When resource acquisition fails.
        """
        app_state = websocket.app.state

        # Load memory manager
        memory_manager = cls._load_memory_manager(
            app_state.redis, call_connection_id, session_id
        )

        # Initialize latency tracking
        latency_tool = LatencyTool(memory_manager)
        websocket.state.lt = latency_tool
        websocket.state.cm = memory_manager
        websocket.state.is_synthesizing = False
        latency_tool.start("greeting_ttfb")

        # Acquire STT/TTS from pools
        recognizer, stt_tier = await app_state.stt_pool.acquire_for_session(
            call_connection_id
        )
        synthesizer, tts_tier = await app_state.tts_pool.acquire_for_session(
            call_connection_id
        )

        # Store on websocket state for compatibility
        websocket.state.tts_client = synthesizer
        websocket.state.session_id = call_connection_id

        logger.info(
            "Acquired STT/TTS for call %s (stt=%s, tts=%s)",
            call_connection_id[-8:],
            getattr(stt_tier, "value", "unknown"),
            getattr(tts_tier, "value", "unknown"),
        )

        # Derive greeting
        greeting_text = cls._derive_greeting(memory_manager)

        # Create handler
        handler = cls(
            websocket=websocket,
            orchestrator_func=orchestrator_func,
            call_connection_id=call_connection_id,
            recognizer=recognizer,
            memory_manager=memory_manager,
            session_id=session_id,
            greeting_text=greeting_text,
            stream_mode=stream_mode,
        )

        # Store pool resources for cleanup
        handler._stt_client = recognizer
        handler._tts_client = synthesizer
        handler._stt_tier = stt_tier
        handler._tts_tier = tts_tier

        return handler

    @staticmethod
    def _load_memory_manager(
        redis_mgr, call_connection_id: str, session_id: str
    ) -> MemoManager:
        """Load memory manager from Redis or create new."""
        try:
            memory_manager = MemoManager.from_redis(call_connection_id, redis_mgr)
            if memory_manager is None:
                logger.warning(
                    "Memory manager from Redis returned None for %s",
                    call_connection_id[-8:],
                )
                return MemoManager(session_id=session_id)
            memory_manager.session_id = session_id
            return memory_manager
        except Exception as e:
            logger.error("Failed to load memory from Redis: %s", e)
            return MemoManager(session_id=session_id)

    @staticmethod
    def _derive_greeting(memory_manager: Optional[MemoManager]) -> str:
        """Build contextual greeting from memory, falling back to default."""
        if not memory_manager:
            return GREETING

        try:
            caller_name = (memory_manager.get_value_from_corememory("caller_name", "") or "").strip()
            active_agent = (memory_manager.get_value_from_corememory("active_agent", "") or "").strip() or "Support"
            institution = (memory_manager.get_value_from_corememory("institution_name", "") or "").strip()
            topic = (memory_manager.get_value_from_corememory("topic", "") or "").strip()

            # Check handoff context
            handoff = memory_manager.get_value_from_corememory("handoff_context", {}) or {}
            if isinstance(handoff, dict):
                topic = topic or handoff.get("issue_summary") or handoff.get("details") or ""
                institution = institution or (handoff.get("institution_name") or "").strip()

            # Try personalized greeting if customer intelligence available
            customer_intel = memory_manager.get_value_from_corememory("customer_intelligence", None)
            if customer_intel:
                return create_personalized_greeting(
                    caller_name=caller_name or None,
                    agent_name=active_agent,
                    customer_intelligence=customer_intel,
                    institution_name=institution or "our team",
                    topic=topic or "your account",
                )

            # Simple contextual greeting
            name = caller_name.split()[0] if caller_name else "there"
            topic_clause = f"I understand you're calling about {topic}. " if topic else ""
            inst_clause = f" with {institution}" if institution else ""
            return f"Hi {name}, you're speaking with our {active_agent} specialist{inst_clause}. {topic_clause}How can I help you today?"

        except Exception:
            logger.debug("Falling back to default greeting", exc_info=True)
            return GREETING

    # =========================================================================
    # Constructor
    # =========================================================================

    def __init__(
        self,
        websocket: WebSocket,
        orchestrator_func: Callable,
        call_connection_id: str,
        recognizer: Optional[StreamingSpeechRecognizerFromBytes] = None,
        memory_manager: Optional[MemoManager] = None,
        session_id: Optional[str] = None,
        greeting_text: str = GREETING,
        stream_mode: StreamMode = ACS_STREAMING_MODE,
    ):
        """
        Initialize ACS Media Handler.

        Args:
            websocket: WebSocket connection for ACS media streaming.
            orchestrator_func: Orchestrator function for conversation management.
            call_connection_id: ACS call connection identifier.
            recognizer: Speech recognition client instance.
            memory_manager: Memory manager for conversation state.
            session_id: Session identifier.
            greeting_text: Text for greeting playback.
            stream_mode: ACS streaming mode (MEDIA/TRANSCRIPTION).
        """
        self.websocket = websocket
        self.call_connection_id = call_connection_id or "unknown"
        self._call_short = call_connection_id[-8:] if call_connection_id else "unknown"
        self.session_id = session_id or call_connection_id
        self.memory_manager = memory_manager
        self.greeting_text = greeting_text
        self.stream_mode = stream_mode or ACS_STREAMING_MODE

        # Store call connection ID on websocket for compatibility
        if call_connection_id:
            setattr(self.websocket, "_call_connection_id", call_connection_id)

        # Ensure stream_mode is accessible to downstream helpers
        try:
            self.websocket.state.stream_mode = self.stream_mode
        except Exception:
            logger.debug(f"[{self._call_short}] Unable to persist stream_mode on websocket state")

        # Initialize speech cascade handler for processing
        self.speech_cascade = SpeechCascadeHandler(
            connection_id=call_connection_id,
            orchestrator_func=self._create_orchestrator_wrapper(orchestrator_func),
            recognizer=recognizer,
            memory_manager=memory_manager,
            on_barge_in=self._on_barge_in,
            on_greeting=self._on_greeting,
            on_announcement=self._on_announcement,
            on_partial_transcript=self._on_partial_transcript,
            on_user_transcript=self._on_user_transcript,
            on_tts_request=self._on_tts_request,
        )

        # ACS protocol state
        self._metadata_received = False
        self._audio_sequence = 0

        # Lifecycle
        self.running = False
        self._stopped = False
        self._greeting_played = False

        # Pool resources (set by factory, None if created directly)
        self._stt_client: Optional[StreamingSpeechRecognizerFromBytes] = None
        self._tts_client = None
        self._stt_tier = None
        self._tts_tier = None

        # Store handler reference on websocket for compatibility
        websocket._acs_media_handler = self

    def _create_orchestrator_wrapper(self, orchestrator_func: Callable) -> Callable:
        """Wrap orchestrator function to inject ACS-specific parameters."""

        async def wrapped_orchestrator(cm: MemoManager, transcript: str):
            return await orchestrator_func(
                cm=cm,
                transcript=transcript,
                ws=self.websocket,
                call_id=self.call_connection_id,
                is_acs=True,
            )

        return wrapped_orchestrator

    # =========================================================================
    # ACS Protocol Handling
    # =========================================================================

    async def handle_media_message(self, raw_message: str) -> None:
        """
        Handle incoming ACS WebSocket message.

        Args:
            raw_message: Raw JSON string from ACS WebSocket.
        """
        try:
            data = json.loads(raw_message)
            if not isinstance(data, dict):
                logger.warning(f"[{self._call_short}] Ignoring non-object ACS payload")
                return
        except json.JSONDecodeError as e:
            logger.error(f"[{self._call_short}] Invalid ACS JSON: {e}")
            return

        kind = data.get("kind")
        if not kind:
            logger.debug(f"[{self._call_short}] ACS payload missing 'kind' field")
            return

        if kind == ACSMessageKind.AUDIO_METADATA:
            await self._handle_audio_metadata(data)
        elif kind == ACSMessageKind.AUDIO_DATA:
            await self._handle_audio_data(data)
        elif kind == ACSMessageKind.DTMF_DATA:
            await self._handle_dtmf_data(data)
        else:
            logger.debug(f"[{self._call_short}] Unhandled ACS message kind: {kind}")

    async def _handle_audio_metadata(self, data: Dict[str, Any]) -> None:
        """Handle AudioMetadata message - start recognizer and greeting."""
        logger.debug(f"[{self._call_short}] AudioMetadata received")
        self._metadata_received = True

        # Start recognizer if not already started
        if self.speech_cascade.speech_sdk_thread:
            self.speech_cascade.speech_sdk_thread.start_recognizer()

        # Queue greeting if not played yet
        if not self._greeting_played and self.greeting_text:
            self.speech_cascade.queue_greeting(self.greeting_text)
            self._greeting_played = True

    async def _handle_audio_data(self, data: Dict[str, Any]) -> None:
        """Handle AudioData message - forward to speech recognizer."""
        audio_section = data.get("audioData") or data.get("AudioData") or {}
        is_silent = audio_section.get("silent", True)

        if is_silent:
            return

        audio_b64 = audio_section.get("data")
        if not audio_b64:
            return

        try:
            audio_bytes = base64.b64decode(audio_b64)
            self.speech_cascade.write_audio(audio_bytes)
        except Exception as e:
            logger.error(f"[{self._call_short}] Failed to decode audio: {e}")

    async def _handle_dtmf_data(self, data: Dict[str, Any]) -> None:
        """Handle DtmfData message."""
        dtmf_section = data.get("dtmfData") or data.get("DtmfData") or {}
        tone = dtmf_section.get("data")

        if tone:
            logger.info(f"[{self._call_short}] DTMF tone: {tone}")
            # DTMF handling delegated to DTMFValidationLifecycle via event handlers

    async def send_stop_audio(self) -> bool:
        """Send StopAudio command to ACS."""
        if not self._is_connected():
            return False

        try:
            await self.websocket.send_json({
                "kind": ACSMessageKind.STOP_AUDIO,
                "AudioData": None,
                "StopAudio": {},
            })
            logger.debug(f"[{self._call_short}] StopAudio sent")
            return True
        except Exception as e:
            if self._is_connected():
                logger.warning(f"[{self._call_short}] Failed to send StopAudio: {e}")
            return False

    def _is_connected(self) -> bool:
        """Check if WebSocket is still connected."""
        return (
            self.websocket.client_state == WebSocketState.CONNECTED
            and self.websocket.application_state == WebSocketState.CONNECTED
        )

    # =========================================================================
    # Speech Cascade Callbacks
    # =========================================================================

    async def _on_barge_in(self) -> None:
        """Handle barge-in - send stop audio to ACS."""
        await self.send_stop_audio()

    async def _on_greeting(self, event: SpeechEvent) -> None:
        """Handle greeting event - play via ACS TTS."""
        await self._play_text_to_acs(event, is_greeting=True)

    async def _on_announcement(self, event: SpeechEvent) -> None:
        """Handle announcement event - play via ACS TTS."""
        await self._play_text_to_acs(event, is_greeting=False)

    def _on_partial_transcript(
        self, text: str, language: str, speaker_id: Optional[str]
    ) -> None:
        """Handle partial transcript - emit to UI."""
        loop = self.speech_cascade.thread_bridge.main_loop
        if loop and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    send_user_partial_transcript(
                        self.websocket,
                        text,
                        language=language,
                        speaker_id=speaker_id,
                    ),
                    loop,
                )
            except Exception as e:
                logger.debug(f"[{self._call_short}] Failed to emit partial transcript: {e}")

    async def _on_user_transcript(self, text: str) -> None:
        """Handle final user transcript - emit to UI."""
        try:
            await send_user_transcript(self.websocket, text)
        except Exception as e:
            logger.warning(f"[{self._call_short}] Failed to emit user transcript: {e}")

    async def _on_tts_request(self, text: str, event_type: SpeechEventType) -> None:
        """Handle TTS request from speech cascade."""
        is_greeting = event_type == SpeechEventType.GREETING
        event = SpeechEvent(event_type=event_type, text=text, language="en-US")
        await self._play_text_to_acs(event, is_greeting=is_greeting)

    # =========================================================================
    # TTS Playback
    # =========================================================================

    async def _play_text_to_acs(
        self, event: SpeechEvent, *, is_greeting: bool = False
    ) -> None:
        """Play text to ACS via TTS."""
        playback_type = "greeting" if is_greeting else event.event_type.value

        if not isinstance(event.text, str) or not event.text:
            logger.warning(
                f"[{self._call_short}] Skipping {playback_type} playback - invalid text"
            )
            return

        logger.debug(
            f"[{self._call_short}] Starting {playback_type} playback (len={len(event.text)})"
        )

        # Record greeting in memory
        if is_greeting and self.memory_manager:
            try:
                self._record_greeting_context(event.text)
            except Exception as e:
                logger.warning(f"[{self._call_short}] Failed to record greeting: {e}")

        # Emit to UI
        await self._emit_to_ui(event.text)

        # Send TTS to ACS
        try:
            latency_tool = getattr(self.websocket.state, "lt", None)

            # Dynamic timeout based on text length
            base_timeout = 8.0
            dynamic_timeout = max(base_timeout, len(event.text) / 15.0 + 5.0) if is_greeting else base_timeout

            playback_task = asyncio.create_task(
                send_response_to_acs(
                    ws=self.websocket,
                    text=event.text,
                    blocking=False,
                    latency_tool=latency_tool,
                    stream_mode=self.stream_mode,
                )
            )

            await asyncio.wait_for(playback_task, timeout=dynamic_timeout)

            if is_greeting:
                logger.info(f"[{self._call_short}] Greeting playback completed")

        except asyncio.TimeoutError:
            logger.error(f"[{self._call_short}] {playback_type} playback timed out")
        except asyncio.CancelledError:
            logger.info(f"[{self._call_short}] {playback_type} playback cancelled")
            raise
        except Exception as e:
            logger.error(f"[{self._call_short}] {playback_type} playback failed: {e}")

    def _record_greeting_context(self, greeting_text: str) -> None:
        """Record greeting in memory manager."""
        if not self.memory_manager:
            return

        try:
            # Get agent name
            app_state = getattr(self.websocket, "app", None)
            app_state = getattr(app_state, "state", None)
            auth_agent = getattr(app_state, "auth_agent", None)
            agent_name = getattr(auth_agent, "name", None) if auth_agent else None
            if not agent_name:
                agent_name = self.memory_manager.get_value_from_corememory("active_agent", None)
            if not agent_name:
                agent_name = "AutoAuth"

            # Append to history
            history = self.memory_manager.get_history(agent_name)
            last_entry = history[-1] if history else None
            last_content = last_entry.get("content") if isinstance(last_entry, dict) else None
            if last_content != greeting_text:
                self.memory_manager.append_to_history(agent_name, "assistant", greeting_text)

            # Update core memory
            if not self.memory_manager.get_value_from_corememory("greeting_sent", False):
                self.memory_manager.update_corememory("greeting_sent", True)
            if not self.memory_manager.get_value_from_corememory("active_agent", None):
                self.memory_manager.update_corememory("active_agent", agent_name)

        except Exception as e:
            logger.warning(f"[{self._call_short}] Failed to record greeting: {e}")

    async def _emit_to_ui(self, text: str) -> None:
        """Emit message to UI dashboard."""
        session_id = (
            getattr(self.memory_manager, "session_id", None)
            or getattr(self.websocket.state, "session_id", None)
            or getattr(self.websocket.state, "call_connection_id", None)
        )

        if session_id:
            envelope = make_status_envelope(
                text,
                sender="System",
                topic="session",
                session_id=session_id,
            )
            try:
                await send_session_envelope(
                    self.websocket,
                    envelope,
                    session_id=session_id,
                    conn_id=None,
                    event_label="acs_message",
                    broadcast_only=True,
                )
            except Exception as e:
                logger.warning(f"[{self._call_short}] Failed to emit to UI: {e}")

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """Start the ACS media handler."""
        with tracer.start_as_current_span(
            "acs_media_handler.start",
            kind=SpanKind.INTERNAL,
            attributes={"call.connection.id": self.call_connection_id},
        ):
            try:
                logger.info(f"[{self._call_short}] Starting ACS media handler")
                self.running = True

                # Start speech cascade handler
                await self.speech_cascade.start()

                logger.info(f"[{self._call_short}] ACS media handler started")

            except Exception as e:
                logger.error(f"[{self._call_short}] Failed to start: {e}")
                await self.stop()
                raise

    async def stop(self) -> None:
        """Stop the ACS media handler."""
        if self._stopped:
            return

        with tracer.start_as_current_span(
            "acs_media_handler.stop", kind=SpanKind.INTERNAL
        ):
            try:
                logger.info(f"[{self._call_short}] Stopping ACS media handler")
                self._stopped = True
                self.running = False

                # Stop speech cascade handler
                try:
                    await self.speech_cascade.stop()
                except Exception as e:
                    logger.error(f"[{self._call_short}] Error stopping speech cascade: {e}")

                # Release pool resources
                await self._release_pool_resources()

                logger.info(f"[{self._call_short}] ACS media handler stopped")

            except Exception as e:
                logger.error(f"[{self._call_short}] Critical stop error: {e}")

    async def _release_pool_resources(self) -> None:
        """Release STT/TTS pool resources."""
        app_state = getattr(self.websocket, "app", None)
        app_state = getattr(app_state, "state", None) if app_state else None
        if not app_state:
            return

        # Release TTS
        if self._tts_client:
            try:
                self._tts_client.stop_speaking()
            except Exception:
                pass
            tts_pool = getattr(app_state, "tts_pool", None)
            if tts_pool:
                try:
                    await tts_pool.release_for_session(self.call_connection_id, self._tts_client)
                except Exception as e:
                    logger.error(f"[{self._call_short}] Error releasing TTS: {e}")
            self._tts_client = None

        # Release STT
        if self._stt_client:
            try:
                self._stt_client.stop()
            except Exception:
                pass
            stt_pool = getattr(app_state, "stt_pool", None)
            if stt_pool:
                try:
                    await stt_pool.release_for_session(self.call_connection_id, self._stt_client)
                except Exception as e:
                    logger.error(f"[{self._call_short}] Error releasing STT: {e}")
            self._stt_client = None

    @property
    def is_running(self) -> bool:
        """Check if the handler is running."""
        return self.running

    # =========================================================================
    # Call Operations
    # =========================================================================

    async def transfer_call(
        self,
        target: str,
        *,
        operation_context: Optional[str] = None,
        operation_callback_url: Optional[str] = None,
        transferee: Optional[str] = None,
        sip_headers: Optional[Dict[str, str]] = None,
        voip_headers: Optional[Dict[str, str]] = None,
        source_caller_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Transfer the active ACS call."""
        return await transfer_call_service(
            call_connection_id=self.call_connection_id,
            target_address=target,
            operation_context=operation_context,
            operation_callback_url=operation_callback_url,
            transferee=transferee,
            sip_headers=sip_headers,
            voip_headers=voip_headers,
            source_caller_id=source_caller_id,
        )

    def queue_direct_text_playback(
        self,
        text: str,
        playback_type: SpeechEventType = SpeechEventType.ANNOUNCEMENT,
        language: str = "en-US",
    ) -> bool:
        """
        Queue direct text for playback.

        Args:
            text: Text to play.
            playback_type: Type of playback event.
            language: Language for TTS.

        Returns:
            True if successfully queued.
        """
        if not self.running:
            return False

        valid_types = {
            SpeechEventType.GREETING,
            SpeechEventType.ANNOUNCEMENT,
            SpeechEventType.STATUS_UPDATE,
            SpeechEventType.ERROR_MESSAGE,
        }

        if playback_type not in valid_types:
            logger.error(f"[{self._call_short}] Invalid playback type: {playback_type}")
            return False

        return self.speech_cascade.queue_event(
            SpeechEvent(event_type=playback_type, text=text, language=language)
        )

    # =========================================================================
    # Internal Component Access (for advanced usage)
    # =========================================================================

    @property
    def recognizer(self) -> StreamingSpeechRecognizerFromBytes:
        """Get the speech recognizer."""
        return self.speech_cascade.recognizer

    @property
    def speech_queue(self) -> asyncio.Queue:
        """Get the speech event queue."""
        return self.speech_cascade.speech_queue

    @property
    def thread_bridge(self):
        """Get the thread bridge."""
        return self.speech_cascade.thread_bridge

    @property
    def speech_sdk_thread(self):
        """Get the speech SDK thread."""
        return self.speech_cascade.speech_sdk_thread

    @property
    def route_turn_thread(self):
        """Get the route turn thread."""
        return self.speech_cascade.route_turn_thread

    @property
    def main_event_loop(self):
        """Get the barge-in controller."""
        return self.speech_cascade.barge_in_controller


__all__ = ["ACSMediaHandler", "ACSMessageKind"]
