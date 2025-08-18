#!/usr/bin/env python3
"""Simple WebSocket connection test for debugging auth issues."""

import asyncio
import os
import sys
import websockets
import json


async def test_connection(url: str):
    """Test basic WebSocket connection without auth headers."""
    print(f"Testing connection to: {url}")
    try:
        # Try without any headers first
        async with websockets.connect(url, timeout=5) as ws:
            print("✅ Connection successful!")
            print("Waiting for greeting message...")
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"📨 Received: {msg[:200]}...")
            return True
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"❌ Connection closed: {e}")
        if "403" in str(e):
            print("🔐 This indicates authentication is required")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
    return False


async def test_with_disable_auth():
    """Test by temporarily disabling auth via environment variable."""
    print("\n🧪 Testing with ENABLE_AUTH_VALIDATION=false")
    original = os.environ.get("ENABLE_AUTH_VALIDATION")
    os.environ["ENABLE_AUTH_VALIDATION"] = "false"

    # This won't affect the running server, but shows the setting
    print(f"Environment set to: {os.environ.get('ENABLE_AUTH_VALIDATION')}")

    if original:
        os.environ["ENABLE_AUTH_VALIDATION"] = original
    else:
        os.environ.pop("ENABLE_AUTH_VALIDATION", None)


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8010/realtime"

    print("🔍 WebSocket Connection Diagnostics")
    print("=" * 50)

    success = await test_connection(url)

    if not success:
        await test_with_disable_auth()
        print("\n💡 Solutions:")
        print("1. Set ENABLE_AUTH_VALIDATION=false in your .env file")
        print("2. Restart the backend server")
        print("3. Or implement proper auth tokens in the test")

        # Show what auth headers might be needed
        print("\n📋 Required auth setup (if keeping auth enabled):")
        print("- Authorization: Bearer <valid-jwt-token>")
        print("- x-ms-client-principal-id: <user-id>")
        print("- See auth middleware for exact requirements")


if __name__ == "__main__":
    asyncio.run(main())
