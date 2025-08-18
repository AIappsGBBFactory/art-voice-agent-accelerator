"""Full Parameter Demonstration for ws_concurrency_test

Runs a small suite of scenarios exercising every parameter of
`ws_concurrency_test.py` so you can quickly verify behavior and
inspect contamination metrics. Designed to be "dull" (simple / no magic).

Usage (pick one):
  python tests/load/full_params_example.py               # uses defaults
  TEST_BEARER_TOKEN=XXX python tests/load/full_params_example.py --with-auth

Outputs:
  - Prints per‑scenario JSON summary (same structure as base script)
  - Writes combined aggregate summary to tests/load/sessions/aggregate_summary.json
  - Exits non‑zero if any scenario reports contamination.

Scenarios executed (small numbers to keep it fast):
  1. baseline            : minimal connect/disconnect
  2. wait_stream         : keep sockets open to observe isolation
  3. audio               : silent audio frames to exercise STT path
  4. multi_iterations    : multiple batches + exports
  5. replay_demo         : replay just‑captured logs (if available)
  6. (optional) auth     : same as baseline but with bearer token

Adjust counts via environment variables if needed:
  WS_DEMO_CONCURRENCY=8 WS_DEMO_ITERATIONS=2 python ...
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime

# Import the existing test module
try:
    from tests.load import ws_concurrency_test as base
except ImportError:
    # Allow running from repo root when PYTHONPATH not set
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.load import ws_concurrency_test as base  # type: ignore


def ns(**kwargs):  # helper to build an argparse-like namespace
    return SimpleNamespace(**kwargs)


def make_common(overrides: dict | None = None):
    """Return a Namespace populated with every parameter supported, then override."""
    ws_url = os.environ.get(
        "TEST_REALTIME_WS_URL", "ws://localhost:8010/api/v1/realtime/conversation"
    )
    base_dir = Path("tests/load/sessions")
    base_dir.mkdir(parents=True, exist_ok=True)
    params = dict(
        ws_url=ws_url,
        concurrency=int(os.environ.get("WS_DEMO_CONCURRENCY", 4)),
        iterations=1,
        iteration_delay=1.0,
        session_timeout=10.0,
        send_audio=False,
        audio_seconds=2.0,
        wait_for_stream=False,
        csv=None,  # set per scenario
        prom=None,  # set per scenario
        log_dir=None,  # set per scenario
        summary_json=None,  # set per scenario
        replay_log_dir=None,
        skip_auth_errors=True,  # default safe for local
        bearer_token=None,
    )
    if overrides:
        params.update(overrides)
    return ns(**params)


async def run_scenario(name: str, args):
    print(f"\n=== Scenario: {name} ===")
    result_dir = Path("tests/load/sessions") / name
    result_dir.mkdir(parents=True, exist_ok=True)
    # enable exports for one illustrative scenario (multi_iterations)
    if name == "multi_iterations":
        args.csv = str(result_dir / "summary.csv")
        args.prom = str(result_dir / "metrics.prom")
        args.log_dir = str(result_dir / "logs")
        args.summary_json = str(result_dir / "summary.json")
    all_results = []
    for it in range(args.iterations):
        tasks = [
            base.run_session(i + it * args.concurrency, args)
            for i in range(args.concurrency)
        ]
        batch = await asyncio.gather(*tasks)
        all_results.extend(batch)
        if args.iteration_delay > 0 and it < args.iterations - 1:
            await asyncio.sleep(args.iteration_delay)
    summary = base.summarize(all_results)
    print(json.dumps(summary, indent=2))
    if args.csv:
        base.write_csv(all_results, args.csv)
    if args.prom:
        base.write_prometheus(all_results, args.prom)
    if args.log_dir:
        Path(args.log_dir).mkdir(parents=True, exist_ok=True)
        for r in all_results:
            with open(
                Path(args.log_dir) / f"session_{r.session_id}.log",
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(r.to_dict() | {"messages": r.messages}, f, indent=2)
    if args.summary_json:
        with open(args.summary_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    return {"name": name, "summary": summary}


async def main():
    scenarios = []
    scenarios.append(("baseline", make_common()))
    scenarios.append(
        ("wait_stream", make_common({"wait_for_stream": True, "session_timeout": 12.0}))
    )
    scenarios.append(("audio", make_common({"send_audio": True, "audio_seconds": 3.0})))
    scenarios.append(
        ("multi_iterations", make_common({"iterations": 2, "concurrency": 3}))
    )
    replay_logs = Path("tests/load/sessions/multi_iterations/logs")
    if replay_logs.exists():
        scenarios.append(
            ("replay_demo", make_common({"replay_log_dir": str(replay_logs)}))
        )
    token = os.environ.get("TEST_BEARER_TOKEN")
    if ("--with-auth" in sys.argv) and token:
        scenarios.append(
            ("auth", make_common({"bearer_token": token, "skip_auth_errors": False}))
        )

    aggregate = []
    for name, args in scenarios:
        if args.replay_log_dir:
            print(f"\n=== Scenario: {name} (replay) ===")
            results = base.load_replay(args.replay_log_dir)
            summary = base.summarize(results)
            print(json.dumps(summary, indent=2))
            aggregate.append({"name": name, "summary": summary})
            continue
        aggregate.append(await run_scenario(name, args))

    agg_summary_path = Path("tests/load/sessions/aggregate_summary.json")
    agg_summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(agg_summary_path, "w", encoding="utf-8") as f:
        json.dump(aggregate, f, indent=2)
    print(f"\nWrote aggregate summary -> {agg_summary_path}")

    any_contam = any(
        s["summary"]["contamination"]["shared_message_count"] > 0
        for s in aggregate
        if "summary" in s
    )
    if any_contam:
        print(
            "Detected potential message contamination in at least one scenario",
            file=sys.stderr,
        )
        sys.exit(2)
    # All sessions failed in any scenario
    any_all_fail = any(
        s["summary"]["sessions_with_errors"] == s["summary"]["sessions"]
        and s["summary"].get("sessions", 0) != 0
        for s in aggregate
        if "summary" in s
    )
    if any_all_fail:
        print("All sessions failed in a scenario", file=sys.stderr)
        sys.exit(1)
    print("All scenarios completed with no contamination.")


if __name__ == "__main__":
    print(f"[full_params_example] start {datetime.utcnow().isoformat()}Z")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
