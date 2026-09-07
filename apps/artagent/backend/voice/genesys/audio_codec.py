"""
Audio codec helpers for the Genesys AudioHook bridge.

Genesys AudioHook uses 8 kHz µ-law audio on the wire. VoiceLive audio deltas are
PCM16 at 24 kHz. The bridge therefore needs streaming-safe conversion in both
directions:

* Inbound: µ-law 8 kHz -> PCM16 24 kHz -> base64 for VoiceLive
* Outbound: PCM16 24 kHz -> µ-law 8 kHz for Genesys

The converters below retain enough residual state to make results invariant to
how input is chunked across frames. That is important for realtime streaming,
where arbitrary transport chunking must not change the produced audio.
"""

from __future__ import annotations

import base64

import numpy as np

# µ-law decode table (µ-law byte -> 16-bit PCM sample).
_ULAW_DECODE_TABLE = np.array(
    [
        -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956,
        -23932, -22908, -21884, -20860, -19836, -18812, -17788, -16764,
        -15996, -15484, -14972, -14460, -13948, -13436, -12924, -12412,
        -11900, -11388, -10876, -10364, -9852, -9340, -8828, -8316,
        -7932, -7676, -7420, -7164, -6908, -6652, -6396, -6140,
        -5884, -5628, -5372, -5116, -4860, -4604, -4348, -4092,
        -3900, -3772, -3644, -3516, -3388, -3260, -3132, -3004,
        -2876, -2748, -2620, -2492, -2364, -2236, -2108, -1980,
        -1884, -1820, -1756, -1692, -1628, -1564, -1500, -1436,
        -1372, -1308, -1244, -1180, -1116, -1052, -988, -924,
        -876, -844, -812, -780, -748, -716, -684, -652,
        -620, -588, -556, -524, -492, -460, -428, -396,
        -372, -356, -340, -324, -308, -292, -276, -260,
        -244, -228, -212, -196, -180, -164, -148, -132,
        -120, -112, -104, -96, -88, -80, -72, -64,
        -56, -48, -40, -32, -24, -16, -8, 0,
        32124, 31100, 30076, 29052, 28028, 27004, 25980, 24956,
        23932, 22908, 21884, 20860, 19836, 18812, 17788, 16764,
        15996, 15484, 14972, 14460, 13948, 13436, 12924, 12412,
        11900, 11388, 10876, 10364, 9852, 9340, 8828, 8316,
        7932, 7676, 7420, 7164, 6908, 6652, 6396, 6140,
        5884, 5628, 5372, 5116, 4860, 4604, 4348, 4092,
        3900, 3772, 3644, 3516, 3388, 3260, 3132, 3004,
        2876, 2748, 2620, 2492, 2364, 2236, 2108, 1980,
        1884, 1820, 1756, 1692, 1628, 1564, 1500, 1436,
        1372, 1308, 1244, 1180, 1116, 1052, 988, 924,
        876, 844, 812, 780, 748, 716, 684, 652,
        620, 588, 556, 524, 492, 460, 428, 396,
        372, 356, 340, 324, 308, 292, 276, 260,
        244, 228, 212, 196, 180, 164, 148, 132,
        120, 112, 104, 96, 88, 80, 72, 64,
        56, 48, 40, 32, 24, 16, 8, 0,
    ],
    dtype=np.int16,
)

# µ-law encode exponent lookup.
_ULAW_ENCODE_TABLE = np.array(
    [
        0, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3,
        4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
        5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
        7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    ],
    dtype=np.uint8,
)

_ULAW_BIAS = 0x84
_ULAW_CLIP = 32635


def ulaw_decode(ulaw_bytes: bytes) -> np.ndarray:
    """Decode µ-law bytes to 8 kHz PCM16 samples."""
    if not ulaw_bytes:
        return np.array([], dtype=np.int16)
    indices = np.frombuffer(ulaw_bytes, dtype=np.uint8)
    return _ULAW_DECODE_TABLE[indices]


def ulaw_encode(pcm16_samples: np.ndarray) -> bytes:
    """Encode PCM16 samples to µ-law bytes."""
    if pcm16_samples.size == 0:
        return b""
    samples = pcm16_samples.astype(np.int32)
    sign = (samples >> 8) & 0x80
    samples = np.where(sign.astype(bool), -samples, samples)
    samples = np.clip(samples, 0, _ULAW_CLIP)
    samples = samples + _ULAW_BIAS
    exponent = _ULAW_ENCODE_TABLE[(samples >> 7) & 0xFF]
    mantissa = (samples >> (exponent.astype(np.int32) + 3)) & 0x0F
    ulaw = ~(sign | (exponent.astype(np.int32) << 4) | mantissa) & 0xFF
    return ulaw.astype(np.uint8).tobytes()


class StreamingUpsampler3x:
    """Streaming-safe 8 kHz -> 24 kHz cubic upsampler."""

    def __init__(self) -> None:
        self._pending = np.array([], dtype=np.int16)
        self._previous_sample: int | None = None

    def process(self, pcm_8khz: np.ndarray) -> np.ndarray:
        """Process another chunk and emit all now-stable 24 kHz output."""
        if pcm_8khz.size:
            self._pending = np.concatenate((self._pending, pcm_8khz.astype(np.int16, copy=False)))
        return self._emit(final=False)

    def flush(self) -> np.ndarray:
        """Flush the remaining tail using edge-repeated boundary samples."""
        return self._emit(final=True)

    def _emit(self, *, final: bool) -> np.ndarray:
        if self._pending.size == 0:
            return np.array([], dtype=np.int16)

        ready = self._pending.size if final else max(self._pending.size - 2, 0)
        if ready == 0:
            return np.array([], dtype=np.int16)

        samples = self._pending.astype(np.float64, copy=False)
        out = np.empty(ready * 3, dtype=np.float64)

        for index in range(ready):
            if index == 0 and self._previous_sample is not None:
                y0 = float(self._previous_sample)
            else:
                y0 = samples[index - 1] if index > 0 else samples[index]
            y1 = samples[index]
            y2 = samples[index + 1] if index + 1 < samples.size else samples[-1]
            y3 = samples[index + 2] if index + 2 < samples.size else y2

            t1 = 1.0 / 3.0
            t2 = 2.0 / 3.0
            a0 = y3 - y2 - y0 + y1
            a1 = y0 - y1 - a0
            a2 = y2 - y0

            out[index * 3] = y1
            out[index * 3 + 1] = a0 * t1**3 + a1 * t1**2 + a2 * t1 + y1
            out[index * 3 + 2] = a0 * t2**3 + a1 * t2**2 + a2 * t2 + y1

        self._previous_sample = int(self._pending[ready - 1])
        self._pending = self._pending[ready:].copy()
        return np.clip(np.round(out), -32768, 32767).astype(np.int16)


class StreamingDownsampler3x:
    """Streaming-safe 24 kHz -> 8 kHz downsampler with residual retention."""

    def __init__(self) -> None:
        self._pending = np.array([], dtype=np.int16)

    def process(self, pcm_24khz: np.ndarray) -> np.ndarray:
        """Process another chunk and emit complete 3-sample groups."""
        if pcm_24khz.size:
            self._pending = np.concatenate((self._pending, pcm_24khz.astype(np.int16, copy=False)))
        return self._emit(final=False)

    def flush(self) -> np.ndarray:
        """Flush trailing residual samples by edge-padding the final group."""
        return self._emit(final=True)

    def _emit(self, *, final: bool) -> np.ndarray:
        if self._pending.size == 0:
            return np.array([], dtype=np.int16)

        if final and self._pending.size % 3:
            remainder = 3 - (self._pending.size % 3)
            pad = np.repeat(self._pending[-1], remainder).astype(np.int16)
            self._pending = np.concatenate((self._pending, pad))

        ready = (self._pending.size // 3) * 3
        if ready == 0:
            return np.array([], dtype=np.int16)

        groups = self._pending[:ready].astype(np.float64).reshape(-1, 3)
        averaged = np.mean(groups, axis=1)
        self._pending = self._pending[ready:].copy()
        return np.clip(np.round(averaged), -32768, 32767).astype(np.int16)


class ULaw8kToPCM16_24kStreamDecoder:
    """Streaming µ-law decoder producing VoiceLive-ready 24 kHz PCM."""

    def __init__(self) -> None:
        self._upsampler = StreamingUpsampler3x()

    def decode_chunk(self, ulaw_bytes: bytes) -> bytes:
        samples_8khz = ulaw_decode(ulaw_bytes)
        return self._upsampler.process(samples_8khz).tobytes()

    def decode_chunk_b64(self, ulaw_bytes: bytes) -> str:
        return base64.b64encode(self.decode_chunk(ulaw_bytes)).decode("ascii")

    def flush(self) -> bytes:
        return self._upsampler.flush().tobytes()

    def flush_b64(self) -> str:
        return base64.b64encode(self.flush()).decode("ascii")


class PCM16_24kToULaw8kStreamEncoder:
    """Streaming PCM16 encoder producing Genesys-ready 8 kHz µ-law."""

    def __init__(self) -> None:
        self._pending_pcm_bytes = bytearray()
        self._downsampler = StreamingDownsampler3x()

    def encode_chunk(self, raw_bytes: bytes) -> bytes:
        if not raw_bytes:
            return b""

        self._pending_pcm_bytes.extend(raw_bytes)
        ready_bytes = len(self._pending_pcm_bytes) & ~0x1
        if ready_bytes == 0:
            return b""

        chunk = bytes(self._pending_pcm_bytes[:ready_bytes])
        del self._pending_pcm_bytes[:ready_bytes]

        pcm_24khz = np.frombuffer(chunk, dtype=np.int16)
        return ulaw_encode(self._downsampler.process(pcm_24khz))

    def encode_base64_chunk(self, pcm16_b64: str) -> bytes:
        try:
            raw_bytes = base64.b64decode(pcm16_b64, validate=True)
        except Exception as exc:  # noqa: BLE001 - normalize decode failures
            raise ValueError("VoiceLive audio delta is not valid base64 PCM16") from exc
        return self.encode_chunk(raw_bytes)

    def flush(self) -> bytes:
        if self._pending_pcm_bytes:
            raise ValueError(
                "VoiceLive PCM16 stream ended with an incomplete sample byte pair"
            )
        return ulaw_encode(self._downsampler.flush())


def upsample_3x(pcm_8khz: np.ndarray) -> np.ndarray:
    """Upsample PCM16 from 8 kHz to 24 kHz using the streaming-safe path."""
    upsampler = StreamingUpsampler3x()
    return np.concatenate((upsampler.process(pcm_8khz), upsampler.flush()))


def downsample_3x(pcm_24khz: np.ndarray) -> np.ndarray:
    """Downsample PCM16 from 24 kHz to 8 kHz using the streaming-safe path."""
    downsampler = StreamingDownsampler3x()
    return np.concatenate((downsampler.process(pcm_24khz), downsampler.flush()))


def ulaw_8khz_to_pcm16_24khz_b64(ulaw_bytes: bytes) -> str:
    """Convert µ-law 8 kHz audio to base64-encoded PCM16 24 kHz."""
    decoder = ULaw8kToPCM16_24kStreamDecoder()
    return decoder.decode_chunk_b64(ulaw_bytes) + decoder.flush_b64()


def pcm16_24khz_b64_to_ulaw_8khz(pcm16_b64: str) -> bytes:
    """Convert base64 PCM16 24 kHz audio to µ-law 8 kHz."""
    encoder = PCM16_24kToULaw8kStreamEncoder()
    return encoder.encode_base64_chunk(pcm16_b64) + encoder.flush()


def pcm16_24khz_bytes_to_ulaw_8khz(raw_bytes: bytes) -> bytes:
    """Convert raw PCM16 24 kHz bytes to µ-law 8 kHz."""
    encoder = PCM16_24kToULaw8kStreamEncoder()
    return encoder.encode_chunk(raw_bytes) + encoder.flush()


def convert_voicelive_delta_to_ulaw(delta: bytes | str) -> bytes:
    """Convert one VoiceLive audio delta to µ-law 8 kHz.

    The one-shot helper remains available for tests and non-streaming callers.
    The Genesys handler uses :class:`PCM16_24kToULaw8kStreamEncoder` directly so
    odd byte pairs and sample remainders can span arbitrary event boundaries.
    """
    if isinstance(delta, bytes):
        return pcm16_24khz_bytes_to_ulaw_8khz(delta)
    if isinstance(delta, str):
        return pcm16_24khz_b64_to_ulaw_8khz(delta)
    raise TypeError(f"Unsupported VoiceLive audio delta type: {type(delta).__name__}")
