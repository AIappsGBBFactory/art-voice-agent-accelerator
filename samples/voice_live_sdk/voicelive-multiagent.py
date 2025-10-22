
import os
import sys
import asyncio
import base64
import argparse
import signal
import threading
import queue
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


class AudioProcessor:
    """
    Handles real-time audio capture and playback for the voice assistant.

    Threading Architecture:
    - Main thread: Event loop and UI
    - Capture thread: PyAudio input stream reading
    - Send thread: Async audio data transmission to VoiceLive
    - Playback thread: PyAudio output stream writing
    """

    def __init__(self, connection):
        self.connection = connection
        self.audio = pyaudio.PyAudio()

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

        # Audio queues and threading
        self.audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self.audio_send_queue: "queue.Queue[str]" = queue.Queue()  # base64 audio to send
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.capture_thread: Optional[threading.Thread] = None
        self.playback_thread: Optional[threading.Thread] = None
        self.send_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None  # Store the event loop

        logger.info("AudioProcessor initialized with 24kHz PCM16 mono audio")

    async def start_capture(self):
        """Start capturing audio from microphone."""
        if self.is_capturing:
            return

        # Store the current event loop for use in threads
        self.loop = asyncio.get_event_loop()

        self.is_capturing = True

        try:
            self.input_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=None,
            )

            self.input_stream.start_stream()

            # Start capture thread
            self.capture_thread = threading.Thread(target=self._capture_audio_thread)
            self.capture_thread.daemon = True
            self.capture_thread.start()

            # Start audio send thread
            self.send_thread = threading.Thread(target=self._send_audio_thread)
            self.send_thread.daemon = True
            self.send_thread.start()

            logger.info("Started audio capture")

        except Exception as e:
            logger.error(f"Failed to start audio capture: {e}")
            self.is_capturing = False
            raise

    def _capture_audio_thread(self):
        """Audio capture thread - runs in background."""
        while self.is_capturing and self.input_stream:
            try:
                # Read audio data
                audio_data = self.input_stream.read(self.chunk_size, exception_on_overflow=False)

                if audio_data and self.is_capturing:
                    # Convert to base64 and queue for sending
                    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                    self.audio_send_queue.put(audio_base64)

            except Exception as e:
                if self.is_capturing:
                    logger.error(f"Error in audio capture: {e}")
                break

    def _send_audio_thread(self):
        """Audio send thread - handles async operations from sync thread."""
        while self.is_capturing:
            try:
                # Get audio data from queue (blocking with timeout)
                audio_base64 = self.audio_send_queue.get(timeout=0.1)

                if audio_base64 and self.is_capturing and self.loop and not self.loop.is_closed():
                    # Schedule the async send operation in the main event loop
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.connection.input_audio_buffer.append(audio=audio_base64), self.loop
                        )
                        # Don't wait for completion to avoid blocking
                    except RuntimeError as e:
                        if "Event loop is closed" in str(e):
                            logger.debug("Event loop closed, stopping audio send thread")
                            break
                        else:
                            raise

            except queue.Empty:
                continue
            except Exception as e:
                if self.is_capturing:
                    logger.error(f"Error sending audio: {e}")
                break

    async def stop_capture(self):
        """Stop capturing audio."""
        if not self.is_capturing:
            return

        self.is_capturing = False

        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None

        if self.capture_thread:
            self.capture_thread.join(timeout=1.0)

        if self.send_thread:
            self.send_thread.join(timeout=1.0)

        # Clear the send queue
        while not self.audio_send_queue.empty():
            try:
                self.audio_send_queue.get_nowait()
            except queue.Empty:
                break

        logger.info("Stopped audio capture")

    async def start_playback(self):
        """Initialize audio playback system."""
        if self.is_playing:
            return

        self.is_playing = True

        try:
            self.output_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                output=True,
                frames_per_buffer=self.chunk_size,
            )

            # Start playback thread
            self.playback_thread = threading.Thread(target=self._playback_audio_thread)
            self.playback_thread.daemon = True
            self.playback_thread.start()

            logger.info("Audio playback system ready")

        except Exception as e:
            logger.error(f"Failed to initialize audio playback: {e}")
            self.is_playing = False
            raise

    def _playback_audio_thread(self):
        """Audio playback thread - runs in background."""
        while self.is_playing:
            try:
                # Get audio data from queue (blocking with timeout)
                audio_data = self.audio_queue.get(timeout=0.1)

                if audio_data and self.output_stream and self.is_playing:
                    self.output_stream.write(audio_data)

            except queue.Empty:
                continue
            except Exception as e:
                if self.is_playing:
                    logger.error(f"Error in audio playback: {e}")
                break

    async def queue_audio(self, audio_data: bytes):
        """Queue audio data for playback."""
        if self.is_playing:
            self.audio_queue.put(audio_data)

    async def stop_playback(self):
        """Stop audio playback and clear queue."""
        if not self.is_playing:
            return

        self.is_playing = False

        # Clear the queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        if self.output_stream:
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None

        if self.playback_thread:
            self.playback_thread.join(timeout=1.0)

        logger.info("Stopped audio playback")

    async def cleanup(self):
        """Clean up audio resources."""
        await self.stop_capture()
        await self.stop_playback()

        if self.audio:
            self.audio.terminate()

        self.executor.shutdown(wait=True)
        logger.info("Audio processor cleaned up")


class BasicVoiceAssistant:
    """Basic voice assistant implementing the VoiceLive SDK patterns."""

    def __init__(
        self,
        endpoint: str,
        credential: Union[AzureKeyCredential, TokenCredential],
        model: str,
        voice: str,
        instructions: str,
    ):

        self.endpoint = endpoint
        self.credential = credential
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.connection: Optional["VoiceLiveConnection"] = None
        self.audio_processor: Optional[AudioProcessor] = None
        self.session_ready = False
        self.conversation_started = False
        
        # Initialize agent system
        self.agent_registry = AgentRegistry()
        self.session_manager = SessionManager(self.agent_registry)
        self.current_agent_type = AgentType.ORCHESTRATOR

    async def start(self):
        """Start the voice assistant session."""
        try:
            logger.info(f"Connecting to VoiceLive API with model {self.model}")

            # Connect to VoiceLive WebSocket API
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
                conn = connection
                self.connection = conn

                # Initialize audio processor
                ap = AudioProcessor(conn)
                self.audio_processor = ap

                # Configure session for voice conversation
                await self._setup_session()

                # Start audio systems
                await ap.start_playback()

                logger.info("Voice assistant ready! Start speaking...")
                print("" + "=" * 60)
                print("🎤 VOICE ASSISTANT READY")
                print("Start speaking to begin conversation")
                print("Press Ctrl+C to exit")
                print("=" * 60 + "")

                # Process events
                await self._process_events()

        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")

        except Exception as e:
            logger.error(f"Connection error: {e}")
            raise

        # Cleanup
        if self.audio_processor:
            await self.audio_processor.cleanup()

    async def _setup_session(self):
        """Configure the VoiceLive session for audio conversation."""
        logger.info("Setting up voice conversation session...")
        
        # Start with orchestrator agent
        await self._switch_to_agent(AgentType.ORCHESTRATOR)
        
        logger.info("Session configuration sent")

    async def _switch_to_agent(self, agent_type: AgentType, context: Optional[Dict[str, Any]] = None):
        """Switch to a specific agent with improved handoff workflow."""
        logger.info(f"\n=== STARTING AGENT SWITCH ===")
        logger.info(f"From: {self.current_agent_type.value} -> To: {agent_type.value}")
        
        # Store any context for the handoff
        if context:
            for key, value in context.items():
                self.session_manager.set_conversation_context(key, value)
            logger.info(f"Context stored: {context}")
        
        try:
            # Step 1: Orchestrator confirms the handoff (if switching from orchestrator)
            if self.current_agent_type == AgentType.ORCHESTRATOR and agent_type != AgentType.ORCHESTRATOR:
                specialist_name = agent_type.value.replace('_', ' ').title()
                confirmation_msg = f"I'm connecting you with our {specialist_name} specialist now. One moment please..."
                await self._send_text_response(confirmation_msg)
                logger.info(f"Orchestrator confirmation sent: {confirmation_msg}")
                
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
            
            # # Step 4: Send agent greeting
            # if agent_config and agent_config.greeting:
            #     logger.info(f"New agent: {agent_config.name}")
            #     await self._send_agent_greeting(agent_config)
            #     print(f"\n🤖 Switched to: {agent_config.name}")
            # else:
            #     print(f"\n🤖 Switched to: {agent_type.value}")
            
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


        """
                # Create strongly typed session configuration
                session_config = RequestSession(
                    modalities=[Modality.TEXT, Modality.AUDIO],
                    instructions="You are Dr. Sarah Chen, a Cardiology Specialist Agent. You ONLY handle heart-related medical questions and procedures. "
                            "Your expertise includes: arrhythmias, heart attacks, chest pain, blood pressure, cardiac procedures, and heart medications. "
                            "HANDOFF SIGNALS: "
                            "- If asked about bones, joints, or injuries, say 'HANDOFF_ORTHOPEDIC' and stop responding "
                            "- If asked about brain, mental health, or neurological issues, say 'HANDOFF_NEUROLOGY' and stop responding "
                            "- If asked about skin conditions or rashes, say 'HANDOFF_DERMATOLOGY' and stop responding "
                            "- If asked about children's health or pediatrics, say 'HANDOFF_PEDIATRICS' and stop responding "
                            "- If asked about general practice or non-cardiac topics, say 'HANDOFF_GENERAL' and stop responding "
                            "Always speak confidently about cardiac matters and use medical terminology. "
                            "When you detect a handoff signal topic, immediately announce the handoff code and explain you're transferring them to the appropriate specialist.",
                    voice=voice_config,
                    input_audio_format=InputAudioFormat.PCM16,
                    output_audio_format=OutputAudioFormat.PCM16,
                    turn_detection=turn_detection_config,
                )
                conn = self.connection
        """
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
    
    async def _send_agent_greeting(self, agent_config):
        """Send the agent's greeting via the VoiceLive connection."""
        try:
            if agent_config and agent_config.greeting:
                # Wait a moment for the session to be fully established
                await asyncio.sleep(0.5)
                
                conn = self.connection
                if conn and hasattr(conn, 'response'):
                    # Create a response with the greeting
                    from azure.ai.voicelive.models import ResponseCreateParams
                    greeting_instruction = f"You have just been connected to assist this user. Please introduce yourself by saying: '{agent_config.greeting}'"
                    response_params = ResponseCreateParams(
                        instructions=greeting_instruction
                    )
                    await conn.response.create(response=response_params)
                    logger.info(f"Sent agent greeting: {agent_config.greeting}")
                    print(f"💬 {agent_config.name}: {agent_config.greeting}")
                else:
                    logger.warning("Cannot send agent greeting - connection not available")
            else:
                logger.info("No greeting configured for this agent")
        except Exception as e:
            logger.error(f"Failed to send agent greeting: {e}")
    
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
                
                # Step 1: Orchestrator confirms the handoff
                target_agent_config = self.agent_registry.get_agent(target_agent)
                handoff_message = f"I'm connecting you with {target_agent_config.name.split(' - ')[0]} who can better assist you with your {context['user_concern'].lower()}. Please hold while I transfer you."
                
                # Send handoff confirmation via text-to-speech
                await self._send_text_response(handoff_message)
                
                # Step 2: Switch to the target agent
                await self._switch_to_agent(target_agent, context)
                
                # Step 3: Have the new agent introduce itself with greeting
                # await self._send_agent_greeting(target_agent_config)
                
                logger.info(f"=== FUNCTION CALL COMPLETED - SWITCHED TO {target_agent.value} ===")
                return True
            else:
                logger.warning(f"Unknown function call: {function_name}")
                logger.warning(f"Available functions: {list(self.agent_registry.get_agent_by_function_name.__code__.co_consts)}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling function call: {e}")
            logger.error(f"Exception details:", exc_info=True)
            return False

    async def _process_events(self):
        """Process events from the VoiceLive connection."""
        try:
            conn = self.connection
            assert conn is not None, "Connection must be established before processing events"
            async for event in conn:
                await self._handle_event(event)

        except KeyboardInterrupt:
            logger.info("Event processing interrupted")
        except Exception as e:
            logger.error(f"Error processing events: {e}")
            raise

    async def _handle_event(self, event):
        """Handle different types of events from VoiceLive."""
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
            # Import json at the top of the file if not already imported

            # Replace the selection with:
            logger.info("🤖 Assistant response created")
            try:
                response_data = {
                    "id": event.response.id,
                    "conversation_id": event.response.conversation_id,
                    "status": event.response.status,
                    "status_details": getattr(event.response, 'status_details', None),
                    "output": getattr(event.response, 'output', None),
                    "usage": getattr(event.response, 'usage', None)
                }
                # Remove None values for cleaner output
                response_data = {k: v for k, v in response_data.items() if v is not None}
                
                logger.info("Response details:\n" + json.dumps(response_data, indent=2, default=str))
            except Exception as e:
                logger.warning(f"Could not format response data: {e}")
                logger.debug(f"Raw response object: {event.response}")

        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            # Stream audio response to speakers
            logger.debug("Received audio delta")
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
            
            # # Check if this was the orchestrator agent and no handoff occurred
            # if self.current_agent_type == AgentType.ORCHESTRATOR:
            #     logger.info("Response completed by orchestrator - staying with orchestrator")
            # else:
            #     # For specialist agents, return to orchestrator after response
            #     logger.info(f"Specialist {self.current_agent_type.value} response completed - returning to orchestrator")
            #     await self._switch_to_agent(AgentType.ORCHESTRATOR)
            #     print("🔄 Returned to orchestrator - ready for next request")

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
            if hasattr(event, 'call') and event.call:
                logger.info(f"Processing function call: {event.call.name}")
                success = await self._handle_function_call(event.call)
                if success:
                    logger.info("Function call handled successfully - agent should have switched")
                else:
                    logger.warning("Function call handling failed")
            else:
                logger.warning("Function call event received but no call object found")
        
        elif event.type == ServerEventType.RESPONSE_OUTPUT_ITEM_ADDED:
            logger.debug(f"Response output item added: {getattr(event.item, 'id', 'unknown')}")
            
            # Check if this is a function call item
            if hasattr(event.item, 'name'):  # Function call item
                logger.info(f"Function call initiated: {event.item.name}")
                
        elif event.type == ServerEventType.RESPONSE_OUTPUT_ITEM_DONE:
            logger.debug(f"Response output item done: {getattr(event.item, 'id', 'unknown')}")
            
            # Check if this is a function call item that just completed
            if hasattr(event.item, 'name'):  # Function call item
                logger.info(f"Function call completed: {event.item.name}")
                
                # If this is a function call, we might need to trigger the switch here too
                if hasattr(event.item, 'call_id') and hasattr(event.item, 'arguments'):
                    logger.info("Function call item has arguments, attempting switch...")
                    # Create a mock function call object for processing
                    class MockCall:
                        def __init__(self, name, arguments):
                            self.name = name
                            self.arguments = arguments
                    
                    mock_call = MockCall(event.item.name, getattr(event.item, 'arguments', '{}'))
                    success = await self._handle_function_call(mock_call)
                    if success:
                        logger.info("Function call processed successfully from output item")

        else:
            logger.debug(f"Unhandled event type: {event.type}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Basic Voice Assistant using Azure VoiceLive SDK",
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
    """Main function."""
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

        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            logger.info("Received shutdown signal")
            raise KeyboardInterrupt()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start the assistant
        await assistant.start()

    except KeyboardInterrupt:
        print("👋 Voice assistant shut down. Goodbye!")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
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

    # Check audio system
    try:
        p = pyaudio.PyAudio()
        # Check for input devices
        input_devices = [
            i
            for i in range(p.get_device_count())
            if cast(Union[int, float], p.get_device_info_by_index(i).get("maxInputChannels", 0) or 0) > 0
        ]
        # Check for output devices
        output_devices = [
            i
            for i in range(p.get_device_count())
            if cast(Union[int, float], p.get_device_info_by_index(i).get("maxOutputChannels", 0) or 0) > 0
        ]
        p.terminate()

        if not input_devices:
            print("❌ No audio input devices found. Please check your microphone.")
            sys.exit(1)
        if not output_devices:
            print("❌ No audio output devices found. Please check your speakers.")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Audio system check failed: {e}")
        sys.exit(1)

    print("🎙️  Basic Voice Assistant with Azure VoiceLive SDK")
    print("=" * 50)

    # Run the assistant
    asyncio.run(main())