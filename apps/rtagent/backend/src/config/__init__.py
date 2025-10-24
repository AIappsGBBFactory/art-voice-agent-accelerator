"""
Use Case Configuration Module
=============================

Provides use case management and DTMF-based orchestrator selection.
"""

from .use_cases import (
    UseCase,
    UseCaseConfig,
    USE_CASE_REGISTRY,
    DTMF_TO_USE_CASE,
    get_use_case_from_dtmf,
    get_use_case_config,
    get_selection_greeting,
    USE_CASE_SELECTED_KEY,
    USE_CASE_TYPE_KEY,
    USE_CASE_GREETING_SENT_KEY,
)

__all__ = [
    "UseCase",
    "UseCaseConfig",
    "USE_CASE_REGISTRY",
    "DTMF_TO_USE_CASE",
    "get_use_case_from_dtmf",
    "get_use_case_config",
    "get_selection_greeting",
    "USE_CASE_SELECTED_KEY",
    "USE_CASE_TYPE_KEY",
    "USE_CASE_GREETING_SENT_KEY",
]
