# Ensure telemetry is disabled for unit tests to avoid the ProxyLogger/resource issue
import os

# Disable cloud telemetry so utils/ml_logging avoids attaching OpenTelemetry LoggingHandler.
# This must be set before importing modules that call get_logger() at import time.
os.environ.setdefault("DISABLE_CLOUD_TELEMETRY", "true")
# Also ensure Application Insights connection string is not set (prevents other code paths)
os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.rtagent.backend.api.v1.handlers.dtmf_validation_lifecycle import (
    DTMFValidationLifecycle,
)


class DummyMemo:
    def __init__(self):
        self._d = {}
        self.persist_calls = 0

    def get_context(self, key, default=None):
        return self._d.get(key, default)

    def set_context(self, key, value):
        self._d[key] = value

    def update_context(self, key, value):
        self._d[key] = value

    async def persist_to_redis_async(self, redis_mgr):
        self.persist_calls += 1


class DummyContext:
    def __init__(self, event_data, memo_manager=None, redis_mgr=None, acs_caller=None):
        self._event_data = event_data
        self.memo_manager = memo_manager
        self.redis_mgr = redis_mgr
        self.acs_caller = acs_caller
        self.call_connection_id = "call-123"

    def get_event_data(self):
        return self._event_data


class DummyRedis:
    def __init__(self, result):
        self._result = result

    async def read_events_blocking_async(self, **kwargs):
        return self._result


def test_is_dtmf_validation_gate_open():
    memo = DummyMemo()
    memo.set_context("dtmf_validation_gate_open", True)

    assert DTMFValidationLifecycle.is_dtmf_validation_gate_open(memo, "call")

    memo.set_context("dtmf_validation_gate_open", False)
    assert not DTMFValidationLifecycle.is_dtmf_validation_gate_open(memo, "call")


@pytest.mark.asyncio
async def test_handle_dtmf_tone_received_updates_sequence():
    memo = DummyMemo()
    redis_mgr = AsyncMock()
    context = DummyContext(
        {"tone": "5", "sequenceId": 1}, memo_manager=memo, redis_mgr=redis_mgr
    )

    await DTMFValidationLifecycle.handle_dtmf_tone_received(context)

    assert memo.get_context("dtmf_tone") == "5"
    assert memo.persist_calls == 1


@pytest.mark.asyncio
async def test_handle_dtmf_tone_received_routes_to_validation_flow():
    memo = DummyMemo()
    memo.set_context("aws_connect_validation_pending", True)
    context = DummyContext({"tone": "1", "sequenceId": 2}, memo_manager=memo)

    with patch.object(
        DTMFValidationLifecycle,
        "_handle_aws_connect_validation_tone",
        new=AsyncMock(),
    ) as mock_handler:
        await DTMFValidationLifecycle.handle_dtmf_tone_received(context)

    mock_handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_aws_connect_validation_flow_sets_context():
    memo = DummyMemo()
    redis_mgr = AsyncMock()
    context = DummyContext({}, memo_manager=memo, redis_mgr=redis_mgr)
    call_conn = MagicMock()

    with patch.object(
        DTMFValidationLifecycle,
        "_start_dtmf_recognition",
        new=AsyncMock(),
    ) as mock_start:
        await DTMFValidationLifecycle.setup_aws_connect_validation_flow(
            context, call_conn
        )

    assert memo.get_context("aws_connect_validation_pending") is True
    assert memo.get_context("aws_connect_input_sequence") == ""
    digits = memo.get_context("aws_connect_validation_digits")
    assert isinstance(digits, str) and len(digits) == 3
    assert memo.persist_calls == 1
    mock_start.assert_awaited_once_with(context, call_conn)


@pytest.mark.asyncio
async def test_wait_for_dtmf_validation_completion_success():
    redis_mgr = DummyRedis(result={"validation_status": "completed"})

    result = await DTMFValidationLifecycle.wait_for_dtmf_validation_completion(
        redis_mgr, "call-1"
    )

    assert result is True


@pytest.mark.asyncio
async def test_wait_for_dtmf_validation_completion_timeout():
    redis_mgr = DummyRedis(result=None)

    result = await DTMFValidationLifecycle.wait_for_dtmf_validation_completion(
        redis_mgr, "call-1"
    )

    assert result is False
