#!/usr/bin/env python3
"""
CI Latency / Perf Guardrail Reporter
====================================

Renders a Markdown snippet that shows the *current-state* latency averages
observed during an eval run next to the perf guardrails configured for the
scenario. Used by the Live Evals workflow so each scenario's parallel job
surfaces its own responsiveness numbers (not just pass/fail).

It never gates the run — the pass/fail decision stays with the eval CLI /
strict gate. This is purely observability so a reviewer can see how much
headroom each scenario has against its budgets.

Usage:
    python -m tests.evaluation.ci_latency_report \
        --scenario tests/evaluation/scenarios/session_based/latency_first_audio.yaml \
        --results-dir runs/results/latency_first_audio \
        --name latency_first_audio
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001 - reporting must never crash the job
        return {}


def _find_summary(results_dir: Path) -> dict[str, Any] | None:
    """Return the most recent summary.json under results_dir (or None)."""
    candidates = sorted(
        results_dir.glob("**/summary.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for candidate in candidates:
        try:
            with open(candidate, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            continue
    return None


def _collect_guardrails(scenario: dict[str, Any]) -> dict[str, float | None]:
    """Extract the tightest configured perf guardrails from a scenario YAML."""
    thresholds = scenario.get("thresholds") or {}
    guardrails: dict[str, float | None] = {
        "e2e_p95_ms": thresholds.get("max_latency_p95_ms"),
        "ttft_ms": None,
        "tts_first_chunk_ms": None,
        "e2e_turn_ms": None,
    }

    # Per-turn budgets are the tightest observable gate — take the min across turns.
    def _tighten(key: str, value: Any) -> None:
        if value is None:
            return
        current = guardrails[key]
        guardrails[key] = value if current is None else min(current, value)

    for turn in scenario.get("turns") or []:
        expectations = (turn or {}).get("expectations") or {}
        _tighten("ttft_ms", expectations.get("max_ttft_ms"))
        _tighten("tts_first_chunk_ms", expectations.get("max_tts_first_chunk_ms"))
        _tighten("e2e_turn_ms", expectations.get("max_latency_ms"))

    return guardrails


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.0f}ms"
    except (TypeError, ValueError):
        return str(value)


def _status(observed_p95: Any, guardrail: Any) -> str:
    if guardrail is None or observed_p95 is None:
        return "—"
    try:
        return "✅" if float(observed_p95) <= float(guardrail) else "⚠️"
    except (TypeError, ValueError):
        return "—"


def render(name: str, scenario_path: Path, results_dir: Path) -> str:
    scenario = _load_yaml(scenario_path)
    guardrails = _collect_guardrails(scenario)
    summary = _find_summary(results_dir)

    lines: list[str] = []
    lines.append(f"### ⏱️ Latency / perf guardrails — `{name}`")
    lines.append("")

    if not summary:
        lines.append("> ⚠️ No `summary.json` found — latency metrics unavailable.")
        lines.append("")
        return "\n".join(lines)

    m = summary.get("latency_metrics") or {}

    # Metric family -> (mean_key, p50_key, p95_key, guardrail_key)
    families = [
        ("End-to-end", "e2e_mean_ms", "e2e_p50_ms", "e2e_p95_ms", "e2e_p95_ms"),
        (
            "First audio (client)",
            "first_audio_mean_ms",
            "first_audio_p50_ms",
            "first_audio_p95_ms",
            "__not_comparable_to_server_tts__",
        ),
        ("Time-to-first-token", "ttft_mean_ms", "ttft_p50_ms", "ttft_p95_ms", "ttft_ms"),
        (
            "TTS first chunk",
            "tts_first_chunk_mean_ms",
            "tts_first_chunk_p50_ms",
            "tts_first_chunk_p95_ms",
            "tts_first_chunk_ms",
        ),
    ]

    lines.append("| Metric | Mean | P50 | P95 | Guardrail | Status |")
    lines.append("|--------|------|-----|-----|-----------|--------|")

    any_row = False
    for label, mean_k, p50_k, p95_k, guard_k in families:
        mean_v = m.get(mean_k)
        p50_v = m.get(p50_k)
        p95_v = m.get(p95_k)
        if mean_v is None and p50_v is None and p95_v is None:
            continue
        any_row = True
        guard = guardrails.get(guard_k)
        lines.append(
            f"| {label} | {_fmt(mean_v)} | {_fmt(p50_v)} | {_fmt(p95_v)} "
            f"| {_fmt(guard)} | {_status(p95_v, guard)} |"
        )

    if not any_row:
        lines.append("| _no latency samples recorded_ | — | — | — | — | — |")

    verdict = summary.get("pass_fail")
    if verdict is True:
        gate = "✅ passed latency gate"
    elif verdict is False:
        gate = "❌ failed latency gate"
    else:
        gate = "no explicit latency gate (observability only)"
    lines.append("")
    lines.append(f"Latency gate: **{gate}**")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    try:
        sys.stdout.write(render(args.name, args.scenario, args.results_dir))
        sys.stdout.write("\n")
    except Exception as exc:  # noqa: BLE001 - never fail the CI job on reporting
        sys.stdout.write(f"> ⚠️ latency report unavailable: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
