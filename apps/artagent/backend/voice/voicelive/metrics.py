"""
VoiceLive Latency Metrics
=========================

OpenTelemetry metrics for tracking VoiceLive turn latencies.
These metrics show up in Application Insights Performance view for analysis.

IMPORTANT: Metrics are initialized lazily to ensure the MeterProvider is configured
before creating instruments. Call get_meter() only after configure_azure_monitor().
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter
from utils.ml_logging import get_logger

logger = get_logger("voicelive.metrics")

# ═══════════════════════════════════════════════════════════════════════════════
# LAZY METER INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

_meter: Meter | None = None
_llm_ttft_histogram: Histogram | None = None
_tts_ttfb_histogram: Histogram | None = None
_stt_latency_histogram: Histogram | None = None
_turn_duration_histogram: Histogram | None = None
_turn_counter: Counter | None = None


def _ensure_metrics_initialized() -> None:
    """
    Initialize metrics instruments lazily.

    This must be called after configure_azure_monitor() has been invoked,
    otherwise the instruments will use a no-op meter.
    """
    global _meter, _llm_ttft_histogram, _tts_ttfb_histogram
    global _stt_latency_histogram, _turn_duration_histogram, _turn_counter

    if _meter is not None:
        return

    _meter = metrics.get_meter("voicelive.turn.latency", version="1.0.0")

    # LLM Time-To-First-Token (from turn start to first LLM token)
    _llm_ttft_histogram = _meter.create_histogram(
        name="voicelive.llm.ttft",
        description="LLM Time-To-First-Token in milliseconds",
        unit="ms",
    )

    # TTS Time-To-First-Byte (from VAD end to first audio byte - end-to-end latency)
    _tts_ttfb_histogram = _meter.create_histogram(
        name="voicelive.tts.ttfb",
        description="TTS Time-To-First-Byte (E2E latency from VAD end to first audio) in milliseconds",
        unit="ms",
    )

    # STT latency (from VAD end to transcript completion)
    _stt_latency_histogram = _meter.create_histogram(
        name="voicelive.stt.latency",
        description="STT latency from VAD end to transcript completion in milliseconds",
        unit="ms",
    )

    # Total turn duration
    _turn_duration_histogram = _meter.create_histogram(
        name="voicelive.turn.duration",
        description="Total turn duration in milliseconds",
        unit="ms",
    )

    # Turn counter
    _turn_counter = _meter.create_counter(
        name="voicelive.turn.count",
        description="Number of conversation turns processed",
        unit="1",
    )

    logger.info("VoiceLive latency metrics initialized")


# ═══════════════════════════════════════════════════════════════════════════════
# METRIC RECORDING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def record_llm_ttft(
    ttft_ms: float,
    *,
    session_id: str,
    turn_number: int,
    agent_name: str | None = None,
) -> None:
    """
    Record LLM Time-To-First-Token metric.

    :param ttft_ms: Time to first token in milliseconds
    :param session_id: Session identifier for correlation
    :param turn_number: Turn number within the conversation
    :param agent_name: Optional agent name handling the turn
    """
    _ensure_metrics_initialized()

    attributes = {
        "session.id": session_id,
        "turn.number": turn_number,
        "metric.type": "llm_ttft",
    }
    if agent_name:
        attributes["agent.name"] = agent_name

    _llm_ttft_histogram.record(ttft_ms, attributes=attributes)
    logger.info(
        "📊 LLM TTFT metric recorded: %.2fms | session=%s turn=%d agent=%s",
        ttft_ms,
        session_id,
        turn_number,
        agent_name or "unknown",
    )


def record_tts_ttfb(
    ttfb_ms: float,
    *,
    session_id: str,
    turn_number: int,
    reference: str = "vad_end",
    agent_name: str | None = None,
) -> None:
    """
    Record TTS Time-To-First-Byte metric (E2E latency).

    :param ttfb_ms: Time to first audio byte in milliseconds
    :param session_id: Session identifier for correlation
    :param turn_number: Turn number within the conversation
    :param reference: Timing reference point (vad_end or turn_start)
    :param agent_name: Optional agent name handling the turn
    """
    _ensure_metrics_initialized()

    attributes = {
        "session.id": session_id,
        "turn.number": turn_number,
        "metric.type": "tts_ttfb",
        "latency.reference": reference,
    }
    if agent_name:
        attributes["agent.name"] = agent_name

    _tts_ttfb_histogram.record(ttfb_ms, attributes=attributes)
    logger.info(
        "📊 TTS TTFB metric recorded: %.2fms | session=%s turn=%d ref=%s agent=%s",
        ttfb_ms,
        session_id,
        turn_number,
        reference,
        agent_name or "unknown",
    )


def record_stt_latency(
    latency_ms: float,
    *,
    session_id: str,
    turn_number: int,
) -> None:
    """
    Record STT latency metric.

    :param latency_ms: STT latency in milliseconds
    :param session_id: Session identifier for correlation
    :param turn_number: Turn number within the conversation
    """
    _ensure_metrics_initialized()

    attributes = {
        "session.id": session_id,
        "turn.number": turn_number,
        "metric.type": "stt_latency",
    }

    _stt_latency_histogram.record(latency_ms, attributes=attributes)
    logger.info(
        "📊 STT latency metric recorded: %.2fms | session=%s turn=%d",
        latency_ms,
        session_id,
        turn_number,
    )


def record_turn_complete(
    duration_ms: float,
    *,
    session_id: str,
    turn_number: int,
    stt_latency_ms: float | None = None,
    llm_ttft_ms: float | None = None,
    tts_ttfb_ms: float | None = None,
    agent_name: str | None = None,
) -> None:
    """
    Record turn completion with all latency metrics.

    This records the turn duration histogram and increments the turn counter.
    Individual component metrics (STT, LLM, TTS) should be recorded separately
    when they occur for more accurate timing.

    :param duration_ms: Total turn duration in milliseconds
    :param session_id: Session identifier for correlation
    :param turn_number: Turn number within the conversation
    :param stt_latency_ms: Optional STT latency for the turn
    :param llm_ttft_ms: Optional LLM TTFT for the turn
    :param tts_ttfb_ms: Optional TTS TTFB for the turn
    :param agent_name: Optional agent name handling the turn
    """
    _ensure_metrics_initialized()

    base_attributes = {
        "session.id": session_id,
        "turn.number": turn_number,
    }
    if agent_name:
        base_attributes["agent.name"] = agent_name

    # Record turn duration
    _turn_duration_histogram.record(
        duration_ms,
        attributes={
            **base_attributes,
            "metric.type": "turn_duration",
        },
    )

    # Increment turn counter
    _turn_counter.add(1, attributes=base_attributes)

    # Log summary
    logger.info(
        "📊 Turn complete metric: duration=%.2fms stt=%s llm=%s tts=%s | session=%s turn=%d",
        duration_ms,
        f"{stt_latency_ms:.2f}ms" if stt_latency_ms else "N/A",
        f"{llm_ttft_ms:.2f}ms" if llm_ttft_ms else "N/A",
        f"{tts_ttfb_ms:.2f}ms" if tts_ttfb_ms else "N/A",
        session_id,
        turn_number,
    )


# Accessor functions for histogram/counter access (if needed externally)
def get_llm_ttft_histogram() -> Histogram | None:
    """Get the LLM TTFT histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _llm_ttft_histogram


def get_tts_ttfb_histogram() -> Histogram | None:
    """Get the TTS TTFB histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _tts_ttfb_histogram


def get_stt_latency_histogram() -> Histogram | None:
    """Get the STT latency histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _stt_latency_histogram


def get_turn_duration_histogram() -> Histogram | None:
    """Get the turn duration histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _turn_duration_histogram


def get_turn_counter() -> Counter | None:
    """Get the turn counter after ensuring initialization."""
    _ensure_metrics_initialized()
    return _turn_counter


__all__ = [
    "record_llm_ttft",
    "record_tts_ttfb",
    "record_stt_latency",
    "record_turn_complete",
]
