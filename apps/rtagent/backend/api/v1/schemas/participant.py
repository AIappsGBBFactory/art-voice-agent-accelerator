"""
Participant-related API schemas.

Pydantic schemas for participant management API requests and responses.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ParticipantResponse(BaseModel):
    """Response model for participant information."""

    participant_id: str = Field(
        ..., description="Unique participant identifier", example="participant_abc123"
    )
    display_name: Optional[str] = Field(
        None, description="Display name of the participant", example="John Doe"
    )
    phone_number: Optional[str] = Field(
        None, description="Phone number of the participant", example="+1234567890"
    )
    email: Optional[str] = Field(
        None,
        description="Email address of the participant",
        example="john.doe@example.com",
    )
    role: str = Field(
        ...,
        description="Role of the participant in the call",
        example="caller",
        enum=["caller", "agent", "moderator", "observer"],
    )
    status: str = Field(
        ...,
        description="Current status of the participant",
        example="connected",
        enum=["invited", "joining", "connected", "muted", "on_hold", "disconnected"],
    )
    capabilities: Dict[str, bool] = Field(
        default_factory=dict,
        description="Participant capabilities and permissions",
        example={
            "can_speak": True,
            "can_listen": True,
        },
    )
    quality_metrics: Optional[Dict[str, float]] = Field(
        None,
        description="Audio and network quality metrics",
        example={"audio_quality_score": 0.85, "network_quality_score": 0.92},
    )
    interaction_stats: Optional[Dict[str, int]] = Field(
        None,
        description="Interaction statistics",
        example={
            "total_speak_time_seconds": 120,
            "total_mute_time_seconds": 30,
            "interaction_count": 5,
        },
    )
    timestamps: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Relevant timestamps for the participant",
        example={
            "invited_at": "2025-08-10T13:45:00Z",
            "joined_at": "2025-08-10T13:45:15Z",
            "last_activity_at": "2025-08-10T13:50:30Z",
        },
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional participant metadata",
        example={
            "user_agent": "Mozilla/5.0...",
            "ip_address": "192.168.1.100",
            "device_type": "desktop",
        },
    )

    class Config:
        json_schema_extra = {
            "example": {
                "participant_id": "participant_abc123",
                "display_name": "John Doe",
                "phone_number": "+1234567890",
                "email": "john.doe@example.com",
                "role": "caller",
                "status": "connected",
                "capabilities": {
                    "can_speak": True,
                    "can_listen": True,
                },
                "quality_metrics": {
                    "audio_quality_score": 0.85,
                    "network_quality_score": 0.92,
                },
                "interaction_stats": {
                    "total_speak_time_seconds": 120,
                    "total_mute_time_seconds": 30,
                    "interaction_count": 5,
                },
                "timestamps": {
                    "invited_at": "2025-08-10T13:45:00Z",
                    "joined_at": "2025-08-10T13:45:15Z",
                    "last_activity_at": "2025-08-10T13:50:30Z",
                },
                "metadata": {
                    "user_agent": "Mozilla/5.0...",
                    "ip_address": "192.168.1.100",
                    "device_type": "desktop",
                },
            }
        }


class ParticipantUpdateRequest(BaseModel):
    """Request model for updating participant properties."""

    display_name: Optional[str] = Field(
        None, description="Updated display name", example="John Smith"
    )
    role: Optional[str] = Field(
        None,
        description="Updated participant role",
        enum=["caller", "agent", "moderator", "observer"],
        example="moderator",
    )
    status: Optional[str] = Field(
        None,
        description="Updated participant status",
        enum=["connected", "muted", "on_hold", "disconnected"],
        example="muted",
    )
    capabilities: Optional[Dict[str, bool]] = Field(
        None,
        description="Updated capabilities",
        example={
            "can_speak": False,
            "can_listen": True,
        },
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Updated metadata",
        example={
            "notes": "Participant requested to be muted",
            "updated_by": "agent_123",
        },
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "muted",
                "capabilities": {"can_speak": False, "can_listen": True},
                "metadata": {
                    "mute_reason": "background_noise",
                    "updated_by": "agent_123",
                },
            }
        }


class ParticipantInviteRequest(BaseModel):
    """Request model for inviting participants to a call."""

    phone_number: Optional[str] = Field(
        None,
        description="Phone number to invite (E.164 format)",
        pattern=r"^\+[1-9]\d{1,14}$",
        example="+1234567890",
    )
    email: Optional[str] = Field(
        None, description="Email address to invite", example="participant@example.com"
    )
    display_name: Optional[str] = Field(
        None, description="Display name for the participant", example="Jane Doe"
    )
    role: str = Field(
        default="caller",
        description="Role to assign to the participant",
        enum=["caller", "agent", "moderator", "observer"],
        example="caller",
    )
    capabilities: Optional[Dict[str, bool]] = Field(
        default_factory=lambda: {
            "can_speak": True,
            "can_listen": True,
        },
        description="Initial capabilities for the participant",
    )
    context: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional context for the invitation",
        example={"invitation_reason": "customer_support", "priority": "high"},
    )

    class Config:
        json_schema_extra = {
            "example": {
                "phone_number": "+1234567890",
                "display_name": "Jane Doe",
                "role": "caller",
                "capabilities": {
                    "can_speak": True,
                    "can_listen": True,
                },
                "context": {
                    "invitation_reason": "customer_support",
                    "priority": "high",
                },
            }
        }


class ParticipantInviteResponse(BaseModel):
    """Response model for participant invitation."""

    participant_id: str = Field(
        ..., description="Generated participant ID", example="participant_xyz789"
    )
    invitation_status: str = Field(
        ...,
        description="Status of the invitation",
        example="sent",
        enum=["sent", "failed", "pending"],
    )
    message: str = Field(
        ...,
        description="Human-readable status message",
        example="Invitation sent successfully",
    )
    invitation_details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Details about the invitation",
        example={
            "invited_at": "2025-08-10T13:45:00Z",
            "invitation_method": "phone",
            "expected_join_time": "2025-08-10T13:46:00Z",
        },
    )

    class Config:
        json_schema_extra = {
            "example": {
                "participant_id": "participant_xyz789",
                "invitation_status": "sent",
                "message": "Invitation sent successfully to +1234567890",
                "invitation_details": {
                    "invited_at": "2025-08-10T13:45:00Z",
                    "invitation_method": "phone",
                    "expected_join_time": "2025-08-10T13:46:00Z",
                },
            }
        }


class ParticipantListResponse(BaseModel):
    """Response model for listing participants."""

    participants: List[ParticipantResponse] = Field(
        ..., description="List of participants"
    )
    total: int = Field(..., description="Total number of participants", example=3)
    active: int = Field(..., description="Number of active participants", example=2)
    call_id: Optional[str] = Field(
        None,
        description="Associated call ID if filtered by call",
        example="call_abc123",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "participants": [
                    {
                        "participant_id": "participant_abc123",
                        "display_name": "John Doe",
                        "phone_number": "+1234567890",
                        "role": "caller",
                        "status": "connected",
                        "capabilities": {"can_speak": True, "can_listen": True},
                        "timestamps": {"joined_at": "2025-08-10T13:45:15Z"},
                        "metadata": {},
                    }
                ],
                "total": 3,
                "active": 2,
                "call_id": "call_abc123",
            }
        }
