from __future__ import annotations
"""rtagent_orchestrator
======================
Main orchestration loop for the XYMZ Insurance **RTAgent** real‑time voice bot.

* **Intent routing simplified** – the *authentication* tool  echoes back
  ``intent`` ("claims" | "general") **and** ``claim_intent`` once the caller is

* The specialist agents still retain the ability to switch context later via
  the existing hand‑off mechanism (``handoff: ai_agent``).

"""

from contextlib import asynccontextmanager
import json
import os
from typing import Any, Callable, Dict, TYPE_CHECKING

from fastapi import WebSocket
from apps.rtagent.backend.src.shared_ws import broadcast_message
from utils.ml_logging import get_logger
from utils.trace_context import create_trace_context
from src.enums.monitoring import SpanAttr

if TYPE_CHECKING:  # pragma: no cover
    from src.stateful.state_managment import MemoManager  # noqa: N812 – external camel‑case

logger = get_logger(__name__)

# Performance optimization: Cache tracing configuration
_ORCHESTRATOR_TRACING = os.getenv("ORCHESTRATOR_TRACING", "true").lower() == "true"

def _get_correlation_context(ws: WebSocket, cm: "MemoManager") -> tuple[str, str]:
    """Extract correlation context from WebSocket and MemoManager."""
    call_connection_id = (
        getattr(ws.state, "call_connection_id", None) or
        ws.headers.get("x-call-connection-id") or
        cm.session_id  # fallback to session_id
    )
    session_id = (
        getattr(ws.state, "session_id", None) or
        ws.headers.get("x-session-id") or
        cm.session_id
    )
    return call_connection_id, session_id


def _cm_get(cm: "MemoManager", key: str, default: Any = None) -> Any:
    """Shorthand for ``cm.get_value_from_corememory`` with a default."""
    return cm.get_value_from_corememory(key, default)


def _cm_set(cm: "MemoManager", **kwargs: Dict[str, Any]) -> None:
    """Bulk update core‑memory with ``key=value`` pairs."""
    for k, v in kwargs.items():
        cm.update_corememory(k, v)


@asynccontextmanager
async def track_latency(timer, label: str, redis_mgr):
    """Context‑manager that starts/stops a latency timer and stores the metric."""
    timer.start(label)
    try:
        yield
    finally:
        timer.stop(label, redis_mgr)


async def run_auth_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """Execute the AuthAgent.  If it succeeds, prime routing metadata."""

    if _cm_get(cm, "authenticated", False):
        return

    auth_agent = ws.app.state.auth_agent
    async with track_latency(ws.state.lt, "auth_agent", ws.app.state.redis):
        result: Dict[str, Any] | Any = await auth_agent.respond(cm, utterance, ws, is_acs=is_acs)

    if not (isinstance(result, dict) and result.get("authenticated")):
        return

    # Cache values locally to avoid repeated lookups
    caller_name = result.get("caller_name")
    policy_id = result.get("policy_id")
    call_reason = result.get("call_reason")
    claim_intent = result.get("claim_intent")
    intent = result.get("intent", "general")
    active_agent = "Claims" if intent == "claims" else "General"

    _cm_set(
        cm,
        authenticated=True,
        caller_name=caller_name,
        policy_id=policy_id,
        call_reason=call_reason,
        claim_intent=claim_intent,
        active_agent=active_agent,
    )

    logger.info(
        "✅ Auth OK – session=%s caller=%s policy=%s → %s agent",
        cm.session_id,
        caller_name,
        policy_id,
        active_agent,
    )


# 2.  Specialist agents 

async def run_general_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    agent = ws.app.state.general_info_agent
    caller_name = _cm_get(cm, "caller_name")
    call_reason = _cm_get(cm, "call_reason")
    policy_id = _cm_get(cm, "policy_id")
    async with track_latency(ws.state.lt, "general_agent", ws.app.state.redis):
        resp = await agent.respond(
            cm,
            utterance,
            ws,
            is_acs=is_acs,
            caller_name=caller_name,
            topic=call_reason,
            policy_id=policy_id,
        )
    await _process_tool_response(cm, resp)


async def run_claims_agent(
    cm: "MemoManager",
    utterance: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    agent = ws.app.state.claim_intake_agent
    caller_name = _cm_get(cm, "caller_name")
    claim_intent = _cm_get(cm, "claim_intent")
    policy_id = _cm_get(cm, "policy_id")
    async with track_latency(ws.state.lt, "claim_agent", ws.app.state.redis):
        resp = await agent.respond(
            cm,
            utterance,
            ws,
            is_acs=is_acs,
            caller_name=caller_name,
            claim_intent=claim_intent,
            policy_id=policy_id,
        )
    await _process_tool_response(cm, resp)


def _get_field(resp: Dict[str, Any], key: str) -> Any:  # noqa: D401 – simple util
    """Return ``resp[key]`` or ``resp['data'][key]`` if nested."""
    if key in resp:
        return resp[key]
    return resp.get("data", {}).get(key) if isinstance(resp.get("data"), dict) else None


async def _process_tool_response(cm: "MemoManager", resp: Any) -> None:  # noqa: C901
    """Inspect structured tool outputs and update core‑memory accordingly."""

    if not isinstance(resp, dict):
        return

    handoff_type = _get_field(resp, "handoff")
    target_agent = _get_field(resp, "target_agent")

    # FNOL‑specific outputs
    claim_success = resp.get("claim_success")

    # Primary call reason updates (may come from auth agent or later)
    topic = _get_field(resp, "topic")
    claim_intent = _get_field(resp, "claim_intent")
    intent = _get_field(resp, "intent")

    # ─── Unified intent routing (post‑auth) ─────────────
    if intent in {"claims", "general"} and _cm_get(cm, "authenticated", False):
        new_agent = "Claims" if intent == "claims" else "General"
        _cm_set(cm, active_agent=new_agent, claim_intent=claim_intent, call_reason=topic)
        logger.info("🔀 Routed via intent → %s", new_agent)
        return  # Skip legacy hand‑off logic if present

    # ─── hand‑off (non‑auth transfers) ──────
    if handoff_type == "ai_agent" and target_agent:
        if "Claim" in target_agent:
            _cm_set(cm, active_agent="Claims", claim_intent=claim_intent)
        else:
            _cm_set(cm, active_agent="General", call_reason=topic)
        logger.info("🔀 Hand‑off → %s", _cm_get(cm, "active_agent"))

    elif handoff_type == "human_agent":
        _cm_set(cm, active_agent="HumanEscalation")

    # ─── 3. Claim intake completed ─────────────────────────────
    elif claim_success:
        _cm_set(cm, intake_completed=True, latest_claim_id=resp["claim_id"])


SPECIALIST_MAP: Dict[str, Callable[..., Any]] = {
    "General": run_general_agent,
    "Claims": run_claims_agent,
}


async def route_turn(
    cm: "MemoManager",
    transcript: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """Handle a single user turn end‑to‑end."""

    redis_mgr = ws.app.state.redis
    
    # Broadcast the user input to all connected clients (relay dashboard)
    # This centralizes the broadcast to avoid duplication across different handlers
    try:
        await broadcast_message(ws.app.state.clients, transcript, "User")
    except Exception as e:
        logger.error(f"Failed to broadcast user message: {e}")
    
    try:
        await run_auth_agent(cm, transcript, ws, is_acs=is_acs)

        authenticated = _cm_get(cm, "authenticated", False)
        if not authenticated:
            return

        active_agent = _cm_get(cm, "active_agent")
        if active_agent == "HumanEscalation":
            await ws.send_text(json.dumps({"type": "live_agent_transfer"}))
            return

        active = active_agent if active_agent else "General"
        handler = SPECIALIST_MAP.get(active)
        if handler:
            await handler(cm, transcript, ws, is_acs=is_acs)
        else:
            logger.warning("Unknown active_agent=%s session=%s", active, cm.session_id)

    except Exception:
        logger.exception("💥 route_turn crash – session=%s", cm.session_id)
        raise
    finally:
        await cm.persist_to_redis_async(redis_mgr)