"""
V1 Event Types
==============

Simple type definitions for V1 event processing inspired by Azure's Event Processor pattern.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable
from azure.core.messaging import CloudEvent

from src.stateful.state_managment import MemoManager


@dataclass
class CallEventContext:
    """
    Simplified context for call event processing.

    Inspired by Azure's Event Processor pattern but simplified for V1 needs.
    Contains only essential data for call event handling.
    """

    event: CloudEvent
    call_connection_id: str
    event_type: str
    memo_manager: Optional[MemoManager] = None
    redis_mgr: Optional[Any] = None
    acs_caller: Optional[Any] = None
    clients: Optional[list] = None

    def get_event_data(self) -> Dict[str, Any]:
        """Safely extract event data as dictionary."""
        try:
            data = self.event.data
            if isinstance(data, dict):
                return data
            elif isinstance(data, str):
                import json

                return json.loads(data)
            elif isinstance(data, bytes):
                import json

                return json.loads(data.decode("utf-8"))
            elif hasattr(data, "__dict__"):
                return data.__dict__
            else:
                return {}
        except Exception:
            return {}

    def get_event_field(self, field_name: str, default: Any = None) -> Any:
        """Safely get a field from event data."""
        return self.get_event_data().get(field_name, default)


@runtime_checkable
class CallEventHandler(Protocol):
    """Protocol for call event handlers following Azure Event Processor pattern."""

    async def __call__(self, context: CallEventContext) -> None:
        """Handle a call event with the given context."""
        ...


# Standard ACS event types
class ACSEventTypes:
    """Standard Azure Communication Services event types."""

    # Call Management
    CALL_CONNECTED = "Microsoft.Communication.CallConnected"
    CALL_DISCONNECTED = "Microsoft.Communication.CallDisconnected"
    CALL_TRANSFER_ACCEPTED = "Microsoft.Communication.CallTransferAccepted"
    CALL_TRANSFER_FAILED = "Microsoft.Communication.CallTransferFailed"
    CREATE_CALL_FAILED = "Microsoft.Communication.CreateCallFailed"
    ANSWER_CALL_FAILED = "Microsoft.Communication.AnswerCallFailed"

    # Participants
    PARTICIPANTS_UPDATED = "Microsoft.Communication.ParticipantsUpdated"

    # DTMF
    DTMF_TONE_RECEIVED = "Microsoft.Communication.ContinuousDtmfRecognitionToneReceived"
    DTMF_TONE_FAILED = "Microsoft.Communication.ContinuousDtmfRecognitionToneFailed"
    DTMF_TONE_STOPPED = "Microsoft.Communication.ContinuousDtmfRecognitionStopped"

    # Media
    PLAY_COMPLETED = "Microsoft.Communication.PlayCompleted"
    PLAY_FAILED = "Microsoft.Communication.PlayFailed"
    PLAY_CANCELED = "Microsoft.Communication.PlayCanceled"

    # Recognition
    RECOGNIZE_COMPLETED = "Microsoft.Communication.RecognizeCompleted"
    RECOGNIZE_FAILED = "Microsoft.Communication.RecognizeFailed"
    RECOGNIZE_CANCELED = "Microsoft.Communication.RecognizeCanceled"


# Custom V1 API event types for lifecycle management
class V1EventTypes:
    """Custom V1 API event types for call lifecycle management."""

    # API-initiated events
    CALL_INITIATED = "V1.Call.Initiated"
    INBOUND_CALL_RECEIVED = "V1.Call.InboundReceived"
    CALL_ANSWERED = "V1.Call.Answered"
    WEBHOOK_EVENTS = "V1.Webhook.Events"

    # State management events
    CALL_STATE_UPDATED = "V1.Call.StateUpdated"
    CALL_CLEANUP_REQUESTED = "V1.Call.CleanupRequested"
