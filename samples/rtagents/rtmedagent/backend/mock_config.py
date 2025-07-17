"""
Mock service configurations for load testing
Provides realistic mock implementations with configurable latency and error injection
"""
import asyncio
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MockConfig:
    """Configuration for mock services"""

    # Latency simulation settings (in seconds)
    redis_latency_range: tuple = (0.001, 0.005)  # 1-5ms
    cosmos_latency_range: tuple = (0.020, 0.080)  # 20-80ms
    openai_latency_range: tuple = (0.200, 0.800)  # 200-800ms
    speech_latency_range: tuple = (0.100, 0.400)  # 100-400ms

    # Error injection rates (0.0 = no errors, 1.0 = all errors)
    redis_error_rate: float = 0.01  # 1% error rate
    cosmos_error_rate: float = 0.02  # 2% error rate
    openai_error_rate: float = 0.03  # 3% error rate
    speech_error_rate: float = 0.02  # 2% error rate

    # Mock data settings
    enable_realistic_responses: bool = True
    enable_latency_simulation: bool = True
    enable_error_injection: bool = True

    # Performance tracking
    track_performance_metrics: bool = True
    log_slow_operations: bool = True
    slow_operation_threshold_ms: float = 1000.0


# Load configuration from environment variables
def load_mock_config() -> MockConfig:
    """Load mock configuration from environment variables"""
    return MockConfig(
        # Latency ranges
        redis_latency_range=(
            float(os.getenv("MOCK_REDIS_MIN_LATENCY", "0.001")),
            float(os.getenv("MOCK_REDIS_MAX_LATENCY", "0.005")),
        ),
        cosmos_latency_range=(
            float(os.getenv("MOCK_COSMOS_MIN_LATENCY", "0.020")),
            float(os.getenv("MOCK_COSMOS_MAX_LATENCY", "0.080")),
        ),
        openai_latency_range=(
            float(os.getenv("MOCK_OPENAI_MIN_LATENCY", "0.200")),
            float(os.getenv("MOCK_OPENAI_MAX_LATENCY", "0.800")),
        ),
        speech_latency_range=(
            float(os.getenv("MOCK_SPEECH_MIN_LATENCY", "0.100")),
            float(os.getenv("MOCK_SPEECH_MAX_LATENCY", "0.400")),
        ),
        # Error rates
        redis_error_rate=float(os.getenv("MOCK_REDIS_ERROR_RATE", "0.01")),
        cosmos_error_rate=float(os.getenv("MOCK_COSMOS_ERROR_RATE", "0.02")),
        openai_error_rate=float(os.getenv("MOCK_OPENAI_ERROR_RATE", "0.03")),
        speech_error_rate=float(os.getenv("MOCK_SPEECH_ERROR_RATE", "0.02")),
        # Feature flags
        enable_realistic_responses=os.getenv("MOCK_REALISTIC_RESPONSES", "true").lower()
        == "true",
        enable_latency_simulation=os.getenv("MOCK_LATENCY_SIMULATION", "true").lower()
        == "true",
        enable_error_injection=os.getenv("MOCK_ERROR_INJECTION", "true").lower()
        == "true",
        # Performance settings
        track_performance_metrics=os.getenv("MOCK_TRACK_PERFORMANCE", "true").lower()
        == "true",
        log_slow_operations=os.getenv("MOCK_LOG_SLOW_OPS", "true").lower() == "true",
        slow_operation_threshold_ms=float(
            os.getenv("MOCK_SLOW_THRESHOLD_MS", "1000.0")
        ),
    )


# Helper functions for mock services
async def simulate_latency(
    latency_range: tuple, operation_name: str = "operation"
) -> float:
    """Simulate realistic latency for mock operations"""
    config = load_mock_config()

    if not config.enable_latency_simulation:
        return 0.0

    latency = random.uniform(*latency_range)
    await asyncio.sleep(latency)

    latency_ms = latency * 1000
    if config.log_slow_operations and latency_ms > config.slow_operation_threshold_ms:
        print(f"⚠️  Slow mock operation: {operation_name} took {latency_ms:.2f}ms")

    return latency_ms


def should_inject_error(error_rate: float, operation_name: str = "operation") -> bool:
    """Determine if an error should be injected based on configured rate"""
    config = load_mock_config()

    if not config.enable_error_injection:
        return False

    if random.random() < error_rate:
        print(f"💥 Injecting error for mock operation: {operation_name}")
        return True

    return False


# Mock response generators
class MockResponseGenerator:
    """Generate realistic mock responses for different services"""

    @staticmethod
    def generate_medical_response() -> str:
        """Generate realistic medical agent responses"""
        responses = [
            "I understand your concern about your medication. Let me help you with that.",
            "Based on your symptoms, I recommend scheduling an appointment with your healthcare provider.",
            "That's a common question about insurance coverage. Here's what you need to know:",
            "I can help you understand your lab results. Let me explain what they mean.",
            "For emergency symptoms, please call 911 or go to the nearest emergency room immediately.",
            "Your prescription refill request has been processed. You can pick it up tomorrow.",
            "I've scheduled your appointment for next Tuesday at 2:30 PM with Dr. Smith.",
            "Your insurance covers this procedure with a $50 copay. Would you like to proceed?",
            "Let me check your medical history to provide the most accurate information.",
            "I'm transferring you to our billing specialist who can assist with payment options.",
        ]
        return random.choice(responses)

    @staticmethod
    def generate_cosmos_document() -> dict:
        """Generate realistic Cosmos DB document"""
        return {
            "id": f"doc_{random.randint(100000, 999999)}",
            "patient_id": f"patient_{random.randint(10000, 99999)}",
            "call_id": f"call_{random.randint(100000, 999999)}",
            "timestamp": "2024-01-15T10:30:00Z",
            "conversation_summary": MockResponseGenerator.generate_medical_response(),
            "intent": random.choice(
                ["medication", "billing", "appointment", "general"]
            ),
            "sentiment": random.choice(["positive", "neutral", "concerned"]),
            "metadata": {
                "duration_seconds": random.randint(60, 300),
                "agent_version": "v1.0.0",
                "language": "en-US",
            },
        }

    @staticmethod
    def generate_redis_session() -> dict:
        """Generate realistic Redis session data"""
        return {
            "session_id": f"session_{random.randint(100000, 999999)}",
            "user_id": f"user_{random.randint(10000, 99999)}",
            "last_activity": "2024-01-15T10:30:00Z",
            "conversation_state": random.choice(
                ["greeting", "collecting_info", "processing", "summary"]
            ),
            "intent_history": ["greeting", "medication_inquiry"],
            "context": {
                "current_topic": "prescription_refill",
                "urgency_level": random.choice(["low", "medium", "high"]),
                "language_preference": "en-US",
            },
        }


# Export the default configuration
MOCK_CONFIG = load_mock_config()
