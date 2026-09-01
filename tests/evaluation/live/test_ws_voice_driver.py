from __future__ import annotations

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
