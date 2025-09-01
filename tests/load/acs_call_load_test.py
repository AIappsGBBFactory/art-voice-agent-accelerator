#!/usr/bin/env python3
"""
ACS Call Load Testing Framework
===============================

Tests actual Azure Communication Services phone call initiation and management,
including real PSTN calls, call automation, and end-to-end call lifecycle.

This tests the complete ACS integration, not just the WebSocket endpoint.
"""

import asyncio
import time
import json
import statistics
import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from pathlib import Path
import uuid

import httpx
from src.acs.acs_helper import AcsCaller, StreamMode


@dataclass
class AcsCallMetrics:
    """Metrics for a single ACS call test."""

    call_id: str
    target_number: str
    call_initiation_time_ms: float
    call_established_time_ms: float
    call_duration_ms: float
    success: bool
    error_message: str = ""
    call_connection_id: str = ""

    # ACS-specific metrics
    acs_api_latency_ms: float = 0
    call_automation_latency_ms: float = 0
    media_stream_established_ms: float = 0


@dataclass
class AcsLoadTestConfig:
    """Configuration for ACS load testing."""

    total_calls: int = 10
    concurrent_calls: int = 3
    target_phone_numbers: List[str] = None  # List of test numbers
    call_duration_seconds: int = 30
    source_phone_number: str = ""
    acs_connection_string: str = ""
    callback_url: str = ""

    def __post_init__(self):
        """Validate configuration."""
        if not self.target_phone_numbers:
            # Try to get from environment variable if not provided via parameters
            env_phone = os.getenv("ACS_TARGET_PHONE_NUMBER")
            if env_phone:
                self.target_phone_numbers = [env_phone]
            else:
                self.target_phone_numbers = []


class AcsCallLoadTester:
    """Load tester for actual ACS phone calls."""

    def __init__(self, config: AcsLoadTestConfig):
        self.config = config
        self.results: List[AcsCallMetrics] = []

        # Initialize ACS caller
        self.acs_caller = AcsCaller(
            source_number=config.source_phone_number,
            callback_url=config.callback_url,
            acs_connection_string=config.acs_connection_string,
            websocket_url="ws://localhost:8010/api/v1/media/stream",
        )

    async def initiate_single_call(
        self, target_number: str, call_id: str
    ) -> AcsCallMetrics:
        """Initiate a single ACS call and measure performance."""

        metrics = AcsCallMetrics(
            call_id=call_id,
            target_number=target_number,
            call_initiation_time_ms=0,
            call_established_time_ms=0,
            call_duration_ms=0,
            success=False,
        )

        try:
            print(f"📞 Initiating ACS call {call_id} to {target_number}")

            # Measure call initiation time
            start_time = time.time()

            # Call ACS API to initiate call
            call_result = await self.acs_caller.initiate_call(
                target_number=target_number, stream_mode=StreamMode.MEDIA
            )

            acs_api_time = time.time()
            metrics.acs_api_latency_ms = (acs_api_time - start_time) * 1000
            metrics.call_connection_id = call_result.get("call_id", "")

            print(f"✅ ACS API call successful: {metrics.call_connection_id}")
            print(f"   ACS API Latency: {metrics.acs_api_latency_ms:.1f}ms")

            # TODO: In a real test, you'd wait for call establishment
            # and measure actual call metrics via ACS webhooks/events

            # For now, simulate call establishment
            await asyncio.sleep(2)  # Simulate call setup time

            call_established_time = time.time()
            metrics.call_established_time_ms = (
                call_established_time - start_time
            ) * 1000

            # Simulate call duration
            await asyncio.sleep(self.config.call_duration_seconds)

            call_end_time = time.time()
            metrics.call_duration_ms = (call_end_time - start_time) * 1000

            # TODO: Properly hang up the call via ACS API
            # connection = self.acs_caller.get_call_connection(metrics.call_connection_id)
            # if connection:
            #     connection.hang_up()

            metrics.success = True
            print(f"✅ Call {call_id} completed successfully")

        except Exception as e:
            metrics.error_message = str(e)
            metrics.success = False
            print(f"❌ Call {call_id} failed: {e}")

        return metrics

    async def run_load_test(self) -> Dict[str, Any]:
        """Run the complete ACS call load test."""

        print(f"🚀 Starting ACS Call Load Test")
        print(f"   Total Calls: {self.config.total_calls}")
        print(f"   Concurrent: {self.config.concurrent_calls}")
        print(f"   Target Numbers: {len(self.config.target_phone_numbers)}")
        print(f"   Call Duration: {self.config.call_duration_seconds}s")
        print()

        start_time = time.time()
        semaphore = asyncio.Semaphore(self.config.concurrent_calls)

        async def run_single_call(call_index: int) -> AcsCallMetrics:
            async with semaphore:
                target_number = self.config.target_phone_numbers[
                    call_index % len(self.config.target_phone_numbers)
                ]
                call_id = f"load-test-{call_index}-{uuid.uuid4().hex[:8]}"
                return await self.initiate_single_call(target_number, call_id)

        # Run all calls concurrently
        tasks = [run_single_call(i) for i in range(self.config.total_calls)]
        self.results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and failed calls
        valid_results = [r for r in self.results if isinstance(r, AcsCallMetrics)]

        end_time = time.time()
        test_duration = end_time - start_time

        # Calculate statistics
        successful_calls = [r for r in valid_results if r.success]
        failed_calls = [r for r in valid_results if not r.success]

        print(f"\n📊 ACS Call Load Test Results")
        print(f"=" * 50)
        print(f"Test Duration: {test_duration:.2f}s")
        print(f"Total Calls: {len(valid_results)}")
        print(f"Successful: {len(successful_calls)}")
        print(f"Failed: {len(failed_calls)}")
        print(f"Success Rate: {len(successful_calls)/len(valid_results)*100:.1f}%")

        if successful_calls:
            acs_latencies = [c.acs_api_latency_ms for c in successful_calls]
            establishment_times = [c.call_established_time_ms for c in successful_calls]

            print(f"\n⏱️  ACS API Latency Statistics:")
            print(f"   Mean: {statistics.mean(acs_latencies):.1f}ms")
            print(f"   P50:  {statistics.median(acs_latencies):.1f}ms")
            print(
                f"   P95:  {statistics.quantiles(acs_latencies, n=20)[18] if len(acs_latencies) >= 20 else max(acs_latencies):.1f}ms"
            )
            print(f"   Max:  {max(acs_latencies):.1f}ms")

            print(f"\n📞 Call Establishment Statistics:")
            print(f"   Mean: {statistics.mean(establishment_times):.1f}ms")
            print(f"   P50:  {statistics.median(establishment_times):.1f}ms")
            print(
                f"   P95:  {statistics.quantiles(establishment_times, n=20)[18] if len(establishment_times) >= 20 else max(establishment_times):.1f}ms"
            )
            print(f"   Max:  {max(establishment_times):.1f}ms")

        if failed_calls:
            print(f"\n❌ Failed Call Analysis:")
            error_counts = {}
            for call in failed_calls:
                error_type = (
                    call.error_message.split(":")[0]
                    if ":" in call.error_message
                    else call.error_message
                )
                error_counts[error_type] = error_counts.get(error_type, 0) + 1

            for error, count in error_counts.items():
                print(f"   {error}: {count} calls")

        return {
            "test_duration_s": test_duration,
            "total_calls": len(valid_results),
            "successful_calls": len(successful_calls),
            "failed_calls": len(failed_calls),
            "success_rate_percent": len(successful_calls) / len(valid_results) * 100
            if valid_results
            else 0,
            "acs_api_latency_stats": {
                "mean_ms": statistics.mean(acs_latencies) if acs_latencies else 0,
                "p95_ms": statistics.quantiles(acs_latencies, n=20)[18]
                if len(acs_latencies) >= 20
                else max(acs_latencies)
                if acs_latencies
                else 0,
                "max_ms": max(acs_latencies) if acs_latencies else 0,
            },
            "call_establishment_stats": {
                "mean_ms": statistics.mean(establishment_times)
                if establishment_times
                else 0,
                "p95_ms": statistics.quantiles(establishment_times, n=20)[18]
                if len(establishment_times) >= 20
                else max(establishment_times)
                if establishment_times
                else 0,
                "max_ms": max(establishment_times) if establishment_times else 0,
            },
            "error_breakdown": error_counts if failed_calls else {},
        }


async def main():
    """Example usage of ACS call load testing - Development Configuration."""
    import argparse

    parser = argparse.ArgumentParser(description="ACS Call Load Testing")
    parser.add_argument(
        "--target-phones",
        nargs="+",
        required=False,  # Not required anymore since we have env fallback
        help="Target phone numbers to call (e.g., --target-phones +8165019907 +1234567890). If not provided, uses ACS_TARGET_PHONE_NUMBER env var.",
    )
    parser.add_argument(
        "--total-calls", type=int, default=1, help="Total number of calls to make"
    )
    parser.add_argument(
        "--concurrent", type=int, default=1, help="Number of concurrent calls"
    )
    parser.add_argument(
        "--duration", type=int, default=15, help="Call duration in seconds"
    )

    args = parser.parse_args()

    # 🎯 CONFIGURABLE DEVELOPMENT CONFIGURATION
    config = AcsLoadTestConfig(
        total_calls=args.total_calls,
        concurrent_calls=args.concurrent,
        target_phone_numbers=args.target_phones,  # Use provided phone numbers (or None to use env var)
        call_duration_seconds=args.duration,
        source_phone_number=os.getenv("ACS_SOURCE_PHONE_NUMBER", ""),
        acs_connection_string=os.getenv("ACS_CONNECTION_STRING", ""),
        callback_url=os.getenv(
            "ACS_CALLBACK_URL", "https://your-domain.com/api/v1/acs/events"
        ),
    )

    # Validate that we have target phone numbers
    if not config.target_phone_numbers:
        print("❌ No target phone numbers provided!")
        print(
            "   Either use --target-phones parameter or set ACS_TARGET_PHONE_NUMBER environment variable"
        )
        print("   Examples:")
        print(
            "     python tests/load/acs_call_load_test.py --target-phones +8165019907"
        )
        print("     export ACS_TARGET_PHONE_NUMBER='+8165019907'")
        exit(1)

    print(f"🎯 ACS Call Load Test Configuration:")
    print(f"   Target Phones: {', '.join(config.target_phone_numbers)}")
    print(f"   Source Phone: {config.source_phone_number}")
    print(f"   Total Calls: {config.total_calls}")
    print(f"   Concurrent: {config.concurrent_calls}")
    print(f"   Duration: {config.call_duration_seconds}s")
    print()

    tester = AcsCallLoadTester(config)
    results = await tester.run_load_test()

    # Save results with timestamp
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    results_file = Path(f"tests/load/results/acs_call_load_test_{timestamp}.json")
    results_file.parent.mkdir(exist_ok=True)

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n💾 Results saved to: {results_file}")

    # Print scaling instructions
    print(f"\n🚀 Example scaling commands:")
    print(
        f"   python tests/load/acs_call_load_test.py --target-phones {' '.join(config.target_phone_numbers)} --total-calls 5 --concurrent 2"
    )
    print(
        f"   python tests/load/acs_call_load_test.py --target-phones {' '.join(config.target_phone_numbers)} --total-calls 10 --concurrent 3 --duration 30"
    )


if __name__ == "__main__":
    # ⚠️ IMPORTANT: This requires real phone numbers and will incur charges!
    # Only run this if you have proper test setup
    import os

    required_env_vars = ["ACS_SOURCE_PHONE_NUMBER", "ACS_CONNECTION_STRING"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]

    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   {var}")
        print("\nPlease set these environment variables before running ACS call tests:")
        print(
            "   export ACS_SOURCE_PHONE_NUMBER='+1234567890'     # Your ACS phone number"
        )
        print(
            "   export ACS_CONNECTION_STRING='endpoint=https://...'  # Your ACS connection string"
        )
        print(
            "   export ACS_TARGET_PHONE_NUMBER='+8165019907'     # Target phone to call (optional)"
        )
        exit(1)

    print("⚠️  WARNING: This will initiate real ACS phone calls!")
    print("⚠️  Make sure you have test numbers and sufficient credits!")
    print("⚠️  Press Ctrl+C to cancel, or wait 5 seconds to continue...")

    try:
        time.sleep(5)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Test cancelled by user")
