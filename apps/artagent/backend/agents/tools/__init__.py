"""
Tool Registry for Unified Agents
================================

Self-contained tool registry for the unified agent structure.
Does not depend on legacy vlagent/artagent directories.

Architecture:
- registry.py: Core registration and execution logic
- schemas/: Tool schema definitions (OpenAI function calling format)
- executors/: Tool implementation functions
- handoffs.py: Handoff tool implementations

Usage:
    from apps.artagent.backend.agents.tools import (
        register_tool,
        get_tool_schema,
        get_tool_executor,
        get_tools_for_agent,
        execute_tool,
        initialize_tools,
    )
    
    # Initialize all tools
    initialize_tools()
    
    # Get tools for an agent
    tools = get_tools_for_agent(["get_account_summary", "handoff_fraud_agent"])
    
    # Execute a tool
    result = await execute_tool("get_account_summary", {"client_id": "123"})
"""

from apps.artagent.backend.agents.tools.registry import (
    # Core registration
    register_tool,
    get_tool_schema,
    get_tool_executor,
    get_tool_definition,
    is_handoff_tool,
    list_tools,
    get_tools_for_agent,
    execute_tool,
    initialize_tools,
    # Types
    ToolDefinition,
    ToolExecutor,
)

__all__ = [
    # Core registration
    "register_tool",
    "get_tool_schema",
    "get_tool_executor",
    "get_tool_definition",
    "is_handoff_tool",
    "list_tools",
    "get_tools_for_agent",
    "execute_tool",
    "initialize_tools",
    # Types
    "ToolDefinition",
    "ToolExecutor",
]
