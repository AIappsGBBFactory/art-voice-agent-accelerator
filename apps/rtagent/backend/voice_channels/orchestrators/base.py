"""
Voice Orchestrator Protocol
============================

Abstract base protocol for voice channel orchestrators. Defines the common
interface that different orchestration strategies must implement.

Current Implementations:
    - gpt_flow.process_gpt_response: STT→LLM→TTS for SpeechCascadeHandler
    - LiveOrchestrator: Multi-agent for VoiceLiveSDKHandler

Future:
    Orchestrators will be moved here and implement this protocol directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket


class OrchestratorCapabilities(Flag):
    """Capabilities that an orchestrator may support."""
    
    NONE = 0
    STREAMING_TTS = auto()          # Can stream TTS audio chunks
    TOOL_CALLING = auto()           # Supports function/tool calls
    MULTI_AGENT = auto()            # Supports agent handoffs
    BARGE_IN = auto()               # Supports interruption handling
    CONVERSATION_MEMORY = auto()    # Maintains conversation history
    LATENCY_TRACKING = auto()       # Reports latency metrics
    

@dataclass
class OrchestratorContext:
    """Context passed to orchestrator for each turn."""
    
    websocket: "WebSocket"
    session_id: str
    call_connection_id: Optional[str] = None
    user_text: str = ""
    turn_id: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorResult:
    """Result from an orchestrator turn."""
    
    response_text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    agent_name: Optional[str] = None
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    interrupted: bool = False
    error: Optional[str] = None


class VoiceOrchestrator(Protocol):
    """
    Protocol for voice channel orchestrators.
    
    Orchestrators handle the AI processing layer between speech recognition
    and text-to-speech synthesis. They may implement different strategies:
    
    - Simple LLM streaming (gpt_flow)
    - Multi-agent with handoffs (LiveOrchestrator)
    - RAG-enhanced responses
    - Custom business logic
    
    Example Implementation:
        class MyOrchestrator:
            @property
            def capabilities(self) -> OrchestratorCapabilities:
                return (
                    OrchestratorCapabilities.STREAMING_TTS |
                    OrchestratorCapabilities.TOOL_CALLING
                )
            
            async def process_turn(
                self,
                context: OrchestratorContext,
                on_tts_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
            ) -> OrchestratorResult:
                # Process user input and generate response
                ...
    """
    
    @property
    def capabilities(self) -> OrchestratorCapabilities:
        """Return the capabilities this orchestrator supports."""
        ...
    
    @property
    def name(self) -> str:
        """Return a human-readable name for this orchestrator."""
        ...
    
    async def process_turn(
        self,
        context: OrchestratorContext,
        *,
        on_tts_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_start: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        on_tool_end: Optional[Callable[[str, Any], Awaitable[None]]] = None,
    ) -> OrchestratorResult:
        """
        Process a single conversation turn.
        
        Args:
            context: The orchestrator context with user input and state
            on_tts_chunk: Callback for streaming TTS text chunks
            on_tool_start: Callback when a tool execution begins
            on_tool_end: Callback when a tool execution completes
            
        Returns:
            OrchestratorResult with response and metadata
        """
        ...
    
    async def cancel_current(self) -> None:
        """Cancel any in-progress processing (for barge-in)."""
        ...


# Type alias for the legacy orchestrator function signature
# Used by SpeechCascadeHandler's route_turn integration
LegacyOrchestratorFunc = Callable[
    [
        "WebSocket",           # websocket
        str,                   # user_text
        List[Dict[str, Any]],  # conversation_history
        Optional[str],         # session_id
        Optional[Any],         # memo_manager
    ],
    Awaitable[Optional[str]]   # response text
]


__all__ = [
    "VoiceOrchestrator",
    "OrchestratorCapabilities",
    "OrchestratorContext",
    "OrchestratorResult",
    "LegacyOrchestratorFunc",
]
