#!/usr/bin/env python3
"""
Test Conversation Orchestrator
=============================

Example usage of the conversation manifest for orchestrating test scenarios.
Demonstrates how other Python tests can consume the manifest to coordinate
conversational turns with pre-generated PCM audio files.
"""

import pytest
import asyncio
from pathlib import Path
from typing import List, Dict, Any

from conversation_manifest import ConversationManifest, initialize_default_flows


class TestConversationOrchestrator:
    """Example test class showing how to orchestrate conversations using the manifest."""

    @classmethod
    def setup_class(cls):
        """Initialize the conversation manifest for all tests."""
        cls.manifest = initialize_default_flows()
        cls.test_data = cls.manifest.export_for_tests()

    def test_manifest_initialization(self):
        """Test that the manifest loads correctly."""
        assert len(self.manifest.flows) > 0
        assert "insurance_inquiry" in self.manifest.flows
        assert "travel_inquiry" in self.manifest.flows
        assert "mixed_conversation" in self.manifest.flows

    def test_flow_categories(self):
        """Test that flows are properly categorized."""
        insurance_flows = self.manifest.get_flows_by_category("insurance")
        travel_flows = self.manifest.get_flows_by_category("travel")
        mixed_flows = self.manifest.get_flows_by_category("mixed")

        assert len(insurance_flows) >= 1
        assert len(travel_flows) >= 1
        assert len(mixed_flows) >= 1

    def test_audio_file_mapping(self):
        """Test that audio files are properly mapped."""
        flow = self.manifest.get_flow("insurance_inquiry")
        assert flow is not None

        for i, turn in enumerate(flow.turns):
            audio_path = self.manifest.get_audio_path("insurance_inquiry", i)
            assert audio_path is not None
            assert audio_path.name.endswith(".pcm")

    def test_conversation_orchestration(self):
        """Demonstrate how to orchestrate a conversation using the manifest."""
        flow_name = "insurance_inquiry"
        conversation_steps = self._orchestrate_conversation(flow_name)

        assert len(conversation_steps) > 0

        # Each step should have the required fields for test orchestration
        for step in conversation_steps:
            assert "turn_index" in step
            assert "text" in step
            assert "audio_path" in step
            assert "duration" in step
            assert "audio_exists" in step

    def test_multi_flow_orchestration(self):
        """Test orchestrating multiple conversation flows."""
        flows_to_test = ["insurance_inquiry", "travel_inquiry"]

        all_conversations = []
        for flow_name in flows_to_test:
            steps = self._orchestrate_conversation(flow_name)
            all_conversations.append(
                {
                    "flow_name": flow_name,
                    "steps": steps,
                    "total_duration": sum(step["duration"] for step in steps),
                }
            )

        assert len(all_conversations) == 2

        # Validate that each conversation has different content
        texts_flow1 = {step["text"] for step in all_conversations[0]["steps"]}
        texts_flow2 = {step["text"] for step in all_conversations[1]["steps"]}
        assert (
            texts_flow1 != texts_flow2
        )  # Different conversations should have different content

    def test_load_test_scenario_generation(self):
        """Generate load test scenarios from the manifest."""
        scenarios = self._generate_load_test_scenarios()

        assert len(scenarios) > 0

        for scenario in scenarios:
            assert "name" in scenario
            assert "category" in scenario
            assert "turns" in scenario
            assert "expected_duration" in scenario
            assert "audio_files_ready" in scenario

    def _orchestrate_conversation(self, flow_name: str) -> List[Dict[str, Any]]:
        """
        Orchestrate a conversation flow for testing.

        Returns a list of conversation steps that can be used by load tests
        or integration tests to simulate user interactions.
        """
        flow = self.manifest.get_flow(flow_name)
        if not flow:
            return []

        conversation_steps = []

        for i, turn in enumerate(flow.turns):
            audio_path = self.manifest.get_audio_path(flow_name, i)

            step = {
                "turn_index": i,
                "text": turn.text,
                "audio_path": str(audio_path) if audio_path else None,
                "duration": turn.duration_seconds,
                "audio_exists": audio_path.exists() if audio_path else False,
                "metadata": turn.metadata or {},
            }

            conversation_steps.append(step)

        return conversation_steps

    def _generate_load_test_scenarios(self) -> List[Dict[str, Any]]:
        """Generate load test scenarios from all available flows."""
        scenarios = []

        for flow_name, flow in self.manifest.flows.items():
            # Check if all audio files are ready
            validation_result = self.manifest.validate_audio_files(flow_name)
            audio_files_ready = validation_result.get(flow_name, False)

            scenario = {
                "name": flow_name,
                "description": flow.description,
                "category": flow.category,
                "turns": len(flow.turns),
                "expected_duration": flow.total_duration,
                "audio_files_ready": audio_files_ready,
                "conversation_steps": self._orchestrate_conversation(flow_name),
            }

            scenarios.append(scenario)

        return scenarios


class LoadTestSimulator:
    """Example class showing how to use the manifest for load testing simulation."""

    def __init__(self, manifest: ConversationManifest):
        self.manifest = manifest

    async def simulate_conversation(
        self, flow_name: str, delay_between_turns: float = 1.0
    ):
        """
        Simulate a conversation with realistic timing.

        Args:
            flow_name: Name of the conversation flow to simulate
            delay_between_turns: Seconds to wait between conversation turns
        """
        flow = self.manifest.get_flow(flow_name)
        if not flow:
            raise ValueError(f"Flow '{flow_name}' not found")

        print(f"🎬 Starting conversation simulation: {flow_name}")
        print(f"📝 Description: {flow.description}")
        print(f"🏷️ Category: {flow.category}")
        print(f"⏱️ Expected duration: {flow.total_duration:.2f}s")

        for i, turn in enumerate(flow.turns):
            print(f"\n🗣️ Turn {i+1}/{len(flow.turns)}: {turn.text}")

            # Get audio file path
            audio_path = self.manifest.get_audio_path(flow_name, i)

            if audio_path and audio_path.exists():
                print(f"🎵 Audio file: {audio_path.name} ({turn.duration_seconds:.2f}s)")

                # In a real load test, this would stream the audio data
                # to the voice agent endpoint
                await self._simulate_audio_streaming(audio_path, turn.duration_seconds)

            else:
                print(f"⚠️ Audio file not found: {turn.audio_file}")

            # Wait before next turn (except for the last turn)
            if i < len(flow.turns) - 1:
                await asyncio.sleep(delay_between_turns)

        print(f"\n✅ Conversation simulation completed: {flow_name}")

    async def _simulate_audio_streaming(self, audio_path: Path, duration: float):
        """Simulate streaming audio data (placeholder for actual implementation)."""
        # In a real implementation, this would:
        # 1. Read the PCM audio file
        # 2. Stream it to the voice agent endpoint
        # 3. Handle responses and maintain conversation state

        # For now, just simulate the time it takes to "play" the audio
        await asyncio.sleep(min(duration, 0.5))  # Cap simulation time for testing


def main():
    """Demonstrate the conversation orchestrator functionality."""
    print("🎭 Testing Conversation Orchestrator...")

    # Initialize manifest
    manifest = initialize_default_flows()

    # Create test orchestrator
    orchestrator = TestConversationOrchestrator()
    orchestrator.setup_class()

    # Run some example tests
    print("\n🧪 Running orchestration tests...")
    orchestrator.test_manifest_initialization()
    orchestrator.test_conversation_orchestration()

    # Generate load test scenarios
    scenarios = orchestrator._generate_load_test_scenarios()
    print(f"\n📊 Generated {len(scenarios)} load test scenarios:")

    for scenario in scenarios:
        status = "✅" if scenario["audio_files_ready"] else "❌"
        print(
            f"  {status} {scenario['name']}: {scenario['turns']} turns, {scenario['expected_duration']:.2f}s"
        )

    # Demonstrate conversation simulation
    print(f"\n🎬 Demonstrating conversation simulation...")
    simulator = LoadTestSimulator(manifest)

    # Run a quick simulation (synchronously for demo)
    import asyncio

    asyncio.run(
        simulator.simulate_conversation("insurance_inquiry", delay_between_turns=0.1)
    )

    print(f"\n✅ Orchestrator demonstration complete!")


if __name__ == "__main__":
    main()
