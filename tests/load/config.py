"""
Load test configuration and shared utilities for RTMedAgent testing
"""
import os
import json
import time
import random
from typing import Dict, Any, Optional
from dataclasses import dataclass
from faker import Faker

fake = Faker()

@dataclass
class TestConfig:
    """Centralized configuration for load tests"""
    # API Configuration
    api_base_url: str = os.getenv("API_BASE_URL", "https://rtmedagent-api.azurewebsites.net")
    websocket_base_url: str = os.getenv("WS_BASE_URL", "wss://rtmedagent-api.azurewebsites.net")
    
    # Authentication
    azure_client_id: str = os.getenv("AZURE_CLIENT_ID", "")
    azure_client_secret: str = os.getenv("AZURE_CLIENT_SECRET", "")
    azure_tenant_id: str = os.getenv("AZURE_TENANT_ID", "")
    
    # Service Endpoints
    acs_endpoint: str = os.getenv("ACS_ENDPOINT", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    cosmos_endpoint: str = os.getenv("COSMOS_ENDPOINT", "")
    openai_endpoint: str = os.getenv("OPENAI_ENDPOINT", "")
    
    # Test Parameters
    test_duration_seconds: int = int(os.getenv("TEST_DURATION", "300"))
    ramp_up_seconds: int = int(os.getenv("RAMP_UP_TIME", "60"))
    max_concurrent_users: int = int(os.getenv("MAX_USERS", "100"))
    
    # Performance Targets (from load testing doc)
    websocket_handshake_target_ms: int = 150
    ping_pong_rtt_target_ms: int = 250
    stt_first_partial_target_ms: int = 400
    stt_final_segment_target_ms: int = 1000
    llm_ttft_target_ms: int = 600
    tts_first_byte_target_ms: int = 200
    end_to_end_voice_loop_target_ms: int = 700

class TestDataGenerator:
    """Generate realistic test data for medical agent scenarios"""
    
    @staticmethod
    def generate_phone_number() -> str:
        """Generate a valid US phone number for testing"""
        return f"+1555{random.randint(1000000, 9999999)}"
    
    @staticmethod
    def generate_call_data() -> Dict[str, Any]:
        """Generate realistic call initiation data"""
        return {
            "agent_type": "medical",
            "caller_number": TestDataGenerator.generate_phone_number(),
            "language": random.choice(["en-US", "es-US", "fr-CA"]),
            "priority": random.choice(["normal", "urgent", "emergency"]),
            "patient_id": fake.uuid4(),
            "appointment_type": random.choice([
                "general_consultation", 
                "follow_up", 
                "urgent_care", 
                "mental_health"
            ])
        }
    
    @staticmethod
    def generate_medical_query() -> str:
        """Generate realistic medical queries for testing"""
        queries = [
            "I've been having chest pain for the past hour",
            "My child has a fever of 102°F and won't eat",
            "I need to schedule a follow-up appointment",
            "Can you explain my lab results?",
            "I'm experiencing shortness of breath",
            "I need a prescription refill for my diabetes medication",
            "I have questions about my upcoming surgery",
            "I'm having side effects from my new medication"
        ]
        return random.choice(queries)
    
    @staticmethod
    def generate_audio_chunk() -> Dict[str, Any]:
        """Generate mock audio chunk data"""
        return {
            "type": "audio_chunk",
            "format": "pcm",
            "sample_rate": 16000,
            "channels": 1,
            "data": "mock_audio_data_" + fake.uuid4()[:8],
            "timestamp": time.time() * 1000,  # milliseconds
            "sequence": random.randint(1, 1000)
        }
    
    @staticmethod
    def generate_websocket_message(message_type: str) -> Dict[str, Any]:
        """Generate various WebSocket message types"""
        base_message = {
            "type": message_type,
            "timestamp": time.time() * 1000,
            "session_id": fake.uuid4()
        }
        
        if message_type == "audio_chunk":
            base_message.update(TestDataGenerator.generate_audio_chunk())
        elif message_type == "start_speech":
            base_message.update({
                "language": "en-US",
                "interim_results": True
            })
        elif message_type == "end_speech":
            base_message.update({
                "final_transcript": TestDataGenerator.generate_medical_query()
            })
        elif message_type == "agent_response":
            base_message.update({
                "response_text": "I understand your concern. Let me help you with that.",
                "response_audio_url": f"https://audio-service.com/response/{fake.uuid4()}.wav"
            })
        
        return base_message

class PerformanceTracker:
    """Track and validate performance metrics during load tests"""
    
    def __init__(self):
        self.metrics = []
        self.config = TestConfig()
    
    def record_metric(self, operation: str, duration_ms: float, success: bool, **kwargs):
        """Record a performance metric"""
        metric = {
            "operation": operation,
            "duration_ms": duration_ms,
            "success": success,
            "timestamp": time.time(),
            **kwargs
        }
        self.metrics.append(metric)
    
    def validate_performance(self, operation: str, duration_ms: float) -> bool:
        """Validate if performance meets targets"""
        targets = {
            "websocket_handshake": self.config.websocket_handshake_target_ms,
            "ping_pong": self.config.ping_pong_rtt_target_ms,
            "stt_partial": self.config.stt_first_partial_target_ms,
            "stt_final": self.config.stt_final_segment_target_ms,
            "llm_ttft": self.config.llm_ttft_target_ms,
            "tts_first_byte": self.config.tts_first_byte_target_ms,
            "voice_loop": self.config.end_to_end_voice_loop_target_ms
        }
        
        target = targets.get(operation)
        return target is None or duration_ms <= target
    
    def get_statistics(self) -> Dict[str, Any]:
        """Calculate performance statistics"""
        if not self.metrics:
            return {}
        
        operations = {}
        for metric in self.metrics:
            op = metric["operation"]
            if op not in operations:
                operations[op] = []
            operations[op].append(metric["duration_ms"])
        
        stats = {}
        for op, durations in operations.items():
            durations.sort()
            count = len(durations)
            stats[op] = {
                "count": count,
                "mean": sum(durations) / count,
                "median": durations[count // 2],
                "p95": durations[int(count * 0.95)] if count > 20 else durations[-1],
                "p99": durations[int(count * 0.99)] if count > 100 else durations[-1],
                "min": min(durations),
                "max": max(durations)
            }
        
        return stats

# Global configuration instance
config = TestConfig()
performance_tracker = PerformanceTracker()
