#!/usr/bin/env python3
"""
Comprehensive Load Testing Suite
================================

Production-ready load testing suite for evaluating system performance
under various concurrent conversation loads.
"""

import asyncio
import sys
from pathlib import Path
import argparse
from datetime import datetime

# Add current directory to path for imports
sys.path.append(str(Path(__file__).parent))

from load_test_conversations import ConversationLoadTester, LoadTestConfig


class ComprehensiveLoadTest:
    """Comprehensive load testing with multiple scenarios."""

    def __init__(self, base_url: str = "ws://localhost:8010/api/v1/media/stream"):
        self.base_url = base_url
        self.results = []

    async def run_light_load_test(self, max_turns: int = 3) -> dict:
        """Light load: 3 concurrent, 3 total conversations with configurable turns."""
        print("🟢 Running LIGHT load test...")

        config = LoadTestConfig(
            max_concurrent_conversations=3,
            total_conversations=3,
            ramp_up_time_s=5.0,
            test_duration_s=120.0,
            conversation_templates=["quick_question"],
            ws_url=self.base_url,
            output_dir="tests/load/results",
            max_conversation_turns=max_turns,
            min_conversation_turns=1,
            turn_variation_strategy="random",
        )

        tester = ConversationLoadTester(config)
        results = await tester.run_load_test()

        print("📊 LIGHT LOAD RESULTS:")
        tester.print_summary(results)

        filename = f"light_load_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results_file = tester.save_results(results, filename)

        return {
            "test_type": "light",
            "config": config,
            "results": results,
            "results_file": results_file,
            "summary": results.get_summary(),
        }

    async def run_medium_load_test(self, max_turns: int = 5) -> dict:
        """Medium load: 10 concurrent, 30 total conversations with configurable turns."""
        print("🟡 Running MEDIUM load test...")

        config = LoadTestConfig(
            max_concurrent_conversations=10,
            total_conversations=30,
            ramp_up_time_s=15.0,
            test_duration_s=120.0,
            conversation_templates=[
                "quick_question",
                "insurance_inquiry",
                "confused_customer",
            ],
            ws_url=self.base_url,
            output_dir="tests/load/results",
            max_conversation_turns=max_turns,
            min_conversation_turns=2,
            turn_variation_strategy="random",
        )

        tester = ConversationLoadTester(config)
        results = await tester.run_load_test()

        print("📊 MEDIUM LOAD RESULTS:")
        tester.print_summary(results)

        filename = f"medium_load_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results_file = tester.save_results(results, filename)

        return {
            "test_type": "medium",
            "config": config,
            "results": results,
            "results_file": results_file,
            "summary": results.get_summary(),
        }

    async def run_heavy_load_test(self, max_turns: int = 7) -> dict:
        """Heavy load: 20 concurrent, 50 total conversations with configurable turns."""
        print("🔴 Running HEAVY load test...")

        config = LoadTestConfig(
            max_concurrent_conversations=20,
            total_conversations=50,
            ramp_up_time_s=30.0,
            test_duration_s=300.0,
            conversation_templates=[
                "quick_question",
                "insurance_inquiry",
                "confused_customer",
            ],
            ws_url=self.base_url,
            output_dir="tests/load/results",
            max_conversation_turns=max_turns,
            min_conversation_turns=3,
            turn_variation_strategy="increasing",
        )

        tester = ConversationLoadTester(config)
        results = await tester.run_load_test()

        print("📊 HEAVY LOAD RESULTS:")
        tester.print_summary(results)

        filename = f"heavy_load_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results_file = tester.save_results(results, filename)

        return {
            "test_type": "heavy",
            "config": config,
            "results": results,
            "results_file": results_file,
            "summary": results.get_summary(),
        }

    async def run_stress_test(self, max_turns: int = 10) -> dict:
        """Stress test: 150 concurrent, 200 total conversations with configurable turns."""
        print("🚨 Running STRESS test...")

        config = LoadTestConfig(
            max_concurrent_conversations=150,
            total_conversations=200,
            ramp_up_time_s=60.0,
            test_duration_s=600.0,
            conversation_templates=[
                "quick_question",
                "insurance_inquiry",
                "confused_customer",
            ],
            ws_url=self.base_url,
            output_dir="tests/load/results",
            max_conversation_turns=max_turns,
            min_conversation_turns=1,
            turn_variation_strategy="random",
        )

        tester = ConversationLoadTester(config)
        results = await tester.run_load_test()

        print("📊 STRESS TEST RESULTS:")
        tester.print_summary(results)

        filename = f"stress_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results_file = tester.save_results(results, filename)

        return {
            "test_type": "stress",
            "config": config,
            "results": results,
            "results_file": results_file,
            "summary": results.get_summary(),
        }

    async def run_endurance_test(self, max_turns: int = 6) -> dict:
        """Endurance test: 15 concurrent, 200 total conversations over 30 minutes with configurable turns."""
        print("⏳ Running ENDURANCE test...")

        config = LoadTestConfig(
            max_concurrent_conversations=15,
            total_conversations=200,
            ramp_up_time_s=60.0,
            test_duration_s=1800.0,  # 30 minutes
            conversation_templates=[
                "quick_question",
                "insurance_inquiry",
                "confused_customer",
            ],
            ws_url=self.base_url,
            output_dir="tests/load/results",
            max_conversation_turns=max_turns,
            min_conversation_turns=2,
            turn_variation_strategy="random",
        )

        tester = ConversationLoadTester(config)
        results = await tester.run_load_test()

        print("📊 ENDURANCE TEST RESULTS:")
        tester.print_summary(results)

        filename = f"endurance_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results_file = tester.save_results(results, filename)

        return {
            "test_type": "endurance",
            "config": config,
            "results": results,
            "results_file": results_file,
            "summary": results.get_summary(),
        }

    def compare_test_results(self, test_results: list) -> dict:
        """Compare results across different load test scenarios."""

        print(f"\n📈 COMPREHENSIVE LOAD TEST COMPARISON")
        print(f"=" * 70)

        comparison = {"test_count": len(test_results), "tests": {}, "trends": {}}

        # Extract key metrics for each test
        for test_result in test_results:
            test_type = test_result["test_type"]
            summary = test_result["summary"]

            comparison["tests"][test_type] = {
                "success_rate": summary.get("success_rate_percent", 0),
                "peak_concurrency": summary.get("peak_concurrency", 0),
                "avg_connection_ms": summary.get("connection_times_ms", {}).get(
                    "avg", 0
                ),
                "avg_agent_response_ms": summary.get("agent_response_times_ms", {}).get(
                    "avg", 0
                ),
                "conversations_completed": summary.get("conversations_completed", 0),
                "conversations_attempted": summary.get("conversations_attempted", 0),
                "error_count": summary.get("error_count", 0),
            }

        # Print comparison table
        print(
            f"{'Test Type':<12} {'Success%':<8} {'Peak Conc':<10} {'Avg Conn(ms)':<12} {'Avg Agent(ms)':<13} {'Completed':<10} {'Errors':<7}"
        )
        print(f"-" * 70)

        for test_type, metrics in comparison["tests"].items():
            print(
                f"{test_type:<12} "
                f"{metrics['success_rate']:<8.1f} "
                f"{metrics['peak_concurrency']:<10} "
                f"{metrics['avg_connection_ms']:<12.0f} "
                f"{metrics['avg_agent_response_ms']:<13.0f} "
                f"{metrics['conversations_completed']:<10} "
                f"{metrics['error_count']:<7}"
            )

        # Analyze trends
        success_rates = [m["success_rate"] for m in comparison["tests"].values()]
        connection_times = [
            m["avg_connection_ms"]
            for m in comparison["tests"].values()
            if m["avg_connection_ms"] > 0
        ]
        agent_times = [
            m["avg_agent_response_ms"]
            for m in comparison["tests"].values()
            if m["avg_agent_response_ms"] > 0
        ]

        comparison["trends"] = {
            "success_rate_trend": "stable"
            if max(success_rates) - min(success_rates) < 10
            else "degrading",
            "connection_time_trend": "stable"
            if not connection_times
            or max(connection_times) / min(connection_times) < 2.0
            else "increasing",
            "agent_response_trend": "stable"
            if not agent_times or max(agent_times) / min(agent_times) < 2.0
            else "increasing",
        }

        print(f"\n🔍 TRENDS ANALYSIS:")
        for trend_name, trend_value in comparison["trends"].items():
            status_emoji = "✅" if trend_value == "stable" else "⚠️"
            print(
                f"   {status_emoji} {trend_name.replace('_', ' ').title()}: {trend_value}"
            )

        return comparison

    async def run_comprehensive_suite(
        self,
        tests: list = None,
        pause_between_tests_s: float = 30.0,
        max_conversation_turns: int = 5,
    ) -> list:
        """Run a comprehensive suite of load tests with configurable conversation depth."""

        if tests is None:
            tests = ["light", "medium", "heavy"]  # Default to non-extreme tests

        print(f"🚀 Starting comprehensive load testing suite")
        print(f"📋 Tests to run: {', '.join(tests)}")
        print(f"🔄 Max conversation turns: {max_conversation_turns}")
        print(f"⏸️  Pause between tests: {pause_between_tests_s}s")
        print(f"🎯 Target URL: {self.base_url}")
        print("=" * 70)

        # Update test mapping to pass max_conversation_turns
        test_mapping = {
            "light": lambda: self.run_light_load_test(
                max_turns=min(3, max_conversation_turns)
            ),
            "medium": lambda: self.run_medium_load_test(
                max_turns=max_conversation_turns
            ),
            "heavy": lambda: self.run_heavy_load_test(max_turns=max_conversation_turns),
            "stress": lambda: self.run_stress_test(max_turns=max_conversation_turns),
            "endurance": lambda: self.run_endurance_test(
                max_turns=max_conversation_turns
            ),
        }

        results = []

        for i, test_name in enumerate(tests):
            if test_name not in test_mapping:
                print(f"❌ Unknown test: {test_name}")
                continue

            print(f"\n🔄 Running test {i+1}/{len(tests)}: {test_name.upper()}")

            try:
                test_func = test_mapping[test_name]
                result = await test_func()
                results.append(result)

                print(f"✅ {test_name.upper()} test completed")

                # Pause between tests (except after the last one)
                if i < len(tests) - 1:
                    print(f"⏸️  Pausing {pause_between_tests_s}s before next test...")
                    await asyncio.sleep(pause_between_tests_s)

            except Exception as e:
                print(f"❌ {test_name.upper()} test failed: {e}")
                results.append(
                    {
                        "test_type": test_name,
                        "error": str(e),
                        "summary": {"success_rate_percent": 0, "error_count": 1},
                    }
                )

        # Generate comparison report
        if len(results) > 1:
            comparison = self.compare_test_results(results)

        print(f"\n🎉 Comprehensive load testing suite completed!")
        print(
            f"📊 Tests completed: {len([r for r in results if 'error' not in r])}/{len(tests)}"
        )

        return results


async def main():
    """Main entry point for comprehensive load testing with configurable conversation depth."""

    parser = argparse.ArgumentParser(description="Comprehensive Load Testing Suite")
    parser.add_argument(
        "--url",
        default="ws://localhost:8010/api/v1/media/stream",
        help="WebSocket URL to test",
    )
    parser.add_argument(
        "--tests",
        nargs="+",
        choices=["light", "medium", "heavy", "stress", "endurance"],
        default=["light", "medium"],
        help="Tests to run",
    )
    parser.add_argument(
        "--pause", type=float, default=30.0, help="Pause between tests in seconds"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=5,
        help="Maximum conversation turns per conversation (default: 5)",
    )

    args = parser.parse_args()

    # Create results directory
    results_dir = Path("tests/load/results")
    results_dir.mkdir(parents=True, exist_ok=True)

    # Run comprehensive tests
    suite = ComprehensiveLoadTest(args.url)
    results = await suite.run_comprehensive_suite(
        tests=args.tests,
        pause_between_tests_s=args.pause,
        max_conversation_turns=args.max_turns,
    )

    # Save overall summary
    overall_summary = {
        "timestamp": datetime.now().isoformat(),
        "url_tested": args.url,
        "tests_run": args.tests,
        "results": [
            {
                "test_type": r["test_type"],
                "success": "error" not in r,
                "summary": r.get("summary", {}),
                "results_file": r.get("results_file"),
            }
            for r in results
        ],
    }

    summary_file = (
        results_dir
        / f"comprehensive_test_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(summary_file, "w") as f:
        import json

        json.dump(overall_summary, f, indent=2)

    print(f"\n💾 Overall summary saved to: {summary_file}")


if __name__ == "__main__":
    asyncio.run(main())
