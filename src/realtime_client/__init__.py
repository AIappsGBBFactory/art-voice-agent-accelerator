"""
Realtime Client Package

Provides classes and utilities for:
- Realtime audio and text interactions
- Audio encoding/decoding
- WebSocket API management
- Conversation tracking
- Event dispatching and handling
"""

from .api import RealtimeAPI
from .client import RealtimeClient
from .conversation import RealtimeConversation
from .event_handler import RealtimeEventHandler
from .utils import (
    array_buffer_to_base64,
    base64_to_array_buffer,
    float_to_16bit_pcm,
    merge_int16_arrays,
)

__all__ = [
    "RealtimeClient",
    "RealtimeAPI",
    "RealtimeConversation",
    "RealtimeEventHandler",
    "float_to_16bit_pcm",
    "base64_to_array_buffer",
    "array_buffer_to_base64",
    "merge_int16_arrays",
]

# Optional: versioning (future-proofing)
# __version__ = "0.1.0"
