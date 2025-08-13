"""
Realtime API Schemas
===================

Pydantic schemas for realtime WebSocket communication endpoints.

This module provides comprehensive schemas for:
- WebSocket connection and status responses
- Dashboard relay configuration and status
- Conversation session management
- Real-time communication metadata
- Service health and monitoring

All schemas include proper validation, serialization, and OpenAPI documentation
support for the V1 realtime API endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class RealtimeStatusResponse(BaseModel):
    """
    Response schema for realtime service status endpoint.

    Provides comprehensive information about the realtime communication
    service including availability, features, and active connections.
    """

    status: str = Field(
        ...,
        description="Current service status",
        example="available",
        enum=["available", "degraded", "unavailable"],
    )

    websocket_endpoints: Dict[str, str] = Field(
        ...,
        description="Available WebSocket endpoints",
        example={
            "dashboard_relay": "/api/v1/realtime/dashboard/relay",
            "conversation": "/api/v1/realtime/conversation",
        },
    )

    features: Dict[str, bool] = Field(
        ...,
        description="Supported features and capabilities",
        example={
            "dashboard_broadcasting": True,
            "conversation_streaming": True,
            "orchestrator_support": True,
            "session_management": True,
        },
    )

    active_connections: Dict[str, int] = Field(
        ...,
        description="Current active connection counts",
        example={"dashboard_clients": 0, "conversation_sessions": 0},
    )

    protocols_supported: List[str] = Field(
        default=["WebSocket"],
        description="Supported communication protocols",
        example=["WebSocket"],
    )

    version: str = Field(default="v1", description="API version", example="v1")


class DashboardConnectionResponse(BaseModel):
    """
    Response schema for dashboard connection events.

    Provides information about dashboard client connections including
    client tracking, session details, and connection metadata.
    """

    client_id: str = Field(
        ...,
        description="Unique identifier for the dashboard client",
        example="abc123def",
    )

    connection_time: datetime = Field(
        ...,
        description="Timestamp when the connection was established",
        example="2024-01-01T12:00:00Z",
    )

    total_clients: int = Field(
        ..., description="Total number of connected dashboard clients", example=1, ge=0
    )

    endpoint: str = Field(
        default="dashboard_relay",
        description="WebSocket endpoint used for connection",
        example="dashboard_relay",
    )

    features_enabled: List[str] = Field(
        default=["broadcasting", "monitoring"],
        description="Features enabled for this dashboard connection",
        example=["broadcasting", "monitoring", "tracing"],
    )


class ConversationSessionResponse(BaseModel):
    """
    Response schema for conversation session events.

    Provides comprehensive information about conversation sessions including
    session management, orchestrator details, and session state.
    """

    session_id: str = Field(
        ...,
        description="Unique identifier for the conversation session",
        example="conv_abc123def",
    )

    start_time: datetime = Field(
        ...,
        description="Timestamp when the session was started",
        example="2024-01-01T12:00:00Z",
    )

    orchestrator_name: Optional[str] = Field(
        None,
        description="Name of the orchestrator handling this session",
        example="gpt-4-orchestrator",
    )

    total_sessions: int = Field(
        ..., description="Total number of active conversation sessions", example=1, ge=0
    )

    features_enabled: List[str] = Field(
        default=["stt", "tts", "conversation_memory"],
        description="Features enabled for this conversation session",
        example=["stt", "tts", "conversation_memory", "interruption_handling"],
    )

    audio_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Audio processing configuration for the session",
        example={
            "stt_language": "en-US",
            "tts_voice": "en-US-AriaNeural",
            "sample_rate": 24000,
        },
    )

    memory_status: Optional[Dict[str, Any]] = Field(
        None,
        description="Conversation memory status and configuration",
        example={"enabled": True, "turn_count": 0, "context_length": 0},
    )


class WebSocketMessageBase(BaseModel):
    """
    Base schema for WebSocket messages.

    Provides common fields for all WebSocket message types including
    message identification, typing, and metadata.
    """

    type: str = Field(..., description="Message type identifier", example="status")

    timestamp: Optional[datetime] = Field(
        None, description="Message timestamp", example="2024-01-01T12:00:00Z"
    )

    session_id: Optional[str] = Field(
        None, description="Associated session identifier", example="conv_abc123def"
    )


class StatusMessage(WebSocketMessageBase):
    """
    WebSocket status message schema.

    Used for sending status updates and system messages
    to connected WebSocket clients.
    """

    type: str = Field(
        default="status",
        description="Message type - always 'status' for status messages",
        example="status",
    )

    message: str = Field(
        ...,
        description="Status message content",
        example="Welcome to the conversation service",
    )

    level: str = Field(
        default="info",
        description="Message level",
        example="info",
        enum=["info", "warning", "error"],
    )


class ConversationMessage(WebSocketMessageBase):
    """
    WebSocket conversation message schema.

    Used for sending conversation messages between users and assistants
    including proper sender identification and content.
    """

    type: str = Field(
        default="conversation",
        description="Message type - always 'conversation' for conversation messages",
        example="conversation",
    )

    sender: str = Field(
        ...,
        description="Message sender identifier",
        example="User",
        enum=["User", "Assistant", "System"],
    )

    message: str = Field(
        ...,
        description="Conversation message content",
        example="Hello, how can I help you today?",
    )

    language: Optional[str] = Field(
        None, description="Detected or specified language code", example="en-US"
    )


class StreamingMessage(WebSocketMessageBase):
    """
    WebSocket streaming message schema.

    Used for real-time streaming content including partial transcriptions,
    assistant responses, and other streaming data.
    """

    type: str = Field(
        default="streaming",
        description="Message type - always 'streaming' for streaming messages",
        example="streaming",
    )

    content: str = Field(
        ...,
        description="Streaming content",
        example="This is a partial transcription...",
    )

    is_final: bool = Field(
        default=False,
        description="Whether this is the final streaming message",
        example=False,
    )

    streaming_type: str = Field(
        ...,
        description="Type of streaming content",
        example="stt_partial",
        enum=["stt_partial", "stt_final", "assistant_partial", "assistant_final"],
    )


class ErrorMessage(WebSocketMessageBase):
    """
    WebSocket error message schema.

    Used for communicating errors and exceptions to WebSocket clients
    with proper error classification and recovery information.
    """

    type: str = Field(
        default="error",
        description="Message type - always 'error' for error messages",
        example="error",
    )

    error_code: str = Field(
        ..., description="Error code identifier", example="STT_ERROR"
    )

    error_message: str = Field(
        ...,
        description="Human-readable error message",
        example="Speech-to-text service temporarily unavailable",
    )

    error_type: str = Field(
        ...,
        description="Error classification",
        example="service_error",
        enum=[
            "validation_error",
            "auth_error",
            "service_error",
            "network_error",
            "unknown_error",
        ],
    )

    recovery_suggestion: Optional[str] = Field(
        None,
        description="Suggested recovery action",
        example="Please try again in a few moments",
    )

    is_recoverable: bool = Field(
        default=True,
        description="Whether the error condition is recoverable",
        example=True,
    )


class AudioMetadata(BaseModel):
    """
    Audio processing metadata schema.

    Provides information about audio stream configuration,
    processing parameters, and quality metrics.
    """

    sample_rate: int = Field(
        ..., description="Audio sample rate in Hz", example=24000, gt=0
    )

    channels: int = Field(
        default=1, description="Number of audio channels", example=1, ge=1, le=2
    )

    bit_depth: int = Field(
        default=16, description="Audio bit depth", example=16, enum=[16, 24, 32]
    )

    format: str = Field(
        default="pcm",
        description="Audio format",
        example="pcm",
        enum=["pcm", "opus", "mp3"],
    )

    language: Optional[str] = Field(
        None, description="Audio language code", example="en-US"
    )


class SessionMetrics(BaseModel):
    """
    Session performance metrics schema.

    Provides performance and quality metrics for conversation sessions
    including latency, accuracy, and processing statistics.
    """

    session_id: str = Field(
        ...,
        description="Session identifier for these metrics",
        example="conv_abc123def",
    )

    duration_seconds: float = Field(
        ..., description="Session duration in seconds", example=120.5, ge=0
    )

    message_count: int = Field(
        ..., description="Total number of messages exchanged", example=10, ge=0
    )

    avg_response_time_ms: float = Field(
        ..., description="Average response time in milliseconds", example=250.5, ge=0
    )

    stt_accuracy: Optional[float] = Field(
        None,
        description="Speech-to-text accuracy percentage",
        example=95.2,
        ge=0,
        le=100,
    )

    tts_synthesis_time_ms: Optional[float] = Field(
        None,
        description="Average TTS synthesis time in milliseconds",
        example=180.3,
        ge=0,
    )

    interruption_count: int = Field(
        default=0, description="Number of conversation interruptions", example=2, ge=0
    )

    error_count: int = Field(
        default=0, description="Number of errors during session", example=0, ge=0
    )
