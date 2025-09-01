#!/usr/bin/env python3
"""
Azure Load Test Compatible Comprehensive Load Testing Suite
===========================================================

Azure Load Test compatible version of the comprehensive load testing suite
optimized for cloud-scale testing with enhanced metrics tracking.

This script is designed to work with Azure Load Test's JMeter-based infrastructure
while maintaining comprehensive conversation-based load testing capabilities.
"""

import asyncio
import sys
import json
import time
import uuid
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import statistics
import logging

# Add current directory to path for imports
sys.path.append(str(Path(__file__).parent))

from conversation_simulator import (
    ConversationSimulator,
    ConversationTemplates,
    ConversationMetrics,
    ConversationTemplate,
)

# Configure logging for Azure Load Test
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/azure_load_test.log")
        if "/tmp" in os.environ.get("PATH", "")
        else logging.NullHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class AzureLoadTestConfig:
    """Azure Load Test optimized configuration."""

    # Test execution parameters
    test_duration_minutes: int = 5
    ramp_up_duration_minutes: int = 1
    target_rps: float = 10.0  # Requests per second
    max_concurrent_users: int = 50

    # Conversation parameters
    conversation_templates: List[str] = field(
        default_factory=lambda: ["quick_question", "insurance_inquiry"]
    )
    ws_url: str = "ws://localhost:8010/api/v1/media/stream"

    # Azure-specific parameters
    azure_test_id: str = field(
        default_factory=lambda: f"load-test-{uuid.uuid4().hex[:8]}"
    )
    azure_resource_group: str = "load-test-rg"
    azure_location: str = "eastus"

    # Metrics and monitoring
    enable_app_insights: bool = True
    enable_detailed_metrics: bool = True
    custom_metrics_endpoint: Optional[str] = None

    # Output configuration
    results_container: str = "load-test-results"
    output_format: str = "json"


@dataclass
class AzureLoadTestMetrics:
    """Comprehensive metrics for Azure Load Test."""

    # Test metadata
    test_id: str
    start_time: datetime
    end_time: Optional[datetime] = None

    # Performance metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    error_rate_percent: float = 0.0

    # Response time metrics (ms)
    response_times_ms: List[float] = field(default_factory=list)
    connection_times_ms: List[float] = field(default_factory=list)

    # Throughput metrics
    requests_per_second: float = 0.0
    bytes_per_second: float = 0.0

    # Conversation-specific metrics
    conversations_completed: int = 0
    conversations_failed: int = 0
    avg_conversation_duration_s: float = 0.0

    # Agent performance metrics
    agent_response_times_ms: List[float] = field(default_factory=list)
    speech_recognition_times_ms: List[float] = field(default_factory=list)
    audio_processing_times_ms: List[float] = field(default_factory=list)

    # Resource utilization (if available)
    cpu_usage_percent: List[float] = field(default_factory=list)
    memory_usage_mb: List[float] = field(default_factory=list)

    # Network metrics
    bytes_sent: int = 0
    bytes_received: int = 0
    network_errors: int = 0

    # Error tracking
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    error_messages: List[str] = field(default_factory=list)

    # Custom business metrics
    user_satisfaction_score: float = 0.0
    task_completion_rate: float = 0.0
    conversation_quality_score: float = 0.0

    def calculate_summary_stats(self) -> Dict[str, Any]:
        """Calculate comprehensive summary statistics."""
        duration_s = (
            (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        )

        summary = {
            "test_metadata": {
                "test_id": self.test_id,
                "duration_seconds": duration_s,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat() if self.end_time else None,
            },
            "performance": {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "success_rate_percent": (
                    self.successful_requests / max(1, self.total_requests)
                )
                * 100,
                "error_rate_percent": self.error_rate_percent,
                "requests_per_second": self.requests_per_second,
                "throughput_bytes_per_second": self.bytes_per_second,
            },
        }

        # Response time statistics
        if self.response_times_ms:
            summary["response_times_ms"] = {
                "min": min(self.response_times_ms),
                "max": max(self.response_times_ms),
                "mean": statistics.mean(self.response_times_ms),
                "median": statistics.median(self.response_times_ms),
                "p90": statistics.quantiles(self.response_times_ms, n=10)[8]
                if len(self.response_times_ms) >= 10
                else max(self.response_times_ms),
                "p95": statistics.quantiles(self.response_times_ms, n=20)[18]
                if len(self.response_times_ms) >= 20
                else max(self.response_times_ms),
                "p99": statistics.quantiles(self.response_times_ms, n=100)[98]
                if len(self.response_times_ms) >= 100
                else max(self.response_times_ms),
                "std_dev": statistics.stdev(self.response_times_ms)
                if len(self.response_times_ms) > 1
                else 0,
            }

        # Connection time statistics
        if self.connection_times_ms:
            summary["connection_times_ms"] = {
                "min": min(self.connection_times_ms),
                "max": max(self.connection_times_ms),
                "mean": statistics.mean(self.connection_times_ms),
                "median": statistics.median(self.connection_times_ms),
                "p95": statistics.quantiles(self.connection_times_ms, n=20)[18]
                if len(self.connection_times_ms) >= 20
                else max(self.connection_times_ms),
            }

        # Agent performance
        if self.agent_response_times_ms:
            summary["agent_performance_ms"] = {
                "mean_response_time": statistics.mean(self.agent_response_times_ms),
                "p95_response_time": statistics.quantiles(
                    self.agent_response_times_ms, n=20
                )[18]
                if len(self.agent_response_times_ms) >= 20
                else max(self.agent_response_times_ms),
                "fastest_response": min(self.agent_response_times_ms),
                "slowest_response": max(self.agent_response_times_ms),
            }

        # Conversation metrics
        summary["conversations"] = {
            "completed": self.conversations_completed,
            "failed": self.conversations_failed,
            "completion_rate_percent": (
                self.conversations_completed
                / max(1, self.conversations_completed + self.conversations_failed)
            )
            * 100,
            "avg_duration_seconds": self.avg_conversation_duration_s,
        }

        # Network metrics
        summary["network"] = {
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "total_bytes": self.bytes_sent + self.bytes_received,
            "network_errors": self.network_errors,
        }

        # Quality metrics
        summary["quality"] = {
            "user_satisfaction_score": self.user_satisfaction_score,
            "task_completion_rate": self.task_completion_rate,
            "conversation_quality_score": self.conversation_quality_score,
        }

        # Error analysis
        summary["errors"] = {
            "total_errors": len(self.error_messages),
            "errors_by_type": self.errors_by_type,
            "top_errors": self.error_messages[:10] if self.error_messages else [],
        }

        return summary


class AzureConversationLoadTester:
    """Azure Load Test optimized conversation load tester."""

    def __init__(self, config: AzureLoadTestConfig):
        self.config = config
        self.metrics = AzureLoadTestMetrics(
            test_id=config.azure_test_id, start_time=datetime.utcnow()
        )
        self.active_conversations = 0

        # Get conversation templates
        self.templates = {
            template.name: template
            for template in ConversationTemplates.get_all_templates()
        }

        logger.info(f"Initialized Azure Load Tester with ID: {config.azure_test_id}")

    def log_azure_metric(
        self, metric_name: str, value: float, dimensions: Dict[str, str] = None
    ):
        """Log custom metrics for Azure Monitor."""
        dimensions = dimensions or {}
        timestamp = datetime.utcnow().isoformat()

        metric_data = {
            "timestamp": timestamp,
            "metric_name": metric_name,
            "value": value,
            "dimensions": dimensions,
            "test_id": self.config.azure_test_id,
        }

        # Log to standard output for Azure Load Test ingestion
        print(f"AZURE_METRIC: {json.dumps(metric_data)}")
        logger.info(f"Azure Metric - {metric_name}: {value}")

    async def run_single_conversation_azure(
        self, template: ConversationTemplate, user_id: str, semaphore: asyncio.Semaphore
    ) -> Optional[ConversationMetrics]:
        """Run a single conversation optimized for Azure Load Test."""

        async with semaphore:
            self.active_conversations += 1
            start_time = time.time()

            simulator = ConversationSimulator(self.config.ws_url)
            session_id = f"azure-{self.config.azure_test_id}-{user_id}"

            try:
                logger.info(
                    f"Starting Azure conversation {user_id} with template {template.name}"
                )

                # Log conversation start
                self.log_azure_metric(
                    "conversation_started",
                    1,
                    {"template": template.name, "user_id": user_id},
                )

                metrics = await simulator.simulate_conversation(template, session_id)

                # Calculate timings
                conversation_duration = time.time() - start_time

                # Update metrics
                self.metrics.total_requests += 1
                self.metrics.successful_requests += 1
                self.metrics.conversations_completed += 1

                # Record response times
                self.metrics.response_times_ms.append(conversation_duration * 1000)
                self.metrics.connection_times_ms.append(metrics.connection_time_ms)

                # Agent performance metrics
                if metrics.total_agent_processing_time_ms > 0:
                    avg_agent_time = metrics.total_agent_processing_time_ms / max(
                        1, metrics.user_turns
                    )
                    self.metrics.agent_response_times_ms.append(avg_agent_time)

                    self.log_azure_metric(
                        "agent_response_time_ms",
                        avg_agent_time,
                        {"template": template.name, "user_id": user_id},
                    )

                # Speech recognition metrics
                if metrics.total_speech_recognition_time_ms > 0:
                    avg_speech_time = metrics.total_speech_recognition_time_ms / max(
                        1, metrics.user_turns
                    )
                    self.metrics.speech_recognition_times_ms.append(avg_speech_time)

                    self.log_azure_metric(
                        "speech_recognition_time_ms",
                        avg_speech_time,
                        {"template": template.name, "user_id": user_id},
                    )

                # Network metrics
                estimated_bytes = len(json.dumps(metrics.__dict__).encode("utf-8"))
                self.metrics.bytes_received += estimated_bytes

                # Log conversation completion
                self.log_azure_metric(
                    "conversation_completed",
                    1,
                    {
                        "template": template.name,
                        "user_id": user_id,
                        "duration_ms": conversation_duration * 1000,
                        "success": "true",
                    },
                )

                logger.info(
                    f"Completed Azure conversation {user_id} in {conversation_duration:.2f}s"
                )
                return metrics

            except Exception as e:
                error_msg = f"Azure conversation {user_id} failed: {str(e)}"
                logger.error(error_msg)

                # Update error metrics
                self.metrics.total_requests += 1
                self.metrics.failed_requests += 1
                self.metrics.conversations_failed += 1
                self.metrics.error_messages.append(error_msg)

                error_type = type(e).__name__
                self.metrics.errors_by_type[error_type] = (
                    self.metrics.errors_by_type.get(error_type, 0) + 1
                )

                # Log error to Azure
                self.log_azure_metric(
                    "conversation_failed",
                    1,
                    {
                        "template": template.name,
                        "user_id": user_id,
                        "error_type": error_type,
                        "success": "false",
                    },
                )

                return None

            finally:
                self.active_conversations -= 1

    async def run_azure_load_test_scenario(self, scenario_name: str) -> Dict[str, Any]:
        """Run a specific load test scenario optimized for Azure."""

        scenario_configs = {
            "light": {
                "max_concurrent": 5,
                "duration_minutes": 2,
                "target_rps": 2.0,
                "templates": ["quick_question"],
            },
            "medium": {
                "max_concurrent": 15,
                "duration_minutes": 5,
                "target_rps": 5.0,
                "templates": ["quick_question", "insurance_inquiry"],
            },
            "heavy": {
                "max_concurrent": 30,
                "duration_minutes": 10,
                "target_rps": 10.0,
                "templates": [
                    "quick_question",
                    "insurance_inquiry",
                    "confused_customer",
                ],
            },
            "stress": {
                "max_concurrent": 100,
                "duration_minutes": 15,
                "target_rps": 20.0,
                "templates": [
                    "quick_question",
                    "insurance_inquiry",
                    "confused_customer",
                ],
            },
        }

        if scenario_name not in scenario_configs:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        scenario_config = scenario_configs[scenario_name]

        logger.info(f"🚀 Starting Azure Load Test scenario: {scenario_name.upper()}")
        logger.info(f"📊 Configuration: {scenario_config}")

        # Update config
        self.config.max_concurrent_users = scenario_config["max_concurrent"]
        self.config.test_duration_minutes = scenario_config["duration_minutes"]
        self.config.target_rps = scenario_config["target_rps"]
        self.config.conversation_templates = scenario_config["templates"]

        # Reset metrics
        self.metrics = AzureLoadTestMetrics(
            test_id=f"{self.config.azure_test_id}-{scenario_name}",
            start_time=datetime.utcnow(),
        )

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.config.max_concurrent_users)

        # Calculate test parameters
        test_duration_s = self.config.test_duration_minutes * 60
        ramp_up_duration_s = self.config.ramp_up_duration_minutes * 60
        total_conversations = int(self.config.target_rps * test_duration_s)

        logger.info(
            f"⏰ Test duration: {test_duration_s}s, Target conversations: {total_conversations}"
        )

        # Track active tasks
        active_tasks = set()
        conversation_counter = 0
        test_start_time = time.time()

        try:
            while (
                time.time() - test_start_time < test_duration_s
                and conversation_counter < total_conversations
            ):
                elapsed_time = time.time() - test_start_time

                # Calculate current RPS based on ramp-up
                if elapsed_time < ramp_up_duration_s:
                    current_rps = (
                        elapsed_time / ramp_up_duration_s
                    ) * self.config.target_rps
                else:
                    current_rps = self.config.target_rps

                # Calculate delay between conversation starts
                delay_between_starts = 1.0 / max(current_rps, 0.1)

                # Start new conversation if under concurrency limit
                if (
                    len(active_tasks) < self.config.max_concurrent_users
                    and conversation_counter < total_conversations
                ):
                    template_name = self.config.conversation_templates[
                        conversation_counter % len(self.config.conversation_templates)
                    ]
                    template = self.templates[template_name]

                    user_id = f"user-{conversation_counter:04d}"
                    conversation_counter += 1

                    task = asyncio.create_task(
                        self.run_single_conversation_azure(template, user_id, semaphore)
                    )
                    active_tasks.add(task)

                    # Log active users metric
                    self.log_azure_metric("active_users", len(active_tasks))

                # Clean up completed tasks
                completed_tasks = [t for t in active_tasks if t.done()]
                for task in completed_tasks:
                    active_tasks.remove(task)

                # Wait before next iteration
                await asyncio.sleep(delay_between_starts)

                # Progress logging every 30 seconds
                if int(elapsed_time) % 30 == 0 and elapsed_time > 0:
                    logger.info(
                        f"⏱️  Progress: {elapsed_time:.0f}s, Active: {len(active_tasks)}, "
                        f"Completed: {self.metrics.conversations_completed}, "
                        f"Failed: {self.metrics.conversations_failed}"
                    )

            # Wait for remaining conversations
            if active_tasks:
                logger.info(
                    f"⏳ Waiting for {len(active_tasks)} remaining conversations..."
                )
                await asyncio.gather(*active_tasks, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("🛑 Test interrupted by user")
            for task in active_tasks:
                task.cancel()

        except Exception as e:
            logger.error(f"❌ Test error: {e}")
            self.metrics.error_messages.append(f"Test error: {str(e)}")

        finally:
            self.metrics.end_time = datetime.utcnow()

            # Calculate final metrics
            duration_s = (
                self.metrics.end_time - self.metrics.start_time
            ).total_seconds()
            self.metrics.requests_per_second = self.metrics.total_requests / max(
                duration_s, 1
            )
            self.metrics.error_rate_percent = (
                self.metrics.failed_requests / max(self.metrics.total_requests, 1)
            ) * 100

            if self.metrics.response_times_ms:
                self.metrics.avg_conversation_duration_s = (
                    statistics.mean(self.metrics.response_times_ms) / 1000
                )

        # Log final metrics
        self.log_azure_metric(
            "test_completed",
            1,
            {
                "scenario": scenario_name,
                "total_requests": str(self.metrics.total_requests),
                "success_rate": str(
                    (
                        self.metrics.successful_requests
                        / max(self.metrics.total_requests, 1)
                    )
                    * 100
                ),
            },
        )

        return {
            "scenario": scenario_name,
            "config": scenario_config,
            "metrics": self.metrics,
            "summary": self.metrics.calculate_summary_stats(),
        }

    def export_azure_compatible_results(self, results: List[Dict[str, Any]]) -> str:
        """Export results in Azure Load Test compatible format."""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"azure_load_test_results_{timestamp}.json"

        # Prepare Azure-compatible results
        azure_results = {
            "test_metadata": {
                "test_id": self.config.azure_test_id,
                "timestamp": timestamp,
                "azure_resource_group": self.config.azure_resource_group,
                "azure_location": self.config.azure_location,
                "test_type": "comprehensive_conversation_load_test",
            },
            "configuration": {
                "max_concurrent_users": self.config.max_concurrent_users,
                "test_duration_minutes": self.config.test_duration_minutes,
                "target_rps": self.config.target_rps,
                "conversation_templates": self.config.conversation_templates,
                "ws_url": self.config.ws_url,
            },
            "scenarios": results,
            "aggregate_metrics": self._calculate_aggregate_metrics(results),
        }

        # Write to file
        output_path = Path("tests/load/results") / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(azure_results, f, indent=2, default=str)

        logger.info(f"💾 Azure Load Test results saved to: {output_path}")
        return str(output_path)

    def _calculate_aggregate_metrics(
        self, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate aggregate metrics across all scenarios."""

        total_requests = sum(
            r["summary"]["performance"]["total_requests"] for r in results
        )
        total_successful = sum(
            r["summary"]["performance"]["successful_requests"] for r in results
        )
        total_failed = sum(
            r["summary"]["performance"]["failed_requests"] for r in results
        )

        all_response_times = []
        all_agent_times = []

        for result in results:
            if "response_times_ms" in result["summary"]:
                # Note: In real implementation, you'd need access to raw data
                # This is a simplified version for the aggregate
                all_response_times.extend(
                    [result["summary"]["response_times_ms"]["mean"]]
                )

            if "agent_performance_ms" in result["summary"]:
                all_agent_times.extend(
                    [result["summary"]["agent_performance_ms"]["mean_response_time"]]
                )

        aggregate = {
            "overall_performance": {
                "total_requests": total_requests,
                "successful_requests": total_successful,
                "failed_requests": total_failed,
                "overall_success_rate_percent": (
                    total_successful / max(total_requests, 1)
                )
                * 100,
                "scenarios_run": len(results),
            }
        }

        if all_response_times:
            aggregate["response_time_summary"] = {
                "mean_across_scenarios": statistics.mean(all_response_times),
                "min_scenario_mean": min(all_response_times),
                "max_scenario_mean": max(all_response_times),
            }

        if all_agent_times:
            aggregate["agent_performance_summary"] = {
                "mean_response_time_ms": statistics.mean(all_agent_times),
                "best_scenario_ms": min(all_agent_times),
                "worst_scenario_ms": max(all_agent_times),
            }

        return aggregate


async def main():
    """Main entry point for Azure Load Test execution."""

    # Get configuration from environment variables (Azure Load Test standard)
    config = AzureLoadTestConfig(
        test_duration_minutes=int(os.environ.get("TEST_DURATION_MINUTES", "5")),
        ramp_up_duration_minutes=int(os.environ.get("RAMP_UP_DURATION_MINUTES", "1")),
        target_rps=float(os.environ.get("TARGET_RPS", "10.0")),
        max_concurrent_users=int(os.environ.get("MAX_CONCURRENT_USERS", "50")),
        ws_url=os.environ.get(
            "WEBSOCKET_URL", "ws://localhost:8010/api/v1/media/stream"
        ),
        azure_test_id=os.environ.get(
            "AZURE_TEST_ID", f"load-test-{uuid.uuid4().hex[:8]}"
        ),
        azure_resource_group=os.environ.get("AZURE_RESOURCE_GROUP", "load-test-rg"),
        azure_location=os.environ.get("AZURE_LOCATION", "eastus"),
    )

    # Determine scenarios to run
    scenarios_env = os.environ.get("TEST_SCENARIOS", "light,medium")
    scenarios = [s.strip() for s in scenarios_env.split(",")]

    logger.info(f"🚀 Starting Azure Load Test with scenarios: {scenarios}")
    logger.info(f"🎯 Configuration: {config.__dict__}")

    # Create tester
    tester = AzureConversationLoadTester(config)

    # Run scenarios
    results = []
    for i, scenario in enumerate(scenarios):
        try:
            logger.info(
                f"\n🔄 Running scenario {i+1}/{len(scenarios)}: {scenario.upper()}"
            )
            result = await tester.run_azure_load_test_scenario(scenario)
            results.append(result)

            # Brief pause between scenarios (except the last)
            if i < len(scenarios) - 1:
                pause_time = 30
                logger.info(f"⏸️  Pausing {pause_time}s before next scenario...")
                await asyncio.sleep(pause_time)

        except Exception as e:
            logger.error(f"❌ Scenario {scenario} failed: {e}")
            results.append(
                {
                    "scenario": scenario,
                    "error": str(e),
                    "summary": {
                        "performance": {
                            "total_requests": 0,
                            "successful_requests": 0,
                            "failed_requests": 1,
                        }
                    },
                }
            )

    # Export results
    results_file = tester.export_azure_compatible_results(results)

    # Print summary
    print(f"\n🎉 Azure Load Test completed!")
    print(
        f"📊 Scenarios completed: {len([r for r in results if 'error' not in r])}/{len(scenarios)}"
    )
    print(f"💾 Results saved to: {results_file}")

    # Log final summary for Azure ingestion
    total_requests = sum(
        r.get("summary", {}).get("performance", {}).get("total_requests", 0)
        for r in results
    )
    total_success = sum(
        r.get("summary", {}).get("performance", {}).get("successful_requests", 0)
        for r in results
    )

    logger.info(
        f"AZURE_SUMMARY: Total requests: {total_requests}, Successful: {total_success}, Success rate: {(total_success/max(total_requests,1))*100:.1f}%"
    )


if __name__ == "__main__":
    asyncio.run(main())
