"""
Speech Cascade Runtime Components
=================================

Speech SDK callbacks feed a bounded thread-safe inbox. Its owning asyncio loop
alone mutates speech queues and serializes turns. Barge-in callbacks are tracked
tasks on that loop. The historical SpeechSDKThread and RouteTurnThread names
remain import-compatible; neither creates a Python recognition/turn thread.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
import weakref
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from apps.artagent.backend.voice.shared.close import cancel_and_join
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from src.speech.speech_recognizer import StreamingSpeechRecognizerFromBytes
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger
from utils.telemetry_decorators import ConversationTurnSpan

if TYPE_CHECKING:
    pass

logger = get_logger("v1.handlers.speech_cascade_handler")
tracer = trace.get_tracer(__name__)


def _cancellation_text(error: Any) -> str:
    """Reduce a Speech SDK cancellation callback argument to readable text.

    The SDK invokes cancel callbacks with a ``SpeechRecognitionCanceledEventArgs``
    rather than a string, so the useful cause is nested under
    ``result.cancellation_details.error_details``. Returning plain text here keeps
    every downstream consumer (logging, classification, the UI envelope) working
    with a single, predictable type.
    """
    if error is None:
        return ""
    if isinstance(error, str):
        return error

    parts: list[str] = []
    details = getattr(getattr(error, "result", None), "cancellation_details", None)
    details = details or getattr(error, "cancellation_details", None)
    if details is not None:
        for attr in ("reason", "error_code", "error_details"):
            value = getattr(details, attr, None)
            if value is not None and str(value) not in parts:
                parts.append(str(value))
    if parts:
        return " | ".join(parts)

    try:
        return str(error)
    except Exception:  # pragma: no cover - defensive
        return repr(type(error).__name__)


class SpeechEventType(Enum):
    """Types of speech recognition events."""

    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"
    GREETING = "greeting"
    ANNOUNCEMENT = "announcement"
    STATUS_UPDATE = "status"
    ERROR_MESSAGE = "error_msg"
    TTS_RESPONSE = "tts_response"  # Queued TTS from orchestrator/gpt_flow


@dataclass
class SpeechEvent:
    """Speech recognition event with metadata."""

    event_type: SpeechEventType
    text: str
    language: str | None = None
    speaker_id: str | None = None
    confidence: float | None = None
    timestamp: float | None = field(default_factory=time.time)
    # Canonical ID shared by this utterance's partial/final transcript, assistant
    # response, and any tool calls. It is allocated on the first STT partial.
    turn_id: str | None = None
    sequence: int | None = None
    # Wall-clock time (time.time) of the first partial for this utterance, i.e.
    # when the user started speaking. Used to draw a real STT recognition span.
    recognition_start_ts: float | None = None
    # perf_counter() captured at recognition finalization (end of user speech).
    # Shares a clock with the LLM/TTS latency markers, so it anchors the per-turn
    # "end of recognition -> first token / first audio" KPIs.
    recognition_end_perf: float | None = None
    # Voice configuration for TTS events
    voice_name: str | None = None
    voice_style: str | None = None
    voice_rate: str | None = None
    voice_pitch: str | None = None
    is_greeting: bool = False


class ResponseSender(Protocol):
    """Protocol for sending responses (TTS) to the transport layer."""

    async def send_response(
        self,
        text: str,
        *,
        voice_name: str | None = None,
        voice_style: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> None:
        """Send a text response via TTS."""
        ...


class TranscriptEmitter(Protocol):
    """Protocol for emitting transcripts to UI/dashboard."""

    async def emit_user_transcript(
        self, text: str, *, partial: bool = False, turn_id: str | None = None
    ) -> None:
        """Emit user transcript to connected clients."""
        ...

    async def emit_assistant_transcript(self, text: str, *, sender: str | None = None) -> None:
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
        self.main_loop: asyncio.AbstractEventLoop | None = None
        self.connection_id = "unknown"
        self._route_turn_thread_ref: weakref.ReferenceType | None = None
        # Thread-safe flag to suppress barge-in during agent transitions/greetings
        self._suppress_barge_in = threading.Event()
        # Pre-speech turn guard: armed the moment a final transcript is produced
        # and held until the agent actually starts speaking (first audio chunk).
        # While armed, partials are ignored because they are the trailing tail of
        # the utterance that just spawned the turn -- acting on them would cancel
        # that very turn and tell the UI to drop its audio. A monotonic deadline
        # is a safety backstop in case first-audio never fires (e.g. tool-only
        # turn); the turn's finally block also disarms it.
        self._turn_guard = threading.Event()
        self._turn_guard_deadline: float = 0.0
        # Only the bounded SDK inbox is shared across threads. asyncio queues
        # and tasks belong exclusively to main_loop.
        self._queue_lock = threading.Lock()
        self._pending: deque[tuple[asyncio.Queue, SpeechEvent]] = deque()
        self._drain_scheduled = False
        self._closed = False
        self._tasks: set[asyncio.Task] = set()
        self._callbacks: deque[tuple[Callable, tuple[Any, ...]]] = deque()
        self._callbacks_scheduled = False
        # perf_counter timestamp of the most recent barge-in detection, used to
        # measure how long barge-in takes to take effect (detection -> TTS stop).
        self.last_barge_in_detected_ts: float | None = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop, connection_id: str = None) -> None:
        """
        Set the main event loop reference for cross-thread communication.

        Args:
            loop: Main event loop instance for cross-thread coroutine scheduling.
            connection_id: Optional connection ID for logging context.
        """
        self.main_loop = loop
        if connection_id:
            self.connection_id = connection_id

    def set_route_turn_thread(self, route_turn_thread: RouteTurnThread) -> None:
        """Store a weak reference to the RouteTurnThread for coordinated cancellation."""
        try:
            self._route_turn_thread_ref = weakref.ref(route_turn_thread)
        except TypeError:
            self._route_turn_thread_ref = None

    def suppress_barge_in(self) -> None:
        """
        Suppress barge-in detection during agent transitions/greetings.

        Call this before playing handoff/greeting audio to prevent
        audio echo from triggering false barge-in events.
        """
        self._suppress_barge_in.set()
        logger.debug(f"[{self.connection_id}] Barge-in suppressed")

    def allow_barge_in(self) -> None:
        """
        Re-enable barge-in detection after agent transition completes.
        """
        self._suppress_barge_in.clear()
        logger.debug(f"[{self.connection_id}] Barge-in allowed")

    @property
    def barge_in_suppressed(self) -> bool:
        """Check if barge-in is currently suppressed (thread-safe)."""
        return self._suppress_barge_in.is_set()

    def arm_turn_guard(self, max_duration_s: float = 15.0) -> None:
        """Suppress trailing-partial barge-in until the agent starts speaking.

        Called from the STT thread when a final transcript is produced. Any
        partials that arrive after this belong to the just-finished utterance and
        must not cancel the turn it spawns.
        """
        self._turn_guard_deadline = time.monotonic() + max_duration_s
        self._turn_guard.set()

    def disarm_turn_guard(self) -> None:
        """Re-enable barge-in (agent has started speaking, or the turn ended)."""
        self._turn_guard.clear()

    @property
    def turn_guard_active(self) -> bool:
        """True while trailing-partial barge-in suppression is in effect."""
        return self._turn_guard.is_set() and time.monotonic() < self._turn_guard_deadline

    def schedule_barge_in(self, handler_func: Callable) -> None:
        """
        Schedule barge-in handler to execute on main event loop with priority.

        Args:
            handler_func: Callable barge-in handler function to schedule.
        """
        # Hard kill switch: half-duplex mode. When set, the user cannot interrupt
        # the agent, but trailing partials can never cancel a turn's audio either.
        # Useful to isolate barge-in as the cause of dropped turn audio.
        if os.getenv("CASCADE_DISABLE_BARGE_IN", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            logger.debug(f"[{self.connection_id}] Barge-in disabled (CASCADE_DISABLE_BARGE_IN)")
            return

        # Check suppression flag (thread-safe)
        if self._suppress_barge_in.is_set():
            logger.debug(
                f"[{self.connection_id}] Barge-in skipped (suppressed during handoff/greeting)"
            )
            return

        # Stamp detection time so the handler can report barge-in effect latency.
        self.last_barge_in_detected_ts = time.perf_counter()

        if not self.main_loop or self.main_loop.is_closed():
            logger.warning(f"[{self.connection_id}] No main loop for barge-in scheduling")
            return

        self.schedule_callback(handler_func)

    def schedule_callback(self, callback: Callable, *args: Any) -> None:
        """Transfer an SDK callback to a tracked task on the owning loop."""
        loop = self.main_loop
        if self._closed or loop is None or loop.is_closed():
            return
        with self._queue_lock:
            if self._closed:
                return
            if len(self._callbacks) >= 50:
                logger.warning("[%s] Speech callback inbox full", self.connection_id)
                return
            self._callbacks.append((callback, args))
            if not self._callbacks_scheduled:
                self._callbacks_scheduled = True
                loop.call_soon_threadsafe(self._drain_callbacks)

    def _drain_callbacks(self) -> None:
        with self._queue_lock:
            callbacks = list(self._callbacks)
            self._callbacks.clear()
            self._callbacks_scheduled = False
        for callback, args in callbacks:
            self._start_callback(callback, args)

    def _start_callback(self, callback: Callable, args: tuple[Any, ...]) -> None:
        if self._closed:
            return
        if len(self._tasks) >= 50:
            logger.warning("[%s] Speech callback capacity reached", self.connection_id)
            return
        task = asyncio.create_task(callback(*args))
        self._tasks.add(task)
        task.add_done_callback(self._callback_done)

    def _callback_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("[%s] Speech callback failed: %s", self.connection_id, task.exception())

    async def close(self) -> None:
        """Reject late SDK callbacks and await every owned callback task."""
        with self._queue_lock:
            self._closed = True
            self._pending.clear()
            self._callbacks.clear()
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def queue_speech_result(self, speech_queue: asyncio.Queue, event: SpeechEvent) -> bool:
        """Submit without blocking; evict a partial or reject the newest event.

        SDK callbacks first enter a bounded inbox with at most one scheduled
        drain. All asyncio.Queue mutations, including eviction, run on main_loop.
        Full queues never create blocking puts or unbounded pending put tasks.
        """
        if not isinstance(event, SpeechEvent):
            logger.error(f"[{self.connection_id}] Non-SpeechEvent enqueued: {type(event).__name__}")
            return False
        loop = self.main_loop
        if self._closed or loop is None or loop.is_closed():
            logger.warning("[%s] Speech event rejected: bridge is not live", self.connection_id)
            return False
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self._drain_pending()
            return self._enqueue_on_loop(speech_queue, event)

        with self._queue_lock:
            if self._closed:
                return False
            if len(self._pending) >= (speech_queue.maxsize or 50):
                partial_index = next(
                    (
                        i
                        for i, (_, old) in enumerate(self._pending)
                        if old.event_type == SpeechEventType.PARTIAL
                    ),
                    None,
                )
                if event.event_type == SpeechEventType.PARTIAL or partial_index is None:
                    logger.warning(
                        "[%s] SDK inbox full; rejecting %s",
                        self.connection_id,
                        event.event_type.value,
                    )
                    return False
                del self._pending[partial_index]
            self._pending.append((speech_queue, event))
            if not self._drain_scheduled:
                self._drain_scheduled = True
                loop.call_soon_threadsafe(self._drain_pending)
        return True

    def _drain_pending(self) -> None:
        with self._queue_lock:
            pending = list(self._pending)
            self._pending.clear()
            self._drain_scheduled = False
        if not self._closed:
            for queue, event in pending:
                self._enqueue_on_loop(queue, event)

    def _enqueue_on_loop(self, queue: asyncio.Queue, event: SpeechEvent) -> bool:
        if queue.full() and event.event_type != SpeechEventType.PARTIAL:
            retained = []
            evicted = False
            while not queue.empty():
                old = queue.get_nowait()
                queue.task_done()
                if not evicted and old.event_type == SpeechEventType.PARTIAL:
                    evicted = True
                else:
                    retained.append(old)
            for old in retained:
                queue.put_nowait(old)
        if queue.full():
            logger.warning(
                "[%s] Speech queue full; rejecting %s", self.connection_id, event.event_type.value
            )
            return False
        queue.put_nowait(event)
        return True

    async def queue_speech_result_async(
        self, speech_queue: asyncio.Queue, event: SpeechEvent, *, timeout: float = 5.0
    ) -> None:
        """Backpressure async input providers instead of evicting finalized turns."""
        if self._closed:
            raise RuntimeError("Speech event bridge is closed.")
        if self.main_loop is not asyncio.get_running_loop():
            raise RuntimeError("Async speech events must use the owning event loop.")
        await asyncio.wait_for(speech_queue.put(event), timeout=timeout)


class SpeechSDKThread:
    """
    Speech SDK Thread Manager - handles continuous audio recognition.

    Key Characteristics:
    - Recognition runs on SDK-owned threads
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
        on_partial_transcript: Callable[[str, str, str | None, str, int], None] | None = None,
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

        self.thread_obj: threading.Thread | None = None
        self.thread_running = False
        self.recognizer_started = False
        self.stop_event = threading.Event()
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._stop_complete = False
        self._stop_error: Exception | None = None
        self._stop_task: asyncio.Task | None = None
        # Wall-clock time of the first partial of the current utterance (user
        # started speaking). Reset after each final. Drives the STT span.
        self._utterance_start_ts: float | None = None
        self._utterance_turn_id: str | None = None
        self._utterance_sequence = 0

        self._setup_callbacks()
        self._pre_initialize_recognizer()

    def _pre_initialize_recognizer(self) -> None:
        """Pre-initialize push_stream to prevent audio data loss."""
        try:
            if hasattr(self.recognizer, "push_stream") and self.recognizer.push_stream is not None:
                logger.debug(f"[{self._conn_short}] Push_stream already exists, skipping pre-init")
                return

            if hasattr(self.recognizer, "create_push_stream"):
                self.recognizer.create_push_stream()
                logger.info(f"[{self._conn_short}] Pre-initialized push_stream")
            elif hasattr(self.recognizer, "prepare_stream"):
                self.recognizer.prepare_stream()
                logger.info(f"[{self._conn_short}] Pre-initialized via prepare_stream")
            else:
                logger.warning(f"[{self._conn_short}] No direct push_stream method found")
                self.recognizer.prepare_start()

        except Exception as e:
            logger.warning(f"[{self._conn_short}] Failed to pre-init push_stream: {e}")

    def _setup_callbacks(self) -> None:
        """Configure speech recognition callbacks."""

        def on_partial(text: str, lang: str, speaker_id: str | None = None):
            if self._stopped:
                return
            logger.info(
                f"[{self._conn_short}] Partial speech: '{text}' ({lang}) len={len(text.strip())}"
            )
            # Ignore all trailing hypotheses while the just-finalized turn is
            # waiting for first audio. Do this before allocating the next turn ID
            # so late SDK callbacks cannot contaminate the following utterance.
            if self.thread_bridge.turn_guard_active:
                logger.debug(f"[{self._conn_short}] Partial ignored (pre-speech turn guard)")
                return

            # Stamp the start of this utterance (user started speaking) on the
            # first partial so we can draw an accurate STT recognition span.
            if self._utterance_start_ts is None:
                self._utterance_start_ts = time.time()
            if self._utterance_turn_id is None:
                self._utterance_turn_id = uuid.uuid4().hex
            if len(text.strip()) > 3:
                try:
                    self.thread_bridge.schedule_barge_in(self.barge_in_handler)
                except Exception as e:
                    logger.error(f"[{self._conn_short}] Barge-in error: {e}")

                if self.on_partial_transcript:
                    try:
                        self._utterance_sequence += 1
                        self.on_partial_transcript(
                            text.strip(),
                            lang,
                            speaker_id,
                            self._utterance_turn_id,
                            self._utterance_sequence,
                        )
                    except Exception as e:
                        logger.debug(f"[{self._conn_short}] Partial transcript callback error: {e}")

        def on_final(text: str, lang: str, speaker_id: str | None = None):
            if self._stopped:
                return
            logger.debug(
                f"[{self._conn_short}] Final speech: '{text}' ({lang}) len={len(text.strip())}"
            )

            if len(text.strip()) > 1:
                logger.info(f"[{self._conn_short}] Speech: '{text}' ({lang})")
                turn_id = self._utterance_turn_id or uuid.uuid4().hex
                # Arm the pre-speech guard at finalization so trailing partials of
                # this utterance cannot cancel the turn it is about to spawn.
                self.thread_bridge.arm_turn_guard()
                event = SpeechEvent(
                    event_type=SpeechEventType.FINAL,
                    text=text,
                    language=lang,
                    speaker_id=speaker_id,
                    turn_id=turn_id,
                    sequence=self._utterance_sequence + 1,
                    recognition_start_ts=self._utterance_start_ts,
                    recognition_end_perf=time.perf_counter(),
                )
                self.thread_bridge.queue_speech_result(self.speech_queue, event)
            # Reset utterance start for the next utterance.
            self._utterance_start_ts = None
            self._utterance_turn_id = None
            self._utterance_sequence = 0

        def on_error(error: Any):
            if self._stopped:
                return
            # The Speech SDK invokes cancel callbacks with a
            # SpeechRecognitionCanceledEventArgs, not a string, so pull the
            # human-readable cause out before it travels any further.
            detail = _cancellation_text(error)
            logger.error(f"[{self._conn_short}] Speech error: {detail}")
            error_event = SpeechEvent(event_type=SpeechEventType.ERROR, text=detail)
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
        """Compatibility hook; recognition already runs on Speech SDK threads."""
        self.thread_running = not self._stopped

    def start_recognizer(self) -> None:
        """Start the speech recognizer."""
        if self.recognizer_started or self._stopped:
            return

        try:
            logger.info(
                f"[{self._conn_short}] Starting speech recognizer, push_stream_exists={bool(self.recognizer.push_stream)}"
            )
            self.recognizer.start()
            self.recognizer_started = True
            self.thread_running = True
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

    def stop_stt_timer_for_barge_in(self) -> None:
        """
        Stop any active STT timer during barge-in.

        Called when user interrupts to end current recognition session.
        This signals to the recognizer that the current utterance is complete
        due to user interruption.
        """
        logger.debug(f"[{self._conn_short}] STT timer stopped for barge-in")
        # Signal recognizer to finalize current audio buffer if supported
        if self.recognizer and hasattr(self.recognizer, "finalize_current_utterance"):
            try:
                self.recognizer.finalize_current_utterance()
            except Exception as e:
                logger.debug(f"[{self._conn_short}] Error finalizing utterance: {e}")

    def stop(self) -> None:
        """Stop SDK recognition; propagate failure so its lease is not reused."""
        self._stopped = True
        self.thread_running = False
        self.recognizer_started = False
        self.stop_event.set()
        with self._stop_lock:
            if self._stop_error is not None:
                raise self._stop_error
            if self._stop_complete:
                return
            try:
                if self.recognizer:
                    self.recognizer.stop()
            except Exception as exc:
                self._stop_error = exc
                logger.error("[%s] Error stopping recognizer: %s", self._conn_short, exc)
                raise
            self._stop_complete = True
            logger.info("[%s] Speech SDK recognition stopped", self._conn_short)

    async def stop_async(self, *, timeout_sec: float = 10.0) -> None:
        """Await native stop in owned worker work, withholding the lease on timeout.

        Keep the task alive if the caller is cancelled or its deadline expires:
        cancelling an executor Future cannot terminate a native SDK operation.
        Repeat callers await the same operation, including any recorded failure.
        """
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(
                asyncio.to_thread(self.stop), name=f"cascade-stt-stop-{self._conn_short}"
            )
            self._stop_task.add_done_callback(self._observe_stop_result)
        try:
            await asyncio.wait_for(asyncio.shield(self._stop_task), timeout=timeout_sec)
        except TimeoutError:
            logger.error(
                "[%s] Speech stop acknowledgement timed out after %.1fs; lease withheld",
                self._conn_short,
                timeout_sec,
            )
            raise

    def _observe_stop_result(self, task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "[%s] Native speech stop failed; lease remains withheld: %s",
                self._conn_short,
                task.exception(),
            )


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
        memory_manager: MemoManager | None,
        *,
        response_sender: ResponseSender | None = None,
        transcript_emitter: TranscriptEmitter | None = None,
        on_greeting: Callable[[SpeechEvent], Awaitable[None]] | None = None,
        on_announcement: Callable[[SpeechEvent], Awaitable[None]] | None = None,
        on_user_transcript: Callable[[str, str | None, int | None], Awaitable[None]] | None = None,
        on_tts_request: Callable[[str, SpeechEventType], Awaitable[None]] | None = None,
        thread_bridge: "ThreadBridge | None" = None,
        on_error: Callable[[str], Awaitable[None]] | None = None,
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
            on_tts_request: Callback for TTS playback requests. Signature:
                (text, event_type, *, voice_name, voice_style, voice_rate, voice_pitch) -> None
            thread_bridge: Shared cross-thread bridge.
            on_error: Callback invoked with the raw speech error text so the
                transport layer can classify it and surface it to the client.
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
        self.on_error = on_error
        # Shared cross-thread bridge; used to disarm the pre-speech turn guard
        # once the agent starts speaking / the turn ends.
        self.thread_bridge = thread_bridge

        self.processing_task: asyncio.Task | None = None
        self.current_response_task: asyncio.Task | None = None
        self._stop_task: asyncio.Task | None = None
        self.running = False
        self._stopped = False

        # Turn tracking for telemetry
        self._turn_number: int = 0
        self._active_turn_span: ConversationTurnSpan | None = None
        # perf_counter() of the most recent FINAL recognition (end of user
        # speech). Read by the orchestrator KPI summary to anchor the per-turn
        # "recognition end -> first token / first audio" latencies.
        self._last_recog_end_perf: float | None = None

    async def start(self) -> None:
        """Start the route turn processing loop."""
        if self._stopped:
            raise RuntimeError("Cannot restart a stopped route worker")
        if self.running:
            return

        self.running = True
        self.processing_task = asyncio.create_task(self._processing_loop())

    async def _processing_loop(self) -> None:
        """Main processing loop."""
        while self.running:
            try:
                speech_event = await asyncio.wait_for(self.speech_queue.get(), timeout=1.0)

                try:
                    logger.debug(
                        f"[{self._conn_short}] Routing speech event type={getattr(speech_event, 'event_type', 'unknown')}"
                    )
                    if speech_event.event_type == SpeechEventType.FINAL:
                        # End previous turn if active
                        await self._end_active_turn()
                        # Start new turn
                        await self._process_final_speech(speech_event)
                    elif speech_event.event_type == SpeechEventType.TTS_RESPONSE:
                        # TTS response from orchestrator - use on_tts_request callback
                        # This ensures sequential playback through the unified queue
                        if self.on_tts_request:
                            await self.on_tts_request(
                                speech_event.text,
                                speech_event.event_type,
                                voice_name=speech_event.voice_name,
                                voice_style=speech_event.voice_style,
                                voice_rate=speech_event.voice_rate,
                                voice_pitch=speech_event.voice_pitch,
                            )
                        logger.debug(
                            f"[{self._conn_short}] TTS response processed: {speech_event.text[:50]}..."
                        )
                    elif speech_event.event_type == SpeechEventType.GREETING:
                        # Use on_greeting if available, otherwise fall back to on_tts_request
                        if self.on_greeting:
                            await self.on_greeting(speech_event)
                        elif self.on_tts_request:
                            await self.on_tts_request(
                                speech_event.text,
                                speech_event.event_type,
                                voice_name=speech_event.voice_name,
                                voice_style=speech_event.voice_style,
                                voice_rate=speech_event.voice_rate,
                                voice_pitch=speech_event.voice_pitch,
                            )
                    elif speech_event.event_type in {
                        SpeechEventType.ANNOUNCEMENT,
                        SpeechEventType.STATUS_UPDATE,
                        SpeechEventType.ERROR_MESSAGE,
                    }:
                        # Use on_announcement if available, otherwise fall back to on_tts_request
                        if self.on_announcement:
                            await self.on_announcement(speech_event)
                        elif self.on_tts_request:
                            await self.on_tts_request(
                                speech_event.text,
                                speech_event.event_type,
                                voice_name=speech_event.voice_name,
                                voice_style=speech_event.voice_style,
                                voice_rate=speech_event.voice_rate,
                                voice_pitch=speech_event.voice_pitch,
                            )
                    elif speech_event.event_type == SpeechEventType.ERROR:
                        logger.error(f"[{self._conn_short}] Speech error: {speech_event.text}")
                        if self.on_error:
                            try:
                                await self.on_error(speech_event.text or "")
                            except Exception:
                                logger.debug(
                                    f"[{self._conn_short}] Failed to surface speech error",
                                    exc_info=True,
                                )
                except asyncio.CancelledError:
                    if not self.running or asyncio.current_task().cancelling():
                        raise
                    continue  # Barge-in cancellation
                finally:
                    self.speech_queue.task_done()
            except TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[{self._conn_short}] Processing loop error: {e}")
                break

    async def _end_active_turn(self) -> None:
        """End the currently active turn span if it exists."""
        if self._active_turn_span:
            try:
                await self._active_turn_span.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"[{self._conn_short}] Error closing turn span: {e}")
            finally:
                self._active_turn_span = None

    async def _process_final_speech(self, event: SpeechEvent) -> None:
        """
        Process final speech through orchestrator with turn-level telemetry.

        Creates a ConversationTurnSpan that tracks the full turn lifecycle:
        - STT completion (when this method is called)
        - LLM processing (during orchestrator execution)
        - TTS synthesis (when TTS callback fires)
        """
        # Increment turn counter
        self._turn_number += 1
        event.turn_id = event.turn_id or uuid.uuid4().hex

        # Capture recognition-end (perf clock) so the orchestrator KPI summary
        # can anchor TTFT/TTFB at the moment the user stopped speaking.
        self._last_recog_end_perf = getattr(event, "recognition_end_perf", None)

        # Get session_id from memory manager for correlation
        session_id = (
            getattr(self.memory_manager, "session_id", None) if self.memory_manager else None
        )

        # Create ConversationTurnSpan for end-to-end turn tracking
        # Manually manage span lifecycle to cover async TTS events.
        # Backdate the span to when the user started speaking (first partial) so
        # voice.turn.N.total frames the full STT → LLM → TTS pipeline.
        recognition_start_ts = getattr(event, "recognition_start_ts", None)
        turn = ConversationTurnSpan(
            call_connection_id=self.connection_id,
            session_id=session_id,
            turn_number=self._turn_number,
            transport_type="cascade",
            user_intent_preview=event.text[:50] if event.text else None,
            start_time_ns=int(recognition_start_ts * 1e9) if recognition_start_ts else None,
        )
        await turn.__aenter__()
        self._active_turn_span = turn

        # Record STT complete (we just received the final transcript)
        turn.record_stt_complete(
            text=event.text,
            language=event.language,
        )

        # Draw a real STT recognition span (user started speaking → final) so STT
        # shows as its own timeline line item instead of an unexplained gap.
        if recognition_start_ts:
            turn.add_stt_recognition_span(
                start_ts=recognition_start_ts,
                end_ts=event.timestamp,
                text=event.text,
                language=event.language,
            )

        # Parent the orchestrator work under the turn span so voice.turn.N.total
        # visually frames the whole turn (STT → LLM → TTS) instead of floating as
        # a sibling. trace.use_span activates the turn span as current context
        # without ending it (it stays open for later TTS events / barge-in).
        with trace.use_span(turn.span, end_on_exit=False):
            with tracer.start_as_current_span(
                "route_turn_thread.process_speech",
                kind=SpanKind.INTERNAL,  # INTERNAL for in-process orchestration (not external call)
                attributes={
                    "speech.text": event.text,
                    "speech.language": event.language,
                    "turn.number": self._turn_number,
                },
            ):
                try:
                    if not self.memory_manager:
                        logger.error(f"[{self._conn_short}] No memory manager available")
                        return

                    # Make the STT-allocated ID available to route_turn without
                    # changing the long-standing orchestrator callable signature.
                    # The queue serializes turns, so this value is session-safe.
                    self.memory_manager.set_corememory("current_turn_id", event.turn_id)

                    # Emit user transcript via callback (for transport coordination)
                    if self.on_user_transcript:
                        try:
                            await self.on_user_transcript(
                                event.text,
                                event.turn_id,
                                event.sequence,
                            )
                        except Exception as e:
                            logger.warning(
                                f"[{self._conn_short}] Failed to invoke on_user_transcript: {e}"
                            )

                    # Legacy: emit via transcript emitter (deprecated)
                    if self.transcript_emitter:
                        try:
                            await self.transcript_emitter.emit_user_transcript(
                                event.text,
                                turn_id=event.turn_id,
                            )
                        except Exception as e:
                            logger.warning(
                                f"[{self._conn_short}] Failed to emit user transcript: {e}"
                            )

                    # Call orchestrator (LLM processing happens here)
                    if self.orchestrator_func:
                        # Record LLM start (approximation - actual first token comes from agent)
                        turn.record_tts_start()  # TTS will start streaming during orchestrator

                        coro = self.orchestrator_func(
                            cm=self.memory_manager,
                            transcript=event.text,
                        )
                        if coro:
                            self.current_response_task = asyncio.create_task(coro)
                            await asyncio.shield(self.current_response_task)

                except asyncio.CancelledError:
                    logger.info(
                        f"[{self._conn_short}] Orchestrator processing cancelled (turn {self._turn_number})"
                    )
                    raise
                except Exception as e:
                    logger.error(
                        f"[{self._conn_short}] Error processing speech with orchestrator: {e}"
                    )
                finally:
                    # Turn finished (or errored) -> ensure the pre-speech guard is
                    # released even when the turn produced no audio at all.
                    if self.thread_bridge is not None:
                        self.thread_bridge.disarm_turn_guard()
                    if self.current_response_task and not self.current_response_task.done():
                        if not self.current_response_task.cancelling():
                            self.current_response_task.cancel()
                        await asyncio.gather(self.current_response_task, return_exceptions=True)
                    self.current_response_task = None
                    # Close voice.turn.N.total now that the response is fully generated
                    # and TTS has been dispatched. The core KPIs (ttft/ttfb/synth/wall)
                    # are already stamped during orchestration via record_turn_kpis, so
                    # this keeps the turn span tightly scoped (recognition start ->
                    # response done) and sequential instead of lingering through the idle
                    # gap until the next utterance. Barge-in cancels the task above and
                    # still routes through this finally.
                    await self._end_active_turn()

    def record_llm_first_token(self) -> None:
        """Record LLM first token timing on the active turn span (call from agent)."""
        if self._active_turn_span:
            self._active_turn_span.record_llm_first_token()

    def record_llm_complete(
        self,
        total_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        response_text: str | None = None,
    ) -> None:
        """Record LLM completion timing on the active turn span."""
        if self._active_turn_span:
            self._active_turn_span.record_llm_complete(
                total_ms=total_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                response_text=response_text,
            )

    def record_tts_first_audio(self) -> None:
        """Record TTS first audio timing on the active turn span (call from TTS callback)."""
        # Agent is now speaking -> trailing-partial window is over; allow genuine
        # barge-in for the rest of this turn.
        if self.thread_bridge is not None:
            self.thread_bridge.disarm_turn_guard()
        if self._active_turn_span:
            self._active_turn_span.record_tts_first_audio()

    def record_tts_complete(self, total_ms: float | None = None) -> None:
        """Record TTS completion on the active turn span."""
        if self._active_turn_span:
            self._active_turn_span.record_tts_complete(total_ms=total_ms)

    def add_turn_metadata(self, key: str, value: Any) -> None:
        """Attach a KPI value to the active turn span (turn.metadata.<key>)."""
        if self._active_turn_span:
            self._active_turn_span.add_metadata(key, value)

    def record_turn_kpis(
        self,
        *,
        ttft_ms: float | None = None,
        ttfb_ms: float | None = None,
        synth_ms: float | None = None,
        stt_ms: float | None = None,
        llm_ttft_ms: float | None = None,
        llm_total_ms: float | None = None,
        tts_total_ms: float | None = None,
        turn_wall_ms: float | None = None,
        agent_name: str | None = None,
        latency_anchor: str | None = None,
        model: str | None = None,
    ) -> None:
        """Stamp the structured per-turn latency profile on the active turn span."""
        if self._active_turn_span:
            self._active_turn_span.record_turn_kpis(
                ttft_ms=ttft_ms,
                ttfb_ms=ttfb_ms,
                synth_ms=synth_ms,
                stt_ms=stt_ms,
                llm_ttft_ms=llm_ttft_ms,
                llm_total_ms=llm_total_ms,
                tts_total_ms=tts_total_ms,
                turn_wall_ms=turn_wall_ms,
                agent_name=agent_name,
                latency_anchor=latency_anchor,
                model=model,
            )

    @property
    def turn_number(self) -> int:
        """Current turn number for external reference."""
        return self._turn_number

    @property
    def last_recog_end_perf(self) -> float | None:
        """perf_counter() of the last finalized recognition (end of user speech)."""
        return self._last_recog_end_perf

    @property
    def has_active_response(self) -> bool:
        """Whether a response task is currently running and safe to interrupt."""
        return self.current_response_task is not None and not self.current_response_task.done()

    async def cancel_current_processing(self) -> None:
        """Cancel current processing for barge-in."""
        try:
            # End active turn span on barge-in
            await self._end_active_turn()

            # Clear speech queue
            cleared_count = 0
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                    self.speech_queue.task_done()
                    cleared_count += 1
                except asyncio.QueueEmpty:
                    break

            if cleared_count > 0:
                logger.debug(f"[{self._conn_short}] Cleared {cleared_count} events during barge-in")

            # Cancel current response task
            if self.current_response_task and not self.current_response_task.done():
                await cancel_and_join([self.current_response_task])
            self.current_response_task = None

        except Exception as e:
            logger.error(f"[{self._conn_short}] Error cancelling processing: {e}")
            raise

    async def stop(self) -> None:
        """Await one retained close, keeping unacknowledged producers quarantined."""
        if self._stop_task is None:
            self._stopped = True
            self.running = False
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        try:
            await cancel_and_join(
                task for task in (self.current_response_task, self.processing_task) if task
            )
        finally:
            await self._end_active_turn()
            await self._clear_speech_queue()

    async def _clear_speech_queue(self) -> None:
        """Clear remaining events from the speech queue."""
        try:
            cleared_count = 0
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                    self.speech_queue.task_done()
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
        on_barge_in: Callable[[], Awaitable[None]] | None = None,
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
        self.current_playback_task: asyncio.Task | None = None

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
            try:
                await asyncio.sleep(0.1)
            finally:
                self.barge_in_active.clear()


__all__ = [
    "SpeechEvent",
    "SpeechEventType",
    "ThreadBridge",
    "SpeechSDKThread",
    "RouteTurnThread",
    "BargeInController",
    "ResponseSender",
    "TranscriptEmitter",
]
