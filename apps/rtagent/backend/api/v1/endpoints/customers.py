"""
Customer Endpoints
==================

API endpoints for customer profile management and switching.
"""

from __future__ import annotations

import asyncio
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace

from utils.ml_logging import get_logger
from src.cosmosdb.manager import CosmosDBMongoCoreManager
from config.app_settings import AZURE_COSMOS_DATABASE_NAME

logger = get_logger("customers")
tracer = trace.get_tracer(__name__)

router = APIRouter()


def get_avatar_emoji(user: Dict[str, Any]) -> str:
    """
    Map user to avatar emoji based on style preferences.
    
    Args:
        user: User document from Cosmos DB
        
    Returns:
        Emoji string representing user's style
    """
    user_id = user.get("user_id", "")
    
    # Map known demo users
    if user_id == "sarah_johnson":
        return "🏃‍♀️"
    elif user_id == "michael_chen":
        return "💼"
    elif user_id == "emma_rodriguez":
        return "🌸"
    
    # Fallback based on style preferences
    styles = user.get("preferences", {}).get("style", [])
    if "athletic" in styles:
        return "🏃‍♀️"
    elif "business_casual" in styles or "professional" in styles:
        return "💼"
    elif "boho" in styles or "vintage" in styles:
        return "🌸"
    
    return "👤"  # Default


@router.get("/customers")
async def get_customers(request: Request):
    """
    Get list of available customers for demo user switching.
    
    Returns:
        JSON response with list of customers including:
        - user_id
        - full_name
        - loyalty_tier
        - location
        - avatar_emoji
        - style_summary
    """
    with tracer.start_as_current_span("get_customers") as span:
        try:
            # Get Cosmos DB manager from app state
            cosmos_manager: CosmosDBMongoCoreManager = request.app.state.cosmos_manager
            
            # Query all users
            users = await asyncio.to_thread(
                cosmos_manager.query_documents,
                query={}
            )
            
            if not users:
                logger.warning("No users found in Cosmos DB")
                return JSONResponse(
                    content={
                        "status": "success",
                        "customers": []
                    }
                )
            
            # Transform for frontend
            customers = []
            for user in users:
                loyalty_data = user.get("dynamics365_data", {})
                location = user.get("location", {})
                preferences = user.get("preferences", {})
                
                customer = {
                    "user_id": user.get("user_id"),
                    "full_name": user.get("full_name"),
                    "loyalty_tier": loyalty_data.get("loyalty_tier", "Member"),
                    "location": f"{location.get('city', 'Unknown')}, {location.get('state', '')}".strip(", "),
                    "avatar_emoji": get_avatar_emoji(user),
                    "style_summary": ", ".join(preferences.get("style", [])[:2]).title()
                }
                customers.append(customer)
            
            span.set_attribute("customer.count", len(customers))
            logger.info(f"Retrieved {len(customers)} customers")
            
            return JSONResponse(
                content={
                    "status": "success",
                    "customers": customers
                }
            )
            
        except Exception as e:
            logger.error(f"Error fetching customers: {e}", exc_info=True)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            span.record_exception(e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch customers: {str(e)}"
            )


@router.get("/customer/{user_id}")
async def get_customer_profile(user_id: str, request: Request):
    """
    Get full customer profile for selected user.
    
    Args:
        user_id: Customer user ID (e.g., "sarah_johnson")
        
    Returns:
        JSON response with full customer profile including:
        - user_id
        - full_name
        - age
        - location (city, state, climate)
        - loyalty_tier
        - loyalty_points
        - preferences (style, colors, brands)
        - shopping_patterns
        - conversation_memory
    """
    with tracer.start_as_current_span(
        "get_customer_profile",
        attributes={"customer.user_id": user_id}
    ) as span:
        try:
            # Get Cosmos DB manager from app state
            cosmos_manager: CosmosDBMongoCoreManager = request.app.state.cosmos_manager
            
            # Query specific user
            user = await asyncio.to_thread(
                cosmos_manager.read_document,
                query={"user_id": user_id}
            )
            
            if not user:
                logger.warning(f"Customer not found: {user_id}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Customer '{user_id}' not found"
                )
            
            # Build customer profile response
            customer = {
                "user_id": user.get("user_id"),
                "full_name": user.get("full_name"),
                "age": user.get("age"),
                "location": user.get("location", {}),
                "loyalty_tier": user.get("dynamics365_data", {}).get("loyalty_tier", "Member"),
                "loyalty_points": user.get("dynamics365_data", {}).get("loyalty_points", 0),
                "preferences": user.get("preferences", {}),
                "shopping_patterns": user.get("shopping_patterns", {}),
                "conversation_memory": user.get("conversation_memory", {})
            }
            
            logger.info(f"Retrieved profile for customer: {user_id}")
            
            return JSONResponse(
                content={
                    "status": "success",
                    "customer": customer
                }
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching customer profile: {e}", exc_info=True)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            span.record_exception(e)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch customer profile: {str(e)}"
            )
