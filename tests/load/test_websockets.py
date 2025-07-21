"""
Load tests for WebSocket handlers
Tests real-time voice streaming, ACS call streaming, and relay WebSockets
"""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import websockets
from config import PerformanceTracker, TestDataGenerator, config
from locust import User, between, events, task


class WebSocketUser(User):
    """Custom WebSocket user for testing voice streaming"""

    wait_time = between(2, 5)

    def __init__(self, environment):
        super().__init__(environment)
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.performance_tracker = PerformanceTracker()
        self.session_id = None
        self.ws_connections = {}

    def on_start(self):
        """Initialize WebSocket connections"""
        self.session_id = f"session-{int(time.time())}-{id(self)}"

    @task(5)
    def test_realtime_websocket(self):
        """Test /ws/realtime WebSocket for browser voice streaming"""
        start_time = time.time()

        future = self.executor.submit(self._test_realtime_connection)
        try:
            result = future.result(timeout=30)
            duration_ms = (time.time() - start_time) * 1000

            if result["success"]:
                self.performance_tracker.record_metric(
                    "websocket_realtime",
                    duration_ms,
                    True,
                    messages_sent=result.get("messages_sent", 0),
                    messages_received=result.get("messages_received", 0),
                )

                events.request.fire(
                    request_type="WebSocket",
                    name="realtime_voice_streaming",
                    response_time=duration_ms,
                    response_length=result.get("total_bytes", 0),
                    exception=None,
                    context=self.context(),
                )
            else:
                events.request.fire(
                    request_type="WebSocket",
                    name="realtime_voice_streaming",
                    response_time=duration_ms,
                    response_length=0,
                    exception=Exception(result.get("error", "WebSocket failed")),
                    context=self.context(),
                )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="realtime_voice_streaming",
                response_time=duration_ms,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _test_realtime_connection(self):
        """Run real-time WebSocket test in thread"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._realtime_websocket_flow())
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            loop.close()

    async def _realtime_websocket_flow(self):
        """Simulate realistic voice conversation flow"""
        ws_url = f"{config.websocket_base_url}/ws/realtime"

        try:
            async with websockets.connect(ws_url) as websocket:
                # Connection established
                handshake_time = time.time()

                # Send initial connection message
                init_message = {
                    "type": "connection_init",
                    "session_id": self.session_id,
                    "audio_format": {
                        "encoding": "pcm",
                        "sample_rate": 16000,
                        "channels": 1,
                    },
                }
                await websocket.send(json.dumps(init_message))

                # Wait for connection ack
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                connection_response = json.loads(response)

                if connection_response.get("type") != "connection_ack":
                    return {"success": False, "error": "Connection not acknowledged"}

                messages_sent = 1
                messages_received = 1
                total_bytes = len(response)

                # Simulate conversation flow (3 voice exchanges)
                for conversation_round in range(3):
                    # 1. Send audio chunks (simulate 3 seconds of speech)
                    for chunk in range(30):  # 100ms chunks
                        audio_message = TestDataGenerator.generate_audio_chunk()
                        await websocket.send(json.dumps(audio_message))
                        messages_sent += 1

                        # Small delay between chunks
                        await asyncio.sleep(0.1)

                    # 2. Send end of speech
                    end_speech = {
                        "type": "end_speech",
                        "session_id": self.session_id,
                        "timestamp": time.time() * 1000,
                    }
                    await websocket.send(json.dumps(end_speech))
                    messages_sent += 1

                    # 3. Wait for STT result
                    stt_start = time.time()
                    stt_response = await asyncio.wait_for(
                        websocket.recv(), timeout=10.0
                    )
                    stt_duration = (time.time() - stt_start) * 1000

                    stt_data = json.loads(stt_response)
                    messages_received += 1
                    total_bytes += len(stt_response)

                    # Validate STT performance
                    if stt_duration > config.stt_final_segment_target_ms:
                        print(
                            f"STT latency exceeded target: {stt_duration}ms > {config.stt_final_segment_target_ms}ms"
                        )

                    # 4. Wait for agent response
                    agent_start = time.time()
                    agent_response = await asyncio.wait_for(
                        websocket.recv(), timeout=15.0
                    )
                    agent_duration = (time.time() - agent_start) * 1000

                    agent_data = json.loads(agent_response)
                    messages_received += 1
                    total_bytes += len(agent_response)

                    # Validate agent response performance
                    if agent_duration > config.end_to_end_voice_loop_target_ms:
                        print(
                            f"Agent response exceeded target: {agent_duration}ms > {config.end_to_end_voice_loop_target_ms}ms"
                        )

                    # Brief pause between conversation rounds
                    await asyncio.sleep(1)

                # Close connection gracefully
                close_message = {
                    "type": "connection_close",
                    "session_id": self.session_id,
                }
                await websocket.send(json.dumps(close_message))
                messages_sent += 1

                return {
                    "success": True,
                    "messages_sent": messages_sent,
                    "messages_received": messages_received,
                    "total_bytes": total_bytes,
                    "handshake_time": handshake_time,
                }

        except asyncio.TimeoutError:
            return {"success": False, "error": "WebSocket timeout"}
        except websockets.exceptions.ConnectionClosed:
            return {"success": False, "error": "Connection closed unexpectedly"}
        except Exception as e:
            return {"success": False, "error": f"WebSocket error: {str(e)}"}

    @task(3)
    def test_acs_call_stream(self):
        """Test /ws/call/stream WebSocket for ACS audio streaming"""
        start_time = time.time()

        future = self.executor.submit(self._test_acs_stream_connection)
        try:
            result = future.result(timeout=25)
            duration_ms = (time.time() - start_time) * 1000

            if result["success"]:
                events.request.fire(
                    request_type="WebSocket",
                    name="acs_call_streaming",
                    response_time=duration_ms,
                    response_length=result.get("total_bytes", 0),
                    exception=None,
                    context=self.context(),
                )
            else:
                events.request.fire(
                    request_type="WebSocket",
                    name="acs_call_streaming",
                    response_time=duration_ms,
                    response_length=0,
                    exception=Exception(result.get("error", "ACS stream failed")),
                    context=self.context(),
                )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="acs_call_streaming",
                response_time=duration_ms,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _test_acs_stream_connection(self):
        """Run ACS stream WebSocket test in thread"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._acs_stream_flow())
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            loop.close()

    async def _acs_stream_flow(self):
        """Simulate ACS bidirectional PCM audio stream"""
        call_id = f"call-{int(time.time())}-{id(self)}"
        ws_url = f"{config.websocket_base_url}/ws/call/stream?callId={call_id}"

        try:
            async with websockets.connect(ws_url) as websocket:
                # Send stream initialization
                init_message = {
                    "type": "stream_init",
                    "call_id": call_id,
                    "audio_format": "pcm_16khz_mono",
                    "direction": "bidirectional",
                }
                await websocket.send(json.dumps(init_message))

                # Wait for stream ready
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                stream_response = json.loads(response)

                if stream_response.get("type") != "stream_ready":
                    return {"success": False, "error": "Stream not ready"}

                messages_sent = 1
                messages_received = 1
                total_bytes = len(response)

                # Simulate bidirectional audio streaming
                for stream_cycle in range(5):  # 5 cycles of audio exchange
                    # Send incoming audio (from caller)
                    for chunk in range(20):  # 2 seconds of audio
                        audio_chunk = {
                            "type": "audio_data",
                            "direction": "incoming",
                            "data": f"pcm_data_chunk_{chunk}",
                            "timestamp": time.time() * 1000,
                            "sequence": chunk,
                        }
                        await websocket.send(json.dumps(audio_chunk))
                        messages_sent += 1
                        await asyncio.sleep(0.1)  # 100ms chunks

                    # Wait for processed audio response
                    try:
                        audio_response = await asyncio.wait_for(
                            websocket.recv(), timeout=8.0
                        )
                        response_data = json.loads(audio_response)
                        messages_received += 1
                        total_bytes += len(audio_response)

                        if (
                            response_data.get("type") == "audio_data"
                            and response_data.get("direction") == "outgoing"
                        ):
                            # Successful audio processing
                            pass
                        else:
                            print(
                                f"Unexpected audio response: {response_data.get('type')}"
                            )

                    except asyncio.TimeoutError:
                        print("Audio response timeout")
                        break

                    await asyncio.sleep(0.5)  # Brief pause between cycles

                return {
                    "success": True,
                    "messages_sent": messages_sent,
                    "messages_received": messages_received,
                    "total_bytes": total_bytes,
                }

        except Exception as e:
            return {"success": False, "error": f"ACS stream error: {str(e)}"}

    @task(1)
    def test_relay_websocket(self):
        """Test /ws/relay WebSocket for event relay"""
        start_time = time.time()

        future = self.executor.submit(self._test_relay_connection)
        try:
            result = future.result(timeout=15)
            duration_ms = (time.time() - start_time) * 1000

            if result["success"]:
                events.request.fire(
                    request_type="WebSocket",
                    name="event_relay",
                    response_time=duration_ms,
                    response_length=result.get("total_bytes", 0),
                    exception=None,
                    context=self.context(),
                )
            else:
                events.request.fire(
                    request_type="WebSocket",
                    name="event_relay",
                    response_time=duration_ms,
                    response_length=0,
                    exception=Exception(result.get("error", "Relay failed")),
                    context=self.context(),
                )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket",
                name="event_relay",
                response_time=duration_ms,
                response_length=0,
                exception=e,
                context=self.context(),
            )

    def _test_relay_connection(self):
        """Run relay WebSocket test in thread"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._relay_flow())
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            loop.close()

    async def _relay_flow(self):
        """Simulate event relay subscription and broadcasting"""
        ws_url = f"{config.websocket_base_url}/ws/relay"

        try:
            async with websockets.connect(ws_url) as websocket:
                # Subscribe to events
                subscribe_message = {
                    "type": "subscribe",
                    "topics": ["call_events", "agent_status", "system_metrics"],
                    "client_id": f"test-client-{id(self)}",
                }
                await websocket.send(json.dumps(subscribe_message))

                # Wait for subscription confirmation
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                sub_response = json.loads(response)

                if sub_response.get("type") != "subscription_confirmed":
                    return {"success": False, "error": "Subscription not confirmed"}

                messages_sent = 1
                messages_received = 1
                total_bytes = len(response)

                # Listen for events and send some test events
                for i in range(10):
                    # Send a test event
                    test_event = {
                        "type": "event",
                        "topic": "call_events",
                        "data": {
                            "event_type": "call_progress",
                            "call_id": f"test-call-{i}",
                            "status": "processing",
                        },
                        "timestamp": time.time() * 1000,
                    }
                    await websocket.send(json.dumps(test_event))
                    messages_sent += 1

                    # Listen for potential broadcast events
                    try:
                        event_response = await asyncio.wait_for(
                            websocket.recv(), timeout=2.0
                        )
                        event_data = json.loads(event_response)
                        messages_received += 1
                        total_bytes += len(event_response)
                    except asyncio.TimeoutError:
                        pass  # No events to receive, continue

                    await asyncio.sleep(0.5)

                return {
                    "success": True,
                    "messages_sent": messages_sent,
                    "messages_received": messages_received,
                    "total_bytes": total_bytes,
                }

        except Exception as e:
            return {"success": False, "error": f"Relay error: {str(e)}"}

    def on_stop(self):
        """Cleanup when user stops"""
        self.executor.shutdown(wait=False)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Generate WebSocket performance report"""
    print("\n" + "=" * 50)
    print("WEBSOCKET LOAD TEST SUMMARY")
    print("=" * 50)

    stats = environment.stats

    # WebSocket specific metrics
    ws_stats = {
        name: stat for name, stat in stats.entries.items() if stat.method == "WebSocket"
    }

    for name, stat in ws_stats.items():
        print(f"\n{name}:")
        print(f"  Requests: {stat.num_requests}")
        print(f"  Failures: {stat.num_failures}")
        print(f"  Avg response time: {stat.avg_response_time:.2f}ms")
        print(f"  95th percentile: {stat.get_response_time_percentile(0.95):.2f}ms")
        print(f"  99th percentile: {stat.get_response_time_percentile(0.99):.2f}ms")

        # Performance target validation
        if (
            "realtime" in name
            and stat.avg_response_time <= config.end_to_end_voice_loop_target_ms
        ):
            print(f"  ✓ Voice loop latency target met")
        elif "realtime" in name:
            print(f"  ✗ Voice loop latency target missed")


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
        config.websocket_base_url,
        "--users",
        "25",
        "--spawn-rate",
        "2",
        "--run-time",
        "3m",
        "--headless",
    ]

    subprocess.run(cmd)
