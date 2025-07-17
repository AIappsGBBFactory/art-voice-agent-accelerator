"""
tools_helper.py

Single source of truth for
 • callable-name → python-function mapping
 • JSON frames that announce tool_start / tool_progress / tool_end
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Dict

from fastapi import WebSocket
from rtagents.RTMedAgent.backend.agents.tool_store.auth import authenticate_user
from rtagents.RTMedAgent.backend.agents.tool_store.billing import (
    insurance_billing_question,
)
from rtagents.RTMedAgent.backend.agents.tool_store.emergency import escalate_emergency
from rtagents.RTMedAgent.backend.agents.tool_store.general_health import (
    general_health_question,
)
from rtagents.RTMedAgent.backend.agents.tool_store.handoff import handoff_agent
from rtagents.RTMedAgent.backend.agents.tool_store.medications import (
    check_drug_interactions,
    fill_new_prescription,
    get_current_prescriptions,
    lookup_medication_info,
    lookup_side_effects,
    refill_prescription,
)
from rtagents.RTMedAgent.backend.agents.tool_store.referrals import (
    check_referral_status,
    get_specialist_list,
    request_referral,
)
from rtagents.RTMedAgent.backend.agents.tool_store.scheduling import (
    cancel_appointment,
    change_appointment,
    get_upcoming_appointments,
    schedule_appointment,
)

from utils.ml_logging import get_logger

log = get_logger("tools_helper")

# --------------------------------------------------------------------------- #
#  public mapping {openai_tool_name: python_callable}
# --------------------------------------------------------------------------- #
function_mapping: Dict[str, Callable[..., Any]] = {
    "schedule_appointment": schedule_appointment,
    "change_appointment": change_appointment,
    "cancel_appointment": cancel_appointment,
    "get_upcoming_appointments": get_upcoming_appointments,
    "refill_prescription": refill_prescription,
    "fill_new_prescription": fill_new_prescription,
    "get_current_prescriptions": get_current_prescriptions,
    "lookup_medication_info": lookup_medication_info,
    "lookup_side_effects": lookup_side_effects,
    "check_drug_interactions": check_drug_interactions,
    "escalate_emergency": escalate_emergency,
    "authenticate_user": authenticate_user,
    "general_health_question": general_health_question,
    "insurance_billing_question": insurance_billing_question,
    "request_referral": request_referral,
    "get_specialist_list": get_specialist_list,
    "check_referral_status": check_referral_status,
    "handoff_agent": handoff_agent,
}


async def call_agent_tool(tool_name: str, args: dict) -> Any:
    fn = function_mapping.get(tool_name)
    if fn is None:
        log.error(f"No function mapped for tool '{tool_name}'")
        return {"ok": False, "message": f"Tool '{tool_name}' not supported."}
    try:
        result = await fn(args)
        return result
    except Exception as e:
        log.exception(f"Error running tool '{tool_name}'")
        return {"ok": False, "message": str(e)}


async def _emit(ws: WebSocket, payload: dict, *, is_acs: bool) -> None:
    """
    • browser `/realtime`  → send JSON directly on that socket
    • phone   `/call/*`    → fan-out to every dashboard on `/relay`

    IMPORTANT: we forward the *raw* JSON (no additional wrapper) so that the
               front-end can treat both transports identically.
    """
    frame = json.dumps(payload)

    if is_acs:
        # never block STT/TTS – fire-and-forget
        for cli in set(ws.app.state.clients):
            asyncio.create_task(cli.send_text(frame))
    else:
        await ws.send_text(frame)


def _frame(
    _type: str,
    call_id: str,
    name: str,
    **extra: Any,
) -> dict:
    return {
        "type": _type,
        "callId": call_id,
        "tool": name,
        "ts": time.time(),
        **extra,
    }


async def push_tool_start(
    ws: WebSocket,
    call_id: str,
    name: str,
    args: dict,
    *,
    is_acs: bool = False,
) -> None:
    await _emit(ws, _frame("tool_start", call_id, name, args=args), is_acs=is_acs)


async def push_tool_progress(
    ws: WebSocket,
    call_id: str,
    name: str,
    pct: int,
    note: str | None = None,
    *,
    is_acs: bool = False,
) -> None:
    await _emit(
        ws, _frame("tool_progress", call_id, name, pct=pct, note=note), is_acs=is_acs
    )


async def push_tool_end(
    ws: WebSocket,
    call_id: str,
    name: str,
    status: str,  # "success" | "error"
    elapsed_ms: float,
    *,
    result: dict | None = None,
    error: str | None = None,
    is_acs: bool = False,
) -> None:
    await _emit(
        ws,
        _frame(
            "tool_end",
            call_id,
            name,
            status=status,
            elapsedMs=round(elapsed_ms, 1),
            result=result,
            error=error,
        ),
        is_acs=is_acs,
    )
