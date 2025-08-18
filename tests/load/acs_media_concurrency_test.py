"""Concurrent ACS media WebSocket isolation & latency test.

Spawns N concurrent ACS media WebSocket sessions (simulated) to validate:
  * Per-session isolation (no cross leakage of messages)
  * Greeting / first-token timing (if applicable)
  * Handler stability under concurrency

Notes:
  The ACS media socket expects a real ACS call context (callConnectionId).
  For pure backend stress (without real ACS infra), we simulate by providing
  synthetic x-ms-call-connection-id headers. If backend strictly requires
  a prior REST call setup, these sessions will likely close quickly; we still
  record connection lifecycle results.

Run examples:
  python -m tests.load.acs_media_concurrency_test -c 15 --ws-url ws://localhost:8000/api/v1/media/stream

Add --send-audio to push silent PCM to exercise STT path.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

import websockets

DEFAULT_GREETING_SUBSTRINGS = ["Hi there", "Thank you for calling", "Welcome"]


@dataclass
class MediaSessionResult:
    call_id: str
    connect_latency_ms: float | None = None
    duration_ms: float | None = None
    greeting_latency_ms: float | None = None
    messages: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    closed_code: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "connect_latency_ms": self.connect_latency_ms,
            "greeting_latency_ms": self.greeting_latency_ms,
            "duration_ms": self.duration_ms,
            "message_count": len(self.messages),
            "errors": self.errors,
            "closed_code": self.closed_code,
        }


async def generate_silence_chunk(
    duration_sec: float, sample_rate: int = 16000
) -> bytes:
    frame_count = int(sample_rate * duration_sec)
    return b"\x00\x00" * frame_count


async def run_media_session(idx: int, args) -> MediaSessionResult:
    call_id = f"call-{idx}-{random.randint(1000,9999)}"
    result = MediaSessionResult(call_id=call_id)
    headers = {"x-ms-call-connection-id": call_id}
    start = time.perf_counter()
    try:
        async with websockets.connect(
            args.ws_url, additional_headers=headers, max_size=2**22
        ) as ws:
            result.connect_latency_ms = (time.perf_counter() - start) * 1000
            start_session = time.perf_counter()
            greeting_received = False

            async def sender():
                if not args.send_audio:
                    return
                remaining = args.audio_seconds
                frame_dur = 0.1
                while remaining > 0:
                    chunk = await generate_silence_chunk(min(frame_dur, remaining))
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
                except Exception as e:
                    result.errors.append(f"recv_error:{e}")
                    break
                if isinstance(msg, bytes):
                    # Media handler may not send binary back; ignore
                    continue
                result.messages.append(msg)
                txt = None
                if msg.startswith("{"):
                    try:
                        payload = json.loads(msg)
                        txt = (
                            payload.get("message")
                            or payload.get("content")
                            or payload.get("text")
                        )
                    except json.JSONDecodeError:
                        txt = msg
                else:
                    txt = msg
                if (
                    not greeting_received
                    and txt
                    and any(s in txt for s in DEFAULT_GREETING_SUBSTRINGS)
                ):
                    greeting_received = True
                    result.greeting_latency_ms = (
                        time.perf_counter() - start_session
                    ) * 1000
                    if not args.wait_for_stream:
                        break
            sender_task.cancel()
            with contextlib.suppress(Exception):
                await sender_task
    except Exception as e:
        result.errors.append(f"connect_error:{e}")
    finally:
        result.duration_ms = (time.perf_counter() - start) * 1000
    return result


def percentile(data: List[float], pct: float) -> float:
    if not data:
        return math.nan
    arr = sorted(data)
    k = (len(arr) - 1) * pct / 100
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return arr[int(k)]
    return arr[f] * (c - k) + arr[c] * (k - f)


def detect_shared(results: List[MediaSessionResult]) -> Dict[str, Any]:
    occ: Dict[str, int] = {}
    for r in results:
        seen = set()
        for m in r.messages:
            if any(s in m for s in DEFAULT_GREETING_SUBSTRINGS):
                continue
            if len(m) < 8:
                continue
            if m in seen:
                continue
            seen.add(m)
            occ[m] = occ.get(m, 0) + 1
    shared = {m: c for m, c in occ.items() if c > 1}
    return {"shared_message_count": len(shared), "examples": list(shared.items())[:5]}


def summarize(results: List[MediaSessionResult]) -> Dict[str, Any]:
    conn = [r.connect_latency_ms for r in results if r.connect_latency_ms]
    greet = [r.greeting_latency_ms for r in results if r.greeting_latency_ms]

    def stats(a: List[float]):
        if not a:
            return {}
        return {
            "count": len(a),
            "avg_ms": round(statistics.mean(a), 2),
            "p50_ms": round(statistics.median(a), 2),
            "p95_ms": round(percentile(a, 95), 2),
            "p99_ms": round(percentile(a, 99), 2),
            "max_ms": round(max(a), 2),
        }

    shared = detect_shared(results)
    return {
        "sessions": len(results),
        "connect_latency": stats(conn),
        "greeting_latency": stats(greet),
        "contamination": shared,
        "errors_total": sum(len(r.errors) for r in results),
        "sessions_with_errors": sum(1 for r in results if r.errors),
        "session_samples": [r.to_dict() for r in results[: min(5, len(results))]],
    }


def write_csv(results: List[MediaSessionResult], path: str):
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "call_id",
                "connect_latency_ms",
                "greeting_latency_ms",
                "duration_ms",
                "message_count",
                "errors",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.call_id,
                    r.connect_latency_ms,
                    r.greeting_latency_ms,
                    r.duration_ms,
                    len(r.messages),
                    "|".join(r.errors),
                ]
            )


def write_prometheus(results: List[MediaSessionResult], path: str):
    # Basic exposition format counters/histograms (manual simple form)
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
        "# HELP media_sessions_total Total media sessions run",
        "# TYPE media_sessions_total counter",
        f"media_sessions_total {len(results)}",
        "# HELP media_session_errors_total Total sessions with errors",
        "# TYPE media_session_errors_total counter",
        f"media_session_errors_total {sum(1 for r in results if r.errors)}",
        "# HELP media_connect_latency Connection latency histogram (ms)",
        "# TYPE media_connect_latency histogram",
        emit_hist("media_connect_latency", conn),
        "# HELP media_greeting_latency Greeting latency histogram (ms)",
        "# TYPE media_greeting_latency histogram",
        emit_hist("media_greeting_latency", greet),
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(l for l in lines if l is not None))


def ensure_log_dir(path: str):
    import pathlib

    p = pathlib.Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def main_async(args):
    results: List[MediaSessionResult] = []
    for it in range(args.iterations):
        tasks = [
            run_media_session(i + it * args.concurrency, args)
            for i in range(args.concurrency)
        ]
        batch = await asyncio.gather(*tasks)
        results.extend(batch)
        if args.iteration_delay > 0 and it < args.iterations - 1:
            await asyncio.sleep(args.iteration_delay)
    summary = summarize(results)
    print(json.dumps(summary, indent=2))
    if args.csv:
        ensure_log_dir(os.path.dirname(args.csv) or ".")
        write_csv(results, args.csv)
    if args.prom:
        ensure_log_dir(os.path.dirname(args.prom) or ".")
        write_prometheus(results, args.prom)
    if args.log_dir:
        d = ensure_log_dir(args.log_dir)
        for r in results:
            with open(d / f"session_{r.call_id}.log", "w", encoding="utf-8") as f:
                json.dump(r.to_dict() | {"messages": r.messages}, f, indent=2)
    if summary["contamination"]["shared_message_count"] > 0:
        sys.exit(2)


def parse_args(argv: List[str]):
    ap = argparse.ArgumentParser(description="ACS media WebSocket concurrency test")
    ap.add_argument(
        "--ws-url",
        default=os.environ.get(
            "TEST_ACS_MEDIA_WS_URL", "ws://localhost:8000/api/v1/media/stream"
        ),
    )
    ap.add_argument("-c", "--concurrency", type=int, default=5)
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--iteration-delay", type=float, default=0.0)
    ap.add_argument("--session-timeout", type=float, default=15.0)
    ap.add_argument("--send-audio", action="store_true")
    ap.add_argument("--audio-seconds", type=float, default=2.0)
    ap.add_argument("--wait-for-stream", action="store_true")
    ap.add_argument("--csv", help="Write per-session summary CSV")
    ap.add_argument("--prom", help="Write Prometheus metrics exposition file")
    ap.add_argument("--log-dir", help="Directory for per-session detailed logs")
    return ap.parse_args(argv)


def main(argv: List[str]):
    args = parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
