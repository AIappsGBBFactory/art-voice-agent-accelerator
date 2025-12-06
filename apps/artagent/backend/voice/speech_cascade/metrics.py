"""
Speech Cascade Metrics
======================

OpenTelemetry metrics for tracking Speech Cascade latencies.
These metrics show up in Application Insights Performance view for analysis.

Metrics tracked:
- STT recognition latency (first partial to final)
- Turn processing latency
- Barge-in detection latency

IMPORTANT: Metrics are initialized lazily to ensure the MeterProvider is configured
before creating instruments. Call get_meter() only after configure_azure_monitor().
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter
from utils.ml_logging import get_logger

logger = get_logger("speech_cascade.metrics")

# ═══════════════════════════════════════════════════════════════════════════════
# LAZY METER INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

_meter: Meter | None = None
_stt_recognition_histogram: Histogram | None = None
_turn_processing_histogram: Histogram | None = None
_barge_in_histogram: Histogram | None = None
_turn_counter: Counter | None = None
_barge_in_counter: Counter | None = None


def _ensure_metrics_initialized() -> None:
    """
    Initialize metrics instruments lazily.

    This must be called after configure_azure_monitor() has been invoked,
    otherwise the instruments will use a no-op meter.
    """
    global _meter, _stt_recognition_histogram, _turn_processing_histogram
    global _barge_in_histogram, _turn_counter, _barge_in_counter

    if _meter is not None:
        return

    _meter = metrics.get_meter("speech_cascade.latency", version="1.0.0")

    # STT Recognition latency (first partial to final)
    _stt_recognition_histogram = _meter.create_histogram(
        name="speech_cascade.stt.recognition",
        description="STT recognition latency from first partial to final in milliseconds",
        unit="ms",
    )

    # Turn processing latency (user speech end to response start)
    _turn_processing_histogram = _meter.create_histogram(
        name="speech_cascade.turn.processing",
        description="Turn processing latency in milliseconds",
        unit="ms",
    )

    # Barge-in detection latency
    _barge_in_histogram = _meter.create_histogram(
        name="speech_cascade.barge_in.latency",
        description="Barge-in detection latency in milliseconds",
        unit="ms",
    )

    # Turn counter
    _turn_counter = _meter.create_counter(
        name="speech_cascade.turn.count",
        description="Number of conversation turns processed",
        unit="1",
    )

    # Barge-in counter
    _barge_in_counter = _meter.create_counter(
        name="speech_cascade.barge_in.count",
        description="Number of barge-in events detected",
        unit="1",
    )

    logger.info("Speech Cascade latency metrics initialized")


# ═══════════════════════════════════════════════════════════════════════════════
# METRIC RECORDING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def record_stt_recognition(
    latency_ms: float,
    *,
    session_id: str,
    call_connection_id: str | None = None,
    turn_number: int | None = None,
    transcript_length: int | None = None,
) -> None:
    """
    Record STT recognition latency metric.

    This measures the time from first meaningful partial to final recognition.

    :param latency_ms: Recognition latency in milliseconds
    :param session_id: Session identifier for correlation
    :param call_connection_id: Call connection ID
    :param turn_number: Turn number within the conversation
    :param transcript_length: Length of final transcript in characters
    """
    _ensure_metrics_initialized()

    attributes = {
        "session.id": session_id,
        "metric.type": "stt_recognition",
    }
    if call_connection_id:
        attributes["call.connection.id"] = call_connection_id
    if turn_number is not None:
        attributes["turn.number"] = turn_number
    if transcript_length is not None:
        attributes["transcript.length"] = transcript_length

    _stt_recognition_histogram.record(latency_ms, attributes=attributes)
    logger.debug("📊 STT recognition metric: %.2fms | session=%s", latency_ms, session_id)


def record_turn_processing(
    latency_ms: float,
    *,
    session_id: str,
    call_connection_id: str | None = None,
    turn_number: int | None = None,
    has_tool_calls: bool = False,
) -> None:
    """
    Record turn processing latency metric.

    :param latency_ms: Processing latency in milliseconds
    :param session_id: Session identifier for correlation
    :param call_connection_id: Call connection ID
    :param turn_number: Turn number within the conversation
    :param has_tool_calls: Whether the turn included tool calls
    """
    _ensure_metrics_initialized()

    attributes = {
        "session.id": session_id,
        "metric.type": "turn_processing",
        "has_tool_calls": has_tool_calls,
    }
    if call_connection_id:
        attributes["call.connection.id"] = call_connection_id
    if turn_number is not None:
        attributes["turn.number"] = turn_number

    _turn_processing_histogram.record(latency_ms, attributes=attributes)
    _turn_counter.add(1, attributes={"session.id": session_id})

    logger.debug(
        "📊 Turn processing metric: %.2fms | session=%s tools=%s",
        latency_ms,
        session_id,
        has_tool_calls,
    )


def record_barge_in(
    latency_ms: float,
    *,
    session_id: str,
    call_connection_id: str | None = None,
    trigger: str = "partial",
    tts_was_playing: bool = True,
) -> None:
    """
    Record barge-in detection latency metric.

    :param latency_ms: Detection latency in milliseconds
    :param session_id: Session identifier for correlation
    :param call_connection_id: Call connection ID
    :param trigger: What triggered the barge-in (partial, energy, etc.)
    :param tts_was_playing: Whether TTS was actively playing
    """
    _ensure_metrics_initialized()

    attributes = {
        "session.id": session_id,
        "metric.type": "barge_in",
        "barge_in.trigger": trigger,
        "tts_was_playing": tts_was_playing,
    }
    if call_connection_id:
        attributes["call.connection.id"] = call_connection_id

    _barge_in_histogram.record(latency_ms, attributes=attributes)
    _barge_in_counter.add(
        1,
        attributes={
            "session.id": session_id,
            "barge_in.trigger": trigger,
        },
    )

    logger.debug(
        "📊 Barge-in metric: %.2fms | session=%s trigger=%s", latency_ms, session_id, trigger
    )


# Accessor functions for histogram/counter access (if needed externally)
def get_stt_recognition_histogram() -> Histogram | None:
    """Get the STT recognition histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _stt_recognition_histogram


def get_turn_processing_histogram() -> Histogram | None:
    """Get the turn processing histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _turn_processing_histogram


def get_barge_in_histogram() -> Histogram | None:
    """Get the barge-in histogram after ensuring initialization."""
    _ensure_metrics_initialized()
    return _barge_in_histogram


__all__ = [
    "record_stt_recognition",
    "record_turn_processing",
    "record_barge_in",
]
