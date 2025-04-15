import logging
from datetime import datetime
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
        'conversation.item.created': lambda self, event: self._process_item_created(event),
        'conversation.item.truncated': lambda self, event: self._process_item_truncated(event),
        'conversation.item.deleted': lambda self, event: self._process_item_deleted(event),
        'conversation.item.input_audio_transcription.completed': lambda self, event: self._process_input_audio_transcription_completed(event),
        'input_audio_buffer.speech_started': lambda self, event: self._process_speech_started(event),
        'input_audio_buffer.speech_stopped': lambda self, event, input_audio_buffer: self._process_speech_stopped(event, input_audio_buffer),
        'response.created': lambda self, event: self._process_response_created(event),
        'response.output_item.added': lambda self, event: self._process_output_item_added(event),
        'response.output_item.done': lambda self, event: self._process_output_item_done(event),
        'response.content_part.added': lambda self, event: self._process_content_part_added(event),
        'response.audio_transcript.delta': lambda self, event: self._process_audio_transcript_delta(event),
        'response.audio.delta': lambda self, event: self._process_audio_delta(event),
        'response.text.delta': lambda self, event: self._process_text_delta(event),
        'response.function_call_arguments.delta': lambda self, event: self._process_function_call_arguments_delta(event),
    }

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        """Reset all internal state for a new conversation."""
        self.item_lookup: Dict[str, dict] = {}
        self.items: List[dict] = []
        self.response_lookup: Dict[str, dict] = {}
        self.responses: List[dict] = []
        self.queued_speech_items: Dict[str, dict] = {}
        self.queued_transcript_items: Dict[str, dict] = {}
        self.queued_input_audio: Optional[bytes] = None

    def queue_input_audio(self, input_audio: bytes) -> None:
        self.queued_input_audio = input_audio

    def process_event(self, event: dict, *args: Optional[np.ndarray]) -> Tuple[Optional[dict], Optional[dict]]:
        """Process an incoming Realtime event."""
        processor = self.EventProcessors.get(event['type'])
        if not processor:
            raise Exception(f"Missing processor for event type: {event['type']}")
        return processor(self, event, *args)

    def get_item(self, item_id: str) -> Optional[dict]:
        return self.item_lookup.get(item_id)

    def get_items(self) -> List[dict]:
        return self.items.copy()

    def _process_item_created(self, event: dict) -> Tuple[Optional[dict], None]:
        item = event['item']
        item_copy = item.copy()

        if item_copy['id'] not in self.item_lookup:
            self.item_lookup[item_copy['id']] = item_copy
            self.items.append(item_copy)

        item_copy['formatted'] = {'audio': bytearray(), 'text': '', 'transcript': ''}

        # Attach any queued speech or transcript
        if item_copy['id'] in self.queued_speech_items:
            item_copy['formatted']['audio'] = self.queued_speech_items.pop(item_copy['id'])['audio']

        if 'content' in item_copy:
            for c in item_copy['content']:
                if c.get('type') in ['text', 'input_text']:
                    item_copy['formatted']['text'] += c.get('text', '')

        if item_copy['id'] in self.queued_transcript_items:
            item_copy['formatted']['transcript'] = self.queued_transcript_items.pop(item_copy['id'])['transcript']

        # Set status
        if item_copy['type'] == 'message':
            if item_copy.get('role') == 'user':
                item_copy['status'] = 'completed'
                if self.queued_input_audio:
                    item_copy['formatted']['audio'] = self.queued_input_audio
                    self.queued_input_audio = None
            else:
                item_copy['status'] = 'in_progress'
        elif item_copy['type'] == 'function_call':
            item_copy['formatted']['tool'] = {
                'type': 'function',
                'name': item_copy.get('name', ''),
                'call_id': item_copy.get('call_id', ''),
                'arguments': ''
            }
            item_copy['status'] = 'in_progress'
        elif item_copy['type'] == 'function_call_output':
            item_copy['status'] = 'completed'
            item_copy['formatted']['output'] = item_copy.get('output', '')

        return item_copy, None

    def _process_item_truncated(self, event: dict) -> Tuple[Optional[dict], None]:
        item_id = event['item_id']
        audio_end_ms = event['audio_end_ms']

        item = self.item_lookup.get(item_id)
        if not item:
            raise Exception(f"Truncated: Item '{item_id}' not found")

        end_index = (audio_end_ms * self.default_frequency) // 1000
        item['formatted']['audio'] = item['formatted']['audio'][:end_index]
        item['formatted']['transcript'] = ''

        return item, None

    def _process_item_deleted(self, event: dict) -> Tuple[Optional[dict], None]:
        item_id = event['item_id']
        item = self.item_lookup.pop(item_id, None)
        if item:
            self.items = [i for i in self.items if i['id'] != item_id]
        return item, None

    def _process_input_audio_transcription_completed(self, event: dict) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event['item_id']
        content_index = event['content_index']
        transcript = event.get('transcript', ' ')

        item = self.item_lookup.get(item_id)
        if not item:
            self.queued_transcript_items[item_id] = {'transcript': transcript}
            return None, None

        item['content'][content_index]['transcript'] = transcript
        item['formatted']['transcript'] = transcript

        return item, {'transcript': transcript}

    def _process_speech_started(self, event: dict) -> Tuple[None, None]:
        item_id = event['item_id']
        self.queued_speech_items[item_id] = {'audio_start_ms': event['audio_start_ms']}
        return None, None

    def _process_speech_stopped(self, event: dict, input_audio_buffer: Optional[np.ndarray]) -> Tuple[None, None]:
        item_id = event['item_id']
        audio_end_ms = event['audio_end_ms']

        speech = self.queued_speech_items.get(item_id)
        if not speech:
            return None, None

        speech['audio_end_ms'] = audio_end_ms

        if input_audio_buffer is not None:
            start_idx = (speech['audio_start_ms'] * self.default_frequency) // 1000
            end_idx = (audio_end_ms * self.default_frequency) // 1000
            speech['audio'] = input_audio_buffer[start_idx:end_idx]

        return None, None

    def _process_response_created(self, event: dict) -> Tuple[None, None]:
        response = event['response']
        if response['id'] not in self.response_lookup:
            self.response_lookup[response['id']] = response
            self.responses.append(response)
        return None, None

    def _process_output_item_added(self, event: dict) -> Tuple[None, None]:
        response_id = event['response_id']
        item = event['item']

        response = self.response_lookup.get(response_id)
        if response:
            response.setdefault('output', []).append(item['id'])

        return None, None

    def _process_output_item_done(self, event: dict) -> Tuple[Optional[dict], None]:
        item = event.get('item')
        if not item:
            raise Exception("output_item.done: Missing item.")

        found_item = self.item_lookup.get(item['id'])
        if found_item:
            found_item['status'] = item['status']

        return found_item, None

    def _process_content_part_added(self, event: dict) -> Tuple[Optional[dict], None]:
        item_id = event['item_id']
        part = event['part']

        item = self.item_lookup.get(item_id)
        if item:
            item.setdefault('content', []).append(part)

        return item, None

    def _process_audio_transcript_delta(self, event: dict) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event['item_id']
        content_index = event['content_index']
        delta = event['delta']

        item = self.item_lookup.get(item_id)
        if item:
            item['content'][content_index]['transcript'] += delta
            item['formatted']['transcript'] += delta

        return item, {'transcript': delta}

    def _process_audio_delta(self, event: dict) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event['item_id']
        delta = event['delta']

        item = self.item_lookup.get(item_id)
        if not item:
            return None, None

        audio_data = base64_to_array_buffer(delta).tobytes()
        item['formatted']['audio'] += audio_data

        return item, {'audio': audio_data}

    def _process_text_delta(self, event: dict) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event['item_id']
        content_index = event['content_index']
        delta = event['delta']

        item = self.item_lookup.get(item_id)
        if item:
            item['content'][content_index]['text'] += delta
            item['formatted']['text'] += delta

        return item, {'text': delta}

    def _process_function_call_arguments_delta(self, event: dict) -> Tuple[Optional[dict], Optional[dict]]:
        item_id = event['item_id']
        delta = event['delta']

        item = self.item_lookup.get(item_id)
        if not item:
            return None, None

        if 'arguments' not in item:
            item['arguments'] = ''

        item['arguments'] += delta

        if 'formatted' not in item or 'tool' not in item['formatted']:
            item['formatted']['tool'] = {'arguments': ''}

        item['formatted']['tool']['arguments'] += delta

        return item, {'arguments': delta}
