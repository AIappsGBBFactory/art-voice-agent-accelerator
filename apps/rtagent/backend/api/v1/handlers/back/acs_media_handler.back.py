"""
ACS Media Handler - Simplified & Maintainable Implementation
===========================================================

This refactored implementation breaks down the complex media handler into focused,
maintainable components while preserving the critical barge-in logic and event looping.

Key Design Principles:
- Separation of concerns across focused classes
- Preserves the three-thread architecture for optimal performance  
- Clean event loop handling for barge-in interruptions
- Simplified tracing with consistent patterns
- Maintainable async task lifecycle management
"""

import asyncio
import json
import threading
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass

from azure.communication.callautomation import TextSource
from fastapi import WebSocket
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from apps.rtagent.backend.settings import GREETING
from apps.rtagent.backend.src.shared_ws import send_response_to_acs
from apps.rtagent.backend.src.utils.tracing import (
    trace_acs_operation,
    trace_acs_dependency,
)
from src.speech.speech_recognizer import StreamingSpeechRecognizerFromBytes
from src.stateful.state_managment import MemoManager
from utils.ml_logging import get_logger

logger = get_logger("handlers.acs_media_handler")
tracer = trace.get_tracer(__name__)


def get_current_time() -> float:
    """Get current time for consistent timing measurements."""
    return time.time()


def safe_set_span_attributes(span_context, attributes: dict):
    """Safely set span attributes without accessing private attributes."""
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attributes(attributes)
    except Exception as e:
        logger.debug(f"Failed to set span attributes: {e}")


@dataclass
class BargeInState:
    """Simple state management for barge-in detection."""

    event: threading.Event

    def __post_init__(self):
        self.event = threading.Event()

    def trigger(self) -> bool:
        """Trigger barge-in if not already active. Returns True if newly triggered."""
        if self.event.is_set():
            return False
        self.event.set()
        return True

    def clear(self):
        """Clear barge-in state for new speech processing."""
        self.event.clear()

    def is_active(self) -> bool:
        """Check if barge-in is currently active."""
        return self.event.is_set()


class SpeechCallbacks:
    """
    Speech recognition callbacks that bridge to the main event loop.

    This class encapsulates the critical cross-thread communication
    required for real-time barge-in detection and speech processing.
    """

    def __init__(
        self,
        main_loop: asyncio.AbstractEventLoop,
        barge_in_state: BargeInState,
        speech_queue: asyncio.Queue,
        stop_playback_callback: Callable,
    ):
        self.main_loop = main_loop
        self.barge_in_state = barge_in_state
        self.speech_queue = speech_queue
        self.stop_playback_callback = stop_playback_callback

    def on_partial(self, text: str, lang: str, speaker_id: Optional[str] = None):
        """Handle partial speech recognition - IMMEDIATE barge-in trigger."""
        speaker_info = f" (Speaker: {speaker_id})" if speaker_id else ""
        logger.info(f"🗣️ User (partial) in {lang}: {text}{speaker_info}")

        # Only trigger barge-in if not already active
        if self.barge_in_state.trigger():
            logger.info("🚨 Barge-in detected - stopping current playback")

            # Schedule immediate playback cancellation on main loop
            if self.main_loop and not self.main_loop.is_closed():
                try:
                    # Add minimal tracing for barge-in latency measurement
                    with tracer.start_as_current_span(
                        "speech.barge_in_detected",
                        kind=SpanKind.INTERNAL,
                        attributes={
                            "speech.partial_text": text[:100],  # Truncate for privacy
                            "speech.language": lang,
                            "speech.speaker_id": speaker_id,
                            "barge_in.trigger_time": get_current_time(),
                        },
                    ):
                        asyncio.run_coroutine_threadsafe(
                            self.stop_playback_callback(), self.main_loop
                        )
                        logger.info("✅ Barge-in handling scheduled successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to schedule barge-in handling: {e}")

    def on_final(self, text: str, lang: str, speaker_id: Optional[str] = None):
        """Handle final speech recognition - queue for AI processing."""
        speaker_info = f" (Speaker: {speaker_id})" if speaker_id else ""
        logger.info(f"🧾 User (final) in {lang}: {text}{speaker_info}")

        # Clear barge-in state for new processing
        self.barge_in_state.clear()

        # Queue final speech for AI processing
        if self.main_loop and not self.main_loop.is_closed():
            try:
                # Add tracing for final speech processing
                with tracer.start_as_current_span(
                    "speech.final_recognized",
                    kind=SpanKind.INTERNAL,
                    attributes={
                        "speech.text_length": len(text),
                        "speech.language": lang,
                        "speech.speaker_id": speaker_id,
                        "speech.final_time": get_current_time(),
                    },
                ):
                    asyncio.run_coroutine_threadsafe(
                        self.speech_queue.put(("final", text)), self.main_loop
                    )
                    logger.info("📋 Final speech queued for processing")
            except Exception as e:
                logger.error(f"❌ Failed to queue final speech: {e}")

    def on_cancel(self, event):
        """Handle speech recognition cancellation."""
        logger.warning(f"🚫 Recognition canceled: {event}")


class TurnProcessor:
    """
    Handles the conversation turn processing loop.

    This class manages the route_turn_loop that processes final speech
    results and coordinates with the AI orchestrator.
    """

    def __init__(
        self,
        orchestrator_func: Callable,
        websocket: WebSocket,
        memory_manager: MemoManager,
        call_connection_id: str,
        session_id: str,
    ):
        self.orchestrator_func = orchestrator_func
        self.websocket = websocket
        self.memory_manager = memory_manager
        self.call_connection_id = call_connection_id
        self.session_id = session_id

        self.speech_queue: asyncio.Queue = asyncio.Queue()
        self.playback_task: Optional[asyncio.Task] = None
        self.processing_task: Optional[asyncio.Task] = None
        self.stopped = False

    async def start_processing_loop(self):
        """Start the main conversation turn processing loop."""
        self.processing_task = asyncio.create_task(self._processing_loop())
        logger.info("✅ Turn processing loop started")

    async def _processing_loop(self):
        """Main processing loop for conversation turns."""
        with trace_acs_operation(
            tracer,
            logger,
            "turn_processing_loop",
            call_connection_id=self.call_connection_id,
        ) as op:
            op.log_info("Turn processing loop started")

            try:
                while not self.stopped:
                    try:
                        # Wait for speech input with short timeout for responsiveness
                        loop_start_time = get_current_time()
                        kind, text = await asyncio.wait_for(
                            self.speech_queue.get(), timeout=0.1
                        )

                        queue_wait_time = get_current_time() - loop_start_time
                        op.log_info(
                            f"Processing {kind} turn: {text[:50]}... (queue_wait: {queue_wait_time:.3f}s)"
                        )

                        # Cancel any existing playback
                        await self._cancel_current_playback()

                        # Start new AI processing with timing
                        self.playback_task = asyncio.create_task(
                            self._route_and_playback(kind, text)
                        )

                        # Mark queue task as done
                        self.speech_queue.task_done()

                    except asyncio.TimeoutError:
                        # Short sleep to prevent tight loop
                        await asyncio.sleep(0.01)
                        continue
                    except Exception as e:
                        op.log_error(f"Error in processing loop: {e}")
                        await asyncio.sleep(0.1)

            except Exception as e:
                op.set_error(f"Turn processing loop failed: {e}")
            finally:
                op.log_info("Turn processing loop ended")

    async def _cancel_current_playback(self):
        """Cancel any currently running playback task."""
        if self.playback_task and not self.playback_task.done():
            logger.info("🛑 Cancelling current playback task")
            self.playback_task.cancel()
            try:
                await asyncio.wait_for(self.playback_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            finally:
                self.playback_task = None

    async def _route_and_playback(self, kind: str, text: str):
        """Route conversation turn to orchestrator and handle playback."""
        with trace_acs_dependency(
            tracer,
            logger,
            "orchestration",
            "route_conversation_turn",
            call_connection_id=self.call_connection_id,
        ) as dep_op:
            dep_op.log_info(f"Routing {kind} turn to orchestrator")

            try:
                # Add span attributes for orchestration metrics
                orchestration_start_time = get_current_time()

                # Call the orchestrator function
                await asyncio.wait_for(
                    self.orchestrator_func(
                        cm=self.memory_manager,
                        transcript=text,
                        ws=self.websocket,
                        caller=kind,
                    ),
                    timeout=30.0,
                )

                orchestration_duration = get_current_time() - orchestration_start_time

                # Add success metrics to span
                safe_set_span_attributes(
                    dep_op,
                    {
                        "orchestration.duration_seconds": orchestration_duration,
                        "orchestration.text_length": len(text),
                        "orchestration.turn_type": kind,
                        "orchestration.success": True,
                    },
                )

                dep_op.log_info(
                    f"Orchestration completed successfully in {orchestration_duration:.3f}s"
                )

            except asyncio.CancelledError:
                dep_op.log_info("Orchestration cancelled (barge-in)")
                safe_set_span_attributes(dep_op, {"orchestration.cancelled": True})
                raise
            except asyncio.TimeoutError:
                dep_op.set_error("Orchestration timed out")
                logger.error("Orchestration timed out after 30 seconds")
                safe_set_span_attributes(dep_op, {"orchestration.timeout": True})
                raise
            except Exception as e:
                dep_op.set_error(f"Orchestration failed: {e}")
                safe_set_span_attributes(
                    dep_op,
                    {
                        "orchestration.error": str(e),
                        "orchestration.success": False,
                    },
                )
                raise

    async def stop_playback_immediately(self):
        """Immediately stop current playback (called by barge-in)."""
        await self._cancel_current_playback()

        # Clear any pending speech in the queue
        while not self.speech_queue.empty():
            try:
                self.speech_queue.get_nowait()
                self.speech_queue.task_done()
            except asyncio.QueueEmpty:
                break

        logger.info("🧹 Playback stopped and queue cleared")

    async def stop(self):
        """Stop the turn processor and clean up."""
        logger.info("Stopping turn processor")
        self.stopped = True

        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass

        await self._cancel_current_playback()
        logger.info("✅ Turn processor stopped")


class MediaProcessor:
    """
    Handles WebSocket media message processing and audio streaming.

    This class focuses specifically on ACS media protocol handling
    and audio data flow to the speech recognizer.
    """

    def __init__(
        self,
        recognizer: StreamingSpeechRecognizerFromBytes,
        websocket: WebSocket,
        call_connection_id: str,
    ):
        self.recognizer = recognizer
        self.websocket = websocket
        self.call_connection_id = call_connection_id
        self.recognizer_started = False

    async def handle_media_message(self, stream_data: str):
        """Process incoming WebSocket message from ACS."""
        try:
            data = json.loads(stream_data)
            kind = data.get("kind")

            if kind == "AudioMetadata":
                with tracer.start_as_current_span(
                    "media.audio_metadata_received",
                    kind=SpanKind.INTERNAL,
                    attributes={
                        "media.metadata_received_time": get_current_time(),
                        "media.kind": kind,
                    },
                ):
                    await self._handle_audio_metadata()
            elif kind == "AudioData":
                # Only trace audio data periodically to avoid span spam
                audio_data_section = data.get("audioData", {})
                if not audio_data_section.get("silent", True):
                    await self._handle_audio_data(data)

        except Exception as e:
            logger.error(f"Error processing media message: {e}")
            # Add error span for debugging
            with tracer.start_as_current_span(
                "media.message_processing_error",
                kind=SpanKind.INTERNAL,
                attributes={
                    "error.type": type(e).__name__,
                    "error.message": str(e),
                },
            ) as span:
                span.set_status(Status(StatusCode.ERROR, str(e)))

    async def _handle_audio_metadata(self):
        """Handle AudioMetadata message - ACS is ready for streaming."""
        logger.info("📡 Received AudioMetadata - ACS ready for audio streaming")

        if not self.recognizer_started:
            with tracer.start_as_current_span(
                "media.speech_recognizer_start",
                kind=SpanKind.INTERNAL,
                attributes={
                    "recognizer.trigger": "audio_metadata",
                    "recognizer.start_time": get_current_time(),
                },
            ):
                logger.info("🎤 Starting speech recognizer on first AudioMetadata")
                self.recognizer_started = True

    async def _handle_audio_data(self, data: dict):
        """Handle AudioData message - process incoming audio."""
        audio_data_section = data.get("audioData", {})

        # Skip silent audio frames
        if audio_data_section.get("silent", True):
            return

        # Process audio bytes
        audio_bytes = audio_data_section.get("data")
        if audio_bytes:
            if isinstance(audio_bytes, str):
                import base64

                audio_bytes = base64.b64decode(audio_bytes)

            # Send audio to speech recognizer
            self.recognizer.write_bytes(audio_bytes)

    async def send_stop_audio_command(self):
        """Send stop audio command to ACS."""
        try:
            stop_audio_data = {
                "Kind": "StopAudio",
                "AudioData": None,
                "StopAudio": {},
            }
            await self.websocket.send_text(json.dumps(stop_audio_data))
            logger.info("🛑 Stop audio command sent to ACS")
        except Exception as e:
            logger.warning(f"Failed to send stop audio command: {e}")


class ACSMediaHandler:
    """
    Simplified ACS Media Handler with clean separation of concerns.

    This handler maintains the critical three-thread architecture while
    breaking down responsibilities into focused, maintainable components:

    - SpeechCallbacks: Cross-thread communication for barge-in
    - TurnProcessor: Conversation turn processing and AI orchestration
    - MediaProcessor: WebSocket media protocol and audio streaming
    - BargeInState: Simple state management for interruptions

    Key preserved features:
    - Sub-50ms barge-in response time
    - Clean async task lifecycle management
    - Thread-safe speech processing queue
    - Comprehensive tracing and logging
    """

    def __init__(
        self,
        ws: WebSocket,
        orchestrator_func: Callable,
        call_connection_id: str,
        recognizer: Optional[StreamingSpeechRecognizerFromBytes] = None,
        cm: Optional[MemoManager] = None,
        session_id: Optional[str] = None,
        greeting_text: str = GREETING,
        enable_tracing: bool = True,
    ):
        """Initialize the simplified ACS media handler."""

        # Core dependencies
        self.incoming_websocket = ws
        self.orchestrator_func = orchestrator_func
        self.call_connection_id = call_connection_id
        self.session_id = session_id or call_connection_id
        self.cm = cm
        self.greeting_text = greeting_text
        self.enable_tracing = enable_tracing

        # Initialize speech recognizer
        self.recognizer = recognizer or StreamingSpeechRecognizerFromBytes(
            candidate_languages=["en-US", "fr-FR", "de-DE", "es-ES", "it-IT"],
            vad_silence_timeout_ms=800,
            audio_format="pcm",
        )

        # State management
        self.barge_in_state = BargeInState()
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.stopped = False

        # Component initialization
        self.turn_processor = TurnProcessor(
            orchestrator_func=orchestrator_func,
            websocket=ws,
            memory_manager=cm,
            call_connection_id=call_connection_id,
            session_id=self.session_id,
        )

        self.media_processor = MediaProcessor(
            recognizer=self.recognizer,
            websocket=ws,
            call_connection_id=call_connection_id,
        )

        # Speech callbacks will be initialized when we have the main loop
        self.speech_callbacks: Optional[SpeechCallbacks] = None

        logger.info(
            f"✅ Simplified ACS Media Handler initialized - "
            f"call_id: {self.call_connection_id}, session_id: {self.session_id}"
        )

    async def start_recognizer(self):
        """Start the media handler and all its components."""
        with trace_acs_operation(
            tracer,
            logger,
            "start_media_handler",
            call_connection_id=self.call_connection_id,
        ) as op:
            op.log_info("Starting ACS Media Handler")

            handler_start_time = get_current_time()

            # Capture the main event loop
            self.main_loop = asyncio.get_running_loop()

            # Initialize speech callbacks with the main loop
            self.speech_callbacks = SpeechCallbacks(
                main_loop=self.main_loop,
                barge_in_state=self.barge_in_state,
                speech_queue=self.turn_processor.speech_queue,
                stop_playback_callback=self._handle_barge_in,
            )

            # Configure speech recognizer callbacks
            recognizer_setup_start = get_current_time()
            self.recognizer.set_partial_result_callback(
                self.speech_callbacks.on_partial
            )
            self.recognizer.set_final_result_callback(self.speech_callbacks.on_final)
            self.recognizer.set_cancel_callback(self.speech_callbacks.on_cancel)

            # Start speech recognition with timing
            self.recognizer.start()
            recognizer_setup_duration = get_current_time() - recognizer_setup_start
            op.log_info(
                f"Speech recognizer started in {recognizer_setup_duration:.3f}s"
            )

            # Start conversation processing loop
            await self.turn_processor.start_processing_loop()

            # Play greeting
            greeting_start_time = get_current_time()
            await self._play_greeting()
            greeting_duration = get_current_time() - greeting_start_time

            total_startup_time = get_current_time() - handler_start_time

            # Add startup metrics to span
            safe_set_span_attributes(
                op,
                {
                    "startup.total_duration_seconds": total_startup_time,
                    "startup.recognizer_setup_duration": recognizer_setup_duration,
                    "startup.greeting_duration": greeting_duration,
                    "startup.success": True,
                },
            )

            op.log_info(
                f"ACS Media Handler started successfully in {total_startup_time:.3f}s"
            )

    async def handle_media_message(self, stream_data: str):
        """Handle incoming WebSocket media messages."""
        await self.media_processor.handle_media_message(stream_data)

    async def _handle_barge_in(self):
        """Handle barge-in events - stop current playback immediately."""
        with tracer.start_as_current_span(
            "barge_in.handle_interruption",
            kind=SpanKind.INTERNAL,
            attributes={
                "barge_in.start_time": get_current_time(),
            },
        ) as span:
            barge_in_start_time = get_current_time()
            logger.info("🚨 Handling barge-in - stopping playback")

            # Stop current playback and clear queue
            await self.turn_processor.stop_playback_immediately()

            # Send stop audio command to ACS
            await self.media_processor.send_stop_audio_command()

            barge_in_duration = get_current_time() - barge_in_start_time

            span.set_attributes(
                {
                    "barge_in.duration_seconds": barge_in_duration,
                    "barge_in.success": True,
                }
            )

            logger.info(f"✅ Barge-in handled successfully in {barge_in_duration:.3f}s")

    async def _play_greeting(self):
        """Play the initial greeting message."""
        with tracer.start_as_current_span(
            "greeting.play_initial_message",
            kind=SpanKind.CLIENT,
            attributes={
                "greeting.text_length": len(self.greeting_text),
                "greeting.voice": "en-US-EmmaNeural",
                "greeting.start_time": get_current_time(),
            },
        ) as span:
            try:
                text_source = TextSource(
                    text=self.greeting_text, voice_name="en-US-EmmaNeural"
                )

                greeting_send_start = get_current_time()
                await send_response_to_acs(self.incoming_websocket, text_source)
                greeting_send_duration = get_current_time() - greeting_send_start

                span.set_attributes(
                    {
                        "greeting.send_duration_seconds": greeting_send_duration,
                        "greeting.success": True,
                    }
                )

                logger.info(
                    f"🎵 Greeting played in {greeting_send_duration:.3f}s: {self.greeting_text}"
                )

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attributes(
                    {
                        "greeting.error": str(e),
                        "greeting.success": False,
                    }
                )
                logger.error(f"Failed to play greeting: {e}")
                raise

    async def stop(self):
        """Stop the handler and clean up all resources."""
        with trace_acs_operation(
            tracer,
            logger,
            "stop_media_handler",
            call_connection_id=self.call_connection_id,
        ) as op:
            op.log_info("Stopping ACS Media Handler")

            self.stopped = True

            # Stop speech recognizer
            if self.recognizer:
                self.recognizer.stop()
                op.log_info("Speech recognizer stopped")

            # Stop turn processor
            await self.turn_processor.stop()

            op.log_info("ACS Media Handler stopped successfully")
