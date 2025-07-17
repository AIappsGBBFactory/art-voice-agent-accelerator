# routes/fnol_route.py
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import WebSocket
from rtagents.RTInsuranceAgent.backend.agents.tool_store.fnol import claims_db
from rtagents.RTInsuranceAgent.backend.agents.tool_store.report_builder import (
    generate_claim_report,
)

# builds .docx
from rtagents.RTInsuranceAgent.backend.postcall.push_claims import (
    fetch_claim_record,
    persist_claim_record,
)

from utils.ml_logging import get_logger

logger = get_logger("fnol_route")


async def route_turn(cm, transcript: str, ws: WebSocket, *, is_acs: bool) -> None:
    """
    Two-stage FNOL flow:
        1) authenticate_caller  (AuthAgent)
        2) record_fnol          (FNOLIntakeAgent)
    After a successful FNOL record the websocket is closed by the caller.
    """
    redis_mgr = ws.app.state.redis
    latency_tool = ws.state.lt

    if not cm.get_context("authenticated", False):
        latency_tool.start("auth_agent")
        auth_agent = getattr(ws.app.state, "auth_agent")
        result = await auth_agent.respond(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop("auth_agent", redis_mgr)

        if isinstance(result, dict) and result.get("authenticated"):
            cm.update_context("authenticated", True)
            cm.update_context("caller_name", result["caller_name"])
            cm.update_context("policy_id", result["policy_id"])
            logger.info(
                f"✅ Session {cm.session_id} authenticated for "
                f"{result['caller_name']} / {result['policy_id']}"
            )
        else:
            # AuthAgent handles retry messaging itself; just persist state.
            cm.persist_to_redis(redis_mgr)
            return
    else:
        fnol_agent = getattr(ws.app.state, "claim_intake_agent")
        latency_tool.start("fnol_agent")
        result = await fnol_agent.respond(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop("fnol_agent", redis_mgr)

        if isinstance(result, dict) and result.get("claim_success"):
            # Intake finished → mark and logger
            cm.update_context("intake_completed", True)
            claim_id = result["claim_id"]
            # Build Word report
            claim_record = claims_db[-1]
            claim_record.update(
                {
                    "session_id": cm.session_id,
                }
            )
            report_path: Path = generate_claim_report(claim_record)
            logger.info("📄 FNOL recorded (%s); report at %s", claim_id, report_path)
            cosmos_mgr = getattr(ws.app.state, "cosmos", None)
            # Push to Cosmos DB if manager provided
            if cosmos_mgr:
                persist_claim_record(cosmos_mgr, claim_record, report_path)
            logger.info(f"📄 FNOL completed – {claim_id} – " f"session {cm.session_id}")
            await ws.send_text(
                json.dumps(
                    {
                        "type": "claim_submitted",
                        "claim_id": claim_id,
                    }
                )
            )
            # await ws.close(code=1000)

    cm.persist_to_redis(redis_mgr)
