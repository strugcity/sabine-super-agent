"""
Simple verification script for dual-context briefing.
Tests the core functions without requiring pytest.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.agent.scheduler import extract_context_items, format_dual_briefing


def test_extract_context_items():
    """Test context extraction."""
    print("\n" + "="*60)
    print("TEST: extract_context_items")
    print("="*60)
    
    mock_context = """[CONTEXT FOR: "work tasks" (WORK DOMAIN)]

[RELEVANT WORK MEMORIES]
- Team standup scheduled for 10 AM (Feb 09, 85% match)
- PriceSpider contract review deadline Friday (Feb 08)

[RELATED WORK ENTITIES]
- Jenny (Person, Work): Partner at PriceSpider
- No related entities found"""
    
    items = extract_context_items(mock_context)
    print(f"Input length: {len(mock_context)} chars")
    print(f"Output length: {len(items)} chars")
    print("\nExtracted items:")
    print(items)
    
    # Verify expectations
    assert "- Team standup" in items, "Should include memory item"
    assert "- Jenny" in items, "Should include entity item"
    assert "[CONTEXT FOR:" not in items, "Should not include header"
    assert "No related entities" not in items, "Should not include 'No' items"
    print("✓ All assertions passed")


def test_format_dual_briefing():
    """Test dual-context briefing formatter."""
    print("\n" + "="*60)
    print("TEST: format_dual_briefing")
    print("="*60)
    
    work = """[CONTEXT]
- Meeting at 10 AM
- Contract deadline Friday"""
    
    personal = """[CONTEXT]
- Dentist appointment Thursday"""
    
    family = """[CONTEXT]
- Kids pickup Friday 6 PM"""
    
    alerts = """[CROSS-CONTEXT ADVISORY]
- Work meeting conflicts with dentist"""
    
    briefing = format_dual_briefing(work, personal, family, alerts)
    print(f"Briefing length: {len(briefing)} chars")
    print("\nGenerated briefing:")
    print(briefing)
    print("\n" + "-"*60)
    
    # Verify structure
    assert "Good morning, Ryan!" in briefing, "Should have greeting"
    assert "WORK" in briefing, "Should have WORK section"
    assert "PERSONAL/FAMILY" in briefing, "Should have PERSONAL/FAMILY section"
    assert "CROSS-CONTEXT ALERTS" in briefing, "Should have CROSS-CONTEXT ALERTS section"
    assert "Meeting at 10 AM" in briefing, "Should include work item"
    assert "Dentist appointment" in briefing, "Should include personal item"
    assert "Kids pickup" in briefing, "Should include family item"
    assert "conflicts with dentist" in briefing, "Should include alert"
    print("✓ All assertions passed")


def test_format_dual_briefing_empty():
    """Test formatting with no items."""
    print("\n" + "="*60)
    print("TEST: format_dual_briefing (empty)")
    print("="*60)
    
    briefing = format_dual_briefing("", "", "", "")
    print(f"Briefing length: {len(briefing)} chars")
    print("\nGenerated briefing:")
    print(briefing)
    print("\n" + "-"*60)
    
    # Verify graceful handling
    assert "Good morning, Ryan!" in briefing, "Should have greeting"
    assert "No work items to report" in briefing, "Should have empty work message"
    assert "No personal items to report" in briefing, "Should have empty personal message"
    assert "CROSS-CONTEXT ALERTS" not in briefing, "Should not show empty alerts section"
    print("✓ All assertions passed")


def test_format_dual_briefing_work_only():
    """Test formatting with only work items."""
    print("\n" + "="*60)
    print("TEST: format_dual_briefing (work only)")
    print("="*60)
    
    work = """[CONTEXT]
- Team standup 10 AM
- Sprint planning 2 PM"""
    
    briefing = format_dual_briefing(work, "", "", "")
    print(f"Briefing length: {len(briefing)} chars")
    print("\nGenerated briefing:")
    print(briefing)
    print("\n" + "-"*60)
    
    # Verify partial content handling
    assert "Good morning, Ryan!" in briefing
    assert "WORK" in briefing
    assert "Team standup" in briefing
    assert "No personal items to report" in briefing
    print("✓ All assertions passed")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("DUAL-CONTEXT BRIEFING VERIFICATION")
    print("="*60)
    
    try:
        test_extract_context_items()
        test_format_dual_briefing()
        test_format_dual_briefing_empty()
        test_format_dual_briefing_work_only()
        
        print("\n" + "="*60)
        print("✓ ALL TESTS PASSED")
        print("="*60)
        return 0
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
