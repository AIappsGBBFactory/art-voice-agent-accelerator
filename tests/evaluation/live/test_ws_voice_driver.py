from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from tests.evaluation.live import ws_voice_driver as driver
from tests.evaluation.live.run_matrix import _mode_summary
from tests.evaluation.live.ws_voice_driver import (
    FRAME_BYTES,
    ScenarioResult,
    TurnResult,
    _evaluate_live_result,
    _is_audio_kind,
    _is_response_kind,
    _new_traceparent,
    _silence_frame,
)


def test_silence_frame_is_deterministic_pcm_frame() -> None:
    frame = _silence_frame()

    assert len(frame) == FRAME_BYTES
    assert frame == (_silence_frame())
    assert frame[:4] == b"\x0c\x00\xf4\xff"


def test_traceparent_has_w3c_shape() -> None:
    traceparent = _new_traceparent()

    version, trace_id, parent_id, flags = traceparent.split("-")
    assert version == "00"
    assert len(trace_id) == 32
    assert len(parent_id) == 16
    assert flags == "01"


def test_lowercase_audio_data_is_counted_as_first_audio() -> None:
    assert _is_audio_kind("audio_data")
    assert _is_audio_kind("AudioData")
    assert _is_audio_kind("audio-data")
    assert _is_response_kind("assistant_streaming")
    assert not _is_response_kind("event")


def test_live_result_reports_latency_metrics_and_passes_client_gates() -> None:
    result = ScenarioResult(
        scenario_name="latency_first_audio",
        session_id="eval_live_realtime_latency_first_audio_1",
        ws_url="ws://localhost:8010/api/v1/browser/conversation",
        streaming_mode="realtime",
        ok=True,
        turns=[
            TurnResult(
                turn_id="turn_1",
                user_input="hello",
                first_response_ms=500.0,
                first_audio_ms=650.0,
                turn_wall_ms=1800.0,
            )
        ],
    )

    _evaluate_live_result(
        result,
        {
            "turns": [
                {
                    "turn_id": "turn_1",
                    "expectations": {
                        "max_latency_ms": 2000,
                        "max_ttft_ms": 1000,
                        "max_tts_first_chunk_ms": 1000,
                    },
                }
            ],
            "thresholds": {"max_latency_p95_ms": 2000},
        },
        require_audio=True,
    )

    payload = result.to_dict()
    assert result.pass_fail is True
    assert payload["latency_metrics"]["e2e_p95_ms"] == 1800.0
    assert payload["latency_metrics"]["first_audio_p95_ms"] == 650.0
    assert result.unmeasured_expectations == [
        "max_ttft_ms (server trace)",
        "max_tts_first_chunk_ms (server trace)",
    ]


def test_live_result_fails_when_audio_is_missing() -> None:
    result = ScenarioResult(
        scenario_name="latency_first_audio",
        session_id="eval_live_voice_live_latency_first_audio_1",
        ws_url="ws://localhost:8010/api/v1/browser/conversation",
        streaming_mode="voice_live",
        ok=True,
        turns=[
            TurnResult(
                turn_id="turn_1",
                user_input="hello",
                first_response_ms=500.0,
                turn_wall_ms=1200.0,
            )
        ],
    )

    _evaluate_live_result(
        result,
        {"turns": [{"turn_id": "turn_1", "expectations": {}}]},
        require_audio=True,
    )

    assert result.pass_fail is False
    assert result.ok is False
    assert result.checks[0]["check"] == "first_audio_ms"


def test_mode_summary_aggregates_repeated_runs() -> None:
    summary = _mode_summary(
        [
            {
                "session_id": "eval_live_realtime_1",
                "pass_fail": True,
                "turns": [
                    {
                        "first_audio_ms": 400.0,
                        "first_response_ms": 300.0,
                        "turn_wall_ms": 900.0,
                    }
                ],
            },
            {
                "session_id": "eval_live_realtime_2",
                "pass_fail": False,
                "turns": [
                    {
                        "first_audio_ms": 600.0,
                        "first_response_ms": 500.0,
                        "turn_wall_ms": 1100.0,
                    }
                ],
            },
        ]
    )

    assert summary["runs"] == 2
    assert summary["passed_runs"] == 1
    assert summary["failed_runs"] == 1
    assert summary["latency_metrics"]["first_audio_p95_ms"] == 590.0


class ScriptedSocket:
    def __init__(self, clock, messages, *, wait_for_audio=True):
        self.clock = clock
        self.messages = list(messages)
        self.sent_count = 0
        self.audio_sent = asyncio.Event()
        if not wait_for_audio:
            self.audio_sent.set()

    async def send(self, data):
        self.sent_count += 1
        if self.sent_count == 61:
            self.audio_sent.set()

    async def recv(self):
        await self.audio_sent.wait()
        if not self.messages:
            self.clock.now += 0.2
            await asyncio.sleep(0)
            raise TimeoutError
        timestamp, message = self.messages.pop(0)
        self.clock.now = timestamp
        if isinstance(message, BaseException):
            raise message
        return json.dumps(message) if isinstance(message, dict) else message


@pytest.fixture
def wire_clock(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(driver, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(driver, "FRAME_MS", 0)
    return clock


@pytest.mark.asyncio
async def test_control_traffic_does_not_complete_a_turn_before_its_response(wire_clock):
    ws = ScriptedSocket(
        wire_clock,
        [
            (0.05, {"type": "event", "payload": {"type": "user", "content": "hello"}}),
            (0.25, TimeoutError()),
            (0.3, b"audio"),
            (
                0.4,
                {
                    "type": "event",
                    "payload": {"type": "assistant", "content": "answer"},
                },
            ),
        ],
    )
    result = await driver._run_turn(
        ws,
        "turn",
        "hello",
        b"x" * FRAME_BYTES,
        turn_timeout=2,
        quiet_gap=0.1,
        first_byte_timeout=1,
    )

    assert result.error is None
    assert result.first_audio_ms == 300
    assert result.response_text == "answer"
    assert result.turn_wall_ms == 400  # Observer quiet time is not response latency.


@pytest.mark.asyncio
@pytest.mark.parametrize("content_mode", ["snapshot", "delta"])
async def test_current_transcript_envelopes_do_not_duplicate_text(wire_clock, content_mode):
    def assistant(kind, content, mode):
        return {
            "type": kind,
            "payload": {
                "type": "assistant",
                "content": content,
                "content_mode": mode,
                "turn_id": "server-turn",
                "response_id": "server-response",
            },
        }

    ws = ScriptedSocket(
        wire_clock,
        [
            (0.05, b"audio"),
            (0.1, assistant("assistant_streaming", "Hello ", content_mode)),
            (
                0.15,
                assistant(
                    "assistant_streaming",
                    "Hello world" if content_mode == "snapshot" else "world",
                    content_mode,
                ),
            ),
            (0.2, assistant("event", "Hello world", "final_turn")),
        ],
    )
    result = await driver._run_turn(
        ws,
        "turn",
        "hello",
        b"x" * FRAME_BYTES,
        turn_timeout=2,
        quiet_gap=0.1,
        first_byte_timeout=1,
    )
    assert result.response_text == "Hello world"
    assert result.turn_wall_ms == 200


@pytest.mark.asyncio
async def test_mid_turn_close_is_an_error_not_a_successful_partial_turn(wire_clock):
    ws = ScriptedSocket(
        wire_clock,
        [(0.1, b"audio"), (0.15, ConnectionClosedError(Close(1012, "restart"), None))],
    )
    result = await driver._run_turn(
        ws,
        "turn",
        "hello",
        b"x" * FRAME_BYTES,
        turn_timeout=2,
        quiet_gap=0.1,
        first_byte_timeout=1,
    )
    assert result.error == "connection_closed: 1012"
    assert result.turn_wall_ms is None


@pytest.mark.asyncio
async def test_open_transcript_survives_a_gap_before_final_output(wire_clock):
    ws = ScriptedSocket(
        wire_clock,
        [
            (
                0.05,
                {
                    "type": "assistant_streaming",
                    "payload": {
                        "content": "Working",
                        "content_mode": "snapshot",
                        "turn_id": "server-turn",
                    },
                },
            ),
            (0.25, TimeoutError()),
            (
                0.35,
                {
                    "type": "event",
                    "payload": {
                        "type": "assistant",
                        "content": "Complete answer",
                        "content_mode": "final_turn",
                        "turn_id": "server-turn",
                    },
                },
            ),
            (0.4, b"audio"),
        ],
    )
    result = await driver._run_turn(
        ws,
        "turn",
        "hello",
        b"x" * FRAME_BYTES,
        turn_timeout=2,
        quiet_gap=0.1,
        first_byte_timeout=1,
    )
    assert result.response_text == "Complete answer"
    assert result.first_audio_ms == 400
    assert result.turn_wall_ms == 400


@pytest.mark.asyncio
async def test_silence_padding_does_not_block_audio_observation(monkeypatch):
    monkeypatch.setattr(driver, "FRAME_MS", 0)
    audio_received = asyncio.Event()
    incoming = asyncio.Queue()
    sent = []

    async def send(data):
        sent.append(data)
        if len(sent) == 2:
            await incoming.put(b"audio")
            await audio_received.wait()

    async def recv():
        message = await incoming.get()
        audio_received.set()
        return message

    ws = SimpleNamespace(send=send, recv=recv)
    result = await asyncio.wait_for(
        driver._run_turn(
            ws,
            "turn",
            "hello",
            b"x" * FRAME_BYTES,
            turn_timeout=1,
            quiet_gap=0.01,
            first_byte_timeout=0.5,
        ),
        timeout=1,
    )
    assert audio_received.is_set()
    assert len(sent) == 61
    assert result.first_audio_ms is not None
    assert result.error is None


@pytest.mark.asyncio
async def test_cancelling_observation_joins_the_audio_sender(monkeypatch):
    monkeypatch.setattr(driver, "FRAME_MS", 0)
    sending = asyncio.Event()
    stopped = asyncio.Event()
    sender_tasks = []

    async def send(data):
        sender_tasks.append(asyncio.current_task())
        sending.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def recv():
        await asyncio.Event().wait()

    task = asyncio.create_task(
        driver._run_turn(
            SimpleNamespace(send=send, recv=recv),
            "turn",
            "hello",
            b"x" * FRAME_BYTES,
            turn_timeout=1,
            quiet_gap=0.01,
            first_byte_timeout=0.5,
        )
    )
    await asyncio.wait_for(sending.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
    assert all(sender.done() for sender in sender_tasks)


@pytest.mark.asyncio
async def test_startup_waits_for_readiness_and_greeting_quiescence(wire_clock):
    ws = ScriptedSocket(
        wire_clock,
        [
            (0.05, TimeoutError()),
            (
                0.2,
                {"type": "event", "payload": {"event_type": "voice_live_connected"}},
            ),
            (0.3, b"greeting audio"),
            (0.4, {"type": "assistant", "payload": {"content": "Welcome"}}),
        ],
        wait_for_audio=False,
    )

    await driver._drain_startup_messages(ws)

    assert not ws.messages


@pytest.mark.asyncio
async def test_startup_without_readiness_times_out(wire_clock):
    ws = ScriptedSocket(wire_clock, [], wait_for_audio=False)
    with pytest.raises(TimeoutError, match="readiness/greeting"):
        await driver._drain_startup_messages(ws)


@pytest.mark.asyncio
async def test_startup_socket_failure_propagates(wire_clock):
    ws = ScriptedSocket(
        wire_clock,
        [(0.1, ConnectionClosedError(Close(1012, "restart"), None))],
        wait_for_audio=False,
    )
    with pytest.raises(ConnectionClosedError):
        await driver._drain_startup_messages(ws)


@pytest.mark.asyncio
async def test_audio_sender_failure_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(driver, "FRAME_MS", 0)
    sent = asyncio.Event()
    sender_tasks = []

    async def send(data):
        sender_tasks.append(asyncio.current_task())
        sent.set()
        raise OSError("send failed")

    async def recv():
        await sent.wait()
        raise TimeoutError

    with pytest.raises(OSError, match="send failed"):
        await driver._run_turn(
            SimpleNamespace(send=send, recv=recv),
            "turn",
            "hello",
            b"x" * FRAME_BYTES,
            turn_timeout=1,
            quiet_gap=0.01,
            first_byte_timeout=0.5,
        )
    assert all(sender.done() for sender in sender_tasks)


@pytest.mark.asyncio
async def test_failed_turn_does_not_send_a_following_turn(tmp_path, monkeypatch):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        "scenario_name: stop_on_failure\n"
        "turns:\n"
        "  - {turn_id: first, user_input: hello}\n"
        "  - {turn_id: second, user_input: do not send}\n"
    )
    synth = SimpleNamespace(
        _cache_path=lambda text: tmp_path / "input.pcm",
        pcm_for=lambda text: b"x" * FRAME_BYTES,
    )
    monkeypatch.setattr(driver, "TurnAudioSynth", lambda path: synth)
    connection = AsyncMock()
    connection.__aenter__.return_value = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(driver.websockets, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(driver, "_drain_startup_messages", AsyncMock())
    run_turn = AsyncMock(
        return_value=TurnResult(
            turn_id="first", user_input="hello", error="no_response_before_first_byte_timeout"
        )
    )
    monkeypatch.setattr(driver, "_run_turn", run_turn)

    result = await driver.run_scenario(path, "https://backend.example", bootstrap_appconfig=False)

    run_turn.assert_awaited_once()
    assert len(result.turns) == 1
    assert result.error == "turn_failed: first: no_response_before_first_byte_timeout"
    assert result.pass_fail is False
