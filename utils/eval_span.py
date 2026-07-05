# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License in the project root for
# license information.
# --------------------------------------------------------------------------
"""
Eval-ready span content annotation.

Attaches GenAI message content (``gen_ai.input.messages`` /
``gen_ai.output.messages``) to the ``invoke_agent`` span so that Azure AI
Foundry **trace evaluation** can grade real conversations directly from the
connected Application Insights — without replaying synthetic scenarios or
building a separate dataset. Foundry reads these attributes natively; see
https://learn.microsoft.com/azure/foundry/how-to/develop/cloud-evaluation#trace-evaluation-preview

Privacy-first defaults
----------------------
Content capture is **OFF by default**. The voice pipeline handles regulated
data (SSNs, financial account/routing numbers, caller IDs), so message content
is never written to traces unless explicitly opted in.

Environment variables
----------------------
- ``EVAL_SPAN_CONTENT_ENABLED`` (default ``false``): master switch. When false
  this module is a no-op.
- ``EVAL_SPAN_CONTENT_RAW`` (default ``false``): when true, content is attached
  *without* PII scrubbing. NOT recommended for production or regulated data.
  When false (default), all content is scrubbed via :mod:`utils.pii_filter`.
- ``EVAL_SPAN_CONTENT_MAX_CHARS`` (default ``8000``): per-field character cap to
  bound span size / telemetry egress.

Attributes emitted
-------------------
These are exactly the attributes Azure AI Foundry **trace evaluation** reads
from ``invoke_agent`` spans (see
https://learn.microsoft.com/azure/foundry/how-to/develop/cloud-evaluation#trace-evaluation-preview).
Foundry derives ``query``/``response``/``tool_calls`` from these message arrays,
so no extra custom fields are needed:

- ``gen_ai.input.messages``  — JSON array with the latest user query (not the
  full history: each turn has its own span, joinable by ``session.id``)
- ``gen_ai.output.messages`` — JSON array with the assistant response
- ``eval.content.scrubbed``  — bool flag indicating whether scrubbing was applied
"""

from __future__ import annotations

import json
import os
from typing import Any

from utils.ml_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_MAX_CHARS = 8000


def _bool_env(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def is_eval_content_enabled() -> bool:
    """Return True if eval span content capture is enabled.

    Content capture is **off by default**, matching the OpenTelemetry / Azure
    GenAI instrumentation convention (message content is opt-in because it can
    contain PII, and this app handles regulated data). Enable via either:

    - ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`` — the standard
      OTel/Azure GenAI content-capture flag (honored so this integrates with
      the rest of an Azure tracing setup rather than being a bespoke switch), or
    - ``EVAL_SPAN_CONTENT_ENABLED`` — the app-specific override.

    Span *structure* (``gen_ai.operation.name``, ``gen_ai.agent.name/id``) is
    always emitted regardless of this flag; only the conversation content is
    gated.
    """
    return _bool_env("EVAL_SPAN_CONTENT_ENABLED", False) or _bool_env(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", False
    )


def _max_chars() -> int:
    try:
        return int(os.getenv("EVAL_SPAN_CONTENT_MAX_CHARS", str(_DEFAULT_MAX_CHARS)))
    except ValueError:
        return _DEFAULT_MAX_CHARS


def _scrub(text: str) -> str:
    """Scrub PII from text unless raw capture is explicitly enabled."""
    if _bool_env("EVAL_SPAN_CONTENT_RAW", False):
        return text
    # Lazy import so the scrubber is only loaded when content capture is on.
    from utils.pii_filter import scrub_pii

    return scrub_pii(text)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _last_user_content(messages: list[dict[str, Any]]) -> str:
    """Return the most recent user message content (the evaluator query).

    Only the latest user turn is captured — not the full history — because each
    turn emits its own span (joinable by ``session.id``), so re-serializing the
    growing conversation on every span is redundant and would scale O(n^2) over
    a long call.
    """
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        return content
    return ""


def _prepare_input(messages: list[dict[str, Any]], limit: int) -> str | None:
    """Serialize the latest user query to a truncated-then-scrubbed JSON string."""
    query = _last_user_content(messages)
    if not query:
        return None
    # Truncate BEFORE scrubbing so regex work is bounded by ``limit``, not by
    # however large the raw content is.
    payload = [{"role": "user", "content": _scrub(_truncate(query, limit))}]
    return _truncate(json.dumps(payload, default=str), limit)


def annotate_eval_content(
    span: Any,
    *,
    input_messages: list[dict[str, Any]] | None = None,
    output_text: str | None = None,
) -> None:
    """Attach eval-ready GenAI content to an ``invoke_agent`` span.

    Safe to call unconditionally on the hot path: returns immediately when
    capture is disabled and never raises (telemetry must not break a call).

    Foundry trace evaluation derives ``query``/``response``/``tool_calls`` from
    the ``gen_ai.input.messages`` / ``gen_ai.output.messages`` arrays, so only
    those two are emitted.

    Args:
        span: The ``invoke_agent`` span to annotate. Ignored if ``None`` or not
            recording. (Foundry only reads spans where
            ``gen_ai.operation.name == "invoke_agent"``.)
        input_messages: Conversation messages sent to the model. The last user
            message is captured as the evaluator query.
        output_text: The assistant's response text for this turn.
    """
    if span is None or not is_eval_content_enabled():
        return

    try:
        # Some spans (NonRecordingSpan) lack is_recording; guard defensively.
        is_recording = getattr(span, "is_recording", None)
        if callable(is_recording) and not span.is_recording():
            return

        limit = _max_chars()
        scrubbed = not _bool_env("EVAL_SPAN_CONTENT_RAW", False)
        span.set_attribute("eval.content.scrubbed", scrubbed)

        if input_messages:
            prepared_input = _prepare_input(input_messages, limit)
            if prepared_input:
                span.set_attribute("gen_ai.input.messages", prepared_input)

        if output_text:
            output_payload = [{"role": "assistant", "content": _scrub(_truncate(output_text, limit))}]
            span.set_attribute(
                "gen_ai.output.messages",
                _truncate(json.dumps(output_payload, default=str), limit),
            )
    except Exception as exc:  # pragma: no cover - telemetry must never break a call
        logger.debug("annotate_eval_content skipped due to error: %s", exc)
