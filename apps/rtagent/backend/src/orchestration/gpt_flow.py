from __future__ import annotations

"""OpenAI streaming + tool-call orchestration layer.

Handles GPT chat-completion streaming, TTS relay, and function-calling for the
real-time voice agent.

Public API
----------
process_gpt_response() – Stream completions, emit TTS chunks, run tools.
"""

import asyncio
import json
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastapi import WebSocket
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from urllib.parse import urlparse

from apps.rtagent.backend.settings import AZURE_OPENAI_CHAT_DEPLOYMENT_ID, TTS_END
from apps.rtagent.backend.src.agents.tool_store.tool_registry import (
    available_tools as DEFAULT_TOOLS,
)
from apps.rtagent.backend.src.agents.tool_store.tools_helper import (
    function_mapping,
    push_tool_end,
    push_tool_start,
)
from apps.rtagent.backend.src.helpers import add_space
from apps.rtagent.backend.src.services.openai_services import client as az_openai_client
from apps.rtagent.backend.src.shared_ws import (
    broadcast_message,
    push_final,
    send_response_to_acs,
    send_tts_audio,
)
from apps.rtagent.backend.settings import AZURE_OPENAI_ENDPOINT
from src.enums.monitoring import SpanAttr
from utils.ml_logging import get_logger
from utils.trace_context import create_trace_context
from apps.rtagent.backend.src.utils.tracing_utils import (
    create_service_handler_attrs,
    create_service_dependency_attrs,
    log_with_context,
)


if TYPE_CHECKING:  # pragma: no cover – typing-only import
    from src.stateful.state_managment import MemoManager  # noqa: F401

logger = get_logger("gpt_flow")

# Get OpenTelemetry tracer for Application Map
tracer = trace.get_tracer(__name__)

# Performance optimization: Cache tracing configuration
_GPT_FLOW_TRACING = os.getenv("GPT_FLOW_TRACING", "true").lower() == "true"
_STREAM_TRACING = (
    os.getenv("STREAM_TRACING", "false").lower() == "true"
)  # High frequency ops


def _get_agent_voice_config(
    cm: "MemoManager",
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract agent voice configuration from memory manager.

    Returns:
        Tuple of (voice_name, voice_style, voice_rate) or (None, None, None) if not available
    """
    if cm is None:
        logger.warning("MemoManager is None, using default voice configuration")
        return None, None, None

    try:
        voice_name = cm.get_value_from_corememory("current_agent_voice")
        voice_style = cm.get_value_from_corememory("current_agent_voice_style", "chat")
        voice_rate = cm.get_value_from_corememory("current_agent_voice_rate", "+3%")
        return voice_name, voice_style, voice_rate
    except Exception as e:
        logger.warning(f"Failed to get agent voice config: {e}")
        return None, None, None


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


async def process_gpt_response(  # noqa: D401
    cm: "MemoManager",
    user_prompt: str,
    ws: WebSocket,
    *,
    agent_name: str,
    is_acs: bool = False,
    model_id: str = AZURE_OPENAI_CHAT_DEPLOYMENT_ID,
    temperature: float = 0.5,
    top_p: float = 1.0,
    max_tokens: int = 4096,
    available_tools: Optional[List[Dict[str, Any]]] = None,
    call_connection_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Stream a chat completion, emitting TTS and handling tool calls.

    Args:
        cm: Active :class:`MemoManager`.
        user_prompt: The raw user prompt string.
        ws: WebSocket connection to the client.
        agent_name: Identifier used to fetch the agent‑specific chat history.
        is_acs: Flag indicating Azure Communication Services pathway.
        model_id: Azure OpenAI deployment ID.
        temperature: Sampling temperature.
        top_p: Nucleus sampling value.
        max_tokens: Max tokens for the completion.
        available_tools: Tool definitions to expose; *None* defaults to the
            global *DEFAULT_TOOLS* list.
        call_connection_id: ACS call connection ID for tracing correlation.
        session_id: Session ID for tracing correlation.

    Returns:
        Optional tool result dictionary if a tool was executed; otherwise *None*.
    """

    # Create handler span for GPT flow service
    span_attrs = create_service_handler_attrs(
        service_name="gpt_flow",
        call_connection_id=call_connection_id,
        session_id=session_id,
        operation="process_response",
        agent_name=agent_name,
        model_id=model_id,
        is_acs=is_acs,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        tools_available=len(available_tools or DEFAULT_TOOLS),
        prompt_length=len(user_prompt) if user_prompt else 0,
    )

    with tracer.start_as_current_span(
        "gpt_flow.process_response", attributes=span_attrs
    ) as span:
        agent_history: List[Dict[str, Any]] = cm.get_history(agent_name)
        agent_history.append({"role": "user", "content": user_prompt})

        tool_set = available_tools or DEFAULT_TOOLS
        span.set_attribute("tools.count", len(tool_set))

        chat_kwargs: Dict[str, Any] = {
            "stream": True,
            "messages": agent_history,
            "model": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "tools": tool_set,
            "tool_choice": "auto" if tool_set else "none",
        }

        span.set_attribute("chat.history_length", len(agent_history))
        logger.debug("process_gpt_response – chat kwargs prepared: %s", chat_kwargs)

        # Create dependency span for calling Azure OpenAI
        azure_openai_attrs = create_service_dependency_attrs(
            source_service="gpt_flow",
            target_service="azure_openai",
            call_connection_id=call_connection_id,
            session_id=session_id,
            operation="stream_completion",
            model=model_id,
            stream=True,
        )
        aoai_endpoint = AZURE_OPENAI_ENDPOINT
        host = urlparse(aoai_endpoint).netloc or "api.openai.azure.com"

        with tracer.start_as_current_span(
            "gpt_flow.stream_completion",
            kind=SpanKind.CLIENT,
            attributes={
                **azure_openai_attrs,
                "peer.service": "azure-openai",
                "server.address": host,
                "server.port": 443,
                "http.method": "POST",
                "http.url": f"https://{host}/openai/deployments/{model_id}/chat/completions",
                "pipeline.stage": "orchestrator -> aoai",
            },
        ) as stream_span:
            response = az_openai_client.chat.completions.create(**chat_kwargs)
            stream_span.add_event("openai_stream_started")

            collected: List[str] = []  # Temporary buffer for partial tokens.
            final_chunks: List[str] = []  # All streamed assistant chunks.

            tool_started = False
            tool_name = ""
            tool_id = ""
            args = ""
            chunk_count = 0

            for chunk in response:
                chunk_count += 1
                if not chunk.choices:
                    continue  # Skip empty chunks.

                delta = chunk.choices[0].delta

                if delta.tool_calls:
                    tc = delta.tool_calls[0]
                    tool_id = tc.id or tool_id
                    tool_name = tc.function.name or tool_name
                    args += tc.function.arguments or ""
                    if not tool_started:  # First tool call chunk
                        tool_started = True
                        stream_span.add_event(
                            "tool_call_detected", {"tool_name": tool_name}
                        )
                    continue

                if delta.content:
                    collected.append(delta.content)
                    if delta.content in TTS_END:  # Time to flush a sentence.
                        streaming = add_space("".join(collected).strip())
                        logger.info(
                            "process_gpt_response – streaming text chunk: %s",
                            streaming,
                        )
                        await _emit_streaming_text(
                            streaming, ws, is_acs, cm, call_connection_id, session_id
                        )
                        final_chunks.append(streaming)
                        collected.clear()

            stream_span.set_attribute("chunks_processed", chunk_count)
            stream_span.set_attribute("tool_call_detected", tool_started)
            if tool_started:
                stream_span.set_attribute("tool_name", tool_name)

        # Handle remaining collected content
        if collected:
            pending = "".join(collected).strip()
            await _emit_streaming_text(
                pending, ws, is_acs, cm, call_connection_id, session_id
            )
            final_chunks.append(pending)

        full_text = "".join(final_chunks).strip()
        if full_text:
            agent_history.append({"role": "assistant", "content": full_text})
            await push_final(ws, "assistant", full_text, is_acs=is_acs)
            # Broadcast the final assistant response to relay dashboard
            try:
                # Get current agent name for specialist display
                active_agent = (
                    cm.get_value_from_corememory("active_agent") if cm else None
                )
                authenticated = (
                    cm.get_value_from_corememory("authenticated") if cm else False
                )

                if active_agent == "Claims":
                    agent_sender = "Claims Specialist"
                elif active_agent == "General":
                    agent_sender = "General Info"
                elif not authenticated:  # Auth agent (before authentication)
                    agent_sender = "Auth Agent"
                else:
                    agent_sender = "Assistant"
                await broadcast_message(ws.app.state.clients, full_text, agent_sender)
            except Exception as e:
                logger.error(f"Failed to broadcast assistant message: {e}")
            span.set_attribute("response.length", len(full_text))

        # Handle follow‑up tool call (if any)
        if tool_started:
            span.add_event(
                "tool_execution_starting", {"tool_name": tool_name, "tool_id": tool_id}
            )

            agent_history.append(
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
            result = await _handle_tool_call(
                tool_name,
                tool_id,
                args,
                cm,
                ws,
                agent_name,
                is_acs,
                model_id,
                temperature,
                top_p,
                max_tokens,
                tool_set,
                call_connection_id,
                session_id,
            )
            if result is not None:
                # Persist tool output and update slots in the background to avoid blocking response flow
                async def persist_tool_results():
                    cm.persist_tool_output(tool_name, result)
                    if isinstance(result, dict) and "slots" in result:
                        cm.update_slots(result["slots"])

                asyncio.create_task(persist_tool_results())
                span.set_attribute("tool.execution_success", True)
                span.add_event("tool_execution_completed", {"tool_name": tool_name})
            return result

        span.set_attribute("completion_type", "text_only")
        return None


# ===========================================================================
# Helper routines – kept functionally identical
# ===========================================================================


def _get_agent_sender_name(cm: "MemoManager") -> str:
    """Get the agent sender name for display purposes."""
    try:
        active_agent = (
            cm.get_value_from_corememory("active_agent") if cm else None
        )
        authenticated = (
            cm.get_value_from_corememory("authenticated") if cm else False
        )

        if active_agent == "Claims":
            return "Claims Specialist"
        elif active_agent == "General":
            return "General Info"
        elif not authenticated:  # Auth agent (before authentication)
            return "Auth Agent"
        else:
            return "Assistant"
    except Exception:
        return "Assistant"


async def _emit_streaming_text(
    text: str,
    ws: WebSocket,
    is_acs: bool,
    cm: "MemoManager",
    call_connection_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:  # noqa: D401,E501
    """Emit one assistant text chunk via either ACS or WebSocket + TTS."""
    if _STREAM_TRACING:
        span_attrs = create_service_handler_attrs(
            service_name="gpt_flow",
            call_connection_id=call_connection_id,
            session_id=session_id,
            operation="emit_streaming_text",
            text_length=len(text),
            is_acs=is_acs,
            chunk_type="streaming_text",
        )

        with tracer.start_as_current_span(
            "gpt_flow.emit_streaming_text", attributes=span_attrs
        ) as span:
            # Get agent voice configuration
            agent_voice, agent_voice_style, agent_voice_rate = _get_agent_voice_config(
                cm
            )

            if is_acs:
                span.set_attribute("output_channel", "acs")
                # Note: broadcast_message is handled separately for final responses to avoid duplication
                await send_response_to_acs(
                    ws,
                    text,
                    latency_tool=ws.state.lt,
                    voice_name=agent_voice,
                    voice_style=agent_voice_style,
                    rate=agent_voice_rate,
                )
            else:
                span.set_attribute("output_channel", "websocket_tts")
                await send_tts_audio(
                    text,
                    ws,
                    latency_tool=ws.state.lt,
                    voice_name=agent_voice,
                    voice_style=agent_voice_style,
                    rate=agent_voice_rate,
                )
                agent_sender_name = _get_agent_sender_name(cm)
                await ws.send_text(
                    json.dumps({"type": "assistant_streaming", "content": text, "speaker": agent_sender_name})
                )

            span.add_event("text_emitted", {"text_length": len(text)})
    else:
        # Fast path when high-frequency tracing is disabled
        # Get agent voice configuration
        agent_voice, agent_voice_style, agent_voice_rate = _get_agent_voice_config(cm)

        if is_acs:
            await send_response_to_acs(
                ws,
                text,
                latency_tool=ws.state.lt,
                voice_name=agent_voice,
                voice_style=agent_voice_style,
                rate=agent_voice_rate,
            )
        else:
            await send_tts_audio(
                text,
                ws,
                latency_tool=ws.state.lt,
                voice_name=agent_voice,
                voice_style=agent_voice_style,
                rate=agent_voice_rate,
            )
            agent_sender_name = _get_agent_sender_name(cm)
            await ws.send_text(
                json.dumps({"type": "assistant_streaming", "content": text, "speaker": agent_sender_name})
            )


async def _handle_tool_call(  # noqa: PLR0913
    tool_name: str,
    tool_id: str,
    args: str,
    cm: "MemoManager",
    ws: WebSocket,
    agent_name: str,
    is_acs: bool,
    model_id: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    available_tools: List[Dict[str, Any]],
    call_connection_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a tool, emit telemetry events, and trigger GPT follow‑up."""
    with create_trace_context(
        name="gpt_flow.handle_tool_call",
        call_connection_id=call_connection_id,
        session_id=session_id,
        metadata={
            "tool_name": tool_name,
            "tool_id": tool_id,
            "agent_name": agent_name,
            "is_acs": is_acs,
            "args_length": len(args) if args else 0,
        },
    ) as trace_ctx:
        params: Dict[str, Any] = json.loads(args or "{}")
        fn = function_mapping.get(tool_name)
        if fn is None:
            trace_ctx.set_attribute("error", f"Unknown tool '{tool_name}'")
            raise ValueError(f"Unknown tool '{tool_name}'")

        trace_ctx.set_attribute("tool.parameters_count", len(params))
        call_id = uuid.uuid4().hex[:8]
        trace_ctx.set_attribute("tool.call_id", call_id)

        await push_tool_start(ws, call_id, tool_name, params, is_acs=is_acs)
        trace_ctx.add_event("tool_start_pushed", {"call_id": call_id})

        # Execute tool with nested tracing
        with create_trace_context(
            name=f"gpt_flow.execute_tool.{tool_name}",
            call_connection_id=call_connection_id,
            session_id=session_id,
            metadata={
                "tool_name": tool_name,
                "call_id": call_id,
                "parameters": params,
            },
        ) as exec_ctx:
            t0 = time.perf_counter()
            result_raw = await fn(params)  # Tool functions are expected to be async.
            elapsed_ms = (time.perf_counter() - t0) * 1000

            exec_ctx.set_attribute("execution.duration_ms", elapsed_ms)
            exec_ctx.set_attribute("execution.success", True)

            result: Dict[str, Any] = (
                json.loads(result_raw) if isinstance(result_raw, str) else result_raw
            )
            exec_ctx.set_attribute("result.type", type(result).__name__)

        agent_history = cm.get_history(agent_name)
        agent_history.append(
            {
                "tool_call_id": tool_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps(result),
            }
        )

        await push_tool_end(
            ws, call_id, tool_name, "success", elapsed_ms, result=result, is_acs=is_acs
        )
        trace_ctx.add_event("tool_end_pushed", {"elapsed_ms": elapsed_ms})

        # Broadcast tool completion to relay dashboard (only for ACS calls)
        if is_acs:
            try:
                # Get current agent name for specialist display
                active_agent = (
                    cm.get_value_from_corememory("active_agent") if cm else None
                )
                authenticated = (
                    cm.get_value_from_corememory("authenticated") if cm else False
                )

                if active_agent == "Claims":
                    agent_sender = "Claims Specialist"
                elif active_agent == "General":
                    agent_sender = "General Info"
                elif not authenticated:  # Auth agent (before authentication)
                    agent_sender = "Auth Agent"
                else:
                    agent_sender = "Assistant"
                await broadcast_message(
                    ws.app.state.clients, f"🛠️ {tool_name} ✔️", agent_sender
                )
            except Exception as e:
                logger.error(f"Failed to broadcast tool completion: {e}")

        # Handle tool follow-up with tracing
        trace_ctx.add_event("starting_tool_followup")
        await _process_tool_followup(
            cm,
            ws,
            agent_name,
            is_acs,
            model_id,
            temperature,
            top_p,
            max_tokens,
            available_tools,
            call_connection_id,
            session_id,
        )

        trace_ctx.set_attribute("tool.execution_complete", True)
        return result


async def _process_tool_followup(  # noqa: PLR0913
    cm: "MemoManager",
    ws: WebSocket,
    agent_name: str,
    is_acs: bool,
    model_id: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    available_tools: List[Dict[str, Any]],
    call_connection_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Invoke GPT once more after tool execution (no new user input)."""
    with create_trace_context(
        name="gpt_flow.tool_followup",
        call_connection_id=call_connection_id,
        session_id=session_id,
        metadata={
            "agent_name": agent_name,
            "model_id": model_id,
            "is_acs": is_acs,
            "followup_type": "post_tool_execution",
        },
    ) as trace_ctx:
        trace_ctx.add_event("starting_followup_completion")

        await process_gpt_response(
            cm,
            "",  # No new user prompt.
            ws,
            agent_name=agent_name,
            is_acs=is_acs,
            model_id=model_id,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            available_tools=available_tools,
            call_connection_id=call_connection_id,
            session_id=session_id,
        )

        trace_ctx.add_event("followup_completion_finished")
