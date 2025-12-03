"""
GPT Flow Orchestrator Adapter
==============================

Adapter that wraps the existing gpt_flow.process_gpt_response to conform
to the VoiceOrchestrator protocol.

The actual implementation remains in:
    apps/rtagent/backend/src/orchestration/artagent/gpt_flow.py

This adapter provides:
- Protocol-compliant interface
- Capability declaration
- Future migration path

Usage:
    from apps.rtagent.backend.voice_channels.orchestrators import GPTFlowOrchestrator
    
    orchestrator = GPTFlowOrchestrator()
    result = await orchestrator.process_turn(context)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

from .base import (
    VoiceOrchestrator,
    OrchestratorCapabilities,
    OrchestratorContext,
    OrchestratorResult,
)

if TYPE_CHECKING:
    from fastapi import WebSocket
    from src.stateful.state_managment import MemoManager


@dataclass
class GPTFlowOrchestrator:
    """
    Adapter for gpt_flow.process_gpt_response implementing VoiceOrchestrator protocol.
    
    This orchestrator handles the STT→LLM→TTS pipeline for SpeechCascadeHandler:
    - Streams OpenAI completions
    - Executes tool calls
    - Emits TTS chunks progressively
    
    Attributes:
        model: The OpenAI model/deployment to use
        tools: Available tool definitions
        system_prompt: Optional system prompt override
    """
    
    model: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    system_prompt: Optional[str] = None
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    
    @property
    def capabilities(self) -> OrchestratorCapabilities:
        """GPT flow supports streaming TTS, tool calling, and latency tracking."""
        return (
            OrchestratorCapabilities.STREAMING_TTS |
            OrchestratorCapabilities.TOOL_CALLING |
            OrchestratorCapabilities.CONVERSATION_MEMORY |
            OrchestratorCapabilities.BARGE_IN |
            OrchestratorCapabilities.LATENCY_TRACKING
        )
    
    @property
    def name(self) -> str:
        return "gpt_flow"
    
    async def process_turn(
        self,
        context: OrchestratorContext,
        *,
        on_tts_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_start: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
        on_tool_end: Optional[Callable[[str, Any], Awaitable[None]]] = None,
    ) -> OrchestratorResult:
        """
        Process a conversation turn using gpt_flow.
        
        This delegates to the existing process_gpt_response function,
        adapting the interface to the VoiceOrchestrator protocol.
        """
        # Import here to avoid circular imports
        from apps.rtagent.backend.src.orchestration.artagent.gpt_flow import (
            process_gpt_response,
        )
        
        self._cancel_event.clear()
        
        try:
            # Build messages from context
            messages = list(context.conversation_history)
            if context.system_prompt or self.system_prompt:
                system_msg = {"role": "system", "content": context.system_prompt or self.system_prompt}
                if not messages or messages[0].get("role") != "system":
                    messages.insert(0, system_msg)
            
            # Add user message
            if context.user_text:
                messages.append({"role": "user", "content": context.user_text})
            
            # Get memo manager from metadata if available
            memo_manager = context.metadata.get("memo_manager")
            
            # Call the existing gpt_flow
            response_text = await process_gpt_response(
                ws=context.websocket,
                messages=messages,
                memo_manager=memo_manager,
                tools=self.tools or context.tools,
                model=self.model,
            )
            
            return OrchestratorResult(
                response_text=response_text or "",
                interrupted=self._cancel_event.is_set(),
            )
            
        except asyncio.CancelledError:
            return OrchestratorResult(
                response_text="",
                interrupted=True,
            )
        except Exception as e:
            return OrchestratorResult(
                response_text="",
                error=str(e),
            )
    
    async def cancel_current(self) -> None:
        """Signal cancellation for barge-in."""
        self._cancel_event.set()


# Factory function for easy instantiation
def get_gpt_flow_orchestrator(
    *,
    model: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    system_prompt: Optional[str] = None,
) -> GPTFlowOrchestrator:
    """
    Create a GPTFlowOrchestrator instance.
    
    Args:
        model: Optional model/deployment override
        tools: Optional tool definitions
        system_prompt: Optional system prompt
        
    Returns:
        Configured GPTFlowOrchestrator
    """
    return GPTFlowOrchestrator(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
    )


__all__ = [
    "GPTFlowOrchestrator",
    "get_gpt_flow_orchestrator",
]
