"""
Handoff Service
===============

Unified handoff resolution for all orchestrators (Cascade and VoiceLive).

This service provides a single source of truth for:
- Detecting handoff tools
- Resolving handoff targets from scenario config or handoff maps
- Getting handoff behavior (discrete/announced, share_context)
- Building consistent system_vars for agent switches
- Selecting appropriate greetings based on handoff mode

Usage:
    from apps.artagent.backend.voice.shared.handoff_service import HandoffService

    # Create service (typically once per session)
    service = HandoffService(
        scenario_name="banking",
        handoff_map={"handoff_fraud": "FraudAgent"},
        agents=agent_registry,
    )

    # Check if tool triggers handoff
    if service.is_handoff("handoff_fraud"):
        # Resolve the handoff
        resolution = service.resolve_handoff(
            tool_name="handoff_fraud",
            tool_args={"reason": "fraud inquiry"},
            source_agent="Concierge",
            current_system_vars={"session_profile": {...}},
            user_last_utterance="I think my card was stolen",
        )

        # Use resolution to switch agents
        await orchestrator.switch_to(
            resolution.target_agent,
            resolution.system_vars,
        )

        # Get greeting if announced handoff
        greeting = service.select_greeting(
            agent=agents[resolution.target_agent],
            is_first_visit=True,
            greet_on_switch=resolution.greet_on_switch,
            system_vars=resolution.system_vars,
        )

See Also:
    - docs/proposals/handoff-consolidation-plan.md
    - apps/artagent/backend/registries/scenariostore/loader.py
    - apps/artagent/backend/voice/handoffs/context.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from apps.artagent.backend.registries.scenariostore.loader import (
    HandoffConfig,
    get_handoff_config,
)
from apps.artagent.backend.registries.toolstore.registry import (
    is_handoff_tool as registry_is_handoff_tool,
)
from apps.artagent.backend.voice.handoffs.context import (
    build_handoff_system_vars,
    sanitize_handoff_context,
)

if TYPE_CHECKING:
    from apps.artagent.backend.registries.agentstore.base import UnifiedAgent
    from src.stateful.state_managment import MemoManager

try:
    from utils.ml_logging import get_logger

    logger = get_logger("voice.shared.handoff_service")
except ImportError:
    import logging

    logger = logging.getLogger("voice.shared.handoff_service")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class HandoffResolution:
    """
    Result of resolving a handoff tool call.

    Contains all information needed by an orchestrator to execute the
    agent switch consistently, regardless of orchestration mode.

    Attributes:
        success: Whether handoff resolution succeeded
        target_agent: Name of the agent to switch to
        source_agent: Name of the agent initiating the handoff
        tool_name: The handoff tool that triggered this resolution
        system_vars: Pre-built system_vars for agent.apply_session()
        greet_on_switch: Whether target agent should announce the handoff
        share_context: Whether to pass conversation context to target
        handoff_type: "discrete" (silent) or "announced" (greeting)
        error: Error message if success=False

    Example:
        resolution = service.resolve_handoff(...)
        if resolution.success:
            await self._switch_to(resolution.target_agent, resolution.system_vars)
            if resolution.greet_on_switch:
                greeting = service.select_greeting(...)
    """

    success: bool
    target_agent: str = ""
    source_agent: str = ""
    tool_name: str = ""
    system_vars: dict[str, Any] = field(default_factory=dict)
    greet_on_switch: bool = True
    share_context: bool = True
    handoff_type: str = "announced"  # "discrete" or "announced"
    error: str | None = None

    @property
    def is_discrete(self) -> bool:
        """Check if this is a discrete (silent) handoff."""
        return self.handoff_type == "discrete"

    @property
    def is_announced(self) -> bool:
        """Check if this is an announced (greeting) handoff."""
        return self.handoff_type == "announced"


# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class HandoffService:
    """
    Unified handoff resolution for Cascade and VoiceLive orchestrators.

    This service encapsulates all handoff logic to ensure consistent behavior:
    - Scenario store configs are always respected
    - Greeting selection follows the same rules
    - System vars are built the same way

    The service is stateless and can be shared across turns within a session.
    Session-specific state (like visited_agents) should be passed as arguments.

    Attributes:
        scenario_name: Active scenario (e.g., "banking", "insurance")
        handoff_map: Static tool→agent mapping (fallback if no scenario)
        agents: Registry of available agents

    Example:
        service = HandoffService(
            scenario_name="banking",
            handoff_map=build_handoff_map(agents),
            agents=discover_agents(),
        )
    """

    def __init__(
        self,
        scenario_name: str | None = None,
        handoff_map: dict[str, str] | None = None,
        agents: dict[str, UnifiedAgent] | None = None,
        memo_manager: MemoManager | None = None,
    ) -> None:
        """
        Initialize HandoffService.

        Args:
            scenario_name: Active scenario name (for config lookup)
            handoff_map: Static tool→agent mapping (fallback)
            agents: Registry of available agents
            memo_manager: Optional MemoManager for session state access
        """
        self._scenario_name = scenario_name
        self._handoff_map = handoff_map or {}
        self._agents = agents or {}
        self._memo_manager = memo_manager

        logger.debug(
            "HandoffService initialized | scenario=%s agents=%d handoff_tools=%d",
            scenario_name or "(none)",
            len(self._agents),
            len(self._handoff_map),
        )

    # ───────────────────────────────────────────────────────────────────────────
    # Properties
    # ───────────────────────────────────────────────────────────────────────────

    @property
    def scenario_name(self) -> str | None:
        """Get the active scenario name."""
        return self._scenario_name

    @property
    def handoff_map(self) -> dict[str, str]:
        """Get the current handoff map (tool→agent)."""
        return self._handoff_map

    @property
    def available_agents(self) -> list[str]:
        """Get list of available agent names."""
        return list(self._agents.keys())

    # ───────────────────────────────────────────────────────────────────────────
    # Handoff Detection
    # ───────────────────────────────────────────────────────────────────────────

    def is_handoff(self, tool_name: str) -> bool:
        """
        Check if a tool triggers an agent handoff.

        Uses the centralized tool registry check, which looks at the
        is_handoff flag set during tool registration.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool triggers a handoff
        """
        return registry_is_handoff_tool(tool_name)

    # ───────────────────────────────────────────────────────────────────────────
    # Handoff Resolution
    # ───────────────────────────────────────────────────────────────────────────

    def get_handoff_target(self, tool_name: str) -> str | None:
        """
        Get the target agent for a handoff tool.

        Resolution order:
        1. Handoff map (static or from scenario)
        2. Returns None if not found

        Args:
            tool_name: The handoff tool name

        Returns:
            Target agent name, or None if not found
        """
        return self._handoff_map.get(tool_name)

    def get_handoff_config(
        self,
        source_agent: str,
        tool_name: str,
    ) -> HandoffConfig:
        """
        Get handoff configuration for a specific route.

        Looks up the handoff config by (source_agent, tool_name) to find
        the exact route behavior (discrete/announced, share_context).

        Args:
            source_agent: The agent initiating the handoff
            tool_name: The handoff tool being called

        Returns:
            HandoffConfig with type, share_context, greet_on_switch
        """
        return get_handoff_config(
            scenario_name=self._scenario_name,
            from_agent=source_agent,
            tool_name=tool_name,
        )

    def resolve_handoff(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        source_agent: str,
        current_system_vars: dict[str, Any],
        user_last_utterance: str | None = None,
        tool_result: dict[str, Any] | None = None,
    ) -> HandoffResolution:
        """
        Resolve a handoff tool call into a complete HandoffResolution.

        This is the main method called by orchestrators when a handoff tool
        is detected. It:
        1. Looks up the target agent
        2. Gets handoff config from scenario (discrete/announced, share_context)
        3. Builds system_vars using the shared helper
        4. Returns a complete resolution for the orchestrator to execute

        Args:
            tool_name: The handoff tool that was called
            tool_args: Arguments passed to the handoff tool
            source_agent: Name of the agent initiating the handoff
            current_system_vars: Current session's system_vars
            user_last_utterance: User's most recent speech
            tool_result: Result from executing the handoff tool (if any)

        Returns:
            HandoffResolution with all info needed to execute the switch

        Example:
            resolution = service.resolve_handoff(
                tool_name="handoff_fraud",
                tool_args={"reason": "suspicious activity"},
                source_agent="Concierge",
                current_system_vars={"session_profile": {...}},
                user_last_utterance="I think someone stole my card",
            )

            if resolution.success:
                await self._switch_to(resolution.target_agent, resolution.system_vars)
        """
        # Step 1: Get target agent
        target_agent = self.get_handoff_target(tool_name)
        if not target_agent:
            logger.warning(
                "Handoff tool '%s' not found in handoff_map | scenario=%s",
                tool_name,
                self._scenario_name,
            )
            return HandoffResolution(
                success=False,
                source_agent=source_agent,
                tool_name=tool_name,
                error=f"No target agent configured for handoff tool: {tool_name}",
            )

        # Validate target agent exists
        if target_agent not in self._agents:
            logger.warning(
                "Handoff target '%s' not in agent registry | tool=%s",
                target_agent,
                tool_name,
            )
            return HandoffResolution(
                success=False,
                source_agent=source_agent,
                tool_name=tool_name,
                target_agent=target_agent,
                error=f"Target agent '{target_agent}' not found in registry",
            )

        # Step 2: Get handoff config from scenario
        handoff_cfg = self.get_handoff_config(source_agent, tool_name)

        # Step 3: Build system_vars using shared helper
        system_vars = build_handoff_system_vars(
            source_agent=source_agent,
            target_agent=target_agent,
            tool_result=tool_result or {},
            tool_args=tool_args,
            current_system_vars=current_system_vars,
            user_last_utterance=user_last_utterance,
            share_context=handoff_cfg.share_context,
            greet_on_switch=handoff_cfg.greet_on_switch,
        )

        logger.info(
            "Handoff resolved | %s → %s | tool=%s type=%s share_context=%s",
            source_agent,
            target_agent,
            tool_name,
            handoff_cfg.type,
            handoff_cfg.share_context,
        )

        return HandoffResolution(
            success=True,
            target_agent=target_agent,
            source_agent=source_agent,
            tool_name=tool_name,
            system_vars=system_vars,
            greet_on_switch=handoff_cfg.greet_on_switch,
            share_context=handoff_cfg.share_context,
            handoff_type=handoff_cfg.type,
        )

    # ───────────────────────────────────────────────────────────────────────────
    # Greeting Selection
    # ───────────────────────────────────────────────────────────────────────────

    def select_greeting(
        self,
        agent: UnifiedAgent,
        is_first_visit: bool,
        greet_on_switch: bool,
        system_vars: dict[str, Any],
    ) -> str | None:
        """
        Select appropriate greeting for agent activation.

        This provides consistent greeting logic for both orchestrators:
        - Priority 1: Explicit greeting override in system_vars
        - Priority 2: Skip if discrete handoff (greet_on_switch=False)
        - Priority 3: Render agent's greeting/return_greeting template

        Args:
            agent: The agent being activated
            is_first_visit: Whether this is first visit to this agent
            greet_on_switch: Whether handoff mode allows greeting
            system_vars: Context for template rendering

        Returns:
            Rendered greeting string, or None if no greeting needed

        Example:
            greeting = service.select_greeting(
                agent=agents["FraudAgent"],
                is_first_visit=True,
                greet_on_switch=resolution.greet_on_switch,
                system_vars=resolution.system_vars,
            )
            if greeting:
                await agent.trigger_response(conn, say=greeting)
        """
        # Priority 1: Explicit greeting override
        explicit = system_vars.get("greeting")
        if not explicit:
            overrides = system_vars.get("session_overrides")
            if isinstance(overrides, dict):
                explicit = overrides.get("greeting")
        if explicit:
            return explicit.strip() or None

        # Priority 2: Discrete handoff = no greeting
        if not greet_on_switch:
            logger.debug(
                "Discrete handoff - skipping greeting for %s",
                getattr(agent, "name", "unknown"),
            )
            return None

        # Priority 3: Render from agent config
        # Build greeting context from system_vars
        greeting_context = self._build_greeting_context(system_vars)

        if is_first_visit:
            rendered = agent.render_greeting(greeting_context)
            return (rendered or "").strip() or None
        else:
            rendered = agent.render_return_greeting(greeting_context)
            return (rendered or "Welcome back!").strip()

    def _build_greeting_context(
        self,
        system_vars: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build context dict for greeting template rendering.

        Extracts relevant variables from system_vars to pass to Jinja2
        templates for personalized greetings.

        Args:
            system_vars: Current system variables

        Returns:
            Context dict for template rendering
        """
        context: dict[str, Any] = {}

        # Core identity fields
        identity_keys = (
            "caller_name",
            "client_id",
            "institution_name",
            "customer_intelligence",
            "session_profile",
            "relationship_tier",
            "active_agent",
            "previous_agent",
            "agent_name",
        )
        for key in identity_keys:
            if system_vars.get(key) is not None:
                context[key] = system_vars[key]

        # Extract from handoff_context if available
        handoff_context = system_vars.get("handoff_context")
        if handoff_context and isinstance(handoff_context, dict):
            handoff_keys = ("caller_name", "client_id", "institution_name", "customer_intelligence")
            for key in handoff_keys:
                if key not in context and handoff_context.get(key) is not None:
                    context[key] = handoff_context[key]

        # Extract from session_profile if available
        session_profile = system_vars.get("session_profile")
        if session_profile and isinstance(session_profile, dict):
            if "caller_name" not in context and session_profile.get("full_name"):
                context["caller_name"] = session_profile["full_name"]
            if "client_id" not in context and session_profile.get("client_id"):
                context["client_id"] = session_profile["client_id"]
            if "customer_intelligence" not in context and session_profile.get(
                "customer_intelligence"
            ):
                context["customer_intelligence"] = session_profile["customer_intelligence"]
            if "institution_name" not in context and session_profile.get("institution_name"):
                context["institution_name"] = session_profile["institution_name"]

        return context


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════


def create_handoff_service(
    scenario_name: str | None = None,
    agents: dict[str, UnifiedAgent] | None = None,
    handoff_map: dict[str, str] | None = None,
    memo_manager: MemoManager | None = None,
) -> HandoffService:
    """
    Factory function to create a HandoffService with proper defaults.

    If no agents or handoff_map provided, attempts to load from the
    agent registry and scenario configuration.

    Args:
        scenario_name: Active scenario name
        agents: Agent registry (will load if not provided)
        handoff_map: Handoff mappings (will build from scenario if not provided)
        memo_manager: Optional MemoManager for session state

    Returns:
        Configured HandoffService instance

    Example:
        # Simple creation with scenario
        service = create_handoff_service(scenario_name="banking")

        # Full control
        service = create_handoff_service(
            scenario_name="banking",
            agents=my_agents,
            handoff_map=my_map,
        )
    """
    # Load agents if not provided
    if agents is None:
        try:
            from apps.artagent.backend.registries.agentstore.loader import discover_agents

            agents = discover_agents()
        except ImportError:
            logger.warning("Could not load agents from registry")
            agents = {}

    # Build handoff map from scenario or agents
    if handoff_map is None:
        if scenario_name:
            try:
                from apps.artagent.backend.registries.scenariostore.loader import (
                    build_handoff_map_from_scenario,
                )

                handoff_map = build_handoff_map_from_scenario(scenario_name)
            except ImportError:
                pass

        # Fallback to building from agents
        if not handoff_map and agents:
            try:
                from apps.artagent.backend.registries.agentstore.loader import build_handoff_map

                handoff_map = build_handoff_map(agents)
            except ImportError:
                pass

        handoff_map = handoff_map or {}

    return HandoffService(
        scenario_name=scenario_name,
        handoff_map=handoff_map,
        agents=agents,
        memo_manager=memo_manager,
    )


__all__ = [
    "HandoffService",
    "HandoffResolution",
    "create_handoff_service",
]
