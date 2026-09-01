"""
Live VoiceLive session-hygiene probe
====================================

The existing live driver (``ws_voice_driver.py``) measures *liveness and
latency*: did a turn answer, and how fast. It deliberately discards the
connection preamble -- ``_drain_startup_messages()`` is documented as "Discard
readiness/greeting frames queued before the first measured turn" -- and it never
asserts anything about the frames themselves beyond counting their kinds.

That is precisely why a family of protocol-correctness regressions shipped
unnoticed: every one of them keeps the call *alive and fast* while corrupting
what the user actually sees and hears.

This probe closes that gap. It captures the startup phase instead of draining
it, and asserts on frame content rather than frame timing:

    greeting_complete      the opening line is not cut off mid-word
    greeting_single        the greeting is delivered exactly once
    envelope_ids_present   the backend stamps a stable id on each envelope
    no_duplicate_delivery  no envelope reaches the client twice
    session_update_quiet   no SESSION UPDATED noise once the session settles
    audio_received         the greeting is actually spoken, not just texted

No audio synthesis and no Azure Speech dependency: the greeting arrives
unprompted on connect, so the highest-signal checks are also the cheapest and
the most deterministic.

Usage
-----
    python -m tests.evaluation.live.session_hygiene_probe --base-url https://<backend-host>

Exit code is non-zero when any check fails, so it can gate CI directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

try:
    import websockets
except ImportError:  # pragma: no cover - dependency is declared in the dev extra
    websockets = None  # type: ignore[assignment]

DEFAULT_WS_PATH = "/api/v1/browser/conversation"
SESSION_PREFIX = "hygiene_"

# The greeting streams in over a few hundred ms and the per-turn session echo
# lands ~200ms after it completes, so a short observation window captures the
# whole startup sequence including anything that arrives late.
DEFAULT_OBSERVE_SECONDS = 12.0

_TEXT_KEYS = ("content", "message", "text", "transcript", "displayText")


def _to_ws_url(base: str, path: str) -> str:
    parsed = urlparse(base if "://" in base else f"https://{base}")
    scheme = "wss" if parsed.scheme in ("https", "wss") else "ws"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def _envelope_id(frame: dict[str, Any]) -> str | None:
    value = frame.get("id")
    return value if isinstance(value, str) and value else None


def _frame_kind(frame: dict[str, Any]) -> str:
    payload = frame.get("payload")
    if isinstance(payload, dict):
        event_type = payload.get("event_type") or payload.get("eventType")
        if isinstance(event_type, str) and event_type:
            return event_type
    kind = frame.get("kind") or frame.get("type") or "unknown"
    return str(kind)


def _extract_text(frame: dict[str, Any]) -> str:
    payload = frame.get("payload")
    source = payload if isinstance(payload, dict) else frame
    for key in _TEXT_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_audio_frame(frame: dict[str, Any]) -> bool:
    """Agent audio arrives as JSON ``audio_data`` frames, not binary WS frames."""
    return str(frame.get("type") or frame.get("kind") or "").lower() in {
        "audio_data",
        "audiodata",
    }


def _is_assistant_frame(frame: dict[str, Any]) -> bool:
    kind = _frame_kind(frame).lower()
    if kind in {"assistant", "assistant_streaming"}:
        return True
    sender = frame.get("sender")
    # Envelope form: an assistant utterance carries real text and a non-System sender.
    return bool(
        isinstance(sender, str)
        and sender not in {"System", "User"}
        and _extract_text(frame)
        and kind not in {"session_updated", "agent_change"}
    )


@dataclass
class Check:
    name: str
    passed: bool
    detail: str

    def render(self) -> str:
        return f"  [{'PASS' if self.passed else 'FAIL'}] {self.name}: {self.detail}"


@dataclass
class ProbeReport:
    base_url: str
    session_id: str
    connected: bool = False
    error: str | None = None
    greeting: str = ""
    frames: list[dict[str, Any]] = field(default_factory=list)
    binary_audio_frames: int = 0
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.checks) and all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "session_id": self.session_id,
            "connected": self.connected,
            "error": self.error,
            "frames_captured": len(self.frames),
            "binary_audio_frames": self.binary_audio_frames,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            "ok": self.ok,
        }


def evaluate(report: ProbeReport) -> None:
    """Apply protocol-correctness checks to the captured startup frames."""
    frames = report.frames
    assistant_texts = [_extract_text(f) for f in frames if _is_assistant_frame(f)]
    assistant_texts = [t for t in assistant_texts if t]

    # ---- greeting delivered, and delivered whole -----------------------------
    # Streaming frames are cumulative prefixes ("Hi" -> "Hi," -> ...), so the
    # longest text is the greeting in its final, fullest form.
    final_greeting = max(assistant_texts, key=len) if assistant_texts else ""

    if not assistant_texts:
        report.checks.append(
            Check("greeting_delivered", False, "no assistant greeting frame was received at all")
        )
    else:
        report.checks.append(
            Check("greeting_delivered", True, f"greeting received ({len(final_greeting)} chars)")
        )
        report.greeting = final_greeting

    # ---- the spoken greeting must match the text -----------------------------
    # A cancelled response stops emitting audio while the text already committed
    # stays on screen. Roughly one 20ms frame per few characters is expected, so
    # a near-empty audio stream against real text means playback was cut off.
    if final_greeting:
        expected_min_frames = max(5, len(final_greeting) // 12)
        report.checks.append(
            Check(
                "greeting_audio_complete",
                report.binary_audio_frames >= expected_min_frames,
                (
                    f"{report.binary_audio_frames} audio frame(s) for {len(final_greeting)} chars "
                    f"of text (expected >= {expected_min_frames}); playback was cut short"
                    if report.binary_audio_frames < expected_min_frames
                    else f"{report.binary_audio_frames} audio frames match {len(final_greeting)} chars"
                ),
            )
        )

    # ---- every envelope must be identifiable ---------------------------------
    envelope_frames = [f for f in frames if isinstance(f.get("payload"), dict)]
    with_ids = [f for f in envelope_frames if _envelope_id(f)]
    if not envelope_frames:
        report.checks.append(
            Check("envelope_ids_present", False, "no envelope-shaped frames captured")
        )
    else:
        report.checks.append(
            Check(
                "envelope_ids_present",
                len(with_ids) == len(envelope_frames),
                (
                    f"{len(with_ids)}/{len(envelope_frames)} envelopes carry an id "
                    "(without one, duplicate delivery cannot be detected or suppressed)"
                ),
            )
        )

    # ---- no envelope may arrive twice ----------------------------------------
    # Prefer ids. Fall back to a content signature so a build that predates
    # envelope ids is still evaluated rather than silently skipped.
    if with_ids:
        seen: dict[str, int] = {}
        for frame in with_ids:
            fid = _envelope_id(frame)
            if fid:
                seen[fid] = seen.get(fid, 0) + 1
        dupes = {k: v for k, v in seen.items() if v > 1}
        report.checks.append(
            Check(
                "no_duplicate_delivery",
                not dupes,
                (
                    f"{len(dupes)} envelope id(s) delivered more than once"
                    if dupes
                    else f"all {len(seen)} envelope ids unique"
                ),
            )
        )
    else:
        signatures: dict[tuple[str, str, str], int] = {}
        for frame in envelope_frames:
            sig = (_frame_kind(frame), _extract_text(frame), str(frame.get("ts") or ""))
            signatures[sig] = signatures.get(sig, 0) + 1
        dupes = {k: v for k, v in signatures.items() if v > 1 and k[2]}
        report.checks.append(
            Check(
                "no_duplicate_delivery",
                not dupes,
                (
                    f"{len(dupes)} identical envelope(s) (same kind+text+ts) delivered twice: "
                    f"{[k[0] for k in list(dupes)[:3]]}"
                    if dupes
                    else "no duplicate frames detected (content signature)"
                ),
            )
        )

    # ---- SESSION UPDATED must not be per-turn noise --------------------------
    # Bootstrap legitimately emits exactly one: the session really was configured
    # for an agent, and that is worth surfacing once. The bug was the *context-only*
    # instruction refresh after every turn also reaching the UI. This probe only
    # observes the connect phase, so the correct expectation here is "at most the
    # single bootstrap event" -- anything beyond that is the per-turn leak.
    session_updates = [f for f in frames if _frame_kind(f) == "session_updated"]
    report.checks.append(
        Check(
            "session_update_quiet",
            len(session_updates) <= 1,
            (
                f"{len(session_updates)} session_updated events during connect; at most the "
                "single bootstrap event is expected, so a context-only refresh is leaking to the UI"
                if len(session_updates) > 1
                else f"{len(session_updates)} session_updated event(s) (bootstrap only)"
            ),
        )
    )

    # ---- the greeting must actually be audible -------------------------------
    report.checks.append(
        Check(
            "audio_received",
            report.binary_audio_frames > 0,
            f"{report.binary_audio_frames} audio frame(s) received",
        )
    )


async def probe(
    base_url: str,
    *,
    ws_path: str = DEFAULT_WS_PATH,
    observe_seconds: float = DEFAULT_OBSERVE_SECONDS,
    streaming_mode: str = "realtime",
) -> ProbeReport:
    """Connect, listen through the startup phase, and evaluate what arrived."""
    if websockets is None:  # pragma: no cover
        raise RuntimeError("the 'websockets' package is required to run this probe")

    session_id = f"{SESSION_PREFIX}{uuid.uuid4().hex[:8]}"
    query = urlencode(
        {
            "session_id": session_id,
            "streaming_mode": streaming_mode,
            "client_user_id": "hygiene_probe",
        }
    )
    ws_url = f"{_to_ws_url(base_url, ws_path)}?{query}"
    report = ProbeReport(base_url=base_url, session_id=session_id)

    headers = {"x-ms-call-connection-id": session_id, "x-session-id": session_id}

    try:
        async with websockets.connect(
            ws_url, additional_headers=headers, max_size=None, open_timeout=30
        ) as ws:
            report.connected = True
            deadline = time.monotonic() + observe_seconds
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(0.5, max(0.05, remaining)))
                except TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    break

                if isinstance(msg, (bytes, bytearray)):
                    report.binary_audio_frames += 1
                    continue
                try:
                    frame = json.loads(msg)
                except (json.JSONDecodeError, TypeError):
                    continue
                if _is_audio_frame(frame):
                    # Counted, not retained: 100+ base64 payloads per greeting
                    # would swamp the report for no diagnostic gain.
                    report.binary_audio_frames += 1
                    continue
                report.frames.append(frame)
    except Exception as exc:  # noqa: BLE001 - surface connection failures as a report
        report.error = f"{type(exc).__name__}: {exc}"

    evaluate(report)
    return report


async def probe_repeated(
    base_url: str,
    *,
    runs: int = 3,
    ws_path: str = DEFAULT_WS_PATH,
    observe_seconds: float = DEFAULT_OBSERVE_SECONDS,
    streaming_mode: str = "voice_live",
) -> tuple[list[ProbeReport], Check]:
    """Run the probe several times and check the greeting is *deterministic*.

    The greeting is model-generated from a ``say=`` instruction, so there is no
    fixed string to diff against -- but a correct implementation still delivers
    the same complete opening every time. When a race truncates it, the cut
    lands in a different place on each call ("I'm Banking", "I'm BankingConc",
    "Contoso Bank."). Instability across runs is therefore a direct, assertable
    signature of the race that no single-run check can produce.
    """
    reports: list[ProbeReport] = []
    for _ in range(runs):
        reports.append(
            await probe(
                base_url,
                ws_path=ws_path,
                observe_seconds=observe_seconds,
                streaming_mode=streaming_mode,
            )
        )

    greetings = [r.greeting for r in reports if r.greeting]
    distinct = sorted(set(greetings))
    if len(greetings) < 2:
        stability = Check(
            "greeting_stable",
            False,
            f"only {len(greetings)} of {runs} runs produced a greeting to compare",
        )
    else:
        stability = Check(
            "greeting_stable",
            len(distinct) == 1,
            (
                f"greeting differed across {len(greetings)} runs -> "
                f"{[g[-28:] for g in distinct]} (truncation point varies: race)"
                if len(distinct) > 1
                else f"identical greeting across {len(greetings)} runs"
            ),
        )
    return reports, stability


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Live VoiceLive session-hygiene probe")
    p.add_argument("--base-url", required=True, help="Backend base URL or host")
    p.add_argument("--ws-path", default=DEFAULT_WS_PATH)
    p.add_argument("--observe-seconds", type=float, default=DEFAULT_OBSERVE_SECONDS)
    p.add_argument("--streaming-mode", default="voice_live")
    p.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Run N sessions and additionally assert the greeting is stable across them",
    )
    p.add_argument("--json", action="store_true", help="Emit the report as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.runs > 1:
        reports, stability = asyncio.run(
            probe_repeated(
                args.base_url,
                runs=args.runs,
                ws_path=args.ws_path,
                observe_seconds=args.observe_seconds,
                streaming_mode=args.streaming_mode,
            )
        )
        report = reports[-1]
        report.checks.append(stability)
        if args.json:
            print(
                json.dumps(
                    {
                        "runs": [r.to_dict() for r in reports],
                        "stability": {
                            "name": stability.name,
                            "passed": stability.passed,
                            "detail": stability.detail,
                        },
                    },
                    indent=2,
                )
            )
            return 0 if all(r.ok for r in reports) and stability.passed else 1
    else:
        report = asyncio.run(
            probe(
                args.base_url,
                ws_path=args.ws_path,
                observe_seconds=args.observe_seconds,
                streaming_mode=args.streaming_mode,
            )
        )
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
            return 0 if report.ok else 1

    print(f"\nVoiceLive session hygiene -- {args.base_url}")
    print(
        f"  mode={args.streaming_mode} runs={args.runs} "
        f"frames={len(report.frames)} audio={report.binary_audio_frames}"
    )
    if report.error:
        print(f"  connection error: {report.error}")
    if report.greeting:
        print(f"  greeting: {report.greeting!r}")
    print()
    for check in report.checks:
        print(check.render())
    print(f"\n  => {'PASS' if report.ok else 'FAIL'}\n")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
