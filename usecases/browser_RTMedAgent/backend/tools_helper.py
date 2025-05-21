"""
tools_helper.py

This module provides helper functions and mappings for managing tool execution and communication
between the backend and frontend via WebSocket in the browser_RTMedAgent use case.

"""
import json
import time
from typing import Any, Callable, Dict

from fastapi import WebSocket
from usecases.browser_RTMedAgent.backend.functions import (
    authenticate_user,
    check_drug_interactions,
    escalate_emergency,
    evaluate_prior_authorization,
    fill_new_prescription,
    get_current_prescriptions,
    lookup_medication_info,
    lookup_side_effects,
    refill_prescription,
    schedule_appointment,
)

# --- Init Logger ---
from utils.ml_logging import get_logger

logger = get_logger()

function_mapping: Dict[str, Callable[..., Any]] = {
    "schedule_appointment": schedule_appointment,
    "refill_prescription": refill_prescription,
    "lookup_medication_info": lookup_medication_info,
    "evaluate_prior_authorization": evaluate_prior_authorization,
    "escalate_emergency": escalate_emergency,
    "authenticate_user": authenticate_user,
    "fill_new_prescription": fill_new_prescription,
    "lookup_side_effects": lookup_side_effects,
    "get_current_prescriptions": get_current_prescriptions,
    "check_drug_interactions": check_drug_interactions,
}


async def push_tool_start(
    ws: WebSocket,
    call_id: str,
    name: str,
    args: dict,
) -> None:
    """Notify UI that a tool just kicked off."""
    await ws.send_text(
        json.dumps(
            {
                "type": "tool_start",
                "callId": call_id,
                "tool": name,
                "args": args,  # keep it PHI-free
                "ts": time.time(),
            }
        )
    )


async def push_tool_progress(
    ws: WebSocket,
    call_id: str,
    pct: int,
    note: str | None = None,
) -> None:
    """Optional: stream granular progress for long-running tools."""
    await ws.send_text(
        json.dumps(
            {
                "type": "tool_progress",
                "callId": call_id,
                "pct": pct,  # 0-100
                "note": note,
                "ts": time.time(),
            }
        )
    )


async def push_tool_end(
    ws: WebSocket,
    call_id: str,
    name: str,
    status: str,
    elapsed_ms: float,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Finalise the life-cycle (status = success|error)."""
    await ws.send_text(
        json.dumps(
            {
                "type": "tool_end",
                "callId": call_id,
                "tool": name,
                "status": status,
                "elapsedMs": round(elapsed_ms, 1),
                "result": result,
                "error": error,
                "ts": time.time(),
            }
        )
    )
