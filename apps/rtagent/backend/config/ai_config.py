"""
AI and Model Configuration (DEPRECATED)
=======================================

This file is deprecated. Import from config or config.settings instead.

Note: Legacy AGENT_*_CONFIG settings have been removed.
Agents are now auto-discovered from apps/rtagent/backend/agents/
"""

from .settings import (
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    AOAI_REQUEST_TIMEOUT,
)
