#!/usr/bin/env python3
"""
Deployed voice-WebSocket eval driver
====================================

Drives a session-based eval scenario against a *deployed* backend's real voice
WebSocket (``/api/v1/browser/conversation``) so latency numbers reflect the
deployed environment (real STT -> LLM -> TTS -> first audio), rather than the
in-process orchestrator run on the CI runner.

What it does per scenario:

1. Load a session-based scenario YAML and read ``turns[].user_input``.
2. Synthesize each user turn to base64 PCM16 16 kHz frames via the production
   ``SpeechSynthesizer`` (cached on disk keyed by text hash).
3. Connect to ``wss://<host>/api/v1/browser/conversation`` with
    ``?session_id=<prefix><scenario>_<uuid>&streaming_mode=<mode>``. The
    ``session_id`` is stamped onto the backend's OpenTelemetry spans, so an
    ``eval_live_`` prefix makes every span for this run separable in App Insights.
4. Stream the turn's audio (binary PCM frames) + a short trailing silence to
   trigger STT finalization, then capture per turn:
    * ``first_response_ms`` = EOS -> first assistant/audio frame
       * ``first_audio_ms``    = EOS -> first inbound *audio* frame
       * ``response_text``      = best-effort assistant text from inbound frames
       * ``turn_wall_ms``       = EOS -> response considered complete
5. Write a JSON result (per-turn latencies + captured text + the ``session_id``)
   so a downstream trace-grading step can join on ``session.id``.

This driver only *observes* the voice channel. Tool-call / handoff / content
assertions are graded from the ``eval_``-tagged traces in App Insights.

Wire protocol matches ``tests/load/locustfile.browser_conversation.py``: one
``AudioMetadata`` JSON frame on connect, then raw binary PCM16 16 kHz mono
frames.

Example
-------
    python -m tests.evaluation.live.ws_voice_driver \
        --scenario tests/evaluation/scenarios/session_based/decline_specialist_email.yaml \
        --url https://artagent-backend-xxxx.azurecontainerapps.io \
        --out /tmp/live_eval_result.json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import websockets
import yaml

from utils.ml_logging import get_logger

logger = get_logger("evaluation.live.ws_voice_driver")

# --- Audio constants (PCM16 mono 16 kHz, 20 ms frames) -----------------------
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
CHANNELS = 1
FRAME_MS = 20
FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS * FRAME_MS / 1000)  # 640

DEFAULT_WS_PATH = "/api/v1/browser/conversation"
DEFAULT_SESSION_PREFIX = "eval_"
# Committable cache so CI can drive the deployed WS with zero Azure data-plane
# creds (audio is generated once by a run that can reach Azure Speech).
DEFAULT_CACHE_DIR = Path("runs/live-evals/audio-cache")

# Inbound text frames carrying assistant content use varied key names across
# pipelines; probe these in order.
_TEXT_KEYS = ("text", "content", "displayText", "message", "transcript", "response")


# =============================================================================
# Result models
# =============================================================================
@dataclass
class TurnResult:
    turn_id: str
    user_input: str
    audio_frames_sent: int = 0
    audio_ms_sent: float = 0.0
    first_response_ms: float | None = None
    first_audio_ms: float | None = None
    turn_wall_ms: float | None = None
    response_text: str = ""
    inbound_kinds: dict[str, int] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ScenarioResult:
    scenario_name: str
    session_id: str
    ws_url: str
    streaming_mode: str
    traceparent: str | None = None
    connect_latency_ms: float | None = None
    ok: bool = False
    error: str | None = None
    turns: list[TurnResult] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    unmeasured_expectations: list[str] = field(default_factory=list)
    pass_fail: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # summary latency rollups (helps the CI gate / trace join)
        first_audio = [t.first_audio_ms for t in self.turns if t.first_audio_ms is not None]
        first_responses = [
            t.first_response_ms for t in self.turns if t.first_response_ms is not None
        ]
        turn_walls = [t.turn_wall_ms for t in self.turns if t.turn_wall_ms is not None]
        d["summary"] = {
            "turns": len(self.turns),
            "turns_with_response": sum(1 for t in self.turns if t.first_response_ms is not None),
            "turns_with_audio": sum(1 for t in self.turns if t.first_audio_ms is not None),
            "first_audio_ms_avg": round(sum(first_audio) / len(first_audio), 1)
            if first_audio
            else None,
            "first_audio_ms_max": round(max(first_audio), 1) if first_audio else None,
        }
        d["latency_metrics"] = {
            **_latency_stats("e2e", turn_walls),
            **_latency_stats("first_audio", first_audio),
            **_latency_stats("first_response", first_responses),
        }
        return d


# =============================================================================
# Audio synthesis (text -> base64 PCM16 16k frames), disk-cached
# =============================================================================
class TurnAudioSynth:
    """Synthesizes scenario turns to PCM16 16 kHz frames using production TTS."""

    def __init__(self, cache_dir: Path, voice: str | None = None) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.voice = voice or os.getenv("EVAL_TTS_VOICE", "en-US-JennyMultilingualNeural")
        self._synth: Any = None  # lazily created SpeechSynthesizer

    def _ensure_synth(self) -> None:
        if self._synth is not None:
            return
        # Import lazily so `--help` and cached runs don't require the Speech SDK.
        from src.speech.text_to_speech import SpeechSynthesizer

        self._synth = SpeechSynthesizer(
            region=os.getenv("AZURE_SPEECH_REGION"),
            key=os.getenv("AZURE_SPEECH_KEY"),
            language="en-US",
            voice=self.voice,
            playback="never",
            enable_tracing=False,
        )

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.sha1(f"{self.voice}|{text}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{digest}.pcm"

    def pcm_for(self, text: str) -> bytes:
        """Return raw PCM16 16 kHz mono bytes for `text` (cached on disk)."""
        cache_path = self._cache_path(text)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path.read_bytes()

        self._ensure_synth()
        frames_b64 = self._synth.synthesize_to_base64_frames(text, sample_rate=SAMPLE_RATE)
        pcm = b"".join(base64.b64decode(f) for f in frames_b64)
        if not pcm:
            raise RuntimeError(f"TTS produced no audio for turn text: {text!r}")
        cache_path.write_bytes(pcm)
        return pcm


def _silence_frame() -> bytes:
    """Return deterministic low-level PCM noise that keeps STT VAD engaged."""
    pattern = b"\x0c\x00\xf4\xff"  # alternating +12/-12 PCM16 samples
    return (pattern * (FRAME_BYTES // len(pattern) + 1))[:FRAME_BYTES]


def _percentile(values: list[float], percentage: float) -> float | None:
    """Return a linearly interpolated percentile without external dependencies."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    position = (len(ordered) - 1) * percentage / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 1)


def _latency_stats(prefix: str, values: list[float]) -> dict[str, float | None]:
    """Build stable mean/P50/P95/P99 fields for CI and local reports."""
    return {
        f"{prefix}_mean_ms": round(sum(values) / len(values), 1) if values else None,
        f"{prefix}_p50_ms": _percentile(values, 50),
        f"{prefix}_p95_ms": _percentile(values, 95),
        f"{prefix}_p99_ms": _percentile(values, 99),
    }


def _new_traceparent() -> str:
    """Create a valid W3C traceparent for the driver-to-backend trace root."""
    return f"00-{uuid.uuid4().hex}-{uuid.uuid4().hex[:16]}-01"


def _evaluate_live_result(
    result: ScenarioResult,
    scenario: dict[str, Any],
    *,
    require_audio: bool,
) -> None:
    """Apply client-observable E2E gates without pretending to measure server KPIs."""
    expectations_by_turn = {
        str(turn.get("turn_id")): turn.get("expectations") or {}
        for turn in scenario.get("turns") or []
        if isinstance(turn, dict)
    }
    checks: list[dict[str, Any]] = []
    unmeasured: set[str] = set()

    for turn in result.turns:
        expectations = expectations_by_turn.get(turn.turn_id, {})
        if expectations.get("max_ttft_ms") is not None:
            unmeasured.add("max_ttft_ms (server trace)")
        if expectations.get("max_tts_first_chunk_ms") is not None:
            unmeasured.add("max_tts_first_chunk_ms (server trace)")

        if turn.error:
            checks.append(
                {
                    "turn_id": turn.turn_id,
                    "check": "turn_completed",
                    "passed": False,
                    "actual": turn.error,
                    "expected": "response",
                }
            )
            continue

        if require_audio:
            checks.append(
                {
                    "turn_id": turn.turn_id,
                    "check": "first_audio_ms",
                    "passed": turn.first_audio_ms is not None,
                    "actual": turn.first_audio_ms,
                    "expected": "not null",
                }
            )

        max_latency_ms = expectations.get("max_latency_ms")
        if max_latency_ms is not None:
            passed = turn.turn_wall_ms is not None and turn.turn_wall_ms <= float(max_latency_ms)
            checks.append(
                {
                    "turn_id": turn.turn_id,
                    "check": "max_latency_ms",
                    "passed": passed,
                    "actual": turn.turn_wall_ms,
                    "expected": max_latency_ms,
                }
            )

    max_latency_p95_ms = (scenario.get("thresholds") or {}).get("max_latency_p95_ms")
    if max_latency_p95_ms is not None:
        turn_walls = [
            turn.turn_wall_ms for turn in result.turns if turn.turn_wall_ms is not None
        ]
        observed_p95 = _percentile(turn_walls, 95)
        checks.append(
            {
                "turn_id": None,
                "check": "max_latency_p95_ms",
                "passed": observed_p95 is not None and observed_p95 <= float(max_latency_p95_ms),
                "actual": observed_p95,
                "expected": max_latency_p95_ms,
            }
        )

    if not result.turns or result.error:
        checks.append(
            {
                "turn_id": None,
                "check": "scenario_completed",
                "passed": False,
                "actual": result.error or "no turns",
                "expected": "all turns completed",
            }
        )

    result.checks = checks
    result.unmeasured_expectations = sorted(unmeasured)
    result.pass_fail = all(check["passed"] for check in checks) if checks else result.ok
    result.ok = result.ok and result.pass_fail is not False


def _load_turns(scenario_path: Path) -> list[tuple[str, str]]:
    """Return ``[(turn_id, user_input), ...]`` for a session-based scenario YAML."""
    doc = yaml.safe_load(scenario_path.read_text())
    turns: list[tuple[str, str]] = []
    for idx, turn in enumerate(doc.get("turns") or []):
        user_input = str(turn.get("user_input", "")).strip()
        turn_id = str(turn.get("turn_id") or f"turn_{idx + 1}")
        if user_input:
            turns.append((turn_id, user_input))
    return turns


def pregenerate_audio(
    scenario_path: Path, cache_dir: Path, voice: str | None = None
) -> list[Path]:
    """Synthesize every turn of a scenario into the disk cache and return the paths.

    Run this once from an environment that can reach Azure Speech; the resulting
    cache is portable, so the WS driver can then run against the deployed
    endpoint without any Azure data-plane credentials.
    """
    _maybe_bootstrap_appconfig()
    synth = TurnAudioSynth(cache_dir, voice=voice)
    paths: list[Path] = []
    for _turn_id, user_input in _load_turns(scenario_path):
        synth.pcm_for(user_input)  # writes to cache
        paths.append(synth._cache_path(user_input))
    return paths


def _maybe_bootstrap_appconfig() -> None:
    """Hydrate Azure Speech creds from App Configuration if absent from the env.

    Local and CI runs get Speech region/key from Azure App Config rather than
    ``.env``; without this the TTS step has no credentials. No-op when Speech
    creds are already present or App Config is not configured. Requires an
    ``az login`` / managed identity that can read the App Config store.
    """
    if os.getenv("AZURE_SPEECH_KEY") or os.getenv("AZURE_SPEECH_ENDPOINT"):
        return
    if not os.getenv("AZURE_APPCONFIG_ENDPOINT"):
        return
    try:
        from apps.artagent.backend.config.appconfig_provider import bootstrap_appconfig

        if bootstrap_appconfig():
            logger.info("Hydrated Azure Speech config from App Configuration")
    except Exception as exc:  # noqa: BLE001 - fall back to whatever env creds exist
        logger.warning("App Config bootstrap failed (%s); relying on env creds", exc)


# =============================================================================
# WebSocket driving
# =============================================================================
def _to_ws_url(base: str, path: str) -> str:
    """Normalize an http(s)/ws(s) base + path into a wss:// (or ws://) URL."""
    base = base.strip()
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    elif not base.startswith(("ws://", "wss://")):
        base = "wss://" + base.lstrip("/")

    parsed = urlparse(base)
    if parsed.path in ("", "/"):
        parsed = parsed._replace(path=path)
    return urlunparse(parsed)


def _extract_text(frame: dict[str, Any]) -> str:
    for key in _TEXT_KEYS:
        val = frame.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Nested envelopes (e.g. {"audioData": {...}}, {"errorData": {...}})
    for val in frame.values():
        if isinstance(val, dict):
            nested = _extract_text(val)
            if nested:
                return nested
    return ""


def _frame_kind(frame: dict[str, Any]) -> str:
    return str(frame.get("kind") or frame.get("type") or "unknown")


def _normalized_kind(kind: str) -> str:
    return kind.lower().replace("-", "_")


def _is_audio_kind(kind: str) -> bool:
    return _normalized_kind(kind) in {"audiodata", "audio_data"}


def _is_response_kind(kind: str) -> bool:
    return _is_audio_kind(kind) or _normalized_kind(kind) in {
        "assistant",
        "assistant_streaming",
    }


async def _drain_startup_messages(ws: Any) -> None:
    """Discard readiness/greeting frames queued before the first measured turn."""
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.05)
        except asyncio.TimeoutError:
            return
        except websockets.ConnectionClosed:
            return


async def _run_turn(
    ws: Any,
    turn_id: str,
    user_input: str,
    pcm: bytes,
    *,
    turn_timeout: float,
    quiet_gap: float,
    first_byte_timeout: float,
) -> TurnResult:
    result = TurnResult(turn_id=turn_id, user_input=user_input)

    # --- Send the user turn as 20 ms binary PCM frames at real-time cadence ---
    frames = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    for chunk in frames:
        await ws.send(chunk)
        result.audio_frames_sent += 1
        await asyncio.sleep(FRAME_MS / 1000.0)
    result.audio_ms_sent = round(len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE) * 1000.0, 1)

    # --- Trailing silence to trigger STT finalization (~1.2s) ---
    for _ in range(60):
        await ws.send(_silence_frame())
        await asyncio.sleep(FRAME_MS / 1000.0)

    # End-of-speech anchor: latency is measured from here.
    eos = time.monotonic()
    deadline = eos + turn_timeout
    first_byte_deadline = eos + first_byte_timeout
    last_inbound: float | None = None
    texts: list[str] = []

    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        # Complete once we've had a response and then a quiet gap.
        if last_inbound is not None and (now - last_inbound) >= quiet_gap:
            break
        if result.first_response_ms is None and now >= first_byte_deadline:
            result.error = "no_response_before_first_byte_timeout"
            break

        recv_timeout = min(0.2, max(0.02, deadline - now))
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
        except asyncio.TimeoutError:
            continue
        except websockets.ConnectionClosed:
            break

        now = time.monotonic()
        last_inbound = now

        if isinstance(msg, (bytes, bytearray)):
            # Inbound binary = agent audio.
            result.inbound_kinds["binary_audio"] = result.inbound_kinds.get("binary_audio", 0) + 1
            if result.first_response_ms is None:
                result.first_response_ms = round((now - eos) * 1000.0, 1)
            if result.first_audio_ms is None:
                result.first_audio_ms = round((now - eos) * 1000.0, 1)
            continue

        try:
            frame = json.loads(msg)
        except (json.JSONDecodeError, TypeError):
            result.inbound_kinds["unparseable"] = result.inbound_kinds.get("unparseable", 0) + 1
            continue

        kind = _frame_kind(frame)
        result.inbound_kinds[kind] = result.inbound_kinds.get(kind, 0) + 1
        text = _extract_text(frame)
        if result.first_response_ms is None and _is_response_kind(kind):
            result.first_response_ms = round((now - eos) * 1000.0, 1)
        if _is_audio_kind(kind) and result.first_audio_ms is None:
            result.first_audio_ms = round((now - eos) * 1000.0, 1)
        if text:
            texts.append(text)

    result.response_text = " ".join(texts).strip()
    if result.first_response_ms is not None:
        result.turn_wall_ms = round((time.monotonic() - eos) * 1000.0, 1)
    return result


async def run_scenario(
    scenario_path: Path,
    base_url: str,
    *,
    ws_path: str = DEFAULT_WS_PATH,
    streaming_mode: str = "realtime",
    session_prefix: str = DEFAULT_SESSION_PREFIX,
    industry: str | None = None,
    cache_dir: Path | None = None,
    turn_timeout: float = 20.0,
    quiet_gap: float = 2.0,
    first_byte_timeout: float = 12.0,
    inter_turn_pause: float = 1.0,
    bootstrap_appconfig: bool = True,
    require_audio_cache: bool = False,
    require_audio: bool = True,
) -> ScenarioResult:
    """Drive one scenario against the deployed voice WS and return measurements."""
    if bootstrap_appconfig:
        _maybe_bootstrap_appconfig()

    doc = yaml.safe_load(scenario_path.read_text())
    scenario_name = str(doc.get("scenario_name") or scenario_path.stem)
    industry = industry or (doc.get("session_config", {}).get("agent_defaults", {}) or {}).get(
        "industry"
    ) or (doc.get("demo_user", {}) or {}).get("scenario")
    configured_email = (doc.get("demo_user", {}) or {}).get("email")
    scenario_text = scenario_path.read_text(encoding="utf-8")
    uses_email_placeholder = "${demo_user.email}" in scenario_text or "${email}" in scenario_text
    demo_email = (
        os.getenv("EVAL_EMAIL_OVERRIDE") if uses_email_placeholder else configured_email
    ) or configured_email

    session_id = f"{session_prefix}{scenario_name}_{uuid.uuid4().hex[:8]}"
    ws_url = _to_ws_url(base_url, ws_path)
    traceparent = _new_traceparent()
    query = "?" + urlencode(
        {
            "session_id": session_id,
            "streaming_mode": streaming_mode,
            "client_traceparent": traceparent,
            "client_user_id": "eval_driver",
            **({"user_email": demo_email} if demo_email else {}),
            **({"scenario": industry} if industry else {}),
        }
    )

    result = ScenarioResult(
        scenario_name=scenario_name,
        session_id=session_id,
        ws_url=ws_url,
        streaming_mode=streaming_mode,
        traceparent=traceparent,
    )

    synth = TurnAudioSynth(cache_dir or DEFAULT_CACHE_DIR)
    # Pre-synthesize (fail fast + not counted against turn latency).
    pcm_by_turn: list[tuple[str, str, bytes]] = []
    try:
        for turn_id, user_input in _load_turns(scenario_path):
            cache_path = synth._cache_path(user_input)
            if require_audio_cache and (not cache_path.exists() or cache_path.stat().st_size <= 0):
                raise FileNotFoundError(
                    f"Missing cached input audio for {turn_id}; run with --synth-only first"
                )
            pcm_by_turn.append((turn_id, user_input, synth.pcm_for(user_input)))
    except Exception as exc:  # noqa: BLE001 - surface synthesis failures to the caller
        result.error = f"tts_failed: {exc}"
        logger.error("TTS synthesis failed for %s: %s", scenario_name, exc, exc_info=True)
        _evaluate_live_result(result, doc, require_audio=require_audio)
        return result

    logger.info(
        "Driving %d turns against %s (session_id=%s)", len(pcm_by_turn), ws_url, session_id
    )

    headers = {
        "x-ms-call-connection-id": session_id,
        "x-session-id": session_id,
    }
    metadata = {
        "kind": "AudioMetadata",
        "audioMetadata": {
            "subscriptionId": str(uuid.uuid4()),
            "encoding": "PCM",
            "sampleRate": SAMPLE_RATE,
            "channels": CHANNELS,
            "length": FRAME_BYTES,
        },
    }

    try:
        connect_started = time.monotonic()
        async with websockets.connect(
            ws_url + query,
            additional_headers=headers,
            max_size=None,
            open_timeout=30,
        ) as ws:
            result.connect_latency_ms = round((time.monotonic() - connect_started) * 1000.0, 1)
            await ws.send(json.dumps(metadata))
            await asyncio.sleep(1.0)  # let the session initialize / greeting settle
            await _drain_startup_messages(ws)

            for turn_id, user_input, pcm in pcm_by_turn:
                logger.info("[%s] turn %s: %r", session_id, turn_id, user_input[:80])
                try:
                    turn_result = await _run_turn(
                        ws,
                        turn_id,
                        user_input,
                        pcm,
                        turn_timeout=turn_timeout,
                        quiet_gap=quiet_gap,
                        first_byte_timeout=first_byte_timeout,
                    )
                except websockets.ConnectionClosed as exc:
                    turn_result = TurnResult(turn_id=turn_id, user_input=user_input)
                    turn_result.error = f"connection_closed: {exc.code}"
                    result.turns.append(turn_result)
                    result.error = f"connection_closed_mid_scenario: {exc.code}"
                    break
                result.turns.append(turn_result)
                await asyncio.sleep(inter_turn_pause)

        result.ok = result.error is None and all(t.error is None for t in result.turns)
    except Exception as exc:  # noqa: BLE001 - connection/handshake failures
        result.error = f"ws_error: {exc}"
        logger.error("WebSocket drive failed for %s: %s", scenario_name, exc, exc_info=True)

    _evaluate_live_result(result, doc, require_audio=require_audio)
    return result


# =============================================================================
# CLI
# =============================================================================
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Drive an eval scenario against a deployed voice WS.")
    p.add_argument("--scenario", required=True, type=Path, help="Session-based scenario YAML.")
    p.add_argument(
        "--url",
        default=os.getenv("EVAL_BACKEND_URL") or os.getenv("BACKEND_CONTAINER_APP_URL"),
        help="Deployed backend base URL (http[s]/ws[s]). Defaults to EVAL_BACKEND_URL.",
    )
    p.add_argument("--ws-path", default=DEFAULT_WS_PATH)
    p.add_argument(
        "--streaming-mode",
        choices=("realtime", "voice_live"),
        default=os.getenv("EVAL_STREAMING_MODE", "realtime"),
        help="Backend orchestration mode to exercise explicitly.",
    )
    p.add_argument("--session-prefix", default=DEFAULT_SESSION_PREFIX)
    p.add_argument("--industry", default=None, help="Scenario industry query (e.g. banking).")
    p.add_argument("--cache-dir", type=Path, default=None)
    p.add_argument(
        "--synth-only",
        action="store_true",
        help="Only generate the audio cache for the scenario (needs Azure Speech), then exit.",
    )
    p.add_argument("--turn-timeout", type=float, default=20.0)
    p.add_argument("--quiet-gap", type=float, default=2.0)
    p.add_argument("--first-byte-timeout", type=float, default=12.0)
    p.add_argument(
        "--require-audio-cache",
        action="store_true",
        help="Fail instead of synthesizing missing input audio (recommended for perf runs).",
    )
    p.add_argument(
        "--allow-missing-audio",
        action="store_true",
        help="Do not fail the E2E gate when the backend returns no audio frame.",
    )
    p.add_argument(
        "--no-appconfig",
        action="store_true",
        help="Do not hydrate Speech creds from Azure App Config (use env vars only).",
    )
    p.add_argument("--out", type=Path, default=None, help="Write JSON result here.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.scenario.exists():
        print(f"error: scenario not found: {args.scenario}", file=sys.stderr)
        return 2

    if args.synth_only:
        paths = pregenerate_audio(args.scenario, args.cache_dir or DEFAULT_CACHE_DIR)
        for pth in paths:
            print(pth)
        logger.info("Generated %d cached audio file(s)", len(paths))
        return 0

    if not args.url:
        print(
            "error: --url (or EVAL_BACKEND_URL / BACKEND_CONTAINER_APP_URL) is required",
            file=sys.stderr,
        )
        return 2

    result = asyncio.run(
        run_scenario(
            args.scenario,
            args.url,
            ws_path=args.ws_path,
            streaming_mode=args.streaming_mode,
            session_prefix=args.session_prefix,
            industry=args.industry,
            cache_dir=args.cache_dir,
            turn_timeout=args.turn_timeout,
            quiet_gap=args.quiet_gap,
            first_byte_timeout=args.first_byte_timeout,
            bootstrap_appconfig=not args.no_appconfig,
            require_audio_cache=args.require_audio_cache,
            require_audio=not args.allow_missing_audio,
        )
    )

    payload = result.to_dict()
    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.write_text(text)
        logger.info("Wrote result to %s", args.out)
    print(text)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
