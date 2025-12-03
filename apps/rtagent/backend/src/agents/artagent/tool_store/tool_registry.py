"""
ARTAgent Tool Registry
======================

This module provides backwards-compatible access to the unified tool registry.
Tools are now centralized in apps.rtagent.backend.src.agents.shared.tool_registry.
"""

from typing import Any, Callable, Dict, List

from utils.ml_logging import get_logger

# Import from shared registry
from apps.rtagent.backend.src.agents.shared.tool_registry import (
    initialize_tools,
    get_tool_schema,
    get_tool_executor,
    get_legacy_tool_registry,
    get_legacy_function_mapping,
    get_legacy_available_tools,
    execute_tool,
)

log = get_logger("artagent.tool_registry")

# Initialize shared tools on import
initialize_tools()


# Legacy compatibility exports - these dynamically reference the shared registry
def _get_function_mapping() -> Dict[str, Callable[..., Any]]:
    """Get function_mapping from shared registry."""
    return get_legacy_function_mapping()


def _get_available_tools() -> List[Dict[str, Any]]:
    """Get available_tools list from shared registry."""
    return get_legacy_available_tools()


def _get_tool_registry() -> Dict[str, Dict[str, Any]]:
    """Get TOOL_REGISTRY from shared registry."""
    return get_legacy_tool_registry()


# These are accessed as module-level variables, so we provide property-like behavior
# by computing them at import time. For better performance, we cache them.
function_mapping: Dict[str, Callable[..., Any]] = _get_function_mapping()
available_tools: List[Dict[str, Any]] = _get_available_tools()
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = _get_tool_registry()

__all__ = [
    "function_mapping",
    "available_tools", 
    "TOOL_REGISTRY",
    "execute_tool",
]
