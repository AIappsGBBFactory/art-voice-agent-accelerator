"""
Tests for speech container configuration switching.

Verifies that TTS and STT modules correctly switch between:
- Container mode (SPEECH_USE_CONTAINERS=true) using self-hosted containers
- Cloud mode (SPEECH_USE_CONTAINERS=false) using Azure cloud services

Environment Variables Tested:
- SPEECH_USE_CONTAINERS: Enable/disable container mode
- TTS_CONTAINER_ENDPOINT: TTS container URL (e.g., http://host:5000)
- STT_CONTAINER_ENDPOINT: STT container URL (e.g., ws://host:5000)
- SPEECH_CONTAINER_API_KEY: Billing API key for containers
- AZURE_SPEECH_KEY: Azure Speech subscription key
- AZURE_SPEECH_REGION: Azure region for cloud speech
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# TTS Container Configuration Tests
# ============================================================================

class TestTTSContainerConfig:
    """Test TTS SpeechSynthesizer configuration switching."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Reset environment for each test."""
        # Clear container-related env vars
        for var in [
            "SPEECH_USE_CONTAINERS",
            "TTS_CONTAINER_ENDPOINT",
            "STT_CONTAINER_ENDPOINT",
            "SPEECH_CONTAINER_API_KEY",
        ]:
            monkeypatch.delenv(var, raising=False)
        
        # Set cloud mode defaults
        monkeypatch.setenv("AZURE_SPEECH_KEY", "test-speech-key")
        monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")

    @patch("azure.cognitiveservices.speech.SpeechConfig")
    def test_tts_cloud_mode_with_api_key(self, mock_speech_config, monkeypatch):
        """When SPEECH_USE_CONTAINERS=false, should use Azure cloud with API key."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "false")
        monkeypatch.setenv("AZURE_SPEECH_KEY", "my-azure-key")
        monkeypatch.setenv("AZURE_SPEECH_REGION", "westus2")
        
        mock_config = MagicMock()
        mock_speech_config.return_value = mock_config
        
        from src.speech.text_to_speech import SpeechSynthesizer
        
        synth = SpeechSynthesizer(
            key="my-azure-key",
            region="westus2",
            voice="en-US-JennyNeural",
        )
        
        # Should have called SpeechConfig with subscription/region, not host
        mock_speech_config.assert_called_with(subscription="my-azure-key", region="westus2")

    @patch("azure.cognitiveservices.speech.SpeechConfig")
    def test_tts_container_mode_enabled(self, mock_speech_config, monkeypatch):
        """When SPEECH_USE_CONTAINERS=true with endpoint, should use container host."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "true")
        monkeypatch.setenv("TTS_CONTAINER_ENDPOINT", "http://tts-container:5000")
        monkeypatch.setenv("SPEECH_CONTAINER_API_KEY", "billing-key-123")
        
        mock_config = MagicMock()
        mock_speech_config.return_value = mock_config
        
        # Mock the voice list fetch
        with patch("src.speech.text_to_speech._fetch_container_voice") as mock_fetch:
            mock_fetch.return_value = "en-US-JessaNeural"
            
            from src.speech.text_to_speech import SpeechSynthesizer
            
            synth = SpeechSynthesizer(
                region="eastus",  # Should be ignored in container mode
                voice="en-US-JennyNeural",
            )
            
            # Should have called SpeechConfig with host (container endpoint)
            mock_speech_config.assert_called_with(host="http://tts-container:5000")

    @patch("azure.cognitiveservices.speech.SpeechConfig")
    def test_tts_container_mode_sets_api_key(self, mock_speech_config, monkeypatch):
        """Container mode should set API key via property for billing."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "true")
        monkeypatch.setenv("TTS_CONTAINER_ENDPOINT", "http://localhost:5000")
        monkeypatch.setenv("SPEECH_CONTAINER_API_KEY", "billing-key-xyz")
        
        mock_config = MagicMock()
        mock_speech_config.return_value = mock_config
        
        with patch("src.speech.text_to_speech._fetch_container_voice") as mock_fetch:
            mock_fetch.return_value = "en-US-AriaNeural"
            
            from src.speech.text_to_speech import SpeechSynthesizer
            
            synth = SpeechSynthesizer()
            
            # Should have set the API key via set_property
            mock_config.set_property.assert_called()

    def test_tts_container_mode_without_endpoint_falls_back(self, monkeypatch):
        """Container mode without endpoint should fall back to cloud."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "true")
        monkeypatch.setenv("TTS_CONTAINER_ENDPOINT", "")  # Empty endpoint
        monkeypatch.setenv("AZURE_SPEECH_KEY", "fallback-key")
        monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")
        
        with patch("azure.cognitiveservices.speech.SpeechConfig") as mock_speech_config:
            mock_config = MagicMock()
            mock_speech_config.return_value = mock_config
            
            from src.speech.text_to_speech import SpeechSynthesizer
            
            synth = SpeechSynthesizer(
                key="fallback-key",
                region="eastus",
            )
            
            # Should use cloud mode (subscription/region) not container (host)
            mock_speech_config.assert_called_with(subscription="fallback-key", region="eastus")

    @pytest.mark.parametrize("flag_value", ["true", "True", "TRUE", "1", "yes", "YES"])
    def test_tts_container_flag_case_insensitive(self, flag_value, monkeypatch):
        """SPEECH_USE_CONTAINERS should be case-insensitive."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", flag_value)
        monkeypatch.setenv("TTS_CONTAINER_ENDPOINT", "http://container:5000")
        
        with patch("azure.cognitiveservices.speech.SpeechConfig") as mock_speech_config:
            mock_config = MagicMock()
            mock_speech_config.return_value = mock_config
            
            with patch("src.speech.text_to_speech._fetch_container_voice") as mock_fetch:
                mock_fetch.return_value = "en-US-AriaNeural"
                
                from src.speech.text_to_speech import SpeechSynthesizer
                
                synth = SpeechSynthesizer()
                
                # Should use container mode
                mock_speech_config.assert_called_with(host="http://container:5000")


# ============================================================================
# STT Container Configuration Tests
# ============================================================================

class TestSTTContainerConfig:
    """Test STT StreamingConversationTranscriberFromBytes configuration switching."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Reset environment for each test."""
        for var in [
            "SPEECH_USE_CONTAINERS",
            "TTS_CONTAINER_ENDPOINT",
            "STT_CONTAINER_ENDPOINT",
            "SPEECH_CONTAINER_API_KEY",
        ]:
            monkeypatch.delenv(var, raising=False)
        
        monkeypatch.setenv("AZURE_SPEECH_KEY", "test-speech-key")
        monkeypatch.setenv("AZURE_SPEECH_REGION", "eastus")

    def test_stt_cloud_mode_with_api_key(self, monkeypatch):
        """When SPEECH_USE_CONTAINERS=false, STT should use Azure cloud."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "false")
        
        with patch("src.speech.conversation_recognizer.SpeechConfig") as mock_speech_config:
            mock_config = MagicMock()
            mock_speech_config.return_value = mock_config
            
            from src.speech.conversation_recognizer import StreamingConversationTranscriberFromBytes
            
            transcriber = StreamingConversationTranscriberFromBytes(
                key="cloud-speech-key",
                region="westeurope",
                call_connection_id="test-call-123",
            )
            
            # Should use subscription/region for cloud mode
            mock_speech_config.assert_called_with(subscription="cloud-speech-key", region="westeurope")

    def test_stt_container_mode_enabled(self, monkeypatch):
        """When SPEECH_USE_CONTAINERS=true, STT should use container host."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "true")
        monkeypatch.setenv("STT_CONTAINER_ENDPOINT", "ws://stt-container:5000")
        monkeypatch.setenv("SPEECH_CONTAINER_API_KEY", "billing-key")
        
        with patch("src.speech.conversation_recognizer.SpeechConfig") as mock_speech_config:
            mock_config = MagicMock()
            mock_speech_config.return_value = mock_config
            
            from src.speech.conversation_recognizer import StreamingConversationTranscriberFromBytes
            
            transcriber = StreamingConversationTranscriberFromBytes(
                key="ignored-in-container-mode",
                region="ignored-region",
                call_connection_id="test-call-456",
            )
            
            # Should use host (container endpoint) instead of subscription/region
            mock_speech_config.assert_called_with(host="ws://stt-container:5000")

    def test_stt_container_mode_sets_api_key(self, monkeypatch):
        """STT container mode should set API key for billing."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "true")
        monkeypatch.setenv("STT_CONTAINER_ENDPOINT", "ws://localhost:5000")
        monkeypatch.setenv("SPEECH_CONTAINER_API_KEY", "stt-billing-key")
        
        with patch("src.speech.conversation_recognizer.SpeechConfig") as mock_speech_config:
            mock_config = MagicMock()
            mock_speech_config.return_value = mock_config
            
            from src.speech.conversation_recognizer import StreamingConversationTranscriberFromBytes
            
            transcriber = StreamingConversationTranscriberFromBytes(
                call_connection_id="test-call",
            )
            
            # Should set API key via set_property
            mock_config.set_property.assert_called()

    def test_stt_container_mode_without_endpoint_falls_back(self, monkeypatch):
        """STT container mode without endpoint should fall back to cloud."""
        monkeypatch.setenv("SPEECH_USE_CONTAINERS", "true")
        monkeypatch.setenv("STT_CONTAINER_ENDPOINT", "")  # Empty
        
        with patch("src.speech.conversation_recognizer.SpeechConfig") as mock_speech_config:
            mock_config = MagicMock()
            mock_speech_config.return_value = mock_config
            
            from src.speech.conversation_recognizer import StreamingConversationTranscriberFromBytes
            
            transcriber = StreamingConversationTranscriberFromBytes(
                key="fallback-key",
                region="centralus",
                call_connection_id="test",
            )
            
            # Should fall back to cloud mode
            mock_speech_config.assert_called_with(subscription="fallback-key", region="centralus")


# ============================================================================
# TTS Container Voice Auto-Detection Tests
# ============================================================================

class TestTTSContainerVoiceDetection:
    """Test TTS container voice auto-detection functionality."""

    def test_fetch_container_voice_success(self):
        """Should fetch and return the first available voice from container."""
        mock_response = json.dumps([
            {"ShortName": "en-US-JessaNeural", "DisplayName": "Jessa", "Locale": "en-US"},
        ]).encode()
        
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_response)))
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_context
            
            from src.speech.text_to_speech import _fetch_container_voice, _container_voice_cache
            
            # Clear cache
            _container_voice_cache.clear()
            
            voice = _fetch_container_voice("http://localhost:5000")
            
            assert voice == "en-US-JessaNeural"

    def test_fetch_container_voice_caches_result(self):
        """Should cache voice lookup results."""
        mock_response = json.dumps([
            {"ShortName": "en-US-AriaNeural"},
        ]).encode()
        
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_response)))
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_context
            
            from src.speech.text_to_speech import _fetch_container_voice, _container_voice_cache
            
            # Clear cache
            _container_voice_cache.clear()
            
            # First call
            voice1 = _fetch_container_voice("http://cached-test:5000")
            # Second call (should use cache)
            voice2 = _fetch_container_voice("http://cached-test:5000")
            
            assert voice1 == voice2 == "en-US-AriaNeural"
            # urlopen should only be called once due to caching
            assert mock_urlopen.call_count == 1

    def test_fetch_container_voice_handles_empty_list(self):
        """Should return None when container has no voices."""
        mock_response = json.dumps([]).encode()
        
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=mock_response)))
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_context
            
            from src.speech.text_to_speech import _fetch_container_voice, _container_voice_cache
            
            _container_voice_cache.clear()
            
            voice = _fetch_container_voice("http://empty-container:5000")
            
            assert voice is None

    def test_fetch_container_voice_handles_network_error(self):
        """Should return None on network errors."""
        import urllib.error
        
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
            
            from src.speech.text_to_speech import _fetch_container_voice, _container_voice_cache
            
            _container_voice_cache.clear()
            
            voice = _fetch_container_voice("http://unreachable:5000")
            
            assert voice is None


# ============================================================================
# Integration Tests - Config Consistency
# ============================================================================

class TestConfigConsistency:
    """Test that TTS and STT share same env var for container mode switch."""

    def test_same_env_var_controls_both_services(self, monkeypatch):
        """Both TTS and STT check SPEECH_USE_CONTAINERS env var."""
        # This is a code-level check that both services respect the same flag
        # Instead of complex mocking, verify the actual code paths exist
        
        from src.speech.text_to_speech import SpeechSynthesizer
        from src.speech.conversation_recognizer import StreamingConversationTranscriberFromBytes
        
        # Verify both modules check the same env var
        import inspect
        tts_source = inspect.getsource(SpeechSynthesizer._create_speech_config)
        stt_source = inspect.getsource(StreamingConversationTranscriberFromBytes._create_speech_config)
        
        # Both should reference SPEECH_USE_CONTAINERS
        assert "SPEECH_USE_CONTAINERS" in tts_source, "TTS should check SPEECH_USE_CONTAINERS"
        assert "SPEECH_USE_CONTAINERS" in stt_source, "STT should check SPEECH_USE_CONTAINERS"
        
    def test_container_endpoints_are_separate(self, monkeypatch):
        """TTS and STT use separate container endpoint env vars."""
        import inspect
        from src.speech.text_to_speech import SpeechSynthesizer
        from src.speech.conversation_recognizer import StreamingConversationTranscriberFromBytes
        
        tts_source = inspect.getsource(SpeechSynthesizer._create_speech_config)
        stt_source = inspect.getsource(StreamingConversationTranscriberFromBytes._create_speech_config)
        
        # TTS should use TTS_CONTAINER_ENDPOINT
        assert "TTS_CONTAINER_ENDPOINT" in tts_source, "TTS should use TTS_CONTAINER_ENDPOINT"
        
        # STT should use STT_CONTAINER_ENDPOINT
        assert "STT_CONTAINER_ENDPOINT" in stt_source, "STT should use STT_CONTAINER_ENDPOINT"
