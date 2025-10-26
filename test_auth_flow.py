#!/usr/bin/env python3
"""
Test Authentication Flow with client_id

This script tests:
1. Authentication database query 
2. Returns client_id instead of policy_id
"""

import asyncio
import os
import sys
from typing import Dict, Any, Optional

# Add the project root to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'apps', 'rtagent', 'backend'))
sys.path.append(os.path.dirname(__file__))

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from utils.ml_logging import get_logger

logger = get_logger(__name__)

async def test_auth_database_structure():
    """Test the policyholders database structure to see if it has client_id."""
    
    print("🧪 Testing Authentication Database Structure")
    print("=" * 50)
    
    try:
        # Connect to the policyholders collection
        auth_manager = CosmosDBMongoCoreManager(
            database_name="voice_agent_db",
            collection_name="policyholders"
        )
        
        print("📡 Checking policyholders collection structure...")
        
        # Get one document to see the structure
        sample_doc = await asyncio.to_thread(
            auth_manager.read_document,
            query={}  # Get any document
        )
        
        if sample_doc:
            print("✅ Sample document found:")
            print(f"  Fields: {list(sample_doc.keys())}")
            
            # Check if it has client_id or policy_id
            if "client_id" in sample_doc:
                print(f"  ✅ client_id found: {sample_doc['client_id']}")
            elif "policy_id" in sample_doc:
                print(f"  ⚠️  policy_id found: {sample_doc['policy_id']} (needs update)")
            else:
                print("  ❌ Neither client_id nor policy_id found")
                
            # Show other important fields
            for key in ['full_name', 'zip', 'ssn4', 'policy4']:
                if key in sample_doc:
                    print(f"  {key}: {sample_doc[key]}")
        else:
            print("❌ No documents found in policyholders collection")
            
    except Exception as e:
        print(f"❌ Error testing auth database: {e}")

if __name__ == "__main__":
    asyncio.run(test_auth_database_structure())