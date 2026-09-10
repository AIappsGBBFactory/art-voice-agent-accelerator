"""Native STT stop acknowledgement through production recognizer and runtime."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from apps.artagent.backend.voice.speech_cascade.handler import SpeechSDKThread, ThreadBridge
from src.speech.speech_recognizer import StreamingSpeechRecognizerFromBytes

from tests.test_cascade_runtime_ownership import app_state, make_handler


class PendingStop:
    """A native future that cannot complete until the test acknowledges stop."""

    def __init__(self, *, error=None):
        self.entered = threading.Event()
        self.acknowledged = threading.Event()
        self.error = error
        self.get_calls = 0

    def get(self):
        self.get_calls += 1
        self.entered.set()
        assert self.acknowledged.wait(3), "test did not complete the native future"
        if self.error is not None:
            raise self.error


def production_recognizer(future):
    """Replace only SDK construction and native future, not stop implementation."""
    with patch.object(
        StreamingSpeechRecognizerFromBytes, "_create_speech_config", return_value=object()
    ):
        recognizer = StreamingSpeechRecognizerFromBytes(
            key="test", region="test", enable_tracing=False
        )
    recognizer.push_stream = object()
    recognizer.speech_recognizer = SimpleNamespace(
        stop_continuous_recognition_async=Mock(return_value=future)
    )
    return recognizer


@pytest.mark.asyncio
async def test_production_stop_waits_for_native_get_before_reporting_success():
    future = PendingStop()
    recognizer = production_recognizer(future)
    span = Mock()
    recognizer._session_span = span
    stopping = asyncio.create_task(asyncio.to_thread(recognizer.stop))
    try:
        assert await asyncio.to_thread(future.entered.wait, 1)
        assert not stopping.done()
        span.end.assert_not_called()
        future.acknowledged.set()
        await asyncio.wait_for(stopping, 1)
        assert future.get_calls == 1
        span.end.assert_called_once()
    finally:
        future.acknowledged.set()
        await asyncio.gather(stopping, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_wrapper_owned_stop_retains_pending_native_work_after_timeout(failure):
    future = PendingStop(error=RuntimeError("native stop failed") if failure else None)
    recognizer = production_recognizer(future)
    wrapper = SpeechSDKThread(
        connection_id="stop-test",
        recognizer=recognizer,
        thread_bridge=ThreadBridge(),
        speech_queue=asyncio.Queue(),
        barge_in_handler=None,
    )
    try:
        with pytest.raises(TimeoutError):
            await wrapper.stop_async(timeout_sec=0.03)
        assert future.entered.is_set()
        assert not wrapper._stop_complete
        assert not wrapper._stop_task.done()
        assert not wrapper._stop_task.cancelled()
        future.acknowledged.set()
        if failure:
            with pytest.raises(RuntimeError, match="native stop failed"):
                await wrapper.stop_async(timeout_sec=1)
            with pytest.raises(RuntimeError, match="native stop failed"):
                await asyncio.to_thread(wrapper.stop)
        else:
            await wrapper.stop_async(timeout_sec=1)
            await asyncio.to_thread(wrapper.stop)
            assert wrapper._stop_complete
        assert future.get_calls == 1
        recognizer.speech_recognizer.stop_continuous_recognition_async.assert_called_once()
    finally:
        future.acknowledged.set()
        await asyncio.gather(wrapper._stop_task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_handler_withholds_lease_until_production_stop_acknowledges(failure):
    future = PendingStop(error=RuntimeError("native stop failed") if failure else None)
    recognizer = production_recognizer(future)
    app = app_state(stt=recognizer)
    handler = await make_handler(app)
    stopping = asyncio.create_task(handler.stop())
    try:
        assert await asyncio.to_thread(future.entered.wait, 1)
        assert app.stt_pool.released == 0
        assert not stopping.done()
        future.acknowledged.set()
        if failure:
            with pytest.raises(ExceptionGroup, match="could not be quiesced"):
                await asyncio.wait_for(stopping, 1)
            with pytest.raises(ExceptionGroup, match="could not be quiesced"):
                await handler.stop()
            assert app.stt_pool.released == 0
        else:
            await asyncio.wait_for(stopping, 1)
            await handler.stop()
            assert app.stt_pool.released == 1
        assert future.get_calls == 1
    finally:
        future.acknowledged.set()
        await asyncio.gather(stopping, return_exceptions=True)
