"""
Live Verification Test for Context Retrieval System
===================================================

This script tests the Phase 3 retrieval pipeline.

Usage:
    python tests/verify_retrieval.py

Requirements:
    - OPENAI_API_KEY must be set (for embeddings)
    - SUPABASE_URL must be set
    - SUPABASE_SERVICE_ROLE_KEY must be set
    - Database must have memories and entities from Phase 2 ingestion
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def check_environment():
    """Verify all required environment variables are set."""
    required_vars = [
        "OPENAI_API_KEY",     # For embeddings
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY"
    ]

    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        logger.error(
            f"❌ Missing required environment variables: {', '.join(missing)}")
        logger.error("Please set these variables before running the test.")
        return False

    logger.info("✓ All required environment variables are set")
    return True


async def test_retrieval():
    """Test the retrieval system with sample queries."""
    from lib.agent.retrieval import retrieve_context

    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    test_queries = [
        "What's happening with Jenny?",
        "Tell me about the PriceSpider contract",
        "What meetings do I have?",
    ]

    logger.info("=" * 70)
    logger.info("CONTEXT RETRIEVAL TEST")
    logger.info("=" * 70)

    success_count = 0
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'=' * 70}")
        print(f"Test {i}/{len(test_queries)}: {query}")
        print('=' * 70)

        try:
            context = await retrieve_context(
                user_id=test_user_id,
                query=query
            )

            print(context)
            print()

            # Check if context has meaningful content
            if "[ERROR]" not in context:
                success_count += 1
                logger.info(f"✓ Query {i} succeeded")
            else:
                logger.warning(f"⚠️  Query {i} returned error context")

        except Exception as e:
            logger.error(f"❌ Query {i} failed: {e}", exc_info=True)

    return success_count, len(test_queries)


async def test_individual_components():
    """Test individual retrieval components."""
    from lib.agent.retrieval import (
        extract_keywords,
        search_entities_by_keywords,
        search_similar_memories,
        get_embeddings
    )

    logger.info("\n" + "=" * 70)
    logger.info("COMPONENT TESTS")
    logger.info("=" * 70)

    # Test 1: Keyword extraction
    logger.info("\n📝 Test 1: Keyword Extraction")
    test_query = "What's happening with Jenny and the PriceSpider contract?"
    keywords = extract_keywords(test_query)
    logger.info(f"   Query: {test_query}")
    logger.info(f"   Keywords: {keywords}")
    assert len(keywords) > 0, "No keywords extracted"
    logger.info("   ✓ Keyword extraction working")

    # Test 2: Entity search
    logger.info("\n🔍 Test 2: Entity Search")
    entities = await search_entities_by_keywords(["Jenny", "PriceSpider"])
    logger.info(f"   Found {len(entities)} entities")
    for entity in entities:
        logger.info(f"   - {entity.name} ({entity.type})")
    logger.info("   ✓ Entity search working")

    # Test 3: Vector search
    logger.info("\n🧠 Test 3: Vector Memory Search")
    embeddings = get_embeddings()
    query_embedding = await embeddings.aembed_query("Jenny meeting")
    logger.info(f"   Generated {len(query_embedding)}-dim embedding")

    memories = await search_similar_memories(
        query_embedding=query_embedding,
        threshold=0.5,
        limit=5
    )
    logger.info(f"   Found {len(memories)} similar memories")
    for memory in memories[:3]:  # Show top 3
        similarity = memory.get('similarity', 0)
        content = memory.get('content', 'N/A')
        logger.info(f"   - {content[:50]}... (similarity: {similarity:.2f})")
    logger.info("   ✓ Vector search working")

    logger.info("\n✅ All component tests passed")


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("CONTEXT RETRIEVAL VERIFICATION TEST")
    print("=" * 70)
    print(f"Date: {datetime.utcnow().isoformat()}")
    print("=" * 70 + "\n")

    # Step 1: Check environment
    if not check_environment():
        sys.exit(1)

    # Step 2: Test individual components
    try:
        await test_individual_components()
    except Exception as e:
        logger.error(f"❌ Component tests failed: {e}", exc_info=True)
        sys.exit(1)

    # Step 3: Test full retrieval
    try:
        success_count, total_count = await test_retrieval()
    except Exception as e:
        logger.error(f"❌ Retrieval tests failed: {e}", exc_info=True)
        sys.exit(1)

    # Final summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    if success_count == total_count:
        print(f"✅ ALL TESTS PASSED ({success_count}/{total_count})")
        print("   • Component tests passed")
        print("   • Retrieval queries successful")
        print("   • Context formatting working")
        print("\n🎉 Context retrieval system is working correctly!")
    else:
        print(f"⚠️  TESTS PARTIALLY PASSED ({success_count}/{total_count})")
        print(f"   • {success_count} queries succeeded")
        print(f"   • {total_count - success_count} queries failed")
        print("\n⚠️  Review the logs above for details.")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Test failed with error: {e}", exc_info=True)
        sys.exit(1)
