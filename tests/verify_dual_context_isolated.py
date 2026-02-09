"""
Isolated verification of dual-context briefing functions.
Tests only the pure Python functions without imports.
"""


def extract_context_items(context_str: str) -> str:
    """
    Extract the memory and entity bullet points from a formatted context string.
    (Copied from scheduler.py for isolated testing)
    """
    lines = []
    for line in context_str.split("\n"):
        stripped = line.strip()
        # Include lines that start with "- " but skip "No relevant" / "No related" messages
        if stripped.startswith("- "):
            # Check if this is a "No relevant/related" message
            content_after_dash = stripped[2:].strip().lower()
            if not (content_after_dash.startswith("no relevant") or 
                    content_after_dash.startswith("no related")):
                lines.append(line)
    return "\n".join(lines) + "\n" if lines else ""


def format_dual_briefing(
    work_context: str,
    personal_context: str,
    family_context: str,
    cross_alerts: str,
) -> str:
    """
    Format a structured dual-context morning briefing.
    (Copied from scheduler.py for isolated testing)
    """
    sections = ["Good morning, Ryan!\n"]

    # Work section
    sections.append("WORK")
    if work_context and "[No relevant memories found]" not in work_context:
        work_items = extract_context_items(work_context)
        if work_items.strip():
            sections.append(work_items)
        else:
            sections.append("- No work items to report\n")
    else:
        sections.append("- No work items to report\n")

    # Personal/Family section
    sections.append("PERSONAL/FAMILY")
    combined_personal = ""
    if personal_context and "[No relevant memories found]" not in personal_context:
        combined_personal += extract_context_items(personal_context)
    if family_context and "[No relevant memories found]" not in family_context:
        combined_personal += extract_context_items(family_context)

    if combined_personal.strip():
        sections.append(combined_personal)
    else:
        sections.append("- No personal items to report\n")

    # Cross-context alerts (if any)
    if cross_alerts and cross_alerts.strip():
        sections.append("CROSS-CONTEXT ALERTS")
        sections.append(cross_alerts)

    return "\n".join(sections)


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
    import sys
    sys.exit(main())
