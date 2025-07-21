"""
Load tests for backend services
Tests Redis, Azure Speech, OpenAI, Cosmos DB, and storage services
"""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

import openai
from config import PerformanceTracker, TestDataGenerator, config
from locust import User, between, events, task

import redis

# Import Azure SDK components (these would need to be properly configured)
try:
    from azure.cognitiveservices.speech import SpeechConfig, SpeechRecognizer
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    print("Azure SDKs not available - service tests will be simulated")


class BackendServicesUser(User):
    """User for testing backend services performance"""

    wait_time = between(1, 4)

    def __init__(self, environment):
        super().__init__(environment)
        self.performance_tracker = PerformanceTracker()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.session_id = f"test-session-{int(time.time())}-{id(self)}"

        # Initialize service clients
        self._init_service_clients()

    def _init_service_clients(self):
        """Initialize service clients"""
        try:
            # Redis client
            self.redis_client = redis.from_url(
                config.redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )

            # OpenAI client (for Azure OpenAI)
            if config.openai_endpoint:
                openai.api_type = "azure"
                openai.api_base = config.openai_endpoint
                openai.api_version = "2024-02-01"
                openai.api_key = "test-key"  # Would be from environment

            # Azure Cosmos DB client
            if AZURE_AVAILABLE and config.cosmos_endpoint:
                credential = DefaultAzureCredential()
                self.cosmos_client = CosmosClient(config.cosmos_endpoint, credential)
                self.database = self.cosmos_client.get_database_client("RTMedAgent")
                self.container = self.database.get_container_client("conversations")
            else:
                self.cosmos_client = None

        except Exception as e:
            print(f"Service initialization error: {e}")
            self.redis_client = None
            self.cosmos_client = None

    @task(8)
    def test_redis_session_operations(self):
        """Test Redis session storage and retrieval"""
        if not self.redis_client:
            return

        start_time = time.time()

        try:
            # Test session creation
            session_data = {
                "session_id": self.session_id,
                "call_id": f"call-{int(time.time())}",
                "participant_count": "2",
                "status": "active",
                "created_at": str(time.time()),
                "conversation_turns": "0",
            }

            # Set session data
            set_start = time.time()
            self.redis_client.hset(f"session:{self.session_id}", mapping=session_data)
            set_duration = (time.time() - set_start) * 1000

            # Add conversation history
            for turn in range(5):
                conversation_key = f"session:{self.session_id}:conversation"
                turn_data = {
                    f"turn_{turn}_user": TestDataGenerator.generate_medical_query(),
                    f"turn_{turn}_agent": f"I understand. Let me help you with that issue.",
                    f"turn_{turn}_timestamp": str(time.time()),
                }
                self.redis_client.hset(conversation_key, mapping=turn_data)

            # Test session retrieval
            get_start = time.time()
            session = self.redis_client.hgetall(f"session:{self.session_id}")
            conversation = self.redis_client.hgetall(
                f"session:{self.session_id}:conversation"
            )
            get_duration = (time.time() - get_start) * 1000

            # Test session update
            update_start = time.time()
            self.redis_client.hset(
                f"session:{self.session_id}",
                "status",
                "completed",
                "ended_at",
                str(time.time()),
            )
            update_duration = (time.time() - update_start) * 1000

            total_duration = (time.time() - start_time) * 1000

            # Record metrics
            self.performance_tracker.record_metric("redis_set", set_duration, True)
            self.performance_tracker.record_metric("redis_get", get_duration, True)
            self.performance_tracker.record_metric(
                "redis_update", update_duration, True
            )

            events.request.fire(
                request_type="Redis",
                name="session_operations",
                response_time=total_duration,
                response_length=len(str(session)) + len(str(conversation)),
                exception=None,
                context=self.context(),
            )

            # Cleanup
            self.redis_client.delete(f"session:{self.session_id}")
            self.redis_client.delete(f"session:{self.session_id}:conversation")

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="Redis",
                name="session_operations",
                response_time=duration,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    @task(5)
    def test_openai_completion(self):
        """Test Azure OpenAI completion performance"""
        start_time = time.time()

        try:
            # Simulate OpenAI completion request
            prompt_messages = [
                {
                    "role": "system",
                    "content": "You are a helpful medical assistant. Provide concise, accurate medical information.",
                },
                {"role": "user", "content": TestDataGenerator.generate_medical_query()},
            ]

            # Simulate API call (replace with actual OpenAI call in real test)
            future = self.executor.submit(
                self._simulate_openai_request, prompt_messages
            )
            result = future.result(timeout=10)

            duration = (time.time() - start_time) * 1000

            if result["success"]:
                # Validate TTFT target
                ttft_met = result["ttft_ms"] <= config.llm_ttft_target_ms

                self.performance_tracker.record_metric(
                    "openai_completion",
                    duration,
                    True,
                    ttft_ms=result["ttft_ms"],
                    tokens_generated=result["tokens"],
                    ttft_target_met=ttft_met,
                )

                events.request.fire(
                    request_type="OpenAI",
                    name="chat_completion",
                    response_time=duration,
                    response_length=result["tokens"] * 4,  # Approximate bytes
                    exception=None,
                    context=self.context(),
                )
            else:
                events.request.fire(
                    request_type="OpenAI",
                    name="chat_completion",
                    response_time=duration,
                    response_length=0,
                    exception=Exception(result["error"]),
                    context=self.context(),
                )

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="OpenAI",
                name="chat_completion",
                response_time=duration,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _simulate_openai_request(self, messages):
        """Simulate OpenAI request (replace with actual API call)"""
        try:
            # Simulate processing time
            ttft_delay = random.uniform(0.2, 0.8)  # 200-800ms TTFT
            time.sleep(ttft_delay)

            # Simulate token generation
            tokens_generated = random.randint(50, 200)
            generation_time = tokens_generated / 150.0  # ~150 tokens/second
            time.sleep(generation_time)

            return {
                "success": True,
                "ttft_ms": ttft_delay * 1000,
                "tokens": tokens_generated,
                "response": "I understand your concern. Based on your symptoms, I recommend...",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    @task(3)
    def test_cosmos_db_operations(self):
        """Test Cosmos DB conversation storage"""
        if not self.cosmos_client:
            # Simulate Cosmos DB operations
            self._simulate_cosmos_operations()
            return

        start_time = time.time()

        try:
            # Create conversation document
            conversation_doc = {
                "id": f"conv-{self.session_id}",
                "session_id": self.session_id,
                "call_id": f"call-{int(time.time())}",
                "patient_id": f"patient-{random.randint(10000, 99999)}",
                "agent_type": "medical",
                "conversation_history": [],
                "metadata": {
                    "created_at": time.time(),
                    "language": "en-US",
                    "priority": "normal",
                },
            }

            # Add conversation turns
            for turn in range(3):
                conversation_doc["conversation_history"].append(
                    {
                        "turn": turn + 1,
                        "user_message": TestDataGenerator.generate_medical_query(),
                        "agent_response": "I understand your concern. Let me help you with that.",
                        "timestamp": time.time(),
                        "processing_time_ms": random.randint(200, 800),
                    }
                )

            # Insert document
            insert_start = time.time()
            result = self.container.create_item(conversation_doc)
            insert_duration = (time.time() - insert_start) * 1000

            # Query document
            query_start = time.time()
            query = f"SELECT * FROM c WHERE c.session_id = '{self.session_id}'"
            items = list(
                self.container.query_items(query, enable_cross_partition_query=True)
            )
            query_duration = (time.time() - query_start) * 1000

            # Update document
            update_start = time.time()
            conversation_doc["metadata"]["completed_at"] = time.time()
            conversation_doc["status"] = "completed"
            self.container.replace_item(result["id"], conversation_doc)
            update_duration = (time.time() - update_start) * 1000

            total_duration = (time.time() - start_time) * 1000

            # Record metrics
            self.performance_tracker.record_metric(
                "cosmos_insert", insert_duration, True
            )
            self.performance_tracker.record_metric("cosmos_query", query_duration, True)
            self.performance_tracker.record_metric(
                "cosmos_update", update_duration, True
            )

            events.request.fire(
                request_type="CosmosDB",
                name="conversation_operations",
                response_time=total_duration,
                response_length=len(json.dumps(conversation_doc)),
                exception=None,
                context=self.context(),
            )

            # Cleanup
            self.container.delete_item(result["id"], partition_key=self.session_id)

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="CosmosDB",
                name="conversation_operations",
                response_time=duration,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _simulate_cosmos_operations(self):
        """Simulate Cosmos DB operations when client not available"""
        start_time = time.time()

        # Simulate typical Cosmos DB latencies
        insert_time = random.uniform(10, 50)  # 10-50ms
        query_time = random.uniform(5, 30)  # 5-30ms
        update_time = random.uniform(8, 40)  # 8-40ms

        time.sleep((insert_time + query_time + update_time) / 1000)

        total_duration = (time.time() - start_time) * 1000

        events.request.fire(
            request_type="CosmosDB",
            name="conversation_operations_simulated",
            response_time=total_duration,
            response_length=1024,  # Simulated response size
            exception=None,
            context=self.context(),
        )

    @task(2)
    def test_speech_services(self):
        """Test Azure Speech Services (simulated)"""
        start_time = time.time()

        try:
            # Simulate STT operation
            stt_future = self.executor.submit(self._simulate_stt_operation)
            stt_result = stt_future.result(timeout=8)

            # Simulate TTS operation
            tts_future = self.executor.submit(self._simulate_tts_operation)
            tts_result = tts_future.result(timeout=5)

            total_duration = (time.time() - start_time) * 1000

            # Validate performance targets
            stt_target_met = (
                stt_result["duration_ms"] <= config.stt_final_segment_target_ms
            )
            tts_target_met = (
                tts_result["duration_ms"] <= config.tts_first_byte_target_ms
            )

            self.performance_tracker.record_metric(
                "speech_stt",
                stt_result["duration_ms"],
                stt_result["success"],
                target_met=stt_target_met,
            )
            self.performance_tracker.record_metric(
                "speech_tts",
                tts_result["duration_ms"],
                tts_result["success"],
                target_met=tts_target_met,
            )

            events.request.fire(
                request_type="Speech",
                name="stt_tts_operations",
                response_time=total_duration,
                response_length=len(stt_result.get("transcript", ""))
                + tts_result.get("audio_bytes", 0),
                exception=None,
                context=self.context(),
            )

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="Speech",
                name="stt_tts_operations",
                response_time=duration,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _simulate_stt_operation(self):
        """Simulate Speech-to-Text operation"""
        # Simulate STT processing time (based on Azure Speech benchmarks)
        processing_time = random.uniform(0.3, 1.2)  # 300ms to 1.2s
        time.sleep(processing_time)

        return {
            "success": True,
            "duration_ms": processing_time * 1000,
            "transcript": TestDataGenerator.generate_medical_query(),
            "confidence": random.uniform(0.85, 0.98),
        }

    def _simulate_tts_operation(self):
        """Simulate Text-to-Speech operation"""
        # Simulate TTS processing time (based on Azure TTS benchmarks)
        processing_time = random.uniform(0.1, 0.4)  # 100ms to 400ms
        time.sleep(processing_time)

        return {
            "success": True,
            "duration_ms": processing_time * 1000,
            "audio_bytes": random.randint(1024, 8192),
            "audio_duration_ms": random.randint(2000, 8000),
        }

    def on_stop(self):
        """Cleanup when user stops"""
        self.executor.shutdown(wait=False)

        # Cleanup Redis keys
        if self.redis_client:
            try:
                keys_to_delete = self.redis_client.keys(f"*{self.session_id}*")
                if keys_to_delete:
                    self.redis_client.delete(*keys_to_delete)
            except:
                pass


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Generate backend services performance report"""
    print("\n" + "=" * 50)
    print("BACKEND SERVICES LOAD TEST SUMMARY")
    print("=" * 50)

    stats = environment.stats

    # Service-specific metrics
    service_stats = {}
    for name, stat in stats.entries.items():
        service_type = stat.method
        if service_type not in service_stats:
            service_stats[service_type] = []
        service_stats[service_type].append((name, stat))

    for service_type, service_list in service_stats.items():
        print(f"\n{service_type} Services:")
        for name, stat in service_list:
            print(f"  {name}:")
            print(f"    Requests: {stat.num_requests}")
            print(f"    Failures: {stat.num_failures}")
            print(f"    Avg response time: {stat.avg_response_time:.2f}ms")
            print(
                f"    95th percentile: {stat.get_response_time_percentile(0.95):.2f}ms"
            )

            # Performance target validation
            if "redis" in name.lower() and stat.avg_response_time <= 50:
                print(f"    ✓ Redis latency target met")
            elif (
                "openai" in name.lower()
                and stat.avg_response_time <= config.llm_ttft_target_ms
            ):
                print(f"    ✓ OpenAI TTFT target met")
            elif (
                "speech" in name.lower()
                and stat.avg_response_time <= config.stt_final_segment_target_ms
            ):
                print(f"    ✓ Speech processing target met")


if __name__ == "__main__":
    # Run standalone test
    import random
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        __file__,
        "--host",
        config.api_base_url,
        "--users",
        "30",
        "--spawn-rate",
        "3",
        "--run-time",
        "2m",
        "--headless",
    ]

    subprocess.run(cmd)
