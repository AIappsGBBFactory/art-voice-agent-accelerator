# financial_tools.py
"""Financial-services tool wiring for Azure VoiceLive agents."""

from __future__ import annotations

import asyncio
import inspect
import os
import time

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeAlias, Union

from azure.ai.voicelive.models import FunctionTool
from pydantic import BaseModel

from utils.ml_logging import get_logger
from src.cosmosdb.manager import CosmosDBMongoCoreManager
from apps.rtagent.backend.src.agents.shared.rag_retrieval import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_DATABASE_NAME,
    DEFAULT_NUM_CANDIDATES,
    DEFAULT_TOP_K,
    VENMO_COLLECTION_NAME,
    infer_collection_from_query,
    one_shot_query,
    schedule_cosmos_retriever_warmup,
)
from .tool_store.call_transfer import (
    TRANSFER_CALL_SCHEMA,
    transfer_call_to_destination,
    TRANSFER_CALL_CENTER_SCHEMA,
    transfer_call_to_call_center,
)
from .tool_store.tool_registry import (
    available_tools as VL_AVAILABLE_TOOLS,
    function_mapping as VL_FUNCTIONS,
)
from .handoffs import (
    escalate_human as vl_escalate_human,
    handoff_fraud_agent as vl_handoff_fraud_agent,
    handoff_transfer_agency_agent as vl_handoff_transfer_agency_agent,
    handoff_paypal_agent as vl_handoff_paypal_agent,
    handoff_to_auth as vl_handoff_to_auth,
)
from .tool_store.financial_helpers import (
    execute_search_knowledge_base,
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


_VL_SCHEMAS_BY_NAME: Dict[str, Dict[str, Any]] = {
    entry["function"]["name"]: entry["function"]
    for entry in VL_AVAILABLE_TOOLS
    if isinstance(entry, dict) and entry.get("type") == "function"
}


ToolExecutor: TypeAlias = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    """Declarative metadata used to register VoiceLive tools."""

    name: str
    schema: Optional[Dict[str, Any]] = None
    executor: Optional[ToolExecutor] = None
    is_handoff: bool = False


# Tools that rely on the upstream ART implementation without overrides.
STANDARD_TOOL_NAMES: Tuple[str, ...] = (
    "verify_client_identity",
    "verify_fraud_client_identity",
    "verify_mfa_code",
    "check_transaction_authorization",
    "analyze_recent_transactions",
    "check_suspicious_activity",
    "create_fraud_case",
    "create_transaction_dispute",
    "block_card_emergency",
    "provide_fraud_education",
    "ship_replacement_card",
    "send_fraud_case_email",
    "get_client_data",
    "get_drip_positions",
    "check_compliance_status",
    "calculate_liquidation_proceeds",
    "handoff_to_compliance",
    "handoff_to_trading",
    "escalate_emergency",
    "detect_voicemail_and_end_call",
    "confirm_voicemail_and_end_call",
    "transfer_call_to_call_center",
)


REGISTERED_TOOLS: Dict[str, ToolSpec] = {}


def register_tool(
    name: str,
    *,
    schema: Optional[Dict[str, Any]] = None,
    executor: Optional[ToolExecutor] = None,
    is_handoff: bool = False,
) -> None:
    """Central helper to register a tool spec once."""

    if name in REGISTERED_TOOLS:
        logger.warning("Tool '%s' already registered; overriding previous spec", name)
    REGISTERED_TOOLS[name] = ToolSpec(
        name=name,
        schema=schema,
        executor=executor,
        is_handoff=is_handoff,
    )


for tool_name in STANDARD_TOOL_NAMES:
    register_tool(tool_name)


SEARCH_KB_SCHEMA: Dict[str, Any] = {
    "name": "search_knowledge_base",
    "description": (
        "Retrieve institutional knowledge-base snippets from the Cosmos vector index. "
        "Use this after authentication to ground policy summaries, rate tables, or escalation guidance."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language question or keyword to search in the financial KB.",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of passages to return (defaults to service configuration).",
            },
            "num_candidates": {
                "type": "integer",
                "minimum": 1,
                "description": "Candidate pool size for semantic search reranking (defaults to service configuration).",
            },
            "database": {
                "type": "string",
                "description": "Override Cosmos DB database name if a custom corpus is required.",
            },
            "collection": {
                "type": "string",
                "description": "Override Cosmos DB collection name (defaults to paypal; use venmo for Venmo queries).",
            },
            "doc_type": {
                "type": "string",
                "description": "Optional metadata filter (e.g., 'mfa_playbook', 'fraud_policy').",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


PAYPAL_ACCOUNT_SCHEMA: Dict[str, Any] = {
    "name": "get_paypal_account_summary",
    "description": "Retrieve the caller's PayPal account summary, including current balance, after identity verification is complete.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Internal client identifier returned from authentication tools (preferred).",
            },
            "full_name": {
                "type": "string",
                "description": "Optional caller name for logging context after authentication.",
            },
            "institution_name": {
                "type": "string",
                "description": "Optional institution or employer metadata for logging context.",
            },
        },
        "required": ["client_id"],
        "additionalProperties": False,
    },
}


PAYPAL_TRANSACTIONS_SCHEMA: Dict[str, Any] = {
    "name": "get_paypal_transactions",
    "description": "Retrieve the caller's recent PayPal transactions after authentication for activity review.",
    "parameters": {
        "type": "object",
        "properties": {
            "client_id": {
                "type": "string",
                "description": "Verified client identifier returned from authentication tools.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Maximum number of transactions to return (default 5).",
            },
        },
        "required": ["client_id"],
        "additionalProperties": False,
    },
}

ToolExecutor = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

_USERS_MANAGER: Optional[CosmosDBMongoCoreManager] = None


def _get_users_manager() -> CosmosDBMongoCoreManager:
    global _USERS_MANAGER
    if _USERS_MANAGER is None:
        _USERS_MANAGER = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="users",
        )
    return _USERS_MANAGER


async def _execute_get_paypal_account_summary(arguments: Dict[str, Any]) -> Dict[str, Any]:
    client_id = (arguments.get("client_id") or "").strip()
    full_name = (arguments.get("full_name") or "").strip()
    institution_name = (arguments.get("institution_name") or "").strip()

    if not client_id:
        return {
            "success": False,
            "message": "A verified client_id is required before retrieving balance information.",
        }

    query: Dict[str, Any] = {"$or": [{"_id": client_id}, {"client_id": client_id}]}

    manager = _get_users_manager()

    try:
        raw_result = await asyncio.to_thread(manager.read_document, query)
    except Exception as exc:
        logger.error("Failed to load PayPal account summary | query=%s err=%s", query, exc)
        return {
            "success": False,
            "message": "Account lookup temporarily unavailable. Please retry or route to authentication.",
            "error": str(exc),
        }

    if not raw_result:
        return {
            "success": False,
            "message": "No matching client record found. Confirm the caller's identity or escalate.",
        }

    account_status = (raw_result.get("customer_intelligence") or {}).get("account_status") or {}
    balance = account_status.get("current_balance")
    currency = account_status.get("account_currency", "USD")

    return {
        "success": True,
        "message": f"Retrieved PayPal account summary for {raw_result.get('full_name', client_id or full_name)}.",
        "client_id": raw_result.get("client_id") or raw_result.get("_id"),
        "full_name": raw_result.get("full_name"),
        "institution_name": raw_result.get("institution_name"),
        "balance": balance,
        "currency": currency,
        "authorization_level": raw_result.get("authorization_level"),
        "mfa_enabled": (raw_result.get("mfa_settings") or {}).get("enabled", False),
        "mfa_required_threshold": raw_result.get("mfa_required_threshold"),
        "account_health_score": account_status.get("account_health_score"),
        "last_login": raw_result.get("customer_intelligence", {}).get("account_status", {}).get("last_login"),
    }


async def _execute_get_paypal_transactions(arguments: Dict[str, Any]) -> Dict[str, Any]:
    client_id = (arguments.get("client_id") or "").strip()
    limit_raw = arguments.get("limit")

    if not client_id:
        return {
            "success": False,
            "message": "A verified client_id is required before retrieving transaction history.",
        }

    try:
        limit = int(limit_raw) if isinstance(limit_raw, int) else 5
    except (TypeError, ValueError):  # pragma: no cover - defensive
        limit = 5

    limit = max(1, min(limit, 20))

    manager = _get_users_manager()
    query: Dict[str, Any] = {"$or": [{"_id": client_id}, {"client_id": client_id}]}

    try:
        raw_result = await asyncio.to_thread(manager.read_document, query)
    except Exception as exc:
        logger.error("Failed to load PayPal transactions | client_id=%s err=%s", client_id, exc)
        return {
            "success": False,
            "message": "Unable to retrieve transactions right now. Please retry or escalate.",
            "error": str(exc),
        }

    if not raw_result:
        return {
            "success": False,
            "message": "No matching client record found for transaction lookup.",
        }

    transactions = (
        raw_result.get("demo_metadata", {}).get("transactions")
        or raw_result.get("transactions")
        or []
    )

    formatted: List[Dict[str, Any]] = []
    for entry in transactions[:limit]:
        formatted.append(
            {
                "transaction_id": entry.get("transaction_id"),
                "merchant": entry.get("merchant"),
                "amount": entry.get("amount"),
                "category": entry.get("category"),
                "timestamp": entry.get("timestamp") or entry.get("transaction_date"),
                "risk_score": entry.get("risk_score"),
            }
        )

    return {
        "success": True,
        "message": f"Retrieved {len(formatted)} recent PayPal transactions.",
        "client_id": raw_result.get("client_id") or raw_result.get("_id"),
        "transactions": formatted,
    }


async def _execute_send_mfa_code(arguments: Dict[str, Any]) -> Dict[str, Any]:
    forced_args = dict(arguments or {})
    requested_method = (forced_args.get("delivery_method") or "").lower()
    if requested_method and requested_method != "email":
        logger.info(
            "voice-agent: overriding MFA delivery method '%s' to email",
            requested_method,
        )
    forced_args["delivery_method"] = "email"
    return await _call_art_tool("send_mfa_code", forced_args)


async def _execute_resend_mfa_code(arguments: Dict[str, Any]) -> Dict[str, Any]:
    forced_args = dict(arguments or {})
    requested_method = (forced_args.get("delivery_method") or "").lower()
    if requested_method and requested_method != "email":
        logger.info(
            "voice-agent: overriding MFA resend method '%s' to email",
            requested_method,
        )
    forced_args["delivery_method"] = "email"
    return await _call_art_tool("resend_mfa_code", forced_args)
def _prepare_args(fn: Callable[..., Any], raw_args: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Any]]:
    """Coerce VoiceLive dict arguments into the tool's declared signature."""

    signature = inspect.signature(fn)
    params = list(signature.parameters.values())
    if not params:
        return [], {}

    if len(params) == 1:
        param = params[0]
        annotation = param.annotation
        if annotation is not inspect._empty and inspect.isclass(annotation):
            try:
                if issubclass(annotation, BaseModel):
                    return [annotation(**raw_args)], {}
            except TypeError:
                pass
        return [raw_args], {}

    return [], raw_args


async def _call_art_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke an VLAgent tool and normalise its response."""

    fn = VL_FUNCTIONS.get(tool_name)
    if fn is None:
        raise KeyError(f"Tool '{tool_name}' is not registered in VoiceLive tool mapping")

    positional, keyword = _prepare_args(fn, arguments)

    if inspect.iscoroutinefunction(fn):
        result = await fn(*positional, **keyword)
    else:
        result = await asyncio.to_thread(fn, *positional, **keyword)

    return normalize_tool_result(result)


async def _execute_art_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an ART tool, handling handoff payload translation when required."""

    payload = await _call_art_tool(tool_name, arguments)
    if tool_name in HANDOFF_TOOL_NAMES:
        if not payload.get("success", True):
            return payload
        return coerce_handoff_payload(tool_name, payload)
    return payload


def _make_art_executor(tool_name: str) -> ToolExecutor:
    async def _executor(arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await _execute_art_tool(tool_name, arguments)

    return _executor


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


register_tool("send_mfa_code", executor=_execute_send_mfa_code)
register_tool("resend_mfa_code", executor=_execute_resend_mfa_code)
register_tool("handoff_fraud_agent", executor=vl_handoff_fraud_agent, is_handoff=True)
register_tool("handoff_transfer_agency_agent", executor=vl_handoff_transfer_agency_agent, is_handoff=True)
register_tool("handoff_paypal_agent", executor=vl_handoff_paypal_agent, is_handoff=True)
register_tool("handoff_to_auth", executor=vl_handoff_to_auth, is_handoff=True)
register_tool("escalate_human", executor=vl_escalate_human)
register_tool("search_knowledge_base", schema=SEARCH_KB_SCHEMA, executor=execute_search_knowledge_base)
register_tool("get_paypal_account_summary", schema=PAYPAL_ACCOUNT_SCHEMA, executor=_execute_get_paypal_account_summary)
register_tool("get_paypal_transactions", schema=PAYPAL_TRANSACTIONS_SCHEMA, executor=_execute_get_paypal_transactions)
register_tool(
    "transfer_call_to_destination",
    schema=TRANSFER_CALL_SCHEMA,
    executor=transfer_call_to_destination,
)
register_tool(
    "transfer_call_to_call_center",
    schema=TRANSFER_CALL_CENTER_SCHEMA,
    executor=transfer_call_to_call_center,
)

HANDOFF_TOOL_NAMES: Tuple[str, ...] = tuple(
    spec.name for spec in REGISTERED_TOOLS.values() if spec.is_handoff
)

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {}
for spec in REGISTERED_TOOLS.values():
    schema = spec.schema or _VL_SCHEMAS_BY_NAME.get(spec.name)
    if not schema:
        logger.warning(
            "Schema not found for tool '%s'; skipping registration",
            spec.name,
        )
        continue
    TOOL_SCHEMAS[spec.name] = schema

TOOL_EXECUTORS: Dict[str, ToolExecutor] = {}
for spec in REGISTERED_TOOLS.values():
    if spec.executor:
        TOOL_EXECUTORS[spec.name] = spec.executor
        continue
    if spec.name not in VL_FUNCTIONS:
        logger.warning("Implementation not found for tool '%s'; skipping", spec.name)
        continue
    TOOL_EXECUTORS[spec.name] = _make_art_executor(spec.name)


def build_function_tools(tools_cfg: List[Union[str, Dict[str, Any]]] | None) -> List[FunctionTool]:
    """Convert YAML tool declarations into VoiceLive FunctionTool objects."""

    function_tools: List[FunctionTool] = []
    for entry in tools_cfg or []:
        if isinstance(entry, str):
            schema = TOOL_SCHEMAS.get(entry)
            if not schema:
                raise ValueError(f"Tool '{entry}' is not registered")
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
    """Execute a registered tool with model-provided arguments."""

    executor = TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {
            "success": False,
            "error": f"Tool '{tool_name}' not implemented",
            "message": "Requested tool is unavailable in this VoiceLive deployment.",
        }

    return await executor(arguments)


def is_handoff_tool(tool_name: str) -> bool:
    """Return True when tool triggers an agent handoff."""

    return tool_name in HANDOFF_TOOL_NAMES


__all__ = ["build_function_tools", "execute_tool", "is_handoff_tool"]
