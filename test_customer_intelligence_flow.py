#!/usr/bin/env python3
"""
Test Customer Intelligence Data Flow Validation

This script tests the complete flow:
1. Authentication with client_id
2. Cosmos DB customer intelligence retrieval  
3. MemoManager storage via cm_set()
4. Greeting generation using customer intelligence

Run this to verify the orchestration is working correctly.
"""

import asyncio
import os
import sys
from typing import Dict, Any, Optional

# Add the project root to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'apps', 'rtagent', 'backend'))
sys.path.append(os.path.dirname(__file__))

from src.cosmosdb.manager import CosmosDBMongoCoreManager
from src.stateful.state_managment import MemoManager
from apps.rtagent.backend.src.orchestration.artagent.auth import fetch_customer_intelligence
from apps.rtagent.backend.src.orchestration.artagent.cm_utils import cm_set, cm_get
from apps.rtagent.backend.src.orchestration.artagent.greetings import create_personalized_greeting
from utils.ml_logging import get_logger

logger = get_logger(__name__)

async def test_customer_intelligence_flow():
    """Test the complete customer intelligence data flow."""
    
    print("🧪 Testing Customer Intelligence Data Flow")
    print("=" * 50)
    
    # Test client IDs from the sample data
    test_client_ids = [
        "FSC-2024-12345", "FSC-2024-67890", "FSC-2024-11111",  
        "FSC-2024-22222", "FSC-2024-33333"
    ]
    
    for client_id in test_client_ids:
        print(f"\n🔍 Testing client: {client_id}")
        
        # STEP 1: Test Cosmos DB retrieval
        try:
            print("  📡 Fetching from Cosmos DB...")
            intelligence = await fetch_customer_intelligence(client_id)
            
            if intelligence:
                print("  ✅ Customer intelligence retrieved successfully")
                print(f"     Tier: {intelligence.get('relationship_context', {}).get('relationship_tier', 'N/A')}")
                print(f"     Communication: {intelligence.get('memory_score', {}).get('communication_style', 'N/A')}")
                print(f"     Balance: ${intelligence.get('account_status', {}).get('current_balance', 0):,}")
                print(f"     Alerts: {len(intelligence.get('active_alerts', []))}")
            else:
                print("  ❌ No customer intelligence found")
                continue
                
        except Exception as e:
            print(f"  ❌ Error fetching intelligence: {e}")
            continue
            
        # STEP 2: Test MemoManager storage
        try:
            print("  💾 Testing MemoManager storage...")
            
            # Create a test MemoManager instance
            cm = MemoManager(session_id=f"test_{client_id}")
            
            # Simulate the cm_set call that happens after auth
            cm_set(
                cm,
                authenticated=True,
                caller_name="Alice Brown",  # Test name
                client_id=client_id,
                institution_name="First National Bank",
                active_agent="Fraud",
                customer_intelligence=intelligence
            )
            
            # Verify the data was stored
            stored_intelligence = cm_get(cm, "customer_intelligence")
            if stored_intelligence:
                print("  ✅ Customer intelligence stored in MemoManager")
            else:
                print("  ❌ Customer intelligence not found in MemoManager")
                continue
                
        except Exception as e:
            print(f"  ❌ Error storing in MemoManager: {e}")
            continue
            
        # STEP 3: Test personalized greeting generation
        try:
            print("  🎙️ Testing personalized greeting generation...")
            
            greeting = create_personalized_greeting(
                caller_name="Alice Brown",
                agent_name="Fraud",
                customer_intelligence=stored_intelligence,
                institution_name="First National Bank",
                topic="fraud concerns"
            )
            
            print("  ✅ Personalized greeting generated successfully")
            print(f"     Preview: {greeting[:100]}...")
            
        except Exception as e:
            print(f"  ❌ Error generating greeting: {e}")
            continue
            
        print("  🎯 Complete flow validation: SUCCESS")
        break  # Test one successful flow

    print("\n" + "=" * 50)
    print("🏁 Customer Intelligence Flow Test Complete")

async def test_cosmos_connection():
    """Test basic Cosmos DB connection."""
    print("🔗 Testing Cosmos DB Connection")
    print("-" * 30)
    
    try:
        # Test connection to customer intelligence collection
        intelligence_manager = CosmosDBMongoCoreManager(
            database_name="financial_services_db",
            collection_name="customer_intelligence"
        )
        
        print(f"✅ Connected to: {intelligence_manager.database.name}")
        print(f"✅ Collection: {intelligence_manager.collection.name}")
        print(f"✅ Host: {intelligence_manager.cluster_host}")
        
        # Test data retrieval
        sample_doc = await asyncio.to_thread(
            intelligence_manager.read_document,
            query={"client_id": "FSC-2024-12345"}
        )
        
        if sample_doc:
            print("✅ Sample document found")
        else:
            print("❌ No sample document found - check if data was loaded")
            
    except Exception as e:
        print(f"❌ Cosmos DB connection error: {e}")

async def main():
    """Run all validation tests."""
    print("🚀 Customer Intelligence Validation Suite")
    print("=" * 60)
    
    await test_cosmos_connection()
    print()
    await test_customer_intelligence_flow()

if __name__ == "__main__":
    asyncio.run(main())