"""
Voice Live BYOM (Bring Your Own Model) Config
=============================================

Validates the per-agent BYOM config that drives the VoiceLive connect() query
param (``profile``). BYOM is opt-in: when no mode is set the agent connects with
managed VoiceLive (no profile param).

Covers:
  * VoiceLiveBYOMConfig.from_dict normalization (disabled vs enabled, alt keys).
  * to_query() shaping for connect(..., query=...).
  * UnifiedAgent.get_byom_query() delegation.
  * The agent_builder ByomConfigSchema mode validator.
"""

from __future__ import annotations

import pytest

from apps.artagent.backend.registries.agentstore.base import (
    VOICELIVE_BYOM_MODES,
    HandoffConfig,
    ModelConfig,
    UnifiedAgent,
    VoiceLiveBYOMConfig,
)


# =============================================================================
# VoiceLiveBYOMConfig.from_dict — disabled cases
# =============================================================================


@pytest.mark.parametrize("data", [None, {}, {"mode": ""}, {"mode": "   "}])
def test_from_dict_disabled_returns_none(data):
    """Empty/whitespace/missing mode (and no override) → disabled (None)."""
    assert VoiceLiveBYOMConfig.from_dict(data) is None


# =============================================================================
# VoiceLiveBYOMConfig.from_dict — enabled cases
# =============================================================================


def test_from_dict_mode_only():
    cfg = VoiceLiveBYOMConfig.from_dict({"mode": "byom-foundry-anthropic-messages"})
    assert cfg is not None
    assert cfg.mode == "byom-foundry-anthropic-messages"
    assert cfg.to_query() == {"profile": "byom-foundry-anthropic-messages"}


def test_from_dict_accepts_byom_alias():
    """`byom` is accepted as an alias for `mode`."""
    cfg = VoiceLiveBYOMConfig.from_dict({"byom": "byom-azure-openai-chat-completion"})
    assert cfg is not None
    assert cfg.mode == "byom-azure-openai-chat-completion"
    assert cfg.to_query() == {"profile": "byom-azure-openai-chat-completion"}


def test_to_dict_round_trip():
    cfg = VoiceLiveBYOMConfig.from_dict({"mode": "byom-azure-openai-realtime"})
    assert cfg.to_dict() == {"mode": "byom-azure-openai-realtime"}
    # Re-parsing the serialized form yields an equivalent query.
    assert VoiceLiveBYOMConfig.from_dict(cfg.to_dict()).to_query() == cfg.to_query()


def test_to_query_disabled_when_mode_missing():
    """No mode → BYOM disabled → query is None."""
    cfg = VoiceLiveBYOMConfig(mode=None)
    assert cfg.to_query() is None


# =============================================================================
# UnifiedAgent.get_byom_query — delegation
# =============================================================================


def _make_agent(byom: VoiceLiveBYOMConfig | None) -> UnifiedAgent:
    return UnifiedAgent(
        name="ByomAgent",
        description="byom test agent",
        handoff=HandoffConfig(trigger="handoff_byomagent"),
        model=ModelConfig(deployment_id="gpt-realtime"),
        byom=byom,
        prompt_template="You are a test agent.",
    )


def test_agent_get_byom_query_none_when_unset():
    assert _make_agent(None).get_byom_query() is None


def test_agent_get_byom_query_returns_profile():
    cfg = VoiceLiveBYOMConfig.from_dict({"mode": "byom-azure-openai-realtime"})
    assert _make_agent(cfg).get_byom_query() == {"profile": "byom-azure-openai-realtime"}


# =============================================================================
# agent_builder ByomConfigSchema — mode validation at the API boundary
# =============================================================================


def test_schema_rejects_invalid_mode():
    from apps.artagent.backend.api.v1.endpoints.agent_builder import ByomConfigSchema

    with pytest.raises(ValueError):
        ByomConfigSchema(mode="not-a-real-mode")


@pytest.mark.parametrize("mode", VOICELIVE_BYOM_MODES)
def test_schema_accepts_known_modes(mode):
    from apps.artagent.backend.api.v1.endpoints.agent_builder import ByomConfigSchema

    assert ByomConfigSchema(mode=mode).mode == mode


def test_schema_blank_mode_normalizes_to_none():
    from apps.artagent.backend.api.v1.endpoints.agent_builder import ByomConfigSchema

    assert ByomConfigSchema(mode="   ").mode is None


# =============================================================================
# The cross-field invariant the earlier tests could NOT catch
# =============================================================================
#
# Every test above validates BYOM in ISOLATION and treats byom=None as correct
# (it IS correct for a managed model like gpt-realtime). None of them relate the
# chosen *model* to the BYOM flag, so the real production misconfig — a BYOM-only
# model (o3-mini) saved with BYOM OFF, which connects as managed and goes silent —
# slipped through. These tests encode that missing invariant.


@pytest.mark.parametrize(
    "deployment_id, managed",
    [
        ("gpt-realtime", True),
        ("gpt-4o", True),
        ("GPT-4O", True),  # case-insensitive
        ("gpt-5.4", True),
        (None, True),  # empty → nothing to validate (runtime default)
        ("", True),
        ("o3-mini", False),  # the jinlocal failure model — BYOM-only
        ("o1", False),
        ("o3", False),
        ("gpt-5-chat", False),  # plain chat (not the versioned gpt-5.x-chat)
        ("my-finetuned-deployment", False),
    ],
)
def test_is_managed_voicelive_model(deployment_id, managed):
    from apps.artagent.backend.registries.agentstore.base import (
        is_managed_voicelive_model,
    )

    assert is_managed_voicelive_model(deployment_id) is managed


def test_build_session_agent_flags_non_managed_model_without_byom(caplog):
    """Reproduce the exact jinlocal misconfig and assert it is now detectable.

    o3-mini selected for VoiceLive with byom=None is what silently connected to
    managed Voice Live and made the agent go dead. build_session_agent must both
    build the (poisoned) agent AND emit the guard warning so the save is no longer
    silent — this is precisely what no prior test asserted.
    """
    import logging

    from apps.artagent.backend.api.v1.endpoints.agent_builder import (
        DynamicAgentConfig,
        ModelConfigSchema,
        build_session_agent,
    )
    from apps.artagent.backend.registries.agentstore.base import (
        is_managed_voicelive_model,
    )

    cfg = DynamicAgentConfig(
        name="BankingConcierge",
        prompt="You are a helpful banking concierge agent.",
        voicelive_model=ModelConfigSchema(deployment_id="o3-mini"),
        byom=None,  # <-- the misconfig: BYOM-only model, BYOM left off
    )

    with caplog.at_level(logging.WARNING, logger="v1.agent_builder"):
        agent = build_session_agent(cfg, "sess-misconfig", created_at=0.0)

    # The agent is built with the exact silent-failure shape...
    assert agent.get_model_for_mode("voicelive").deployment_id == "o3-mini"
    assert agent.byom is None
    assert not is_managed_voicelive_model("o3-mini")
    # ...and the save path now flags it (was silent before this guard existed).
    assert any(
        "non_managed_voicelive_without_byom" in rec.getMessage()
        for rec in caplog.records
    )


def test_build_session_agent_non_managed_with_byom_is_clean(caplog):
    """Adding the BYOM profile fixes the misconfig: byom persists, no warning."""
    import logging

    from apps.artagent.backend.api.v1.endpoints.agent_builder import (
        ByomConfigSchema,
        DynamicAgentConfig,
        ModelConfigSchema,
        build_session_agent,
    )

    cfg = DynamicAgentConfig(
        name="BankingConcierge",
        prompt="You are a helpful banking concierge agent.",
        voicelive_model=ModelConfigSchema(deployment_id="o3-mini"),
        byom=ByomConfigSchema(mode="byom-azure-openai-chat-completion"),
    )

    with caplog.at_level(logging.WARNING, logger="v1.agent_builder"):
        agent = build_session_agent(cfg, "sess-fixed", created_at=0.0)

    assert agent.byom is not None
    assert agent.byom.mode == "byom-azure-openai-chat-completion"
    assert not any(
        "non_managed_voicelive_without_byom" in rec.getMessage()
        for rec in caplog.records
    )


def test_build_session_agent_managed_model_without_byom_is_clean(caplog):
    """A managed model (gpt-realtime) with BYOM off is valid — no warning."""
    import logging

    from apps.artagent.backend.api.v1.endpoints.agent_builder import (
        DynamicAgentConfig,
        ModelConfigSchema,
        build_session_agent,
    )

    cfg = DynamicAgentConfig(
        name="BankingConcierge",
        prompt="You are a helpful banking concierge agent.",
        voicelive_model=ModelConfigSchema(deployment_id="gpt-realtime"),
        byom=None,
    )

    with caplog.at_level(logging.WARNING, logger="v1.agent_builder"):
        agent = build_session_agent(cfg, "sess-managed", created_at=0.0)

    assert agent.byom is None
    assert not any(
        "non_managed_voicelive_without_byom" in rec.getMessage()
        for rec in caplog.records
    )
