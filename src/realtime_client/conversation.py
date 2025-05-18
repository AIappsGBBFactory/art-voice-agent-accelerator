# conversation.py RealtimeConversation class for managing conversation state and events

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.realtime_client.utils import base64_to_array_buffer

logger = logging.getLogger(__name__)


class RealtimeConversation:
    """
    In-memory store for conversation history and audio buffers.
    Handles event-driven updates based on Realtime API events.
    """

    default_frequency: int = 44100  # Default sample rate (Hz)

    EventProcessors = {
        "conversation.item.created": lambda self, event: self._process_item_created(
            event
        ),
        "conversation.item.truncated": lambda self, event: self._process_item_truncated(
            event
        ),
        "conversation.item.deleted": lambda self, event: self._process_item_deleted(
            event
        ),
        "conversation.item.input_audio_transcription.completed": lambda self, event: self._process_input_audio_transcription_completed(
            event
        ),
        "input_audio_buffer.speech_started": lambda self, event: self._process_speech_started(
            event
        ),
        "input_audio_buffer.speech_stopped": lambda self, event, input_audio_buffer: self._process_speech_stopped(
            event, input_audio_buffer
        ),
        "response.created": lambda self, event: self._process_response_created(event),
        "response.output_item.added": lambda self, event: self._process_output_item_added(
            event
        ),
        "response.output_item.done": lambda self, event: self._process_output_item_done(
            event
        ),
        "response.content_part.added": lambda self, event: self._process_content_part_added(
            event
        ),
        "response.audio_transcript.delta": lambda self, event: self._process_audio_transcript_delta(
            event
        ),
        "response.audio.delta": lambda self, event: self._process_audio_delta(event),
        "response.text.delta": lambda self, event: self._process_text_delta(event),
        "response.function_call_arguments.delta": lambda self, event: self._process_function_call_arguments_delta(
            event
        ),
    }

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        """
        Reset all internal state for a new conversation.
        """
        self.item_lookup: Dict[str, dict] = {}
        self.items: List[dict] = []
        self.response_lookup: Dict[str, dict] = {}
        self.responses: List[dict] = []
        self.queued_speech_items: Dict[str, dict] = {}
        self.queued_transcript_items: Dict[str, dict] = {}
        self.queued_input_audio: Optional[bytes] = None

    def queue_input_audio(self, input_audio: bytes) -> None:
        """
        Queue input audio for later association with a message.
        """
        self.queued_input_audio = input_audio

    def process_event(
        self, event: dict, *args: Optional[np.ndarray]
    ) -> Tuple[Optional[dict], Optional[dict]]:
        """
        Process an incoming Realtime event.
        """
        event_processor = self.EventProcessors.get(event["type"])
        if not event_processor:
            raise Exception(f"Missing conversation event processor for {event['type']}")
        return event_processor(self, event, *args)

    def get_item(self, item_id: str) -> Optional[dict]:
        return self.item_lookup.get(item_id)

    def get_items(self) -> List[dict]:
        return self.items[:]

    def _process_item_created(self, event: dict) -> Tuple[Optional[dict], None]:
        item = event["item"]
        new_item = item.copy()

        if new_item["id"] not in self.item_lookup:
            self.item_lookup[new_item["id"]] = new_item
            self.items.append(new_item)

        new_item["formatted"] = {
            "audio": bytearray(),  # Use bytearray for audio streaming
            "text": "",
            "transcript": "",
        }

        if new_item["id"] in self.queued_speech_items:
            new_item["formatted"]["audio"] = self.queued_speech_items[new_item["id"]][
                "audio"
            ]
            del self.queued_speech_items[new_item["id"]]

        if "content" in new_item:
            for content in new_item["content"]:
                if content["type"] in ["text", "input_text"]:
                    new_item["formatted"]["text"] += content.get("text", "")

        if new_item["id"] in self.queued_transcript_items:
            new_item["formatted"]["transcript"] = self.queued_transcript_items[
                new_item["id"]
            ]["transcript"]
            del self.queued_transcript_items[new_item["id"]]

        if new_item["type"] == "message":
            if new_item["role"] == "user":
                new_item["status"] = "completed"
                if self.queued_input_audio:
                    new_item["formatted"]["audio"] = self.queued_input_audio
                    self.queued_input_audio = None
            else:
                new_item["status"] = "in_progress"
        elif new_item["type"] == "function_call":
            new_item["formatted"]["tool"] = {
                "type": "function",
                "name": new_item.get("name"),
                "call_id": new_item.get("call_id"),
                "arguments": "",
            }
            new_item["status"] = "in_progress"
        elif new_item["type"] == "function_call_output":
            new_item["status"] = "completed"
            new_item["formatted"]["output"] = new_item.get("output")

        return new_item, None

    def _process_item_truncated(self, event: dict) -> Tuple[Optional[dict], None]:
        item_id = event["item_id"]
        audio_end_ms = event["audio_end_ms"]

        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'Item "{item_id}" not found for truncation.')

        end_index = (audio_end_ms * self.default_frequency) // 1000
        item["formatted"]["audio"] = item["formatted"]["audio"][:end_index]
        item["formatted"]["transcript"] = ""

        return item, None

    def _process_item_deleted(self, event: dict) -> Tuple[Optional[dict], None]:
        item_id = event["item_id"]
        item = self.item_lookup.pop(item_id, None)

        if not item:
            raise Exception(f'Item "{item_id}" not found for deletion.')

        self.items = [i for i in self.items if i["id"] != item_id]
        return item, None

    def _process_input_audio_transcription_completed(
        self, event: dict
    ) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event["item_id"]
        content_index = event["content_index"]
        transcript = event["transcript"] or " "

        item = self.item_lookup.get(item_id)
        if not item:
            self.queued_transcript_items[item_id] = {"transcript": transcript}
            return None, None

        item["content"][content_index]["transcript"] = transcript
        item["formatted"]["transcript"] = transcript

        return item, {"transcript": transcript}

    def _process_speech_started(self, event: dict) -> Tuple[None, None]:
        item_id = event["item_id"]
        self.queued_speech_items[item_id] = {"audio_start_ms": event["audio_start_ms"]}
        return None, None

    def _process_speech_stopped(
        self, event: dict, input_audio_buffer: Optional[np.ndarray]
    ) -> Tuple[None, None]:
        item_id = event["item_id"]
        audio_end_ms = event["audio_end_ms"]

        speech = self.queued_speech_items.get(item_id)
        if not speech:
            logger.warning(
                f"Speech stopped received but no matching speech started for item {item_id}"
            )
            return None, None

        speech["audio_end_ms"] = audio_end_ms

        if input_audio_buffer is not None:
            start_index = (speech["audio_start_ms"] * self.default_frequency) // 1000
            end_index = (audio_end_ms * self.default_frequency) // 1000
            speech["audio"] = input_audio_buffer[start_index:end_index]

        return None, None

    def _process_response_created(self, event: dict) -> Tuple[None, None]:
        response = event["response"]

        if response["id"] not in self.response_lookup:
            self.response_lookup[response["id"]] = response
            self.responses.append(response)

        return None, None

    def _process_output_item_added(self, event: dict) -> Tuple[None, None]:
        response_id = event["response_id"]
        item = event["item"]

        response = self.response_lookup.get(response_id)
        if not response:
            raise Exception(
                f'Response "{response_id}" not found for adding output item.'
            )

        response.setdefault("output", []).append(item["id"])
        return None, None

    def _process_output_item_done(self, event: dict) -> Tuple[Optional[dict], None]:
        item = event.get("item")

        if not item:
            raise Exception("Missing item in output_item.done event.")

        found_item = self.item_lookup.get(item["id"])
        if not found_item:
            raise Exception(f'Item "{item["id"]}" not found for output_item.done.')

        found_item["status"] = item["status"]
        return found_item, None

    def _process_content_part_added(self, event: dict) -> Tuple[Optional[dict], None]:
        item_id = event["item_id"]
        part = event["part"]

        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'Item "{item_id}" not found for content_part.added.')

        item.setdefault("content", []).append(part)
        return item, None

    def _process_audio_transcript_delta(
        self, event: dict
    ) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]

        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'Item "{item_id}" not found for audio_transcript.delta.')

        item["content"][content_index]["transcript"] += delta
        item["formatted"]["transcript"] += delta

        return item, {"transcript": delta}

    def _process_audio_delta(
        self, event: dict
    ) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event["item_id"]
        delta = event["delta"]

        item = self.item_lookup.get(item_id)
        if not item:
            logger.debug(
                f'Audio delta received for unknown item "{item_id}". Skipping.'
            )
            return None, None

        audio_data = base64_to_array_buffer(delta).tobytes()

        if not isinstance(item["formatted"].get("audio"), (bytearray, bytes)):
            item["formatted"]["audio"] = bytearray()

        item["formatted"]["audio"] += audio_data

        return item, {"audio": audio_data}

    def _process_text_delta(self, event: dict) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event["item_id"]
        content_index = event["content_index"]
        delta = event["delta"]

        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f'Item "{item_id}" not found for text.delta.')

        item["content"][content_index]["text"] += delta
        item["formatted"]["text"] += delta

        return item, {"text": delta}

    def _process_function_call_arguments_delta(
        self, event: dict
    ) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event["item_id"]
        delta = event["delta"]

        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(
                f'Item "{item_id}" not found for function_call_arguments.delta.'
            )

        if "arguments" not in item:
            item["arguments"] = ""

        if "formatted" not in item or "tool" not in item["formatted"]:
            item["formatted"]["tool"] = {"arguments": ""}

        item["arguments"] += delta
        item["formatted"]["tool"]["arguments"] += delta

        return item, {"arguments": delta}
