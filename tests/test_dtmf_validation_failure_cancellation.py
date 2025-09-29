"""Tests for DTMF validation completion and helper utilities."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.rtagent.backend.api.v1.handlers.dtmf_validation_lifecycle import (
    DTMFValidationLifecycle,
)
from apps.rtagent.backend.api.v1.events.types import CallEventContext


class DummyMemo:
    def __init__(self):
        self._d = {}
        self.persist_calls = 0

    def set_context(self, key, value):
        self._d[key] = value

    def get_context(self, key, default=None):
        return self._d.get(key, default)

    def update_context(self, key, value):
        self._d[key] = value

    async def persist_to_redis_async(self, redis_mgr):
        self.persist_calls += 1


class DummyContext:
    def __init__(self, memo_manager=None, redis_mgr=None):
        self.call_connection_id = "test-call-123"
        self.memo_manager = memo_manager
        self.redis_mgr = redis_mgr
        self.acs_caller = MagicMock()


@pytest.fixture
def context_with_memo():
    memo = DummyMemo()
    redis_mgr = AsyncMock()
    redis_mgr.add_event_async = AsyncMock()
    redis_mgr.set_value_async = AsyncMock()
    return DummyContext(memo_manager=memo, redis_mgr=redis_mgr), memo, redis_mgr


@pytest.mark.asyncio
async def test_complete_validation_success_sets_flags(context_with_memo):
    context, memo, redis_mgr = context_with_memo

    await DTMFValidationLifecycle._complete_aws_connect_validation(
        context, input_sequence="123", expected_digits="123"
    )

    assert memo.get_context("dtmf_validated") is True
    assert memo.get_context("dtmf_validation_gate_open") is True
    redis_mgr.add_event_async.assert_awaited_once()
    assert memo.persist_calls == 1


@pytest.mark.asyncio
async def test_complete_validation_failure_marks_invalid(context_with_memo):
    context, memo, redis_mgr = context_with_memo

    await DTMFValidationLifecycle._complete_aws_connect_validation(
        context, input_sequence="000", expected_digits="123"
    )

    assert memo.get_context("dtmf_validated") is False
    redis_mgr.add_event_async.assert_not_called()


def test_get_fresh_dtmf_validation_status():
    memo = DummyMemo()
    memo.set_context("dtmf_validated", True)

    result = DTMFValidationLifecycle.get_fresh_dtmf_validation_status(
        memo, "call-123"
    )

    assert result is True


def test_normalize_tone_mapping():
    assert DTMFValidationLifecycle._normalize_tone("five") == "5"
    assert DTMFValidationLifecycle._normalize_tone("*") == "*"
    assert DTMFValidationLifecycle._normalize_tone(None) is None


@pytest.mark.asyncio
async def test_update_dtmf_sequence_handles_append(context_with_memo):
    context, memo, redis_mgr = context_with_memo

    class DummyCallEventContext(CallEventContext):
        def __init__(self, memo_manager, redis_mgr):
            self.memo_manager = memo_manager
            self.redis_mgr = redis_mgr
            self.call_connection_id = "call-123"

    fake_context = DummyCallEventContext(memo, redis_mgr)

    DTMFValidationLifecycle._update_dtmf_sequence(fake_context, tone="1", sequence_id=0)
    DTMFValidationLifecycle._update_dtmf_sequence(fake_context, tone="2", sequence_id=1)

    assert memo.get_context("dtmf_sequence") == "12"

    await asyncio.sleep(0)  # allow background task to run
    redis_mgr.set_value_async.assert_called()
