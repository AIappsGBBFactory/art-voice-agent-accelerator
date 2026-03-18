"""
Speaker Recognition client — calls the SpeechBrain speaker-id microservice.

Replaces the retired Azure Speaker Recognition REST API with a local
ECAPA-TDNN service that extracts 192-dim embeddings and compares them
via cosine similarity.
"""

from __future__ import annotations

import base64
import io
import os
import wave
from typing import Any

import httpx

from utils.ml_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_URL = "http://speakerid:8000"


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, bits: int = 16, channels: int = 1) -> bytes:
    """Wrap raw PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


class SpeakerRecognitionService:
    """Client for the SpeechBrain speaker-id microservice."""

    def __init__(self, service_url: str | None = None) -> None:
        self._url = (service_url or os.getenv("SPEAKERID_SERVICE_URL") or _DEFAULT_URL).rstrip("/")

    def get_embedding(self, audio_data: bytes) -> list[float]:
        """
        Extract a 192-dim speaker embedding from raw PCM audio.

        Args:
            audio_data: Raw PCM bytes (16-bit 16kHz mono).

        Returns:
            List of 192 floats representing the speaker embedding.
        """
        wav_data = _pcm_to_wav(audio_data)
        logger.info(
            "Requesting embedding from %s (%d bytes PCM, %d bytes WAV)",
            self._url, len(audio_data), len(wav_data),
        )

        resp = httpx.post(
            f"{self._url}/embed",
            content=wav_data,
            headers={"Content-Type": "audio/wav"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        embedding = data["embedding"]
        logger.info("Got embedding: %d dimensions", len(embedding))
        return embedding

    def verify(
        self,
        audio_data: bytes,
        stored_embedding: list[float],
        threshold: float = 0.55,
    ) -> dict[str, Any]:
        """
        Verify a speaker against a stored embedding.

        Args:
            audio_data: Raw PCM bytes for verification.
            stored_embedding: Previously enrolled 192-dim embedding.
            threshold: Cosine similarity threshold (default 0.70).

        Returns:
            Dict with 'match' (bool), 'score' (float), 'reason' (str).
        """
        wav_data = _pcm_to_wav(audio_data)
        audio_b64 = base64.b64encode(wav_data).decode("utf-8")

        resp = httpx.post(
            f"{self._url}/verify",
            json={
                "audio": audio_b64,
                "embedding": stored_embedding,
                "threshold": threshold,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        match = data["match"]
        score = data["score"]
        
        if match:
            reason = "accept"
            logger.info("Verification SUCCESS: match=True, score=%.3f (threshold=%.2f)", score, threshold)
        else:
            reason = "reject (below threshold)" if score < threshold else "reject"
            logger.warning("Verification FAILURE: match=False, score=%.3f (threshold=%.2f)", score, threshold)

        return {
            "match": match,
            "score": score,
            "reason": reason,
        }
