"""
Load tests for REST API endpoints
Tests health checks, call management, and ACS callback endpoints
"""
import json
import random
import time

from config import PerformanceTracker, TestDataGenerator, config
from locust import HttpUser, between, events, task
from locust.contrib.fasthttp import FastHttpUser


class APIEndpointsUser(FastHttpUser):
    """Load test user for REST API endpoints"""

    wait_time = between(1, 3)

    def on_start(self):
        """Initialize user session"""
        self.session_id = None
        self.call_id = None
        self.performance_tracker = PerformanceTracker()

    @task(10)
    def health_check(self):
        """Test health endpoint - high frequency for monitoring"""
        start_time = time.time()

        with self.client.get("/health", catch_response=True) as response:
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                self.performance_tracker.record_metric(
                    "health_check", duration_ms, True, status_code=response.status_code
                )
            else:
                response.failure(f"Health check failed: {response.status_code}")
                self.performance_tracker.record_metric(
                    "health_check", duration_ms, False, status_code=response.status_code
                )

    @task(5)
    def start_call(self):
        """Test call initiation endpoint"""
        start_time = time.time()
        call_data = TestDataGenerator.generate_call_data()

        with self.client.post(
            "/api/call",
            json=call_data,
            headers={"Content-Type": "application/json"},
            catch_response=True,
        ) as response:
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code == 200 or response.status_code == 201:
                try:
                    response_data = response.json()
                    self.session_id = response_data.get("session_id")
                    self.call_id = response_data.get("call_id")

                    self.performance_tracker.record_metric(
                        "call_start", duration_ms, True, session_id=self.session_id
                    )
                except (ValueError, KeyError) as e:
                    response.failure(f"Invalid response format: {e}")
                    self.performance_tracker.record_metric(
                        "call_start", duration_ms, False, error=str(e)
                    )
            else:
                response.failure(f"Call start failed: {response.status_code}")
                self.performance_tracker.record_metric(
                    "call_start", duration_ms, False, status_code=response.status_code
                )

    @task(3)
    def inbound_call(self):
        """Test inbound call handling endpoint"""
        start_time = time.time()
        inbound_data = {
            "from": TestDataGenerator.generate_phone_number(),
            "to": "+15551234567",  # System number
            "call_id": f"inbound-{int(time.time())}-{random.randint(1000, 9999)}",
            "direction": "inbound",
            "caller_info": {
                "patient_id": f"patient-{random.randint(10000, 99999)}",
                "priority": random.choice(["normal", "urgent", "emergency"]),
            },
        }

        with self.client.post(
            "/api/call/inbound",
            json=inbound_data,
            headers={"Content-Type": "application/json"},
            catch_response=True,
        ) as response:
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code in [200, 201, 202]:
                self.performance_tracker.record_metric(
                    "inbound_call", duration_ms, True, call_id=inbound_data["call_id"]
                )
            else:
                response.failure(f"Inbound call failed: {response.status_code}")
                self.performance_tracker.record_metric(
                    "inbound_call", duration_ms, False, status_code=response.status_code
                )

    @task(2)
    def acs_callback(self):
        """Test ACS callback webhook endpoint"""
        start_time = time.time()

        # Generate realistic ACS callback data
        callback_data = {
            "eventType": random.choice(
                [
                    "Microsoft.Communication.CallConnected",
                    "Microsoft.Communication.CallDisconnected",
                    "Microsoft.Communication.RecognizeCompleted",
                    "Microsoft.Communication.PlayCompleted",
                ]
            ),
            "subject": f"calling/callConnections/{self.call_id or 'test-call-123'}",
            "data": {
                "callConnectionId": self.call_id
                or f"call-{random.randint(1000, 9999)}",
                "serverCallId": f"server-{random.randint(10000, 99999)}",
                "correlationId": f"corr-{random.randint(1000000, 9999999)}",
                "operationContext": "medical-agent-operation",
            },
            "eventTime": time.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "dataVersion": "1.0",
        }

        with self.client.post(
            "/call/callbacks",
            json=callback_data,
            headers={
                "Content-Type": "application/json",
                "ce-specversion": "1.0",
                "ce-type": "Microsoft.Communication.CallConnected",
                "ce-source": "calling",
                "ce-id": f"event-{random.randint(100000, 999999)}",
            },
            catch_response=True,
        ) as response:
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code in [200, 202, 204]:
                self.performance_tracker.record_metric(
                    "acs_callback",
                    duration_ms,
                    True,
                    event_type=callback_data["eventType"],
                )
            else:
                response.failure(f"ACS callback failed: {response.status_code}")
                self.performance_tracker.record_metric(
                    "acs_callback", duration_ms, False, status_code=response.status_code
                )

    @task(1)
    def get_call_metrics(self):
        """Test call metrics retrieval"""
        if not self.session_id:
            return

        start_time = time.time()

        with self.client.get(
            f"/api/call/{self.session_id}/metrics", catch_response=True
        ) as response:
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code == 200:
                self.performance_tracker.record_metric(
                    "get_metrics", duration_ms, True, session_id=self.session_id
                )
            elif response.status_code == 404:
                # Session might not exist yet, not necessarily an error
                pass
            else:
                response.failure(f"Get metrics failed: {response.status_code}")
                self.performance_tracker.record_metric(
                    "get_metrics", duration_ms, False, status_code=response.status_code
                )

    def on_stop(self):
        """Cleanup when user stops"""
        if self.session_id:
            # Attempt to clean up session
            try:
                self.client.delete(f"/api/call/{self.session_id}")
            except:
                pass  # Best effort cleanup


# Event listeners for custom metrics
@events.request.add_listener
def on_request(
    request_type, name, response_time, response_length, exception, context, **kwargs
):
    """Custom request event handler"""
    if exception:
        print(f"Request failed: {name} - {exception}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Generate performance report when test stops"""
    print("\n" + "=" * 50)
    print("API ENDPOINTS LOAD TEST SUMMARY")
    print("=" * 50)

    stats = environment.stats

    print(f"Total requests: {stats.total.num_requests}")
    print(f"Total failures: {stats.total.num_failures}")
    print(f"Average response time: {stats.total.avg_response_time:.2f}ms")
    print(f"95th percentile: {stats.total.get_response_time_percentile(0.95):.2f}ms")
    print(f"99th percentile: {stats.total.get_response_time_percentile(0.99):.2f}ms")
    print(f"Requests per second: {stats.total.current_rps:.2f}")

    # Performance target validation
    targets_met = []
    if stats.total.avg_response_time <= config.websocket_handshake_target_ms:
        targets_met.append("✓ Average response time target met")
    else:
        targets_met.append("✗ Average response time target missed")

    print("\nPerformance Targets:")
    for target in targets_met:
        print(f"  {target}")


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
        "50",
        "--spawn-rate",
        "5",
        "--run-time",
        "2m",
        "--headless",
    ]

    subprocess.run(cmd)
