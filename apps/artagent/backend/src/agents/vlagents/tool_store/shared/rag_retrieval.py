"""Reusable Cosmos DB vector retrieval helpers for VoiceLive agents."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import threading

import pymongo
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pymongo.auth_oidc import (
    OIDCCallback,
    OIDCCallbackContext,
    OIDCCallbackResult,
)
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.aoai.client import client as shared_aoai_client

load_dotenv()

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 20
DEFAULT_NUM_CANDIDATES = 80
COSMOS_VECTOR_DIMENSION_LIMIT = 2000
DEFAULT_DATABASE_NAME = "vectordb"
DEFAULT_COLLECTION_NAME = "paypal"
VENMO_COLLECTION_NAME = "venmo"


class AzureIdentityTokenCallback(OIDCCallback):
    """MongoDB OIDC callback that returns an Azure AD access token."""

    def __init__(self, credential: DefaultAzureCredential) -> None:
        self._credential = credential

    def fetch(self, context: OIDCCallbackContext) -> OIDCCallbackResult:  # pragma: no cover - external call
        token = self._credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token
        return OIDCCallbackResult(access_token=token)


class EmbeddingClient:
    """Wrapper around Azure OpenAI embeddings."""

    def __init__(self, deployment: str, client: Optional[Any] = None) -> None:
        if not deployment:
            raise ValueError("Embedding deployment name must be provided")
        self._client = client or shared_aoai_client
        if self._client is None:
            raise RuntimeError("Azure OpenAI client is not initialized; ensure src/aoai/client.py configured correctly")
        self._deployment = deployment
        self._logger = logging.getLogger(self.__class__.__name__)

    def embed(self, text: str) -> List[float]:
        with tracer.start_as_current_span("azure.openai.embeddings") as span:
            span.set_attribute("ai.request.model", self._deployment)
            span.set_attribute("embedding.text_length", len(text))
            start = time.perf_counter()
            try:
                response = self._client.embeddings.create(
                    input=text,
                    model=self._deployment,
                )
            except Exception as exc:  # pragma: no cover - network failure
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise RuntimeError(f"Azure OpenAI embeddings request failed: {exc}") from exc

            elapsed_ms = (time.perf_counter() - start) * 1000.0
            data = getattr(response, "data", None)
            if not data:
                message = "Azure OpenAI embeddings response is missing data"
                span.set_status(Status(StatusCode.ERROR, message))
                raise RuntimeError(message)

            first_item = data[0]
            embedding = getattr(first_item, "embedding", None)
            if embedding is None:
                message = "Azure OpenAI embeddings response item missing embedding vector"
                span.set_status(Status(StatusCode.ERROR, message))
                raise RuntimeError(message)

            span.set_attribute("embedding.dimension", len(embedding))
            span.set_attribute("latency.ms", elapsed_ms)
            self._logger.debug("Generated embedding with %d dimensions", len(embedding))
            return embedding


@dataclass
class RetrievalResult:
    url: str
    content: Optional[str]
    doc_type: Optional[str]
    score: Optional[float]
    raw: dict
    snippet: Optional[str] = None


def build_embedding_client_from_env() -> EmbeddingClient:
    deployment = os.environ.get(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        os.environ.get("EMBEDDINGS_MODEL_DEPLOYMENT_NAME"),
    )
    if not deployment:
        raise RuntimeError(
            "Missing Azure OpenAI embedding deployment. Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT or EMBEDDINGS_MODEL_DEPLOYMENT_NAME."
        )

    return EmbeddingClient(deployment)


def build_rbac_connection_string(endpoint: str) -> str:
    parsed = urlparse(endpoint.strip())
    host = parsed.netloc or parsed.path or endpoint
    host = host.strip("/")
    if host.startswith("https://"):
        host = host[len("https://") :]
    if host.startswith("http://"):
        host = host[len("http://") :]
    if ":" in host:
        host = host.split(":", 1)[0]
    if not host:
        raise ValueError("Invalid COSMOS_DB_ENDPOINT; unable to identify host")

    if host.endswith(".mongocluster.cosmos.azure.com"):
        return (
            f"mongodb+srv://{host}/?tls=true&authMechanism=MONGODB-OIDC&"
            "retrywrites=false&maxIdleTimeMS=120000"
        )

    return (
        f"mongodb://{host}:10255/?ssl=true&replicaSet=globaldb&retrywrites=false&"
        "maxIdleTimeMS=120000&authMechanism=MONGODB-OIDC"
    )


def connect_to_cosmos(
    connection_string: str,
    database_name: str,
    *,
    credential: Optional[DefaultAzureCredential] = None,
    appname: str = "venmo-agent",
) -> pymongo.database.Database:
    credential = credential or DefaultAzureCredential()
    auth_properties = {"OIDC_CALLBACK": AzureIdentityTokenCallback(credential)}
    client = pymongo.MongoClient(
        connection_string,
        appname=appname,
        retryWrites=False,
        authMechanismProperties=auth_properties,
    )
    return client[database_name]


def infer_collection_from_query(query: str, *, default: str = DEFAULT_COLLECTION_NAME) -> str:
    """Pick an appropriate collection based on brand keywords in the query."""

    text = (query or "").lower()
    if "venmo" in text:
        return VENMO_COLLECTION_NAME
    if "paypal" in text:
        return DEFAULT_COLLECTION_NAME
    return default


def normalize_similarity(similarity: str) -> str:
    mapping = {
        "cos": "COS",
        "cosine": "COS",
        "cosine_distance": "COS",
        "l2": "L2",
        "euclidean": "L2",
        "ip": "IP",
        "innerproduct": "IP",
        "inner_product": "IP",
        "dot": "IP",
        "dotproduct": "IP",
    }
    key = similarity.lower().strip()
    if key not in mapping:
        raise ValueError(
            f"Unsupported similarity metric '{similarity}'. Choose from cosine, euclidean/L2, or inner product/IP."
        )
    return mapping[key]


def detect_vector_dimensions(collection: Collection, vector_field: str) -> Optional[int]:
    try:
        for index in collection.list_indexes():
            key_spec = index.get("key", {})
            if key_spec.get(vector_field) == "cosmosSearch":
                options = index.get("cosmosSearchOptions") or {}
                dimensions = options.get("dimensions")
                if dimensions:
                    return int(dimensions)
    except Exception as exc:  # pragma: no cover - connection failure
        logging.debug("Unable to inspect vector index dimensions: %s", exc)
    return None


def align_embedding_dimensions(vector: List[float], target: Optional[int]) -> List[float]:
    if target is None or len(vector) == target:
        return vector
    if len(vector) > target:
        return vector[:target]
    if len(vector) < target:
        return vector + [0.0] * (target - len(vector))
    return vector


def build_vector_search_pipeline(
    aligned_embedding: List[float],
    vector_field: str,
    top_k: int,
    num_candidates: int,
    filters: Optional[Dict[str, Any]] = None,
    index_name: Optional[str] = None,
) -> List[dict]:
    search_stage: Dict[str, Any] = {
        "$vectorSearch": {
            "path": vector_field,
            "queryVector": aligned_embedding,
            "numCandidates": num_candidates,
            "limit": top_k,
        }
    }
    if index_name:
        search_stage["$vectorSearch"]["index"] = index_name

    pipeline: List[dict] = [search_stage]

    if filters:
        pipeline.append({"$match": filters})

    pipeline.append(
        {
            "$project": {
                "_id": 0,
                "url": 1,
                "doc_type": 1,
                "content": {"$substrCP": ["$content", 0, 512]},
                "snippet": {"$substrCP": ["$content", 0, 200]},
                "score": {"$meta": "vectorSearchScore"},
            }
        }
    )

    return pipeline


def fallback_vector_search_pipeline(
    aligned_embedding: List[float],
    vector_field: str,
    top_k: int,
    num_candidates: int,
    filters: Optional[Dict[str, Any]] = None,
    index_name: Optional[str] = None,
) -> List[dict]:
    pipeline: List[dict] = [
        {
            "$vectorSearch": {
                "path": vector_field,
                "vector": aligned_embedding,
                "k": top_k,
                "numCandidates": num_candidates,
            }
        }
    ]

    if index_name:
        pipeline[0]["$vectorSearch"]["index"] = index_name

    if filters:
        pipeline.append({"$match": filters})

    pipeline.append(
        {
            "$project": {
                "_id": 0,
                "url": 1,
                "doc_type": 1,
                "content": {"$substrCP": ["$content", 0, 512]},
                "snippet": {"$substrCP": ["$content", 0, 200]},
                "score": {"$meta": "vectorSearchScore"},
            }
        }
    )

    return pipeline


class CosmosVectorRetriever:
    """Convenience wrapper for issuing vector searches against Cosmos Mongo vCore."""

    def __init__(
        self,
        collection: Collection,
        embedder: EmbeddingClient,
        *,
        vector_field: str = "embedding",
        similarity: str = "cosine",
        max_dimensions: int = COSMOS_VECTOR_DIMENSION_LIMIT,
        vector_index: Optional[str] = None,
    ) -> None:
        self._collection = collection
        self._embedder = embedder
        self._vector_field = vector_field
        self._similarity = normalize_similarity(similarity)
        self._max_dimensions = max_dimensions
        self._index_dimensions = detect_vector_dimensions(collection, vector_field)
        self._vector_index = vector_index

    @classmethod
    def from_env(
        cls,
        *,
        connection_string: Optional[str] = None,
        database: Optional[str] = None,
        collection: Optional[str] = None,
        vector_field: str = "embedding",
        similarity: str = "cosine",
        vector_index: Optional[str] = None,
        credential: Optional[DefaultAzureCredential] = None,
        appname: str = "venmo-agent",
    ) -> "CosmosVectorRetriever":
        connection_string = connection_string or os.environ.get("AZURE_COSMOS_CONNECTION_STRING") or os.environ.get(
            "COSMOS_CONNECTION_STRING"
        )
        if not connection_string:
            endpoint = os.environ.get("COSMOS_DB_ENDPOINT")
            if endpoint:
                connection_string = build_rbac_connection_string(endpoint)
        if not connection_string:
            raise ValueError(
                "Provide a connection string via AZURE_COSMOS_CONNECTION_STRING, COSMOS_CONNECTION_STRING, COSMOS_DB_ENDPOINT, or constructor argument."
            )

        database_name = (
            database
            or os.environ.get("AZURE_COSMOS_DATABASE_NAME")
            or os.environ.get("COSMOS_DATABASE")
            or DEFAULT_DATABASE_NAME
        )

        collection_name = (
            collection
            or os.environ.get("AZURE_COSMOS_COLLECTION_NAME")
            or os.environ.get("COSMOS_COLLECTION")
            or DEFAULT_COLLECTION_NAME
        )

        normalized_similarity = normalize_similarity(similarity)
        index_name = (
            vector_index
            or os.environ.get("AZURE_COSMOS_VECTOR_INDEX_NAME")
            or os.environ.get("COSMOS_VECTOR_INDEX_NAME")
            or os.environ.get("COSMOS_VECTOR_INDEX")
        )

        if credential is not None:
            db = connect_to_cosmos(connection_string, database_name, credential=credential, appname=appname)
            collection_ref = db[collection_name]
            embedder = build_embedding_client_from_env()
            return cls(
                collection_ref,
                embedder,
                vector_field=vector_field,
                similarity=normalized_similarity,
                vector_index=index_name,
            )

        return _get_cached_retriever(
            connection_string,
            database_name,
            collection_name,
            vector_field,
            normalized_similarity,
            index_name,
            appname,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        num_candidates: int = DEFAULT_NUM_CANDIDATES,
        filters: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
    ) -> List[RetrievalResult]:
        if not query.strip():
            raise ValueError("Query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        num_candidates = max(num_candidates, top_k)

        metrics_dict = metrics if metrics is not None else None
        total_start = time.perf_counter()

        with tracer.start_as_current_span("cosmos.vector.search") as span:
            span.set_attribute("db.system", "cosmosdb-mongodb")
            span.set_attribute("db.cosmos.collection", self._collection.name)
            span.set_attribute("db.cosmos.database", self._collection.database.name)
            span.set_attribute("vector.top_k", top_k)
            span.set_attribute("vector.num_candidates", num_candidates)
            span.set_attribute("vector.field", self._vector_field)
            span.set_attribute("vector.similarity", self._similarity)
            span.set_attribute("vector.index_dimensions", self._index_dimensions or 0)
            span.set_attribute("vector.index_name", self._vector_index or "")
            span.set_attribute("query.length", len(query))

            embed_start = time.perf_counter()
            query_embedding = self._embedder.embed(query)
            embedding_latency_ms = (time.perf_counter() - embed_start) * 1000.0
            span.set_attribute("latency.embedding_ms", embedding_latency_ms)
            if metrics_dict is not None:
                metrics_dict["embedding_ms"] = embedding_latency_ms
            span.set_attribute("embedding.input_dimension", len(query_embedding))

            target_dimensions = self._index_dimensions or min(len(query_embedding), self._max_dimensions)
            aligned_embedding = align_embedding_dimensions(query_embedding, target_dimensions)
            if len(aligned_embedding) > self._max_dimensions:
                aligned_embedding = aligned_embedding[: self._max_dimensions]
            span.set_attribute("embedding.aligned_dimension", len(aligned_embedding))

            primary_pipeline = build_vector_search_pipeline(
                aligned_embedding=aligned_embedding,
                vector_field=self._vector_field,
                top_k=top_k,
                num_candidates=num_candidates,
                filters=filters,
                index_name=self._vector_index,
            )

            logging.debug(
                "Vector search params: limit=%s numCandidates=%s similarity=%s indexDims=%s payloadDims=%s",
                top_k,
                num_candidates,
                self._similarity,
                self._index_dimensions,
                len(aligned_embedding),
            )

            documents: List[dict]
            aggregate_latency_ms: float
            fallback_used = False
            try:
                documents, aggregate_latency_ms = self._execute_pipeline(
                    primary_pipeline,
                    span_name="cosmos.mongo.aggregate",
                )
            except OperationFailure as exc:
                message = str(exc)
                logging.warning("Primary vector search pipeline failed: %s", message)
                if "$vectorSearch.queryVector" in message or "UnknownBsonField" in message:
                    fallback_pipeline = fallback_vector_search_pipeline(
                        aligned_embedding=aligned_embedding,
                        vector_field=self._vector_field,
                        top_k=top_k,
                        num_candidates=num_candidates,
                        filters=filters,
                        index_name=self._vector_index,
                    )
                    documents, aggregate_latency_ms = self._execute_pipeline(
                        fallback_pipeline,
                        span_name="cosmos.mongo.aggregate.fallback",
                        is_fallback=True,
                    )
                    fallback_used = True
                else:
                    span.record_exception(exc)
                    raise

            span.set_attribute("latency.aggregate_ms", aggregate_latency_ms)
            span.set_attribute("vector.fallback_used", fallback_used)
            if metrics_dict is not None:
                metrics_dict["aggregate_ms"] = aggregate_latency_ms
                metrics_dict["fallback_used"] = fallback_used

            results: List[RetrievalResult] = []
            for doc in documents:
                score = doc.get("score") or doc.get("$vectorSearchScore") or doc.get("$searchScore")
                results.append(
                    RetrievalResult(
                        url=doc.get("url", ""),
                        content=doc.get("content"),
                        doc_type=doc.get("doc_type"),
                        score=score,
                        raw=doc,
                        snippet=doc.get("snippet"),
                    )
                )

            span.set_attribute("vector.result_count", len(results))
            total_latency_ms = (time.perf_counter() - total_start) * 1000.0
            span.set_attribute("latency.total_ms", total_latency_ms)
            if metrics_dict is not None:
                metrics_dict["total_ms"] = total_latency_ms
            return results

    def _execute_pipeline(
        self,
        pipeline: List[dict],
        *,
        span_name: str,
        is_fallback: bool = False,
    ) -> Tuple[List[dict], float]:
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("db.system", "cosmosdb-mongodb")
            span.set_attribute("db.cosmos.collection", self._collection.name)
            span.set_attribute("db.operation", "aggregate")
            span.set_attribute("vector.pipeline_length", len(pipeline))
            span.set_attribute("vector.fallback", is_fallback)
            start = time.perf_counter()
            try:
                cursor = self._collection.aggregate(pipeline)
                documents = list(cursor)
                latency_ms = (time.perf_counter() - start) * 1000.0
                span.set_attribute("latency.ms", latency_ms)
                span.set_attribute("vector.candidate_count", len(documents))
                logging.debug("Retrieved %d documents from vector search", len(documents))
                logging.debug("Vector search took %.2f ms", latency_ms)

                return documents, latency_ms
            except OperationFailure as exc:
                span.record_exception(exc)
                failure_latency = (time.perf_counter() - start) * 1000.0
                span.set_attribute("latency.ms", failure_latency)
                raise


@lru_cache(maxsize=8)
def _get_cached_retriever(
    connection_string: str,
    database_name: str,
    collection_name: str,
    vector_field: str,
    similarity: str,
    vector_index: Optional[str],
    appname: str,
) -> "CosmosVectorRetriever":
    credential = DefaultAzureCredential()
    db = connect_to_cosmos(connection_string, database_name, credential=credential, appname=appname)
    collection_ref = db[collection_name]
    embedder = build_embedding_client_from_env()
    return CosmosVectorRetriever(
        collection_ref,
        embedder,
        vector_field=vector_field,
        similarity=similarity,
        vector_index=vector_index,
    )


def one_shot_query(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
    connection_string: Optional[str] = None,
    database: Optional[str] = None,
    collection: Optional[str] = None,
    vector_field: str = "embedding",
    similarity: str = "cosine",
    vector_index: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    include_metrics: bool = False,
) -> Any:
    metrics: Optional[Dict[str, float]] = {} if include_metrics else None
    retriever_start = time.perf_counter()
    retriever = CosmosVectorRetriever.from_env(
        connection_string=connection_string,
        database=database,
        collection=collection,
        vector_field=vector_field,
        similarity=similarity,
        vector_index=vector_index,
    )
    retriever_latency_ms = (time.perf_counter() - retriever_start) * 1000.0
    if metrics is not None:
        metrics["retriever_init_ms"] = retriever_latency_ms

    results = retriever.search(
        query,
        top_k=top_k,
        num_candidates=num_candidates,
        filters=filters,
        metrics=metrics,
    )
    if include_metrics:
        return results, metrics or {}
    return results


_warmup_lock = threading.Lock()
_warmup_inflight = False


def schedule_cosmos_retriever_warmup(
    *,
    connection_string: Optional[str] = None,
    database: Optional[str] = None,
    collection: Optional[str] = None,
    vector_field: str = "embedding",
    similarity: str = "cosine",
    vector_index: Optional[str] = None,
    appname: str = "venmo-agent",
) -> bool:
    """Warm the Cosmos retriever cache on a background thread.

    Returns ``True`` when a warmup task was scheduled. The task exits quietly when
    configuration is missing or an error occurs.
    """

    disable_flag = os.environ.get("VOICELIVE_DISABLE_COSMOS_WARMUP", "").lower()
    if disable_flag in {"1", "true", "yes", "on"}:
        logger.debug("Cosmos retriever warmup disabled via VOICELIVE_DISABLE_COSMOS_WARMUP")
        return False

    if "PYTEST_CURRENT_TEST" in os.environ:
        logger.debug("Skipping Cosmos retriever warmup during pytest execution")
        return False

    global _warmup_inflight
    with _warmup_lock:
        if _warmup_inflight:
            return False
        _warmup_inflight = True

    def _warmup() -> None:
        start_time = time.perf_counter()
        try:
            CosmosVectorRetriever.from_env(
                connection_string=connection_string,
                database=database,
                collection=collection,
                vector_field=vector_field,
                similarity=similarity,
                vector_index=vector_index,
                appname=appname,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.debug("Cosmos retriever warmup completed in %.2f ms", elapsed_ms)
        except ValueError as exc:
            logger.debug("Cosmos retriever warmup skipped: %s", exc)
        except Exception as exc:  # pragma: no cover - best effort warmup
            logger.warning("Cosmos retriever warmup failed: %s", exc)
        finally:
            with _warmup_lock:
                global _warmup_inflight
                _warmup_inflight = False

    thread = threading.Thread(target=_warmup, name="cosmos-retriever-warmup", daemon=True)
    thread.start()
    return True


__all__ = [
    "AzureIdentityTokenCallback",
    "EmbeddingClient",
    "RetrievalResult",
    "CosmosVectorRetriever",
    "DEFAULT_TOP_K",
    "DEFAULT_NUM_CANDIDATES",
    "DEFAULT_DATABASE_NAME",
    "DEFAULT_COLLECTION_NAME",
    "one_shot_query",
    "schedule_cosmos_retriever_warmup",
]
