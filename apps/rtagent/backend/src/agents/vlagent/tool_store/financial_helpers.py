from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from utils.ml_logging import get_logger
from apps.rtagent.backend.src.agents.shared.rag_retrieval import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_DATABASE_NAME,
    DEFAULT_NUM_CANDIDATES,
    DEFAULT_TOP_K,
    VENMO_COLLECTION_NAME,
    infer_collection_from_query,
    one_shot_query,
    _get_cached_retriever,
)
from src.aoai import client as aoai_client_module

kb_logger = get_logger("voicelive.tools.financial.kb")
handoff_logger = get_logger("voicelive.tools.financial.handoff")


async def execute_search_knowledge_base(arguments: Dict[str, Any]) -> Dict[str, Any]:
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
    effective_candidates = (
        int(num_candidates) if isinstance(num_candidates, int) and num_candidates > 0 else DEFAULT_NUM_CANDIDATES
    )
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
    retry_auth = False
    for attempt in range(2):
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
            break
        except Exception as exc:
            if _is_embedding_auth_error(exc) and not retry_auth:
                retry_auth = True
                kb_logger.warning("Embedding auth failure detected; refreshing Azure OpenAI client and retriever cache.")
                _refresh_embedding_stack()
                continue
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


def normalize_tool_result(result: Any) -> Dict[str, Any]:
    """Convert tool results into JSON-serialisable dictionaries."""

    if result is None:
        return {"success": False, "message": "Tool returned no data."}

    if hasattr(result, "model_dump"):
        result = result.model_dump()
    elif hasattr(result, "dict") and callable(getattr(result, "dict")):
        try:
            result = result.dict()
        except TypeError:
            pass

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return {"success": False, "message": result}

    if isinstance(result, dict) and "ok" in result:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        normalised = {
            "success": bool(result.get("ok")),
            "message": result.get("message", ""),
        }
        normalised.update(data)
        return normalised

    if isinstance(result, dict):
        return result

    return {"success": True, "value": result}


def cleanup_context(data: Dict[str, Any]) -> Dict[str, Any]:
    """Strip falsy values to keep handoff payloads compact."""

    return {key: value for key, value in (data or {}).items() if value not in (None, "", [], {}, False)}


def build_handoff_payload(
    *,
    target_agent: str,
    message: str,
    summary: str,
    context: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create orchestrator-compatible payload for agent switching."""

    payload: Dict[str, Any] = {
        "handoff": True,
        "target_agent": target_agent,
        "message": message,
        "handoff_summary": summary,
        "handoff_context": context,
    }
    if extra:
        payload.update(extra)
    return payload


def coerce_handoff_payload(tool_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate upstream handoff payloads into orchestrator format."""

    data = dict(payload or {})
    success = bool(data.pop("success", True))
    message = data.pop("message", f"Transferring to {data.get('target_agent') or tool_name}.")
    summary = data.pop("handoff_summary", message)
    target = data.pop("target_agent", data.pop("handoff", tool_name))
    session_overrides = data.pop("session_overrides", None)
    should_interrupt = bool(data.pop("should_interrupt_playback", True))

    extra: Dict[str, Any] = {"handoff": True, "should_interrupt_playback": should_interrupt}
    if session_overrides:
        extra["session_overrides"] = session_overrides

    payload_out = build_handoff_payload(
        target_agent=str(target or tool_name),
        message=message,
        summary=summary,
        context=cleanup_context(data),
        extra=extra,
    )
    payload_out["success"] = success
    return payload_out


def _is_embedding_auth_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "azure openai embeddings request failed" in message and ("401" in message or "unauthorized" in message)


def _refresh_embedding_stack() -> None:
    try:
        aoai_client_module.client = aoai_client_module.create_azure_openai_client()
        _get_cached_retriever.cache_clear()
        kb_logger.info("Azure OpenAI client and retriever cache refreshed after auth failure.")
    except Exception as refresh_exc:  # noqa: BLE001
        kb_logger.error("Failed to refresh Azure OpenAI client after auth failure: %s", refresh_exc)


__all__ = [
    "execute_search_knowledge_base",
    "normalize_tool_result",
    "coerce_handoff_payload",
    "build_handoff_payload",
    "cleanup_context",
]
