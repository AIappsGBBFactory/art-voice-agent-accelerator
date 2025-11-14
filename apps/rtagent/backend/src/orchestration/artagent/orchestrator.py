from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Tuple

from fastapi import WebSocket
from opentelemetry import trace

from .auth import run_auth_agent
from .cm_utils import cm_get, cm_set, get_correlation_context
from .config import ENTRY_AGENT
from .registry import (
    get_specialist,
    register_specialist,
)
from .specialists import run_fraud_agent, run_agency_agent, run_compliance_agent, run_trading_agent
from .termination import maybe_terminate_if_escalated
from apps.rtagent.backend.src.ws_helpers.envelopes import make_envelope
from apps.rtagent.backend.src.ws_helpers.shared_ws import broadcast_message, send_session_envelope
from apps.rtagent.backend.src.utils.tracing import (
    create_service_handler_attrs,
    create_service_dependency_attrs,
)
from utils.ml_logging import get_logger

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager


# -------------------------------------------------------------
# Public entry-point (per user turn)
# -------------------------------------------------------------
async def route_turn(
    cm: "MemoManager",
    transcript: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """Handle **one** user turn plus any immediate follow-ups.

    Responsibilities:
    * Broadcast the user message to supervisor dashboards.
    * Run the authentication agent until success.
    * Delegate to the correct specialist agent.
    * Detect when a live human transfer is required.
    * Persist conversation state to Redis for resilience.
    * Create a per-turn run_id and group all stage latencies under it.
    """
    if cm is None:
        logger.error("❌ MemoManager (cm) is None - cannot process orchestration")
        raise ValueError("MemoManager (cm) parameter cannot be None")

    # Extract correlation context
    call_connection_id, session_id = get_correlation_context(ws, cm)

    # Ensure we start a per-turn latency run and expose the id in CoreMemory
    try:
        run_id = ws.state.lt.begin_run(label="turn")  # new LatencyTool (v2)
        # pin it as "current run" for subsequent start/stop calls in this turn
        if hasattr(ws.state.lt, "set_current_run"):
            ws.state.lt.set_current_run(run_id)
    except Exception:
        # fallback to a locally generated id if the tool doesn't support begin_run
        run_id = uuid.uuid4().hex[:12]
    cm_set(cm, current_run_id=run_id)

    # Initialize session with configured entry agent if no active_agent is set
    if (
        not cm_get(cm, "authenticated", False)
        and cm_get(cm, "active_agent") != ENTRY_AGENT
    ):
        cm_set(cm, active_agent=ENTRY_AGENT)

    # Create handler span for orchestrator service
    span_attrs = create_service_handler_attrs(
        service_name="orchestrator",
        call_connection_id=call_connection_id,
        session_id=session_id,
        operation="route_turn",
        transcript_length=len(transcript),
        is_acs=is_acs,
        authenticated=cm_get(cm, "authenticated", False),
        active_agent=cm_get(cm, "active_agent", "none"),
    )
    # include run.id in the span
    span_attrs["run.id"] = run_id

    with tracer.start_as_current_span(
        "orchestrator.route_turn", attributes=span_attrs
    ) as span:
        redis_mgr = ws.app.state.redis

        try:
            # 1) Unified escalation check (for *any* agent)
            if await maybe_terminate_if_escalated(cm, ws, is_acs=is_acs):
                return

            # 2) Dispatch to agent (AutoAuth or specialists; registry-backed)
            active: str = cm_get(cm, "active_agent") or ENTRY_AGENT
            span.set_attribute("orchestrator.stage", "specialist_dispatch")
            span.set_attribute("orchestrator.target_agent", active)
            span.set_attribute("run.id", run_id)

            handler = get_specialist(active)
            if handler is None:
                logger.warning(
                    "Unknown active_agent=%s session=%s", active, cm.session_id
                )
                span.set_attribute("orchestrator.error", "unknown_agent")
                return

            agent_attrs = create_service_dependency_attrs(
                source_service="orchestrator",
                target_service=active.lower() + "_agent",
                call_connection_id=call_connection_id,
                session_id=session_id,
                operation="process_turn",
                transcript_length=len(transcript),
            )
            agent_attrs["run.id"] = run_id

            with tracer.start_as_current_span(
                f"orchestrator.call_{active.lower()}_agent", attributes=agent_attrs
            ):
                await handler(cm, transcript, ws, is_acs=is_acs)

                # 3) After any agent runs, if escalation flag was set during the turn, terminate.
                if await maybe_terminate_if_escalated(cm, ws, is_acs=is_acs):
                    return

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("💥 route_turn crash – session=%s", cm.session_id)
            span.set_attribute("orchestrator.error", "exception")
            try:
                await _emit_orchestrator_error_status(ws, cm, exc)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.debug("Failed to emit orchestrator error status", exc_info=True)
            raise
        finally:
            # Ensure core-memory is persisted even if a downstream component failed.
            await cm.persist_to_redis_async(redis_mgr)



def bind_default_handlers() -> None:
    """
    Register default agent handlers for Financial Services multi-agent system.
    
    Flow: Auth -> (Fraud | Agency) -> (Compliance | Trading)
    """
    # Entry point agent 
    register_specialist("AutoAuth", run_auth_agent)
    
    # Main service agents (post-authentication routing)
    register_specialist("Fraud", run_fraud_agent)        # ← Fraud detection & dispute resolution
    register_specialist("Agency", run_agency_agent)      # ← Transfer Agency coordinator
    
    # Transfer Agency specialists (receive handoffs from Agency)
    register_specialist("Compliance", run_compliance_agent)  # ← AML/FATCA verification
    register_specialist("Trading", run_trading_agent)       # ← Complex trade execution
    

def _summarize_orchestrator_exception(exc: Exception) -> Tuple[str, str, str]:
    """Return user-friendly message, caption, and tone for frontend display."""
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()

    if "responsibleaipolicyviolation" in lowered or "content_filter" in lowered:
        return (
            "🚫 Response blocked by content policy",
            "Azure OpenAI flagged the last response. Try rephrasing or adjusting the prompt.",
            "warning",
        )

    if "badrequest" in lowered or "400" in lowered:
        excerpt = text[:220]
        return (
            "⚠️ Assistant could not complete the request",
            excerpt,
            "warning",
        )

    excerpt = text[:220]
    return (
        "❌ Assistant ran into an unexpected error",
        excerpt,
        "error",
    )


async def _emit_orchestrator_error_status(ws: WebSocket, cm: "MemoManager", exc: Exception) -> None:
    """Send a structured status envelope to the frontend describing orchestrator failures."""
    message, caption, tone = _summarize_orchestrator_exception(exc)

    session_id = getattr(cm, "session_id", None) or getattr(ws.state, "session_id", None)
    call_id = getattr(ws.state, "call_connection_id", None) or getattr(cm, "call_connection_id", None)
    envelope = make_envelope(
        etype="status",
        sender="System",
        payload={
            "message": message,
            "statusTone": tone,
            "statusCaption": caption,
        },
        topic="session",
        session_id=session_id,
        call_id=call_id,
    )

    await send_session_envelope(
        ws,
        envelope,
        session_id=session_id,
        conn_id=getattr(ws.state, "conn_id", None),
        event_label="orchestrator_error",
        broadcast_only=False,
    )

