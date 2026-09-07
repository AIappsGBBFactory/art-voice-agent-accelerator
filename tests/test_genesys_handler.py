from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from apps.artagent.backend.registries.agentstore.base import ModelConfig
from apps.artagent.backend.voice.genesys.handler import (
    GenesysVoiceLiveHandler,
    _OutboundAudioFrame,
)
from azure.ai.voicelive.models import ServerEventType
from fastapi.websockets import WebSocketState


class _FakeWebSocket:
    def __init__(self) -> None:
        self.application_state = WebSocketState.CONNECTED
        self.client_state = WebSocketState.CONNECTED
        self.state = SimpleNamespace()
        self.app = SimpleNamespace(state=SimpleNamespace(redis=None))
        self.sent_text: list[str] = []
        self.sent_bytes: list[bytes] = []

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)


def _make_handler() -> tuple[GenesysVoiceLiveHandler, _FakeWebSocket]:
    ws = _FakeWebSocket()
    handler = GenesysVoiceLiveHandler(websocket=ws, session_id="genesys-session")
    handler._running = True
    handler._AUDIO_CHUNK_SIZE = 4
    handler._AUDIO_PACE_MS = 0
    handler._MAX_OUTBOUND_AUDIO_BYTES = 64
    return handler, ws


def _drain_queue(handler: GenesysVoiceLiveHandler) -> list[object]:
    items: list[object] = []
    while True:
        try:
            items.append(handler._outbound_queue.get_nowait())
        except asyncio.QueueEmpty:
            return items


class _FakeVoiceLiveConnection:
    def __init__(self) -> None:
        self.input_audio_buffer = SimpleNamespace(append=AsyncMock())

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _FakeConnectionManager:
    def __init__(self, connection: _FakeVoiceLiveConnection) -> None:
        self.connection = connection
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True


class _FakeLiveOrchestrator:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.start = AsyncMock()
        self.cleanup = Mock()
        self.handle_event = AsyncMock()


@pytest.mark.asyncio
async def test_barge_in_invalidates_queued_audio_and_drops_late_delta() -> None:
    handler, _ = _make_handler()

    await handler._enqueue_binary(b"abcdefgh", response_id="resp-old")
    await handler._flush_audio_buffer(response_id="resp-old")
    handler._active_response_ids.add("resp-old")
    handler._current_response_id = "resp-old"

    await handler._handle_voicelive_event(
        SimpleNamespace(type=ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED),
        ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED,
    )

    queued = _drain_queue(handler)
    assert all(not isinstance(item, _OutboundAudioFrame) for item in queued)
    assert [item["parameters"]["entities"][0]["type"] for item in queued if isinstance(item, dict)] == [
        "barge_in"
    ]
    assert "resp-old" in handler._cancelled_response_ids

    await handler._handle_voicelive_event(
        SimpleNamespace(
            type=ServerEventType.RESPONSE_AUDIO_DELTA,
            response_id="resp-old",
            delta=b"\x00\x00\x01\x00\x02\x00",
        ),
        ServerEventType.RESPONSE_AUDIO_DELTA,
    )

    assert handler._pending_audio_bytes == 0
    assert handler._audio_accum == bytearray()

    await handler._handle_voicelive_event(
        SimpleNamespace(
            type=ServerEventType.RESPONSE_AUDIO_DELTA,
            response_id="resp-new",
            delta=b"\x00\x00\x01\x00\x02\x00",
        ),
        ServerEventType.RESPONSE_AUDIO_DELTA,
    )

    assert handler._audio_accum_response_id == "resp-new"
    assert handler._pending_audio_bytes > 0


@pytest.mark.asyncio
async def test_unidentified_audio_delta_is_dropped_instead_of_reusing_current_response() -> None:
    handler, _ = _make_handler()
    handler._current_response_id = "resp-known"

    await handler._handle_voicelive_event(
        SimpleNamespace(
            type=ServerEventType.RESPONSE_AUDIO_DELTA,
            delta=b"\x00\x00\x01\x00\x02\x00",
        ),
        ServerEventType.RESPONSE_AUDIO_DELTA,
    )

    assert handler._pending_audio_bytes == 0
    assert handler._audio_accum == bytearray()
    assert handler._audio_accum_response_id is None


@pytest.mark.asyncio
async def test_control_messages_keep_monotonic_seq_after_audio_invalidation() -> None:
    handler, _ = _make_handler()

    await handler._enqueue_message(handler._protocol.create_opened({"format": "PCMU", "rate": 8000}))
    await handler._enqueue_binary(b"abcdefgh", response_id="resp-old")
    await handler._flush_audio_buffer(response_id="resp-old")
    handler._active_response_ids.add("resp-old")
    handler._current_response_id = "resp-old"

    await handler._handle_voicelive_event(
        SimpleNamespace(type=ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED),
        ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED,
    )
    await handler._handle_close()

    queued = _drain_queue(handler)
    messages = [item for item in queued if isinstance(item, dict)]

    assert all(not isinstance(item, _OutboundAudioFrame) for item in queued)
    assert [message["type"] for message in messages] == ["opened", "event", "closed"]
    assert [message["seq"] for message in messages] == [1, 2, 3]


@pytest.mark.asyncio
async def test_stop_cleans_up_pacer_writer_and_partial_runtime() -> None:
    handler, ws = _make_handler()
    await handler.start()
    handler._connection_cm = _FakeConnectionManager(_FakeVoiceLiveConnection())
    handler._connection = handler._connection_cm.connection
    handler._orchestrator = _FakeLiveOrchestrator()
    handler._event_task = asyncio.create_task(asyncio.sleep(60))

    await handler._enqueue_binary(b"abcdefgh", response_id="resp-stop")

    await handler.stop()

    assert handler._pacer_task is None
    assert handler._writer_task is None
    assert handler._event_task is None
    assert handler._connection is None
    assert handler._connection_cm is None
    assert handler._orchestrator is None
    assert handler._pending_audio_bytes == 0
    assert ws.sent_bytes == []


@pytest.mark.asyncio
async def test_connect_passes_byom_query_and_shared_credential_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.voice.genesys import handler as genesys_handler
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler

    handler, _ = _make_handler()
    captured: dict[str, object] = {}
    fake_connection = _FakeVoiceLiveConnection()
    fake_cm = _FakeConnectionManager(fake_connection)
    fake_orchestrator = _FakeLiveOrchestrator()
    credential = object()

    class _Agent:
        def get_model_for_mode(self, mode: str) -> ModelConfig:
            assert mode == "voicelive"
            return ModelConfig(deployment_id="o3-mini")

        def get_byom_query(self) -> dict[str, str]:
            return {
                "profile": "byom-azure-openai-chat-completion",
                "foundry-resource-override": "resource-1",
            }

    monkeypatch.setattr(
        genesys_handler,
        "get_settings",
        lambda: SimpleNamespace(
            ws_max_msg_size=1024,
            ws_heartbeat=30,
            ws_timeout=10,
            azure_voicelive_endpoint="wss://voice.example",
            azure_voicelive_model="gpt-realtime",
            has_api_key_auth=False,
        ),
    )
    monkeypatch.setattr(
        handler,
        "_resolve_agents",
        AsyncMock(
            return_value=(
                {"StartAgent": _Agent()},
                SimpleNamespace(),
                "StartAgent",
                {},
            )
        ),
    )
    monkeypatch.setattr(
        voicelive_handler.VoiceLiveSDKHandler,
        "_build_credential",
        AsyncMock(return_value=credential),
    )

    def _fake_connect(**kwargs):
        captured.update(kwargs)
        return fake_cm

    monkeypatch.setattr(genesys_handler, "connect", _fake_connect)
    monkeypatch.setattr(genesys_handler, "LiveOrchestrator", lambda *args, **kwargs: fake_orchestrator)
    monkeypatch.setattr(genesys_handler, "register_voicelive_orchestrator", Mock())
    monkeypatch.setattr(genesys_handler, "unregister_voicelive_orchestrator", Mock())

    await handler._connect_voicelive()
    await handler.stop()

    assert captured["credential"] is credential
    assert captured["model"] == "o3-mini"
    assert captured["query"] == {
        "profile": "byom-azure-openai-chat-completion",
        "foundry-resource-override": "resource-1",
    }


@pytest.mark.asyncio
async def test_partial_connect_failure_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.artagent.backend.voice.genesys import handler as genesys_handler
    from apps.artagent.backend.voice.voicelive import handler as voicelive_handler

    handler, _ = _make_handler()
    fake_connection = _FakeVoiceLiveConnection()
    fake_cm = _FakeConnectionManager(fake_connection)

    class _FailingOrchestrator(_FakeLiveOrchestrator):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.start = AsyncMock(side_effect=RuntimeError("start failed"))

    class _Agent:
        def get_model_for_mode(self, _mode: str) -> ModelConfig:
            return ModelConfig(deployment_id="gpt-realtime")

        def get_byom_query(self) -> None:
            return None

    monkeypatch.setattr(
        genesys_handler,
        "get_settings",
        lambda: SimpleNamespace(
            ws_max_msg_size=1024,
            ws_heartbeat=30,
            ws_timeout=10,
            azure_voicelive_endpoint="wss://voice.example",
            azure_voicelive_model="gpt-realtime",
            has_api_key_auth=False,
        ),
    )
    monkeypatch.setattr(
        handler,
        "_resolve_agents",
        AsyncMock(return_value=({"StartAgent": _Agent()}, SimpleNamespace(), "StartAgent", {})),
    )
    monkeypatch.setattr(
        voicelive_handler.VoiceLiveSDKHandler,
        "_build_credential",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(genesys_handler, "connect", lambda **kwargs: fake_cm)
    monkeypatch.setattr(genesys_handler, "LiveOrchestrator", _FailingOrchestrator)
    monkeypatch.setattr(genesys_handler, "register_voicelive_orchestrator", Mock())
    unregister = Mock()
    monkeypatch.setattr(genesys_handler, "unregister_voicelive_orchestrator", unregister)

    with pytest.raises(RuntimeError, match="start failed"):
        await handler._connect_voicelive()

    assert fake_cm.exited is True
    assert handler._connection is None
    assert handler._connection_cm is None
    unregister.assert_called_with("genesys-session")
