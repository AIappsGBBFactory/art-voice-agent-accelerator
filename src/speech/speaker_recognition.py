"""
Azure Speaker Recognition Module for Voice Biometrics.

Uses the Azure Speaker Recognition REST API directly (the Speech SDK's
VoiceProfileClient is not available in the Linux SDK build).
"""

import io
import os
import struct
import wave
from typing import Any, Optional

import httpx

from src.speech.auth_manager import get_speech_token_manager
from utils.ml_logging import get_logger

logger = get_logger(__name__)

_API_VERSION = "2024-11-15"


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
    """
    Service for managing Azure Speaker Recognition operations via REST API.
    """

    def __init__(
        self,
        key: Optional[str] = None,
        region: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        self.key = key or os.getenv("AZURE_SPEECH_KEY")
        self.region = region or os.getenv("AZURE_SPEECH_REGION")
        self.endpoint = endpoint or os.getenv("AZURE_SPEECH_ENDPOINT")

        if not self.region and not self.endpoint:
            raise ValueError("Azure Speech region or endpoint must be provided")

        # Build base URL for REST API
        if self.endpoint:
            self._base_url = self.endpoint.rstrip("/")
        else:
            self._base_url = f"https://{self.region}.api.cognitive.microsoft.com"

    def _get_headers(self) -> dict[str, str]:
        """Get auth headers using key or AAD token."""
        if self.key:
            return {"Ocp-Apim-Subscription-Key": self.key}
        token_manager = get_speech_token_manager()
        token = token_manager.get_token()
        return {"Authorization": f"Bearer {token.token}"}

    def create_profile(self, locale: str = "en-US") -> str:
        """
        Create a new text-independent verification profile.

        Returns:
            The unique profile ID.
        """
        url = f"{self._base_url}/speaker-recognition/verification/text-independent/profiles"
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"

        resp = httpx.post(
            url,
            params={"api-version": _API_VERSION},
            headers=headers,
            json={"locale": locale},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        profile_id = data.get("profileId") or data.get("self", "").rsplit("/", 1)[-1]
        logger.info("Created voice profile: %s", profile_id)
        return profile_id

    def enroll_profile(self, profile_id: str, audio_data: bytes) -> bool:
        """
        Enroll a speaker profile with audio data.

        Args:
            profile_id: The ID of the profile to enroll.
            audio_data: Raw PCM audio bytes (16-bit 16kHz mono).

        Returns:
            True if enrollment was successful.
        """
        url = (
            f"{self._base_url}/speaker-recognition/verification/text-independent"
            f"/profiles/{profile_id}/enrollments"
        )
        headers = self._get_headers()
        headers["Content-Type"] = "audio/wav"

        wav_data = _pcm_to_wav(audio_data)
        logger.info(
            "Enrolling profile %s with %d bytes PCM (%d bytes WAV)",
            profile_id, len(audio_data), len(wav_data),
        )

        resp = httpx.post(
            url,
            params={"api-version": _API_VERSION},
            headers=headers,
            content=wav_data,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        remaining = data.get("remainingEnrollmentsSpeechLength", 0)
        status = data.get("enrollmentStatus", "unknown")
        logger.info(
            "Enrollment result for %s: status=%s, remaining_speech=%.1fs",
            profile_id, status, remaining,
        )
        return status.lower() == "enrolled"

    def verify_speaker(self, profile_id: str, audio_data: bytes) -> dict[str, Any]:
        """
        Verify a speaker against a profile.

        Args:
            profile_id: The ID of the profile to verify against.
            audio_data: Raw PCM audio bytes for verification.

        Returns:
            Dictionary with 'match', 'score', and 'reason'.
        """
        url = (
            f"{self._base_url}/speaker-recognition/verification/text-independent"
            f"/profiles/{profile_id}/verify"
        )
        headers = self._get_headers()
        headers["Content-Type"] = "audio/wav"

        wav_data = _pcm_to_wav(audio_data)

        resp = httpx.post(
            url,
            params={"api-version": _API_VERSION},
            headers=headers,
            content=wav_data,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        result = data.get("recognitionResult", "reject").lower()
        score = data.get("score", 0.0)
        match = result == "accept"

        logger.info("Verification for %s: match=%s, score=%.3f", profile_id, match, score)

        return {
            "match": match,
            "score": score,
            "reason": result,
        }

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a speaker profile."""
        url = (
            f"{self._base_url}/speaker-recognition/verification/text-independent"
            f"/profiles/{profile_id}"
        )
        headers = self._get_headers()

        resp = httpx.delete(
            url,
            params={"api-version": _API_VERSION},
            headers=headers,
            timeout=30,
        )
        return resp.status_code in (200, 204)
