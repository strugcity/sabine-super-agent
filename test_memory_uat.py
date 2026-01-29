#!/usr/bin/env python3
"""
Memory System UAT - Active Testing
==================================

This script performs active UAT testing of the Context Engine memory system.
It tests:
1. Memory ingestion (entity extraction + embedding + storage)
2. Context retrieval (vector search + entity matching)
3. End-to-end flow verification

Run with: python test_memory_uat.py
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables (override=True is required for Windows)
from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}[PASS] {text}{Colors.RESET}")

def print_error(text: str):
    print(f"{Colors.RED}[FAIL] {text}{Colors.RESET}")

def print_info(text: str):
    print(f"{Colors.CYAN}[INFO] {text}{Colors.RESET}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.RESET}")


async def test_database_connection():
    """Test 1: Verify Supabase connection and tables exist."""
    print_header("TEST 1: Database Connection")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not url or not key:
            print_error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
            return False

        print_info(f"Connecting to: {url[:50]}...")
        client = create_client(url, key)

        # Test entities table
        result = client.table("entities").select("count", count="exact").limit(1).execute()
        entity_count = result.count if hasattr(result, 'count') else 0
        print_success(f"Entities table accessible - {entity_count} records")

        # Test memories table
        result = client.table("memories").select("count", count="exact").limit(1).execute()
        memory_count = result.count if hasattr(result, 'count') else 0
        print_success(f"Memories table accessible - {memory_count} records")

        # Test tasks table
        result = client.table("tasks").select("count", count="exact").limit(1).execute()
        task_count = result.count if hasattr(result, 'count') else 0
        print_success(f"Tasks table accessible - {task_count} records")

        return True

    except Exception as e:
        print_error(f"Database connection failed: {e}")
        return False


async def test_embedding_generation():
    """Test 2: Verify OpenAI embedding generation works."""
    print_header("TEST 2: Embedding Generation")

    try:
        from langchain_openai import OpenAIEmbeddings

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print_error("Missing OPENAI_API_KEY")
            return False

        print_info("Initializing text-embedding-3-small...")
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=api_key
        )

        test_text = "Baseball game moved to 5 PM Saturday"
        print_info(f"Generating embedding for: '{test_text}'")

        vector = await embeddings.aembed_query(test_text)

        if len(vector) == 1536:
            print_success(f"Generated {len(vector)}-dimension embedding")
            print_info(f"First 5 values: {vector[:5]}")
            return True
        else:
            print_error(f"Expected 1536 dimensions, got {len(vector)}")
            return False

    except Exception as e:
        print_error(f"Embedding generation failed: {e}")
        return False


async def test_entity_extraction():
    """Test 3: Verify Claude entity extraction works."""
    print_header("TEST 3: Entity Extraction (Claude)")

    try:
        from lib.agent.memory import extract_context

        test_messages = [
            "Baseball game moved to 5 PM Saturday at Lincoln Park",
            "Told Jenny to review the Q1 budget deck by Friday",
            "Doctor appointment rescheduled to Wednesday at 2 PM"
        ]

        for msg in test_messages:
            print_info(f"Extracting from: '{msg}'")
            result = await extract_context(msg)

            print_success(f"  Domain: {result.domain.value}")
            print_success(f"  Core Memory: {result.core_memory[:60]}...")
            print_success(f"  Entities extracted: {len(result.extracted_entities)}")

            for entity in result.extracted_entities:
                print(f"    - {entity.name} ({entity.type}, {entity.domain.value})")
                if entity.attributes:
                    print(f"      Attributes: {entity.attributes}")
            print()

        return True

    except Exception as e:
        print_error(f"Entity extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_memory_ingestion():
    """Test 4: Full memory ingestion pipeline."""
    print_header("TEST 4: Memory Ingestion Pipeline")

    try:
        from lib.agent.memory import ingest_user_message

        test_user_id = UUID("00000000-0000-0000-0000-000000000001")

        test_messages = [
            ("Jenny called about the PriceSpider contract renewal - deadline is Feb 15", "sms"),
            ("Kids have soccer practice Tuesday and Thursday at 4 PM", "api"),
            ("Need to pick up dry cleaning before the board meeting Friday", "api"),
        ]

        for msg, source in test_messages:
            print_info(f"Ingesting: '{msg[:50]}...'")

            result = await ingest_user_message(
                user_id=test_user_id,
                content=msg,
                source=source
            )

            if result["status"] == "success":
                print_success(f"  Memory ID: {result['memory_id']}")
                print_success(f"  Entities created: {result['entities_created']}")
                print_success(f"  Entities updated: {result['entities_updated']}")
                print_success(f"  Domain: {result['domain']}")
                print_success(f"  Processing time: {result['processing_time_ms']}ms")
            else:
                print_error(f"  Failed: {result.get('error', 'Unknown error')}")
                return False
            print()

        return True

    except Exception as e:
        print_error(f"Memory ingestion failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_context_retrieval():
    """Test 5: Context retrieval with vector search."""
    print_header("TEST 5: Context Retrieval")

    try:
        from lib.agent.retrieval import retrieve_context

        test_user_id = UUID("00000000-0000-0000-0000-000000000001")

        test_queries = [
            "What's happening with Jenny?",
            "What do the kids have this week?",
            "Tell me about the PriceSpider contract",
            "What meetings do I have coming up?"
        ]

        for query in test_queries:
            print_info(f"Query: '{query}'")

            context = await retrieve_context(
                user_id=test_user_id,
                query=query,
                memory_threshold=0.5,  # Lower threshold for testing
                memory_limit=5,
                entity_limit=10
            )

            print(f"\n{Colors.CYAN}--- Retrieved Context ---{Colors.RESET}")
            print(context)
            print(f"{Colors.CYAN}--- End Context ---{Colors.RESET}\n")

        return True

    except Exception as e:
        print_error(f"Context retrieval failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_vector_search_function():
    """Test 6: Test the match_memories PostgreSQL function directly."""
    print_header("TEST 6: Vector Search Function (match_memories)")

    try:
        from lib.agent.memory import get_supabase_client, get_embeddings

        supabase = get_supabase_client()
        embeddings = get_embeddings()

        # Generate a test query embedding
        test_query = "contract deadline"
        print_info(f"Generating embedding for: '{test_query}'")
        query_embedding = await embeddings.aembed_query(test_query)

        print_info("Calling match_memories RPC...")
        # Format embedding as pgvector-compatible string
        pgvector_embedding = f"[{','.join(str(x) for x in query_embedding)}]"
        response = supabase.rpc(
            "match_memories",
            {
                "query_embedding": pgvector_embedding,
                "match_threshold": 0.3,  # Low threshold to find matches
                "match_count": 5,
                "user_id_filter": None
            }
        ).execute()

        if response.data:
            print_success(f"Found {len(response.data)} matching memories")
            for i, mem in enumerate(response.data):
                print(f"\n  [{i+1}] Similarity: {mem.get('similarity', 0):.2%}")
                print(f"      Content: {mem.get('content', '')[:80]}...")
                print(f"      Created: {mem.get('created_at', '')[:19]}")
        else:
            print_warning("No matching memories found (this is OK if database is empty)")

        return True

    except Exception as e:
        print_error(f"Vector search failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_list_stored_data():
    """Test 7: List all stored entities and memories."""
    print_header("TEST 7: List Stored Data")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        client = create_client(url, key)

        # List entities
        print_info("Fetching entities...")
        entities = client.table("entities").select("*").order("created_at", desc=True).limit(10).execute()

        if entities.data:
            print_success(f"Found {len(entities.data)} entities (showing up to 10)")
            for e in entities.data:
                print(f"\n  Name: {e['name']}")
                print(f"  Type: {e['type']} | Domain: {e['domain']} | Status: {e['status']}")
                if e.get('attributes'):
                    print(f"  Attributes: {e['attributes']}")
        else:
            print_warning("No entities found")

        # List memories
        print_info("\nFetching memories...")
        memories = client.table("memories").select("id, content, metadata, importance_score, created_at").order("created_at", desc=True).limit(10).execute()

        if memories.data:
            print_success(f"Found {len(memories.data)} memories (showing up to 10)")
            for m in memories.data:
                print(f"\n  ID: {m['id'][:8]}...")
                print(f"  Content: {m['content'][:80]}...")
                print(f"  Source: {m.get('metadata', {}).get('source', 'unknown')}")
                print(f"  Created: {m['created_at'][:19]}")
        else:
            print_warning("No memories found")

        return True

    except Exception as e:
        print_error(f"Failed to list data: {e}")
        return False


async def main():
    """Run all UAT tests."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("=" * 70)
    print("    SABINE MEMORY SYSTEM - USER ACCEPTANCE TESTING")
    print("                   Active UAT Suite")
    print("=" * 70)
    print(f"{Colors.RESET}")

    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Environment: {os.getenv('NODE_ENV', 'development')}")

    results = {}

    # Run tests in sequence
    results["Database Connection"] = await test_database_connection()
    results["Embedding Generation"] = await test_embedding_generation()
    results["Entity Extraction"] = await test_entity_extraction()
    results["Memory Ingestion"] = await test_memory_ingestion()
    results["Vector Search"] = await test_vector_search_function()
    results["Context Retrieval"] = await test_context_retrieval()
    results["List Stored Data"] = await test_list_stored_data()

    # Summary
    print_header("UAT SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_test in results.items():
        if passed_test:
            print_success(f"{test_name}")
        else:
            print_error(f"{test_name}")

    print()
    if passed == total:
        print(f"{Colors.GREEN}{Colors.BOLD}All {total} tests passed!{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}{passed}/{total} tests passed{Colors.RESET}")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
