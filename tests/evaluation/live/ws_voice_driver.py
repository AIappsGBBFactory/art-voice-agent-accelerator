#!/usr/bin/env python3
"""
Deployed voice-WebSocket eval driver
====================================

Drives a session-based eval scenario against a *deployed* backend's real voice
WebSocket (``/api/v1/realtime/conversation``) so latency numbers reflect the
deployed environment (real STT -> LLM -> TTS -> first audio), rather than the
in-process orchestrator run on the CI runner.

What it does per scenario:

1. Load a session-based scenario YAML and read ``turns[].user_input``.
2. Synthesize each user turn to base64 PCM16 16 kHz frames via the production
   ``SpeechSynthesizer`` (cached on disk keyed by text hash).
3. Connect to ``wss://<host>/api/v1/realtime/conversation`` with
   ``?session_id=<prefix><scenario>_<uuid>&scenario=<industry>``. The
   ``session_id`` is stamped onto the backend's OpenTelemetry spans, so an
   ``eval_`` prefix makes every span for this run separable in App Insights.
4. Stream the turn's audio (binary PCM frames) + a short trailing silence to
   trigger STT finalization, then capture per turn:
       * ``first_response_ms`` = EOS -> first inbound frame
       * ``first_audio_ms``    = EOS -> first inbound *audio* frame
       * ``response_text``      = best-effort assistant text from inbound frames
       * ``turn_wall_ms``       = EOS -> response considered complete
5. Write a JSON result (per-turn latencies + captured text + the ``session_id``)
   so a downstream trace-grading step can join on ``session.id``.

This driver only *observes* the voice channel. Tool-call / handoff / content
assertions are graded from the ``eval_``-tagged traces in App Insights.

Wire protocol matches ``tests/load/locustfile.browser_conversation.py`` (the
proven ``/realtime/conversation`` driver): one ``AudioMetadata`` JSON frame on
connect, then raw binary PCM16 16 kHz mono frames.

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
import random
import struct
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

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

DEFAULT_WS_PATH = "/api/v1/realtime/conversation"
DEFAULT_SESSION_PREFIX = "eval_"
# Committable cache so CI can drive the deployed WS with zero Azure data-plane
# creds (audio is generated once by a run that can reach Azure Speech).
DEFAULT_CACHE_DIR = Path(__file__).parent / "audio_cache"

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
    ok: bool = False
    error: str | None = None
    turns: list[TurnResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # summary latency rollups (helps the CI gate / trace join)
        firsts = [t.first_audio_ms or t.first_response_ms for t in self.turns]
        firsts = [f for f in firsts if f is not None]
        d["summary"] = {
            "turns": len(self.turns),
            "turns_with_response": sum(1 for t in self.turns if t.first_response_ms is not None),
            "first_audio_ms_avg": round(sum(firsts) / len(firsts), 1) if firsts else None,
            "first_audio_ms_max": round(max(firsts), 1) if firsts else None,
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
    """20 ms of low-level noise (keeps STT VAD engaged for finalization)."""
    return b"".join(struct.pack("<h", random.randint(-18, 18)) for _ in range(FRAME_BYTES // 2))


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
        if result.first_response_ms is None:
            result.first_response_ms = round((now - eos) * 1000.0, 1)

        if isinstance(msg, (bytes, bytearray)):
            # Inbound binary = agent audio.
            result.inbound_kinds["binary_audio"] = result.inbound_kinds.get("binary_audio", 0) + 1
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
        if kind == "AudioData" and result.first_audio_ms is None:
            result.first_audio_ms = round((now - eos) * 1000.0, 1)
        text = _extract_text(frame)
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
    session_prefix: str = DEFAULT_SESSION_PREFIX,
    industry: str | None = None,
    cache_dir: Path | None = None,
    turn_timeout: float = 20.0,
    quiet_gap: float = 2.0,
    first_byte_timeout: float = 12.0,
    inter_turn_pause: float = 1.0,
    bootstrap_appconfig: bool = True,
) -> ScenarioResult:
    """Drive one scenario against the deployed voice WS and return measurements."""
    if bootstrap_appconfig:
        _maybe_bootstrap_appconfig()

    doc = yaml.safe_load(scenario_path.read_text())
    scenario_name = str(doc.get("scenario_name") or scenario_path.stem)
    industry = industry or (doc.get("session_config", {}).get("agent_defaults", {}) or {}).get(
        "industry"
    ) or (doc.get("demo_user", {}) or {}).get("scenario")

    session_id = f"{session_prefix}{scenario_name}_{uuid.uuid4().hex[:8]}"
    ws_url = _to_ws_url(base_url, ws_path)
    query = f"?session_id={session_id}"
    if industry:
        query += f"&scenario={industry}"

    result = ScenarioResult(scenario_name=scenario_name, session_id=session_id, ws_url=ws_url)

    synth = TurnAudioSynth(cache_dir or DEFAULT_CACHE_DIR)
    # Pre-synthesize (fail fast + not counted against turn latency).
    pcm_by_turn: list[tuple[str, str, bytes]] = []
    try:
        for turn_id, user_input in _load_turns(scenario_path):
            pcm_by_turn.append((turn_id, user_input, synth.pcm_for(user_input)))
    except Exception as exc:  # noqa: BLE001 - surface synthesis failures to the caller
        result.error = f"tts_failed: {exc}"
        logger.error("TTS synthesis failed for %s: %s", scenario_name, exc, exc_info=True)
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
        async with websockets.connect(
            ws_url + query,
            additional_headers=headers,
            max_size=None,
            open_timeout=30,
        ) as ws:
            await ws.send(json.dumps(metadata))
            await asyncio.sleep(1.0)  # let the session initialize / greeting settle

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
            session_prefix=args.session_prefix,
            industry=args.industry,
            cache_dir=args.cache_dir,
            turn_timeout=args.turn_timeout,
            quiet_gap=args.quiet_gap,
            first_byte_timeout=args.first_byte_timeout,
            bootstrap_appconfig=not args.no_appconfig,
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
