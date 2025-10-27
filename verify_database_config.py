#!/usr/bin/env python3
"""
Database Configuration Verification Script

Verifies that all fraud detection and authentication tools are correctly configured
to use the unified financial_services_db with proper collections and methods.

Run this script to validate the database configuration updates.
"""

import asyncio
import sys
import os

# Add the backend directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

def test_database_managers():
    """Test that all database managers are correctly configured."""
    
    print("🔍 Testing Database Manager Configuration...")
    print("=" * 60)
    
    try:
        # Test fraud detection managers
        from apps.rtagent.backend.src.agents.artagent.tool_store.fraud_detection import (
            get_fraud_cosmos_manager,
            get_users_cosmos_manager, 
            get_transactions_cosmos_manager,
            get_card_orders_cosmos_manager,
            get_mfa_sessions_cosmos_manager
        )
        
        # Test MFA auth managers
        from apps.rtagent.backend.src.agents.artagent.tool_store.financial_mfa_auth import (
            get_financial_cosmos_manager,
            get_mfa_cosmos_manager
        )
        
        # Test managers configuration
        managers_config = [
            ("Fraud Cases", get_fraud_cosmos_manager(), "fraud_cases"),
            ("Users", get_users_cosmos_manager(), "users"), 
            ("Transactions", get_transactions_cosmos_manager(), "transactions"),
            ("Card Orders", get_card_orders_cosmos_manager(), "card_orders"),
            ("MFA Sessions (Fraud)", get_mfa_sessions_cosmos_manager(), "mfa_sessions"),
            ("Users (MFA Auth)", get_financial_cosmos_manager(), "users"),
            ("MFA Sessions (Auth)", get_mfa_cosmos_manager(), "mfa_sessions"),
        ]
        
        all_correct = True
        
        for name, manager, expected_collection in managers_config:
            database_name = manager.database.name
            collection_name = manager.collection.name
            
            database_correct = database_name == "financial_services_db"
            collection_correct = collection_name == expected_collection
            
            status = "✅" if (database_correct and collection_correct) else "❌"
            
            print(f"{status} {name:<20} | DB: {database_name:<20} | Collection: {collection_name}")
            
            if not database_correct:
                print(f"   ⚠️  Expected database: financial_services_db, got: {database_name}")
                all_correct = False
                
            if not collection_correct:
                print(f"   ⚠️  Expected collection: {expected_collection}, got: {collection_name}")
                all_correct = False
        
        print("=" * 60)
        
        if all_correct:
            print("🎉 All database managers correctly configured!")
            return True
        else:
            print("❌ Some database managers have incorrect configuration")
            return False
            
    except Exception as e:
        print(f"💥 Error testing managers: {e}")
        return False

async def test_database_queries():
    """Test that database queries work with the new structure."""
    
    print("\n🧪 Testing Database Queries...")
    print("=" * 60)
    
    try:
        from apps.rtagent.backend.src.agents.artagent.tool_store.fraud_detection import (
            get_client_data_async
        )
        
        # Test client lookup with known test client
        test_client_id = "pablo_salvador_cfs"
        
        print(f"🔍 Testing client lookup for: {test_client_id}")
        
        client_data = await get_client_data_async(test_client_id)
        
        if client_data:
            print(f"✅ Found client: {client_data.get('full_name', 'Unknown')}")
            print(f"   🏢 Institution: {client_data.get('institution_name', 'Unknown')}")
            print(f"   🆔 Client ID: {client_data.get('client_id', 'Unknown')}")
            
            # Check if customer intelligence is present
            customer_intel = client_data.get('customer_intelligence', {})
            if customer_intel:
                tier = customer_intel.get('relationship_context', {}).get('relationship_tier', 'Unknown')
                print(f"   🎯 Tier: {tier}")
                print("   🧠 Customer Intelligence: Available")
            else:
                print("   ⚠️  Customer Intelligence: Missing")
            
            return True
        else:
            print("❌ Client not found - this may indicate database setup issues")
            return False
            
    except Exception as e:
        print(f"💥 Error testing queries: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all verification tests."""
    
    print("🚀 Financial Services Database Configuration Verification")
    print("🏦 Target Database: financial_services_db")
    print("🔑 Universal Key: client_id")
    print()
    
    # Test 1: Manager Configuration
    managers_ok = test_database_managers()
    
    # Test 2: Database Queries
    queries_ok = asyncio.run(test_database_queries())
    
    print("\n" + "=" * 60)
    print("📋 VERIFICATION SUMMARY")
    print("=" * 60)
    
    print(f"🔧 Database Managers: {'✅ PASS' if managers_ok else '❌ FAIL'}")
    print(f"🧪 Database Queries:  {'✅ PASS' if queries_ok else '❌ FAIL'}")
    
    if managers_ok and queries_ok:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Fraud detection and authentication tools are ready to use!")
        print("✅ Database configuration is correct!")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("⚠️  Please check the error messages above")
        return 1

if __name__ == "__main__":
    exit(main())