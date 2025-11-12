"""Knowledge base retrieval behaviour for Venmo agent."""

from __future__ import annotations

import pytest

from apps.rtagent.backend.src.agents.shared.rag_retrieval import RetrievalResult
from apps.rtagent.backend.src.agents.vlagent import tools as venmo_tools


@pytest.mark.asyncio
async def test_search_knowledge_base_metrics_and_index(monkeypatch):
    """Ensure KB searches attach filters, capture latency, and pass vector index."""

    fake_results = [
        RetrievalResult(
            url="https://support.venmo.com/articles/transfer-limits",
            content="Venmo transfer limits apply to person-to-person payments.",
            doc_type="venmo_support",
            score=0.91,
            raw={"content": "Venmo transfer limits apply to person-to-person payments."},
            snippet="Venmo transfer limits apply to person-to-person payments.",
        )
    ]

    captured: dict[str, object] = {}

    def fake_one_shot_query(
        query: str,
        *,
        top_k: int,
        num_candidates: int,
        database: str,
        collection: str,
        vector_index: str | None,
        filters: dict | None,
        include_metrics: bool = False,
    ):
        captured["query"] = query
        captured["top_k"] = top_k
        captured["num_candidates"] = num_candidates
        captured["database"] = database
        captured["collection"] = collection
        captured["filters"] = filters
        captured["vector_index"] = vector_index
        metrics = {
            "retriever_init_ms": 4.0,
            "embedding_ms": 12.0,
            "aggregate_ms": 18.0,
            "total_ms": 34.0,
            "fallback_used": False,
        }
        if include_metrics:
            return fake_results, metrics
        return fake_results

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    perf_calls: list[float] = []

    def fake_perf_counter() -> float:
        base = 100.0
        step = 0.05
        value = base + step * len(perf_calls)
        perf_calls.append(value)
        return value

    monkeypatch.setenv("VOICELIVE_KB_VECTOR_INDEX", "venmo-hnsw-index")
    monkeypatch.setattr(venmo_tools, "DEFAULT_TOP_K", 6, raising=False)
    monkeypatch.setattr(venmo_tools, "DEFAULT_NUM_CANDIDATES", 24, raising=False)
    monkeypatch.setattr(venmo_tools, "one_shot_query", fake_one_shot_query)
    monkeypatch.setattr(venmo_tools.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(venmo_tools.time, "perf_counter", fake_perf_counter)

    response = await venmo_tools.search_knowledge_base(
        "How do I add money to my Venmo balance?",
        doc_type="venmo_support",
    )

    assert captured["query"] == "How do I add money to my Venmo balance?"
    assert captured["filters"] == {"doc_type": "venmo_support"}
    assert captured["top_k"] == 6
    assert captured["num_candidates"] == 24
    assert captured["vector_index"] == "venmo-hnsw-index"

    assert response["success"] is True
    assert response["latency_ms"] == pytest.approx(50.0, abs=0.01)
    assert response["vector_index"] == "venmo-hnsw-index"

    breakdown = response["latency_breakdown"]
    assert breakdown["retriever_init_ms"] == pytest.approx(4.0, abs=0.01)
    assert breakdown["embedding_ms"] == pytest.approx(12.0, abs=0.01)
    assert breakdown["aggregate_ms"] == pytest.approx(18.0, abs=0.01)
    assert breakdown["cosmos_total_ms"] == pytest.approx(34.0, abs=0.01)
    assert breakdown["tool_total_ms"] == pytest.approx(50.0, abs=0.01)
    assert breakdown["fallback_used"] is False

    snippet = response["results"][0]["snippet"]
    assert snippet.startswith("Venmo transfer limits apply")
    assert response["filters"] == {"doc_type": "venmo_support"}