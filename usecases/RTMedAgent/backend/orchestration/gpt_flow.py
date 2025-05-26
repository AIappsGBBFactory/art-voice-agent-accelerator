# orchestration/gpt_flow.py
# ========================
"""
All OpenAI-streaming + tool plumbing in one place.

Public API
----------
process_gpt_response()  – stream GPT → TTS (+ tools)
route_turn()            – single user turn (auth ⇆ main)
"""
from __future__ import annotations

import asyncio, json, time, uuid
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from usecases.RTMedAgent.backend.services.openai_services import client as az_openai_client
from utils.ml_logging import get_logger
from usecases.RTMedAgent.backend.latency.latency_tool import LatencyTool
from usecases.RTMedAgent.backend.settings import (
    AZURE_OPENAI_CHAT_DEPLOYMENT_ID,
    TTS_END,
)
from usecases.RTMedAgent.backend.helpers import add_space
from usecases.RTMedAgent.backend.agents.tool_store.tools import available_tools
from usecases.RTMedAgent.backend.agents.tool_store.tools_helper import (
    function_mapping,
    push_tool_start,
    push_tool_end,
)
from shared_ws import (
    send_tts_audio,
    push_final,
    broadcast_message,
    send_response_to_acs,
)

logger = get_logger("gpt_flow")


# ────────────────────────────────────────────────────────────────────────────
# GPT streaming helper
# ────────────────────────────────────────────────────────────────────────────
async def process_gpt_response(
    cm,
    user_prompt: str,
    ws: WebSocket,
    *,
    is_acs: bool = False,
) -> Optional[Dict[str, Any]]:
    """Stream a chat completion, emit TTS, handle tool calls."""
    cm.hist.append({"role": "user", "content": user_prompt})

    response = az_openai_client.chat.completions.create(
        stream=True,
        messages=cm.hist,
        tools=available_tools,
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.5,
        top_p=1.0,
        model=AZURE_OPENAI_CHAT_DEPLOYMENT_ID,
    )

    collected, final_chunks = [], []
    tool_started = False
    tool_name = tool_id = args = ""

    for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # ── tool-call tokens ────────────────────────────────────────────────
        if delta.tool_calls:
            tc = delta.tool_calls[0]
            tool_id = tc.id or tool_id
            tool_name = tc.function.name or tool_name
            args += tc.function.arguments or ""
            tool_started = True
            continue

        # ── normal content tokens ───────────────────────────────────────────
        if delta.content:
            collected.append(delta.content)
            if delta.content in TTS_END:
                streaming = add_space("".join(collected).strip())
                await _emit_streaming_text(streaming, ws, is_acs)
                final_chunks.append(streaming)
                collected.clear()

    # flush tail
    if collected:
        pending = "".join(collected).strip()
        await _emit_streaming_text(pending, ws, is_acs)
        final_chunks.append(pending)

    full_text = "".join(final_chunks).strip()
    if full_text:
        cm.hist.append({"role": "assistant", "content": full_text})
        await push_final(ws, "assistant", full_text, is_acs=is_acs)

    # ── follow-up tool call ────────────────────────────────────────────────
    if tool_started:
        cm.hist.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": args},
                    }
                ],
            }
        )
        return await _handle_tool_call(tool_name, tool_id, args, cm, ws, is_acs)

    return None

async def _emit_streaming_text(text: str, ws: WebSocket, is_acs: bool) -> None:
    """Send one streaming chunk (TTS + relay)."""
    if is_acs:
        await broadcast_message(ws.app.state.clients, text, "Assistant")
        await send_response_to_acs(ws, text, latency_tool=ws.state.lt)  # fire-and-forget
    else:
        await send_tts_audio(text, ws, latency_tool=ws.state.lt)
        await ws.send_text(json.dumps({"type": "assistant_streaming", "content": text}))

async def _handle_tool_call(
    tool_name: str,
    tool_id: str,
    args: str,
    cm,
    ws: WebSocket,
    is_acs: bool,
) -> dict:
    params = json.loads(args or "{}")
    fn = function_mapping.get(tool_name)
    if fn is None:
        raise ValueError(f"Unknown tool '{tool_name}'")

    call_id = uuid.uuid4().hex[:8]

    # --- notify UI (start) --------------------------------------------------
    await push_tool_start(ws, call_id, tool_name, params, is_acs=is_acs)

    # --- run the tool -------------------------------------------------------
    t0 = time.perf_counter()
    result = await fn(params)
    elapsed = (time.perf_counter() - t0) * 1000
    result = json.loads(result) if isinstance(result, str) else result

    cm.hist.append(
        {
            "tool_call_id": tool_id,
            "role": "tool",
            "name": tool_name,
            "content": json.dumps(result),
        }
    )

    # --- notify UI (end) ----------------------------------------------------
    await push_tool_end(
        ws, call_id, tool_name, "success", elapsed, result=result, is_acs=is_acs
    )

    # (pretty bubble for ACS – optional, one line only)
    if is_acs:
        await broadcast_message(ws.app.state.clients, f"🛠️ {tool_name} ✔️", "Assistant")

    # --- ask GPT to follow up ----------------------------------------------
    await _process_tool_followup(cm, ws, is_acs)
    return result


async def _process_tool_followup(cm, ws: WebSocket, is_acs: bool) -> None:
    """Ask GPT to respond *after* tool execution (no new user input)."""
    await process_gpt_response(cm, "", ws, is_acs=is_acs)

async def route_turn(cm, transcript: str, ws: WebSocket, *, is_acs: bool) -> None:
    """
    Routes a single user utterance through authentication or main dialog,
    then persists the conversation state.

    Adds latency tracking for each step.
    """
    redis_mgr = ws.app.state.redis
    latency_tool = ws.state.lt

    if not cm.get_context("authenticated", False):
        # Processing step for authentication
        latency_tool.start("processing")
        result = await process_gpt_response(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop("processing", redis_mgr)

        if result and result.get("authenticated"):
            cm.update_context("authenticated", True)
            cm.upsert_system_prompt()
            logger.info(
                f"Session {cm.session_id} authenticated successfully."
            )
    else:
        # Processing step for main dialog
        latency_tool.start("processing")
        await process_gpt_response(cm, transcript, ws, is_acs=is_acs)
        latency_tool.stop("processing", redis_mgr)
    cm.persist_to_redis(redis_mgr)

