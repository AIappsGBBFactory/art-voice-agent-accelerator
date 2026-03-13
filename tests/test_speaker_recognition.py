import pytest
from unittest.mock import MagicMock, patch
from src.speech.speaker_recognition import SpeakerRecognitionService

class TestSpeakerRecognition:
    """Test suite for Speaker Recognition Service."""

    @patch('azure.cognitiveservices.speech.VoiceProfileClient')
    @patch('azure.cognitiveservices.speech.SpeechConfig')
    def test_create_profile(self, mock_config, mock_client_class):
        # Setup
        mock_client = mock_client_class.return_value
        mock_result = MagicMock()
        mock_result.profile_id = "test-profile-id"
        mock_result.reason = MagicMock() # Will be compared but doesn't need specific value here
        
        mock_future = MagicMock()
        mock_future.get.return_value = mock_result
        mock_client.create_profile_async.return_value = mock_future
        
        # Execute
        service = SpeakerRecognitionService(key="test", region="test")
        profile_id = service.create_profile()
        
        # Verify
        assert profile_id == "test-profile-id"
        mock_client.create_profile_async.assert_called_once()

    @patch('azure.cognitiveservices.speech.VoiceProfileClient')
    def test_enroll_profile(self, mock_client_class):
        # Setup
        mock_client = mock_client_class.return_value
        mock_result = MagicMock()
        import azure.cognitiveservices.speech as speechsdk
        mock_result.reason = speechsdk.ResultReason.Enrolled
        
        mock_future = MagicMock()
        mock_future.get.return_value = mock_result
        mock_client.enroll_profile_async.return_value = mock_future
        
        # Execute
        service = SpeakerRecognitionService(key="test", region="test")
        success = service.enroll_profile("test-id", b"dummy-audio-data")
        
        # Verify
        assert success is True
        mock_client.enroll_profile_async.assert_called_once()

    @patch('azure.cognitiveservices.speech.SpeakerRecognizer')
    def test_verify_speaker(self, mock_recognizer_class):
        # Setup
        mock_recognizer = mock_recognizer_class.return_value
        mock_result = MagicMock()
        import azure.cognitiveservices.speech as speechsdk
        mock_result.reason = speechsdk.ResultReason.VerifiedSpeaker
        mock_result.score = 0.95
        
        mock_future = MagicMock()
        mock_future.get.return_value = mock_result
        mock_recognizer.recognize_once_async.return_value = mock_future
        
        # Execute
        service = SpeakerRecognitionService(key="test", region="test")
        result = service.verify_speaker("test-id", b"dummy-audio-data")
        
        # Verify
        assert result["match"] is True
        assert result["score"] == 0.95
