"""
Health check API schemas.

Pydantic schemas for health and readiness API responses.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Overall health status", example="healthy")
    version: str = Field(default="1.0.0", description="API version", example="1.0.0")
    timestamp: float = Field(
        ..., description="Timestamp when check was performed", example=1691668800.0
    )
    message: str = Field(
        ...,
        description="Human-readable status message",
        example="Real-Time Audio Agent API v1 is running",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional health details",
        example={"api_version": "v1", "service": "rtagent-backend"},
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": 1691668800.0,
                "message": "Real-Time Audio Agent API v1 is running",
                "details": {"api_version": "v1", "service": "rtagent-backend"},
            }
        }


class ServiceCheck(BaseModel):
    """Individual service check result."""

    component: str = Field(
        ..., description="Name of the component being checked", example="redis"
    )
    status: str = Field(
        ...,
        description="Health status of the component",
        example="healthy",
        enum=["healthy", "unhealthy", "degraded"],
    )
    check_time_ms: float = Field(
        ..., description="Time taken to perform the check in milliseconds", example=12.5
    )
    error: Optional[str] = Field(
        None, description="Error message if check failed", example="Connection timeout"
    )
    details: Optional[str] = Field(
        None,
        description="Additional details about the check",
        example="Connected to Redis successfully",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "component": "redis",
                "status": "healthy",
                "check_time_ms": 12.5,
                "details": "Connected to Redis successfully",
            }
        }


class ReadinessResponse(BaseModel):
    """Comprehensive readiness check response model."""

    status: str = Field(
        ...,
        description="Overall readiness status",
        example="ready",
        enum=["ready", "not_ready", "degraded"],
    )
    timestamp: float = Field(
        ..., description="Timestamp when check was performed", example=1691668800.0
    )
    response_time_ms: float = Field(
        ..., description="Total time taken for all checks in milliseconds", example=45.2
    )
    checks: List[ServiceCheck] = Field(
        ..., description="Individual component health checks"
    )
    event_system: Optional[Dict[str, Any]] = Field(
        None,
        description="Event system status information",
        example={"is_healthy": True, "handlers_count": 7, "domains_count": 2},
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "ready",
                "timestamp": 1691668800.0,
                "response_time_ms": 45.2,
                "checks": [
                    {
                        "component": "redis",
                        "status": "healthy",
                        "check_time_ms": 12.5,
                        "details": "Connected to Redis successfully",
                    },
                    {
                        "component": "azure_openai",
                        "status": "healthy",
                        "check_time_ms": 8.3,
                        "details": "Client initialized",
                    },
                ],
                "event_system": {
                    "is_healthy": True,
                    "handlers_count": 7,
                    "domains_count": 2,
                },
            }
        }
