"""
Azure Speaker Recognition Module for Voice Biometrics.

This module provides comprehensive capabilities for speaker identification and
verification using the Azure Cognitive Services Speech SDK. It supports
creating speaker profiles, enrolling voice samples, and verifying speakers
in real-time or from recorded audio.
"""

import os
from typing import Optional, List
import azure.cognitiveservices.speech as speechsdk
from utils.ml_logging import get_logger
from src.speech.auth_manager import get_speech_token_manager

logger = get_logger(__name__)

class SpeakerRecognitionService:
    """
    Service for managing Azure Speaker Recognition operations.
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

    def _get_config(self) -> speechsdk.SpeechConfig:
        """Create a speech configuration for Speaker Recognition."""
        if self.endpoint:
            config = speechsdk.SpeechConfig(endpoint=self.endpoint)
        else:
            config = speechsdk.SpeechConfig(subscription=self.key, region=self.region)

        # Use Azure AD authentication if key is not provided
        if not self.key:
            token_manager = get_speech_token_manager()
            token_manager.apply_to_config(config)
            
        return config

    def create_profile(self, locale: str = "en-US") -> str:
        """
        Create a new speaker profile.
        
        Args:
            locale: The locale for the profile (default: en-US)
            
        Returns:
            The unique profile ID.
        """
        config = self._get_config()
        client = speechsdk.VoiceProfileClient(config)
        
        # We use text-independent verification for natural conversation
        future = client.create_profile_async(
            speechsdk.VoiceProfileType.TextIndependentVerification, 
            locale
        )
        result = future.get()
        
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            logger.error(f"Profile creation canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                logger.error(f"Error details: {cancellation_details.error_details}")
            raise RuntimeError("Failed to create voice profile")
            
        profile_id = result.profile_id
        logger.info(f"Created voice profile: {profile_id}")
        return profile_id

    def enroll_profile(self, profile_id: str, audio_data: bytes) -> bool:
        """
        Enroll a speaker profile with audio data.
        
        Args:
            profile_id: The ID of the profile to enroll.
            audio_data: Raw audio bytes (PCM 16-bit 16kHz mono).
            
        Returns:
            True if enrollment was successful and complete.
        """
        config = self._get_config()
        client = speechsdk.VoiceProfileClient(config)
        
        # Create profile object
        profile = speechsdk.VoiceProfile(
            profile_id, 
            speechsdk.VoiceProfileType.TextIndependentVerification
        )
        
        # Create audio stream from bytes
        # Assuming 16kHz, 16-bit, Mono PCM
        stream_format = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        push_stream.write(audio_data)
        push_stream.close()
        
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        
        future = client.enroll_profile_async(profile, audio_config)
        result = future.get()
        
        if result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            logger.error(f"Enrollment canceled: {details.reason}")
            raise RuntimeError(f"Enrollment failed: {details.error_details}")
            
        logger.info(f"Enrollment result for {profile_id}: {result.reason}")
        # Enrollment is complete when reason is Enrolled
        return result.reason == speechsdk.ResultReason.Enrolled

    def verify_speaker(self, profile_id: str, audio_data: bytes) -> dict:
        """
        Verify a speaker against a profile.
        
        Args:
            profile_id: The ID of the profile to verify against.
            audio_data: Raw audio bytes for verification.
            
        Returns:
            Dictionary with 'match', 'confidence', and 'score'.
        """
        config = self._get_config()
        
        # Create profile object
        profile = speechsdk.VoiceProfile(
            profile_id, 
            speechsdk.VoiceProfileType.TextIndependentVerification
        )
        
        # Create audio stream
        stream_format = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        push_stream.write(audio_data)
        push_stream.close()
        
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        
        # Create recognizer
        recognizer = speechsdk.SpeakerRecognizer(config, audio_config)
        
        # Create model for verification
        model = speechsdk.SpeakerVerificationModel(profile)
        
        future = recognizer.recognize_once_async(model)
        result = future.get()
        
        if result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            logger.error(f"Verification canceled: {details.reason}")
            return {"match": False, "error": details.error_details}
            
        # Extract results
        match = result.reason == speechsdk.ResultReason.VerifiedSpeaker
        score = result.score
        
        # Map confidence level to threshold (can be tuned)
        logger.info(f"Verification for {profile_id}: match={match}, score={score}")
        
        return {
            "match": match,
            "score": score,
            "reason": str(result.reason)
        }

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a speaker profile."""
        config = self._get_config()
        client = speechsdk.VoiceProfileClient(config)
        
        profile = speechsdk.VoiceProfile(
            profile_id, 
            speechsdk.VoiceProfileType.TextIndependentVerification
        )
        
        future = client.delete_profile_async(profile)
        result = future.get()
        
        return result.reason == speechsdk.ResultReason.Deleted
