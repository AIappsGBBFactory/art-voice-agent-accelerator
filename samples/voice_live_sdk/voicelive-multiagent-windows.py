import os
import sys
import asyncio
import base64
import argparse
import signal
import threading
import queue
import platform
import atexit
from azure.ai.voicelive.models import ServerEventType
from typing import Union, Optional, TYPE_CHECKING, cast
from concurrent.futures import ThreadPoolExecutor
import logging


# Audio processing imports
try:
    import pyaudio
except ImportError:
    print("This sample requires pyaudio. Install with: pip install pyaudio")
    sys.exit(1)

# Environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

# Azure VoiceLive SDK imports
from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential

from azure.ai.voicelive.aio import connect

if TYPE_CHECKING:
    # Only needed for type checking; avoids runtime import issues
    from azure.ai.voicelive.aio import VoiceLiveConnection
import json

from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat
)

# Agent system imports
from agents import AgentRegistry, SessionManager, AgentType
from typing import Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class WindowsAudioProcessor:
    """
    Windows-compatible audio processor that handles PyAudio threading issues.
    
    Key fixes for Windows:
    1. Proper thread synchronization and cleanup
    2. Exception handling for Windows audio device access
    3. Graceful shutdown without access violations
    4. Windows-specific PyAudio configuration
    """

    def __init__(self, connection):
        self.connection = connection
        self.audio = None
        
        # Windows-specific PyAudio initialization
        try:
            self.audio = pyaudio.PyAudio()
        except Exception as e:
            logger.error(f"Failed to initialize PyAudio on Windows: {e}")
            raise

        # Audio configuration - PCM16, 24kHz, mono as specified
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 24000
        self.chunk_size = 1024

        # Capture and playback state
        self.is_capturing = False
        self.is_playing = False
        self.input_stream = None
        self.output_stream = None
        self._shutdown_event = threading.Event()

        # Audio queues and threading
        self.audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self.audio_send_queue: "queue.Queue[str]" = queue.Queue()  # base64 audio to send
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="AudioProcessor")
        self.capture_thread: Optional[threading.Thread] = None
        self.playback_thread: Optional[threading.Thread] = None
        self.send_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None  # Store the event loop

        # Register cleanup on exit (Windows-specific)
        atexit.register(self._emergency_cleanup)

        logger.info("WindowsAudioProcessor initialized with 24kHz PCM16 mono audio")

    def _emergency_cleanup(self):
        """Emergency cleanup called on program exit - Windows specific."""
        try:
            logger.info("Emergency cleanup triggered")
            self._shutdown_event.set()
            
            # Force cleanup of streams
            if self.input_stream:
                try:
                    self.input_stream.stop_stream()
                    self.input_stream.close()
                except:
                    pass
                    
            if self.output_stream:
                try:
                    self.output_stream.stop_stream()
                    self.output_stream.close()
                except:
                    pass
                    
            if self.audio:
                try:
                    self.audio.terminate()
                except:
                    pass
        except:
            pass  # Suppress all errors in emergency cleanup

    async def start_capture(self):
        """Start capturing audio from microphone with Windows-specific error handling."""
        if self.is_capturing or self._shutdown_event.is_set():
            return

        # Store the current event loop for use in threads
        self.loop = asyncio.get_event_loop()
        self.is_capturing = True

        try:
            # Windows-specific device selection and error handling
            default_input_device = None
            try:
                default_input_device = self.audio.get_default_input_device_info()
                logger.info(f"Using input device: {default_input_device['name']}")
            except OSError as e:
                logger.warning(f"Could not get default input device: {e}")
                # Try to find any available input device
                for i in range(self.audio.get_device_count()):
                    info = self.audio.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        default_input_device = info
                        logger.info(f"Using fallback input device: {info['name']}")
                        break
                
                if not default_input_device:
                    raise Exception("No input devices found")

            # Open input stream with Windows-compatible parameters
            self.input_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=default_input_device['index'] if default_input_device else None,
                frames_per_buffer=self.chunk_size,
                stream_callback=None,
                start=False  # Don't start immediately
            )

            # Start the stream after opening
            self.input_stream.start_stream()

            # Start capture thread with Windows-specific naming
            self.capture_thread = threading.Thread(
                target=self._capture_audio_thread,
                name="AudioCapture-Windows",
                daemon=True
            )
            self.capture_thread.start()

            # Start audio send thread
            self.send_thread = threading.Thread(
                target=self._send_audio_thread,
                name="AudioSend-Windows", 
                daemon=True
            )
            self.send_thread.start()

            logger.info("Started audio capture on Windows")

        except Exception as e:
            logger.error(f"Failed to start audio capture on Windows: {e}")
            self.is_capturing = False
            await self._cleanup_capture()
            raise

    def _capture_audio_thread(self):
        """Audio capture thread - Windows-compatible version."""
        logger.info("Audio capture thread started")
        
        while self.is_capturing and not self._shutdown_event.is_set():
            try:
                if not self.input_stream or not self.input_stream.is_active():
                    break
                    
                # Read audio data with Windows-specific exception handling
                try:
                    audio_data = self.input_stream.read(
                        self.chunk_size, 
                        exception_on_overflow=False
                    )
                except OSError as e:
                    if "Input overflowed" in str(e):
                        logger.debug("Input overflow, continuing...")
                        continue
                    else:
                        logger.error(f"Audio input error: {e}")
                        break

                if audio_data and self.is_capturing and not self._shutdown_event.is_set():
                    # Convert to base64 and queue for sending
                    try:
                        audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                        self.audio_send_queue.put(audio_base64, timeout=0.1)
                    except queue.Full:
                        logger.debug("Audio send queue full, dropping frame")
                        continue

            except Exception as e:
                if self.is_capturing and not self._shutdown_event.is_set():
                    logger.error(f"Error in audio capture thread: {e}")
                break
                
        logger.info("Audio capture thread stopped")

    def _send_audio_thread(self):
        """Audio send thread - Windows-compatible version."""
        logger.info("Audio send thread started")
        
        while self.is_capturing and not self._shutdown_event.is_set():
            try:
                # Get audio data from queue (blocking with timeout)
                try:
                    audio_base64 = self.audio_send_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if (audio_base64 and self.is_capturing and 
                    not self._shutdown_event.is_set() and 
                    self.loop and not self.loop.is_closed()):
                    
                    # Schedule the async send operation in the main event loop
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.connection.input_audio_buffer.append(audio=audio_base64), 
                            self.loop
                        )
                        # Don't wait for completion to avoid blocking
                    except RuntimeError as e:
                        if "Event loop is closed" in str(e):
                            logger.debug("Event loop closed, stopping audio send thread")
                            break
                        else:
                            logger.error(f"Runtime error in send thread: {e}")
                            break

            except Exception as e:
                if self.is_capturing and not self._shutdown_event.is_set():
                    logger.error(f"Error sending audio: {e}")
                break
                
        logger.info("Audio send thread stopped")

    async def _cleanup_capture(self):
        """Clean up capture resources safely on Windows."""
        try:
            if self.input_stream:
                if self.input_stream.is_active():
                    self.input_stream.stop_stream()
                self.input_stream.close()
                self.input_stream = None

            # Wait for threads to finish with timeout
            if self.capture_thread and self.capture_thread.is_alive():
                self.capture_thread.join(timeout=2.0)
                if self.capture_thread.is_alive():
                    logger.warning("Capture thread did not stop gracefully")

            if self.send_thread and self.send_thread.is_alive():
                self.send_thread.join(timeout=2.0)
                if self.send_thread.is_alive():
                    logger.warning("Send thread did not stop gracefully")

            # Clear the send queue
            while not self.audio_send_queue.empty():
                try:
                    self.audio_send_queue.get_nowait()
                except queue.Empty:
                    break

        except Exception as e:
            logger.error(f"Error during capture cleanup: {e}")

    async def stop_capture(self):
        """Stop capturing audio with Windows-specific cleanup."""
        if not self.is_capturing:
            return

        logger.info("Stopping audio capture...")
        self.is_capturing = False
        
        await self._cleanup_capture()
        logger.info("Stopped audio capture")

    async def start_playback(self):
        """Initialize audio playback system with Windows compatibility."""
        if self.is_playing or self._shutdown_event.is_set():
            return

        self.is_playing = True

        try:
            # Windows-specific device selection
            default_output_device = None
            try:
                default_output_device = self.audio.get_default_output_device_info()
                logger.info(f"Using output device: {default_output_device['name']}")
            except OSError as e:
                logger.warning(f"Could not get default output device: {e}")
                # Try to find any available output device
                for i in range(self.audio.get_device_count()):
                    info = self.audio.get_device_info_by_index(i)
                    if info['maxOutputChannels'] > 0:
                        default_output_device = info
                        logger.info(f"Using fallback output device: {info['name']}")
                        break
                
                if not default_output_device:
                    raise Exception("No output devices found")

            self.output_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                output=True,
                output_device_index=default_output_device['index'] if default_output_device else None,
                frames_per_buffer=self.chunk_size,
                start=False  # Don't start immediately
            )

            # Start the output stream
            self.output_stream.start_stream()

            # Start playback thread
            self.playback_thread = threading.Thread(
                target=self._playback_audio_thread,
                name="AudioPlayback-Windows",
                daemon=True
            )
            self.playback_thread.start()

            logger.info("Audio playback system ready on Windows")

        except Exception as e:
            logger.error(f"Failed to initialize audio playback on Windows: {e}")
            self.is_playing = False
            await self._cleanup_playback()
            raise

    def _playback_audio_thread(self):
        """Audio playback thread - Windows-compatible version."""
        logger.info("Audio playback thread started")
        
        while self.is_playing and not self._shutdown_event.is_set():
            try:
                # Get audio data from queue (blocking with timeout)
                try:
                    audio_data = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if (audio_data and self.output_stream and 
                    self.is_playing and not self._shutdown_event.is_set()):
                    
                    try:
                        self.output_stream.write(audio_data)
                        logger.debug(f"🔊 Played {len(audio_data)} bytes to output device")
                    except OSError as e:
                        if ("Output underflowed" in str(e) or 
                            "Stream is stopped" in str(e) or 
                            "Unanticipated host error" in str(e)):
                            logger.debug(f"Audio stream status change: {e}")
                            break  # Exit gracefully when stream is stopped
                        else:
                            logger.error(f"Audio output error: {e}")
                            break

            except Exception as e:
                if self.is_playing and not self._shutdown_event.is_set():
                    logger.error(f"Error in audio playback thread: {e}")
                break
                
        logger.info("Audio playback thread stopped")

    async def queue_audio(self, audio_data: bytes):
        """Queue audio data for playback with Windows error handling."""
        if self.is_playing and not self._shutdown_event.is_set():
            try:
                self.audio_queue.put(audio_data, timeout=0.1)
                logger.debug(f"🔊 Queued {len(audio_data)} bytes for playback (queue size: {self.audio_queue.qsize()})")
            except queue.Full:
                logger.warning("Audio playback queue full, dropping frame")
        else:
            logger.warning(f"🔊 Cannot queue audio - is_playing: {self.is_playing}, shutdown: {self._shutdown_event.is_set()}")

    async def _cleanup_playback(self):
        """Clean up playback resources safely on Windows."""
        try:
            # Clear the queue first
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break

            if self.output_stream:
                try:
                    if self.output_stream.is_active():
                        self.output_stream.stop_stream()
                    self.output_stream.close()
                    self.output_stream = None
                except Exception as stream_error:
                    logger.debug(f"Audio stream cleanup warning: {stream_error}")

            if self.playback_thread and self.playback_thread.is_alive():
                self.playback_thread.join(timeout=2.0)
                if self.playback_thread.is_alive():
                    logger.warning("Playback thread did not stop gracefully")

        except Exception as e:
            logger.debug(f"Playback cleanup completed with minor warnings: {e}")

    async def stop_playback(self):
        """Stop audio playback and clear queue with Windows cleanup."""
        if not self.is_playing:
            return

        logger.info("Stopping audio playback...")
        self.is_playing = False
        
        # Clear the playback queue but keep the stream open for next response
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        
        # Wait for playback thread to stop
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=1.0)
        
        logger.info("Stopped audio playback")

    async def cleanup(self):
        """Clean up audio resources with Windows-specific handling."""
        logger.info("Starting audio processor cleanup...")
        
        # Signal all threads to stop
        self._shutdown_event.set()
        
        # Stop capture and playback
        await self.stop_capture()
        await self.stop_playback()

        # Cleanup PyAudio
        if self.audio:
            try:
                self.audio.terminate()
                self.audio = None
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}")

        # Shutdown executor (Windows-compatible - no timeout parameter)
        try:
            self.executor.shutdown(wait=True)
        except Exception as e:
            logger.error(f"Error shutting down executor: {e}")
            
        logger.info("Audio processor cleaned up")


# Replace the original AudioProcessor with WindowsAudioProcessor for the rest of the code
AudioProcessor = WindowsAudioProcessor


class BasicVoiceAssistant:
    """Basic voice assistant implementing the VoiceLive SDK patterns with Windows compatibility."""

    def __init__(
        self,
        endpoint: str,
        credential: Union[AzureKeyCredential, TokenCredential],
        model: str = "gpt-4o-realtime-preview",
        voice: str = "en-US-AvaNeural",
        instructions: str = "You are a helpful AI assistant.",
    ):
        self.endpoint = endpoint
        self.credential = credential
        self.model = model
        self.voice = voice
        self.instructions = instructions

        # Connection and state
        self.connection: Optional["VoiceLiveConnection"] = None
        self.audio_processor: Optional[AudioProcessor] = None
        self.session_ready = False
        self._shutdown_event = threading.Event()

        # Agent system components
        self.agent_registry = AgentRegistry()
        self.session_manager = SessionManager(self.agent_registry)
        self.current_agent_type = AgentType.ORCHESTRATOR

        # Windows-specific signal handling
        if platform.system() == "Windows":
            # Windows doesn't support SIGTERM the same way
            signal.signal(signal.SIGINT, self._signal_handler)
        else:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Windows-compatible signal handler."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self._shutdown_event.set()
        
        # Create a task to handle graceful shutdown
        if hasattr(self, '_shutdown_task'):
            return  # Already shutting down
            
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
            
        if loop:
            self._shutdown_task = loop.create_task(self._graceful_shutdown())
        else:
            # If no loop is running, force exit
            logger.warning("No event loop found, forcing exit")
            os._exit(1)

    async def _graceful_shutdown(self):
        """Perform graceful shutdown with proper cleanup."""
        try:
            logger.info("Starting graceful shutdown...")
            
            if self.audio_processor:
                await self.audio_processor.cleanup()
                
            if self.connection:
                try:
                    await self.connection.close()
                except:
                    pass
                    
            logger.info("Graceful shutdown completed")
            
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
        finally:
            # Exit the event loop
            loop = asyncio.get_running_loop()
            loop.stop()

    async def start(self):
        """Start the voice assistant with Windows-specific error handling."""
        try:
            logger.info(f"Connecting to VoiceLive API with model {self.model}")

            # Connect to VoiceLive WebSocket API using context manager
            async with connect(
                endpoint=self.endpoint,
                credential=self.credential,
                model=self.model,
                connection_options={
                    "max_msg_size": 10 * 1024 * 1024,
                    "heartbeat": 20,
                    "timeout": 20,
                },
            ) as connection:
                self.connection = connection

                # Initialize audio processor
                self.audio_processor = AudioProcessor(self.connection)

                # Set up voice conversation session
                logger.info("Setting up voice conversation session...")
                await self._switch_to_agent(AgentType.ORCHESTRATOR)

                logger.info("Session configuration sent")

                # Start audio playback system
                await self.audio_processor.start_playback()
                logger.info("Voice assistant ready! Start speaking...")

                # User interface
                print("=" * 60)
                print("🎤 VOICE ASSISTANT READY")
                print("Start speaking to begin conversation")
                print("Press Ctrl+C to exit")
                print("=" * 60)

                # Process events
                await self._process_events()

        except KeyboardInterrupt:
            logger.info("Voice assistant interrupted by user")
        except Exception as e:
            logger.error(f"Error in voice assistant: {e}")
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self):
        """Clean up resources with Windows-specific handling."""
        logger.info("Cleaning up voice assistant...")
        
        try:
            if self.audio_processor:
                await self.audio_processor.cleanup()
                
            if self.connection:
                await self.connection.close()
                
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            
        logger.info("Voice assistant cleanup completed")

    # ... rest of the methods remain the same as in the original code ...
    # (Including _switch_to_agent, _create_fallback_session, _handle_function_call, etc.)
    # For brevity, I'm not copying all methods, but they would be identical

    async def _switch_to_agent(self, agent_type: AgentType, context: Dict[str, Any] = None):
        """Switch to a different agent type with error handling."""
        try:
            if context is None:
                context = {}
            
            logger.info(f"\n=== STARTING AGENT SWITCH ===")
            logger.info(f"From: {self.current_agent_type.value} -> To: {agent_type.value}")
            
            # Step 1: Optional handoff confirmation (only for non-orchestrator switches)
            if (self.current_agent_type != AgentType.ORCHESTRATOR and 
                agent_type != AgentType.ORCHESTRATOR):
                # Send confirmation message via text-to-speech
                handoff_message = f"Transferring you to the appropriate specialist. One moment please."
                await self._send_text_response(handoff_message)
                # Small delay to let confirmation play
                await asyncio.sleep(1.0)
            
            # Step 2: Create session configuration for the new agent
            logger.info(f"Creating session config for {agent_type.value}...")
            session_config = self.session_manager.create_session_config(agent_type, context)
            
            conn = self.connection
            assert conn is not None, "Connection must be established before switching session"
            
            # Debug log the session configuration
            logger.info(f"Session configuration created:")
            logger.info(f"  Instructions preview: {session_config.instructions[:100]}...")
            logger.info(f"  Voice: {session_config.voice}")
            logger.info(f"  Has tools: {hasattr(session_config, 'tools') and session_config.tools is not None}")
            
            if hasattr(session_config, 'tools') and session_config.tools:
                logger.info(f"  Tool count: {len(session_config.tools)}")
                logger.info(f"  Tool choice: {getattr(session_config, 'tool_choice', 'Not set')}")
                for i, tool in enumerate(session_config.tools):
                    if hasattr(tool, 'name'):
                        logger.info(f"    Tool {i}: {tool.name}")
                    else:
                        logger.warning(f"    Tool {i}: Invalid structure - {type(tool)}")
            
            # Step 3: Update session with error handling
            logger.info(f"Sending session update to VoiceLive API...")
            await conn.session.update(session=session_config)
            logger.info(f"Session update sent successfully!")
            
            # Update current agent state
            old_agent = self.current_agent_type
            self.current_agent_type = agent_type
            agent_config = self.session_manager.get_current_agent()
            
            logger.info(f"Agent state updated: {old_agent.value} -> {agent_type.value}")
            
            # Step 4: Have the new agent introduce themselves and engage with the user
            await self._trigger_agent_introduction(agent_type, context)
            
            logger.info(f"=== AGENT SWITCH COMPLETED SUCCESSFULLY ===")
            
        except Exception as e:
            logger.error(f"❌ Failed to switch to agent {agent_type.value}: {e}")
            logger.error(f"Exception details:", exc_info=True)
            # Try to fall back to a basic session without tools
            try:
                logger.info("Attempting fallback session configuration...")
                fallback_config = self._create_fallback_session(agent_type)
                await conn.session.update(session=fallback_config)
                logger.info("Fallback session created successfully")
                self.current_agent_type = agent_type
            except Exception as fallback_error:
                logger.error(f"Fallback session also failed: {fallback_error}")
                raise e  # Re-raise the original error
    
    def _create_fallback_session(self, agent_type: AgentType) -> RequestSession:
        """Create a basic session configuration without tools as fallback."""
        agent_config = self.agent_registry.get_agent(agent_type)
        
        # Create basic voice configuration
        voice_config: Union[AzureStandardVoice, str]
        if agent_config.voice.startswith("en-US-") or "-" in agent_config.voice:
            voice_config = AzureStandardVoice(name=agent_config.voice, type="azure-standard")
        else:
            voice_config = agent_config.voice
        
        # Create basic turn detection
        turn_detection_config = ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500)
        
        # Create minimal session configuration (no tools)
        return RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=agent_config.instructions,
            voice=voice_config,
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            turn_detection=turn_detection_config
        )

    async def _send_text_response(self, message: str):
        """Send a text message as a response via the VoiceLive connection."""
        try:
            conn = self.connection
            if conn and hasattr(conn, 'response'):
                # Create a response with the text message
                from azure.ai.voicelive.models import ResponseCreateParams
                response_params = ResponseCreateParams(
                    instructions=f"Please say the following message exactly: '{message}'"
                )
                await conn.response.create(response=response_params)
                logger.info(f"Sent text response: {message}")
            else:
                logger.warning("Cannot send text response - connection not available")
        except Exception as e:
            logger.error(f"Failed to send text response: {e}")

    async def _trigger_agent_introduction(self, agent_type: AgentType, context: Dict[str, Any] = None):
        """Trigger the new agent to introduce themselves and engage with the user."""
        try:    
            if context is None:
                context = {}
                
            # Get agent configuration
            agent_config = self.agent_registry.get_agent(agent_type)
            agent_name = agent_config.name.split(' - ')[0]  # Extract just the name part
            user_concern = context.get('user_concern', 'their concern')
            
            logger.info(f"Triggering introduction for {agent_name}")
            logger.info(f"Introduction context: {context}")
            
            # Add a small delay to ensure the session update has taken effect
            await asyncio.sleep(1.0)
            
            # Use a simpler approach - just trigger a response which should make the agent introduce themselves
            # based on their system instructions that include the handoff context
            conn = self.connection
            if conn and hasattr(conn, 'response'):
                from azure.ai.voicelive.models import ResponseCreateParams
                
                # Simple response trigger - the agent should introduce themselves based on their instructions
                response_params = ResponseCreateParams()
                await conn.response.create(response=response_params)
                
                logger.info(f"Introduction response triggered for {agent_name}")
            
        except Exception as e:
            logger.error(f"Failed to trigger agent introduction: {e}")
            logger.error("Exception details:", exc_info=True)

    async def _handle_function_call(self, function_call):
        """Handle function calls from the orchestrator agent."""
        try:
            function_name = getattr(function_call, 'name', None)
            function_args_str = getattr(function_call, 'arguments', None)
            
            logger.info(f"=== PROCESSING FUNCTION CALL ===")
            logger.info(f"Function name: {function_name}")
            logger.info(f"Raw arguments: {function_args_str}")
            
            if not function_name:
                logger.warning("Function call has no name")
                return False
                
            function_args = {}
            if function_args_str:
                try:
                    function_args = json.loads(function_args_str)
                    logger.info(f"Parsed arguments: {function_args}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse function arguments: {e}")
                    return False
            
            # Map function call to agent type
            target_agent = self.agent_registry.get_agent_by_function_name(function_name)
            logger.info(f"Target agent: {target_agent}")
            
            if target_agent:
                # Extract context from function arguments
                context = {
                    "handoff_reason": function_args.get("reason", "User request"),
                    "user_concern": function_args.get("patient_concern") or function_args.get("customer_issue") or function_args.get("technical_issue", "General inquiry"),
                    "previous_agent": self.current_agent_type.value
                }
                
                logger.info(f"Switching from {self.current_agent_type.value} to {target_agent.value}")
                logger.info(f"Handoff context: {context}")
                
                # Switch to the target agent (they will introduce themselves)
                await self._switch_to_agent(target_agent, context)
                
                logger.info(f"=== FUNCTION CALL COMPLETED - SWITCHED TO {target_agent.value} ===")
                return True
            else:
                logger.warning(f"Unknown function call: {function_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling function call: {e}")
            logger.error(f"Exception details:", exc_info=True)
            return False

    async def _process_events(self):
        """Process events from the VoiceLive connection with Windows error handling."""
        try:
            conn = self.connection
            assert conn is not None, "Connection must be established before processing events"
            
            async for event in conn:
                if self._shutdown_event.is_set():
                    logger.info("Shutdown event set, stopping event processing")
                    break
                    
                await self._handle_event(event)

        except KeyboardInterrupt:
            logger.info("Event processing interrupted")
        except Exception as e:
            if not self._shutdown_event.is_set():
                logger.error(f"Error processing events: {e}")
                raise

    async def _handle_event(self, event):
        """Handle different types of events from VoiceLive."""
        if self._shutdown_event.is_set():
            return
            
        logger.debug(f"Received event: {event.type}")
        ap = self.audio_processor
        conn = self.connection
        assert ap is not None, "AudioProcessor must be initialized"
        assert conn is not None, "Connection must be established"

        if event.type == ServerEventType.SESSION_UPDATED:
            logger.info(f"🎯 SESSION_UPDATED: Session ready: {event.session.id}")
            logger.info(f"   Current agent should be: {self.current_agent_type.value}")
            
            # Get current agent info for verification
            current_agent = self.session_manager.get_current_agent()
            if current_agent:
                logger.info(f"   Agent active: {current_agent.name}")
                print(f"✅ Session updated - Active agent: {current_agent.name}")
            
            self.session_ready = True

            # Start audio capture once session is ready
            await ap.start_capture()

        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            logger.info("🎤 User started speaking - stopping playback")
            print("🎤 Listening...")

            # Add a small delay to prevent overly aggressive interruption
            # This gives the assistant a chance to finish current audio
            await asyncio.sleep(0.1)

            # Stop current assistant audio playback (interruption handling)
            await ap.stop_playback()

            # Cancel any ongoing response
            try:
                await conn.response.cancel()
            except Exception as e:
                logger.debug(f"No response to cancel: {e}")

        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
            logger.info("🎤 User stopped speaking")
            print("🤔 Processing...")

            # Restart playback system for response
            await ap.start_playback()

        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            logger.info(f"Response Transcription Done: {event.transcript}")

        elif event.type == ServerEventType.RESPONSE_CREATED:
            logger.info("🤖 Assistant response created")
            try:
                response_data = {
                    "id": event.response.id,
                    "conversation_id": event.response.conversation_id,
                    "status": event.response.status,
                    "output": getattr(event.response, 'output', None),
                }
                # Remove None values for cleaner output
                response_data = {k: v for k, v in response_data.items() if v is not None}
                
                logger.info("Response details:\n" + json.dumps(response_data, indent=2, default=str))
            except Exception as e:
                logger.warning(f"Could not format response data: {e}")

        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            # Stream audio response to speakers
            logger.info(f"🔊 Received audio delta: {len(event.delta)} bytes")
            await ap.queue_audio(event.delta)

        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            logger.info("CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED")
            print("🎤 Ready for next input...")

        elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
            logger.info("🤖 Assistant finished speaking")
            print("🎤 Ready for next input...")

        elif event.type == ServerEventType.RESPONSE_DONE:
            logger.info("✅ Response complete")
            
            # Safely access response output
            try:
                if hasattr(event.response, 'output') and event.response.output:
                    logger.info(f"Response: {event.response.output}")
                else:
                    logger.info("Response completed (no text output)")
            except Exception as e:
                logger.warning(f"Could not access response output: {e}")

        elif event.type == ServerEventType.ERROR:
            logger.error(f"❌ VoiceLive error: {event.error.message}")
            print(f"Error: {event.error.message}")

        elif event.type == ServerEventType.CONVERSATION_ITEM_CREATED:
            logger.debug(f"Conversation item created: {event.item.id}")
            
            # Check item type before accessing content
            if hasattr(event.item, 'content') and event.item.content:
                logger.info(f"Conversation Item Content: {event.item.content}")
            elif hasattr(event.item, 'name'):  # Function call item
                logger.info(f"Function call item created: {event.item.name}")
            else:
                logger.info(f"Conversation item created (type: {type(event.item).__name__})")
            
        elif event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            logger.info("Function call arguments completed")
            
            # Handle function calls for agent switching immediately
            # The function call data is directly on the event object
            if hasattr(event, 'name') and hasattr(event, 'arguments'):
                logger.info(f"Processing function call: {event.name}")
                success = await self._handle_function_call(event)
                if success:
                    logger.info("Function call handled successfully - agent should have switched")
                else:
                    logger.warning("Function call handling failed")
            else:
                logger.warning("Function call event received but no function call data found")

        else:
            logger.debug(f"Unhandled event type: {event.type}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Windows-Compatible Voice Assistant using Azure VoiceLive SDK",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--api-key",
        help="Azure VoiceLive API key. If not provided, will use AZURE_VOICELIVE_API_KEY environment variable.",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_API_KEY"),
    )

    parser.add_argument(
        "--endpoint",
        help="Azure VoiceLive endpoint",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_ENDPOINT", "wss://api.voicelive.com/v1"),
    )

    parser.add_argument(
        "--model",
        help="VoiceLive model to use",
        type=str,
        default=os.environ.get("VOICELIVE_MODEL", "gpt-4o-realtime-preview"),
    )

    parser.add_argument(
        "--voice",
        help="Voice to use for the assistant",
        type=str,
        default=os.environ.get("VOICELIVE_VOICE", "en-US-AvaNeural"),
        choices=[
            "alloy",
            "echo", 
            "fable",
            "onyx",
            "nova",
            "shimmer",
            "en-US-AvaNeural",
            "en-US-JennyNeural",
            "en-US-GuyNeural",
        ],
    )

    parser.add_argument(
        "--instructions",
        help="System instructions for the AI assistant",
        type=str,
        default=os.environ.get(
            "VOICELIVE_INSTRUCTIONS",
            "You are a helpful AI assistant. Respond naturally and conversationally. "
            "Keep your responses concise but engaging.",
        ),
    )

    parser.add_argument(
        "--use-token-credential", help="Use Azure token credential instead of API key", action="store_true"
    )

    parser.add_argument("--verbose", help="Enable verbose logging", action="store_true")

    return parser.parse_args()


async def main():
    """Main function with Windows-specific error handling."""
    args = parse_arguments()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate credentials
    if not args.api_key and not args.use_token_credential:
        print("❌ Error: No authentication provided")
        print("Please provide an API key using --api-key or set AZURE_VOICELIVE_API_KEY environment variable,")
        print("or use --use-token-credential for Azure authentication.")
        sys.exit(1)

    try:
        # Create client with appropriate credential
        credential: Union[AzureKeyCredential, TokenCredential]
        if args.use_token_credential:
            credential = InteractiveBrowserCredential()  # or DefaultAzureCredential() if needed
            logger.info("Using Azure token credential")
        else:
            credential = AzureKeyCredential(args.api_key)
            logger.info("Using API key credential")

        # Create and start voice assistant
        assistant = BasicVoiceAssistant(
            endpoint=args.endpoint,
            credential=credential,
            model=args.model,
            voice=args.voice,
            instructions=args.instructions,
        )

        # Start the assistant
        await assistant.start()

    except KeyboardInterrupt:
        print("👋 Voice assistant shut down. Goodbye!")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Windows-specific compatibility checks
    if platform.system() == "Windows":
        print("🪟 Windows detected - using Windows-compatible audio processing")
        
        # Set Windows-specific asyncio policy to avoid issues
        if sys.version_info >= (3, 8):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except AttributeError:
                pass  # Not available in all Python versions

    # Check for required dependencies
    dependencies = {
        "pyaudio": "Audio processing",
        "azure.ai.voicelive": "Azure VoiceLive SDK",
        "azure.core": "Azure Core libraries",
    }

    missing_deps = []
    for dep, description in dependencies.items():
        try:
            __import__(dep.replace("-", "_"))
        except ImportError:
            missing_deps.append(f"{dep} ({description})")

    if missing_deps:
        print("❌ Missing required dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("Install with: pip install azure-ai-voicelive pyaudio python-dotenv")
        sys.exit(1)

    # Check audio system with Windows-specific handling
    try:
        p = pyaudio.PyAudio()
        
        # Check for input devices
        input_devices = []
        output_devices = []
        
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    input_devices.append(i)
                if info.get("maxOutputChannels", 0) > 0:
                    output_devices.append(i)
            except OSError:
                continue  # Skip problematic devices on Windows
                
        p.terminate()

        if not input_devices:
            print("❌ No audio input devices found. Please check your microphone.")
            print("💡 On Windows, make sure microphone permissions are enabled for your application.")
            sys.exit(1)
        if not output_devices:
            print("❌ No audio output devices found. Please check your speakers.")
            sys.exit(1)

        logger.info(f"Found {len(input_devices)} input devices and {len(output_devices)} output devices")

    except Exception as e:
        print(f"❌ Audio system check failed: {e}")
        print("💡 On Windows, try running as administrator or check audio device permissions.")
        sys.exit(1)

    print("🎙️  Windows-Compatible Voice Assistant with Azure VoiceLive SDK")
    print("=" * 60)

    # Run the assistant
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Assistant terminated by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        print(f"💥 Fatal error: {e}")
        sys.exit(1)