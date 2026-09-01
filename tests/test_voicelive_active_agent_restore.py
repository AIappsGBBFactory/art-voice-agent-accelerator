"""
VoiceLive: which agent a reconnected session actually starts as
===============================================================

``LiveOrchestrator._sync_from_memo_manager()`` runs once, from ``__init__``,
*after* the Voice Live WebSocket is already open. Restoring the ``active_agent``
persisted by an earlier connection on the same ``session_id`` is therefore never
neutral — ``connect()`` has already frozen the generative model and the BYOM
profile around the agent this connection was established for.

The incident these tests pin down: a caller tuned ``Concierge`` (Emma voice,
``gpt-4o-mini``) via Agent Builder, the connection was bound to ``gpt-4o-mini``
as asked, and then a ``BankingConcierge`` left behind by a previous connection
was restored over it — bringing its own Alloy voice and instructions, and asking
for a ``gpt-realtime`` the connection could no longer switch to. The session
greeted and then never answered again, and from the caller's seat that read as
"I picked a different voice and only the default persisted".

Covered here:

* a session-scoped (Quick Tune) agent outranks anything MemoManager restores,
  and the session contract from the diagnostic flips back to ``agent_ok``;
* a restore that contradicts the bound model is refused even without tuning,
  because Voice Live cannot change the model mid-call;
* deployment-tier (SKU) differences are *not* a conflict;
* genuine mid-call continuity — resuming on the agent a previous connection
  handed off to, when the bound model can still serve it — still works;
* an explicit scenario switch still wins over everything.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.artagent.backend.registries.agentstore.base import (
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceConfig,
)
from apps.artagent.backend.voice.shared.config_resolver import (
    OrchestratorConfigResult,
    build_effective_registry,
)
from apps.artagent.backend.voice.voicelive.orchestrator import LiveOrchestrator

EMMA = "en-US-EmmaMultilingualNeural"
ALLOY = "en-US-AlloyTurboMultilingualNeural"


# =============================================================================
# Fakes
# =============================================================================


class _FakeSessionNamespace:
    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def update(self, session=None, **_kwargs):
        self.updates.append(session)


class _FakeConnection:
    def __init__(self) -> None:
        self.session = _FakeSessionNamespace()


class _EchoSession:
    """Stand-in for the ``session`` object on a ``session.updated`` event."""

    def __init__(self, voice: Any = None, model: str | None = None) -> None:
        self.id = "sess-1"
        self.voice = voice
        self.model = model


class _EchoVoice:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeMemo:
    """In-memory MemoManager stand-in.

    Only the surface ``sync_state_from_memo`` / ``sync_state_to_memo`` actually
    touch: corememory get/set plus a context read.
    """

    def __init__(self, **corememory: Any) -> None:
        self.session_id = "sess-1"
        self.corememory: dict[str, Any] = dict(corememory)
        self.writes: list[tuple[str, Any]] = []

    def get_value_from_corememory(self, key: str) -> Any:
        return self.corememory.get(key)

    def get_context(self, key: str) -> Any:  # pragma: no cover - parity shim
        return None

    def set_corememory(self, key: str, value: Any) -> None:
        self.corememory[key] = value
        self.writes.append((key, value))


def _agent(
    name: str,
    *,
    voice: str,
    voicelive_model: str,
) -> UnifiedAgent:
    return UnifiedAgent(
        name=name,
        description=f"{name} test agent",
        handoff=HandoffConfig(trigger=f"handoff_{name.lower()}"),
        model=ModelConfig(deployment_id=voicelive_model),
        voicelive_model=ModelConfig(deployment_id=voicelive_model),
        voice=VoiceConfig(name=voice),
        prompt_template=f"You are {name}.",
    )


def _orchestrator(
    *,
    agents: dict[str, UnifiedAgent],
    start_agent: str,
    model_name: str,
    memo: _FakeMemo | None,
    authoritative: bool = False,
) -> LiveOrchestrator:
    config = OrchestratorConfigResult(
        start_agent=start_agent,
        start_agent_authoritative=authoritative,
    )
    return LiveOrchestrator(
        conn=_FakeConnection(),
        agents=agents,
        start_agent=start_agent,
        model_name=model_name,
        memo_manager=memo,
        orchestrator_config=config,
    )


def _tuned_registry() -> dict[str, UnifiedAgent]:
    """The production pairing: a tuned Concierge next to a stale BankingConcierge."""
    return {
        "Concierge": _agent("Concierge", voice=EMMA, voicelive_model="gpt-4o-mini"),
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime"),
    }


# =============================================================================
# (a) The production incident
# =============================================================================


def test_tuned_session_agent_survives_a_stale_memo_active_agent():
    """The reported bug: Concierge was tuned, BankingConcierge came back instead."""
    memo = _FakeMemo(active_agent="BankingConcierge")

    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=memo,
        authoritative=True,
    )

    assert orch.active == "Concierge"
    assert orch.agents[orch.active].voice.name == EMMA


def test_refused_restore_reanchors_memo_so_the_next_connection_is_clean():
    memo = _FakeMemo(active_agent="BankingConcierge")

    _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=memo,
        authoritative=True,
    )

    assert memo.corememory["active_agent"] == "Concierge"


def test_production_scenario_reports_agent_ok_on_the_session_contract():
    """Ties the fix to the diagnostic added for this incident.

    Before the fix this exact setup reported ``agent_ok: False`` /
    ``overall_ok: False`` — bound=Concierge, active=BankingConcierge.
    """
    memo = _FakeMemo(active_agent="BankingConcierge")
    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=memo,
        authoritative=True,
    )

    contract = orch._verify_session_contract(
        _EchoSession(voice=_EchoVoice(EMMA), model="gpt-4o-mini")
    )

    assert contract is not None
    assert contract["bound_agent"] == "Concierge"
    assert contract["active_agent"] == "Concierge"
    assert contract["agent_ok"] is True
    assert contract["model_override_ignored"] is False
    assert contract["voice_ok"] is True
    assert contract["overall_ok"] is True


# =============================================================================
# (b) A restore the bound model cannot serve
# =============================================================================


def test_restore_is_refused_when_the_agent_needs_a_different_model():
    """No tuning involved — the connection simply cannot run that agent.

    Voice Live binds the model at ``connect()``; honouring this restore is what
    produced "a greeting and then nothing".
    """
    memo = _FakeMemo(active_agent="BankingConcierge")

    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=memo,
        authoritative=False,
    )

    assert orch.active == "Concierge"
    assert orch._memo_restore_conflict("BankingConcierge") == "model_bound"


def test_authority_is_reported_ahead_of_the_model_conflict():
    """Both guards apply; the tuned-agent reason is the one that explains the call."""
    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=None,
        authoritative=True,
    )

    assert orch._memo_restore_conflict("BankingConcierge") == "session_agent_authoritative"


def test_deployment_tier_suffix_is_not_a_model_conflict():
    """``gpt-realtime`` and ``gpt-realtime-datazone-standard`` are the same model."""
    agents = {
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime"),
        "FraudAgent": _agent("FraudAgent", voice=ALLOY, voicelive_model="gpt-realtime"),
    }
    memo = _FakeMemo(active_agent="FraudAgent")

    orch = _orchestrator(
        agents=agents,
        start_agent="BankingConcierge",
        model_name="gpt-realtime-datazone-standard",
        memo=memo,
    )

    assert orch.active == "FraudAgent"


# =============================================================================
# (c) Continuity that must keep working
# =============================================================================


def test_previous_connection_handoff_still_resumes_on_the_same_agent():
    """The reason the restore exists: reconnect mid-conversation after a handoff.

    Nothing was tuned and the bound model serves both agents, so resuming on
    FraudAgent is correct and must not be collateral damage of the fix.
    """
    agents = {
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime"),
        "FraudAgent": _agent("FraudAgent", voice=ALLOY, voicelive_model="gpt-realtime"),
    }
    memo = _FakeMemo(active_agent="FraudAgent")

    orch = _orchestrator(
        agents=agents,
        start_agent="BankingConcierge",
        model_name="gpt-realtime",
        memo=memo,
    )

    assert orch.active == "FraudAgent"
    assert orch._memo_restore_conflict("FraudAgent") is None


def test_restore_of_the_start_agent_itself_is_never_a_conflict():
    """Even a tuned connection may legitimately re-read its own agent."""
    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=None,
        authoritative=True,
    )

    assert orch._memo_restore_conflict("Concierge") is None


def test_unknown_agent_never_becomes_a_refusal():
    """The guard must not invent conflicts it cannot actually evaluate."""
    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=None,
        authoritative=False,
    )

    assert orch._memo_restore_conflict("NotInRegistry") is None


# =============================================================================
# (d) Scenario switch still outranks the memo
# =============================================================================


def test_scenario_switch_pending_still_wins_over_the_memo():
    agents = {
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime"),
        "FraudAgent": _agent("FraudAgent", voice=ALLOY, voicelive_model="gpt-realtime"),
    }
    memo = _FakeMemo(active_agent="FraudAgent")

    orch = _orchestrator(
        agents=agents,
        start_agent="BankingConcierge",
        model_name="gpt-realtime",
        memo=None,
    )
    orch._memo_manager = memo
    orch._scenario_switch_pending = True

    orch._sync_from_memo_manager()

    assert orch.active == "BankingConcierge"
    assert memo.corememory["active_agent"] == "BankingConcierge"
    assert orch._scenario_switch_pending is False


# =============================================================================
# (e) The signal itself
# =============================================================================


def test_build_effective_registry_marks_a_session_agent_as_authoritative():
    base = {
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime")
    }
    session_agent = _agent("Concierge", voice=EMMA, voicelive_model="gpt-4o-mini")
    config = OrchestratorConfigResult(start_agent="BankingConcierge")

    _agents, start_agent, _map = build_effective_registry(
        config,
        base_agents=base,
        session_agent=session_agent,
    )

    assert start_agent == "Concierge"
    assert config.start_agent_authoritative is True


def test_build_effective_registry_leaves_a_plain_scenario_start_unmarked():
    base = {
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime")
    }
    config = OrchestratorConfigResult(start_agent="BankingConcierge")

    _agents, start_agent, _map = build_effective_registry(
        config,
        base_agents=base,
        session_agent=None,
    )

    assert start_agent == "BankingConcierge"
    assert config.start_agent_authoritative is False


def test_orchestrator_defaults_to_non_authoritative_without_a_config():
    """Direct construction (tests, ad-hoc callers) keeps the permissive behaviour."""
    orch = LiveOrchestrator(
        conn=_FakeConnection(),
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
    )

    assert orch._start_agent_authoritative is False


# =============================================================================
# pending_handoff carries the same constraint
# =============================================================================


def test_pending_handoff_to_a_model_incompatible_agent_is_refused():
    memo = _FakeMemo(pending_handoff={"target_agent": "BankingConcierge"})

    orch = _orchestrator(
        agents=_tuned_registry(),
        start_agent="Concierge",
        model_name="gpt-4o-mini",
        memo=memo,
    )

    assert orch.active == "Concierge"
    assert memo.corememory["active_agent"] == "Concierge"


def test_pending_handoff_to_a_servable_agent_is_honored():
    agents = {
        "BankingConcierge": _agent("BankingConcierge", voice=ALLOY, voicelive_model="gpt-realtime"),
        "FraudAgent": _agent("FraudAgent", voice=ALLOY, voicelive_model="gpt-realtime"),
    }
    memo = _FakeMemo(pending_handoff={"target_agent": "FraudAgent"})

    orch = _orchestrator(
        agents=agents,
        start_agent="BankingConcierge",
        model_name="gpt-realtime",
        memo=memo,
    )

    assert orch.active == "FraudAgent"
