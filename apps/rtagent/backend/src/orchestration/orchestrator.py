from __future__ import annotations

"""First‑Notice‑of‑Loss (FNOL) router – typed revision.

Two‑stage conversational flow:

1. **AuthAgent** – verifies caller identity.
2. **FNOLIntakeAgent** – records the claim details.

Assumes a :class:`MemoManager` instance keeps per‑session state in *corememory*
under keys:

* ``authenticated: bool`` – gate between stages.
* ``caller_name: str`` and ``policy_id: str`` – set by *AuthAgent*.
* ``intake_completed: bool`` – set after successful FNOL intake.
"""

import json
from typing import Any, Dict, TYPE_CHECKING

from fastapi import WebSocket

from utils.ml_logging import get_logger

if TYPE_CHECKING:  # pragma: no cover – typing‑only imports
    from src.stateful.state_managment import MemoManager  # noqa: F401

logger = get_logger("fnol_route")

# ---------------------------------------------------------------------------
# Helper wrappers – thin, typed accessors to MemoManager
# ---------------------------------------------------------------------------


def _cm_get(cm: "MemoManager", key: str, default: Any = None) -> Any:  # noqa: D401
    """Typed shortcut to *corememory* getter."""
    return cm.get_value_from_corememory(key, default)


def _cm_set(cm: "MemoManager", **kwargs: Dict[str, Any]) -> None:  # noqa: D401
    """Batch update helper for *corememory*."""
    for k, v in kwargs.items():
        cm.update_corememory(k, v)


# ---------------------------------------------------------------------------
# Route turn entry‑point
# ---------------------------------------------------------------------------
async def route_turn(  # noqa: D401, PLR0913 – many params by FastAPI design
    cm: "MemoManager",
    transcript: str,
    ws: WebSocket,
    *,
    is_acs: bool,
) -> None:
    """Handle a single user *turn* in the FNOL flow.

    Args:
        cm: Active :class:`MemoManager` for this session.
        transcript: Latest user utterance text.
        ws: WebSocket connection to caller.
        is_acs: ``True`` if routed via Azure Communication Services.
    """

    redis_mgr = ws.app.state.redis
    latency_tool = ws.state.lt

    # ------------------------------------------------------------------
    # Stage 1 – Authentication
    # ------------------------------------------------------------------
    if not _cm_get(cm, "authenticated", False):
        latency_tool.start("auth_agent")
        auth_agent = ws.app.state.auth_agent  # type: ignore[attr-defined]
        result = await auth_agent.respond(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop("auth_agent", redis_mgr)

        if isinstance(result, dict) and result.get("authenticated"):
            _cm_set(
                cm,
                authenticated=True,
                caller_name=result.get("caller_name"),
                policy_id=result.get("policy_id"),
            )
            logger.info(
                "✅ Session %s authenticated – %s / %s",
                cm.session_id,
                result.get("caller_name"),
                result.get("policy_id"),
            )
        else:
            # AuthAgent already handled retries/prompts – just persist and exit.
            cm.persist_to_redis(redis_mgr)
            return

    # ------------------------------------------------------------------
    # Stage 2 – FNOL intake
    # ------------------------------------------------------------------
    fnol_agent = ws.app.state.claim_intake_agent  # type: ignore[attr-defined]
    latency_tool.start("fnol_agent")
    result = await fnol_agent.respond(cm, transcript, ws, is_acs=is_acs)
    latency_tool.stop("fnol_agent", redis_mgr)

    if isinstance(result, dict) and result.get("claim_success"):
        claim_id: str = result["claim_id"]
        _cm_set(cm, intake_completed=True)
        logger.info("📄 FNOL completed – %s – session %s", claim_id, cm.session_id)
        await ws.send_text(
            json.dumps({"type": "claim_submitted", "claim_id": claim_id})
        )
        # Optionally close the socket here (caller may prefer to hang up).
        # await ws.close(code=1000)

    # ------------------------------------------------------------------
    # Persist session state at end of turn
    # ------------------------------------------------------------------
    cm.persist_to_redis(redis_mgr)
