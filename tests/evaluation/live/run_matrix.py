"""Run reproducible live voice evaluations across orchestration modes.

The in-process evaluation runner remains the functional/tool assertion suite.
This runner is the transport-level companion: it drives the deployed or local
browser WebSocket with real PCM input, captures first response/first audio and
turn-wall latency, and writes one JSON artifact per mode and repetition.

Typical local flow::

    make eval-live-synth
    make eval-live EVAL_LIVE_URL=http://localhost:8010

The audio cache is generated before the measured run so Azure Speech synthesis
time is never included in the voice latency numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from tests.evaluation.live.ws_voice_driver import (
    DEFAULT_CACHE_DIR,
    DEFAULT_SESSION_PREFIX,
    _latency_stats,
    pregenerate_audio,
    run_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCENARIO = (
    PROJECT_ROOT / "tests/evaluation/scenarios/session_based/latency_first_audio.yaml"
)


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _mode_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [turn for result in results for turn in result.get("turns", [])]
    first_audio = [
        turn["first_audio_ms"]
        for turn in turns
        if turn.get("first_audio_ms") is not None
    ]
    first_response = [
        turn["first_response_ms"]
        for turn in turns
        if turn.get("first_response_ms") is not None
    ]
    e2e = [turn["turn_wall_ms"] for turn in turns if turn.get("turn_wall_ms") is not None]
    return {
        "runs": len(results),
        "passed_runs": sum(1 for result in results if result.get("pass_fail") is True),
        "failed_runs": sum(1 for result in results if result.get("pass_fail") is False),
        "sessions": [result.get("session_id") for result in results],
        "latency_metrics": {
            **_latency_stats("e2e", e2e),
            **_latency_stats("first_audio", first_audio),
            **_latency_stats("first_response", first_response),
        },
    }


async def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = [path.resolve() for path in (args.scenario or [DEFAULT_SCENARIO])]
    modes = _parse_csv(args.modes)
    output_dir = args.out_dir.resolve()
    cache_dir = args.cache_dir.resolve()

    if args.synth_only:
        for scenario in scenarios:
            paths = await asyncio.to_thread(pregenerate_audio, scenario, cache_dir)
            print(f"{scenario.name}: cached {len(paths)} input turn(s) in {cache_dir}")
        return {"synth_only": True, "cache_dir": str(cache_dir)}

    if not args.url:
        raise ValueError("--url or EVAL_LIVE_URL/EVAL_BACKEND_URL is required")
    if not modes:
        raise ValueError("--modes must contain at least one mode")
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1")

    all_results: list[dict[str, Any]] = []
    by_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in modes}

    for scenario in scenarios:
        scenario_name = scenario.stem
        for mode in modes:
            for repetition in range(1, args.repeat + 1):
                result = await run_scenario(
                    scenario,
                    args.url,
                    ws_path=args.ws_path,
                    streaming_mode=mode,
                    session_prefix=f"{args.session_prefix}{mode}_",
                    cache_dir=cache_dir,
                    turn_timeout=args.turn_timeout,
                    quiet_gap=args.quiet_gap,
                    first_byte_timeout=args.first_byte_timeout,
                    inter_turn_pause=args.inter_turn_pause,
                    bootstrap_appconfig=not args.no_appconfig,
                    require_audio_cache=args.require_audio_cache,
                    require_audio=not args.allow_missing_audio,
                )
                payload = result.to_dict()
                payload["scenario_path"] = str(scenario)
                payload["repetition"] = repetition
                all_results.append(payload)
                by_mode[mode].append(payload)
                artifact = output_dir / scenario_name / mode / f"run_{repetition:03d}.json"
                _write_json(artifact, payload)
                print(
                    f"{scenario_name} mode={mode} run={repetition} "
                    f"pass={result.pass_fail} "
                    f"first_audio_p95={payload['latency_metrics'].get('first_audio_p95_ms')}ms"
                )

    summary = {
        "url": args.url,
        "ws_path": args.ws_path,
        "modes": modes,
        "repeat": args.repeat,
        "scenarios": [str(path) for path in scenarios],
        "results": len(all_results),
        "pass_fail": all(result.get("pass_fail") is True for result in all_results),
        "by_mode": {mode: _mode_summary(results) for mode, results in by_mode.items()},
    }
    _write_json(output_dir / "matrix_summary.json", summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("EVAL_LIVE_URL")
        or os.getenv("EVAL_BACKEND_URL")
        or os.getenv("BACKEND_CONTAINER_APP_URL"),
        help="Local or deployed backend base URL.",
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        action="append",
        default=None,
        help="Session-based scenario YAML; repeat for multiple scenarios.",
    )
    parser.add_argument(
        "--modes",
        default=os.getenv("EVAL_LIVE_MODES", "realtime,voice_live"),
        help="Comma-separated browser streaming modes.",
    )
    parser.add_argument("--repeat", type=int, default=int(os.getenv("EVAL_LIVE_REPEAT", "1")))
    parser.add_argument("--ws-path", default="/api/v1/browser/conversation")
    parser.add_argument("--session-prefix", default=DEFAULT_SESSION_PREFIX)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--out-dir", type=Path, default=Path("runs/live-evals"))
    parser.add_argument("--turn-timeout", type=float, default=20.0)
    parser.add_argument("--quiet-gap", type=float, default=2.0)
    parser.add_argument("--first-byte-timeout", type=float, default=12.0)
    parser.add_argument("--inter-turn-pause", type=float, default=1.0)
    parser.add_argument("--synth-only", action="store_true")
    parser.add_argument("--require-audio-cache", action="store_true")
    parser.add_argument("--allow-missing-audio", action="store_true")
    parser.add_argument("--no-appconfig", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        summary = asyncio.run(run_matrix(args))
    except Exception as exc:  # noqa: BLE001 - CLI reports a useful failure
        print(f"live evaluation failed: {exc}", file=sys.stderr)
        return 1

    if args.synth_only:
        return 0
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass_fail"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
