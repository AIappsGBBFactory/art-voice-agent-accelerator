"""
API V1 Router
=============

Main router for API v1 endpoints.
"""

from fastapi import APIRouter

from .endpoints import agent_builder, browser, calls, health, media, metrics

# Create v1 router
v1_router = APIRouter(prefix="/api/v1")

# Include endpoint routers with specific tags for better organization
# see the api/swagger_docs.py for the swagger tags configuration
v1_router.include_router(health.router, tags=["health"])
v1_router.include_router(calls.router, prefix="/calls", tags=["Call Management"])
v1_router.include_router(media.router, prefix="/media", tags=["ACS Media Session", "WebSocket"])
v1_router.include_router(
    browser.router, prefix="/browser", tags=["Browser Communication", "WebSocket"]
)
v1_router.include_router(metrics.router, prefix="/metrics", tags=["Session Metrics", "Telemetry"])
v1_router.include_router(agent_builder.router, prefix="/agent-builder", tags=["Agent Builder"])
