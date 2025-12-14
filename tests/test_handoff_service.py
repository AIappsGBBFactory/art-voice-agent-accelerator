"""
Tests for HandoffService
=========================

Unit tests for the unified handoff resolution service.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.artagent.backend.voice.shared.handoff_service import (
    HandoffResolution,
    HandoffService,
    create_handoff_service,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_agent():
    """Create a mock UnifiedAgent."""
    agent = MagicMock()
    agent.name = "FraudAgent"
    agent.render_greeting.return_value = "Hi, I'm the fraud specialist. How can I help?"
    agent.render_return_greeting.return_value = "Welcome back! Let me continue helping you."
    return agent


@pytest.fixture
def mock_agents(mock_agent):
    """Create a mock agent registry."""
    concierge = MagicMock()
    concierge.name = "Concierge"
    concierge.render_greeting.return_value = "Hello! I'm your concierge."
    concierge.render_return_greeting.return_value = "Welcome back!"

    return {
        "Concierge": concierge,
        "FraudAgent": mock_agent,
        "InvestmentAdvisor": MagicMock(name="InvestmentAdvisor"),
    }


@pytest.fixture
def handoff_map():
    """Standard handoff map for testing."""
    return {
        "handoff_fraud": "FraudAgent",
        "handoff_investment": "InvestmentAdvisor",
        "handoff_concierge": "Concierge",
    }


@pytest.fixture
def service(mock_agents, handoff_map):
    """Create a HandoffService instance for testing."""
    return HandoffService(
        scenario_name="banking",
        handoff_map=handoff_map,
        agents=mock_agents,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF DETECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsHandoff:
    """Tests for is_handoff() method."""

    def test_handoff_tool_detected(self, service):
        """Handoff tools should be detected via registry."""
        with patch(
            "apps.artagent.backend.voice.shared.handoff_service.registry_is_handoff_tool"
        ) as mock_check:
            mock_check.return_value = True
            assert service.is_handoff("handoff_fraud") is True
            mock_check.assert_called_once_with("handoff_fraud")

    def test_non_handoff_tool(self, service):
        """Non-handoff tools should return False."""
        with patch(
            "apps.artagent.backend.voice.shared.handoff_service.registry_is_handoff_tool"
        ) as mock_check:
            mock_check.return_value = False
            assert service.is_handoff("search_accounts") is False


# ═══════════════════════════════════════════════════════════════════════════════
# TARGET RESOLUTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetHandoffTarget:
    """Tests for get_handoff_target() method."""

    def test_target_found(self, service):
        """Should return target agent from handoff map."""
        assert service.get_handoff_target("handoff_fraud") == "FraudAgent"

    def test_target_not_found(self, service):
        """Should return None for unknown tool."""
        assert service.get_handoff_target("unknown_tool") is None


# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF RESOLUTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveHandoff:
    """Tests for resolve_handoff() method."""

    def test_successful_resolution(self, service):
        """Should resolve handoff with all required fields."""
        with patch(
            "apps.artagent.backend.voice.shared.handoff_service.get_handoff_config"
        ) as mock_config:
            mock_config.return_value = MagicMock(
                type="announced",
                share_context=True,
                greet_on_switch=True,
            )

            resolution = service.resolve_handoff(
                tool_name="handoff_fraud",
                tool_args={"reason": "fraud inquiry"},
                source_agent="Concierge",
                current_system_vars={"session_profile": {"name": "John"}},
                user_last_utterance="I think my card was stolen",
            )

            assert resolution.success is True
            assert resolution.target_agent == "FraudAgent"
            assert resolution.source_agent == "Concierge"
            assert resolution.tool_name == "handoff_fraud"
            assert resolution.greet_on_switch is True
            assert resolution.share_context is True
            assert resolution.handoff_type == "announced"

    def test_discrete_handoff_resolution(self, service):
        """Should respect discrete handoff type from scenario config."""
        with patch(
            "apps.artagent.backend.voice.shared.handoff_service.get_handoff_config"
        ) as mock_config:
            mock_config.return_value = MagicMock(
                type="discrete",
                share_context=True,
                greet_on_switch=False,
            )

            resolution = service.resolve_handoff(
                tool_name="handoff_fraud",
                tool_args={"reason": "returning customer"},
                source_agent="Concierge",
                current_system_vars={},
            )

            assert resolution.success is True
            assert resolution.greet_on_switch is False
            assert resolution.handoff_type == "discrete"
            assert resolution.is_discrete is True
            assert resolution.is_announced is False

    def test_unknown_tool_fails(self, service):
        """Should fail if tool not in handoff map."""
        resolution = service.resolve_handoff(
            tool_name="unknown_handoff",
            tool_args={},
            source_agent="Concierge",
            current_system_vars={},
        )

        assert resolution.success is False
        assert resolution.error is not None
        assert "No target agent configured" in resolution.error

    def test_unknown_agent_fails(self, mock_agents, handoff_map):
        """Should fail if target agent not in registry."""
        # Add a handoff to non-existent agent
        handoff_map["handoff_unknown"] = "NonExistentAgent"

        service = HandoffService(
            scenario_name="banking",
            handoff_map=handoff_map,
            agents=mock_agents,
        )

        resolution = service.resolve_handoff(
            tool_name="handoff_unknown",
            tool_args={},
            source_agent="Concierge",
            current_system_vars={},
        )

        assert resolution.success is False
        assert resolution.target_agent == "NonExistentAgent"
        assert "not found in registry" in resolution.error

    def test_system_vars_built_correctly(self, service):
        """Should build system_vars with handoff context."""
        with patch(
            "apps.artagent.backend.voice.shared.handoff_service.get_handoff_config"
        ) as mock_config:
            mock_config.return_value = MagicMock(
                type="announced",
                share_context=True,
                greet_on_switch=True,
            )

            resolution = service.resolve_handoff(
                tool_name="handoff_fraud",
                tool_args={"reason": "fraud inquiry"},
                source_agent="Concierge",
                current_system_vars={
                    "session_profile": {"name": "John"},
                    "client_id": "12345",
                },
                user_last_utterance="I think my card was stolen",
            )

            assert resolution.success is True
            system_vars = resolution.system_vars

            # Should have handoff context
            assert system_vars.get("previous_agent") == "Concierge"
            assert system_vars.get("active_agent") == "FraudAgent"
            assert system_vars.get("is_handoff") is True


# ═══════════════════════════════════════════════════════════════════════════════
# GREETING SELECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestSelectGreeting:
    """Tests for select_greeting() method."""

    def test_first_visit_greeting(self, service, mock_agent):
        """Should use agent's greeting template for first visit."""
        greeting = service.select_greeting(
            agent=mock_agent,
            is_first_visit=True,
            greet_on_switch=True,
            system_vars={"caller_name": "John"},
        )

        assert greeting is not None
        mock_agent.render_greeting.assert_called_once()

    def test_return_greeting(self, service, mock_agent):
        """Should use agent's return_greeting template for repeat visit."""
        greeting = service.select_greeting(
            agent=mock_agent,
            is_first_visit=False,
            greet_on_switch=True,
            system_vars={},
        )

        assert greeting is not None
        mock_agent.render_return_greeting.assert_called_once()

    def test_discrete_handoff_no_greeting(self, service, mock_agent):
        """Discrete handoffs should not produce a greeting."""
        greeting = service.select_greeting(
            agent=mock_agent,
            is_first_visit=True,
            greet_on_switch=False,  # Discrete
            system_vars={},
        )

        assert greeting is None
        mock_agent.render_greeting.assert_not_called()

    def test_explicit_greeting_override(self, service, mock_agent):
        """Explicit greeting in system_vars should override template."""
        greeting = service.select_greeting(
            agent=mock_agent,
            is_first_visit=True,
            greet_on_switch=True,
            system_vars={"greeting": "Custom greeting message"},
        )

        assert greeting == "Custom greeting message"
        mock_agent.render_greeting.assert_not_called()

    def test_session_overrides_greeting(self, service, mock_agent):
        """Greeting from session_overrides should be used."""
        greeting = service.select_greeting(
            agent=mock_agent,
            is_first_visit=True,
            greet_on_switch=True,
            system_vars={"session_overrides": {"greeting": "Override greeting"}},
        )

        assert greeting == "Override greeting"


# ═══════════════════════════════════════════════════════════════════════════════
# GREETING CONTEXT TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildGreetingContext:
    """Tests for _build_greeting_context() method."""

    def test_extracts_identity_fields(self, service):
        """Should extract core identity fields from system_vars."""
        system_vars = {
            "caller_name": "John Doe",
            "client_id": "12345",
            "institution_name": "Contoso Bank",
            "customer_intelligence": {"tier": "premium"},
        }

        context = service._build_greeting_context(system_vars)

        assert context["caller_name"] == "John Doe"
        assert context["client_id"] == "12345"
        assert context["institution_name"] == "Contoso Bank"
        assert context["customer_intelligence"]["tier"] == "premium"

    def test_extracts_from_handoff_context(self, service):
        """Should extract fields from handoff_context if not in system_vars."""
        system_vars = {
            "handoff_context": {
                "caller_name": "Jane",
                "client_id": "67890",
            }
        }

        context = service._build_greeting_context(system_vars)

        assert context["caller_name"] == "Jane"
        assert context["client_id"] == "67890"

    def test_extracts_from_session_profile(self, service):
        """Should extract from session_profile as fallback."""
        system_vars = {
            "session_profile": {
                "full_name": "Bob Smith",
                "client_id": "11111",
                "institution_name": "Acme Corp",
            }
        }

        context = service._build_greeting_context(system_vars)

        assert context["caller_name"] == "Bob Smith"
        assert context["client_id"] == "11111"
        assert context["institution_name"] == "Acme Corp"

    def test_priority_direct_over_nested(self, service):
        """Direct system_vars should take priority over nested sources."""
        system_vars = {
            "caller_name": "Direct Name",
            "session_profile": {"full_name": "Profile Name"},
            "handoff_context": {"caller_name": "Handoff Name"},
        }

        context = service._build_greeting_context(system_vars)

        assert context["caller_name"] == "Direct Name"


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateHandoffService:
    """Tests for create_handoff_service() factory function."""

    def test_creates_with_explicit_args(self, mock_agents, handoff_map):
        """Should create service with explicitly provided arguments."""
        service = create_handoff_service(
            scenario_name="banking",
            agents=mock_agents,
            handoff_map=handoff_map,
        )

        assert service.scenario_name == "banking"
        assert len(service.available_agents) == 3
        assert service.handoff_map == handoff_map

    def test_creates_without_agents(self):
        """Should create service even when agent discovery fails."""
        # When agents can't be loaded, service should still be created
        # with empty agents dict
        service = create_handoff_service(
            scenario_name="test",
            agents=None,
            handoff_map={"test_tool": "TestAgent"},
        )

        # Should have the provided handoff_map
        assert service.handoff_map == {"test_tool": "TestAgent"}
        # Scenario should be set
        assert service.scenario_name == "test"


# ═══════════════════════════════════════════════════════════════════════════════
# HANDOFF RESOLUTION DATACLASS TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandoffResolution:
    """Tests for HandoffResolution dataclass."""

    def test_is_discrete_property(self):
        """is_discrete should return True for discrete type."""
        resolution = HandoffResolution(
            success=True,
            handoff_type="discrete",
        )
        assert resolution.is_discrete is True
        assert resolution.is_announced is False

    def test_is_announced_property(self):
        """is_announced should return True for announced type."""
        resolution = HandoffResolution(
            success=True,
            handoff_type="announced",
        )
        assert resolution.is_discrete is False
        assert resolution.is_announced is True

    def test_default_values(self):
        """Should have sensible defaults."""
        resolution = HandoffResolution(success=True)

        assert resolution.target_agent == ""
        assert resolution.source_agent == ""
        assert resolution.system_vars == {}
        assert resolution.greet_on_switch is True
        assert resolution.share_context is True
        assert resolution.handoff_type == "announced"
        assert resolution.error is None
