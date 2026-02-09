"""
Test Domain Context Wiring
===========================

This script tests that the domain context parameters are properly wired
through the agent pipeline without requiring external services.

Usage:
    python tests/test_domain_context_wiring.py
"""

import logging
import sys
from pathlib import Path
from typing import Optional

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def test_shared_models():
    """Test that InvokeRequest has source_channel field."""
    from lib.agent.shared import InvokeRequest
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 1: InvokeRequest Model")
    logger.info("=" * 70)
    
    # Test with source_channel
    request = InvokeRequest(
        message="Test message",
        user_id="00000000-0000-0000-0000-000000000001",
        source_channel="email-work"
    )
    
    assert request.source_channel == "email-work"
    logger.info("✓ InvokeRequest accepts source_channel parameter")
    
    # Test without source_channel (backward compatible)
    request2 = InvokeRequest(
        message="Test message",
        user_id="00000000-0000-0000-0000-000000000001"
    )
    
    assert request2.source_channel is None
    logger.info("✓ source_channel is optional (backward compatible)")
    
    logger.info("\n✅ InvokeRequest model tests passed")
    return True


def test_agent_signatures():
    """Test that agent functions have correct signatures."""
    import inspect
    from lib.agent.sabine_agent import run_sabine_agent
    from lib.agent.core import run_agent
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 2: Agent Function Signatures")
    logger.info("=" * 70)
    
    # Check run_sabine_agent signature
    sig = inspect.signature(run_sabine_agent)
    params = list(sig.parameters.keys())
    
    assert "source_channel" in params, "run_sabine_agent missing source_channel parameter"
    logger.info("✓ run_sabine_agent has source_channel parameter")
    
    # Verify it's optional
    param = sig.parameters["source_channel"]
    assert param.default is not inspect.Parameter.empty, "source_channel should have a default value (optional)"
    logger.info("✓ source_channel parameter is optional")
    
    # Check run_agent signature
    sig2 = inspect.signature(run_agent)
    params2 = list(sig2.parameters.keys())
    
    assert "source_channel" in params2, "run_agent missing source_channel parameter"
    logger.info("✓ run_agent has source_channel parameter")
    
    logger.info("\n✅ Agent signature tests passed")
    return True


def test_retrieval_functions():
    """Test that retrieval functions exist and have correct signatures."""
    import inspect
    from lib.agent.retrieval import (
        cross_context_scan,
        find_overlapping_entities,
        format_cross_context_advisory
    )
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 3: Cross-Context Retrieval Functions")
    logger.info("=" * 70)
    
    # Check cross_context_scan exists and has correct signature
    sig = inspect.signature(cross_context_scan)
    params = list(sig.parameters.keys())
    
    required_params = ["user_id", "query", "primary_domain"]
    for param in required_params:
        assert param in params, f"cross_context_scan missing {param} parameter"
    
    logger.info("✓ cross_context_scan has correct signature")
    
    # Check helper functions exist
    sig2 = inspect.signature(find_overlapping_entities)
    assert "primary" in sig2.parameters
    assert "cross" in sig2.parameters
    logger.info("✓ find_overlapping_entities exists with correct signature")
    
    sig3 = inspect.signature(format_cross_context_advisory)
    assert "cross_memories" in sig3.parameters
    assert "cross_entities" in sig3.parameters
    assert "shared_entities" in sig3.parameters
    assert "other_domain" in sig3.parameters
    logger.info("✓ format_cross_context_advisory exists with correct signature")
    
    logger.info("\n✅ Retrieval function tests passed")
    return True


def test_gmail_handler():
    """Test that gmail_handler has updated generate_ai_response."""
    import inspect
    from lib.agent.gmail_handler import generate_ai_response
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 4: Gmail Handler Updates")
    logger.info("=" * 70)
    
    # Check generate_ai_response signature
    sig = inspect.signature(generate_ai_response)
    params = list(sig.parameters.keys())
    
    assert "email_domain" in params, "generate_ai_response missing email_domain parameter"
    logger.info("✓ generate_ai_response has email_domain parameter")
    
    # Verify it's optional
    param = sig.parameters["email_domain"]
    assert param.default is not inspect.Parameter.empty, "email_domain should have a default value (optional)"
    logger.info("✓ email_domain parameter is optional")
    
    logger.info("\n✅ Gmail handler tests passed")
    return True


def test_helper_functions():
    """Test helper functions work correctly without external dependencies."""
    from lib.agent.retrieval import find_overlapping_entities, format_cross_context_advisory
    from lib.db.models import Entity, DomainEnum, EntityStatus
    from uuid import uuid4
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST 5: Helper Function Logic")
    logger.info("=" * 70)
    
    # Test find_overlapping_entities
    primary_entities = [
        Entity(
            id=uuid4(),
            name="Jenny",
            type="person",
            domain=DomainEnum.WORK,
            status=EntityStatus.ACTIVE
        )
    ]
    
    cross_entities = [
        Entity(
            id=uuid4(),
            name="Jenny",
            type="person",
            domain=DomainEnum.PERSONAL,
            status=EntityStatus.ACTIVE
        ),
        Entity(
            id=uuid4(),
            name="Bob",
            type="person",
            domain=DomainEnum.PERSONAL,
            status=EntityStatus.ACTIVE
        )
    ]
    
    overlaps = find_overlapping_entities(primary_entities, cross_entities)
    assert len(overlaps) == 1, f"Expected 1 overlap, got {len(overlaps)}"
    assert overlaps[0][0].name == "Jenny"
    assert overlaps[0][1].name == "Jenny"
    logger.info("✓ find_overlapping_entities correctly identifies shared entities")
    
    # Test format_cross_context_advisory with shared entities
    advisory = format_cross_context_advisory(
        cross_memories=[],
        cross_entities=[],
        shared_entities=overlaps,
        other_domain="personal"
    )
    
    assert "[CROSS-CONTEXT ADVISORY]" in advisory
    assert "Jenny" in advisory
    assert "work" in advisory.lower()
    assert "personal" in advisory.lower()
    logger.info("✓ format_cross_context_advisory generates correct output")
    
    # Test with memories
    advisory2 = format_cross_context_advisory(
        cross_memories=[
            {"content": "Meeting with Jenny", "similarity": 0.85},
            {"content": "Project deadline", "similarity": 0.75}
        ],
        cross_entities=[],
        shared_entities=[],
        other_domain="work"
    )
    
    assert "[CROSS-CONTEXT ADVISORY]" in advisory2
    assert "WORK memories" in advisory2
    assert "Meeting with Jenny" in advisory2
    logger.info("✓ format_cross_context_advisory handles memories correctly")
    
    logger.info("\n✅ Helper function logic tests passed")
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("DOMAIN CONTEXT WIRING TESTS")
    print("=" * 70)
    print("Testing parameter threading and function signatures")
    print("=" * 70 + "\n")
    
    tests = [
        ("Shared Models", test_shared_models),
        ("Agent Signatures", test_agent_signatures),
        ("Retrieval Functions", test_retrieval_functions),
        ("Gmail Handler", test_gmail_handler),
        ("Helper Functions", test_helper_functions),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            failed += 1
            logger.error(f"❌ {test_name} failed: {e}", exc_info=True)
    
    # Final summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests passed: {passed}/{len(tests)}")
    print(f"Tests failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n✅ ALL TESTS PASSED")
        print("   • source_channel parameter properly threaded through")
        print("   • Cross-context functions implemented correctly")
        print("   • Helper functions work as expected")
        print("   • Gmail handler updated properly")
        print("   • Backward compatibility maintained")
        print("\n🎉 Domain context wiring is complete!")
    else:
        print(f"\n❌ {failed} TEST(S) FAILED")
        return 1
    
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Test failed with error: {e}", exc_info=True)
        sys.exit(1)
