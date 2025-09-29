"""
Test ACS Events Handler Functionality
=====================================

Focused tests for the refactored ACS events handling.
"""

import sys

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from azure.core.messaging import CloudEvent

# The Lvagent audio stack depends on sounddevice, which is unavailable in CI.
# Inject a stub before importing handlers so tests can load without native deps.
sys.modules.setdefault("sounddevice", MagicMock())

from apps.rtagent.backend.api.v1.events.handlers import CallEventHandlers
from apps.rtagent.backend.api.v1.events.types import (
    CallEventContext,
    ACSEventTypes,
    V1EventTypes,
)


def run_async(coro):
    """Execute coroutine in a fresh event loop for pytest compatibility."""
    return asyncio.run(coro)


class TestCallEventHandlers:
    """Test individual event handlers."""

    @pytest.fixture
    def mock_context(self):
        """Create mock call event context."""
        event = CloudEvent(
            source="test",
            type=ACSEventTypes.CALL_CONNECTED,
            data={"callConnectionId": "test_123"},
        )

        context = CallEventContext(
            event=event,
            call_connection_id="test_123",
            event_type=ACSEventTypes.CALL_CONNECTED,
        )
        context.memo_manager = MagicMock()
        context.redis_mgr = MagicMock()
        context.app_state = MagicMock()
        context.app_state.redis_pool = None
        return context

    @patch("apps.rtagent.backend.api.v1.events.handlers.logger")
    def test_handle_call_initiated(self, mock_logger, mock_context):
        """Test call initiated handler."""
        mock_context.event_type = V1EventTypes.CALL_INITIATED
        mock_context.event.data = {
            "callConnectionId": "test_123",
            "target_number": "+1234567890",
            "api_version": "v1",
        }

        run_async(CallEventHandlers.handle_call_initiated(mock_context))

        # Verify context updates
        assert mock_context.memo_manager.update_context.called
        calls = mock_context.memo_manager.update_context.call_args_list

        # Extract all calls as dict
        updates = {call[0][0]: call[0][1] for call in calls}

        assert updates["call_initiated_via"] == "api"
        assert updates["api_version"] == "v1"
        assert updates["call_direction"] == "outbound"

    @patch("apps.rtagent.backend.api.v1.events.handlers.logger")
    def test_handle_inbound_call_received(self, mock_logger, mock_context):
        """Test inbound call received handler."""
        mock_context.event_type = V1EventTypes.INBOUND_CALL_RECEIVED
        mock_context.event.data = {
            "callConnectionId": "test_123",
            "from": {"kind": "phoneNumber", "phoneNumber": {"value": "+1987654321"}},
        }

        run_async(CallEventHandlers.handle_inbound_call_received(mock_context))

        # Verify context updates
        calls = mock_context.memo_manager.update_context.call_args_list
        updates = {call[0][0]: call[0][1] for call in calls}

        assert updates["call_direction"] == "inbound"
        assert updates["caller_id"] == "+1987654321"

    @patch("apps.rtagent.backend.api.v1.events.handlers.logger")
    def test_handle_call_connected_with_broadcast(
        self, mock_logger, mock_context
    ):
        """Test call connected handler with WebSocket broadcast."""
        mock_clients = [MagicMock(), MagicMock()]
        mock_context.clients = mock_clients
        mock_call_conn = MagicMock()
        mock_call_conn.list_participants.return_value = []
        mock_context.acs_caller = MagicMock()
        mock_context.acs_caller.get_call_connection.return_value = mock_call_conn

        with patch(
            "apps.rtagent.backend.api.v1.events.handlers.broadcast_message"
        ) as mock_broadcast, patch(
            "apps.rtagent.backend.api.v1.events.handlers.DTMFValidationLifecycle.setup_aws_connect_validation_flow",
            new=AsyncMock(),
        ):
            run_async(CallEventHandlers.handle_call_connected(mock_context))

            mock_broadcast.assert_called_once()
            # Verify message structure
            call_args, call_kwargs = mock_broadcast.call_args
            assert call_args[0] is None
            # Message should be JSON string
            import json

            message = json.loads(call_args[1])
            assert message["type"] == "call_connected"
            assert message["call_connection_id"] == "test_123"

    @patch("apps.rtagent.backend.api.v1.events.handlers.logger")
    def test_handle_dtmf_tone_received(self, mock_logger, mock_context):
        """Test DTMF tone handling."""
        mock_context.event_type = ACSEventTypes.DTMF_TONE_RECEIVED
        mock_context.event.data = {
            "callConnectionId": "test_123",
            "tone": "5",
            "sequenceId": 1,
        }

        # Mock current sequence
        mock_context.memo_manager.get_context.return_value = "123"

        run_async(CallEventHandlers.handle_dtmf_tone_received(mock_context))

        # Should update DTMF sequence
        mock_context.memo_manager.update_context.assert_called()

    def test_extract_caller_id_phone_number(self):
        """Test caller ID extraction from phone number."""
        caller_info = {"kind": "phoneNumber", "phoneNumber": {"value": "+1234567890"}}

        caller_id = CallEventHandlers._extract_caller_id(caller_info)
        assert caller_id == "+1234567890"

    def test_extract_caller_id_raw_id(self):
        """Test caller ID extraction from raw ID."""
        caller_info = {"kind": "other", "rawId": "user@domain.com"}

        caller_id = CallEventHandlers._extract_caller_id(caller_info)
        assert caller_id == "user@domain.com"

    def test_extract_caller_id_fallback(self):
        """Test caller ID extraction fallback."""
        caller_info = {}

        caller_id = CallEventHandlers._extract_caller_id(caller_info)
        assert caller_id == "unknown"


class TestEventProcessingFlow:
    """Test event processing flow."""

    @patch("apps.rtagent.backend.api.v1.events.handlers.logger")
    def test_webhook_event_routing(self, mock_logger):
        """Test webhook event router."""
        event = CloudEvent(
            source="test",
            type=ACSEventTypes.CALL_CONNECTED,
            data={"callConnectionId": "test_123"},
        )

        context = CallEventContext(
            event=event,
            call_connection_id="test_123",
            event_type=ACSEventTypes.CALL_CONNECTED,
        )

        with patch.object(CallEventHandlers, "handle_call_connected") as mock_handler:
            run_async(CallEventHandlers.handle_webhook_events(context))
            mock_handler.assert_called_once_with(context)

    @patch("apps.rtagent.backend.api.v1.events.handlers.logger")
    def test_unknown_event_type_handling(self, mock_logger):
        """Test handling of unknown event types."""
        event = CloudEvent(
            source="test",
            type="Unknown.Event.Type",
            data={"callConnectionId": "test_123"},
        )

        context = CallEventContext(
            event=event, call_connection_id="test_123", event_type="Unknown.Event.Type"
        )

        # Should handle gracefully without error
        run_async(CallEventHandlers.handle_webhook_events(context))

        # No specific handler should be called for unknown type
        # This should just log and continue


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
