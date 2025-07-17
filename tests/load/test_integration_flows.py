"""
End-to-end integration load tests
Tests complete call flows and realistic user scenarios
"""
import asyncio
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from config import PerformanceTracker, TestDataGenerator, config
from locust import HttpUser, between, events, task


class IntegratedCallFlowUser(HttpUser):
    """User simulating complete medical agent call flows"""

    wait_time = between(3, 8)  # Longer wait times for realistic call patterns

    def __init__(self, environment):
        super().__init__(environment)
        self.performance_tracker = PerformanceTracker()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.active_sessions = {}
        self.call_scenarios = [
            "emergency_chest_pain",
            "routine_checkup_questions",
            "medication_side_effects",
            "follow_up_appointment",
            "mental_health_consultation",
        ]

    def on_start(self):
        """Initialize user with realistic patient profile"""
        self.patient_profile = {
            "patient_id": f"patient-{random.randint(100000, 999999)}",
            "age": random.randint(18, 85),
            "medical_history": random.choice(
                ["diabetes", "hypertension", "asthma", "healthy", "heart_disease"]
            ),
            "preferred_language": random.choice(["en-US", "es-US"]),
            "insurance_verified": random.choice([True, False]),
            "priority_level": random.choice(["normal", "urgent", "emergency"]),
        }

    @task(10)
    def complete_medical_consultation_flow(self):
        """Simulate a complete medical consultation from start to finish"""
        scenario = random.choice(self.call_scenarios)
        start_time = time.time()

        try:
            # Phase 1: Call Initiation
            session_result = self._initiate_call(scenario)
            if not session_result["success"]:
                return

            session_id = session_result["session_id"]
            self.active_sessions[session_id] = {
                "start_time": start_time,
                "scenario": scenario,
                "phase": "initiated",
            }

            # Phase 2: Voice Interaction Simulation
            voice_result = self._simulate_voice_interaction(session_id, scenario)
            if voice_result["success"]:
                self.active_sessions[session_id]["phase"] = "voice_completed"

            # Phase 3: Call Completion
            completion_result = self._complete_call(session_id)

            # Calculate total call duration
            total_duration = (time.time() - start_time) * 1000

            # Validate end-to-end performance
            e2e_target_met = total_duration <= (
                config.end_to_end_voice_loop_target_ms * 10
            )  # Allow for multiple interactions

            success = (
                session_result["success"]
                and voice_result["success"]
                and completion_result["success"]
            )

            self.performance_tracker.record_metric(
                "e2e_call_flow",
                total_duration,
                success,
                scenario=scenario,
                voice_interactions=voice_result.get("interactions", 0),
                target_met=e2e_target_met,
            )

            events.request.fire(
                request_type="Integration",
                name=f"complete_call_flow_{scenario}",
                response_time=total_duration,
                response_length=voice_result.get("total_bytes", 0),
                exception=None if success else Exception("Call flow failed"),
                context=self.context(),
            )

            # Cleanup
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="Integration",
                name=f"complete_call_flow_{scenario}",
                response_time=duration,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _initiate_call(self, scenario):
        """Phase 1: Initiate call with appropriate urgency and context"""
        start_time = time.time()

        # Customize call data based on scenario
        call_data = TestDataGenerator.generate_call_data()
        call_data.update(
            {
                "patient_id": self.patient_profile["patient_id"],
                "scenario": scenario,
                "patient_context": {
                    "age": self.patient_profile["age"],
                    "medical_history": self.patient_profile["medical_history"],
                    "insurance_verified": self.patient_profile["insurance_verified"],
                },
            }
        )

        # Set priority based on scenario
        if scenario == "emergency_chest_pain":
            call_data["priority"] = "emergency"
        elif scenario in ["medication_side_effects", "mental_health_consultation"]:
            call_data["priority"] = "urgent"
        else:
            call_data["priority"] = "normal"

        try:
            with self.client.post(
                "/api/call", json=call_data, timeout=10, catch_response=True
            ) as response:
                duration = (time.time() - start_time) * 1000

                if response.status_code in [200, 201]:
                    response_data = response.json()
                    return {
                        "success": True,
                        "session_id": response_data.get("session_id"),
                        "call_id": response_data.get("call_id"),
                        "duration_ms": duration,
                    }
                else:
                    response.failure(f"Call initiation failed: {response.status_code}")
                    return {"success": False, "duration_ms": duration}

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "duration_ms": (time.time() - start_time) * 1000,
            }

    def _simulate_voice_interaction(self, session_id, scenario):
        """Phase 2: Simulate realistic voice conversation based on scenario"""

        # Define conversation patterns by scenario
        conversation_patterns = {
            "emergency_chest_pain": {
                "interactions": 8,
                "urgency": "high",
                "questions": [
                    "I'm having severe chest pain",
                    "It started about 30 minutes ago",
                    "The pain is radiating to my left arm",
                    "I'm feeling short of breath",
                    "Should I call 911?",
                    "My chest feels tight",
                    "The pain is getting worse",
                    "Please help me",
                ],
            },
            "routine_checkup_questions": {
                "interactions": 5,
                "urgency": "low",
                "questions": [
                    "I need to schedule my annual checkup",
                    "What vaccinations do I need?",
                    "Can you check my lab results?",
                    "When should I come in next?",
                    "Do I need any screening tests?",
                ],
            },
            "medication_side_effects": {
                "interactions": 6,
                "urgency": "medium",
                "questions": [
                    "I'm having side effects from my new medication",
                    "I feel dizzy and nauseous",
                    "Should I stop taking it?",
                    "Can you prescribe something else?",
                    "How long do side effects usually last?",
                    "Is this dangerous?",
                ],
            },
            "follow_up_appointment": {
                "interactions": 4,
                "urgency": "low",
                "questions": [
                    "I need to follow up on my recent visit",
                    "My symptoms have improved",
                    "Do I still need to take the medication?",
                    "When should I schedule the next appointment?",
                ],
            },
            "mental_health_consultation": {
                "interactions": 7,
                "urgency": "medium",
                "questions": [
                    "I've been feeling very anxious lately",
                    "I'm having trouble sleeping",
                    "My mood has been really low",
                    "Can you recommend a therapist?",
                    "Do I need medication for anxiety?",
                    "How can I manage stress better?",
                    "I need someone to talk to",
                ],
            },
        }

        pattern = conversation_patterns.get(
            scenario, conversation_patterns["routine_checkup_questions"]
        )

        try:
            # Run voice interaction in separate thread to avoid blocking
            future = self.executor.submit(
                self._voice_interaction_worker, session_id, pattern
            )
            result = future.result(
                timeout=45
            )  # Allow up to 45 seconds for conversation
            return result

        except Exception as e:
            return {"success": False, "error": str(e), "interactions": 0}

    def _voice_interaction_worker(self, session_id, pattern):
        """Worker thread for voice interaction simulation"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                self._async_voice_interaction(session_id, pattern)
            )
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            loop.close()

    async def _async_voice_interaction(self, session_id, pattern):
        """Async voice interaction simulation"""
        import websockets

        ws_url = f"{config.websocket_base_url}/ws/realtime"
        interactions_completed = 0
        total_bytes = 0

        try:
            async with websockets.connect(ws_url) as websocket:
                # Initialize connection
                init_message = {
                    "type": "connection_init",
                    "session_id": session_id,
                    "audio_format": {
                        "encoding": "pcm",
                        "sample_rate": 16000,
                        "channels": 1,
                    },
                }
                await websocket.send(json.dumps(init_message))

                # Wait for connection ack
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                total_bytes += len(response)

                # Simulate conversation based on pattern
                for i, question in enumerate(pattern["questions"]):
                    if i >= pattern["interactions"]:
                        break

                    # Simulate user speaking (send audio chunks)
                    speech_duration = len(question.split()) * 0.5  # ~0.5s per word
                    chunks_to_send = max(int(speech_duration * 10), 5)  # 100ms chunks

                    for chunk in range(chunks_to_send):
                        audio_chunk = TestDataGenerator.generate_audio_chunk()
                        audio_chunk["data"] = f"audio_for: {question[:20]}..."
                        await websocket.send(json.dumps(audio_chunk))
                        await asyncio.sleep(0.1)  # 100ms between chunks

                    # Send end of speech
                    end_speech = {
                        "type": "end_speech",
                        "session_id": session_id,
                        "final_transcript": question,
                        "timestamp": time.time() * 1000,
                    }
                    await websocket.send(json.dumps(end_speech))

                    # Wait for agent response with timeout based on urgency
                    timeout = 15 if pattern["urgency"] == "high" else 10
                    try:
                        agent_response = await asyncio.wait_for(
                            websocket.recv(), timeout=timeout
                        )
                        total_bytes += len(agent_response)
                        interactions_completed += 1

                        # Brief pause before next interaction (unless emergency)
                        if pattern["urgency"] != "high":
                            await asyncio.sleep(random.uniform(1, 3))
                        else:
                            await asyncio.sleep(0.5)  # Faster for emergencies

                    except asyncio.TimeoutError:
                        print(
                            f"Timeout waiting for agent response to: {question[:30]}..."
                        )
                        break

                return {
                    "success": True,
                    "interactions": interactions_completed,
                    "total_bytes": total_bytes,
                    "pattern_urgency": pattern["urgency"],
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "interactions": interactions_completed,
                "total_bytes": total_bytes,
            }

    def _complete_call(self, session_id):
        """Phase 3: Complete call and cleanup"""
        start_time = time.time()

        try:
            # Get final call metrics
            with self.client.get(
                f"/api/call/{session_id}/metrics", timeout=5, catch_response=True
            ) as response:
                metrics_success = response.status_code == 200

            # Mark call as completed
            completion_data = {
                "session_id": session_id,
                "completion_reason": "normal",
                "patient_satisfied": random.choice(
                    [True, True, True, False]
                ),  # 75% satisfaction
                "follow_up_needed": random.choice([True, False]),
                "completed_at": time.time(),
            }

            with self.client.post(
                f"/api/call/{session_id}/complete",
                json=completion_data,
                timeout=10,
                catch_response=True,
            ) as response:
                completion_success = response.status_code in [200, 201, 204]
                if not completion_success:
                    response.failure(f"Call completion failed: {response.status_code}")

            duration = (time.time() - start_time) * 1000

            return {
                "success": metrics_success and completion_success,
                "duration_ms": duration,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "duration_ms": (time.time() - start_time) * 1000,
            }

    @task(2)
    def test_concurrent_calls_capacity(self):
        """Test system capacity with multiple concurrent calls"""
        concurrent_sessions = []
        start_time = time.time()

        try:
            # Start 3 concurrent call sessions
            for i in range(3):
                call_data = TestDataGenerator.generate_call_data()
                call_data[
                    "patient_id"
                ] = f"{self.patient_profile['patient_id']}-concurrent-{i}"

                with self.client.post(
                    "/api/call", json=call_data, catch_response=True
                ) as response:
                    if response.status_code in [200, 201]:
                        session_data = response.json()
                        concurrent_sessions.append(session_data.get("session_id"))

            # Brief interactions on each session
            for session_id in concurrent_sessions:
                if session_id:
                    with self.client.get(
                        f"/api/call/{session_id}/status", catch_response=True
                    ) as response:
                        pass  # Just check session status

            total_duration = (time.time() - start_time) * 1000

            events.request.fire(
                request_type="Integration",
                name="concurrent_calls_capacity",
                response_time=total_duration,
                response_length=len(concurrent_sessions) * 100,  # Estimated
                exception=None,
                context=self.context(),
            )

            # Cleanup concurrent sessions
            for session_id in concurrent_sessions:
                if session_id:
                    try:
                        self.client.delete(f"/api/call/{session_id}")
                    except:
                        pass  # Best effort cleanup

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="Integration",
                name="concurrent_calls_capacity",
                response_time=duration,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def on_stop(self):
        """Cleanup when user stops"""
        self.executor.shutdown(wait=False)

        # Cleanup any remaining active sessions
        for session_id in list(self.active_sessions.keys()):
            try:
                self.client.delete(f"/api/call/{session_id}")
            except:
                pass  # Best effort cleanup


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Generate integration test performance report"""
    print("\n" + "=" * 50)
    print("INTEGRATION LOAD TEST SUMMARY")
    print("=" * 50)

    stats = environment.stats

    # Integration-specific metrics
    integration_stats = {
        name: stat
        for name, stat in stats.entries.items()
        if stat.method == "Integration"
    }

    if integration_stats:
        print("\nEnd-to-End Call Flow Performance:")
        for name, stat in integration_stats.items():
            scenario = name.split("_")[-1] if "_" in name else "unknown"
            print(f"  {scenario.replace('_', ' ').title()}:")
            print(f"    Completed flows: {stat.num_requests}")
            print(f"    Failed flows: {stat.num_failures}")
            print(f"    Avg duration: {stat.avg_response_time/1000:.1f}s")
            print(
                f"    95th percentile: {stat.get_response_time_percentile(0.95)/1000:.1f}s"
            )

            # Success rate calculation
            success_rate = (
                ((stat.num_requests - stat.num_failures) / stat.num_requests * 100)
                if stat.num_requests > 0
                else 0
            )
            print(f"    Success rate: {success_rate:.1f}%")

            if success_rate >= 95:
                print(f"    ✓ Success rate target met")
            else:
                print(f"    ✗ Success rate below target (95%)")

    # Overall system health
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    overall_success_rate = (
        ((total_requests - total_failures) / total_requests * 100)
        if total_requests > 0
        else 0
    )

    print(f"\nOverall System Performance:")
    print(f"  Total requests: {total_requests}")
    print(f"  Total failures: {total_failures}")
    print(f"  Overall success rate: {overall_success_rate:.1f}%")
    print(f"  Average response time: {stats.total.avg_response_time:.2f}ms")
    print(f"  Requests per second: {stats.total.current_rps:.2f}")


if __name__ == "__main__":
    # Run standalone test
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
        "20",
        "--spawn-rate",
        "2",
        "--run-time",
        "5m",
        "--headless",
    ]

    subprocess.run(cmd)
