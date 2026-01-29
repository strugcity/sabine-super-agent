#!/usr/bin/env python3
"""
Test Phase 4 API Integration

Tests the Context Engine integration with the FastAPI server:
1. Manual memory ingestion via /memory/ingest
2. Context retrieval via /memory/query
3. Full integration via /invoke

Prerequisites:
- Server running on http://localhost:8001
- Supabase configured with Context Engine schema
- API key set in environment (SABINE_API_KEY)

Usage:
    python tests/test_phase4_integration.py
"""

from dotenv import load_dotenv
import httpx
import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# Load environment variables
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

# Configuration
API_BASE_URL = "http://localhost:8001"
API_KEY = os.getenv("SABINE_API_KEY", "dev-key-123")
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"

# Test data
TEST_MESSAGES = [
    "I signed the PriceSpider contract on Friday. Jenny from their team was very helpful.",
    "John mentioned he's working on a new AI project at Acme Corp.",
    "The quarterly review meeting is scheduled for next Tuesday at 2 PM."
]


async def test_memory_ingest():
    """Test 1: Manual memory ingestion endpoint."""
    print("\n" + "=" * 60)
    print("TEST 1: Memory Ingestion (/memory/ingest)")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        for i, message in enumerate(TEST_MESSAGES, 1):
            print(f"\n[{i}/{len(TEST_MESSAGES)}] Ingesting: {message[:60]}...")

            response = await client.post(
                f"{API_BASE_URL}/memory/ingest",
                headers={
                    "X-API-Key": API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "user_id": TEST_USER_ID,
                    "content": message,
                    "source": "test"
                },
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Success!")
                print(
                    f"   - Entities created: {data.get('entities_created', 0)}")
                print(
                    f"   - Entities updated: {data.get('entities_updated', 0)}")
                print(f"   - Memory ID: {data.get('memory_id', 'N/A')}")
            else:
                print(f"❌ Failed: {response.status_code}")
                print(f"   {response.text}")
                return False

    print("\n✅ ALL INGESTION TESTS PASSED")
    return True


async def test_memory_query():
    """Test 2: Context retrieval endpoint."""
    print("\n" + "=" * 60)
    print("TEST 2: Context Retrieval (/memory/query)")
    print("=" * 60)

    queries = [
        "What happened with PriceSpider?",
        "Who is John?",
        "When is the quarterly review?"
    ]

    async with httpx.AsyncClient() as client:
        for i, query in enumerate(queries, 1):
            print(f"\n[{i}/{len(queries)}] Query: {query}")

            response = await client.post(
                f"{API_BASE_URL}/memory/query",
                headers={
                    "X-API-Key": API_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "user_id": TEST_USER_ID,
                    "query": query
                },
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                print(f"✅ Success!")
                print(
                    f"   - Context length: {data.get('context_length', 0)} chars")
                print(
                    f"   - Memories found: {data['metadata']['memories_found']}")
                print(
                    f"   - Entities found: {data['metadata']['entities_found']}")

                # Show a preview of the context
                context = data.get('context', '')
                if context:
                    print(f"\n   Context Preview:")
                    print(f"   {context[:200]}...")
            else:
                print(f"❌ Failed: {response.status_code}")
                print(f"   {response.text}")
                return False

    print("\n✅ ALL QUERY TESTS PASSED")
    return True


async def test_invoke_integration():
    """Test 3: Full integration via /invoke endpoint."""
    print("\n" + "=" * 60)
    print("TEST 3: Integrated /invoke with Context Engine")
    print("=" * 60)

    test_query = "Tell me about the people I've been working with recently."
    print(f"\nQuery: {test_query}")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE_URL}/invoke",
            headers={
                "X-API-Key": API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "message": test_query,
                "user_id": TEST_USER_ID
            },
            timeout=60.0  # Longer timeout for LLM response
        )

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success!")
            print(f"   - Response: {data['response'][:200]}...")
            print(f"   - Session ID: {data['session_id']}")
            print(f"\n📝 Full Response:")
            print(f"   {data['response']}")
        else:
            print(f"❌ Failed: {response.status_code}")
            print(f"   {response.text}")
            return False

    print("\n✅ INVOKE INTEGRATION TEST PASSED")
    return True


async def check_server_health():
    """Check if the server is running."""
    print("\n🔍 Checking server health...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/health",
                timeout=5.0
            )

            if response.status_code == 200:
                print("✅ Server is healthy")
                return True
            else:
                print(f"⚠️  Server returned {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Server not reachable: {e}")
        print("\n💡 Start the server with:")
        print("   cd /workspaces/sabine-super-agent")
        print("   python lib/agent/server.py")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Phase 4 API Integration Tests")
    print("=" * 60)
    print(f"API URL: {API_BASE_URL}")
    print(f"Test User: {TEST_USER_ID}")

    # Check server health
    if not await check_server_health():
        return

    # Run tests
    try:
        # Test 1: Manual ingestion
        if not await test_memory_ingest():
            print("\n❌ Test 1 failed, stopping")
            return

        # Wait a bit for background processing
        print("\n⏳ Waiting 2 seconds for background processing...")
        await asyncio.sleep(2)

        # Test 2: Context retrieval
        if not await test_memory_query():
            print("\n❌ Test 2 failed, stopping")
            return

        # Test 3: Integrated invoke
        if not await test_invoke_integration():
            print("\n❌ Test 3 failed, stopping")
            return

        # All tests passed
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED! Phase 4 Integration Working!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
