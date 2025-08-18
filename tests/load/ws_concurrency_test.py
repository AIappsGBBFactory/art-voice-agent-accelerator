"""Concurrent WebSocket session isolation test.

Purpose:
  Spawn N concurrent /realtime sessions against the running backend, collect
  per-session timings and messages, and assert there is no cross-session
  message contamination (beyond the expected greeting text).

Usage (examples):
  python -m tests.load.ws_concurrency_test --concurrency 25 --iterations 2 \
      --ws-url ws://localhost:8010/realtime

  # With light audio byte streaming (silence) to exercise STT write path
  python -m tests.load.ws_concurrency_test -c 10 --send-audio --audio-seconds 3

  # With CSV export, Prometheus metrics, and per-session logs
  python -m tests.load.ws_concurrency_test -c 20 --iterations 3 \
      --csv out/ws_realtime.csv --prom out/ws_metrics.prom --log-dir out/session_logs

  # For testing when auth is enabled (will show 403 errors)
  python -m tests.load.ws_concurrency_test -c 5 --skip-auth-errors

  # Produce an extended JSON summary file and later replay previously saved logs
    python -m tests.load.ws_concurrency_test -c 15 --summary-json out/summary.json --log-dir out/session_logs
    # Later (no live traffic) recompute analytics from logs only:
    python -m tests.load.ws_concurrency_test --replay-log-dir out/session_logs --summary-json out/replayed_summary.json

Design notes:
  The existing /realtime route currently expects binary audio frames for STT
  and does not consume text frames as user input. For isolation validation we
  only need to:
    1. Ensure each session receives its own greeting promptly.
    2. Ensure no unexpected messages originating from other sessions appear.
    3. Stress per-connection recognizer allocation & teardown.

  Optional silent PCM frames (16kHz mono 16-bit) are sent when --send-audio is
  enabled to exercise the STT ingest path without requiring real speech.

Outputs:
  Prints a JSON summary with aggregate latency stats and any contamination
  findings. Exits non‑zero if contamination detected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import pathlib
import csv
import glob
import hashlib
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any

import websockets
import contextlib

DEFAULT_GREETING_PREFIX = "Hi there"  # substring match to avoid coupling


@dataclass
class SessionResult:
    session_id: str
    connect_latency_ms: float | None = None
    greeting_latency_ms: float | None = None
    messages: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    alias: str | None = None  # random per-session alias label

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "connect_latency_ms": self.connect_latency_ms,
            "greeting_latency_ms": self.greeting_latency_ms,
            "message_count": len(self.messages),
            "errors": self.errors,
            "alias": self.alias,
        }


async def generate_silence_chunk(
    duration_sec: float, sample_rate: int = 16000
) -> bytes:
    """Return PCM16 little-endian silence covering duration_sec (mono)."""
    frame_count = int(sample_rate * duration_sec)
    # 2 bytes per sample (16-bit); silence == 0
    return b"\x00\x00" * frame_count


ALIASES = [
    "Orion",
    "Lyra",
    "Vega",
    "Nova",
    "Atlas",
    "Zephyr",
    "Cypher",
    "Echo",
    "Quill",
    "Rune",
    "Astra",
    "Nimbus",
    "Sol",
    "Lumen",
    "Kairo",
    "Nyx",
    "Vale",
    "Coda",
    "Pixel",
    "Tempo",
]


def random_alias(idx: int) -> str:
    # Deterministic-ish per run so same idx yields same alias mapping if rerun with same process seed
    return ALIASES[idx % len(ALIASES)] + f"_{idx}"


async def run_session(idx: int, args) -> SessionResult:
    session_id = f"sess-{idx}-{random.randint(1000,9999)}"
    result = SessionResult(session_id=session_id)
    result.alias = random_alias(idx)
    ws_url = args.ws_url
    headers = {"x-test-session-id": session_id}
    # Optional bearer token support for auth-enabled endpoints
    token = getattr(args, "bearer_token", None) or os.environ.get("TEST_BEARER_TOKEN")
    if token:
        headers["Authorization"] = (
            token if token.lower().startswith("bearer ") else f"Bearer {token}"
        )
    start_connect = time.perf_counter()
    try:
        # Use additional_headers instead of extra_headers for compatibility
        async with websockets.connect(
            ws_url, additional_headers=headers, max_size=2**22
        ) as ws:
            result.connect_latency_ms = (time.perf_counter() - start_connect) * 1000

            greeting_received = False
            start_greeting = time.perf_counter()

            async def sender():
                if not args.send_audio:
                    return
                # Break requested audio duration into ~100ms frames
                remaining = args.audio_seconds
                frame_dur = 0.1
                while remaining > 0:
                    chunk_dur = min(frame_dur, remaining)
                    chunk = await generate_silence_chunk(chunk_dur)
                    try:
                        await ws.send(chunk)
                    except Exception as e:
                        result.errors.append(f"send_error:{e}")
                        break
                    await asyncio.sleep(frame_dur)
                    remaining -= frame_dur

            sender_task = asyncio.create_task(sender())

            deadline = time.perf_counter() + args.session_timeout
            while time.perf_counter() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:  # connection closed
                    result.errors.append(f"recv_error:{e}")
                    break

                try:
                    if isinstance(msg, bytes):
                        # Unexpected binary from server
                        continue
                    result.messages.append(msg)
                    parsed = None
                    if msg and msg.startswith("{"):
                        try:
                            parsed = json.loads(msg)
                        except json.JSONDecodeError:
                            pass
                    text_payload = None
                    if parsed:
                        text_payload = (
                            parsed.get("message")
                            or parsed.get("content")
                            or parsed.get("text")
                        )
                    else:
                        text_payload = msg

                    if (
                        not greeting_received
                        and text_payload
                        and DEFAULT_GREETING_PREFIX in text_payload
                    ):
                        greeting_received = True
                        result.greeting_latency_ms = (
                            time.perf_counter() - start_greeting
                        ) * 1000
                        if not args.wait_for_stream:
                            break
                except Exception as e:
                    result.errors.append(f"parse_error:{e}")
                    continue

            sender_task.cancel()
            with contextlib.suppress(Exception):  # type: ignore
                await sender_task
    except Exception as e:
        result.errors.append(f"connect_error:{e}")

    return result


def summarize(results: List[SessionResult]) -> dict:
    connect_lat = [
        r.connect_latency_ms for r in results if r.connect_latency_ms is not None
    ]
    greet_lat = [
        r.greeting_latency_ms for r in results if r.greeting_latency_ms is not None
    ]

    def stats(arr: List[float]) -> dict:
        if not arr:
            return {}
        return {
            "count": len(arr),
            "avg_ms": round(statistics.mean(arr), 2),
            "p50_ms": round(statistics.median(arr), 2),
            "p95_ms": round(percentile(arr, 95), 2),
            "p99_ms": round(percentile(arr, 99), 2),
            "max_ms": round(max(arr), 2),
        }

    contamination = detect_contamination(results)
    alias_contamination = detect_alias_contamination(results)
    error_types: Dict[str, int] = {}
    for r in results:
        for e in r.errors:
            key = e.split(":", 1)[0]
            error_types[key] = error_types.get(key, 0) + 1
    msg_counts = [len(r.messages) for r in results]
    msg_stats = stats(msg_counts) if msg_counts else {}
    return {
        "sessions": len(results),
        "connect_latency": stats(connect_lat),
        "greeting_latency": stats(greet_lat),
        "contamination": contamination,
        "alias_contamination": alias_contamination,
        "errors_total": sum(len(r.errors) for r in results),
        "sessions_with_errors": sum(1 for r in results if r.errors),
        "error_types": error_types,
        "message_count_stats": msg_stats,
        "session_samples": [r.to_dict() for r in results[: min(5, len(results))]],
    }


def percentile(data: List[float], pct: float) -> float:
    if not data:
        return math.nan
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * (pct / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data_sorted[int(k)]
    d0 = data_sorted[int(f)] * (c - k)
    d1 = data_sorted[int(c)] * (k - f)
    return d0 + d1


def detect_contamination(results: List[SessionResult]) -> dict:
    """Identify messages (excluding greeting) that appear verbatim in >1 session.
    This is a heuristic; false positives possible for short generic strings."""
    occurrences: Dict[str, int] = {}
    for r in results:
        seen = set()
        for m in r.messages:
            if DEFAULT_GREETING_PREFIX in m:
                continue
            if len(m) < 8:  # skip very short
                continue
            if m in seen:
                continue
            seen.add(m)
            occurrences[m] = occurrences.get(m, 0) + 1
    shared = {m: c for m, c in occurrences.items() if c > 1}
    return {"shared_message_count": len(shared), "examples": list(shared.items())[:5]}


def detect_alias_contamination(results: List[SessionResult]) -> dict:
    """Check if an alias for one session appears in another session's messages."""
    alias_map = {r.alias: r.session_id for r in results if r.alias}
    cross: Dict[str, List[str]] = {}
    for r in results:
        for alias, sid in alias_map.items():
            if sid == r.session_id:
                continue
            if any(alias in m for m in r.messages):
                cross.setdefault(alias, []).append(r.session_id)
    return {"alias_leak_count": len(cross), "details": cross}


def ensure_dir(path: str):
    if not path:
        return None
    p = pathlib.Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_csv(results: List[SessionResult], path: str):
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "session_id",
                "connect_latency_ms",
                "greeting_latency_ms",
                "message_count",
                "errors",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.session_id,
                    r.connect_latency_ms,
                    r.greeting_latency_ms,
                    len(r.messages),
                    "|".join(r.errors),
                ]
            )


def write_prometheus(results: List[SessionResult], path: str):
    ensure_dir(os.path.dirname(path) or ".")
    conn = [r.connect_latency_ms for r in results if r.connect_latency_ms]
    greet = [r.greeting_latency_ms for r in results if r.greeting_latency_ms]

    def emit_hist(name: str, vals: List[float]) -> str:
        if not vals:
            return ""
        buckets = [50, 100, 200, 500, 1000, 2000, 5000]
        out = []
        for b in buckets:
            c = sum(1 for v in vals if v <= b)
            out.append(f'{name}_bucket{{le="{b}"}} {c}')
        out.append(f'{name}_bucket{{le="+Inf"}} {len(vals)}')
        out.append(f"{name}_count {len(vals)}")
        out.append(f"{name}_sum {sum(vals):.2f}")
        return "\n".join(out)

    lines = [
        "# HELP realtime_sessions_total Total realtime sessions run",
        "# TYPE realtime_sessions_total counter",
        f"realtime_sessions_total {len(results)}",
        "# HELP realtime_session_errors_total Total sessions with errors",
        "# TYPE realtime_session_errors_total counter",
        f"realtime_session_errors_total {sum(1 for r in results if r.errors)}",
        "# HELP realtime_connect_latency Connection latency histogram (ms)",
        "# TYPE realtime_connect_latency histogram",
        emit_hist("realtime_connect_latency", conn),
        "# HELP realtime_greeting_latency Greeting latency histogram (ms)",
        "# TYPE realtime_greeting_latency histogram",
        emit_hist("realtime_greeting_latency", greet),
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(l for l in lines if l is not None))


def load_replay(log_dir: str) -> List[SessionResult]:
    files = glob.glob(os.path.join(log_dir, "session_*.log"))
    results: List[SessionResult] = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            r = SessionResult(
                session_id=data.get("session_id", "unknown"),
                connect_latency_ms=data.get("connect_latency_ms"),
                greeting_latency_ms=data.get("greeting_latency_ms"),
                messages=data.get("messages", []),
                errors=data.get("errors", []),
                alias=data.get("alias"),
            )
            results.append(r)
        except Exception:
            continue
    return results


async def main_async(args):
    if args.replay_log_dir:
        # Replay mode: no live sessions, just aggregate
        all_results = load_replay(args.replay_log_dir)
        summary = summarize(all_results)
        print(json.dumps(summary, indent=2))
        if args.summary_json:
            ensure_dir(os.path.dirname(args.summary_json) or ".")
            with open(args.summary_json, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        return

    all_results: List[SessionResult] = []
    for it in range(args.iterations):
        batch_tasks = [
            run_session(i + it * args.concurrency, args)
            for i in range(args.concurrency)
        ]
        batch_results = await asyncio.gather(*batch_tasks)
        all_results.extend(batch_results)
        if args.iteration_delay > 0 and it < args.iterations - 1:
            await asyncio.sleep(args.iteration_delay)

    summary = summarize(all_results)
    print(json.dumps(summary, indent=2))
    # Exports
    if args.csv:
        write_csv(all_results, args.csv)
    if args.prom:
        write_prometheus(all_results, args.prom)
    if args.log_dir:
        d = ensure_dir(args.log_dir)
        for r in all_results:
            with open(d / f"session_{r.session_id}.log", "w", encoding="utf-8") as f:
                json.dump(r.to_dict() | {"messages": r.messages}, f, indent=2)
    if args.summary_json:
        ensure_dir(os.path.dirname(args.summary_json) or ".")
        with open(args.summary_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    # Check for contamination (exit 2) or auth issues
    if summary["contamination"]["shared_message_count"] > 0:
        # Non-zero shared messages is a potential contamination signal
        sys.exit(2)

    if args.skip_auth_errors:
        # Skip exit on auth errors when testing infrastructure
        auth_errors = summary["error_types"].get("connect_error", 0)
        if auth_errors > 0:
            print(
                f"Note: Skipped {auth_errors} connection errors (likely auth 403s)",
                file=sys.stderr,
            )
    else:
        # Original behavior: any connection errors are concerning
        if summary["sessions_with_errors"] == summary["sessions"]:
            print("Warning: All sessions failed to connect", file=sys.stderr)
            sys.exit(1)

    # Helpful hint if user still points at legacy /realtime without auth token
    if summary["error_types"].get("connect_error") and not args.replay_log_dir:
        # Heuristic: legacy default URL EXACT match and 403-like message content
        if (
            args.ws_url.rstrip("/")
            == "ws://localhost:8010/api/v1/realtime/conversation"
        ):
            print(
                "Hint: /realtime is legacy. Try --ws-url ws://localhost:8010/api/v1/realtime/conversation (add --bearer-token or TEST_BEARER_TOKEN env var if auth enabled).",
                file=sys.stderr,
            )


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Concurrent WebSocket isolation test")
    p.add_argument(
        "--ws-url",
        default=os.environ.get(
            "TEST_REALTIME_WS_URL", "ws://localhost:8010/api/v1/realtime/conversation"
        ),
        help="WebSocket URL for /realtime endpoint",
    )
    p.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=10,
        help="Concurrent sessions per iteration",
    )
    p.add_argument("--iterations", type=int, default=1, help="Number of batches to run")
    p.add_argument(
        "--iteration-delay",
        type=float,
        default=0.0,
        help="Delay seconds between iterations",
    )
    p.add_argument(
        "--session-timeout",
        type=float,
        default=15.0,
        help="Per session max seconds to wait",
    )
    p.add_argument(
        "--send-audio",
        action="store_true",
        help="Send silent PCM frames to exercise STT path",
    )
    p.add_argument(
        "--audio-seconds",
        type=float,
        default=2.0,
        help="Total silent audio seconds to stream when --send-audio is set",
    )
    p.add_argument(
        "--wait-for-stream",
        action="store_true",
        help="Keep session open after greeting until timeout (to catch stray messages)",
    )
    p.add_argument("--csv", help="Path to write per-session CSV summary")
    p.add_argument("--prom", help="Path to write Prometheus metrics exposition file")
    p.add_argument(
        "--log-dir", help="Directory to write per-session detailed JSON logs"
    )
    p.add_argument("--summary-json", help="Path to write extended summary JSON")
    p.add_argument(
        "--replay-log-dir",
        help="Replay existing per-session logs directory (no live traffic)",
    )
    p.add_argument(
        "--skip-auth-errors",
        action="store_true",
        help="Don't fail on 403/auth errors (useful for testing infrastructure)",
    )
    p.add_argument(
        "--bearer-token",
        help="Raw bearer token (w/out 'Bearer') for Authorization header; or set TEST_BEARER_TOKEN env var.",
    )
    return p.parse_args(argv)


def main(argv: List[str]):
    args = parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
