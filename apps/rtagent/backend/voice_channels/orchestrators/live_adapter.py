"""
Live Orchestrator Adapter
==========================

Self-contained adapter for VoiceLive multi-agent orchestration implementing
the VoiceOrchestrator protocol.

The adapter encapsulates:
- Agent registry management
- Handoff logic via pluggable HandoffStrategy
- Event loop for VoiceLive SDK events
- OpenTelemetry tracing with GenAI semantic conventions

Unlike gpt_flow which processes turns synchronously, LiveOrchestrator
is event-driven - it responds to VoiceLive SDK events asynchronously.
The adapter bridges this to the VoiceOrchestrator protocol.

Design Patterns:
    1. Self-contained: All dependencies configured at construction time
    2. Pluggable handoffs: Supports tool-based (VoiceLive) or state-based (ART)
    3. Agent registry: Shared agent definitions across orchestrators
    4. Future-ready: Prepared for shared agentic tools ingestion

Usage:
    # Create with VoiceLive connection
    adapter = LiveOrchestratorAdapter.create(
        conn=voicelive_connection,
        agents=agent_registry,
        handoff_map={"handoff_fraud": "FraudAgent"},
        start_agent="EricaConcierge",
    )
    
    # Start the orchestrator
    await adapter.start(system_vars={"session_profile": profile})
    
    # Process events (typically in event loop)
    await adapter.handle_event(event)
    
    # Or wrap existing LiveOrchestrator for gradual migration
    adapter = wrap_live_orchestrator(existing_orchestrator)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Union, TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from .base import (
    VoiceOrchestrator,
    OrchestratorCapabilities,
    OrchestratorContext,
    OrchestratorResult,
)
from ..handoffs import (
    HandoffStrategy,
    HandoffContext,
    HandoffResult,
    ToolBasedHandoff,
    create_tool_based_handoff,
)

if TYPE_CHECKING:
    from azure.ai.voicelive.models import ServerEventType
    from apps.rtagent.backend.src.agents.vlagent.base import AzureVoiceLiveAgent
    from apps.rtagent.backend.src.agents.vlagent.orchestrator import LiveOrchestrator
    from apps.rtagent.agents.session_manager import SessionAgentManager
    from apps.rtagent.agents.base import UnifiedAgent

# Conditional imports for tracing
try:
    from apps.rtagent.backend.src.utils.tracing import (
        create_service_handler_attrs,
        create_service_dependency_attrs,
    )
    from src.enums.monitoring import SpanAttr, GenAIOperation, GenAIProvider
    _TRACING_AVAILABLE = True
except ImportError:
    _TRACING_AVAILABLE = False
    create_service_handler_attrs = lambda **kw: {}
    create_service_dependency_attrs = lambda **kw: {}
    
    class SpanAttr:
        SESSION_ID = type("V", (), {"value": "session.id"})()
        CALL_CONNECTION_ID = type("V", (), {"value": "call.connection.id"})()
        GENAI_OPERATION_NAME = type("V", (), {"value": "gen_ai.operation.name"})()
        GENAI_PROVIDER_NAME = type("V", (), {"value": "gen_ai.provider.name"})()
        GENAI_REQUEST_MODEL = type("V", (), {"value": "gen_ai.request.model"})()
        GENAI_USAGE_INPUT_TOKENS = type("V", (), {"value": "gen_ai.usage.input_tokens"})()
        GENAI_USAGE_OUTPUT_TOKENS = type("V", (), {"value": "gen_ai.usage.output_tokens"})()
    
    class GenAIOperation:
        INVOKE_AGENT = "invoke_agent"
        EXECUTE_TOOL = "execute_tool"
        CHAT = "chat"
    
    class GenAIProvider:
        AZURE_OPENAI = "azure_openai"


try:
    from utils.ml_logging import get_logger
    logger = get_logger("voicelive.adapter")
except ImportError:
    import logging
    logger = logging.getLogger("voicelive.adapter")

tracer = trace.get_tracer(__name__)


# ─────────────────────────────────────────────────────────────────────
# Provider Protocols (for session-aware agent/handoff resolution)
# ─────────────────────────────────────────────────────────────────────

class AgentProvider(Protocol):
    """Protocol for providing agent definitions to the orchestrator.
    
    Implementations include:
    - SessionAgentManager: Session-aware agent resolution with overrides
    - Static dict wrapper: For backward compatibility
    """
    
    def get_agent(self, name: str) -> Optional[Any]:
        """Get an agent by name (with any session overrides applied)."""
        ...
    
    def list_agents(self) -> List[str]:
        """List available agent names."""
        ...
    
    @property
    def active_agent(self) -> Optional[str]:
        """Get currently active agent name (optional)."""
        ...
    
    def set_active_agent(self, name: str) -> None:
        """Set the currently active agent (optional)."""
        ...


class HandoffProvider(Protocol):
    """Protocol for providing handoff mappings to the orchestrator.
    
    Implementations include:
    - SessionAgentManager: Session-aware handoff resolution
    - Static dict wrapper: For backward compatibility
    """
    
    def get_handoff_target(self, tool_name: str) -> Optional[str]:
        """Get target agent for a handoff tool."""
        ...
    
    @property
    def handoff_map(self) -> Dict[str, str]:
        """Get current handoff mappings."""
        ...
    
    def is_handoff_tool(self, tool_name: str) -> bool:
        """Check if a tool triggers a handoff."""
        ...


class ToolProvider(Protocol):
    """Protocol for providing tool definitions to the orchestrator."""
    
    def get_tools_for_agent(self, agent_name: str) -> List[Dict[str, Any]]:
        """Get tool definitions available to an agent."""
        ...
    
    async def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return the result."""
        ...


# ─────────────────────────────────────────────────────────────────────
# Static Dict Wrappers for Backward Compatibility
# ─────────────────────────────────────────────────────────────────────

class StaticAgentProvider:
    """Wraps a static agent dict to satisfy AgentProvider protocol."""
    
    def __init__(self, agents: Dict[str, Any]) -> None:
        self._agents = agents
        self._active: Optional[str] = None
    
    def get_agent(self, name: str) -> Optional[Any]:
        return self._agents.get(name)
    
    def list_agents(self) -> List[str]:
        return list(self._agents.keys())
    
    @property
    def active_agent(self) -> Optional[str]:
        return self._active
    
    def set_active_agent(self, name: str) -> None:
        if name in self._agents:
            self._active = name


class StaticHandoffProvider:
    """Wraps a static handoff map to satisfy HandoffProvider protocol."""
    
    def __init__(self, handoff_map: Dict[str, str]) -> None:
        self._handoff_map = handoff_map
    
    def get_handoff_target(self, tool_name: str) -> Optional[str]:
        return self._handoff_map.get(tool_name)
    
    @property
    def handoff_map(self) -> Dict[str, str]:
        return self._handoff_map.copy()
    
    def is_handoff_tool(self, tool_name: str) -> bool:
        return tool_name in self._handoff_map


def wrap_as_agent_provider(
    source: Union[Dict[str, Any], AgentProvider, "SessionAgentManager"],
) -> AgentProvider:
    """Convert dict or provider to AgentProvider protocol."""
    if isinstance(source, dict):
        return StaticAgentProvider(source)
    return source  # Assume already implements protocol


def wrap_as_handoff_provider(
    source: Union[Dict[str, str], HandoffProvider, "SessionAgentManager"],
) -> HandoffProvider:
    """Convert dict or provider to HandoffProvider protocol."""
    if isinstance(source, dict):
        return StaticHandoffProvider(source)
    return source  # Assume already implements protocol


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

@dataclass
class LiveOrchestratorConfig:
    """
    Configuration for LiveOrchestratorAdapter.
    
    Attributes:
        start_agent: Name of the initial agent
        model_name: LLM model for token attribution
        transport: Transport type ('acs' or 'websocket')
        call_connection_id: ACS call connection for tracing
        session_id: Session identifier for tracing
    """
    start_agent: str = "EricaConcierge"
    model_name: str = "gpt-4o-realtime"
    transport: str = "acs"
    call_connection_id: Optional[str] = None
    session_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Main Adapter
# ─────────────────────────────────────────────────────────────────────

@dataclass
class LiveOrchestratorAdapter:
    """
    Self-contained adapter for VoiceLive multi-agent orchestration.
    
    This adapter can either:
    1. Wrap an existing LiveOrchestrator (via wrap_live_orchestrator)
    2. Be created standalone with all dependencies (via create())
    
    Key Features:
        - Pluggable handoff strategy (tool-based or state-based)
        - Agent registry for multi-agent scenarios
        - OpenTelemetry instrumentation
        - Future-ready for shared tool providers
    
    Architecture:
        ```
        VoiceLiveSDKHandler
              │
              ▼
        LiveOrchestratorAdapter ──► HandoffStrategy
              │                          │
              ├─► AgentProvider          └─► ToolBasedHandoff
              │                              StateBasedHandoff
              └─► ToolProvider (future)
        ```
    
    Attributes:
        orchestrator: Wrapped LiveOrchestrator (for delegation mode)
        agents: Agent definitions registry (for standalone mode)
        handoff_strategy: Strategy for handling agent switches
        config: Orchestrator configuration
    """
    
    # Either wrap existing or provide all dependencies
    orchestrator: Optional["LiveOrchestrator"] = None
    conn: Optional[Any] = None  # VoiceLive connection
    agents: Dict[str, Any] = field(default_factory=dict)
    handoff_strategy: Optional[HandoffStrategy] = None
    config: LiveOrchestratorConfig = field(default_factory=LiveOrchestratorConfig)
    
    # Optional dependencies
    audio_processor: Optional[Any] = None
    messenger: Optional[Any] = None
    tool_provider: Optional[ToolProvider] = None
    
    # Runtime state
    _active_agent: str = field(default="", init=False)
    _visited_agents: set = field(default_factory=set, init=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _system_vars: Dict[str, Any] = field(default_factory=dict, init=False)
    _last_user_message: Optional[str] = field(default=None, init=False)
    _pending_greeting: Optional[str] = field(default=None, init=False)
    _pending_greeting_agent: Optional[str] = field(default=None, init=False)
    
    # Token tracking for invoke_agent spans
    _agent_input_tokens: int = field(default=0, init=False)
    _agent_output_tokens: int = field(default=0, init=False)
    _agent_start_time: float = field(default_factory=time.perf_counter, init=False)
    _agent_response_count: int = field(default=0, init=False)
    
    # LLM timing
    _llm_turn_start_time: Optional[float] = field(default=None, init=False)
    _llm_first_token_time: Optional[float] = field(default=None, init=False)
    _llm_turn_number: int = field(default=0, init=False)
    
    def __post_init__(self):
        """Initialize based on mode (delegation vs standalone)."""
        if self.orchestrator:
            # Delegation mode - extract state from wrapped orchestrator
            self._active_agent = getattr(self.orchestrator, "active", "")
            self.agents = getattr(self.orchestrator, "agents", {})
            self.conn = getattr(self.orchestrator, "conn", None)
            self.audio_processor = getattr(self.orchestrator, "audio", None)
            self.messenger = getattr(self.orchestrator, "messenger", None)
            
            # Extract config from orchestrator
            self.config = LiveOrchestratorConfig(
                start_agent=self._active_agent,
                model_name=getattr(self.orchestrator, "_model_name", "gpt-4o-realtime"),
                transport=getattr(self.orchestrator, "_transport", "acs"),
                call_connection_id=getattr(self.orchestrator, "call_connection_id", None),
                session_id=(
                    getattr(self.messenger, "session_id", None) 
                    if self.messenger else None
                ),
            )
            
            # Build handoff strategy from orchestrator's handoff_map
            handoff_map = getattr(self.orchestrator, "handoff_map", {})
            self.handoff_strategy = create_tool_based_handoff(handoff_map)
        else:
            # Standalone mode - validate required fields
            self._active_agent = self.config.start_agent
            if self._active_agent and self.agents and self._active_agent not in self.agents:
                raise ValueError(f"Start agent '{self._active_agent}' not found in registry")
    
    @classmethod
    def create(
        cls,
        conn: Any,
        agents: Dict[str, Any],
        handoff_map: Dict[str, str],
        *,
        start_agent: str = "EricaConcierge",
        model_name: str = "gpt-4o-realtime",
        transport: str = "acs",
        audio_processor: Optional[Any] = None,
        messenger: Optional[Any] = None,
        call_connection_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "LiveOrchestratorAdapter":
        """
        Factory method to create a fully configured standalone adapter.
        
        Args:
            conn: VoiceLive SDK connection
            agents: Registry of agent definitions
            handoff_map: Tool name → agent name mapping
            start_agent: Initial agent name
            model_name: Model for token attribution
            transport: Transport type
            audio_processor: Optional audio handler
            messenger: Optional UI messenger
            call_connection_id: ACS call ID for tracing
            session_id: Session ID for tracing
            
        Returns:
            Configured LiveOrchestratorAdapter instance
        """
        config = LiveOrchestratorConfig(
            start_agent=start_agent,
            model_name=model_name,
            transport=transport,
            call_connection_id=call_connection_id,
            session_id=session_id,
        )
        
        strategy = create_tool_based_handoff(handoff_map)
        
        return cls(
            conn=conn,
            agents=agents,
            handoff_strategy=strategy,
            config=config,
            audio_processor=audio_processor,
            messenger=messenger,
        )
    
    # ─────────────────────────────────────────────────────────────────
    # VoiceOrchestrator Protocol Implementation
    # ─────────────────────────────────────────────────────────────────
    
    @property
    def capabilities(self) -> OrchestratorCapabilities:
        """LiveOrchestrator supports multi-agent, streaming, and tools."""
        return (
            OrchestratorCapabilities.STREAMING_TTS |
            OrchestratorCapabilities.TOOL_CALLING |
            OrchestratorCapabilities.MULTI_AGENT |
            OrchestratorCapabilities.CONVERSATION_MEMORY |
            OrchestratorCapabilities.BARGE_IN |
            OrchestratorCapabilities.LATENCY_TRACKING
        )
    
    @property
    def name(self) -> str:
        return "live_orchestrator"
    
    @property
    def current_agent(self) -> Optional[str]:
        """Get the currently active agent name."""
        if self.orchestrator:
            return getattr(self.orchestrator, "active", None)
        return self._active_agent
    
    @property
    def available_agents(self) -> List[str]:
        """Get list of available agent names."""
        if self.orchestrator:
            return list(getattr(self.orchestrator, "agents", {}).keys())
        return list(self.agents.keys())
    
    async def process_turn(
        self,
        context: OrchestratorContext,
        *,
        on_tts_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_start: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        on_tool_end: Optional[Callable[[str, Any], Awaitable[None]]] = None,
    ) -> OrchestratorResult:
        """
        Process a conversation turn.
        
        Note:
            LiveOrchestrator is event-driven - turns are processed via
            handle_event() as VoiceLive SDK events arrive. This method
            is provided for protocol compliance.
            
            For actual turn processing, the VoiceLiveSDKHandler calls
            handle_event() from its event loop.
        
        Returns:
            OrchestratorResult indicating event-driven processing mode
        """
        return OrchestratorResult(
            response_text="",
            agent_name=self.current_agent,
            error="LiveOrchestrator is event-driven; use handle_event() instead",
        )
    
    async def cancel_current(self) -> None:
        """Signal cancellation for barge-in."""
        self._cancel_event.set()
        
        # Delegate to wrapped orchestrator if present
        if self.orchestrator:
            try:
                await self.orchestrator.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during barge-in", exc_info=True)
            if self.orchestrator.audio:
                try:
                    await self.orchestrator.audio.stop_playback()
                except Exception:
                    pass
            return
        
        # Standalone mode
        if self.conn:
            try:
                await self.conn.response.cancel()
            except Exception:
                logger.debug("response.cancel() failed during barge-in", exc_info=True)
        
        if self.audio_processor:
            try:
                await self.audio_processor.stop_playback()
            except Exception:
                logger.debug("Audio stop failed during barge-in", exc_info=True)
    
    # ─────────────────────────────────────────────────────────────────
    # Lifecycle Methods
    # ─────────────────────────────────────────────────────────────────
    
    async def start(self, system_vars: Optional[Dict[str, Any]] = None) -> None:
        """
        Start the orchestrator with the initial agent.
        
        Delegates to wrapped orchestrator if present, otherwise handles standalone.
        
        Args:
            system_vars: Initial system variables (session_profile, etc.)
        """
        if self.orchestrator:
            # Delegate to existing orchestrator
            await self.orchestrator.start(system_vars)
            return
        
        # Standalone mode
        with tracer.start_as_current_span(
            "live_orchestrator.start",
            kind=SpanKind.INTERNAL,
            attributes=create_service_handler_attrs(
                service_name="LiveOrchestratorAdapter.start",
                call_connection_id=self.config.call_connection_id,
                session_id=self.config.session_id,
            ),
        ) as span:
            span.set_attribute("voicelive.start_agent", self._active_agent)
            span.set_attribute("voicelive.agent_count", len(self.agents))
            
            logger.info("[Orchestrator] Starting with agent: %s", self._active_agent)
            
            self._system_vars = dict(system_vars or {})
            await self._switch_to_agent(self._active_agent, self._system_vars)
            
            span.set_status(Status(StatusCode.OK))
    
    async def _switch_to_agent(
        self,
        agent_name: str,
        system_vars: Dict[str, Any],
    ) -> None:
        """
        Switch to a different agent (standalone mode).
        
        Args:
            agent_name: Target agent name
            system_vars: System variables for the new agent
        """
        previous_agent = self._active_agent
        agent = self.agents.get(agent_name)
        
        if not agent:
            raise ValueError(f"Agent '{agent_name}' not found in registry")
        
        # Emit summary span for outgoing agent
        if previous_agent != agent_name and self._agent_response_count > 0:
            self._emit_agent_summary_span(previous_agent)
        
        with tracer.start_as_current_span(
            "live_orchestrator.switch_agent",
            kind=SpanKind.INTERNAL,
            attributes={
                "voicelive.previous_agent": previous_agent,
                "voicelive.target_agent": agent_name,
                SpanAttr.SESSION_ID.value: self.config.session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: self.config.call_connection_id or "",
            },
        ) as span:
            is_first_visit = agent_name not in self._visited_agents
            self._visited_agents.add(agent_name)
            span.set_attribute("voicelive.is_first_visit", is_first_visit)
            
            # Prepare system vars
            vars_copy = dict(system_vars)
            vars_copy["previous_agent"] = previous_agent
            vars_copy["active_agent"] = agent_name
            
            # Select greeting
            greeting = self._select_greeting(
                agent=agent,
                agent_name=agent_name,
                system_vars=vars_copy,
                is_first_visit=is_first_visit,
            )
            if greeting:
                self._pending_greeting = greeting
                self._pending_greeting_agent = agent_name
            
            self._active_agent = agent_name
            
            # Notify messenger
            if self.messenger:
                try:
                    self.messenger.set_active_agent(agent_name)
                except AttributeError:
                    pass
            
            # Apply session configuration
            if hasattr(agent, "apply_session"):
                await agent.apply_session(
                    self.conn,
                    system_vars=vars_copy,
                    say=None,
                    session_id=self.config.session_id,
                    call_connection_id=self.config.call_connection_id,
                )
            
            # Reset token counters
            self._agent_input_tokens = 0
            self._agent_output_tokens = 0
            self._agent_start_time = time.perf_counter()
            self._agent_response_count = 0
            
            span.set_status(Status(StatusCode.OK))
            logger.info("[Active Agent] %s is now active", self._active_agent)
    
    def _select_greeting(
        self,
        agent: Any,
        agent_name: str,
        system_vars: Dict[str, Any],
        is_first_visit: bool,
    ) -> Optional[str]:
        """Select appropriate greeting for agent activation."""
        # Check for explicit greeting
        explicit = system_vars.get("greeting")
        if not explicit:
            overrides = system_vars.get("session_overrides", {})
            if isinstance(overrides, dict):
                explicit = overrides.get("greeting")
        if explicit:
            return explicit.strip() or None
        
        # Check for handoff context (skip automatic greeting)
        has_handoff = bool(
            system_vars.get("handoff_context") or
            system_vars.get("handoff_message") or
            system_vars.get("handoff_reason")
        )
        if has_handoff:
            return None
        
        # Use agent's configured greeting
        if is_first_visit:
            return (getattr(agent, "greeting", None) or "").strip() or None
        return (getattr(agent, "return_greeting", "Welcome back!") or "").strip()
    
    def _emit_agent_summary_span(self, agent_name: str) -> None:
        """Emit invoke_agent summary span with token usage."""
        agent = self.agents.get(agent_name)
        if not agent:
            return
        
        duration_ms = (time.perf_counter() - self._agent_start_time) * 1000
        
        with tracer.start_as_current_span(
            f"invoke_agent {agent_name}",
            kind=SpanKind.INTERNAL,
            attributes={
                "component": "voicelive",
                SpanAttr.SESSION_ID.value: self.config.session_id or "",
                SpanAttr.CALL_CONNECTION_ID.value: self.config.call_connection_id or "",
                SpanAttr.GENAI_OPERATION_NAME.value: GenAIOperation.INVOKE_AGENT,
                SpanAttr.GENAI_PROVIDER_NAME.value: GenAIProvider.AZURE_OPENAI,
                SpanAttr.GENAI_REQUEST_MODEL.value: self.config.model_name,
                "gen_ai.agent.name": agent_name,
                "gen_ai.agent.description": getattr(agent, "description", f"VoiceLive agent: {agent_name}"),
                SpanAttr.GENAI_USAGE_INPUT_TOKENS.value: self._agent_input_tokens,
                SpanAttr.GENAI_USAGE_OUTPUT_TOKENS.value: self._agent_output_tokens,
                "voicelive.response_count": self._agent_response_count,
                "voicelive.duration_ms": duration_ms,
            },
        ) as span:
            span.add_event("gen_ai.agent.session_complete", {
                "agent": agent_name,
                "input_tokens": self._agent_input_tokens,
                "output_tokens": self._agent_output_tokens,
            })
    
    # ─────────────────────────────────────────────────────────────────
    # Handoff Support
    # ─────────────────────────────────────────────────────────────────
    
    async def handle_handoff(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> bool:
        """
        Handle a potential handoff tool call.
        
        Uses the pluggable HandoffStrategy to determine if this is a handoff
        and execute the agent switch.
        
        Args:
            tool_name: Name of the tool that was called
            args: Tool arguments
            
        Returns:
            True if this was a handoff (agent switched), False otherwise
        """
        if not self.handoff_strategy:
            return False
        
        if not self.handoff_strategy.is_handoff_tool(tool_name):
            return False
        
        # Build handoff context
        source = self.current_agent or ""
        context = self.handoff_strategy.build_context_from_args(
            tool_name=tool_name,
            args=args,
            source_agent=source,
            user_last_utterance=self._last_user_message,
        )
        
        # Execute handoff
        result = await self.handoff_strategy.execute_handoff(
            tool_name=tool_name,
            args=args,
            context=context,
        )
        
        if not result.success:
            logger.warning("Handoff failed: %s", result.error)
            return False
        
        if result.target_agent:
            if self.orchestrator:
                # Delegate to wrapped orchestrator
                switch_vars = context.to_system_vars()
                for key in ("session_profile", "client_id", "customer_intelligence"):
                    if key in getattr(self.orchestrator, "_system_vars", {}):
                        switch_vars[key] = self.orchestrator._system_vars[key]
                await self.orchestrator._switch_to(result.target_agent, switch_vars)
            else:
                # Standalone mode
                switch_vars = context.to_system_vars()
                for key in ("session_profile", "client_id", "customer_intelligence"):
                    if key in self._system_vars:
                        switch_vars[key] = self._system_vars[key]
                if result.message:
                    switch_vars["handoff_message"] = result.message
                await self._switch_to_agent(result.target_agent, switch_vars)
            
            self._last_user_message = None
            return True
        
        return False
    
    async def switch_agent(
        self,
        agent_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Programmatically switch to a different agent.
        
        Args:
            agent_name: Target agent name
            context: Optional handoff context
            
        Returns:
            True if switch succeeded
        """
        if self.orchestrator:
            # Delegate to wrapped orchestrator
            try:
                await self.orchestrator._switch_to(agent_name, context or {})
                return True
            except Exception as e:
                logger.exception("Agent switch failed: %s", e)
                return False
        
        # Standalone mode
        if agent_name not in self.agents:
            logger.warning("Cannot switch to unknown agent: %s", agent_name)
            return False
        
        try:
            switch_vars = dict(context or {})
            switch_vars["previous_agent"] = self._active_agent
            await self._switch_to_agent(agent_name, switch_vars)
            return True
        except Exception as e:
            logger.exception("Agent switch failed: %s", e)
            return False
    
    # ─────────────────────────────────────────────────────────────────
    # User Input & Token Tracking
    # ─────────────────────────────────────────────────────────────────
    
    def record_user_message(self, text: str) -> None:
        """Record the user's last utterance for handoff context."""
        self._last_user_message = text.strip() if text else None
        if self.orchestrator:
            self.orchestrator._last_user_message = self._last_user_message
    
    def accumulate_tokens(
        self,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> None:
        """Accumulate token usage for the current agent."""
        if input_tokens:
            self._agent_input_tokens += input_tokens
        if output_tokens:
            self._agent_output_tokens += output_tokens
        self._agent_response_count += 1
    
    def start_turn_timing(self) -> None:
        """Mark start of LLM turn for TTFT calculation."""
        self._llm_turn_number += 1
        self._llm_turn_start_time = time.perf_counter()
        self._llm_first_token_time = None
    
    def record_first_token(self) -> Optional[float]:
        """Record first token time and return TTFT in ms."""
        if self._llm_turn_start_time and self._llm_first_token_time is None:
            self._llm_first_token_time = time.perf_counter()
            return (self._llm_first_token_time - self._llm_turn_start_time) * 1000
        return None


# ─────────────────────────────────────────────────────────────────────
# Factory Functions
# ─────────────────────────────────────────────────────────────────────

def wrap_live_orchestrator(
    orchestrator: "LiveOrchestrator",
) -> LiveOrchestratorAdapter:
    """
    Wrap an existing LiveOrchestrator in a protocol-compliant adapter.
    
    This is a bridge for gradual migration - the adapter delegates most
    operations to the wrapped orchestrator while providing:
    - Protocol compliance
    - Additional handoff strategy abstraction
    - Future-ready interfaces
    
    Args:
        orchestrator: The LiveOrchestrator to wrap
        
    Returns:
        LiveOrchestratorAdapter that delegates to the wrapped orchestrator
    """
    return LiveOrchestratorAdapter(orchestrator=orchestrator)


def get_live_orchestrator(
    conn: Any,
    agents: Dict[str, Any],
    handoff_map: Dict[str, str],
    **kwargs,
) -> LiveOrchestratorAdapter:
    """
    Create a LiveOrchestratorAdapter instance.
    
    Convenience factory matching get_gpt_flow_orchestrator pattern.
    
    Args:
        conn: VoiceLive SDK connection
        agents: Agent registry
        handoff_map: Handoff tool to agent mapping
        **kwargs: Additional configuration (start_agent, model_name, etc.)
        
    Returns:
        Configured LiveOrchestratorAdapter
    """
    return LiveOrchestratorAdapter.create(
        conn=conn,
        agents=agents,
        handoff_map=handoff_map,
        **kwargs,
    )


__all__ = [
    "LiveOrchestratorAdapter",
    "LiveOrchestratorConfig",
    "AgentProvider",
    "ToolProvider",
    "wrap_live_orchestrator",
    "get_live_orchestrator",
]
