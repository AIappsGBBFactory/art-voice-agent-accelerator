"""
TTS Playback - DEPRECATED - Use voice.tts.playback instead
============================================================

This module is a backward compatibility shim.
The canonical location is now: apps.artagent.backend.voice.tts.playback

All new code should import from:
    from apps.artagent.backend.voice.tts import TTSPlayback

This shim will be removed in Phase 3 of the voice-handler-simplification.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

# Re-export from new canonical location
from apps.artagent.backend.voice.tts.playback import (
    SAMPLE_RATE_ACS,
    SAMPLE_RATE_BROWSER,
    TTSPlayback as _NewTTSPlayback,
)
from utils.ml_logging import get_logger

from opentelemetry import trace
from .metrics import record_tts_streaming, record_tts_synthesis

if TYPE_CHECKING:
    from apps.artagent.backend.voice.shared.context import VoiceSessionContext

logger = get_logger("voice.speech_cascade.tts")
tracer = trace.get_tracer(__name__)


class TTSPlayback(_NewTTSPlayback):
    """
    DEPRECATED: Backward compatibility wrapper.
    
    Use apps.artagent.backend.voice.tts.TTSPlayback instead.
    This class adapts the old (websocket, app_state, session_id) signature
    to the new (context, app_state) signature.
    """

    def __init__(
        self,
        websocket_or_context: Any,
        app_state: Any,
        session_id: str | None = None,
        *,
        latency_tool: Any = None,
        cancel_event: Any = None,
    ):
        """
        Initialize TTS playback with backward compatibility.

        Supports both:
        - Old: TTSPlayback(websocket, app_state, session_id, ...)
        - New: TTSPlayback(context, app_state)
        """
        # Check if first arg is VoiceSessionContext (new style)
        from apps.artagent.backend.voice.shared.context import VoiceSessionContext
        
        if isinstance(websocket_or_context, VoiceSessionContext):
            # New style: context-based
            context = websocket_or_context
            super().__init__(context, app_state, latency_tool=latency_tool)
        else:
            # Old style: websocket + session_id
            # Create a minimal context wrapper for backward compatibility
            websocket = websocket_or_context
            
            warnings.warn(
                "TTSPlayback(websocket, app_state, session_id) is deprecated. "
                "Use TTSPlayback(context, app_state) instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            
            # Build a lightweight context for backward compat
            context = self._build_compat_context(
                websocket, session_id or "unknown", cancel_event
            )
            super().__init__(context, app_state, latency_tool=latency_tool)

    @staticmethod
    def _build_compat_context(
        websocket: Any,
        session_id: str,
        cancel_event: Any,
    ) -> VoiceSessionContext:
        """Build a minimal VoiceSessionContext for backward compatibility."""
        import asyncio as _asyncio
        from apps.artagent.backend.voice.shared.context import (
            TransportType,
            VoiceSessionContext,
        )
        
        # Determine transport from websocket state if available
        transport_str = getattr(websocket.state, "transport", None)
        if transport_str == "acs":
            transport = TransportType.ACS
        elif transport_str == "voicelive":
            transport = TransportType.VOICELIVE
        else:
            transport = TransportType.BROWSER
        
        # Create context and manually set the websocket
        # (VoiceSessionContext uses _websocket as private field, set via populate_websocket_state)
        # Only pass cancel_event if provided, otherwise let dataclass create default Event
        ctx = VoiceSessionContext(
            session_id=session_id,
            transport=transport,
            cancel_event=cancel_event if cancel_event is not None else _asyncio.Event(),
        )
        ctx._websocket = websocket
        return ctx

    def get_agent_voice(self, agent_name: str | None = None) -> tuple[str, str | None, str | None]:
        """
        Get voice configuration from the active agent.
        
        This override adds fallback to session_agents for backward compat.
        """
        # First try the new context-based lookup
        result = super().get_agent_voice()
        if result[0] != "en-US-AvaMultilingualNeural":
            return result
        
        # Fallback: check session_agents (old global state)
        from apps.artagent.backend.src.orchestration.session_agents import get_session_agent
        
        session_agent = get_session_agent(self._session_id)
        if session_agent and hasattr(session_agent, "voice") and session_agent.voice:
            voice = session_agent.voice
            if voice.name:
                return (voice.name, voice.style, voice.rate)
        
        return result


__all__ = [
    "TTSPlayback",
    "SAMPLE_RATE_BROWSER",
    "SAMPLE_RATE_ACS",
]
