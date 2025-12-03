"""
Session Loader
==============

Utilities for loading user profiles and session data.
Re-exports from shared services module for backward compatibility.
"""

from __future__ import annotations

from apps.rtagent.backend.src.services.session_loader import (
    load_user_profile_by_email,
    load_user_profile_by_client_id,
)

__all__ = [
    "load_user_profile_by_email",
    "load_user_profile_by_client_id",
]
