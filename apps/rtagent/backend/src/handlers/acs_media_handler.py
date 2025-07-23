import asyncio
import json
import threading
from typing import Optional

from azure.communication.callautomation import (
    TextSource,
)
from fastapi import WebSocket
from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.src.orchestration.orchestrator import route_turn
from apps.rtagent.backend.src.shared_ws import send_response_to_acs, broadcast_message
from apps.rtagent.backend.settings import GREETING
from src.enums.stream_modes import StreamMode
from src.speech.speech_recognizer import StreamingSpeechRecognizerFromBytes
from utils.ml_logging import get_logger
from utils.trace_context import TraceContext
from src.enums.monitoring import SpanAttr

logger = get_logger("handlers.acs_media_handler")


class NoOpTraceContext:
    """
    No-operation context manager that provides the same interface as TraceContext
    but performs no actual tracing operations.
    """
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def set_attribute(self, key, value):
        # No-op for compatibility with TraceContext
        pass


class ACSMediaHandler:
    def __init__(
        self,
        ws: WebSocket,
        recognizer: StreamingSpeechRecognizerFromBytes = None,
        cm: MemoManager = None,
        call_connection_id: str = None,
        session_id: str = None,
        enable_tracing: bool = True,
    ):
        self.recognizer = recognizer or StreamingSpeechRecognizerFromBytes(
            candidate_languages=["en-US", "fr-FR", "de-DE", "es-ES", "it-IT"],
            vad_silence_timeout_ms=800,
            audio_format="pcm",
        )

        self.incoming_websocket = ws
        self.cm = cm
        self.route_turn_queue = asyncio.Queue()

        # Store the event loop reference from the main thread
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.playback_task: Optional[asyncio.Task] = None
        self.route_turn_task: Optional[asyncio.Task] = None
        self.stopped = False

        self.latency_tool = getattr(ws.state, "lt", None)
        self.redis_mgr = getattr(ws.app.state, "redis", None)

        # Thread-safe event for barge-in detection
        self._barge_in_event = threading.Event()
        
        # Track recognizer initialization state
        self._recognizer_started = False

        # Set tracing context from parameters with fallbacks
        self.call_connection_id = (
            call_connection_id or 
            getattr(ws.state, "call_connection_id", None) or
            (ws.headers.get("x-call-connection-id") if hasattr(ws, 'headers') else None)
        )
        self.session_id = (
            session_id or 
            getattr(ws.state, "session_id", None) or
            (ws.headers.get("x-session-id") if hasattr(ws, 'headers') else None)
        )
        
        # Store tracing configuration
        self.enable_tracing = enable_tracing

        logger.info(f"ACSMediaHandler initialized - call_id: {self.call_connection_id}, session_id: {self.session_id}, tracing: {self.enable_tracing}")

    def _create_trace_context(self, name: str, **kwargs):
        """
        Create a TraceContext or NoOpTraceContext based on the enable_tracing setting.
        This provides consistent tracing behavior throughout the handler.
        """
        if self.enable_tracing:
            return TraceContext(
                name=name,
                call_connection_id=self.call_connection_id,
                session_id=self.session_id,
                **kwargs
            )
        else:
            return NoOpTraceContext()

    def _get_trace_metadata(self, operation: str, **kwargs) -> dict:
        """
        Create standardized trace metadata for consistent monitoring.
        Only includes essential attributes to minimize overhead.
        """
        base_metadata = {"operation": operation}
        
        # Add optional attributes if they provide value
        if kwargs:
            # Limit metadata size to prevent performance impact
            filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
            base_metadata.update(filtered_kwargs)
            
        return base_metadata

    async def start_recognizer(self):
        """
        Initialize and start the speech recognizer with proper event loop handling.
        """
        with self._create_trace_context(
            name="acs_media_handler.start_recognizer",
            metadata=self._get_trace_metadata("recognizer_initialization")
        ):
            try:
                # Capture the current event loop for thread-safe operations
                self.main_loop = asyncio.get_running_loop()
                logger.info(f"Captured main event loop: {self.main_loop}")

                # Attach event handlers
                self.recognizer.set_partial_result_callback(self.on_partial)
                self.recognizer.set_final_result_callback(self.on_final)
                self.recognizer.set_cancel_callback(self.on_cancel)

                # Prepare the recognizer (this sets up the Speech SDK components)
                self.recognizer.prepare_start()

                # Start continuous recognition in a background thread
                self.recognizer.speech_recognizer.start_continuous_recognition_async().get()
                logger.info("✅ Speech recognizer started successfully")

                self.route_turn_task = asyncio.create_task(self.route_turn_loop())
                # Fire greeting playback - it handles its own async task creation
                logger.info(f"🎤 Playing greeting: {GREETING}")
                await broadcast_message(
                    connected_clients=self.incoming_websocket.app.state.clients,
                    message=GREETING,
                    sender="Assistant",
                )
                self.play_greeting()

            except Exception as e:
                logger.error(f"❌ Failed to start recognizer: {e}", exc_info=True)
                raise

    async def handle_media_message(self, stream_data):
        """
        Process incoming WebSocket message from ACS.
        Expects JSON with kind == "AudioData" and base64-encoded audio bytes.
        Note: This method is called frequently and uses lightweight tracing to minimize overhead.
        """
        # Use lightweight metadata only for audio processing traces
        with self._create_trace_context(
            name="acs_media_handler.handle_media_message",
            metadata=self._get_trace_metadata("audio_processing", lightweight=True)
        ):
            try:
                
                data = json.loads(stream_data)
                kind = data.get("kind")
                if kind == "AudioMetadata":
                    # Handle AudioMetadata event - this indicates ACS is ready to send audio
                    logger.info("📡 Received AudioMetadata - ACS is ready for audio streaming")
                    
                    # Start the recognizer if not already started (only once, on first AudioMetadata)
                    if not self._recognizer_started:
                        logger.info("🎤 Starting speech recognizer on first AudioMetadata event")
                        
                        # Set trace attributes for recognizer initialization timing
                        with self._create_trace_context(
                            "acs_media_handler.recognizer_initialization_on_audio_metadata"
                        ) as trace:
                            try:
                                await self.start_recognizer()
                                self._recognizer_started = True
                                trace.set_attribute("recognizer.started_on_audio_metadata", True)
                                trace.set_attribute("recognizer.initialization_timing", "optimal")
                                
                                logger.info("✅ Speech recognizer started successfully on AudioMetadata")
                            except Exception as e:
                                trace.set_attribute("recognizer.initialization_error", str(e))
                                logger.error(f"❌ Failed to start recognizer on AudioMetadata: {e}")
                                raise



                    # Start route_turn background processor
                    if not self.route_turn_task or self.route_turn_task.done():
                        self.route_turn_task = asyncio.create_task(self.route_turn_loop())
                        logger.info("✅ Route turn loop started")

                elif kind == "AudioData":
                    audio_data_section = data.get("audioData", {})
                    if not audio_data_section.get("silent", True):
                        audio_bytes = audio_data_section.get("data")
                        if audio_bytes:
                            # If audio is base64-encoded, decode it
                            if isinstance(audio_bytes, str):
                                import base64

                                audio_bytes = base64.b64decode(audio_bytes)
                            self.recognizer.write_bytes(audio_bytes)
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}", exc_info=True)

    def play_greeting(
        self,
        greeting_text: str = GREETING,
    ):
        """
        Send a greeting message to ACS using TTS.
        For Transcription mode, the greeting is played via the CallConnected handler
        """
        with self._create_trace_context(
            name="acs_media_handler.play_greeting",
            metadata=self._get_trace_metadata("greeting_playback", greeting_length=len(greeting_text))
        ):
            try:

                # Send the greeting text to ACS for TTS playback
                self.playback_task = asyncio.create_task(
                    send_response_to_acs(
                        ws=self.incoming_websocket,
                        text=greeting_text,
                        blocking=False,
                        latency_tool=self.latency_tool,
                        stream_mode=StreamMode.MEDIA,
                    )
                )
            except Exception as e:
                logger.error(f"Failed to play greeting: {e}", exc_info=True)

    def on_partial(self, text, lang):
        """
        Handle partial speech recognition results.
        This method is called from the Speech SDK's thread, so we need thread-safe async handling.
        Note: Tracing is intentionally lightweight here due to high frequency calls.
        """
        logger.debug(f"🗣️ User (partial) in {lang}: {text}")
        
        # Start latency measurement for barge-in detection
        # latency_tool = self.latency_tool
        # latency_tool.start("barge_in")
        
        # Set the barge-in event flag immediately
        # Only proceed with barge-in handling if this is a new event
        if self._barge_in_event.is_set():
            logger.info("⏭️ Barge-in already detected. Continuing...")
            return
        
        self._barge_in_event.set()

        # Thread-safe async operation scheduling
        if self.main_loop and not self.main_loop.is_closed():
            try:
                # Schedule barge-in handling on the main event loop
                # Note: We avoid TraceContext here to minimize thread-crossing overhead
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_barge_in_async(), self.main_loop
                )
                logger.info("🚨 Barge-in handling scheduled successfully")
            except Exception as e:
                logger.error(f"❌ Failed to schedule barge-in handling: {e}")
        else:
            logger.warning("⚠️ No main event loop available for barge-in handling")

    def on_final(self, text, lang):
        """
        Handle final speech recognition results.
        This method is called from the Speech SDK's thread, so we need thread-safe async handling.
        Note: Tracing is intentionally lightweight here due to high frequency calls.
        """
        logger.info(f"🧾 User (final) in {lang}: {text}")

        # Clear the barge-in event flag
        self._barge_in_event.clear()
        # Thread-safe queue operation
        if self.main_loop and not self.main_loop.is_closed():
            try:
                # Schedule final result handling on the main event loop
                # Note: We avoid TraceContext here to minimize thread-crossing overhead
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_final_async(text), self.main_loop
                )
                logger.info("📋 Final result handling scheduled successfully")
            except Exception as e:
                logger.error(f"❌ Failed to schedule final result handling: {e}")
        else:
            logger.warning("⚠️ No main event loop available for final result handling")

    def on_cancel(self, evt):
        """Handle recognition cancellation events."""
        logger.warning(f"🚫 Recognition canceled: {evt}")
        self.stopped = True

    async def _handle_barge_in_async(self):
        """
        Async handler for barge-in events, running on the main event loop.
        """
        with self._create_trace_context(
            name="acs_media_handler.handle_barge_in",
            metadata=self._get_trace_metadata("barge_in_processing")
        ):
            try:
                logger.info("🚫 User barge-in detected, stopping playback")
                # await broadcast_message(
                #     connected_clients=self.incoming_websocket.app.state.clients,
                #     message="User has barged in, stopping playback.",
                #     sender="System",
                # )
                # Cancel current playback task if running
                if self.playback_task and not self.playback_task.done():
                    logger.info("Cancelling playback task due to barge-in")
                    self.playback_task.cancel()
                    try:
                        await self.playback_task
                    except asyncio.CancelledError:
                        logger.info("✅ Playback task cancelled successfully")

                # Send stop audio command to ACS
                await self.send_stop_audio()
                self.latency_tool.stop("barge_in", self.redis_mgr)
            except Exception as e:
                logger.error(f"❌ Error in barge-in handling: {e}", exc_info=True)

    async def _handle_final_async(self, text: str):
        """
        Async handler for final speech results, running on the main event loop.
        """
        with self._create_trace_context(
            name="acs_media_handler.handle_final_result",
            metadata=self._get_trace_metadata("final_speech_processing", text_length=len(text))
        ):
            try:
                # Add final result to the processing queue
                try:
                    self.route_turn_queue.put_nowait(("final", text))
                    logger.info(
                        f"📋 Added final result to queue. Queue size: {self.route_turn_queue.qsize()}"
                    )
                except asyncio.QueueFull:
                    logger.warning("⚠️ Route turn queue is full, dropping message")

                # Reset playback task reference
                self.playback_task = None

            except Exception as e:
                logger.error(f"❌ Error in final result handling: {e}", exc_info=True)

    async def route_turn_loop(self):
        """
        Background task that processes queued speech recognition results.
        This runs continuously until stopped.
        """
        with self._create_trace_context(
            name="acs_media_handler.route_turn_loop",
            metadata=self._get_trace_metadata("background_processing_loop")
        ):
            logger.info("🔄 Route turn loop started")

            try:
                while not self.stopped:
                    try:
                        # Wait for next turn to process
                        kind, text = await asyncio.wait_for(
                            self.route_turn_queue.get(),
                            timeout=1.0,  # Allow periodic checking of stopped flag
                        )

                        logger.info(f"🎯 Processing {kind} turn: {text}")
 
                        # Note: broadcast_message is now handled in the orchestrator to avoidduplication
                        # Cancel any current playback before starting new one
                        if self.playback_task and not self.playback_task.done():
                            logger.info("Cancelling previous playback task")
                            self.playback_task.cancel()
                            try:
                                await self.playback_task
                            except asyncio.CancelledError:
                                logger.info("✅ Previous playback task cancelled")

                        # Start new playback task
                        self.playback_task = asyncio.create_task(
                            self.route_and_playback(kind, text)
                        )
                        logger.info(f"🎵 Started new playback task: {self.playback_task}")

                    except asyncio.TimeoutError:
                        # Timeout is expected, continue checking the loop
                        continue
                    except Exception as e:
                        logger.error(f"❌ Error in route turn loop: {e}", exc_info=True)

            except Exception as e:
                logger.error(f"❌ Route turn loop failed: {e}", exc_info=True)
            finally:
                logger.info("🔄 Route turn loop ended")

    async def route_and_playback(self, kind, text):
        """
        Process the turn through the orchestrator and handle any resulting playback.
        """
        with self._create_trace_context(
            name="acs_media_handler.route_and_playback",
            metadata=self._get_trace_metadata(
                "orchestrator_processing",
                kind=kind,
                text_length=len(text),
                queue_size=self.route_turn_queue.qsize()
            )
        ):
            try:
                logger.info(f"🎯 Routing turn with kind={kind} and text={text}")

                # Check for barge-in during processing
                if self._barge_in_event.is_set():
                    logger.info(
                        "🚫 Barge-in detected during route_turn, skipping processing"
                    )
                    return

                # Route the turn through the orchestrator
                await route_turn(
                    cm=self.cm, transcript=text, ws=self.incoming_websocket, is_acs=True
                )
                logger.info("✅ Route turn completed successfully")

            except asyncio.CancelledError:
                logger.info("🚫 Route and playback cancelled")
                raise
            except Exception as e:
                logger.error(f"❌ Error in route and playback: {e}", exc_info=True)

    async def send_stop_audio(self):
        """
        Send a stop-audio event to ACS to interrupt current playback.
        """
        with self._create_trace_context(
            name="acs_media_handler.send_stop_audio",
            metadata=self._get_trace_metadata("stop_audio_command")
        ):
            try:
                stop_audio_data = {"Kind": "StopAudio", "AudioData": None, "StopAudio": {}}
                json_data = json.dumps(stop_audio_data)
                await self.incoming_websocket.send_text(json_data)
                logger.info("📢 Sent stop audio command to ACS")
            except Exception as e:
                logger.warning(f"⚠️ Failed to send stop audio: {e}", exc_info=True)

    async def stop(self):
        """
        Gracefully stop the media handler and all its components.
        """
        with self._create_trace_context(
            name="acs_media_handler.stop",
            metadata=self._get_trace_metadata("cleanup_and_shutdown")
        ):
            logger.info("🛑 Stopping ACS Media Handler")
            self.stopped = True

            try:
                # Stop the speech recognizer
                if self.recognizer:
                    self.recognizer.stop_continuous_recognition()
                    logger.info("✅ Speech recognizer stopped")

                # Cancel playback task
                if self.playback_task and not self.playback_task.done():
                    self.playback_task.cancel()
                    try:
                        await self.playback_task
                    except asyncio.CancelledError:
                        logger.info("✅ Playback task cancelled")

                # Cancel route turn task
                if self.route_turn_task and not self.route_turn_task.done():
                    self.route_turn_task.cancel()
                    try:
                        await self.route_turn_task
                    except asyncio.CancelledError:
                        logger.info("✅ Route turn task cancelled")

                # Note: Greeting check task removed - greeting now fires immediately in WebSocket router

                logger.info("✅ ACS Media Handler stopped successfully")

            except Exception as e:
                logger.error(f"❌ Error stopping ACS Media Handler: {e}", exc_info=True)
