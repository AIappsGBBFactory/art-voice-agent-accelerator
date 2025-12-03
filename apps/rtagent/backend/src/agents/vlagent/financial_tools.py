# financial_tools.py
"""Financial-services tool wiring for Azure VoiceLive agents.

This module provides VoiceLive-specific tool execution using the unified tool registry.
"""

from __future__ import annotations

import asyncio
import os
import time

from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeAlias, Union

from azure.ai.voicelive.models import FunctionTool

from utils.ml_logging import get_logger
from src.cosmosdb.manager import CosmosDBMongoCoreManager

# Use the unified tool registry
from apps.rtagent.backend.src.agents.shared.tool_registry import (
    initialize_tools as init_shared_tools,
    get_tool_schema,
    is_handoff_tool as check_handoff_tool,
    execute_tool as execute_shared_tool,
)
from apps.rtagent.backend.src.agents.shared.rag_retrieval import (
    DEFAULT_DATABASE_NAME,
    DEFAULT_NUM_CANDIDATES,
    DEFAULT_TOP_K,
    VENMO_COLLECTION_NAME,
    infer_collection_from_query,
    one_shot_query,
    schedule_cosmos_retriever_warmup,
)
from .tool_store.financial_helpers import (
    normalize_tool_result,
    coerce_handoff_payload,
)

logger = get_logger("voicelive.tools.financial")
kb_logger = get_logger("voicelive.tools.financial.kb")


def _schedule_retriever_warmup() -> None:
    """Kick off background warmup for Cosmos vector retrieval."""

    try:
        if schedule_cosmos_retriever_warmup(appname="voicelive-financial"):
            logger.debug("Scheduled Cosmos retriever warmup task")
    except Exception:
        logger.debug("Cosmos retriever warmup skipped", exc_info=True)


_schedule_retriever_warmup()

# NOTE: Do NOT call init_shared_tools() here to avoid circular import.
# The shared tool registry imports from this module, so initialization
# must happen from the registry side, not here.


ToolExecutor: TypeAlias = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


_USERS_MANAGER: Optional[CosmosDBMongoCoreManager] = None
database_name = os.getenv("COSMOS_FINANCIAL_DATABASE", "financial_services_db")
collection_name = os.getenv("COSMOS_FINANCIAL_USERS_CONTAINER", "users")


def _get_users_manager() -> CosmosDBMongoCoreManager:
    global _USERS_MANAGER
    if _USERS_MANAGER is None:
        _USERS_MANAGER = CosmosDBMongoCoreManager(
            database_name=database_name,
            collection_name=collection_name,
        )
    return _USERS_MANAGER

async def _execute_send_mfa_code(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Override MFA delivery to email for voice-only channel."""
    forced_args = dict(arguments or {})
    requested_method = (forced_args.get("delivery_method") or "").lower()
    if requested_method and requested_method != "email":
        logger.info(
            "voice-agent: overriding MFA delivery method '%s' to email",
            requested_method,
        )
    forced_args["delivery_method"] = "email"
    return await execute_shared_tool("send_mfa_code", forced_args)


async def _execute_resend_mfa_code(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Override MFA resend delivery to email for voice-only channel."""
    forced_args = dict(arguments or {})
    requested_method = (forced_args.get("delivery_method") or "").lower()
    if requested_method and requested_method != "email":
        logger.info(
            "voice-agent: overriding MFA resend method '%s' to email",
            requested_method,
        )
    forced_args["delivery_method"] = "email"
    return await execute_shared_tool("resend_mfa_code", forced_args)


async def _execute_search_knowledge_base(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Perform Cosmos DB semantic search for grounded institutional answers."""

    query = (arguments.get("query") or "").strip()
    if not query:
        return {
            "success": False,
            "message": "Knowledge base query must not be empty.",
            "results": [],
        }

    top_k = arguments.get("top_k")
    num_candidates = arguments.get("num_candidates")
    database = (arguments.get("database") or "").strip() or DEFAULT_DATABASE_NAME
    raw_collection = (arguments.get("collection") or "").strip()
    doc_type = (arguments.get("doc_type") or "").strip()

    collection = raw_collection
    if not collection:
        if doc_type and "venmo" in doc_type.lower():
            collection = VENMO_COLLECTION_NAME
        else:
            collection = infer_collection_from_query(query, default=VENMO_COLLECTION_NAME)

    effective_top_k = int(top_k) if isinstance(top_k, int) and top_k > 0 else DEFAULT_TOP_K
    effective_candidates = int(num_candidates) if isinstance(num_candidates, int) and num_candidates > 0 else DEFAULT_NUM_CANDIDATES
    if effective_candidates < effective_top_k:
        effective_candidates = effective_top_k

    vector_index = (
        os.environ.get("VOICELIVE_KB_VECTOR_INDEX")
        or os.environ.get("AZURE_COSMOS_VECTOR_INDEX_NAME")
        or os.environ.get("COSMOS_VECTOR_INDEX_NAME")
        or os.environ.get("COSMOS_VECTOR_INDEX")
    )

    filters: Optional[Dict[str, Any]] = {"doc_type": doc_type} if doc_type else None

    kb_logger.info(
        "KB search | query='%s' top_k=%d candidates=%d database=%s collection=%s",
        query,
        effective_top_k,
        effective_candidates,
        database,
        collection,
    )

    start = time.perf_counter()
    try:
        results, metrics = await asyncio.to_thread(
            one_shot_query,
            query,
            top_k=effective_top_k,
            num_candidates=effective_candidates,
            database=database,
            collection=collection,
            filters=filters,
            vector_index=vector_index,
            include_metrics=True,
        )
    except Exception as exc:
        kb_logger.error("Knowledge base search failed for '%s': %s", query, exc)
        return {
            "success": False,
            "message": "Knowledge lookup encountered a temporary issue. Try tightening the question or escalate if it persists.",
            "results": [],
            "error": str(exc),
        }

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    metrics = metrics or {}

    formatted = []
    for item in results:
        formatted.append(
            {
                "url": getattr(item, "url", None),
                "content": getattr(item, "content", None),
                "doc_type": getattr(item, "doc_type", None),
                "score": getattr(item, "score", None),
                "snippet": getattr(item, "snippet", None),
            }
        )

    return {
        "success": True,
        "message": f"Pulling what we know about '{query}'.",
        "results": formatted,
        "latency_ms": round(elapsed_ms, 2),
        "metrics": {
            "retriever_init_ms": metrics.get("retriever_init_ms"),
            "embedding_ms": metrics.get("embedding_ms"),
            "aggregate_ms": metrics.get("aggregate_ms"),
            "cosmos_total_ms": metrics.get("total_ms"),
            "fallback_used": metrics.get("fallback_used", False),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# VOICELIVE-SPECIFIC TOOL OVERRIDES
# ═══════════════════════════════════════════════════════════════════════════════
# These executors override or extend the shared registry for VoiceLive-specific behavior

# VoiceLive-specific tool overrides (e.g., force email for MFA)
_VL_OVERRIDES: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "send_mfa_code": _execute_send_mfa_code,
    "resend_mfa_code": _execute_resend_mfa_code,
    "search_knowledge_base": _execute_search_knowledge_base,
}


def build_function_tools(tools_cfg: List[Union[str, Dict[str, Any]]] | None) -> List[FunctionTool]:
    """Convert YAML tool declarations into VoiceLive FunctionTool objects."""

    function_tools: List[FunctionTool] = []
    for entry in tools_cfg or []:
        if isinstance(entry, str):
            schema = get_tool_schema(entry)
            if not schema:
                raise ValueError(f"Tool '{entry}' is not registered in shared registry")
        else:
            schema = entry.get("function") or entry

        name = schema.get("name")
        if not name:
            raise ValueError("Tool specification missing 'name'")

        function_tools.append(
            FunctionTool(
                name=name,
                description=schema.get("description", ""),
                parameters=schema.get("parameters", {"type": "object", "properties": {}}),
            )
        )

    return function_tools


async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool with VoiceLive-specific overrides.

    Checks for VL-specific overrides first, then falls back to shared registry.
    """
    # Check for VoiceLive-specific override
    if tool_name in _VL_OVERRIDES:
        result = await _VL_OVERRIDES[tool_name](arguments)
        return normalize_tool_result(result)

    # Fall back to shared registry
    result = await execute_shared_tool(tool_name, arguments)

    # Handle handoff payload translation
    if check_handoff_tool(tool_name) and result.get("success", True):
        return coerce_handoff_payload(tool_name, result)

    return result


def is_handoff_tool(tool_name: str) -> bool:
    """Return True when tool triggers an agent handoff."""
    return check_handoff_tool(tool_name)


__all__ = ["build_function_tools", "execute_tool", "is_handoff_tool"]
