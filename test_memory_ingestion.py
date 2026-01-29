"""
Test script for the memory ingestion pipeline.

Run this after setting up environment variables:
- OPENAI_API_KEY
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY

Usage:
    python test_memory_ingestion.py
"""

import asyncio
import logging
from uuid import UUID

from lib.agent.memory import ingest_user_message, extract_context

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def test_extraction_only():
    """Test just the entity extraction (no DB writes)."""
    print("\n" + "=" * 70)
    print("TEST 1: Entity Extraction (GPT-4o)")
    print("=" * 70)

    test_messages = [
        "Baseball game moved to 5 PM Saturday at Lincoln Park",
        "Told Alice to review the Q1 budget deck by Friday",
        "Meeting with Dr. Smith rescheduled to next Wednesday at 2 PM",
        "Need to buy groceries: milk, eggs, bread"
    ]

    for msg in test_messages:
        print(f"\n📝 Input: {msg}")
        result = await extract_context(msg)
        print(f"   Domain: {result.domain}")
        print(f"   Entities: {len(result.extracted_entities)}")
        for entity in result.extracted_entities:
            print(f"      - {entity.name} ({entity.type})")
            print(f"        Attributes: {entity.attributes}")
        print(f"   Memory: {result.core_memory}")


async def test_full_ingestion():
    """Test the complete ingestion pipeline."""
    print("\n" + "=" * 70)
    print("TEST 2: Full Ingestion Pipeline")
    print("=" * 70)

    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    test_messages = [
        "Baseball game moved to 5 PM Saturday at Lincoln Park",
        "Alice needs to review the Q1 budget deck by Friday",
    ]

    for msg in test_messages:
        print(f"\n🧠 Ingesting: {msg}")
        result = await ingest_user_message(
            user_id=test_user_id,
            content=msg,
            source="test"
        )

        print(f"   Status: {result['status']}")
        if result['status'] == 'success':
            print(f"   Memory ID: {result['memory_id']}")
            print(f"   Created: {result['entities_created']} entities")
            print(f"   Updated: {result['entities_updated']} entities")
            print(f"   Time: {result['processing_time_ms']}ms")
        else:
            print(f"   Error: {result.get('error')}")


async def main():
    """Run all tests."""
    print("\n🚀 Memory Ingestion Pipeline Test Suite")
    print("=" * 70)

    # Test 1: Extraction only (no DB required for basic testing)
    await test_extraction_only()

    # Test 2: Full ingestion (requires DB connection)
    print("\n\nAttempting full ingestion test...")
    print("(This requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)")
    try:
        await test_full_ingestion()
    except Exception as e:
        print(f"\n⚠️  Full ingestion test skipped: {e}")
        print("   This is expected if Supabase is not configured.")

    print("\n" + "=" * 70)
    print("✅ Tests complete!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
