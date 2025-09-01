#!/usr/bin/env python3
"""
Conversation Manifest for Load Testing
=====================================

Provides structured access to pre-generated PCM audio files and conversation flows
for orchestrating test scenarios across multiple Python test modules.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple
from dataclasses import dataclass, asdict


@dataclass
class ConversationTurn:
    """Represents a single turn in a conversation."""

    text: str
    audio_file: str
    duration_seconds: float
    turn_type: str = "user"  # "user" or "system"
    metadata: Optional[Dict] = None


@dataclass
class ConversationFlow:
    """Represents a complete conversation flow."""

    name: str
    description: str
    turns: List[ConversationTurn]
    total_duration: float
    category: str = "general"


class ConversationManifest:
    """Manages conversation flows and their associated audio files."""

    def __init__(self, cache_dir: str = "tests/load/audio_cache"):
        """Initialize with the audio cache directory."""
        self.cache_dir = Path(cache_dir)
        self.manifest_file = self.cache_dir / "conversation_manifest.json"
        self.flows: Dict[str, ConversationFlow] = {}

        # Load existing manifest if available
        self._load_manifest()

    def _get_cache_filename(
        self, text: str, voice: str = "en-US-JennyMultilingualNeural"
    ) -> str:
        """Generate cache filename matching audio_generator.py logic."""
        content_hash = hashlib.md5(f"{text}|{voice}".encode()).hexdigest()
        return f"audio_{content_hash}.pcm"

    def _calculate_duration(self, audio_file: Path) -> float:
        """Calculate audio duration from PCM file size (16kHz, 16-bit)."""
        if not audio_file.exists():
            return 0.0
        file_size = audio_file.stat().st_size
        # 16kHz sample rate, 16-bit (2 bytes) per sample
        return file_size / (16000 * 2)

    def add_conversation_flow(
        self,
        name: str,
        description: str,
        texts: List[str],
        category: str = "general",
        voice: str = "en-US-JennyMultilingualNeural",
    ) -> ConversationFlow:
        """
        Add a conversation flow to the manifest.

        Args:
            name: Unique identifier for the conversation flow
            description: Human-readable description
            texts: List of text strings that should have corresponding audio files
            category: Category for organizing flows (e.g., "insurance", "travel", "support")
            voice: Voice used for audio generation

        Returns:
            ConversationFlow object
        """
        turns = []
        total_duration = 0.0

        for i, text in enumerate(texts):
            audio_filename = self._get_cache_filename(text, voice)
            audio_file = self.cache_dir / audio_filename
            duration = self._calculate_duration(audio_file)

            turn = ConversationTurn(
                text=text,
                audio_file=audio_filename,
                duration_seconds=duration,
                turn_type="user",
                metadata={
                    "turn_index": i,
                    "voice": voice,
                    "exists": audio_file.exists(),
                },
            )

            turns.append(turn)
            total_duration += duration

        flow = ConversationFlow(
            name=name,
            description=description,
            turns=turns,
            total_duration=total_duration,
            category=category,
        )

        self.flows[name] = flow
        self._save_manifest()

        return flow

    def get_flow(self, name: str) -> Optional[ConversationFlow]:
        """Get a conversation flow by name."""
        return self.flows.get(name)

    def get_flows_by_category(self, category: str) -> List[ConversationFlow]:
        """Get all flows in a specific category."""
        return [flow for flow in self.flows.values() if flow.category == category]

    def get_all_flows(self) -> List[ConversationFlow]:
        """Get all conversation flows."""
        return list(self.flows.values())

    def get_audio_path(self, flow_name: str, turn_index: int) -> Optional[Path]:
        """Get the full path to an audio file for a specific turn."""
        flow = self.get_flow(flow_name)
        if not flow or turn_index >= len(flow.turns):
            return None

        return self.cache_dir / flow.turns[turn_index].audio_file

    def validate_audio_files(self, flow_name: str = None) -> Dict[str, bool]:
        """
        Validate that all audio files exist for a flow or all flows.

        Args:
            flow_name: Optional specific flow to validate

        Returns:
            Dictionary mapping flow_name to validation status
        """
        flows_to_check = [flow_name] if flow_name else list(self.flows.keys())
        results = {}

        for name in flows_to_check:
            flow = self.flows.get(name)
            if not flow:
                results[name] = False
                continue

            all_exist = True
            for turn in flow.turns:
                audio_path = self.cache_dir / turn.audio_file
                if not audio_path.exists():
                    all_exist = False
                    break

            results[name] = all_exist

        return results

    def _load_manifest(self):
        """Load manifest from JSON file."""
        if not self.manifest_file.exists():
            return

        try:
            with open(self.manifest_file, "r") as f:
                data = json.load(f)

            for flow_name, flow_data in data.get("flows", {}).items():
                turns = [
                    ConversationTurn(**turn_data) for turn_data in flow_data["turns"]
                ]

                flow = ConversationFlow(
                    name=flow_data["name"],
                    description=flow_data["description"],
                    turns=turns,
                    total_duration=flow_data["total_duration"],
                    category=flow_data.get("category", "general"),
                )

                self.flows[flow_name] = flow

        except Exception as e:
            print(f"Warning: Could not load manifest: {e}")

    def _save_manifest(self):
        """Save manifest to JSON file."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "1.0",
            "cache_directory": str(self.cache_dir),
            "flows": {name: asdict(flow) for name, flow in self.flows.items()},
        }

        with open(self.manifest_file, "w") as f:
            json.dump(data, f, indent=2)

    def export_for_tests(self) -> Dict:
        """Export manifest data in a format optimized for test consumption."""
        return {
            "flows": {
                name: {
                    "description": flow.description,
                    "category": flow.category,
                    "total_duration": flow.total_duration,
                    "turns": [
                        {
                            "text": turn.text,
                            "audio_path": str(self.cache_dir / turn.audio_file),
                            "duration": turn.duration_seconds,
                            "exists": (self.cache_dir / turn.audio_file).exists(),
                        }
                        for turn in flow.turns
                    ],
                }
                for name, flow in self.flows.items()
            },
            "categories": list(set(flow.category for flow in self.flows.values())),
            "total_flows": len(self.flows),
        }


# Predefined conversation flows based on the test_texts from audio_generator.py
DEFAULT_FLOWS = {
    "insurance_inquiry": {
        "description": "Customer service conversation about car insurance policy",
        "texts": [
            "Hello, my name is Alice Brown, my social is 1234, and my zip code is 60610",
            "Actually, I need help with my car insurance.",
            "What does my policy cover?",
            "Thank you for the information.",
        ],
        "category": "insurance",
    },
    "travel_inquiry": {
        "description": "Customer asking for travel information about Madrid",
        "texts": [
            "Hello, my name is Alice Brown, my social is 1234, and my zip code is 60610",
            "I'm looking to learn about Madrid. Please provide in 100 words",
            "Thank you for the information.",
        ],
        "category": "travel",
    },
    "mixed_conversation": {
        "description": "Conversation that starts with travel but switches to insurance",
        "texts": [
            "Hello, my name is Alice Brown, my social is 1234, and my zip code is 60610",
            "I'm looking to learn about Madrid. Please provide in 100 words",
            "Actually, I need help with my car insurance.",
            "What does my policy cover?",
            "Thank you for the information.",
        ],
        "category": "mixed",
    },
}


def initialize_default_flows(
    cache_dir: str = "tests/load/audio_cache",
) -> ConversationManifest:
    """Initialize manifest with default conversation flows."""
    manifest = ConversationManifest(cache_dir)

    for flow_name, flow_config in DEFAULT_FLOWS.items():
        manifest.add_conversation_flow(
            name=flow_name,
            description=flow_config["description"],
            texts=flow_config["texts"],
            category=flow_config["category"],
        )

    return manifest


def main():
    """Test the conversation manifest functionality."""
    print("🗂️ Testing Conversation Manifest...")

    # Initialize with default flows
    manifest = initialize_default_flows()

    # Show all flows
    print(f"\n📋 Available Flows ({len(manifest.flows)}):")
    for flow in manifest.get_all_flows():
        print(f"  • {flow.name}: {flow.description} ({flow.category})")
        print(f"    Turns: {len(flow.turns)}, Duration: {flow.total_duration:.2f}s")

    # Validate audio files
    print(f"\n🔍 Validating Audio Files:")
    validation_results = manifest.validate_audio_files()
    for flow_name, is_valid in validation_results.items():
        status = "✅" if is_valid else "❌"
        print(f"  {status} {flow_name}")

    # Export for tests
    test_data = manifest.export_for_tests()
    print(f"\n📤 Test Export Ready:")
    print(f"  Categories: {', '.join(test_data['categories'])}")
    print(f"  Total Flows: {test_data['total_flows']}")

    print(f"\n✅ Manifest saved to: {manifest.manifest_file}")


if __name__ == "__main__":
    main()
