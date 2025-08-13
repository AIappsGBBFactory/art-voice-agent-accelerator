"""
Media API Schemas
================

Pydantic schemas for media streaming, transcription, and audio processing endpoints.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class MediaSessionRequest(BaseModel):
    """Request schema for starting a media session."""

    call_connection_id: str = Field(
        ..., description="ACS call connection identifier", example="call_12345"
    )
    sample_rate: Optional[int] = Field(
        16000, description="Audio sample rate in Hz", example=16000
    )
    channels: Optional[int] = Field(
        1, description="Number of audio channels", example=1
    )
    audio_format: Optional[str] = Field(
        "pcm_16",
        description="Audio format (pcm_16, pcm_24, opus, etc.)",
        example="pcm_16",
    )
    chunk_size: Optional[int] = Field(
        1024, description="Audio chunk size in bytes", example=1024
    )
    enable_transcription: Optional[bool] = Field(
        True, description="Enable real-time transcription", example=True
    )
    enable_vad: Optional[bool] = Field(
        True, description="Enable voice activity detection", example=True
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "call_connection_id": "call_12345",
                "sample_rate": 16000,
                "channels": 1,
                "audio_format": "pcm_16",
                "chunk_size": 1024,
                "enable_transcription": True,
                "enable_vad": True,
            }
        }


class MediaSessionResponse(BaseModel):
    """Response schema for media session creation."""

    session_id: str = Field(
        ...,
        description="Unique media session identifier",
        example="media_session_123456",
    )
    websocket_url: str = Field(
        ...,
        description="WebSocket URL for audio streaming",
        example="wss://api.example.com/v1/media/stream/media_session_123456",
    )
    status: str = Field(..., description="Session status", example="active")
    created_at: str = Field(
        ..., description="Session creation timestamp", example="2025-08-10T13:45:00Z"
    )
    configuration: Dict[str, Any] = Field(
        ...,
        description="Session configuration settings",
        example={
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_16",
            "chunk_size": 1024,
        },
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "websocket_url": "wss://api.example.com/v1/media/stream/media_session_123456",
                "status": "active",
                "created_at": "2025-08-10T13:45:00Z",
                "configuration": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_16",
                    "chunk_size": 1024,
                },
            }
        }


class TranscriptionRequest(BaseModel):
    """Request schema for starting transcription."""

    session_id: str = Field(
        ..., description="Media session identifier", example="media_session_123456"
    )
    language: Optional[str] = Field(
        "en-US", description="Transcription language code", example="en-US"
    )
    confidence_threshold: Optional[float] = Field(
        0.5,
        description="Minimum confidence threshold for results",
        example=0.5,
        ge=0.0,
        le=1.0,
    )
    enable_interim_results: Optional[bool] = Field(
        True, description="Enable interim (partial) transcription results", example=True
    )
    enable_speaker_diarization: Optional[bool] = Field(
        False, description="Enable speaker identification", example=False
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "language": "en-US",
                "confidence_threshold": 0.5,
                "enable_interim_results": True,
                "enable_speaker_diarization": False,
            }
        }


class TranscriptionResponse(BaseModel):
    """Response schema for transcription service."""

    transcription_id: str = Field(
        ...,
        description="Unique transcription identifier",
        example="transcription_media_session_123456",
    )
    session_id: str = Field(
        ...,
        description="Associated media session identifier",
        example="media_session_123456",
    )
    status: str = Field(
        ..., description="Transcription service status", example="active"
    )
    language: str = Field(..., description="Transcription language", example="en-US")
    confidence_threshold: float = Field(
        ..., description="Confidence threshold setting", example=0.5
    )
    started_at: str = Field(
        ..., description="Transcription start timestamp", example="2025-08-10T13:45:00Z"
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "transcription_id": "transcription_media_session_123456",
                "session_id": "media_session_123456",
                "status": "active",
                "language": "en-US",
                "confidence_threshold": 0.5,
                "started_at": "2025-08-10T13:45:00Z",
            }
        }


class AudioStreamStatus(BaseModel):
    """Schema for audio stream status information."""

    session_id: str = Field(
        ..., description="Media session identifier", example="media_session_123456"
    )
    is_active: bool = Field(
        ..., description="Whether the stream is currently active", example=True
    )
    connected_at: str = Field(
        ..., description="Stream connection timestamp", example="2025-08-10T13:45:00Z"
    )
    last_activity: str = Field(
        ..., description="Last activity timestamp", example="2025-08-10T13:47:30Z"
    )
    total_audio_chunks: int = Field(
        ..., description="Total audio chunks processed", example=1250
    )
    total_duration_seconds: float = Field(
        ..., description="Total audio duration in seconds", example=125.0
    )
    is_speaking: bool = Field(
        ..., description="Current voice activity status", example=False
    )
    voice_activity_confidence: float = Field(
        ...,
        description="Voice activity detection confidence",
        example=0.15,
        ge=0.0,
        le=1.0,
    )
    transcription_enabled: bool = Field(
        ..., description="Whether transcription is enabled", example=True
    )
    last_transcription: Optional[str] = Field(
        None,
        description="Last transcription result",
        example="Hello, how can I help you today?",
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "is_active": True,
                "connected_at": "2025-08-10T13:45:00Z",
                "last_activity": "2025-08-10T13:47:30Z",
                "total_audio_chunks": 1250,
                "total_duration_seconds": 125.0,
                "is_speaking": False,
                "voice_activity_confidence": 0.15,
                "transcription_enabled": True,
                "last_transcription": "Hello, how can I help you today?",
            }
        }


class VoiceActivityResponse(BaseModel):
    """Schema for voice activity detection results."""

    session_id: str = Field(
        ..., description="Media session identifier", example="media_session_123456"
    )
    is_speaking: bool = Field(
        ..., description="Whether speech is currently detected", example=False
    )
    confidence: float = Field(
        ..., description="Voice activity confidence score", example=0.15, ge=0.0, le=1.0
    )
    last_speech_detected: Optional[str] = Field(
        None,
        description="Timestamp of last speech detection",
        example="2025-08-10T13:47:25Z",
    )
    speech_duration_seconds: Optional[float] = Field(
        None, description="Duration of last speech segment", example=2.3
    )
    silence_duration_seconds: Optional[float] = Field(
        None, description="Duration of current silence", example=5.2
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "is_speaking": False,
                "confidence": 0.15,
                "last_speech_detected": "2025-08-10T13:47:25Z",
                "speech_duration_seconds": 2.3,
                "silence_duration_seconds": 5.2,
            }
        }


class MediaMetricsResponse(BaseModel):
    """Schema for media processing metrics."""

    session_id: str = Field(
        ..., description="Media session identifier", example="media_session_123456"
    )
    total_audio_chunks: int = Field(
        ..., description="Total audio chunks processed", example=1250
    )
    total_duration_seconds: float = Field(
        ..., description="Total audio duration processed", example=125.0
    )
    average_latency_ms: float = Field(
        ..., description="Average processing latency in milliseconds", example=45.2
    )
    transcription_accuracy: Optional[float] = Field(
        None, description="Transcription accuracy score", example=0.94, ge=0.0, le=1.0
    )
    voice_activity_percentage: Optional[float] = Field(
        None,
        description="Percentage of time with voice activity",
        example=45.6,
        ge=0.0,
        le=100.0,
    )
    processing_errors: int = Field(
        ..., description="Number of processing errors", example=0
    )
    last_updated: str = Field(
        ...,
        description="Metrics last updated timestamp",
        example="2025-08-10T13:47:30Z",
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "total_audio_chunks": 1250,
                "total_duration_seconds": 125.0,
                "average_latency_ms": 45.2,
                "transcription_accuracy": 0.94,
                "voice_activity_percentage": 45.6,
                "processing_errors": 0,
                "last_updated": "2025-08-10T13:47:30Z",
            }
        }


class AudioConfigRequest(BaseModel):
    """Request schema for audio configuration updates."""

    session_id: str = Field(
        ..., description="Media session identifier", example="media_session_123456"
    )
    sample_rate: Optional[int] = Field(
        None, description="Audio sample rate in Hz", example=16000
    )
    channels: Optional[int] = Field(
        None, description="Number of audio channels", example=1
    )
    format: Optional[str] = Field(None, description="Audio format", example="pcm_16")
    noise_reduction_enabled: Optional[bool] = Field(
        None, description="Enable noise reduction", example=True
    )
    echo_cancellation_enabled: Optional[bool] = Field(
        None, description="Enable echo cancellation", example=True
    )
    auto_gain_control_enabled: Optional[bool] = Field(
        None, description="Enable automatic gain control", example=False
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "sample_rate": 16000,
                "channels": 1,
                "format": "pcm_16",
                "noise_reduction_enabled": True,
                "echo_cancellation_enabled": True,
                "auto_gain_control_enabled": False,
            }
        }


class AudioConfigResponse(BaseModel):
    """Response schema for audio configuration updates."""

    session_id: str = Field(
        ..., description="Media session identifier", example="media_session_123456"
    )
    sample_rate: int = Field(
        ..., description="Current audio sample rate", example=16000
    )
    channels: int = Field(
        ..., description="Current number of audio channels", example=1
    )
    format: str = Field(..., description="Current audio format", example="pcm_16")
    noise_reduction_enabled: bool = Field(
        ..., description="Noise reduction status", example=True
    )
    echo_cancellation_enabled: bool = Field(
        ..., description="Echo cancellation status", example=True
    )
    auto_gain_control_enabled: bool = Field(
        ..., description="Auto gain control status", example=False
    )
    applied_at: str = Field(
        ...,
        description="Configuration applied timestamp",
        example="2025-08-10T13:47:30Z",
    )

    class Config:
        json_json_schema_extra = {
            "example": {
                "session_id": "media_session_123456",
                "sample_rate": 16000,
                "channels": 1,
                "format": "pcm_16",
                "noise_reduction_enabled": True,
                "echo_cancellation_enabled": True,
                "auto_gain_control_enabled": False,
                "applied_at": "2025-08-10T13:47:30Z",
            }
        }
