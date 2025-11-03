#!/usr/bin/env python3
"""
Quick script to delete a corrupted session from Redis.
Usage: python scripts/clear_session.py session_1762116065251_tga29y
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.redis.manager import AzureRedisManager
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def clear_session(session_id: str):
    """Delete a session from Redis."""
    redis_host = os.getenv("REDIS_HOST", "").strip('"')
    redis_key = os.getenv("REDIS_ACCESS_KEY", "").strip('"')
    redis_port = int(os.getenv("REDIS_PORT", "6380"))
    redis_ssl = os.getenv("REDIS_SSL", "true").lower() == "true"
    
    print(f"🔌 Connecting to Redis: {redis_host}:{redis_port} (SSL={redis_ssl})")
    
    # Initialize Redis manager
    redis_mgr = AzureRedisManager(
        host=redis_host,
        access_key=redis_key,
        port=redis_port,
        ssl=redis_ssl
    )
    
    # Build the Redis key
    session_key = f"session:{session_id}"
    
    print(f"🔍 Checking if session exists: {session_key}")
    
    # Check if session exists
    data = redis_mgr.get_session_data(session_key)
    if data:
        # Get chat history to see size
        if "chat_history" in data:
            import json
            history = json.loads(data["chat_history"])
            total_len = sum(len(h) for h in history.values()) if isinstance(history, dict) else len(history)
            print(f"📊 Session found with {total_len} messages in history")
        else:
            print(f"📊 Session found (no chat_history key)")
        
        # Delete the session
        print(f"🗑️  Deleting session: {session_key}")
        result = redis_mgr.delete_session(session_key)
        
        if result > 0:
            print(f"✅ Successfully deleted session {session_id}")
        else:
            print(f"❌ Failed to delete session {session_id}")
    else:
        print(f"⚠️  Session not found: {session_key}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Usage: python scripts/clear_session.py <session_id>")
        print("   Example: python scripts/clear_session.py session_1762116065251_tga29y")
        sys.exit(1)
    
    session_id = sys.argv[1]
    clear_session(session_id)
