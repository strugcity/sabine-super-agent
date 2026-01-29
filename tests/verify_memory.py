"""
Live Verification Test for Memory Ingestion Pipeline
====================================================

This script performs a real end-to-end test of the memory ingestion system.

Usage:
    python tests/verify_memory.py

Requirements:
    - ANTHROPIC_API_KEY must be set (for Claude 3.5 Sonnet extraction)
    - OPENAI_API_KEY must be set (for embeddings)
    - SUPABASE_URL must be set
    - SUPABASE_SERVICE_ROLE_KEY must be set
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from uuid import UUID

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def check_environment():
    """Verify all required environment variables are set."""
    required_vars = [
        "ANTHROPIC_API_KEY",  # For Claude 3.5 Sonnet (entity extraction)
        "OPENAI_API_KEY",     # For embeddings (text-embedding-3-small)
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


async def run_ingestion_test():
    """Run the ingestion test with sample data."""
    from lib.agent.memory import ingest_user_message

    # Test configuration
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")
    test_message = "I have a meeting with Jenny about the PriceSpider contract on Friday."

    logger.info("=" * 70)
    logger.info("MEMORY INGESTION TEST")
    logger.info("=" * 70)
    logger.info(f"User ID: {test_user_id}")
    logger.info(f"Message: {test_message}")
    logger.info("=" * 70)

    # Run ingestion
    logger.info("\n🧠 Running ingestion pipeline...")
    start_time = datetime.utcnow()

    try:
        result = await ingest_user_message(
            user_id=test_user_id,
            content=test_message,
            source="test"
        )

        end_time = datetime.utcnow()
        elapsed_ms = int((end_time - start_time).total_seconds() * 1000)

        logger.info("\n✅ Ingestion completed successfully!")
        logger.info("=" * 70)
        logger.info("INGESTION RESULT")
        logger.info("=" * 70)
        logger.info(f"Status: {result['status']}")
        logger.info(f"Memory ID: {result.get('memory_id', 'N/A')}")
        logger.info(f"Entities Created: {result.get('entities_created', 0)}")
        logger.info(f"Entities Updated: {result.get('entities_updated', 0)}")
        logger.info(f"Total Entities: {result.get('total_entities', 0)}")
        logger.info(f"Domain: {result.get('domain', 'N/A')}")
        logger.info(
            f"Processing Time: {result.get('processing_time_ms', elapsed_ms)}ms")
        logger.info(f"Entity IDs: {result.get('entity_ids', [])}")
        logger.info("=" * 70)

        return result

    except Exception as e:
        logger.error(f"\n❌ Ingestion failed: {e}", exc_info=True)
        return None


async def verify_entities(expected_names=None):
    """Query Supabase to verify entities were created."""
    if expected_names is None:
        expected_names = ["Jenny", "PriceSpider"]

    logger.info("\n🔍 Verifying entities in database...")
    logger.info("=" * 70)

    try:
        from lib.agent.memory import get_supabase_client

        supabase = get_supabase_client()

        # Query all entities
        response = supabase.table("entities").select("*").order(
            "created_at", desc=True
        ).limit(10).execute()

        if not response.data:
            logger.warning("⚠️  No entities found in database")
            return False

        logger.info(f"Found {len(response.data)} entities (showing last 10):")
        logger.info("-" * 70)

        found_entities = {}
        for entity in response.data:
            entity_name = entity.get('name', 'Unknown')
            entity_type = entity.get('type', 'unknown')
            entity_domain = entity.get('domain', 'unknown')
            entity_id = entity.get('id', 'N/A')
            created_at = entity.get('created_at', 'N/A')
            attributes = entity.get('attributes', {})

            logger.info(f"\n📦 Entity: {entity_name}")
            logger.info(f"   ID: {entity_id}")
            logger.info(f"   Type: {entity_type}")
            logger.info(f"   Domain: {entity_domain}")
            logger.info(f"   Created: {created_at}")
            logger.info(f"   Attributes: {attributes}")

            # Track if we found expected entities
            for expected in expected_names:
                if expected.lower() in entity_name.lower():
                    found_entities[expected] = entity

        logger.info("-" * 70)

        # Check if expected entities were found
        logger.info("\n✅ VERIFICATION RESULTS:")
        all_found = True
        for expected in expected_names:
            if expected in found_entities:
                logger.info(f"   ✓ Found entity: {expected}")
            else:
                logger.warning(f"   ✗ Missing entity: {expected}")
                all_found = False

        logger.info("=" * 70)
        return all_found

    except Exception as e:
        logger.error(f"❌ Failed to verify entities: {e}", exc_info=True)
        return False


async def verify_memories(memory_id=None):
    """Query Supabase to verify memory was stored."""
    logger.info("\n🔍 Verifying memories in database...")
    logger.info("=" * 70)

    try:
        from lib.agent.memory import get_supabase_client

        supabase = get_supabase_client()

        # Query memories
        query = supabase.table("memories").select(
            "*").order("created_at", desc=True).limit(5)

        if memory_id:
            query = supabase.table("memories").select("*").eq("id", memory_id)

        response = query.execute()

        if not response.data:
            logger.warning("⚠️  No memories found in database")
            return False

        logger.info(f"Found {len(response.data)} memories (showing last 5):")
        logger.info("-" * 70)

        for memory in response.data:
            memory_id = memory.get('id', 'N/A')
            content = memory.get('content', 'N/A')
            entity_links = memory.get('entity_links', [])
            metadata = memory.get('metadata', {})
            created_at = memory.get('created_at', 'N/A')

            logger.info(f"\n💭 Memory: {memory_id}")
            logger.info(f"   Content: {content}")
            logger.info(f"   Entity Links: {len(entity_links)} entities")
            logger.info(f"   Source: {metadata.get('source', 'N/A')}")
            logger.info(f"   Created: {created_at}")

        logger.info("-" * 70)
        logger.info("=" * 70)
        return True

    except Exception as e:
        logger.error(f"❌ Failed to verify memories: {e}", exc_info=True)
        return False


async def main():
    """Main test execution."""
    print("\n" + "=" * 70)
    print("LIVE MEMORY INGESTION VERIFICATION TEST")
    print("=" * 70)
    print(f"Date: {datetime.utcnow().isoformat()}")
    print("=" * 70 + "\n")

    # Step 1: Check environment
    if not check_environment():
        sys.exit(1)

    # Step 2: Run ingestion test
    result = await run_ingestion_test()

    if not result or result.get('status') != 'success':
        logger.error("\n❌ Ingestion test failed. Aborting verification.")
        sys.exit(1)

    memory_id = result.get('memory_id')

    # Step 3: Verify entities
    entities_ok = await verify_entities(expected_names=["Jenny", "PriceSpider"])

    # Step 4: Verify memories
    memories_ok = await verify_memories(memory_id=memory_id)

    # Final summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    if entities_ok and memories_ok:
        print("✅ ALL TESTS PASSED")
        print("   • Ingestion pipeline executed successfully")
        print("   • Expected entities found in database")
        print("   • Memory stored with embeddings")
        print("\n🎉 Memory ingestion system is working correctly!")
    else:
        print("⚠️  TESTS PARTIALLY PASSED")
        if not entities_ok:
            print("   • Some expected entities were not found")
        if not memories_ok:
            print("   • Memory verification failed")
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
