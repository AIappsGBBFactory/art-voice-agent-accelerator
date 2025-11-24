"""
Reusable Azure AI Search vector retrieval helpers for VoiceLive agents.
"""

# -------------------------
# AI Search Retrieval Tool
# -------------------------

from typing import List, Dict, Any
from agents.shared.rag_retrieval import build_embedding_client_from_env
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

# initialize your embedder once
embedder = build_embedding_client_from_env()

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=AzureKeyCredential(SEARCH_API_KEY)
)


def tool_query_ai_search(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Simple vector + keyword search against Azure AI Search.
    Returns title, file_name, snippet, and score.
    """

    # 1 - embed query
    embedding = embedder.embed(query)

    # 2 - execute hybrid vector + keyword search
    results = search_client.search(
        search_text=query,
        vector_queries=[{
            "kind": "vector",
            "vector": embedding,
            "fields": "vector",   # your embedding field
            "k": top_k
        }],
        top=top_k
    )

    # 3 - convert results into clean dicts
    output = []
    for result in results:
        output.append({
            "title": result.get("title"),
            "file_name": result.get("file_name"),
            "snippet": (result.get("content") or "")[:300],
            "score": result.get("@search.score")
        })

    return output
