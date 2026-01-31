"""
MCP Server Management Endpoints
===============================

REST endpoints for dynamically managing MCP (Model Context Protocol) servers
at runtime. Allows users to connect to new MCP servers, discover their tools,
and make those tools available to agents.

Endpoints:
    GET  /api/v1/mcp/servers         - List configured MCP servers with status
    POST /api/v1/mcp/servers         - Add new MCP server connection
    POST /api/v1/mcp/servers/test    - Test connection and discover tools
    DELETE /api/v1/mcp/servers/{name} - Remove server and unregister its tools
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.artagent.backend.config.settings import (
    MCP_ENABLED_SERVERS,
    MCP_SERVER_TIMEOUT,
    get_enabled_mcp_servers,
    get_mcp_server_config,
)
from apps.artagent.backend.registries.toolstore.mcp import (
    MCPClientSession,
    MCPServerConfig,
    MCPTransport,
)
from apps.artagent.backend.registries.toolstore.registry import (
    list_mcp_tools,
    register_mcp_tool,
    unregister_mcp_tools,
)
from utils.ml_logging import get_logger

logger = get_logger("v1.mcp")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY RUNTIME SERVER REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════
# Runtime-added MCP servers (not from environment variables)
# Key: server name, Value: MCPServerConfig
_RUNTIME_MCP_SERVERS: dict[str, MCPServerConfig] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════


class MCPServerRequest(BaseModel):
    """Request schema for adding a new MCP server."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique name for the MCP server (e.g., 'cardapi', 'knowledge')",
        pattern=r"^[a-z0-9_-]+$",
    )
    url: str = Field(
        ...,
        description="HTTP endpoint URL for the MCP server (e.g., 'http://localhost:8080')",
    )
    transport: str = Field(
        default="sse",
        description="Transport type: 'sse' (Server-Sent Events), 'http', or 'stdio'",
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        description="Request timeout in seconds",
    )


class MCPServerInfo(BaseModel):
    """Information about an MCP server."""

    name: str
    url: str
    transport: str
    timeout: float
    status: str  # "healthy", "unhealthy", "unknown"
    tools_count: int
    tool_names: list[str]
    error: str | None = None
    source: str  # "environment" or "runtime"


class MCPToolInfo(BaseModel):
    """Information about a tool discovered from an MCP server."""

    name: str
    prefixed_name: str
    description: str
    server_name: str
    input_schema: dict[str, Any]


class MCPTestResponse(BaseModel):
    """Response from testing an MCP server connection."""

    status: str
    url: str
    connected: bool
    tools_count: int
    tools: list[MCPToolInfo]
    error: str | None = None
    response_time_ms: float


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def _get_all_servers() -> dict[str, dict[str, Any]]:
    """
    Get all configured MCP servers from both environment and runtime.

    Returns:
        Dict mapping server name to config with source field
    """
    servers = {}

    # Environment-configured servers
    for server_config in get_enabled_mcp_servers():
        name = server_config["name"]
        servers[name] = {**server_config, "source": "environment"}

    # Runtime-added servers
    for name, config in _RUNTIME_MCP_SERVERS.items():
        servers[name] = {
            "name": config.name,
            "url": config.url,
            "transport": config.transport.value if hasattr(config.transport, 'value') else str(config.transport),
            "timeout": config.timeout,
            "source": "runtime",
        }

    return servers


async def _check_server_health(url: str, timeout: float = 5.0) -> tuple[bool, dict[str, Any] | None, str | None]:
    """
    Check health of an MCP server.

    Returns:
        Tuple of (is_healthy, health_data, error_message)
    """
    health_url = f"{url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(health_url)
            if response.status_code == 200:
                try:
                    data = response.json()
                    return True, data, None
                except Exception:
                    return True, {}, None
            else:
                return False, None, f"HTTP {response.status_code}"
    except httpx.ConnectError as e:
        return False, None, f"Connection failed: {e}"
    except httpx.TimeoutException:
        return False, None, "Connection timeout"
    except Exception as e:
        return False, None, str(e)


async def _discover_and_register_tools(
    name: str,
    url: str,
    transport: str,
    timeout: float,
) -> tuple[int, list[str], str | None]:
    """
    Connect to MCP server, discover tools, and register them.

    Returns:
        Tuple of (tools_count, tool_names, error_message)
    """
    try:
        config = MCPServerConfig(
            name=name,
            url=url,
            transport=MCPTransport(transport),
            timeout=timeout,
        )
        session = MCPClientSession(config)

        if not await session.connect():
            return 0, [], "MCP client connection failed"

        # Discover tools
        discovered_tools = await session.list_tools()
        tool_names = []

        # Register each tool
        for tool_info in discovered_tools:
            prefixed_name = f"{name}_{tool_info.name}"
            tool_names.append(prefixed_name)

            # Create executor that calls the MCP server
            original_name = tool_info.name
            server_url = url
            server_timeout = timeout

            def make_executor(tool_original_name: str, mcp_url: str, mcp_timeout: float):
                async def executor(args: dict) -> dict:
                    """Execute MCP tool via HTTP endpoint."""
                    tool_endpoint = f"{mcp_url.rstrip('/')}/tools/{tool_original_name}"
                    try:
                        async with httpx.AsyncClient(timeout=mcp_timeout) as client:
                            response = await client.get(tool_endpoint, params=args)
                            if response.status_code == 200:
                                data = response.json()
                                if "result" in data:
                                    return {"success": True, "result": data["result"]}
                                return {"success": True, "result": data}
                            else:
                                return {
                                    "success": False,
                                    "error": f"MCP tool returned HTTP {response.status_code}: {response.text[:200]}",
                                }
                    except httpx.ConnectError as e:
                        return {"success": False, "error": f"Failed to connect to MCP server: {e}"}
                    except Exception as e:
                        return {"success": False, "error": f"MCP tool execution failed: {e}"}
                return executor

            executor = make_executor(original_name, server_url, server_timeout)

            schema = {
                "name": prefixed_name,
                "description": tool_info.description or f"MCP tool from {name}",
                "parameters": tool_info.input_schema or {"type": "object", "properties": {}},
            }

            register_mcp_tool(
                name=prefixed_name,
                schema=schema,
                mcp_server=name,
                executor=executor,
                override=True,
            )

        await session.disconnect()
        return len(tool_names), tool_names, None

    except Exception as e:
        logger.error(f"Failed to discover/register tools from {name}: {e}")
        return 0, [], str(e)


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/servers",
    response_model=dict[str, Any],
    summary="List MCP Servers",
    description="Get list of all configured MCP servers with their status and registered tools.",
    tags=["MCP"],
)
async def list_mcp_servers(request: Request) -> dict[str, Any]:
    """
    List all configured MCP servers with status.

    Returns servers from both environment configuration and runtime additions.
    """
    start = time.time()
    servers_list: list[MCPServerInfo] = []

    # Get all servers
    all_servers = _get_all_servers()

    # Check status of each server
    for name, config in all_servers.items():
        url = config["url"]
        timeout = config.get("timeout", MCP_SERVER_TIMEOUT)
        source = config.get("source", "unknown")

        # Check health
        is_healthy, health_data, error = await _check_server_health(url, timeout=min(timeout, 5.0))

        # Get registered tools for this server
        registered_tools = list_mcp_tools(mcp_server=name)

        # Extract tools info from health response if available
        tools_count = health_data.get("tools_count", len(registered_tools)) if health_data else len(registered_tools)
        tool_names = health_data.get("tool_names", registered_tools) if health_data else registered_tools

        servers_list.append(
            MCPServerInfo(
                name=name,
                url=url,
                transport=config.get("transport", "sse"),
                timeout=timeout,
                status="healthy" if is_healthy else "unhealthy",
                tools_count=tools_count,
                tool_names=tool_names,
                error=error,
                source=source,
            )
        )

    # Also include status from app.state if available
    app_mcp_status = getattr(request.app.state, "mcp_servers_status", {})

    return {
        "status": "success",
        "total": len(servers_list),
        "servers": [s.model_dump() for s in servers_list],
        "startup_status": app_mcp_status,
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.post(
    "/servers",
    response_model=dict[str, Any],
    summary="Add MCP Server",
    description="Add a new MCP server connection at runtime and register its tools.",
    tags=["MCP"],
)
async def add_mcp_server(
    server: MCPServerRequest,
    request: Request,
) -> dict[str, Any]:
    """
    Add a new MCP server at runtime.

    This will:
    1. Connect to the MCP server
    2. Discover available tools
    3. Register tools in the central registry
    4. Make tools available for agent configuration
    """
    start = time.time()

    # Check if server name already exists
    all_servers = _get_all_servers()
    if server.name in all_servers:
        raise HTTPException(
            status_code=409,
            detail=f"MCP server '{server.name}' already exists. Use DELETE to remove it first.",
        )

    # Validate URL format
    if not server.url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="URL must start with http:// or https://",
        )

    # Check health first
    is_healthy, health_data, error = await _check_server_health(server.url, timeout=server.timeout)
    if not is_healthy:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to MCP server at {server.url}: {error}",
        )

    # Discover and register tools
    tools_count, tool_names, register_error = await _discover_and_register_tools(
        name=server.name,
        url=server.url,
        transport=server.transport,
        timeout=server.timeout,
    )

    if register_error:
        raise HTTPException(
            status_code=500,
            detail=f"Connected to server but failed to register tools: {register_error}",
        )

    # Store in runtime registry
    _RUNTIME_MCP_SERVERS[server.name] = MCPServerConfig(
        name=server.name,
        url=server.url,
        transport=MCPTransport(server.transport),
        timeout=server.timeout,
    )

    logger.info(
        f"Added MCP server '{server.name}' at {server.url} with {tools_count} tools: {tool_names}"
    )

    return {
        "status": "success",
        "message": f"MCP server '{server.name}' added successfully",
        "server": {
            "name": server.name,
            "url": server.url,
            "transport": server.transport,
            "timeout": server.timeout,
            "status": "healthy",
            "tools_count": tools_count,
            "tool_names": tool_names,
            "source": "runtime",
        },
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.post(
    "/servers/test",
    response_model=MCPTestResponse,
    summary="Test MCP Server Connection",
    description="Test connection to an MCP server and discover its tools without registering them.",
    tags=["MCP"],
)
async def test_mcp_server(
    server: MCPServerRequest,
) -> MCPTestResponse:
    """
    Test MCP server connection and discover tools.

    This is a read-only operation - tools are NOT registered.
    Use POST /servers to actually add the server and register tools.
    """
    start = time.time()

    # Validate URL format
    if not server.url.startswith(("http://", "https://")):
        return MCPTestResponse(
            status="error",
            url=server.url,
            connected=False,
            tools_count=0,
            tools=[],
            error="URL must start with http:// or https://",
            response_time_ms=round((time.time() - start) * 1000, 2),
        )

    # Check health
    is_healthy, health_data, error = await _check_server_health(server.url, timeout=server.timeout)
    if not is_healthy:
        return MCPTestResponse(
            status="unhealthy",
            url=server.url,
            connected=False,
            tools_count=0,
            tools=[],
            error=error,
            response_time_ms=round((time.time() - start) * 1000, 2),
        )

    # Try to discover tools
    tools: list[MCPToolInfo] = []
    try:
        config = MCPServerConfig(
            name=server.name,
            url=server.url,
            transport=MCPTransport(server.transport),
            timeout=server.timeout,
        )
        session = MCPClientSession(config)

        if await session.connect():
            discovered = await session.list_tools()
            for tool_info in discovered:
                tools.append(
                    MCPToolInfo(
                        name=tool_info.name,
                        prefixed_name=f"{server.name}_{tool_info.name}",
                        description=tool_info.description or f"Tool from {server.name}",
                        server_name=server.name,
                        input_schema=tool_info.input_schema or {"type": "object", "properties": {}},
                    )
                )
            await session.disconnect()
        else:
            error = "Failed to establish MCP client connection"

    except Exception as e:
        error = f"Tool discovery failed: {e}"
        logger.warning(f"Tool discovery failed for {server.url}: {e}")

    return MCPTestResponse(
        status="healthy" if tools else ("connected" if is_healthy else "unhealthy"),
        url=server.url,
        connected=is_healthy,
        tools_count=len(tools),
        tools=tools,
        error=error if not tools and error else None,
        response_time_ms=round((time.time() - start) * 1000, 2),
    )


@router.delete(
    "/servers/{name}",
    response_model=dict[str, Any],
    summary="Remove MCP Server",
    description="Remove an MCP server and unregister all its tools.",
    tags=["MCP"],
)
async def remove_mcp_server(
    name: str,
    request: Request,
) -> dict[str, Any]:
    """
    Remove an MCP server and unregister its tools.

    Only runtime-added servers can be removed. Environment-configured servers
    require environment variable changes and a restart.
    """
    start = time.time()

    # Check if server exists
    all_servers = _get_all_servers()
    if name not in all_servers:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server '{name}' not found",
        )

    # Check if it's a runtime server
    if name not in _RUNTIME_MCP_SERVERS:
        raise HTTPException(
            status_code=400,
            detail=f"MCP server '{name}' is configured via environment variables. "
            "To remove it, update MCP_ENABLED_SERVERS and restart the application.",
        )

    # Unregister tools
    tools_removed = unregister_mcp_tools(mcp_server=name)

    # Remove from runtime registry
    del _RUNTIME_MCP_SERVERS[name]

    logger.info(f"Removed MCP server '{name}' and {tools_removed} tools")

    return {
        "status": "success",
        "message": f"MCP server '{name}' removed successfully",
        "tools_removed": tools_removed,
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.get(
    "/tools",
    response_model=dict[str, Any],
    summary="List MCP Tools",
    description="Get list of all registered MCP tools across all servers.",
    tags=["MCP"],
)
async def list_all_mcp_tools(
    server: str | None = None,
) -> dict[str, Any]:
    """
    List all registered MCP tools.

    Args:
        server: Optional filter by MCP server name
    """
    start = time.time()

    tool_names = list_mcp_tools(mcp_server=server)

    # Group by server
    by_server: dict[str, list[str]] = {}
    for tool_name in tool_names:
        # Parse server name from prefixed tool name (format: "servername_toolname")
        parts = tool_name.split("_", 1)
        if len(parts) == 2:
            srv_name = parts[0]
            if srv_name not in by_server:
                by_server[srv_name] = []
            by_server[srv_name].append(tool_name)
        else:
            if "unknown" not in by_server:
                by_server["unknown"] = []
            by_server["unknown"].append(tool_name)

    return {
        "status": "success",
        "total": len(tool_names),
        "tools": tool_names,
        "by_server": by_server,
        "filter": {"server": server} if server else None,
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }
