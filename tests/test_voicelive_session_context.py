"""
VoiceLive session-context refresh
=================================

``LiveOrchestrator._update_session_context()`` re-renders the active agent's
prompt and pushes it back onto the live VoiceLive session before a response. It
is what keeps the realtime model from forgetting the conversation and what
injects scenario handoff instructions.

``self.agents`` holds :class:`UnifiedAgent` instances directly — ``update_scenario``
documents the registry as "no adapter needed". The method nevertheless reached
for ``agent._agent``, a leftover from the pre-unification adapter wrapper, so it
raised ``AttributeError: 'UnifiedAgent' object has no attribute '_agent'`` on
every single turn. The failure was swallowed by the surrounding ``except``, so
instructions silently never refreshed while a spurious "unexpected error in the
voice pipeline" was pushed to the browser each turn.

These tests pin the unwrap so the regression cannot come back.
"""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator


def _make_orchestrator(agent, scenario=None):
    """Build a bare LiveOrchestrator with only what _update_session_context needs."""
    orch = object.__new__(LiveOrchestrator)

    orch.conn = MagicMock()
    orch.conn.session.update = AsyncMock()
    orch.active = "BankingConcierge"
    orch.agents = {"BankingConcierge": agent}
    orch._system_vars = {}
    orch._user_message_history = deque(["hi"])
    orch._last_assistant_message = None
    orch.call_connection_id = "call-ctx"
    orch._model_name = "gpt-realtime"
    orch._memo_manager = None
    # _session_id resolves through memo_manager then messenger.
    orch.messenger = None
    # Correlates a context-only session.update with its session.updated echo.
    orch._pending_context_session_updates = 0
    # Bypass the cached property's resolve_orchestrator_config() lookup.
    orch._cached_orchestrator_config = SimpleNamespace(
        scenario=scenario, scenario_name="banking" if scenario else None
    )
    orch._build_conversation_recap = lambda: ""
    orch._websocket_for_errors = lambda: None
    return orch


def _unified_agent(name="BankingConcierge", rendered="BASE INSTRUCTIONS"):
    """A raw UnifiedAgent-shaped object: has .name/.render_prompt, no ._agent."""
    agent = SimpleNamespace(name=name, render_prompt=lambda ctx: rendered)
    assert not hasattr(agent, "_agent")
    return agent


@pytest.mark.asyncio
async def test_update_session_context_accepts_raw_unified_agent():
    """A raw UnifiedAgent must render and push instructions, not raise."""
    orch = _make_orchestrator(_unified_agent())

    await orch._update_session_context()

    orch.conn.session.update.assert_awaited_once()
    session = orch.conn.session.update.await_args.kwargs["session"]
    assert "BASE INSTRUCTIONS" in session.instructions


@pytest.mark.asyncio
async def test_update_session_context_injects_handoff_instructions():
    """Scenario handoff instructions are appended for a raw UnifiedAgent.

    This is the behaviour that was dead in production: the AttributeError fired
    before the scenario lookup, so handoff routing never reached the model.
    """
    scenario = MagicMock()
    scenario.build_handoff_instructions.return_value = "HANDOFF RULES"
    orch = _make_orchestrator(_unified_agent(), scenario=scenario)

    await orch._update_session_context()

    scenario.build_handoff_instructions.assert_called_once_with("BankingConcierge")
    session = orch.conn.session.update.await_args.kwargs["session"]
    assert "BASE INSTRUCTIONS" in session.instructions
    assert "HANDOFF RULES" in session.instructions


@pytest.mark.asyncio
async def test_update_session_context_still_unwraps_adapter_agents():
    """Legacy adapter-wrapped agents (exposing ._agent) keep working."""
    inner = _unified_agent(rendered="WRAPPED INSTRUCTIONS")
    adapter = SimpleNamespace(_agent=inner)
    orch = _make_orchestrator(adapter)

    await orch._update_session_context()

    session = orch.conn.session.update.await_args.kwargs["session"]
    assert "WRAPPED INSTRUCTIONS" in session.instructions


@pytest.mark.asyncio
async def test_update_session_context_does_not_emit_voice_error_on_success():
    """No error envelope should reach the browser for a healthy refresh."""
    orch = _make_orchestrator(_unified_agent())
    emitted = []
    orch._websocket_for_errors = lambda: emitted.append("called")

    await orch._update_session_context()

    assert emitted == []
    orch.conn.session.update.assert_awaited_once()
