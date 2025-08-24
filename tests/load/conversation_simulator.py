#!/usr/bin/env python3
"""
Realistic Conversation Simulator for Agent Flow Testing
=======================================================

Simulates realistic human-AI conversations based on actual speech patterns
observed in the server logs to enable proper load testing and agent evaluation.
"""

import asyncio
import json
import base64
import websockets
import struct
import math
import time
import random
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

class ConversationPhase(Enum):
    GREETING = "greeting"
    AUTHENTICATION = "authentication"  
    INQUIRY = "inquiry"
    CLARIFICATION = "clarification"
    RESOLUTION = "resolution"
    FAREWELL = "farewell"

@dataclass
class ConversationTurn:
    """Represents a single turn in a conversation."""
    speaker: str  # "user" or "agent"
    text: str
    phase: ConversationPhase
    delay_before_ms: int = 500  # Pause before speaking
    speech_duration_ms: Optional[int] = None  # Override calculated duration
    interruption_likely: bool = False  # Whether agent might interrupt

@dataclass
class ConversationTemplate:
    """Template for a complete conversation flow."""
    name: str
    description: str
    turns: List[ConversationTurn]
    expected_agent: str = "AuthAgent"
    success_indicators: List[str] = field(default_factory=list)

@dataclass
class ConversationMetrics:
    """Metrics collected during conversation simulation."""
    session_id: str
    template_name: str
    start_time: float
    end_time: float
    connection_time_ms: float
    
    # Turn-level metrics
    user_turns: int = 0
    agent_turns: int = 0
    total_speech_recognition_time_ms: float = 0
    total_agent_processing_time_ms: float = 0
    total_tts_time_ms: float = 0
    
    # Quality metrics
    successful_turns: int = 0
    failed_turns: int = 0
    interruptions_detected: int = 0
    barge_ins_detected: int = 0
    
    # Server responses
    server_responses: List[Dict[str, Any]] = field(default_factory=list)
    audio_chunks_received: int = 0
    errors: List[str] = field(default_factory=list)

class RealisticSpeechGenerator:
    """Generates realistic speech audio patterns that trigger Azure Speech Recognition."""
    
    @staticmethod
    def create_speech_audio(text: str, rate: int = 16000, style: str = "conversational") -> bytes:
        """Generate speech audio optimized for Azure Speech Recognition."""
        # Calculate duration - make longer for better recognition
        words = len(text.split())
        chars = len(text)
        
        # Longer duration helps with speech recognition
        duration_s = max(2.0, words * 0.6 + chars * 0.08)  # ~100 WPM, longer syllables
        
        samples = int(duration_s * rate)
        pcm = bytearray()
        
        # Use standard speech frequency ranges that Azure recognizes well
        base_freq = 150  # Standard adult male fundamental
        
        # Create vowel-consonant patterns for each word
        word_list = text.split()
        samples_per_word = samples // max(1, len(word_list))
        
        for word_idx, word in enumerate(word_list):
            word_start = word_idx * samples_per_word
            word_end = min(samples, (word_idx + 1) * samples_per_word)
            
            for i in range(word_start, word_end):
                t = i / rate
                word_progress = (i - word_start) / max(1, word_end - word_start)
                
                # Strong speech envelope for each word
                if word_progress < 0.1:  # Sharp attack
                    envelope = word_progress * 10
                elif word_progress > 0.9:  # Gradual decay
                    envelope = 1.0 - (word_progress - 0.9) * 5
                else:  # Sustained vowel portion
                    envelope = 0.8 + 0.2 * math.sin(2 * math.pi * 5 * t)  # Slight vibrato
                
                envelope = max(0, min(1.0, envelope))
                
                # Create strong harmonic structure (key for speech recognition)
                fundamental = base_freq * (1.0 + 0.1 * math.sin(2 * math.pi * 3 * t))  # Natural pitch variation
                
                signal = 0.0
                
                # Strong fundamental and harmonics (essential for speech detection)
                signal += 0.6 * math.sin(2 * math.pi * fundamental * t) * envelope
                signal += 0.4 * math.sin(2 * math.pi * fundamental * 2 * t) * envelope * 0.8
                signal += 0.3 * math.sin(2 * math.pi * fundamental * 3 * t) * envelope * 0.6
                signal += 0.2 * math.sin(2 * math.pi * fundamental * 4 * t) * envelope * 0.4
                
                # Add formant frequencies (vowel characteristics)
                # First formant (300-800 Hz)
                f1 = 500 + 200 * math.sin(2 * math.pi * 0.5 * word_progress)
                signal += 0.5 * math.sin(2 * math.pi * f1 * t) * envelope
                
                # Second formant (900-2200 Hz) - most important for intelligibility
                f2 = 1200 + 400 * math.sin(2 * math.pi * 0.7 * word_progress)
                signal += 0.4 * math.sin(2 * math.pi * f2 * t) * envelope * 0.9
                
                # Add some broadband energy (fricatives, etc.)
                if word_progress > 0.3 and word_progress < 0.7:  # Consonant-like sounds
                    fricative = 0.15 * (2 * random.random() - 1.0) * envelope
                    signal += fricative
                
                # Ensure good signal-to-noise ratio for recognition
                signal = signal * envelope
                
                # Apply realistic vocal tract filtering
                if signal > 0:
                    signal = math.tanh(signal * 2.0) * 0.8
                else:
                    signal = -math.tanh(-signal * 2.0) * 0.8
                
                # Convert to 16-bit PCM with strong signal level
                # Azure needs sufficient amplitude to detect speech
                sample = int(max(-32767, min(32767, signal * 25000)))  # Higher amplitude
                pcm += struct.pack('<h', sample)
            
            # Add brief pause between words (helps with recognition)
            if word_idx < len(word_list) - 1:
                pause_samples = int(0.1 * rate)  # 100ms pause
                for _ in range(pause_samples):
                    # Very quiet background noise during pause
                    noise_sample = int((2 * random.random() - 1.0) * 200)
                    pcm += struct.pack('<h', noise_sample)
        
        # Ensure minimum duration for recognition
        while len(pcm) < int(2.0 * rate * 2):  # At least 2 seconds
            pcm += struct.pack('<h', 0)
        
        return bytes(pcm)

class ConversationTemplates:
    """Pre-defined conversation templates for different scenarios."""
    
    @staticmethod
    def get_insurance_inquiry() -> ConversationTemplate:
        """Standard insurance inquiry conversation."""
        return ConversationTemplate(
            name="insurance_inquiry",
            description="Customer calling to ask about insurance coverage",
            turns=[
                ConversationTurn("user", "Hello, what's up?", ConversationPhase.GREETING, delay_before_ms=1000),
                ConversationTurn("user", "I'm looking to learn about Madrid.", ConversationPhase.INQUIRY, delay_before_ms=2000),
                ConversationTurn("user", "Actually, I need help with my car insurance.", ConversationPhase.CLARIFICATION, delay_before_ms=1500),
                ConversationTurn("user", "What does my policy cover?", ConversationPhase.INQUIRY, delay_before_ms=800),
                ConversationTurn("user", "Thank you for the information.", ConversationPhase.FAREWELL, delay_before_ms=1200),
            ],
            expected_agent="AuthAgent",
            success_indicators=["insurance", "policy", "coverage", "help"]
        )
    
    @staticmethod
    def get_quick_question() -> ConversationTemplate:
        """Short, quick question scenario."""
        return ConversationTemplate(
            name="quick_question",
            description="Brief customer inquiry",
            turns=[
                ConversationTurn("user", "Hi there!", ConversationPhase.GREETING, delay_before_ms=500),
                ConversationTurn("user", "Can you help me with my account?", ConversationPhase.INQUIRY, delay_before_ms=800),
                ConversationTurn("user", "Thanks, that's all I needed.", ConversationPhase.FAREWELL, delay_before_ms=1000),
            ],
            expected_agent="AuthAgent",
            success_indicators=["account", "help"]
        )
    
    @staticmethod
    def get_confused_customer() -> ConversationTemplate:
        """Customer who starts confused but gets clarity."""
        return ConversationTemplate(
            name="confused_customer",
            description="Customer initially confused about what they need",
            turns=[
                ConversationTurn("user", "Um, hello?", ConversationPhase.GREETING, delay_before_ms=800),
                ConversationTurn("user", "I'm not sure what I need help with.", ConversationPhase.INQUIRY, delay_before_ms=1200),
                ConversationTurn("user", "Maybe something about my insurance?", ConversationPhase.CLARIFICATION, delay_before_ms=1000),
                ConversationTurn("user", "Yes, that's right. My auto insurance.", ConversationPhase.INQUIRY, delay_before_ms=900),
            ],
            expected_agent="AuthAgent", 
            success_indicators=["insurance", "auto", "help"]
        )
    
    @staticmethod
    def get_all_templates() -> List[ConversationTemplate]:
        """Get all available conversation templates."""
        return [
            ConversationTemplates.get_insurance_inquiry(),
            ConversationTemplates.get_quick_question(),
            ConversationTemplates.get_confused_customer(),
        ]

class ConversationSimulator:
    """Simulates realistic conversations for load testing and agent evaluation."""
    
    def __init__(self, ws_url: str = "ws://localhost:8010/api/v1/media/stream"):
        self.ws_url = ws_url
        self.speech_generator = RealisticSpeechGenerator()
    
    async def simulate_conversation(
        self, 
        template: ConversationTemplate,
        session_id: Optional[str] = None,
        on_turn_complete: Optional[Callable[[ConversationTurn, List[Dict]], None]] = None,
        on_agent_response: Optional[Callable[[str, List[Dict]], None]] = None
    ) -> ConversationMetrics:
        """Simulate a complete conversation using the given template."""
        
        if session_id is None:
            session_id = f"{template.name}-{int(time.time())}-{random.randint(1000, 9999)}"
        
        metrics = ConversationMetrics(
            session_id=session_id,
            template_name=template.name,
            start_time=time.time(),
            end_time=0,
            connection_time_ms=0
        )
        
        print(f"🎭 Starting conversation simulation: {template.name}")
        print(f"📞 Session ID: {session_id}")
        
        try:
            # Connect to WebSocket
            connect_start = time.time()
            async with websockets.connect(
                f"{self.ws_url}?call_connection_id={session_id}",
                additional_headers={"x-ms-call-connection-id": session_id}
            ) as websocket:
                metrics.connection_time_ms = (time.time() - connect_start) * 1000
                print(f"✅ Connected in {metrics.connection_time_ms:.1f}ms")
                
                # Send audio metadata
                metadata = {
                    "kind": "AudioMetadata",
                    "payload": {"format": "pcm", "rate": 16000}
                }
                await websocket.send(json.dumps(metadata))
                
                # Wait for system initialization
                await asyncio.sleep(1.0)
                
                # Process each conversation turn
                for turn_idx, turn in enumerate(template.turns):
                    if turn.speaker == "user":
                        print(f"\n👤 User turn {turn_idx + 1}: '{turn.text}' ({turn.phase.value})")
                        
                        # Wait before speaking (natural pause) - longer pause to let previous response finish
                        pause_time = max(turn.delay_before_ms / 1000.0, 3.0)  # At least 3 seconds
                        print(f"    ⏸️  Waiting {pause_time:.1f}s for agent to finish speaking...")
                        await asyncio.sleep(pause_time)
                        
                        # Generate and send speech audio in a more natural way
                        turn_start = time.time()
                        
                        # Create shorter, more natural speech burst
                        speech_audio = self.speech_generator.create_speech_audio(
                            turn.text, 
                            style="conversational"
                        )
                        
                        # Send audio more quickly to simulate natural speech timing
                        chunk_size = int(16000 * 0.1 * 2)  # Back to 100ms chunks for natural flow
                        audio_chunks_sent = 0
                        
                        print(f"    🎤 Speaking: '{turn.text}'")
                        
                        for i in range(0, len(speech_audio), chunk_size):
                            chunk = speech_audio[i:i + chunk_size]
                            chunk_b64 = base64.b64encode(chunk).decode('utf-8')
                            
                            audio_msg = {
                                "kind": "AudioData",
                                "audioData": {
                                    "data": chunk_b64,
                                    "silent": False,
                                    "timestamp": time.time()
                                }
                            }
                            
                            await websocket.send(json.dumps(audio_msg))
                            audio_chunks_sent += 1
                            
                            # Natural speech timing
                            await asyncio.sleep(0.08)  # 80ms between chunks - more natural
                        
                        print(f"    📤 Sent {audio_chunks_sent} audio chunks ({len(speech_audio)} bytes total)")
                        print(f"    🎵 Audio duration: {len(speech_audio)/(16000*2):.2f}s")
                        
                        # Small pause after speaking (like real conversation)
                        await asyncio.sleep(0.5)
                        
                        metrics.user_turns += 1
                        metrics.total_speech_recognition_time_ms += (time.time() - turn_start) * 1000
                        
                        # Listen for agent responses
                        responses = []
                        agent_start = time.time()
                        
                        # Give extra time after sending audio for speech recognition to process
                        print(f"    ⏳ Waiting for speech recognition and agent response...")
                        await asyncio.sleep(2.0)  # Allow time for speech processing
                        
                        try:
                            # Listen for responses for longer time to catch speech recognition
                            listen_duration = max(8.0, len(turn.text.split()) * 1.0)  # More time for recognition
                            responses_received = 0
                            
                            while time.time() - agent_start < listen_duration:
                                try:
                                    response = await asyncio.wait_for(websocket.recv(), timeout=3.0)  # Longer timeout
                                    response_data = json.loads(response)
                                    responses.append(response_data)
                                    metrics.server_responses.append(response_data)
                                    responses_received += 1
                                    
                                    # Count audio responses (agent speech)
                                    if response_data.get('kind') == 'AudioData':
                                        metrics.audio_chunks_received += 1
                                        
                                    # Print first few responses for debugging
                                    if responses_received <= 3:
                                        resp_type = response_data.get('kind', response_data.get('type', 'unknown'))
                                        print(f"      📨 Response {responses_received}: {resp_type}")
                                        
                                except asyncio.TimeoutError:
                                    break  # No more immediate responses
                        
                        except Exception as e:
                            metrics.errors.append(f"Turn {turn_idx + 1}: {str(e)}")
                        
                        agent_processing_time = (time.time() - agent_start) * 1000
                        metrics.total_agent_processing_time_ms += agent_processing_time
                        
                        print(f"  🤖 Agent responded with {len(responses)} messages in {agent_processing_time:.1f}ms")
                        print(f"  📊 Audio chunks received: {len([r for r in responses if r.get('kind') == 'AudioData'])}")
                        
                        # Callback for turn completion
                        if on_turn_complete:
                            try:
                                on_turn_complete(turn, responses)
                            except Exception as e:
                                print(f"  ⚠️ Turn callback error: {e}")
                        
                        # Callback for agent responses
                        if on_agent_response and responses:
                            try:
                                on_agent_response(turn.text, responses)
                            except Exception as e:
                                print(f"  ⚠️ Agent callback error: {e}")
                        
                        # Brief pause before next turn
                        await asyncio.sleep(0.5)
                
                print(f"\n✅ Conversation completed successfully")
                metrics.end_time = time.time()
                
        except Exception as e:
            print(f"❌ Conversation failed: {e}")
            metrics.errors.append(f"Conversation error: {str(e)}")
            metrics.end_time = time.time()
        
        return metrics

    def analyze_metrics(self, metrics: ConversationMetrics) -> Dict[str, Any]:
        """Analyze conversation metrics and return insights."""
        duration_s = metrics.end_time - metrics.start_time
        
        analysis = {
            "session_id": metrics.session_id,
            "template": metrics.template_name,
            "success": len(metrics.errors) == 0,
            "duration_s": duration_s,
            "connection_time_ms": metrics.connection_time_ms,
            
            # Turn metrics
            "user_turns": metrics.user_turns,
            "agent_turns": len([r for r in metrics.server_responses if r.get('kind') == 'AudioData']),
            "total_responses": len(metrics.server_responses),
            
            # Performance metrics
            "avg_speech_recognition_ms": metrics.total_speech_recognition_time_ms / max(1, metrics.user_turns),
            "avg_agent_processing_ms": metrics.total_agent_processing_time_ms / max(1, metrics.user_turns),
            "audio_chunks_received": metrics.audio_chunks_received,
            
            # Quality metrics
            "error_count": len(metrics.errors),
            "errors": metrics.errors,
            
            # Response analysis
            "response_types": {},
        }
        
        # Analyze response types
        for response in metrics.server_responses:
            resp_type = response.get('kind', response.get('type', 'unknown'))
            analysis["response_types"][resp_type] = analysis["response_types"].get(resp_type, 0) + 1
        
        return analysis

# Example usage and testing
async def main():
    """Example of how to use the conversation simulator."""
    simulator = ConversationSimulator()
    
    # Get a conversation template
    template = ConversationTemplates.get_insurance_inquiry()
    
    # Define callbacks for monitoring
    def on_turn_complete(turn: ConversationTurn, responses: List[Dict]):
        print(f"  📋 Turn completed: {len(responses)} responses")
    
    def on_agent_response(user_text: str, responses: List[Dict]):
        audio_responses = len([r for r in responses if r.get('kind') == 'AudioData'])
        print(f"  🎤 Agent generated {audio_responses} audio responses to: '{user_text[:30]}...'")
    
    # Run simulation
    metrics = await simulator.simulate_conversation(
        template,
        on_turn_complete=on_turn_complete,
        on_agent_response=on_agent_response
    )
    
    # Analyze results
    analysis = simulator.analyze_metrics(metrics)
    
    print(f"\n📊 CONVERSATION ANALYSIS")
    print(f"=" * 50)
    print(f"Success: {'✅' if analysis['success'] else '❌'}")
    print(f"Duration: {analysis['duration_s']:.2f}s")
    print(f"Connection: {analysis['connection_time_ms']:.1f}ms")
    print(f"User turns: {analysis['user_turns']}")
    print(f"Agent responses: {analysis['audio_chunks_received']}")
    print(f"Avg recognition time: {analysis['avg_speech_recognition_ms']:.1f}ms")
    print(f"Avg agent processing: {analysis['avg_agent_processing_ms']:.1f}ms")
    
    if analysis['errors']:
        print(f"❌ Errors: {analysis['error_count']}")
        for error in analysis['errors']:
            print(f"  - {error}")

if __name__ == "__main__":
    asyncio.run(main())