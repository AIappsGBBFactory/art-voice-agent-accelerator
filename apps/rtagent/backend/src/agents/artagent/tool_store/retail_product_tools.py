"""
ARTAgent Retail Product Search Tools
=====================================

This module provides tool functions for the retail multi-agent system:
- Shopping Concierge Agent
- Personal Stylist Agent  
- Post-Sale Agent

Integrates with:
- Azure AI Search (semantic vector search + OData filtering)
- Cosmos DB (product details, inventory, customer data)
- Azure Blob Storage (product images)

Author: Pablo Salvador Lopez
Organization: GBB AI
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from apps.rtagent.backend.src.agents.artagent.tool_store.functions_helper import _json
from utils.ml_logging import get_logger

logger = get_logger("retail_product_tools")

# ═══════════════════════════════════════════════════════════════════
# Azure AI Search & Cosmos DB Clients (Initialize from environment)
# ═══════════════════════════════════════════════════════════════════

# TODO: Initialize these from your app's dependency injection
# from your_app_context import search_client, cosmos_manager, aoai_client

# Placeholder - replace with actual initialization
search_client = None  # Azure SearchClient instance
cosmos_product_manager = None  # Cosmos DB manager for 'products' collection
aoai_client = None  # Azure OpenAI client for embeddings


# ═══════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════

def generate_embedding(text: str) -> List[float]:
    """
    Generate 3072-dim embedding using Azure OpenAI text-embedding-3-large
    
    Args:
        text: Text to embed
    
    Returns:
        List of 3072 floats
    """
    try:
        if not aoai_client:
            logger.error("Azure OpenAI client not initialized")
            return []
        
        response = aoai_client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=3072
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}", exc_info=True)
        return []


def format_product_for_voice(product: Dict[str, Any], score: float = 0.0) -> str:
    """
    Format product data for voice-friendly TTS output
    
    Args:
        product: Product document from Cosmos DB
        score: Relevance score from search
    
    Returns:
        Voice-friendly product description
    """
    try:
        brand = product.get('brand', 'Unknown')
        name = product.get('name', 'Product')
        category = product.get('category', '')
        
        # Pricing
        pricing = product.get('pricing', {})
        base_price = pricing.get('base_price', 0)
        
        # Inventory
        inventory = product.get('inventory', {})
        total_stock = inventory.get('total_stock', 0)
        
        # Colors
        specs = product.get('specifications', {})
        colors = specs.get('colors', [])
        color_str = ', '.join(colors[:3]) if colors else 'various colors'
        
        # Build voice response
        voice_text = f"{brand} {name}. "
        voice_text += f"${base_price:.2f}. "
        voice_text += f"Available in {color_str}. "
        
        if total_stock > 100:
            voice_text += "In stock at all locations. "
        elif total_stock > 0:
            voice_text += "Limited stock available. "
        else:
            voice_text += "Currently out of stock. "
        
        return voice_text
    
    except Exception as e:
        logger.error(f"Product formatting failed: {e}", exc_info=True)
        return "Product information unavailable."


# ═══════════════════════════════════════════════════════════════════
# TOOL 1: General Product Search (Concierge Agent)
# ═══════════════════════════════════════════════════════════════════

class SearchProductsGeneralArgs(TypedDict):
    """Input schema for general product search"""
    query: str  # Natural language search query
    top_k: int  # Number of results (default: 5)


async def search_products_general(args: SearchProductsGeneralArgs) -> Dict[str, Any]:
    """
    CONCIERGE TOOL: Fast semantic product search
    
    Use for direct product queries:
    - "show me jeans"
    - "do you have blue shirts?"  
    - "running shoes"
    
    Args:
        query: Natural language product search
        top_k: Number of products to return (default: 5)
    
    Returns:
        Dict with products, count, and voice_response
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for search_products_general")
        return _json(False, "Invalid search request format.")
    
    try:
        query = (args.get("query") or "").strip()
        top_k = args.get("top_k", 5)
        
        if not query:
            return _json(False, "Please tell me what you're looking for.")
        
        logger.info(f"General search: '{query}' (top_k={top_k})")
        
        # Generate embedding for semantic search
        query_embedding = generate_embedding(query)
        if not query_embedding:
            return _json(False, "Search temporarily unavailable. Please try again.")
        
        # Perform vector search in Azure AI Search
        from azure.search.documents.models import VectorizedQuery
        
        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=top_k,
            fields="desc_vector"
        )
        
        results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            select=["id", "category", "gender", "formality", "colors", "rich_description"],
            top=top_k
        )
        
        # Collect product IDs
        product_ids = []
        search_scores = {}
        for result in results:
            product_id = result["id"]
            product_ids.append(product_id)
            search_scores[product_id] = result.get("@search.score", 0)
        
        if not product_ids:
            return _json(
                True,
                f"I couldn't find any products matching '{query}'. Would you like to try a different search?",
                count=0,
                products=[]
            )
        
        # Retrieve full details from Cosmos DB
        query_filter = {"product_id": {"$in": product_ids}}
        documents = await asyncio.to_thread(
            cosmos_product_manager.query_documents,
            query=query_filter
        )
        
        if not documents:
            return _json(False, "Found matches but couldn't retrieve details. Please try again.")
        
        # Format for voice response
        voice_response = f"I found {len(documents)} option{'s' if len(documents) > 1 else ''} for you. "
        
        for idx, product in enumerate(documents[:3], 1):  # Limit to 3 for voice
            score = search_scores.get(product['product_id'], 0)
            voice_response += format_product_for_voice(product, score)
        
        if len(documents) > 3:
            voice_response += f"I have {len(documents) - 3} more options if you'd like to see them. "
        
        voice_response += "Would you like more details on any of these?"
        
        return _json(
            True,
            voice_response,
            count=len(documents),
            products=documents,
            tool="search_products_general"
        )
    
    except Exception as e:
        logger.error(f"General search failed: {e}", exc_info=True)
        return _json(False, "Search error occurred. Please try again.")


# ═══════════════════════════════════════════════════════════════════
# TOOL 2: Filtered Product Search (Stylist Agent)
# ═══════════════════════════════════════════════════════════════════

class SearchProductsFilteredArgs(TypedDict):
    """Input schema for filtered stylist search"""
    query: str
    occasion: Optional[str]  # wedding, birthday, work, casual, date_night, interview
    weather: Optional[str]   # warm, mild, cold, rainy
    formality: Optional[str]  # casual, business_casual, formal, athletic
    gender: Optional[str]     # Men, Women, Unisex
    age_group: Optional[str]  # teen, young_adult, adult, senior
    colors: Optional[List[str]]  # Preferred colors
    top_k: int


async def search_products_filtered(args: SearchProductsFilteredArgs) -> Dict[str, Any]:
    """
    STYLIST TOOL: Contextual product search with advanced filtering
    
    Use for personalized styling recommendations:
    - "find outfit for grandma's birthday"
    - "wedding attire for winter"
    - "casual summer clothes"
    
    Applies Azure AI Search OData filters for precise matching.
    
    Args:
        query: Semantic search query
        occasion: Event type (optional)
        weather: Climate filter (optional)
        formality: Style level (optional)
        gender: Target gender (optional)
        age_group: Age category (used semantically, not as filter)
        colors: Preferred colors (optional)
        top_k: Number of results (default: 5)
    
    Returns:
        Filtered products with styling context
    """
    if not isinstance(args, dict):
        logger.error("Invalid args type for search_products_filtered")
        return _json(False, "Invalid styling search request.")
    
    try:
        query = (args.get("query") or "").strip()
        occasion = args.get("occasion")
        weather = args.get("weather")
        formality = args.get("formality")
        gender = args.get("gender")
        age_group = args.get("age_group")
        colors = args.get("colors") or []
        top_k = args.get("top_k", 5)
        
        if not query:
            return _json(False, "Please describe what style you're looking for.")
        
        logger.info(f"Stylist search: '{query}' | occasion={occasion}, weather={weather}, formality={formality}")
        
        # Generate embedding
        query_embedding = generate_embedding(query)
        if not query_embedding:
            return _json(False, "Search temporarily unavailable.")
        
        # Build OData filter string
        filter_parts = []
        
        if formality:
            filter_parts.append(f"formality eq '{formality}'")
        
        if gender:
            filter_parts.append(f"gender eq '{gender}'")
        
        if weather:
            filter_parts.append(f"climate/any(c: c eq '{weather}')")
        
        if colors:
            color_filters = [f"colors/any(col: col eq '{color}')" for color in colors]
            if color_filters:
                filter_parts.append(f"({' or '.join(color_filters)})")
        
        filter_expression = " and ".join(filter_parts) if filter_parts else None
        
        logger.info(f"Filter: {filter_expression or 'None (pure semantic)'}")
        
        # Vector search with filters
        from azure.search.documents.models import VectorizedQuery
        
        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=top_k * 2,  # Get more to filter
            fields="desc_vector"
        )
        
        results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            filter=filter_expression,
            select=["id", "category", "gender", "formality", "colors", "climate", "rich_description"],
            top=top_k
        )
        
        # Collect results
        product_ids = []
        search_scores = {}
        for idx, result in enumerate(results, 1):
            if idx > top_k:
                break
            product_id = result["id"]
            product_ids.append(product_id)
            search_scores[product_id] = result.get("@search.score", 0)
        
        if not product_ids:
            relaxation_msg = "I couldn't find products matching all those criteria. "
            if colors:
                relaxation_msg += "Let's try without the color filter, or would you like to try a different color?"
            elif weather:
                relaxation_msg += "Let's try with more flexible weather options."
            else:
                relaxation_msg += "Could you tell me more about what you're looking for?"
            
            return _json(
                True,
                relaxation_msg,
                count=0,
                products=[],
                filters_applied={"occasion": occasion, "weather": weather, "formality": formality, "gender": gender, "colors": colors}
            )
        
        # Get full details from Cosmos DB
        query_filter = {"product_id": {"$in": product_ids}}
        documents = await asyncio.to_thread(
            cosmos_product_manager.query_documents,
            query=query_filter
        )
        
        # Build personalized stylist response
        voice_response = "Based on your needs, here are my personalized recommendations. "
        
        if occasion:
            voice_response += f"Perfect for {occasion.replace('_', ' ')}. "
        
        if weather:
            voice_response += f"Great for {weather} weather. "
        
        voice_response += f"I found {len(documents)} great option{'s' if len(documents) > 1 else ''} for you. "
        
        for idx, product in enumerate(documents[:3], 1):
            score = search_scores.get(product['product_id'], 0)
            voice_response += format_product_for_voice(product, score)
        
        # Add styling tip based on occasion
        if occasion == "wedding":
            voice_response += "For weddings, consider adding elegant accessories to complete the look. "
        elif occasion == "interview":
            voice_response += "Professional tip: Keep colors neutral and cuts classic for interviews. "
        elif occasion == "birthday":
            voice_response += "Birthday parties are great for showing personality with color and style! "
        
        voice_response += "Would you like to see complementary pieces to complete the outfit?"
        
        return _json(
            True,
            voice_response,
            count=len(documents),
            products=documents,
            filters_applied={"occasion": occasion, "weather": weather, "formality": formality, "gender": gender, "age_group": age_group, "colors": colors},
            tool="search_products_filtered"
        )
    
    except Exception as e:
        logger.error(f"Filtered search failed: {e}", exc_info=True)
        return _json(False, "Styling search error. Let me try a simpler search.")


# ═══════════════════════════════════════════════════════════════════
# TOOL 3: Product Availability Check
# ═══════════════════════════════════════════════════════════════════

class CheckProductAvailabilityArgs(TypedDict):
    """Check inventory for specific product"""
    product_id: str
    region: Optional[str]  # US_WEST, US_EAST, US_SOUTH, or None for all


async def check_product_availability(args: CheckProductAvailabilityArgs) -> Dict[str, Any]:
    """
    Check real-time inventory availability
    
    Args:
        product_id: Product identifier
        region: Specific region or None for all regions
    
    Returns:
        Inventory status with regional breakdown
    """
    if not isinstance(args, dict):
        return _json(False, "Invalid availability check request.")
    
    try:
        product_id = (args.get("product_id") or "").strip()
        region = args.get("region")
        
        if not product_id:
            return _json(False, "Product ID required for availability check.")
        
        # Query Cosmos DB for product
        query_filter = {"product_id": product_id}
        documents = await asyncio.to_thread(
            cosmos_product_manager.query_documents,
            query=query_filter
        )
        
        if not documents:
            return _json(False, f"Product {product_id} not found.")
        
        product = documents[0]
        inventory = product.get('inventory', {})
        total_stock = inventory.get('total_stock', 0)
        by_region = inventory.get('by_region', {})
        
        # Build voice response
        if region and region in by_region:
            region_data = by_region[region]
            available = region_data.get('available', 0) if isinstance(region_data, dict) else region_data
            
            if available > 10:
                voice_response = f"Great news! We have {available} units available in {region.replace('_', ' ')}. "
            elif available > 0:
                voice_response = f"Limited stock: {available} units left in {region.replace('_', ' ')}. I'd recommend ordering soon! "
            else:
                voice_response = f"Unfortunately, this item is out of stock in {region.replace('_', ' ')}. "
                # Check other regions
                other_regions = [r for r in by_region.keys() if r != region]
                if other_regions:
                    voice_response += f"But it's available in {', '.join([r.replace('_', ' ') for r in other_regions])}. "
        else:
            if total_stock > 50:
                voice_response = f"In stock! We have {total_stock} units available across all locations. "
            elif total_stock > 0:
                voice_response = f"Limited availability: {total_stock} units left. "
                # Mention which regions
                available_regions = [r for r, data in by_region.items() if (data.get('available', 0) if isinstance(data, dict) else data) > 0]
                if available_regions:
                    voice_response += f"Available in {', '.join([r.replace('_', ' ') for r in available_regions])}. "
            else:
                voice_response = "This item is currently out of stock. Would you like me to find similar alternatives?"
        
        return _json(
            True,
            voice_response,
            product_id=product_id,
            total_stock=total_stock,
            by_region=by_region,
            available=total_stock > 0
        )
    
    except Exception as e:
        logger.error(f"Availability check failed: {e}", exc_info=True)
        return _json(False, "Couldn't check availability. Please try again.")


# ═══════════════════════════════════════════════════════════════════
# Export Tool Registry
# ═══════════════════════════════════════════════════════════════════

# Tool definitions for LLM function calling
RETAIL_TOOLS = {
    "search_products_general": {
        "function": search_products_general,
        "schema": {
            "name": "search_products_general",
            "description": "Fast semantic product search for direct queries. Use when customer asks for specific products without styling context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language product search query (e.g., 'casual jeans', 'blue shirts')"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of products to return (default: 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    "search_products_filtered": {
        "function": search_products_filtered,
        "schema": {
            "name": "search_products_filtered",
            "description": "Advanced filtered search for styling recommendations. Use when customer needs personalized outfit suggestions with context (occasion, weather, style).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Semantic search query describing desired style"
                    },
                    "occasion": {
                        "type": "string",
                        "enum": ["wedding", "birthday", "work", "casual_outing", "date_night", "gym", "interview"],
                        "description": "Event or occasion type"
                    },
                    "weather": {
                        "type": "string",
                        "enum": ["warm", "mild", "cold", "rainy"],
                        "description": "Climate or weather conditions"
                    },
                    "formality": {
                        "type": "string",
                        "enum": ["casual", "business_casual", "smart_casual", "formal", "athletic"],
                        "description": "Formality level"
                    },
                    "gender": {
                        "type": "string",
                        "enum": ["Men", "Women", "Unisex"],
                        "description": "Target gender"
                    },
                    "age_group": {
                        "type": "string",
                        "enum": ["teen", "young_adult", "adult", "senior"],
                        "description": "Age category for appropriate styling"
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred color palette"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    "check_product_availability": {
        "function": check_product_availability,
        "schema": {
            "name": "check_product_availability",
            "description": "Check real-time inventory availability for a specific product",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Product identifier from search results"
                    },
                    "region": {
                        "type": "string",
                        "enum": ["US_WEST", "US_EAST", "US_SOUTH"],
                        "description": "Specific region or omit for all regions"
                    }
                },
                "required": ["product_id"]
            }
        }
    }
}
