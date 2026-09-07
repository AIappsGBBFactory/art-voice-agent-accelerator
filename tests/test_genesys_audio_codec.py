from __future__ import annotations

import base64

import numpy as np
import pytest
from apps.artagent.backend.voice.genesys.audio_codec import (
    PCM16_24kToULaw8kStreamEncoder,
    ULaw8kToPCM16_24kStreamDecoder,
    convert_voicelive_delta_to_ulaw,
    pcm16_24khz_bytes_to_ulaw_8khz,
    ulaw_8khz_to_pcm16_24khz_b64,
    ulaw_decode,
    ulaw_encode,
)


def _partition_bytes(data: bytes, sizes: list[int]) -> list[bytes]:
    parts: list[bytes] = []
    offset = 0
    for size in sizes:
        if offset >= len(data):
            break
        parts.append(data[offset : offset + size])
        offset += size
    if offset < len(data):
        parts.append(data[offset:])
    return parts


def test_ulaw_reference_vector_round_trips_exactly() -> None:
    """Known µ-law reference points decode and re-encode predictably."""
    ulaw = bytes([0x00, 0x7F, 0xFF, 0x80])

    decoded = ulaw_decode(ulaw)

    assert decoded.tolist() == [-32124, 0, 0, 32124]
    assert ulaw_encode(decoded[[0, 2, 3]]) == bytes([0x00, 0xFF, 0x80])


def test_inbound_streaming_is_chunk_partition_invariant() -> None:
    ulaw = bytes(range(1, 96))
    expected = base64.b64decode(ulaw_8khz_to_pcm16_24khz_b64(ulaw))

    decoder = ULaw8kToPCM16_24kStreamDecoder()
    parts = _partition_bytes(ulaw, [1, 2, 7, 3, 11, 5, 4, 8])
    actual = b"".join(decoder.decode_chunk(part) for part in parts) + decoder.flush()

    assert actual == expected


def test_outbound_streaming_is_chunk_partition_invariant() -> None:
    samples = np.array(
        [0, 1200, -2400, 3600, -4800, 6000, -7200, 8400, -9600, 10800, -12000],
        dtype=np.int16,
    )
    raw = samples.tobytes()
    expected = pcm16_24khz_bytes_to_ulaw_8khz(raw)

    encoder = PCM16_24kToULaw8kStreamEncoder()
    parts = _partition_bytes(raw, [1, 5, 2, 7, 3, 1, 4])
    actual = b"".join(encoder.encode_chunk(part) for part in parts) + encoder.flush()

    assert actual == expected


def test_outbound_stream_preserves_partial_sample_byte_until_flush() -> None:
    encoder = PCM16_24kToULaw8kStreamEncoder()

    assert encoder.encode_chunk(b"\x01") == b""
    with pytest.raises(ValueError, match="incomplete sample byte pair"):
        encoder.flush()


def test_base64_delta_validation_is_strict() -> None:
    encoder = PCM16_24kToULaw8kStreamEncoder()

    with pytest.raises(ValueError, match="valid base64 PCM16"):
        encoder.encode_base64_chunk("%%%not-base64%%%")


def test_convert_voicelive_delta_rejects_unknown_types() -> None:
    with pytest.raises(TypeError, match="Unsupported VoiceLive audio delta type"):
        convert_voicelive_delta_to_ulaw(123)  # type: ignore[arg-type]
