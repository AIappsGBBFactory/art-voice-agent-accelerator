"""
Reusable Azure AI Search vector retrieval helpers for VoiceLive agents.

This module provides RAG (Retrieval Augmented Generation) tools for querying
credit card FAQs and product information from Azure AI Search.
"""

# -------------------------
# AI Search Retrieval Tool
# -------------------------

import os
import logging
from typing import List, Dict, Any, Optional
from functools import lru_cache

from dotenv import load_dotenv
from opentelemetry import trace
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI

# Load environment variables
load_dotenv(override=True)

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)

# Azure AI Search Configuration from environment
SEARCH_ENDPOINT = os.environ.get("AZURE_AI_SEARCH_SERVICE_ENDPOINT", "")
SEARCH_API_KEY = os.environ.get("AZURE_AI_SEARCH_ADMIN_KEY", "")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX_NAME", "")

# Azure OpenAI Configuration for embeddings
AOAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AOAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AOAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
EMBED_MODEL = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
MODEL_DIMENSIONS = int(os.environ.get("MODEL_DIMENSIONS", "3072"))

# Known card names for fuzzy matching
KNOWN_CARD_NAMES = [
    "Premium Rewards",
    "Travel Rewards", 
    "Unlimited Cash Rewards",
    "Customized Cash Rewards",
    "BankAmericard",
    "Elite",
]


@lru_cache(maxsize=1)
def _get_aoai_client() -> AzureOpenAI:
    """Get cached Azure OpenAI client for embeddings."""
    return AzureOpenAI(
        api_key=AOAI_KEY,
        api_version=AOAI_API_VERSION,
        azure_endpoint=AOAI_ENDPOINT
    )


@lru_cache(maxsize=1)
def _get_search_client() -> SearchClient:
    """Get cached Azure AI Search client."""
    return SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=SEARCH_INDEX,
        credential=AzureKeyCredential(SEARCH_API_KEY)
    )


def _generate_embedding(text: str) -> List[float]:
    """Generate embedding vector for the given text using Azure OpenAI."""
    with tracer.start_as_current_span("ai_search.generate_embedding") as span:
        span.set_attribute("embedding.model", EMBED_MODEL)
        span.set_attribute("embedding.text_length", len(text))
        
        try:
            client = _get_aoai_client()
            response = client.embeddings.create(
                model=EMBED_MODEL,
                input=text,
                dimensions=MODEL_DIMENSIONS
            )
            embedding = response.data[0].embedding
            span.set_attribute("embedding.dimensions", len(embedding))
            return embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            span.record_exception(e)
            raise


def _normalize_card_name(card_name: str) -> Optional[str]:
    """
    Normalize card name input to match indexed card names.
    Returns the canonical card name or None if no match found.
    """
    if not card_name:
        return None
    
    # Clean input
    card_name_lower = card_name.lower().strip()
    
    # Direct match check
    for known in KNOWN_CARD_NAMES:
        if known.lower() == card_name_lower:
            return known
    
    # Partial match (e.g., "premium" -> "Premium Rewards")
    for known in KNOWN_CARD_NAMES:
        if card_name_lower in known.lower() or known.lower() in card_name_lower:
            return known
    
    # Common abbreviations
    abbreviations = {
        "premium": "Premium Rewards",
        "travel": "Travel Rewards",
        "unlimited": "Unlimited Cash Rewards",
        "unlimited cash": "Unlimited Cash Rewards",
        "customized": "Customized Cash Rewards",
        "customized cash": "Customized Cash Rewards",
        "bankamericard": "BankAmericard",
        "elite": "Elite",
    }
    
    for abbrev, full_name in abbreviations.items():
        if abbrev in card_name_lower:
            return full_name
    
    return None


def search_credit_card_faqs(
    query: str,
    card_name: Optional[str] = None,
    top_k: int = 5,
    include_scores: bool = False
) -> Dict[str, Any]:
    """
    Search credit card FAQs and product information using hybrid vector + keyword search.
    
    This tool retrieves relevant information about credit card features, benefits,
    fees, eligibility requirements, and frequently asked questions from the 
    Azure AI Search knowledge base.
    
    Args:
        query: Natural language question about credit cards (e.g., "What are the foreign 
               transaction fees?", "What credit score do I need?")
        card_name: Optional filter to search within a specific card's documentation.
                   Examples: "Premium Rewards", "Travel Rewards", "Unlimited Cash Rewards"
                   If provided, results will only come from that card's documents.
        top_k: Maximum number of relevant passages to return (default: 5)
        include_scores: Whether to include relevance scores in results
        
    Returns:
        Dictionary containing:
        - success: bool indicating if search was successful
        - results: List of relevant passages with title, card_name, content snippet, and source
        - count: Number of results found
        - filter_applied: The card_name filter that was applied (if any)
        - error: Error message if search failed
    """
    with tracer.start_as_current_span("ai_search.search_credit_card_faqs") as span:
        span.set_attribute("search.query", query)
        span.set_attribute("search.top_k", top_k)
        span.set_attribute("search.index", SEARCH_INDEX)
        span.set_attribute("search.card_name_filter", card_name or "none")
        
        # Validate configuration
        if not SEARCH_ENDPOINT or not SEARCH_API_KEY or not SEARCH_INDEX:
            error_msg = "Azure AI Search is not configured. Missing AZURE_AI_SEARCH_SERVICE_ENDPOINT, AZURE_AI_SEARCH_ADMIN_KEY, or AZURE_SEARCH_INDEX_NAME."
            logger.error(error_msg)
            span.set_attribute("search.error", error_msg)
            return {
                "success": False,
                "results": [],
                "count": 0,
                "filter_applied": None,
                "error": error_msg
            }
        
        if not query or not query.strip():
            return {
                "success": False,
                "results": [],
                "count": 0,
                "filter_applied": None,
                "error": "Query cannot be empty"
            }
        
        try:
            # Generate embedding for semantic search
            embedding = _generate_embedding(query)
            
            # Get search client
            search_client = _get_search_client()
            
            # Build filter if card_name provided
            filter_expression = None
            normalized_card_name = None
            if card_name:
                normalized_card_name = _normalize_card_name(card_name)
                if normalized_card_name:
                    filter_expression = f"card_name eq '{normalized_card_name}'"
                    span.set_attribute("search.filter", filter_expression)
                    logger.info(f"Applying filter: {filter_expression}")
            
            # Execute hybrid search (vector + keyword) with optional filter
            search_kwargs = {
                "search_text": query,
                "vector_queries": [{
                    "kind": "vector",
                    "vector": embedding,
                    "fields": "vector",
                    "k": top_k
                }],
                "top": top_k,
                "select": ["title", "card_name", "content", "file_name"]
            }
            
            if filter_expression:
                search_kwargs["filter"] = filter_expression
            
            results = search_client.search(**search_kwargs)
            
            # Process results
            output_results = []
            for result in results:
                result_item = {
                    "title": result.get("title", "Unknown"),
                    "card_name": result.get("card_name", "Unknown"),
                    "content": (result.get("content") or "")[:500],  # Truncate for voice
                    "source": result.get("file_name", "")
                }
                if include_scores:
                    result_item["score"] = result.get("@search.score", 0)
                output_results.append(result_item)
            
            span.set_attribute("search.result_count", len(output_results))
            logger.info(f"AI Search returned {len(output_results)} results for query: {query[:50]}...")
            
            return {
                "success": True,
                "results": output_results,
                "count": len(output_results),
                "filter_applied": normalized_card_name,
                "query": query
            }
            
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            logger.error(error_msg)
            span.record_exception(e)
            span.set_attribute("search.error", error_msg)
            return {
                "success": False,
                "results": [],
                "count": 0,
                "filter_applied": None,
                "error": error_msg
            }


# Alias for backward compatibility and simpler tool name
def tool_query_credit_card_info(query: str, card_name: Optional[str] = None, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Simple wrapper for credit card FAQ search.
    Returns list of relevant passages for the agent to use in responses.
    """
    result = search_credit_card_faqs(query, card_name=card_name, top_k=top_k)
    if result["success"]:
        return result["results"]
    return []


async def execute_search_credit_card_faqs(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    VoiceLive executor wrapper for search_credit_card_faqs.
    
    This async function properly unpacks the arguments dict that VoiceLive
    passes to tool executors and calls the underlying search function.
    """
    # Extract and validate arguments from the dict
    query = arguments.get("query")
    if query is None:
        return {
            "success": False,
            "results": [],
            "count": 0,
            "filter_applied": None,
            "error": "Query parameter is required"
        }
    
    # Handle case where query might be passed as dict (shouldn't happen but be safe)
    if isinstance(query, dict):
        query = query.get("query", str(query))
    
    query = str(query).strip() if query else ""
    
    card_name = arguments.get("card_name")
    if card_name and isinstance(card_name, dict):
        card_name = card_name.get("card_name", str(card_name))
    card_name = str(card_name).strip() if card_name else None
    
    top_k = arguments.get("top_k", 5)
    if isinstance(top_k, str):
        try:
            top_k = int(top_k)
        except ValueError:
            top_k = 5
    
    include_scores = arguments.get("include_scores", False)
    
    # Call the synchronous search function
    # Since it does I/O, we could use asyncio.to_thread but the Azure SDK
    # handles this reasonably well for now
    return search_credit_card_faqs(
        query=query,
        card_name=card_name,
        top_k=top_k,
        include_scores=include_scores
    )


__all__ = [
    "search_credit_card_faqs",
    "execute_search_credit_card_faqs",
    "tool_query_credit_card_info",
    "KNOWN_CARD_NAMES",
]