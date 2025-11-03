#!/usr/bin/env python3
"""
Script to fix existing documents with incorrect TTL field types.
This script converts numeric TTL values to proper datetime objects for MongoDB TTL to work.
"""

import os
from datetime import datetime, timedelta
from src.cosmosdb.manager import CosmosDBMongoCoreManager


def fix_ttl_documents():
    """
    Fix existing documents that have numeric TTL values instead of datetime objects.
    """
    # Initialize the manager with your connection details
    manager = CosmosDBMongoCoreManager(
        database_name="financial_services_db",  # Replace with your database name
        collection_name="users"  # Replace with your collection name
    )
    
    print("🔍 Searching for documents with numeric TTL values...")
    
    # Find documents with numeric TTL fields
    documents_to_fix = manager.query_documents({
        "ttl": {"$type": "number"}  # Find documents where TTL is a number, not a date
    })
    
    print(f"📊 Found {len(documents_to_fix)} documents to fix")
    
    for doc in documents_to_fix:
        doc_id = doc.get("_id")
        ttl_seconds = doc.get("ttl", 0)
        
        if isinstance(ttl_seconds, (int, float)) and ttl_seconds > 0:
            # Calculate the proper expiration time
            expiration_time = datetime.utcnow() + timedelta(seconds=ttl_seconds)
            
            # Update the document with correct TTL field
            update_result = manager.collection.update_one(
                {"_id": doc_id},
                {
                    "$set": {
                        "ttl": expiration_time,  # Date object for TTL
                        "expires_at": expiration_time.isoformat() + "Z",  # Human-readable string
                        "fixed_at": datetime.utcnow().isoformat() + "Z"  # Track when we fixed it
                    }
                }
            )
            
            if update_result.modified_count > 0:
                print(f"✅ Fixed document {doc_id}: TTL {ttl_seconds}s → expires at {expiration_time}")
            else:
                print(f"⚠️  Failed to fix document {doc_id}")
    
    print("\n🔧 Ensuring TTL index exists...")
    # Make sure the TTL index is properly configured
    index_created = manager.ensure_ttl_index("ttl", 0)  # 0 = use document-level TTL
    
    if index_created:
        print("✅ TTL index is properly configured")
    else:
        print("❌ Failed to create TTL index")
    
    print("\n📋 Current TTL index status:")
    indexes = list(manager.collection.list_indexes())
    for index in indexes:
        if "expireAfterSeconds" in index:
            print(f"   TTL Index: {index['name']} on {list(index['key'].keys())} - expireAfterSeconds: {index['expireAfterSeconds']}")


def verify_ttl_setup():
    """
    Verify that TTL is working by creating a test document with short TTL.
    """
    manager = CosmosDBMongoCoreManager(
        database_name="financial_services_db",
        collection_name="users"
    )
    
    print("\n🧪 Testing TTL with a short-lived document...")
    
    # Create a test document that expires in 60 seconds
    test_doc = {
        "_id": "ttl_test_" + str(int(datetime.utcnow().timestamp())),
        "test": True,
        "message": "This document should expire in 60 seconds"
    }
    
    # Insert with 60-second TTL
    result = manager.insert_document_with_ttl(test_doc, 60)
    
    if result:
        print(f"✅ Test document created: {result}")
        print("   Check back in 60+ seconds - it should be automatically deleted by MongoDB")
        
        # Show what the document looks like now
        created_doc = manager.read_document({"_id": test_doc["_id"]})
        if created_doc:
            print(f"   TTL field type: {type(created_doc.get('ttl'))}")
            print(f"   TTL value: {created_doc.get('ttl')}")
            print(f"   Expires at: {created_doc.get('expires_at')}")
    else:
        print("❌ Failed to create test document")


if __name__ == "__main__":
    print("🔧 MongoDB TTL Fix Script")
    print("=" * 50)
    
    try:
        fix_ttl_documents()
        verify_ttl_setup()
        
        print("\n✅ TTL fix completed!")
        print("\n📝 What changed:")
        print("   - Numeric TTL values converted to datetime objects")
        print("   - TTL index verified/created with expireAfterSeconds=0")
        print("   - Documents should now auto-delete when TTL expires")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check your connection string and credentials")
        print("2. Verify database and collection names")
        print("3. Ensure you have write permissions")