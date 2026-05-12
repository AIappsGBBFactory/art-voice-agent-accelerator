"""
Use-Case Builder
================

Takes a UseCaseSpec (from the research service) and materialises it into a
live ART session by creating mock tools, session agents, and a session scenario.

All artefacts are session-scoped — they live in memory and do not touch the
on-disk agent/scenario/tool registries.  Tool names are prefixed with the
session ID (first 8 chars) to avoid cross-session collisions.
"""

from __future__ import annotations

import json
from typing import Any

from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig as AgentHandoffConfig,
)
from apps.artagent.backend.registries.agentstore.base import (
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.registries.scenariostore.loader import (
    GenericHandoffConfig,
    HandoffConfig as ScenarioHandoffConfig,
    ScenarioConfig,
)
from apps.artagent.backend.registries.toolstore.registry import register_tool
from apps.artagent.backend.src.customer_research.models import (
    BuildResult,
    ToolSpec,
    UseCaseSpec,
)
from apps.artagent.backend.src.orchestration.session_agents import set_session_agent
from apps.artagent.backend.src.orchestration.session_scenarios import (
    set_session_scenario_async,
)
from utils.ml_logging import get_logger

logger = get_logger("customer_research.builder")


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


def _validate_use_case(use_case: UseCaseSpec) -> None:
    """Raise ValueError if the use-case spec is semantically inconsistent."""
    agent_names = {a.name for a in use_case.agents}
    tool_names = {t.name for t in use_case.tools}

    # start_agent must exist
    if use_case.start_agent not in agent_names:
        raise ValueError(
            f"start_agent '{use_case.start_agent}' is not in agents list: {sorted(agent_names)}"
        )

    # agent names must be unique
    if len(agent_names) != len(use_case.agents):
        raise ValueError("Duplicate agent names detected")

    # tool names must be unique
    if len(tool_names) != len(use_case.tools):
        raise ValueError("Duplicate tool names detected")

    # agents' tool references must exist (in business tools OR handoff tools)
    # Auto-create stub tools for any missing references (LLM can be inconsistent)
    handoff_tool_names = {h.tool for h in use_case.handoffs}
    all_known_tools = tool_names | handoff_tool_names
    for agent in use_case.agents:
        missing = [t for t in agent.tools if t not in all_known_tools]
        for tool_name in missing:
            stub = ToolSpec(
                name=tool_name,
                description=f"Auto-generated stub for {tool_name.replace('_', ' ')}",
                mock_response='{"status": "ok"}',
            )
            use_case.tools.append(stub)
            tool_names.add(tool_name)
            all_known_tools.add(tool_name)
            logger.warning(
                "Auto-created stub tool '%s' referenced by agent '%s'",
                tool_name,
                agent.name,
            )

    # handoff agents must exist
    for h in use_case.handoffs:
        if h.from_agent not in agent_names:
            raise ValueError(f"Handoff from unknown agent: '{h.from_agent}'")
        if h.to_agent not in agent_names:
            raise ValueError(f"Handoff to unknown agent: '{h.to_agent}'")


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION-SCOPED NAMING
# ═══════════════════════════════════════════════════════════════════════════════


def _session_prefix(session_id: str) -> str:
    """Short session prefix for tool-name namespacing."""
    return session_id[:8]


def _scope_names(session_id: str, use_case: UseCaseSpec) -> UseCaseSpec:
    """Return a copy of the use-case with all tool names session-scoped.

    This rewrites tool names in tool specs, agent tool lists, and handoff edges
    so every reference is consistent.
    """
    prefix = _session_prefix(session_id)
    name_map: dict[str, str] = {}

    # Build name map for business tools
    for tool in use_case.tools:
        scoped = f"{prefix}_{tool.name}"
        name_map[tool.name] = scoped

    # Build name map for handoff tools
    for h in use_case.handoffs:
        scoped = f"{prefix}_{h.tool}"
        name_map[h.tool] = scoped

    # Rewrite
    from apps.artagent.backend.src.customer_research.models import (
        AgentSpec,
        HandoffSpec,
        ToolSpec,
    )

    scoped_tools = [
        ToolSpec(
            name=name_map.get(t.name, t.name),
            description=t.description,
            parameters=t.parameters,
            required_params=t.required_params,
            mock_response=t.mock_response,
        )
        for t in use_case.tools
    ]

    scoped_agents = [
        AgentSpec(
            name=a.name,
            description=a.description,
            greeting=a.greeting,
            return_greeting=a.return_greeting,
            prompt=a.prompt,
            tools=[name_map.get(tn, tn) for tn in a.tools],
            handoff_trigger=name_map.get(a.handoff_trigger, a.handoff_trigger)
            if a.handoff_trigger
            else "",
        )
        for a in use_case.agents
    ]

    scoped_handoffs = [
        HandoffSpec(
            from_agent=h.from_agent,
            to_agent=h.to_agent,
            tool=name_map.get(h.tool, h.tool),
            type=h.type,
            handoff_condition=h.handoff_condition,
        )
        for h in use_case.handoffs
    ]

    return UseCaseSpec(
        name=use_case.name,
        description=use_case.description,
        icon=use_case.icon,
        industry=use_case.industry,
        agents=scoped_agents,
        tools=scoped_tools,
        handoffs=scoped_handoffs,
        start_agent=use_case.start_agent,
        template_vars=use_case.template_vars,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK TOOL FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def _build_mock_executor(mock_response: str) -> Any:
    """Return an async callable that always returns *mock_response* as a dict."""
    try:
        frozen = json.loads(mock_response)
    except (json.JSONDecodeError, TypeError):
        frozen = {"result": mock_response}

    async def _executor(arguments: dict[str, Any] | str = "") -> dict:
        return frozen

    return _executor


def _register_mock_tools(use_case: UseCaseSpec) -> list[str]:
    """Register mock tools from the use-case spec.  Returns list of tool names."""
    created: list[str] = []

    for tool_spec in use_case.tools:
        properties: dict[str, Any] = {}
        for param in tool_spec.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }

        schema: dict[str, Any] = {
            "name": tool_spec.name,
            "description": tool_spec.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": tool_spec.required_params,
            },
        }

        executor = _build_mock_executor(tool_spec.mock_response)

        register_tool(
            name=tool_spec.name,
            schema=schema,
            executor=executor,
            is_handoff=False,
            tags={"mock", "customer-research"},
            override=True,
        )
        created.append(tool_spec.name)
        logger.debug("Registered mock tool: %s", tool_spec.name)

    return created


# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF TOOL FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def _register_handoff_tools(use_case: UseCaseSpec) -> list[str]:
    """Register handoff tool stubs for every edge in the handoff graph."""
    created: list[str] = []
    seen: set[str] = set()

    for edge in use_case.handoffs:
        tool_name = edge.tool
        if tool_name in seen:
            continue
        seen.add(tool_name)

        schema: dict[str, Any] = {
            "name": tool_name,
            "description": f"Transfer the conversation to {edge.to_agent}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief reason for the handoff",
                    },
                },
                "required": [],
            },
        }

        async def _handoff_executor(arguments: dict[str, Any] | str = "") -> dict:
            return {"status": "transferred"}

        register_tool(
            name=tool_name,
            schema=schema,
            executor=_handoff_executor,
            is_handoff=True,
            tags={"handoff", "customer-research"},
            override=True,
        )
        created.append(tool_name)

    return created


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT POST-PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════


def _inject_handoff_instructions(use_case: UseCaseSpec) -> None:
    """Append explicit handoff routing constraints to each agent's prompt.

    This ensures the LLM only attempts handoffs to agents that actually
    exist in the scenario, preventing hallucinated agent-name references.
    """
    for agent_spec in use_case.agents:
        # Gather outgoing handoff targets for this agent
        targets = [
            h.to_agent
            for h in use_case.handoffs
            if h.from_agent == agent_spec.name
        ]
        if not targets:
            # Agent has no outgoing handoffs — add instruction not to hand off
            agent_spec.prompt += (
                "\n\n## Handoff Policy\n"
                "You do not have handoff capabilities. Handle the customer's "
                "request within your expertise or politely let them know you "
                "cannot help with that specific request."
            )
            continue

        target_list = ", ".join(targets)
        agent_spec.prompt += (
            "\n\n## Handoff Policy\n"
            "You MUST use the `handoff_to_agent` tool to transfer the "
            "conversation when needed. Your ONLY valid handoff targets are: "
            f"{target_list}.\n"
            "Do NOT attempt to hand off to any agent not listed above.\n"
            "Do NOT announce or narrate the transfer — simply call the tool "
            "silently. The target agent will continue the conversation seamlessly."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def _create_session_agents(
    session_id: str, use_case: UseCaseSpec
) -> list[str]:
    """Create UnifiedAgent instances and store them as session agents."""
    created: list[str] = []

    for agent_spec in use_case.agents:
        # Collect tool names: agent's own tools + handoff tools originating from this agent
        tool_names = list(agent_spec.tools)
        for edge in use_case.handoffs:
            if edge.from_agent == agent_spec.name and edge.tool not in tool_names:
                tool_names.append(edge.tool)

        agent = UnifiedAgent(
            name=agent_spec.name,
            description=agent_spec.description,
            greeting=agent_spec.greeting,
            return_greeting=agent_spec.return_greeting,
            handoff=AgentHandoffConfig(trigger=agent_spec.handoff_trigger),
            tool_names=tool_names,
            prompt_template=agent_spec.prompt,
            voice=VoiceConfig(name="en-US-AlloyTurboMultilingualNeural"),
            cascade_model=ModelConfig(deployment_id="gpt-4o"),
            voicelive_model=ModelConfig(deployment_id="gpt-4o-realtime"),
            session={
                "modalities": ["TEXT", "AUDIO"],
                "input_audio_format": "PCM16",
                "output_audio_format": "PCM16",
                "input_audio_transcription_settings": {
                    "model": "azure-speech",
                    "language": "en-US",
                },
                "turn_detection": {
                    "type": "azure_semantic_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 240,
                    "silence_duration_ms": 700,
                },
                "tool_choice": "auto",
            },
        )

        is_start = agent_spec.name == use_case.start_agent
        set_session_agent(session_id, agent, set_active=is_start)
        created.append(agent_spec.name)
        logger.debug("Created session agent: %s (start=%s)", agent_spec.name, is_start)

    return created


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


async def _create_session_scenario(
    session_id: str, use_case: UseCaseSpec
) -> str:
    """Build a ScenarioConfig from the use-case spec and persist it."""

    handoffs = [
        ScenarioHandoffConfig(
            from_agent=h.from_agent,
            to_agent=h.to_agent,
            tool=h.tool,
            type="discrete",
            handoff_condition=h.handoff_condition,
            share_context=True,
        )
        for h in use_case.handoffs
    ]

    scenario = ScenarioConfig(
        name=use_case.name,
        description=use_case.description,
        icon=use_case.icon,
        agents=[a.name for a in use_case.agents],
        start_agent=use_case.start_agent,
        handoff_type="discrete",
        handoffs=handoffs,
        global_template_vars=use_case.template_vars,
        generic_handoff=GenericHandoffConfig(
            enabled=True,
            share_context=True,
            default_type="discrete",
        ),
    )

    await set_session_scenario_async(session_id, scenario)
    logger.info("Created session scenario: %s", use_case.name)
    return use_case.name


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


async def build_use_case(session_id: str, use_case: UseCaseSpec) -> BuildResult:
    """
    Build a complete use case into a live ART session.

    Steps:
        0. Validate semantic consistency
        1. Scope tool names with session prefix to avoid cross-session collisions
        2. Register mock tools
        3. Register handoff tools
        4. Create session agents (with tool references)
        5. Create and activate the session scenario

    Args:
        session_id: Target session identifier.
        use_case: Fully-specified use-case from the research service.

    Returns:
        BuildResult with created artefact names.

    Raises:
        ValueError: If the use-case spec is semantically invalid.
    """
    # 0. Validate before mutating any state
    _validate_use_case(use_case)

    # 1. Prefix tool names with session ID for isolation
    scoped = _scope_names(session_id, use_case)

    logger.info(
        "Building use case | session=%s use_case=%s agents=%d tools=%d",
        session_id,
        scoped.name,
        len(scoped.agents),
        len(scoped.tools),
    )

    # 2. Inject explicit handoff routing into agent prompts
    _inject_handoff_instructions(scoped)

    # 3. Tools first — agents reference them
    mock_tools = _register_mock_tools(scoped)
    handoff_tools = _register_handoff_tools(scoped)
    all_tools = mock_tools + handoff_tools

    # 4. Agents — reference tools by name
    agents_created = _create_session_agents(session_id, scoped)

    # 5. Scenario — wires agents together with handoff graph
    scenario_name = await _create_session_scenario(session_id, scoped)

    logger.info(
        "Build complete | session=%s scenario=%s agents=%s tools=%s",
        session_id,
        scenario_name,
        agents_created,
        all_tools,
    )

    return BuildResult(
        session_id=session_id,
        scenario_name=scenario_name,
        agents_created=agents_created,
        tools_created=all_tools,
    )
