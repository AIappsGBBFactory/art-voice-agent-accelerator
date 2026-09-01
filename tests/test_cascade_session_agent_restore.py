"""
Cascade: a tuned session agent must survive the first memo sync
================================================================

``route_turn()`` does these two things back to back::

    adapter = _get_or_create_adapter(session_id, ..., memo_manager=cm)
    adapter.sync_from_memo_manager(cm)

``_get_or_create_adapter()`` injects the Agent Builder / Quick Tune session agent
and assigns it to ``adapter._active_agent``. ``sync_from_memo_manager()`` then
treats MemoManager as authoritative (``elif state.active_agent:``) — which is
correct for every *later* turn, because that is how tool-driven handoffs
propagate, but on the creation turn it means an ``active_agent`` persisted by an
**earlier connection on the same session_id** silently undoes the injection.

That is the Voice Live split-brain (fixed in 9530f30) reappearing in Cascade.
Cascade resolves its model per turn, so it degrades to the wrong voice and the
wrong instructions rather than to a mute call — but the tuning is lost the same
way, which is the "I picked a different voice and only the default persisted"
symptom.

These tests drive the real ``CascadeOrchestratorAdapter.sync_from_memo_manager``
against a stand-in adapter, so they exercise the actual sequence rather than a
paraphrase of it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.src.orchestration.unified import _get_or_create_adapter
from apps.artagent.backend.voice.speech_cascade.orchestrator import (
    CascadeOrchestratorAdapter,
)

EMMA = "en-US-EmmaMultilingualNeural"
ALLOY = "en-US-AlloyTurboMultilingualNeural"


class _FakeMemo:
    def __init__(self, **corememory: Any) -> None:
        self.session_id = "sess-cascade-1"
        self.corememory: dict[str, Any] = dict(corememory)

    def get_value_from_corememory(self, key: str) -> Any:
        return self.corememory.get(key)

    def get_context(self, key: str) -> Any:
        return None

    def set_corememory(self, key: str, value: Any) -> None:
        self.corememory[key] = value


class _FakeMetrics:
    def __init__(self) -> None:
        self._turn_count = 0

    def restore_from_memo(self, _tokens: dict) -> None:  # pragma: no cover - unused
        pass


class _StandInAdapter:
    """Carries exactly the attributes ``sync_from_memo_manager`` touches."""

    def __init__(self, agents: dict[str, UnifiedAgent], active: str) -> None:
        self.agents = agents
        self._active_agent = active
        self._scenario_switch_pending = False
        self._visited_agents: set[str] = set()
        self._session_vars: dict[str, Any] = {}
        self._metrics = _FakeMetrics()

        class _Cfg:
            start_agent = active

        self.config = _Cfg()

    def sync_from_memo_manager(self, cm) -> None:
        """Delegate to the real implementation under test."""
        CascadeOrchestratorAdapter.sync_from_memo_manager(self, cm)


def _agent(name: str, *, voice: str) -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description=f"{name} test agent",
        handoff=HandoffConfig(trigger=f"handoff_{name.lower()}"),
        model=ModelConfig(deployment_id="gpt-4o"),
        voice=VoiceConfig(name=voice),
        prompt_template=f"You are {name}.",
    )


def _run_route_turn_prelude(memo: _FakeMemo, session_agent: UnifiedAgent | None):
    """Reproduce the two lines route_turn() runs before touching the LLM."""
    base_agents = {"BankingConcierge": _agent("BankingConcierge", voice=ALLOY)}
    stand_in = _StandInAdapter(dict(base_agents), "BankingConcierge")

    with (
        patch(
            "apps.artagent.backend.src.orchestration.unified.get_cascade_orchestrator",
            return_value=stand_in,
        ),
        patch(
            "apps.artagent.backend.src.orchestration.unified.get_session_agent",
            return_value=session_agent,
        ),
        patch(
            "apps.artagent.backend.src.orchestration.unified.get_scenario_from_corememory",
            return_value=None,
        ),
    ):
        adapter = _get_or_create_adapter(
            memo.session_id,
            "call-1",
            app_state=None,
            memo_manager=memo,
        )
        adapter.sync_from_memo_manager(memo)

    return adapter


def _clear_adapter_cache() -> None:
    from apps.artagent.backend.src.orchestration import unified

    unified._adapters.clear()


def test_tuned_agent_survives_the_creation_turn_memo_sync():
    """The bug: BankingConcierge from a previous connection replaced the tune."""
    _clear_adapter_cache()
    memo = _FakeMemo(active_agent="BankingConcierge")
    tuned = _agent("Concierge", voice=EMMA)

    adapter = _run_route_turn_prelude(memo, tuned)

    assert adapter._active_agent == "Concierge"
    assert adapter.agents["Concierge"].voice.name == EMMA


def test_tuned_agent_becomes_the_session_agent_of_record():
    _clear_adapter_cache()
    memo = _FakeMemo(active_agent="BankingConcierge")

    _run_route_turn_prelude(memo, _agent("Concierge", voice=EMMA))

    assert memo.corememory["active_agent"] == "Concierge"


def test_untuned_session_still_restores_the_memo_agent():
    """No session agent — MemoManager stays authoritative, unchanged behaviour.

    This is the continuity the per-turn sync exists for; the fix must not touch
    it.
    """
    _clear_adapter_cache()
    memo = _FakeMemo(active_agent="BankingConcierge")

    adapter = _run_route_turn_prelude(memo, None)

    assert adapter._active_agent == "BankingConcierge"


def test_later_turns_still_follow_memo_after_a_handoff():
    """A handoff made *during* the call must still propagate on the next turn.

    The creation-time write happens once, so it cannot pin the tuned agent for
    the rest of the session.
    """
    _clear_adapter_cache()
    memo = _FakeMemo(active_agent="BankingConcierge")
    adapter = _run_route_turn_prelude(memo, _agent("Concierge", voice=EMMA))
    assert adapter._active_agent == "Concierge"

    # A tool handoff later in the call writes FraudAgent to MemoManager.
    adapter.agents["FraudAgent"] = _agent("FraudAgent", voice=ALLOY)
    memo.corememory["active_agent"] = "FraudAgent"

    adapter.sync_from_memo_manager(memo)

    assert adapter._active_agent == "FraudAgent"


def test_cached_adapter_is_not_repinned_to_the_tuned_agent():
    """Re-entering route_turn returns the cached adapter without re-injecting."""
    _clear_adapter_cache()
    memo = _FakeMemo(active_agent="BankingConcierge")
    adapter = _run_route_turn_prelude(memo, _agent("Concierge", voice=EMMA))

    adapter.agents["FraudAgent"] = _agent("FraudAgent", voice=ALLOY)
    memo.corememory["active_agent"] = "FraudAgent"

    again = _run_route_turn_prelude(memo, _agent("Concierge", voice=EMMA))

    assert again is adapter
    assert again._active_agent == "FraudAgent"
    assert memo.corememory["active_agent"] == "FraudAgent"
