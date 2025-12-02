"""
Session data loader for pre-loading customer profiles.

Loads customer intelligence data from Cosmos DB when user email is provided,
so agents have full context from the start without needing authentication flow.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger("voicelive.session_loader")

_users_manager: Optional[CosmosDBMongoCoreManager] = None


def _get_users_manager() -> CosmosDBMongoCoreManager:
    """Get or create Cosmos DB manager for users collection."""
    global _users_manager
    if _users_manager is None:
        _users_manager = CosmosDBMongoCoreManager(
            database_name="banking_services_db",
            collection_name="users",
        )
    return _users_manager


async def load_user_profile_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Load full customer profile from Cosmos DB by email.
    
    Args:
        email: User's email address (e.g., carlos.salvador@techfusion.com)
    
    Returns:
        Complete customer_intelligence object if found, None otherwise
    """
    if not email or not email.strip():
        return None
    
    email = email.strip().lower()
    
    try:
        logger.info("Loading user profile from Cosmos DB | email=%s", email)
        
        manager = _get_users_manager()
        query = {"contact_info.email": {"$regex": f"^{email}$", "$options": "i"}}
        
        result = await asyncio.to_thread(manager.read_document, query)
        
        if not result:
            logger.warning("No user profile found | email=%s", email)
            return None
        
        logger.info(
            "✅ User profile loaded | email=%s client_id=%s name=%s",
            email,
            result.get("client_id"),
            result.get("full_name")
        )
        
        return result
    
    except Exception as exc:
        logger.error("Failed to load user profile | email=%s error=%s", email, exc, exc_info=True)
        return None
