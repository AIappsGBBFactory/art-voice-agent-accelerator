"""
Scenario Builder Endpoints
==========================

REST endpoints for dynamically creating and managing scenarios at runtime.
Supports session-scoped scenario configurations that can be modified through
the frontend without restarting the backend.

Scenarios define:
- Which agents are available
- Handoff routing between agents (directed graph)
- Handoff behavior (announced vs discrete)
- Agent overrides (greetings, template vars)
- Starting agent

Endpoints:
    GET  /api/v1/scenario-builder/templates     - List available scenario templates
    GET  /api/v1/scenario-builder/templates/{id} - Get scenario template details
    GET  /api/v1/scenario-builder/agents        - List available agents for scenarios
    GET  /api/v1/scenario-builder/defaults      - Get default scenario configuration
    POST /api/v1/scenario-builder/create        - Create dynamic scenario for session
    GET  /api/v1/scenario-builder/session/{session_id} - Get session scenario config
    PUT  /api/v1/scenario-builder/session/{session_id} - Update session scenario config
    DELETE /api/v1/scenario-builder/session/{session_id} - Reset to default scenario
    GET  /api/v1/scenario-builder/sessions      - List all sessions with custom scenarios
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.artagent.backend.registries.agentstore.loader import discover_agents
from apps.artagent.backend.registries.scenariostore.loader import (
    AgentOverride,
    HandoffConfig,
    ScenarioConfig,
    _SCENARIOS_DIR,
    list_scenarios,
    load_scenario,
)
from apps.artagent.backend.src.orchestration.session_scenarios import (
    get_session_scenario,
    list_session_scenarios,
    remove_session_scenario,
    set_session_scenario,
)
from utils.ml_logging import get_logger

logger = get_logger("v1.scenario_builder")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════


class HandoffConfigSchema(BaseModel):
    """Configuration for a handoff route - a directed edge in the agent graph."""

    from_agent: str = Field(..., description="Source agent initiating the handoff")
    to_agent: str = Field(..., description="Target agent receiving the handoff")
    tool: str = Field(..., description="Handoff tool name that triggers this route")
    type: str = Field(
        default="announced",
        description="'discrete' (silent) or 'announced' (greet on switch)",
    )
    share_context: bool = Field(
        default=True, description="Whether to pass conversation context"
    )


class AgentOverrideSchema(BaseModel):
    """Override settings for a specific agent in a scenario."""

    greeting: str | None = Field(default=None, description="Custom greeting override")
    return_greeting: str | None = Field(
        default=None, description="Custom return greeting override"
    )
    description: str | None = Field(
        default=None, description="Custom description override"
    )
    template_vars: dict[str, Any] = Field(
        default_factory=dict, description="Template variable overrides"
    )
    voice_name: str | None = Field(default=None, description="Voice name override")
    voice_rate: str | None = Field(default=None, description="Voice rate override")


class DynamicScenarioConfig(BaseModel):
    """Configuration for creating a dynamic scenario."""

    name: str = Field(
        ..., min_length=1, max_length=64, description="Scenario display name"
    )
    description: str = Field(
        default="", max_length=512, description="Scenario description"
    )
    agents: list[str] = Field(
        default_factory=list,
        description="List of agent names to include (empty = all agents)",
    )
    start_agent: str | None = Field(
        default=None, description="Starting agent for the scenario"
    )
    handoff_type: str = Field(
        default="announced",
        description="Default handoff behavior ('announced' or 'discrete')",
    )
    handoffs: list[HandoffConfigSchema] = Field(
        default_factory=list,
        description="List of handoff configurations (directed edges)",
    )
    agent_defaults: AgentOverrideSchema | None = Field(
        default=None, description="Default overrides applied to all agents"
    )
    global_template_vars: dict[str, Any] = Field(
        default_factory=dict, description="Global template variables for all agents"
    )
    tools: list[str] = Field(
        default_factory=list, description="Additional tools to register for scenario"
    )


class SessionScenarioResponse(BaseModel):
    """Response for session scenario operations."""

    session_id: str
    scenario_name: str
    status: str
    config: dict[str, Any]
    created_at: float | None = None
    modified_at: float | None = None


class ScenarioTemplateInfo(BaseModel):
    """Scenario template information for frontend display."""

    id: str
    name: str
    description: str
    agents: list[str]
    start_agent: str | None
    handoff_type: str
    handoffs: list[dict[str, Any]]
    global_template_vars: dict[str, Any]


class AgentInfo(BaseModel):
    """Agent information for scenario configuration."""

    name: str
    description: str
    greeting: str | None = None
    tools: list[str] = []
    is_entry_point: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/templates",
    response_model=dict[str, Any],
    summary="List Available Scenario Templates",
    description="Get list of all existing scenario configurations that can be used as templates.",
    tags=["Scenario Builder"],
)
async def list_scenario_templates() -> dict[str, Any]:
    """
    List all available scenario templates from the scenarios directory.

    Returns scenario configurations that can be used as starting points
    for creating new dynamic scenarios.
    """
    start = time.time()
    templates: list[ScenarioTemplateInfo] = []

    scenario_names = list_scenarios()

    for name in scenario_names:
        scenario = load_scenario(name)
        if scenario:
            templates.append(
                ScenarioTemplateInfo(
                    id=name,
                    name=scenario.name,
                    description=scenario.description,
                    agents=scenario.agents,
                    start_agent=scenario.start_agent,
                    handoff_type=scenario.handoff_type,
                    handoffs=[
                        {
                            "from_agent": h.from_agent,
                            "to_agent": h.to_agent,
                            "tool": h.tool,
                            "type": h.type,
                            "share_context": h.share_context,
                        }
                        for h in scenario.handoffs
                    ],
                    global_template_vars=scenario.global_template_vars,
                )
            )

    # Sort by name
    templates.sort(key=lambda t: t.name)

    return {
        "status": "success",
        "total": len(templates),
        "templates": [t.model_dump() for t in templates],
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.get(
    "/templates/{template_id}",
    response_model=dict[str, Any],
    summary="Get Scenario Template Details",
    description="Get full details of a specific scenario template.",
    tags=["Scenario Builder"],
)
async def get_scenario_template(template_id: str) -> dict[str, Any]:
    """
    Get the full configuration of a specific scenario template.

    Args:
        template_id: The scenario directory name (e.g., 'banking', 'insurance')
    """
    scenario = load_scenario(template_id)

    if not scenario:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario template '{template_id}' not found",
        )

    return {
        "status": "success",
        "template": {
            "id": template_id,
            "name": scenario.name,
            "description": scenario.description,
            "agents": scenario.agents,
            "start_agent": scenario.start_agent,
            "handoff_type": scenario.handoff_type,
            "handoffs": [
                {
                    "from_agent": h.from_agent,
                    "to_agent": h.to_agent,
                    "tool": h.tool,
                    "type": h.type,
                    "share_context": h.share_context,
                }
                for h in scenario.handoffs
            ],
            "global_template_vars": scenario.global_template_vars,
            "agent_defaults": (
                {
                    "greeting": scenario.agent_defaults.greeting,
                    "return_greeting": scenario.agent_defaults.return_greeting,
                    "description": scenario.agent_defaults.description,
                    "template_vars": scenario.agent_defaults.template_vars,
                    "voice_name": scenario.agent_defaults.voice_name,
                    "voice_rate": scenario.agent_defaults.voice_rate,
                }
                if scenario.agent_defaults
                else None
            ),
        },
    }


@router.get(
    "/agents",
    response_model=dict[str, Any],
    summary="List Available Agents",
    description="Get list of all registered agents that can be included in scenarios.",
    tags=["Scenario Builder"],
)
async def list_available_agents() -> dict[str, Any]:
    """
    List all available agents for scenario configuration.

    Returns agent information for building scenario orchestration graphs.
    """
    start = time.time()

    agents_registry = discover_agents()
    agents_list: list[AgentInfo] = []

    for name, agent in agents_registry.items():
        agents_list.append(
            AgentInfo(
                name=name,
                description=agent.description or "",
                greeting=agent.greeting,
                tools=agent.tool_names if hasattr(agent, "tool_names") else [],
                is_entry_point=name.lower() == "concierge"
                or "concierge" in name.lower(),
            )
        )

    # Sort by name, with entry points first
    agents_list.sort(key=lambda a: (not a.is_entry_point, a.name))

    return {
        "status": "success",
        "total": len(agents_list),
        "agents": [a.model_dump() for a in agents_list],
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.get(
    "/defaults",
    response_model=dict[str, Any],
    summary="Get Default Scenario Configuration",
    description="Get the default configuration template for creating new scenarios.",
    tags=["Scenario Builder"],
)
async def get_default_config() -> dict[str, Any]:
    """Get default scenario configuration for creating new scenarios."""
    # Get available agents for reference
    agents_registry = discover_agents()
    agent_names = list(agents_registry.keys())

    return {
        "status": "success",
        "defaults": {
            "name": "Custom Scenario",
            "description": "",
            "agents": [],  # Empty = all agents
            "start_agent": agent_names[0] if agent_names else None,
            "handoff_type": "announced",
            "handoffs": [],
            "global_template_vars": {
                "company_name": "ART Voice Agent",
                "industry": "general",
            },
            "agent_defaults": None,
        },
        "available_agents": agent_names,
        "handoff_types": ["announced", "discrete"],
    }


@router.post(
    "/create",
    response_model=SessionScenarioResponse,
    summary="Create Dynamic Scenario",
    description="Create a new dynamic scenario configuration for a session.",
    tags=["Scenario Builder"],
)
async def create_dynamic_scenario(
    config: DynamicScenarioConfig,
    session_id: str,
    request: Request,
) -> SessionScenarioResponse:
    """
    Create a dynamic scenario for a specific session.

    This scenario will be used instead of the default for this session.
    The configuration is stored in memory and can be modified at runtime.
    """
    start = time.time()

    # Validate agents exist
    agents_registry = discover_agents()
    if config.agents:
        invalid_agents = [a for a in config.agents if a not in agents_registry]
        if invalid_agents:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid agents: {invalid_agents}. Available: {list(agents_registry.keys())}",
            )

    # Validate start_agent
    if config.start_agent:
        if config.agents and config.start_agent not in config.agents:
            raise HTTPException(
                status_code=400,
                detail=f"start_agent '{config.start_agent}' must be in agents list",
            )
        if not config.agents and config.start_agent not in agents_registry:
            raise HTTPException(
                status_code=400,
                detail=f"start_agent '{config.start_agent}' not found in registry",
            )

    # Build agent_defaults
    agent_defaults = None
    if config.agent_defaults:
        agent_defaults = AgentOverride(
            greeting=config.agent_defaults.greeting,
            return_greeting=config.agent_defaults.return_greeting,
            description=config.agent_defaults.description,
            template_vars=config.agent_defaults.template_vars,
            voice_name=config.agent_defaults.voice_name,
            voice_rate=config.agent_defaults.voice_rate,
        )

    # Build handoff configs
    handoffs: list[HandoffConfig] = []
    for h in config.handoffs:
        handoffs.append(
            HandoffConfig(
                from_agent=h.from_agent,
                to_agent=h.to_agent,
                tool=h.tool,
                type=h.type,
                share_context=h.share_context,
            )
        )

    # Create the scenario
    scenario = ScenarioConfig(
        name=config.name,
        description=config.description,
        agents=config.agents,
        agent_defaults=agent_defaults,
        global_template_vars=config.global_template_vars,
        tools=config.tools,
        start_agent=config.start_agent,
        handoff_type=config.handoff_type,
        handoffs=handoffs,
    )

    # Store in session
    set_session_scenario(session_id, scenario)

    logger.info(
        "Dynamic scenario created | session=%s name=%s agents=%d handoffs=%d",
        session_id,
        config.name,
        len(config.agents),
        len(config.handoffs),
    )

    return SessionScenarioResponse(
        session_id=session_id,
        scenario_name=config.name,
        status="created",
        config={
            "name": config.name,
            "description": config.description,
            "agents": config.agents,
            "start_agent": config.start_agent,
            "handoff_type": config.handoff_type,
            "handoffs": [
                {
                    "from_agent": h.from_agent,
                    "to_agent": h.to_agent,
                    "tool": h.tool,
                    "type": h.type,
                    "share_context": h.share_context,
                }
                for h in handoffs
            ],
            "global_template_vars": config.global_template_vars,
        },
        created_at=time.time(),
    )


@router.get(
    "/session/{session_id}",
    response_model=SessionScenarioResponse,
    summary="Get Session Scenario",
    description="Get the current dynamic scenario configuration for a session.",
    tags=["Scenario Builder"],
)
async def get_session_scenario_config(
    session_id: str,
    request: Request,
) -> SessionScenarioResponse:
    """Get the dynamic scenario for a session."""
    scenario = get_session_scenario(session_id)

    if not scenario:
        raise HTTPException(
            status_code=404,
            detail=f"No dynamic scenario found for session '{session_id}'",
        )

    return SessionScenarioResponse(
        session_id=session_id,
        scenario_name=scenario.name,
        status="active",
        config={
            "name": scenario.name,
            "description": scenario.description,
            "agents": scenario.agents,
            "start_agent": scenario.start_agent,
            "handoff_type": scenario.handoff_type,
            "handoffs": [
                {
                    "from_agent": h.from_agent,
                    "to_agent": h.to_agent,
                    "tool": h.tool,
                    "type": h.type,
                    "share_context": h.share_context,
                }
                for h in scenario.handoffs
            ],
            "global_template_vars": scenario.global_template_vars,
            "agent_defaults": (
                {
                    "greeting": scenario.agent_defaults.greeting,
                    "return_greeting": scenario.agent_defaults.return_greeting,
                    "description": scenario.agent_defaults.description,
                    "template_vars": scenario.agent_defaults.template_vars,
                    "voice_name": scenario.agent_defaults.voice_name,
                    "voice_rate": scenario.agent_defaults.voice_rate,
                }
                if scenario.agent_defaults
                else None
            ),
        },
    )


@router.put(
    "/session/{session_id}",
    response_model=SessionScenarioResponse,
    summary="Update Session Scenario",
    description="Update the dynamic scenario configuration for a session.",
    tags=["Scenario Builder"],
)
async def update_session_scenario(
    session_id: str,
    config: DynamicScenarioConfig,
    request: Request,
) -> SessionScenarioResponse:
    """
    Update the dynamic scenario for a session.

    Creates a new scenario if one doesn't exist.
    """
    # Validate agents exist
    agents_registry = discover_agents()
    if config.agents:
        invalid_agents = [a for a in config.agents if a not in agents_registry]
        if invalid_agents:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid agents: {invalid_agents}. Available: {list(agents_registry.keys())}",
            )

    # Validate start_agent
    if config.start_agent:
        if config.agents and config.start_agent not in config.agents:
            raise HTTPException(
                status_code=400,
                detail=f"start_agent '{config.start_agent}' must be in agents list",
            )
        if not config.agents and config.start_agent not in agents_registry:
            raise HTTPException(
                status_code=400,
                detail=f"start_agent '{config.start_agent}' not found in registry",
            )

    existing = get_session_scenario(session_id)
    created_at = time.time()

    # Build agent_defaults
    agent_defaults = None
    if config.agent_defaults:
        agent_defaults = AgentOverride(
            greeting=config.agent_defaults.greeting,
            return_greeting=config.agent_defaults.return_greeting,
            description=config.agent_defaults.description,
            template_vars=config.agent_defaults.template_vars,
            voice_name=config.agent_defaults.voice_name,
            voice_rate=config.agent_defaults.voice_rate,
        )

    # Build handoff configs
    handoffs: list[HandoffConfig] = []
    for h in config.handoffs:
        handoffs.append(
            HandoffConfig(
                from_agent=h.from_agent,
                to_agent=h.to_agent,
                tool=h.tool,
                type=h.type,
                share_context=h.share_context,
            )
        )

    # Create the updated scenario
    scenario = ScenarioConfig(
        name=config.name,
        description=config.description,
        agents=config.agents,
        agent_defaults=agent_defaults,
        global_template_vars=config.global_template_vars,
        tools=config.tools,
        start_agent=config.start_agent,
        handoff_type=config.handoff_type,
        handoffs=handoffs,
    )

    # Store in session
    set_session_scenario(session_id, scenario)

    logger.info(
        "Dynamic scenario updated | session=%s name=%s agents=%d handoffs=%d",
        session_id,
        config.name,
        len(config.agents),
        len(config.handoffs),
    )

    return SessionScenarioResponse(
        session_id=session_id,
        scenario_name=config.name,
        status="updated" if existing else "created",
        config={
            "name": config.name,
            "description": config.description,
            "agents": config.agents,
            "start_agent": config.start_agent,
            "handoff_type": config.handoff_type,
            "handoffs": [
                {
                    "from_agent": h.from_agent,
                    "to_agent": h.to_agent,
                    "tool": h.tool,
                    "type": h.type,
                    "share_context": h.share_context,
                }
                for h in handoffs
            ],
            "global_template_vars": config.global_template_vars,
        },
        created_at=created_at,
        modified_at=time.time(),
    )


@router.delete(
    "/session/{session_id}",
    summary="Reset Session Scenario",
    description="Remove the dynamic scenario for a session, reverting to default behavior.",
    tags=["Scenario Builder"],
)
async def reset_session_scenario(
    session_id: str,
    request: Request,
) -> dict[str, Any]:
    """Remove the dynamic scenario for a session."""
    removed = remove_session_scenario(session_id)

    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No dynamic scenario found for session '{session_id}'",
        )

    logger.info("Dynamic scenario removed | session=%s", session_id)

    return {
        "status": "success",
        "message": f"Scenario removed for session '{session_id}'",
        "session_id": session_id,
    }


@router.get(
    "/sessions",
    summary="List All Session Scenarios",
    description="List all sessions with dynamic scenarios configured.",
    tags=["Scenario Builder"],
)
async def list_session_scenarios_endpoint() -> dict[str, Any]:
    """List all sessions with custom scenarios."""
    scenarios = list_session_scenarios()

    return {
        "status": "success",
        "total": len(scenarios),
        "sessions": [
            {
                "session_id": session_id,
                "scenario_name": scenario.name,
                "agents": scenario.agents,
                "start_agent": scenario.start_agent,
                "handoff_count": len(scenario.handoffs),
            }
            for session_id, scenario in scenarios.items()
        ],
    }


@router.post(
    "/reload-scenarios",
    summary="Reload Scenario Templates",
    description="Re-discover and reload all scenario templates from disk.",
    tags=["Scenario Builder"],
)
async def reload_scenario_templates(request: Request) -> dict[str, Any]:
    """
    Reload all scenario templates from disk.

    This clears the scenario cache and re-discovers scenarios
    from the scenariostore directory.
    """
    from apps.artagent.backend.registries.scenariostore.loader import (
        _SCENARIOS,
        _discover_scenarios,
    )

    # Clear the cache
    _SCENARIOS.clear()

    # Re-discover scenarios
    _discover_scenarios()

    scenario_names = list_scenarios()

    logger.info("Scenario templates reloaded | count=%d", len(scenario_names))

    return {
        "status": "success",
        "message": f"Reloaded {len(scenario_names)} scenario templates",
        "scenarios": scenario_names,
    }
