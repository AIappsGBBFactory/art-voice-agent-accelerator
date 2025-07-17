from enum import Enum


class StreamMode(Enum):
    """Enumeration for different audio streaming modes in the voice agent system"""

    MEDIA = "media"  # Direct Bi-directional media PCM audio streaming to ACS WebSocket
    TRANSCRIPTION = (
        "transcription"  # ACS <-> Azure AI Speech realtime transcription streaming
    )
    REALTIME = "realtime"  # Real-time WebRTC streaming for browser clients

    def __str__(self) -> str:
        """Return the string value for easy comparison"""
        return self.value

    @classmethod
    def from_string(cls, value: str) -> "StreamMode":
        """Create StreamMode from string with validation"""
        for mode in cls:
            if mode.value == value:
                return mode
        raise ValueError(
            f"Invalid stream mode: {value}. Valid options: {[m.value for m in cls]}"
        )

    @property
    def is_audio_streaming(self) -> bool:
        """Check if this mode involves direct audio streaming"""
        return self in [StreamMode.MEDIA, StreamMode.REALTIME]

    @property
    def is_acs_compatible(self) -> bool:
        """Check if this mode is compatible with Azure Communication Services"""
        return self in [StreamMode.MEDIA, StreamMode.TRANSCRIPTION]
