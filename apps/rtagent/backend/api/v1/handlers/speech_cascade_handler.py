"""
Speech Cascade Handler - Three-Thread Architecture
===================================================

Generic speech processing handler implementing the three-thread architecture
for low-latency voice interactions. This handler is protocol-agnostic and
can be composed with different transport handlers (ACS, VoiceLive, WebRTC, etc.).

🧵 Thread 1: Speech SDK Thread (Never Blocks)
- Continuous audio recognition
- Immediate barge-in detection via on_partial callbacks
- Cross-thread communication via run_coroutine_threadsafe

🧵 Thread 2: Route Turn Thread (Blocks on Queue Only)
- AI processing and response generation
- Orchestrator delegation for TTS and playback
- Queue-based serialization of conversation turns

🧵 Thread 3: Main Event Loop (Never Blocks)
- Task cancellation for barge-in scenarios
- Non-blocking coordination with transport layer

Architecture:
    Transport Handler (ACS/VoiceLive/WebRTC)
           │
           ▼
    SpeechCascadeHandler
           │
    ┌──────┼──────┐
    │      │      │
    ▼      ▼      ▼
  Speech  Route   Main
   SDK    Turn   Event
  Thread  Thread  Loop
"""

from __future__ import annotations

import asyncio
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from config import STT_PROCESSING_TIMEOUT
from src.speech.speech_recognizer import StreamingSpeechRecognizerFromBytes
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = get_logger("v1.handlers.speech_cascade_handler")
tracer = trace.get_tracer(__name__)

# Thread pool for cleanup operations
_handlers_cleanup_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="handler-cleanup"
)


class SpeechEventType(Enum):
    """Types of speech recognition events."""

    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"
    GREETING = "greeting"
    ANNOUNCEMENT = "announcement"
    STATUS_UPDATE = "status"
    ERROR_MESSAGE = "error_msg"


@dataclass
class SpeechEvent:
    """Speech recognition event with metadata."""

    event_type: SpeechEventType
    text: str
    language: Optional[str] = None
    speaker_id: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: Optional[float] = field(default_factory=time.time)


class ResponseSender(Protocol):
    """Protocol for sending responses (TTS) to the transport layer."""

    async def send_response(
        self,
        text: str,
        *,
        voice_name: Optional[str] = None,
        voice_style: Optional[str] = None,
        rate: Optional[str] = None,
    ) -> None:
        """Send a text response via TTS."""
        ...


class TranscriptEmitter(Protocol):
    """Protocol for emitting transcripts to UI/dashboard."""

    async def emit_user_transcript(
        self, text: str, *, partial: bool = False, turn_id: Optional[str] = None
    ) -> None:
        """Emit user transcript to connected clients."""
        ...

    async def emit_assistant_transcript(
        self, text: str, *, sender: Optional[str] = None
    ) -> None:
        """Emit assistant transcript to connected clients."""
        ...


class ThreadBridge:
    """
    Cross-thread communication bridge.

    Provides thread-safe communication between Speech SDK Thread and Main Event Loop.
    Implements the non-blocking patterns for barge-in detection.
    """

    def __init__(self):
        """Initialize cross-thread communication bridge."""
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.connection_id = "unknown"
        self._route_turn_thread_ref: Optional[weakref.ReferenceType] = None

    def set_main_loop(
        self, loop: asyncio.AbstractEventLoop, connection_id: str = None
    ) -> None:
        """
        Set the main event loop reference for cross-thread communication.

        Args:
            loop: Main event loop instance for cross-thread coroutine scheduling.
            connection_id: Optional connection ID for logging context.
        """
        self.main_loop = loop
        if connection_id:
            self.connection_id = connection_id

    def set_route_turn_thread(self, route_turn_thread: "RouteTurnThread") -> None:
        """Store a weak reference to the RouteTurnThread for coordinated cancellation."""
        try:
            self._route_turn_thread_ref = weakref.ref(route_turn_thread)
        except TypeError:
            self._route_turn_thread_ref = None

    def schedule_barge_in(self, handler_func: Callable) -> None:
        """
        Schedule barge-in handler to execute on main event loop with priority.

        Args:
            handler_func: Callable barge-in handler function to schedule.
        """
        if not self.main_loop or self.main_loop.is_closed():
            logger.warning(
                f"[{self.connection_id}] No main loop for barge-in scheduling"
            )
            return

        route_turn_thread = (
            self._route_turn_thread_ref()
            if self._route_turn_thread_ref is not None
            else None
        )

        if route_turn_thread:
            try:
                asyncio.run_coroutine_threadsafe(
                    route_turn_thread.cancel_current_processing(), self.main_loop
                )
            except Exception as exc:
                logger.error(
                    f"[{self.connection_id}] Failed to cancel route turn thread during barge-in: {exc}"
                )

        try:
            asyncio.run_coroutine_threadsafe(handler_func(), self.main_loop)
        except Exception as e:
            logger.error(f"[{self.connection_id}] Failed to schedule barge-in: {e}")

    def queue_speech_result(
        self, speech_queue: asyncio.Queue, event: SpeechEvent
    ) -> None:
        """
        Queue speech recognition result for Route Turn Thread processing.

        Args:
            speech_queue: Async queue for speech event transfer between threads.
            event: Speech recognition event containing transcription results.
        """
        if not isinstance(event, SpeechEvent):
            logger.error(
                f"[{self.connection_id}] Non-SpeechEvent enqueued: {type(event).__name__}"
            )
            return

        try:
            speech_queue.put_nowait(event)
            if event.event_type != SpeechEventType.PARTIAL:
                logger.info(
                    f"[{self.connection_id}] Enqueued speech event type={event.event_type.value} qsize={speech_queue.qsize()}"
                )
        except asyncio.QueueFull:
            logger.warning(
                f"[{self.connection_id}] Speech queue full, evicting oldest event"
            )
            try:
                evicted = speech_queue.get_nowait()
                logger.info(
                    f"[{self.connection_id}] Dropped oldest speech event type={evicted.event_type.value}"
                )
            except asyncio.QueueEmpty:
                pass

            try:
                speech_queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.error(
                    f"[{self.connection_id}] Queue still full after eviction; dropping {event.event_type.value}"
                )
        except Exception:
            # Fallback to run_coroutine_threadsafe
            if self.main_loop and not self.main_loop.is_closed():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        speech_queue.put(event), self.main_loop
                    )
                    future.result(timeout=0.1)
                except Exception as e:
                    logger.error(
                        f"[{self.connection_id}] Failed to queue speech: {e}"
                    )


class SpeechSDKThread:
    """
    Speech SDK Thread Manager - handles continuous audio recognition.

    Key Characteristics:
    - Runs in dedicated background thread
    - Immediate callback execution (< 10ms)
    - Cross-thread communication via ThreadBridge
    - Never blocks on queue operations
    """

    def __init__(
        self,
        connection_id: str,
        recognizer: StreamingSpeechRecognizerFromBytes,
        thread_bridge: ThreadBridge,
        barge_in_handler: Callable,
        speech_queue: asyncio.Queue,
        *,
        on_partial_transcript: Optional[Callable[[str, str, Optional[str]], None]] = None,
    ):
        """
        Initialize Speech SDK Thread.

        Args:
            connection_id: Connection identifier for logging.
            recognizer: Speech recognizer instance.
            thread_bridge: Cross-thread communication bridge.
            barge_in_handler: Handler to call on barge-in detection.
            speech_queue: Queue for final speech results.
            on_partial_transcript: Optional callback for partial transcripts.
        """
        self.connection_id = connection_id
        self._conn_short = connection_id[-8:] if connection_id else "unknown"
        self.recognizer = recognizer
        self.thread_bridge = thread_bridge
        self.barge_in_handler = barge_in_handler
        self.speech_queue = speech_queue
        self.on_partial_transcript = on_partial_transcript

        self.thread_obj: Optional[threading.Thread] = None
        self.thread_running = False
        self.recognizer_started = False
        self.stop_event = threading.Event()
        self._stopped = False

        self._setup_callbacks()
        self._pre_initialize_recognizer()

    def _pre_initialize_recognizer(self) -> None:
        """Pre-initialize push_stream to prevent audio data loss."""
        try:
            if (
                hasattr(self.recognizer, "push_stream")
                and self.recognizer.push_stream is not None
            ):
                logger.debug(
                    f"[{self._conn_short}] Push_stream already exists, skipping pre-init"
                )
                return

            if hasattr(self.recognizer, "create_push_stream"):
                self.recognizer.create_push_stream()
                logger.info(f"[{self._conn_short}] Pre-initialized push_stream")
            elif hasattr(self.recognizer, "prepare_stream"):
                self.recognizer.prepare_stream()
                logger.info(f"[{self._conn_short}] Pre-initialized via prepare_stream")
            else:
                logger.warning(
                    f"[{self._conn_short}] No direct push_stream method found"
                )
                self.recognizer.prepare_start()

        except Exception as e:
            logger.warning(f"[{self._conn_short}] Failed to pre-init push_stream: {e}")

    def _setup_callbacks(self) -> None:
        """Configure speech recognition callbacks."""

        def on_partial(text: str, lang: str, speaker_id: Optional[str] = None):
            logger.info(
                f"[{self._conn_short}] Partial speech: '{text}' ({lang}) len={len(text.strip())}"
            )
            if len(text.strip()) > 3:
                try:
                    self.thread_bridge.schedule_barge_in(self.barge_in_handler)
                except Exception as e:
                    logger.error(f"[{self._conn_short}] Barge-in error: {e}")

                if self.on_partial_transcript:
                    try:
                        self.on_partial_transcript(text.strip(), lang, speaker_id)
                    except Exception as e:
                        logger.debug(
                            f"[{self._conn_short}] Partial transcript callback error: {e}"
                        )

        def on_final(text: str, lang: str, speaker_id: Optional[str] = None):
            logger.debug(
                f"[{self._conn_short}] Final speech: '{text}' ({lang}) len={len(text.strip())}"
            )
            if len(text.strip()) > 1:
                logger.info(f"[{self._conn_short}] Speech: '{text}' ({lang})")
                event = SpeechEvent(
                    event_type=SpeechEventType.FINAL,
                    text=text,
                    language=lang,
                    speaker_id=speaker_id,
                )
                self.thread_bridge.queue_speech_result(self.speech_queue, event)

        def on_error(error: str):
            logger.error(f"[{self._conn_short}] Speech error: {error}")
            error_event = SpeechEvent(event_type=SpeechEventType.ERROR, text=error)
            self.thread_bridge.queue_speech_result(self.speech_queue, error_event)

        try:
            self.recognizer.set_partial_result_callback(on_partial)
            self.recognizer.set_final_result_callback(on_final)
            self.recognizer.set_cancel_callback(on_error)
            logger.info(f"[{self._conn_short}] Speech callbacks registered")
        except Exception as e:
            logger.error(f"[{self._conn_short}] Failed to setup callbacks: {e}")
            raise

    def prepare_thread(self) -> None:
        """Prepare the speech recognition thread."""
        if self.thread_running:
            return

        def recognition_thread():
            try:
                self.thread_running = True
                while self.thread_running and not self.stop_event.is_set():
                    self.stop_event.wait(0.1)
            except Exception as e:
                logger.error(f"[{self._conn_short}] Speech thread error: {e}")
            finally:
                self.thread_running = False

        self.thread_obj = threading.Thread(target=recognition_thread, daemon=True)
        self.thread_obj.start()

    def start_recognizer(self) -> None:
        """Start the speech recognizer."""
        if self.recognizer_started or not self.thread_running:
            return

        try:
            logger.info(
                f"[{self._conn_short}] Starting speech recognizer, push_stream_exists={bool(self.recognizer.push_stream)}"
            )
            self.recognizer.start()
            self.recognizer_started = True
            logger.info(f"[{self._conn_short}] Speech recognizer started")
        except Exception as e:
            logger.error(f"[{self._conn_short}] Failed to start recognizer: {e}")
            raise

    def write_audio(self, audio_bytes: bytes) -> None:
        """
        Write audio bytes to the recognizer.

        Args:
            audio_bytes: Raw audio bytes to process.
        """
        if self.recognizer:
            self.recognizer.write_bytes(audio_bytes)

    def stop(self) -> None:
        """Stop speech recognition and thread."""
        if self._stopped:
            return

        try:
            logger.info(f"[{self._conn_short}] Stopping speech SDK thread")
            self._stopped = True
            self.thread_running = False
            self.recognizer_started = False
            self.stop_event.set()

            if self.recognizer:
                try:
                    self.recognizer.stop()
                except Exception as e:
                    logger.error(f"[{self._conn_short}] Error stopping recognizer: {e}")

            if self.thread_obj and self.thread_obj.is_alive():
                self.thread_obj.join(timeout=2.0)
                if self.thread_obj.is_alive():
                    logger.warning(
                        f"[{self._conn_short}] Recognition thread did not stop within timeout"
                    )

            logger.info(f"[{self._conn_short}] Speech SDK thread stopped")

        except Exception as e:
            logger.error(f"[{self._conn_short}] Error during speech SDK thread stop: {e}")


def _background_task(coro: Awaitable[Any], *, label: str) -> None:
    """Create a background task with logging."""
    task = asyncio.create_task(coro)

    def _log_outcome(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception:
            logger.debug("Background task '%s' failed", label, exc_info=True)

    task.add_done_callback(_log_outcome)


class RouteTurnThread:
    """
    Route Turn Thread Manager - handles AI processing and response generation.

    Key Characteristics:
    - Blocks only on queue.get() operations
    - Serializes conversation turns via queue
    - Delegates to orchestrator for response generation
    - Emits events to transport layer for coordination
    - Isolated from real-time operations
    """

    def __init__(
        self,
        connection_id: str,
        speech_queue: asyncio.Queue,
        orchestrator_func: Callable,
        memory_manager: Optional[MemoManager],
        *,
        response_sender: Optional[ResponseSender] = None,
        transcript_emitter: Optional[TranscriptEmitter] = None,
        on_greeting: Optional[Callable[[SpeechEvent], Awaitable[None]]] = None,
        on_announcement: Optional[Callable[[SpeechEvent], Awaitable[None]]] = None,
        on_user_transcript: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tts_request: Optional[Callable[[str, SpeechEventType], Awaitable[None]]] = None,
    ):
        """
        Initialize Route Turn Thread.

        Args:
            connection_id: Connection identifier for logging.
            speech_queue: Queue for receiving speech events.
            orchestrator_func: Function to call for AI processing.
            memory_manager: Memory manager for conversation state.
            response_sender: Protocol implementation for sending TTS responses.
            transcript_emitter: Protocol implementation for emitting transcripts.
            on_greeting: Callback for greeting events (emitted to transport).
            on_announcement: Callback for announcement events (emitted to transport).
            on_user_transcript: Callback for final user transcripts (emitted to transport).
            on_tts_request: Callback for TTS playback requests (emitted to transport).
        """
        self.connection_id = connection_id
        self._conn_short = connection_id[-8:] if connection_id else "unknown"
        self.speech_queue = speech_queue
        self.orchestrator_func = orchestrator_func
        self.memory_manager = memory_manager
        self.response_sender = response_sender
        self.transcript_emitter = transcript_emitter
        self.on_greeting = on_greeting
        self.on_announcement = on_announcement
        self.on_user_transcript = on_user_transcript
        self.on_tts_request = on_tts_request

        self.processing_task: Optional[asyncio.Task] = None
        self.current_response_task: Optional[asyncio.Task] = None
        self.running = False
        self._stopped = False

    async def start(self) -> None:
        """Start the route turn processing loop."""
        if self.running:
            return

        self.running = True
        self.processing_task = asyncio.create_task(self._processing_loop())

    async def _processing_loop(self) -> None:
        """Main processing loop."""
        while self.running:
            try:
                speech_event = await asyncio.wait_for(
                    self.speech_queue.get(), timeout=1.0
                )

                try:
                    logger.debug(
                        f"[{self._conn_short}] Routing speech event type={getattr(speech_event, 'event_type', 'unknown')}"
                    )
                    if speech_event.event_type == SpeechEventType.FINAL:
                        await self._process_final_speech(speech_event)
                    elif speech_event.event_type == SpeechEventType.GREETING:
                        # Use on_greeting if available, otherwise fall back to on_tts_request
                        if self.on_greeting:
                            await self.on_greeting(speech_event)
                        elif self.on_tts_request:
                            await self.on_tts_request(speech_event.text, speech_event.event_type)
                    elif speech_event.event_type in {
                        SpeechEventType.ANNOUNCEMENT,
                        SpeechEventType.STATUS_UPDATE,
                        SpeechEventType.ERROR_MESSAGE,
                    }:
                        # Use on_announcement if available, otherwise fall back to on_tts_request
                        if self.on_announcement:
                            await self.on_announcement(speech_event)
                        elif self.on_tts_request:
                            await self.on_tts_request(speech_event.text, speech_event.event_type)
                    elif speech_event.event_type == SpeechEventType.ERROR:
                        logger.error(
                            f"[{self._conn_short}] Speech error: {speech_event.text}"
                        )
                except asyncio.CancelledError:
                    continue  # Barge-in cancellation
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[{self._conn_short}] Processing loop error: {e}")
                break

    async def _process_final_speech(self, event: SpeechEvent) -> None:
        """Process final speech through orchestrator."""
        with tracer.start_as_current_span(
            "route_turn_thread.process_speech",
            kind=SpanKind.CLIENT,
            attributes={"speech.text": event.text, "speech.language": event.language},
        ):
            try:
                if not self.memory_manager:
                    logger.error(f"[{self._conn_short}] No memory manager available")
                    return

                # Emit user transcript via callback (for transport coordination)
                if self.on_user_transcript:
                    try:
                        await self.on_user_transcript(event.text)
                    except Exception as e:
                        logger.warning(
                            f"[{self._conn_short}] Failed to invoke on_user_transcript: {e}"
                        )

                # Legacy: emit via transcript emitter (deprecated)
                if self.transcript_emitter:
                    try:
                        await self.transcript_emitter.emit_user_transcript(event.text)
                    except Exception as e:
                        logger.warning(
                            f"[{self._conn_short}] Failed to emit user transcript: {e}"
                        )

                # Call orchestrator
                if self.orchestrator_func:
                    coro = self.orchestrator_func(
                        cm=self.memory_manager,
                        transcript=event.text,
                    )
                    if coro:
                        self.current_response_task = asyncio.create_task(coro)
                        await self.current_response_task

            except asyncio.CancelledError:
                logger.info(f"[{self._conn_short}] Orchestrator processing cancelled")
                raise
            except Exception as e:
                logger.error(
                    f"[{self._conn_short}] Error processing speech with orchestrator: {e}"
                )
            finally:
                if self.current_response_task and not self.current_response_task.done():
                    self.current_response_task.cancel()
                self.current_response_task = None

    async def cancel_current_processing(self) -> None:
        """Cancel current processing for barge-in."""
        try:
            # Clear speech queue
            cleared_count = 0
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                    cleared_count += 1
                except asyncio.QueueEmpty:
                    break

            if cleared_count > 0:
                logger.debug(
                    f"[{self._conn_short}] Cleared {cleared_count} events during barge-in"
                )

            # Cancel current response task
            if self.current_response_task and not self.current_response_task.done():
                self.current_response_task.cancel()
                try:
                    await self.current_response_task
                except asyncio.CancelledError:
                    pass
            self.current_response_task = None

        except Exception as e:
            logger.error(f"[{self._conn_short}] Error cancelling processing: {e}")

    async def stop(self) -> None:
        """Stop the route turn processing loop."""
        if self._stopped:
            return

        self._stopped = True
        self.running = False
        await self.cancel_current_processing()

        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass

        await self._clear_speech_queue()

    async def _clear_speech_queue(self) -> None:
        """Clear remaining events from the speech queue."""
        try:
            cleared_count = 0
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                    cleared_count += 1
                except asyncio.QueueEmpty:
                    break

            if cleared_count > 0:
                logger.info(
                    f"[{self._conn_short}] Cleared {cleared_count} speech events during stop"
                )
        except Exception as e:
            logger.error(f"[{self._conn_short}] Error clearing speech queue: {e}")


class BargeInController:
    """
    Barge-in detection and handling controller.

    Coordinates immediate response to user interruptions across
    all threads without blocking.
    """

    def __init__(
        self,
        connection_id: str,
        *,
        on_barge_in: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        """
        Initialize barge-in controller.

        Args:
            connection_id: Connection identifier for logging.
            on_barge_in: Callback when barge-in is detected.
        """
        self.connection_id = connection_id
        self._conn_short = connection_id[-8:] if connection_id else "unknown"
        self.on_barge_in = on_barge_in
        self.barge_in_active = threading.Event()
        self.current_playback_task: Optional[asyncio.Task] = None

    async def handle_barge_in(self) -> None:
        """Handle barge-in interruption."""
        if self.barge_in_active.is_set():
            return

        self.barge_in_active.set()

        try:
            # Cancel current playback
            if self.current_playback_task and not self.current_playback_task.done():
                self.current_playback_task.cancel()
                try:
                    await self.current_playback_task
                except asyncio.CancelledError:
                    pass

            # Call transport-specific barge-in handler
            if self.on_barge_in:
                await self.on_barge_in()

        except Exception as e:
            logger.error(f"[{self._conn_short}] Barge-in error: {e}")
        finally:
            asyncio.create_task(self._reset_barge_in_state())

    async def _reset_barge_in_state(self) -> None:
        """Reset barge-in state after brief delay."""
        await asyncio.sleep(0.1)
        self.barge_in_active.clear()


class SpeechCascadeHandler:
    """
    Generic Speech Cascade Handler - Three-Thread Architecture Implementation

    Coordinates the three-thread architecture for low-latency voice interactions.
    This handler is protocol-agnostic and can be composed with different
    transport handlers (ACS, VoiceLive, WebRTC, etc.).

    Usage:
        handler = SpeechCascadeHandler(
            connection_id="call_123",
            orchestrator_func=my_orchestrator,
            recognizer=speech_recognizer,
            memory_manager=memo_manager,
        )
        await handler.start()
        # Feed audio via handler.write_audio(bytes)
        # Queue events via handler.queue_event(event)
        await handler.stop()
    """

    def __init__(
        self,
        connection_id: str,
        orchestrator_func: Callable,
        recognizer: Optional[StreamingSpeechRecognizerFromBytes] = None,
        memory_manager: Optional[MemoManager] = None,
        *,
        on_barge_in: Optional[Callable[[], Awaitable[None]]] = None,
        on_greeting: Optional[Callable[[SpeechEvent], Awaitable[None]]] = None,
        on_announcement: Optional[Callable[[SpeechEvent], Awaitable[None]]] = None,
        on_partial_transcript: Optional[Callable[[str, str, Optional[str]], None]] = None,
        on_user_transcript: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tts_request: Optional[Callable[[str, SpeechEventType], Awaitable[None]]] = None,
        transcript_emitter: Optional[TranscriptEmitter] = None,
        response_sender: Optional[ResponseSender] = None,
    ):
        """
        Initialize the speech cascade handler.

        Args:
            connection_id: Unique connection identifier.
            orchestrator_func: Orchestrator function for conversation management.
            recognizer: Speech recognition client instance.
            memory_manager: Memory manager for conversation state.
            on_barge_in: Callback for barge-in events (transport-specific).
            on_greeting: Callback for greeting playback.
            on_announcement: Callback for announcement playback.
            on_partial_transcript: Callback for partial transcripts.
            on_user_transcript: Callback for final user transcripts (emitted to transport).
            on_tts_request: Callback for TTS playback requests (emitted to transport).
            transcript_emitter: Protocol implementation for emitting transcripts.
            response_sender: Protocol implementation for sending TTS responses.
        """
        self.connection_id = connection_id
        self._conn_short = connection_id[-8:] if connection_id else "unknown"
        self.orchestrator_func = orchestrator_func
        self.memory_manager = memory_manager

        # Store callbacks for transport layer coordination
        self.on_user_transcript = on_user_transcript
        self.on_tts_request = on_tts_request

        # Initialize speech recognizer
        self.recognizer = recognizer or StreamingSpeechRecognizerFromBytes(
            candidate_languages=["en-US", "fr-FR", "de-DE", "es-ES", "it-IT"],
            vad_silence_timeout_ms=800,
            audio_format="pcm",
            use_semantic_segmentation=False,
            enable_diarisation=False,
        )

        # Cross-thread communication
        self.speech_queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.thread_bridge = ThreadBridge()

        # Barge-in controller
        self.barge_in_controller = BargeInController(
            connection_id, on_barge_in=on_barge_in
        )

        # Route Turn Thread
        self.route_turn_thread = RouteTurnThread(
            connection_id=connection_id,
            speech_queue=self.speech_queue,
            orchestrator_func=orchestrator_func,
            memory_manager=memory_manager,
            transcript_emitter=transcript_emitter,
            response_sender=response_sender,
            on_greeting=on_greeting,
            on_announcement=on_announcement,
            on_user_transcript=on_user_transcript,
            on_tts_request=on_tts_request,
        )

        # Speech SDK Thread
        self.speech_sdk_thread = SpeechSDKThread(
            connection_id=connection_id,
            recognizer=self.recognizer,
            thread_bridge=self.thread_bridge,
            barge_in_handler=self.barge_in_controller.handle_barge_in,
            speech_queue=self.speech_queue,
            on_partial_transcript=on_partial_transcript,
        )

        self.thread_bridge.set_route_turn_thread(self.route_turn_thread)

        # Lifecycle
        self.running = False
        self._stopped = False

    async def start(self) -> None:
        """Start all threads."""
        with tracer.start_as_current_span(
            "speech_cascade_handler.start",
            kind=SpanKind.INTERNAL,
            attributes={"connection.id": self.connection_id},
        ):
            try:
                logger.info(f"[{self._conn_short}] Starting speech cascade handler")
                self.running = True

                # Capture main event loop
                main_loop = asyncio.get_running_loop()
                self.thread_bridge.set_main_loop(main_loop, self.connection_id)

                # Start threads
                self.speech_sdk_thread.prepare_thread()

                # Wait for thread to be ready
                for _ in range(10):
                    if self.speech_sdk_thread.thread_running:
                        break
                    await asyncio.sleep(0.05)

                # Start recognizer
                await asyncio.get_running_loop().run_in_executor(
                    None, self.speech_sdk_thread.start_recognizer
                )

                await self.route_turn_thread.start()

                logger.info(f"[{self._conn_short}] Speech cascade handler started")

            except Exception as e:
                logger.error(f"[{self._conn_short}] Failed to start: {e}")
                await self.stop()
                raise

    def write_audio(self, audio_bytes: bytes) -> None:
        """
        Write audio bytes to the speech recognizer.

        Args:
            audio_bytes: Raw audio bytes to process.
        """
        if self.running and self.speech_sdk_thread:
            self.speech_sdk_thread.write_audio(audio_bytes)

    def queue_event(self, event: SpeechEvent) -> bool:
        """
        Queue a speech event for processing.

        Args:
            event: Speech event to queue.

        Returns:
            True if successfully queued, False otherwise.
        """
        if not self.running:
            return False

        try:
            self.thread_bridge.queue_speech_result(self.speech_queue, event)
            return True
        except Exception as e:
            logger.error(f"[{self._conn_short}] Failed to queue event: {e}")
            return False

    def queue_greeting(self, text: str, language: str = "en-US") -> bool:
        """Queue a greeting for playback."""
        return self.queue_event(
            SpeechEvent(
                event_type=SpeechEventType.GREETING,
                text=text,
                language=language,
                speaker_id=self.connection_id,
            )
        )

    def queue_announcement(self, text: str, language: str = "en-US") -> bool:
        """Queue an announcement for playback."""
        return self.queue_event(
            SpeechEvent(
                event_type=SpeechEventType.ANNOUNCEMENT,
                text=text,
                language=language,
            )
        )

    def queue_user_text(self, text: str, language: str = "en-US") -> bool:
        """
        Queue user text input for orchestration.

        Used for text input (e.g., browser chat) that bypasses STT.

        Args:
            text: User text input.
            language: Language code.

        Returns:
            True if successfully queued, False otherwise.
        """
        return self.queue_event(
            SpeechEvent(
                event_type=SpeechEventType.FINAL,
                text=text,
                language=language,
                speaker_id=self.connection_id,
            )
        )

    async def stop(self) -> None:
        """Stop all threads."""
        if self._stopped:
            return

        with tracer.start_as_current_span(
            "speech_cascade_handler.stop", kind=SpanKind.INTERNAL
        ):
            try:
                logger.info(f"[{self._conn_short}] Stopping speech cascade handler")
                self._stopped = True
                self.running = False

                cleanup_errors = []

                try:
                    await self.route_turn_thread.stop()
                except Exception as e:
                    cleanup_errors.append(f"route_turn_thread: {e}")

                try:
                    self.speech_sdk_thread.stop()
                except Exception as e:
                    cleanup_errors.append(f"speech_sdk_thread: {e}")

                try:
                    await self._clear_speech_queue_final()
                except Exception as e:
                    cleanup_errors.append(f"speech_queue_cleanup: {e}")

                if cleanup_errors:
                    logger.warning(
                        f"[{self._conn_short}] Stopped with {len(cleanup_errors)} cleanup errors"
                    )
                else:
                    logger.info(f"[{self._conn_short}] Speech cascade handler stopped")

            except Exception as e:
                logger.error(f"[{self._conn_short}] Critical stop error: {e}")

    async def _clear_speech_queue_final(self) -> None:
        """Final cleanup of speech queue."""
        try:
            cleared_count = 0
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                    cleared_count += 1
                except asyncio.QueueEmpty:
                    break

            if cleared_count > 0:
                logger.info(
                    f"[{self._conn_short}] Final cleanup: cleared {cleared_count} speech events"
                )
        except Exception as e:
            logger.error(f"[{self._conn_short}] Error in final speech queue cleanup: {e}")

    @property
    def is_running(self) -> bool:
        """Check if the handler is currently running."""
        return self.running


__all__ = [
    "SpeechCascadeHandler",
    "SpeechEvent",
    "SpeechEventType",
    "ThreadBridge",
    "SpeechSDKThread",
    "RouteTurnThread",
    "BargeInController",
    "ResponseSender",
    "TranscriptEmitter",
]
