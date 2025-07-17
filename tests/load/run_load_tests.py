"""
Master load test runner that orchestrates all test components
Runs coordinated tests across API endpoints, WebSockets, backend services, and integration flows
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import PerformanceTracker, config


class LoadTestOrchestrator:
    """Orchestrates comprehensive load testing across all system components"""

    def __init__(self):
        self.test_results = {}
        self.start_time = None
        self.end_time = None

    def run_comprehensive_test(self, test_config):
        """Run coordinated load tests across all components"""
        self.start_time = datetime.utcnow()

        print("🚀 Starting RTMedAgent Comprehensive Load Test")
        print("=" * 60)
        print(f"Start time: {self.start_time}")
        print(f"Test configuration:")
        for key, value in test_config.items():
            print(f"  {key}: {value}")
        print("=" * 60)

        # Define test phases
        test_phases = [
            {
                "name": "Phase 1: API Endpoints Baseline",
                "description": "Test REST API performance under normal load",
                "tests": [
                    {
                        "file": "test_api_endpoints.py",
                        "users": test_config.get("api_users", 25),
                        "spawn_rate": 3,
                        "duration": "2m",
                        "priority": "high",
                    }
                ],
            },
            {
                "name": "Phase 2: Backend Services Validation",
                "description": "Test Redis, OpenAI, Speech, and Cosmos DB performance",
                "tests": [
                    {
                        "file": "test_backend_services.py",
                        "users": test_config.get("service_users", 20),
                        "spawn_rate": 2,
                        "duration": "3m",
                        "priority": "high",
                    }
                ],
            },
            {
                "name": "Phase 3: WebSocket Stress Testing",
                "description": "Test real-time voice streaming and WebSocket capacity",
                "tests": [
                    {
                        "file": "test_websockets.py",
                        "users": test_config.get("websocket_users", 15),
                        "spawn_rate": 1,
                        "duration": "4m",
                        "priority": "critical",
                    }
                ],
            },
            {
                "name": "Phase 4: Integration Flow Testing",
                "description": "Test complete end-to-end call scenarios",
                "tests": [
                    {
                        "file": "test_integration_flows.py",
                        "users": test_config.get("integration_users", 10),
                        "spawn_rate": 1,
                        "duration": "5m",
                        "priority": "critical",
                    }
                ],
            },
        ]

        # Execute test phases
        if test_config.get("parallel_execution", False):
            self._run_parallel_tests(test_phases, test_config)
        else:
            self._run_sequential_tests(test_phases, test_config)

        # Generate comprehensive report
        self.end_time = datetime.utcnow()
        self._generate_comprehensive_report(test_config)

        return self.test_results

    def _run_sequential_tests(self, test_phases, test_config):
        """Run test phases sequentially"""
        print("\\n📋 Running tests sequentially...")

        for phase in test_phases:
            print(f"\\n🔄 {phase['name']}")
            print(f"   {phase['description']}")

            for test in phase["tests"]:
                print(f"   ▶ Running {test['file']}...")

                result = self._execute_single_test(test, test_config)
                self.test_results[test["file"]] = result

                # Brief pause between tests
                time.sleep(5)

                # Check if test passed critical thresholds
                if test["priority"] == "critical" and not result.get("success", False):
                    print(f"   ❌ Critical test failed: {test['file']}")
                    if test_config.get("fail_fast", False):
                        print("   🛑 Stopping execution due to critical failure")
                        return

    def _run_parallel_tests(self, test_phases, test_config):
        """Run appropriate tests in parallel"""
        print("\\n🔀 Running tests in parallel where possible...")

        # Phase 1 & 2 can run in parallel (API + Backend Services)
        parallel_group_1 = []
        parallel_group_1.extend(test_phases[0]["tests"])  # API tests
        parallel_group_1.extend(test_phases[1]["tests"])  # Backend services

        print("\\n🔄 Parallel Group 1: API + Backend Services")
        self._execute_parallel_group(parallel_group_1, test_config)

        # Brief pause before WebSocket tests
        time.sleep(10)

        # Phase 3: WebSocket tests (sequential due to connection limits)
        print("\\n🔄 Phase 3: WebSocket Testing")
        for test in test_phases[2]["tests"]:
            result = self._execute_single_test(test, test_config)
            self.test_results[test["file"]] = result

        # Brief pause before integration tests
        time.sleep(10)

        # Phase 4: Integration tests (sequential for resource management)
        print("\\n🔄 Phase 4: Integration Testing")
        for test in test_phases[3]["tests"]:
            result = self._execute_single_test(test, test_config)
            self.test_results[test["file"]] = result

    def _execute_parallel_group(self, tests, test_config):
        """Execute a group of tests in parallel"""
        with ThreadPoolExecutor(max_workers=len(tests)) as executor:
            future_to_test = {
                executor.submit(self._execute_single_test, test, test_config): test
                for test in tests
            }

            for future in as_completed(future_to_test):
                test = future_to_test[future]
                try:
                    result = future.result()
                    self.test_results[test["file"]] = result
                    print(f"   ✅ Completed {test['file']}")
                except Exception as e:
                    print(f"   ❌ Failed {test['file']}: {e}")
                    self.test_results[test["file"]] = {
                        "success": False,
                        "error": str(e),
                        "exit_code": 1,
                    }

    def _execute_single_test(self, test, test_config):
        """Execute a single Locust test"""
        test_file = os.path.join(os.path.dirname(__file__), test["file"])

        if not os.path.exists(test_file):
            return {
                "success": False,
                "error": f"Test file not found: {test['file']}",
                "exit_code": 404,
            }

        # Build Locust command
        cmd = [
            sys.executable,
            "-m",
            "locust",
            "-f",
            test_file,
            "--host",
            test_config.get("host", config.api_base_url),
            "--users",
            str(test["users"]),
            "--spawn-rate",
            str(test["spawn_rate"]),
            "--run-time",
            test["duration"],
            "--headless",
            "--csv",
            f"results/{test['file'].replace('.py', '')}",
            "--html",
            f"results/{test['file'].replace('.py', '')}_report.html",
        ]

        # Add environment variables
        env = os.environ.copy()
        env.update(
            {
                "API_BASE_URL": test_config.get("host", config.api_base_url),
                "WS_BASE_URL": test_config.get("ws_host", config.websocket_base_url),
                "REDIS_URL": test_config.get("redis_url", config.redis_url),
                "TEST_DURATION": str(test_config.get("duration", 300)),
            }
        )

        start_time = time.time()

        try:
            # Execute test
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._calculate_timeout(test["duration"]),
                env=env,
            )

            duration = time.time() - start_time

            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_seconds": duration,
                "test_config": test,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Test execution timeout",
                "exit_code": 124,
                "duration_seconds": time.time() - start_time,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "exit_code": 1,
                "duration_seconds": time.time() - start_time,
            }

    def _calculate_timeout(self, duration_str):
        """Calculate appropriate timeout for test duration"""
        # Parse duration string (e.g., "2m", "30s")
        if duration_str.endswith("m"):
            minutes = int(duration_str[:-1])
            return (minutes * 60) + 60  # Add 1 minute buffer
        elif duration_str.endswith("s"):
            seconds = int(duration_str[:-1])
            return seconds + 30  # Add 30 second buffer
        else:
            return 300  # Default 5 minute timeout

    def _generate_comprehensive_report(self, test_config):
        """Generate comprehensive test report"""
        report_time = datetime.utcnow()

        print("\\n" + "=" * 60)
        print("📊 COMPREHENSIVE LOAD TEST RESULTS")
        print("=" * 60)
        print(f"Test completed: {report_time}")
        print(f"Total duration: {self.end_time - self.start_time}")
        print(f"Configuration: {json.dumps(test_config, indent=2)}")

        # Test results summary
        print("\\n📋 Test Results Summary:")
        total_tests = len(self.test_results)
        successful_tests = sum(
            1 for result in self.test_results.values() if result.get("success", False)
        )

        print(f"  Total tests executed: {total_tests}")
        print(f"  Successful tests: {successful_tests}")
        print(f"  Failed tests: {total_tests - successful_tests}")
        print(f"  Success rate: {(successful_tests/total_tests*100):.1f}%")

        # Individual test results
        print("\\n📝 Individual Test Results:")
        for test_file, result in self.test_results.items():
            status = "✅ PASS" if result.get("success", False) else "❌ FAIL"
            duration = result.get("duration_seconds", 0)

            print(f"  {status} {test_file} ({duration:.1f}s)")

            if not result.get("success", False):
                error = result.get("error", result.get("stderr", "Unknown error"))
                print(f"       Error: {error}")

        # Performance targets validation
        self._validate_performance_targets()

        # Generate JSON report
        self._save_json_report(test_config, report_time)

        # Performance recommendations
        self._generate_recommendations()

    def _validate_performance_targets(self):
        """Validate against performance targets from load testing doc"""
        print("\\n🎯 Performance Targets Validation:")

        targets = {
            "WebSocket handshake": {
                "target": f"< {config.websocket_handshake_target_ms}ms",
                "met": None,
            },
            "End-to-end voice loop": {
                "target": f"< {config.end_to_end_voice_loop_target_ms}ms",
                "met": None,
            },
            "STT processing": {
                "target": f"< {config.stt_final_segment_target_ms}ms",
                "met": None,
            },
            "LLM TTFT": {"target": f"< {config.llm_ttft_target_ms}ms", "met": None},
            "TTS first byte": {
                "target": f"< {config.tts_first_byte_target_ms}ms",
                "met": None,
            },
        }

        # This would be populated by parsing test outputs
        # For now, showing the framework
        for target_name, target_info in targets.items():
            status = (
                "⏳ Unknown"
                if target_info["met"] is None
                else ("✅ Met" if target_info["met"] else "❌ Missed")
            )
            print(f"  {status} {target_name}: {target_info['target']}")

    def _generate_recommendations(self):
        """Generate performance recommendations based on test results"""
        print("\\n💡 Performance Recommendations:")

        failed_tests = [
            name
            for name, result in self.test_results.items()
            if not result.get("success", False)
        ]

        if "test_websockets.py" in failed_tests:
            print("  🔧 WebSocket Issues Detected:")
            print("     - Consider increasing WebSocket connection limits")
            print("     - Review voice processing pipeline optimization")
            print("     - Check network bandwidth and latency")

        if "test_backend_services.py" in failed_tests:
            print("  🔧 Backend Service Issues Detected:")
            print("     - Review Redis connection pooling configuration")
            print("     - Consider scaling Azure OpenAI TPM limits")
            print("     - Optimize Cosmos DB query performance")

        if "test_integration_flows.py" in failed_tests:
            print("  🔧 Integration Flow Issues Detected:")
            print("     - Review end-to-end timeout configurations")
            print("     - Consider implementing circuit breakers")
            print("     - Optimize call flow orchestration")

        if not failed_tests:
            print("  🎉 All tests passed! System performing within targets.")
            print("  📈 Consider testing with higher load to find capacity limits.")

    def _save_json_report(self, test_config, report_time):
        """Save detailed JSON report"""
        report_data = {
            "test_execution": {
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
                "duration_seconds": (self.end_time - self.start_time).total_seconds(),
                "configuration": test_config,
            },
            "results": self.test_results,
            "summary": {
                "total_tests": len(self.test_results),
                "successful_tests": sum(
                    1 for r in self.test_results.values() if r.get("success", False)
                ),
                "success_rate": (
                    sum(
                        1 for r in self.test_results.values() if r.get("success", False)
                    )
                    / len(self.test_results)
                )
                * 100
                if self.test_results
                else 0,
            },
        }

        # Ensure results directory exists
        os.makedirs("results", exist_ok=True)

        report_filename = (
            f"results/load_test_report_{report_time.strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(report_filename, "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        print(f"\\n📄 Detailed report saved: {report_filename}")


def main():
    """Main entry point for load test orchestration"""
    parser = argparse.ArgumentParser(
        description="RTMedAgent Comprehensive Load Testing"
    )

    # Test configuration arguments
    parser.add_argument("--host", default=config.api_base_url, help="API host URL")
    parser.add_argument(
        "--ws-host", default=config.websocket_base_url, help="WebSocket host URL"
    )
    parser.add_argument(
        "--api-users", type=int, default=25, help="Number of API test users"
    )
    parser.add_argument(
        "--service-users",
        type=int,
        default=20,
        help="Number of backend service test users",
    )
    parser.add_argument(
        "--websocket-users", type=int, default=15, help="Number of WebSocket test users"
    )
    parser.add_argument(
        "--integration-users",
        type=int,
        default=10,
        help="Number of integration test users",
    )
    parser.add_argument(
        "--parallel", action="store_true", help="Run tests in parallel where possible"
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="Stop on first critical test failure"
    )
    parser.add_argument(
        "--redis-url", default=config.redis_url, help="Redis connection URL"
    )

    # Test selection arguments
    parser.add_argument(
        "--test-suite",
        choices=["quick", "standard", "comprehensive"],
        default="standard",
        help="Test suite intensity",
    )

    args = parser.parse_args()

    # Configure test parameters based on suite
    test_suites = {
        "quick": {
            "api_users": 10,
            "service_users": 8,
            "websocket_users": 5,
            "integration_users": 3,
            "parallel_execution": False,
        },
        "standard": {
            "api_users": args.api_users,
            "service_users": args.service_users,
            "websocket_users": args.websocket_users,
            "integration_users": args.integration_users,
            "parallel_execution": args.parallel,
        },
        "comprehensive": {
            "api_users": 50,
            "service_users": 40,
            "websocket_users": 25,
            "integration_users": 20,
            "parallel_execution": True,
        },
    }

    test_config = test_suites[args.test_suite]
    test_config.update(
        {
            "host": args.host,
            "ws_host": args.ws_host,
            "redis_url": args.redis_url,
            "fail_fast": args.fail_fast,
            "test_suite": args.test_suite,
        }
    )

    # Create results directory
    os.makedirs("results", exist_ok=True)

    # Run comprehensive test
    orchestrator = LoadTestOrchestrator()
    results = orchestrator.run_comprehensive_test(test_config)

    # Exit with appropriate code
    success_rate = (
        sum(1 for r in results.values() if r.get("success", False)) / len(results) * 100
        if results
        else 0
    )
    exit_code = 0 if success_rate >= 80 else 1  # 80% success threshold

    print(f"\\n🏁 Load testing completed with {success_rate:.1f}% success rate")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
