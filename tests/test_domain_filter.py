"""
Test Domain Filter in Retrieval Pipeline
=========================================

This script tests the domain_filter parameter threading through
the retrieval pipeline.

Usage:
    python tests/test_domain_filter.py

Requirements:
    - OPENAI_API_KEY must be set (for embeddings)
    - SUPABASE_URL must be set
    - SUPABASE_SERVICE_ROLE_KEY must be set
    - Database must have match_memories() SQL function with domain_filter parameter
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
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
        "OPENAI_API_KEY",
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


async def test_domain_filter_parameter_passing():
    """Test that domain_filter parameter is correctly passed through the pipeline."""
    from lib.agent.retrieval import (
        retrieve_context,
        search_similar_memories,
        search_entities_by_keywords,
        blend_context,
        get_embeddings
    )

    logger.info("\n" + "=" * 70)
    logger.info("DOMAIN FILTER PARAMETER PASSING TESTS")
    logger.info("=" * 70)

    test_user_id = UUID("00000000-0000-0000-0000-000000000001")
    test_query = "What work tasks do I have?"
    
    # Test 1: search_similar_memories accepts domain_filter
    logger.info("\n📝 Test 1: search_similar_memories with domain_filter")
    try:
        embeddings = get_embeddings()
        query_embedding = await embeddings.aembed_query(test_query)
        
        # Test with domain_filter=None (backward compatible)
        memories_all = await search_similar_memories(
            query_embedding=query_embedding,
            threshold=0.5,
            limit=5,
            domain_filter=None
        )
        logger.info(f"   Without filter: {len(memories_all)} memories")
        
        # Test with domain_filter="work"
        memories_work = await search_similar_memories(
            query_embedding=query_embedding,
            threshold=0.5,
            limit=5,
            domain_filter="work"
        )
        logger.info(f"   With filter='work': {len(memories_work)} memories")
        logger.info("   ✓ search_similar_memories accepts domain_filter")
        
    except Exception as e:
        logger.error(f"   ❌ search_similar_memories test failed: {e}")
        raise

    # Test 2: search_entities_by_keywords accepts domain_filter
    logger.info("\n📝 Test 2: search_entities_by_keywords with domain_filter")
    try:
        # Test with domain_filter=None (backward compatible)
        entities_all = await search_entities_by_keywords(
            keywords=["work", "task"],
            limit=10,
            domain_filter=None
        )
        logger.info(f"   Without filter: {len(entities_all)} entities")
        
        # Test with domain_filter="work"
        entities_work = await search_entities_by_keywords(
            keywords=["work", "task"],
            limit=10,
            domain_filter="work"
        )
        logger.info(f"   With filter='work': {len(entities_work)} entities")
        
        # Verify all entities have work domain
        if entities_work:
            for entity in entities_work:
                assert entity.domain.value == "work", f"Entity {entity.name} has domain {entity.domain.value}, expected 'work'"
            logger.info("   ✓ All filtered entities have work domain")
        
        logger.info("   ✓ search_entities_by_keywords accepts domain_filter")
        
    except Exception as e:
        logger.error(f"   ❌ search_entities_by_keywords test failed: {e}")
        raise

    # Test 3: blend_context adds domain labels
    logger.info("\n📝 Test 3: blend_context with domain labels")
    try:
        # Test without domain_filter
        context_no_filter = blend_context(
            memories=[],
            entities=[],
            query=test_query,
            domain_filter=None
        )
        logger.info("   Without filter:")
        logger.info(f"     Header: {context_no_filter.split(chr(10))[0]}")
        assert "(WORK DOMAIN)" not in context_no_filter
        assert "[RELEVANT MEMORIES]" in context_no_filter
        assert "[RELATED ENTITIES]" in context_no_filter
        logger.info("   ✓ No domain labels when filter is None")
        
        # Test with domain_filter="work"
        context_with_filter = blend_context(
            memories=[],
            entities=[],
            query=test_query,
            domain_filter="work"
        )
        logger.info("\n   With filter='work':")
        logger.info(f"     Header: {context_with_filter.split(chr(10))[0]}")
        assert "(WORK DOMAIN)" in context_with_filter
        assert "[RELEVANT WORK MEMORIES]" in context_with_filter
        assert "[RELATED WORK ENTITIES]" in context_with_filter
        logger.info("   ✓ Domain labels added when filter is active")
        
    except Exception as e:
        logger.error(f"   ❌ blend_context test failed: {e}")
        raise

    # Test 4: retrieve_context integrates domain_filter
    logger.info("\n📝 Test 4: retrieve_context with domain_filter")
    try:
        # Test without domain_filter (backward compatible)
        context_no_filter = await retrieve_context(
            user_id=test_user_id,
            query=test_query,
            memory_threshold=0.5,
            memory_limit=3,
            entity_limit=5,
            role_filter="assistant",
            domain_filter=None
        )
        logger.info("   Without filter:")
        logger.info(f"     Context length: {len(context_no_filter)} chars")
        assert "[CONTEXT FOR:" in context_no_filter
        logger.info("   ✓ retrieve_context works without domain_filter")
        
        # Test with domain_filter="work"
        context_with_filter = await retrieve_context(
            user_id=test_user_id,
            query=test_query,
            memory_threshold=0.5,
            memory_limit=3,
            entity_limit=5,
            role_filter="assistant",
            domain_filter="work"
        )
        logger.info("\n   With filter='work':")
        logger.info(f"     Context length: {len(context_with_filter)} chars")
        assert "(WORK DOMAIN)" in context_with_filter
        logger.info("   ✓ retrieve_context includes domain labels")
        
    except Exception as e:
        logger.error(f"   ❌ retrieve_context test failed: {e}")
        raise

    logger.info("\n✅ All domain filter tests passed")
    return True


async def test_backward_compatibility():
    """Test that existing code without domain_filter still works."""
    from lib.agent.retrieval import retrieve_context

    logger.info("\n" + "=" * 70)
    logger.info("BACKWARD COMPATIBILITY TEST")
    logger.info("=" * 70)

    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    try:
        # Call retrieve_context without domain_filter parameter
        context = await retrieve_context(
            user_id=test_user_id,
            query="What's happening?",
            memory_threshold=0.6,
            memory_limit=5,
            entity_limit=10,
            role_filter="assistant"
            # Note: domain_filter not provided, should default to None
        )
        
        logger.info(f"✓ retrieve_context works without domain_filter parameter")
        logger.info(f"  Context length: {len(context)} chars")
        
        # Verify no domain labels in output
        assert "(WORK DOMAIN)" not in context
        assert "(PERSONAL DOMAIN)" not in context
        assert "[RELEVANT MEMORIES]" in context  # Not "[RELEVANT WORK MEMORIES]"
        logger.info("✓ Backward compatible - no domain labels when filter is None")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Backward compatibility test failed: {e}")
        raise


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("DOMAIN FILTER RETRIEVAL PIPELINE TEST")
    print("=" * 70)
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70 + "\n")

    # Step 1: Check environment
    if not check_environment():
        sys.exit(1)

    # Step 2: Test domain filter parameter passing
    try:
        await test_domain_filter_parameter_passing()
    except Exception as e:
        logger.error(f"❌ Domain filter tests failed: {e}", exc_info=True)
        sys.exit(1)

    # Step 3: Test backward compatibility
    try:
        await test_backward_compatibility()
    except Exception as e:
        logger.error(f"❌ Backward compatibility test failed: {e}", exc_info=True)
        sys.exit(1)

    # Final summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print("✅ ALL TESTS PASSED")
    print("   • Domain filter parameter threading works correctly")
    print("   • Domain labels added to context when filtering")
    print("   • Backward compatibility maintained (domain_filter=None)")
    print("   • Entity domain filtering works correctly")
    print("\n🎉 Domain filter integration is working correctly!")
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
