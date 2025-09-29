"""Unit tests for ACS media lifecycle components aligned with the current implementation."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from apps.rtagent.backend.api.v1.handlers.acs_media_lifecycle import (
    MainEventLoop,
    RouteTurnThread,
    SpeechEvent,
    SpeechEventType,
    SpeechSDKThread,
    ThreadBridge,
)


class DummyRecognizer:
    """Lightweight recognizer test double that matches the current interface."""

    def __init__(self):
        self.started = False
        self.stopped = False
        self.callbacks = {}
        self.push_stream = None
        self.create_push_stream_called = False
        self.prepare_stream_called = False
        self.prepare_start_called = False
        self.write_bytes_calls = []

    def set_partial_result_callback(self, callback):
        self.callbacks["partial"] = callback

    def set_final_result_callback(self, callback):
        self.callbacks["final"] = callback

    def set_cancel_callback(self, callback):
        self.callbacks["cancel"] = callback

    def create_push_stream(self):
        self.create_push_stream_called = True
        self.push_stream = object()

    def prepare_stream(self):
        self.prepare_stream_called = True
        self.push_stream = object()

    def prepare_start(self):
        self.prepare_start_called = True
        self.push_stream = object()

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def write_bytes(self, data: bytes):
        self.write_bytes_calls.append(data)


@pytest.fixture
def dummy_recognizer():
    return DummyRecognizer()


@pytest.mark.asyncio
async def test_thread_bridge_queue_speech_result_put_nowait():
    bridge = ThreadBridge(call_connection_id="call-12345678")
    queue = asyncio.Queue()
    event = SpeechEvent(
        event_type=SpeechEventType.FINAL,
        text="hello",
        language="en-US",
    )

    bridge.queue_speech_result(queue, event)

    queued_event = await asyncio.wait_for(queue.get(), timeout=0.1)
    assert queued_event.text == "hello"
    assert queue.empty()


@pytest.mark.asyncio
async def test_thread_bridge_queue_speech_result_drops_when_full():
    bridge = ThreadBridge(call_connection_id="call-abcdef01")
    bridge.set_main_loop(asyncio.get_running_loop())

    queue = asyncio.Queue(maxsize=1)
    await queue.put("sentinel")

    event = SpeechEvent(
        event_type=SpeechEventType.PARTIAL,
        text="queued",
        language="en-US",
    )

    with patch(
        "apps.rtagent.backend.api.v1.handlers.acs_media_lifecycle.logger.warning"
    ) as warning_mock:
        bridge.queue_speech_result(queue, event)

    await queue.get()
    assert queue.empty()
    warning_mock.assert_called_once()


@pytest.mark.asyncio
async def test_speechsdkthread_preinitializes_push_stream(dummy_recognizer):
    bridge = ThreadBridge(call_connection_id="call-abcdef12")
    speech_queue = asyncio.Queue()
    barge_in_handler = AsyncMock()

    with patch("apps.rtagent.backend.api.v1.handlers.acs_media_lifecycle.logger"):
        thread = SpeechSDKThread(
            recognizer=dummy_recognizer,
            thread_bridge=bridge,
            barge_in_handler=barge_in_handler,
            speech_queue=speech_queue,
        )

    assert dummy_recognizer.create_push_stream_called or dummy_recognizer.push_stream
    assert set(dummy_recognizer.callbacks) == {"partial", "final", "cancel"}

    thread.stop()


@pytest.mark.asyncio
async def test_speechsdkthread_start_requires_thread_running(dummy_recognizer):
    bridge = ThreadBridge(call_connection_id="call-abcdef12")
    speech_queue = asyncio.Queue()

    with patch("apps.rtagent.backend.api.v1.handlers.acs_media_lifecycle.logger"):
        thread = SpeechSDKThread(
            recognizer=dummy_recognizer,
            thread_bridge=bridge,
            barge_in_handler=AsyncMock(),
            speech_queue=speech_queue,
        )

    thread.start_recognizer()

    assert not dummy_recognizer.started
    assert not thread.recognizer_started

    thread.stop()


@pytest.mark.asyncio
async def test_speechsdkthread_prepare_then_start(dummy_recognizer):
    bridge = ThreadBridge(call_connection_id="call-abcdef12")
    speech_queue = asyncio.Queue()

    with patch("apps.rtagent.backend.api.v1.handlers.acs_media_lifecycle.logger"):
        thread = SpeechSDKThread(
            recognizer=dummy_recognizer,
            thread_bridge=bridge,
            barge_in_handler=AsyncMock(),
            speech_queue=speech_queue,
        )

    thread.prepare_thread()
    await asyncio.sleep(0)
    thread.start_recognizer()

    assert dummy_recognizer.started
    assert thread.recognizer_started

    thread.stop()


@pytest.mark.asyncio
async def test_main_event_loop_handles_audio_metadata():
    mock_websocket = MagicMock()
    mock_websocket.send_text = AsyncMock()
    mock_websocket.state = MagicMock()

    main_loop = MainEventLoop(mock_websocket, "call-abcdef12", None)

    handler = MagicMock()
    handler.speech_sdk_thread.start_recognizer = Mock()
    handler.thread_bridge.queue_speech_result = Mock()
    handler.speech_queue = asyncio.Queue()
    handler.greeting_text = "Welcome!"

    metadata_message = json.dumps(
        {
            "kind": "AudioMetadata",
            "audioMetadata": {
                "encoding": "PCM",
                "sampleRate": 24000,
                "channels": 1,
            },
        }
    )

    await main_loop.handle_media_message(metadata_message, recognizer=None, acs_handler=handler)

    handler.speech_sdk_thread.start_recognizer.assert_called_once()
    handler.thread_bridge.queue_speech_result.assert_called_once()
    assert main_loop.greeting_played

    await main_loop.handle_media_message(metadata_message, recognizer=None, acs_handler=handler)
    handler.thread_bridge.queue_speech_result.assert_called_once()


@pytest.mark.asyncio
async def test_main_event_loop_process_audio_chunk_async():
    mock_websocket = MagicMock()
    mock_websocket.send_text = AsyncMock()
    mock_websocket.state = MagicMock()

    main_loop = MainEventLoop(mock_websocket, "call-abcdef12", None)

    recognizer = MagicMock()
    recognizer.push_stream = object()
    recognizer.write_bytes = MagicMock()

    encoded = base64.b64encode(b"audio-bytes").decode("ascii")

    await main_loop._process_audio_chunk_async(encoded, recognizer)

    recognizer.write_bytes.assert_called_once_with(b"audio-bytes")


@pytest.mark.asyncio
async def test_main_event_loop_handle_barge_in_cancels_playback():
    mock_websocket = MagicMock()
    mock_websocket.send_text = AsyncMock()
    mock_websocket.state = MagicMock()

    route_turn_thread = MagicMock()
    route_turn_thread.cancel_current_processing = AsyncMock()

    main_loop = MainEventLoop(mock_websocket, "call-abcdef12", route_turn_thread)
    main_loop.current_playback_task = asyncio.create_task(asyncio.sleep(1))

    await main_loop.handle_barge_in()

    route_turn_thread.cancel_current_processing.assert_awaited()
    mock_websocket.send_text.assert_called()
    assert main_loop.current_playback_task.cancelled()

    await asyncio.sleep(0.11)
    assert not main_loop.barge_in_active.is_set()


@pytest.mark.asyncio
async def test_route_turn_thread_cancel_current_processing_clears_queue():
    speech_queue = asyncio.Queue()
    await speech_queue.put(
        SpeechEvent(event_type=SpeechEventType.FINAL, text="hello", language="en-US")
    )

    orchestrator = AsyncMock()
    memory_manager = MagicMock()
    websocket = MagicMock()
    websocket.state = MagicMock()

    route_thread = RouteTurnThread(
        call_connection_id="call-abcdef12",
        speech_queue=speech_queue,
        orchestrator_func=orchestrator,
        memory_manager=memory_manager,
        websocket=websocket,
    )

    route_thread.current_response_task = asyncio.create_task(asyncio.sleep(1))

    await route_thread.cancel_current_processing()

    assert speech_queue.empty()
    assert route_thread.current_response_task.cancelled()

    # Cleanup to silence lingering tasks
    await asyncio.sleep(0)

