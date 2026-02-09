#!/usr/bin/env python3
"""
Demo script to visualize the dual-context briefing output.
Shows examples of different scenarios.
"""


def extract_context_items(context_str: str) -> str:
    """Extract bullet points from context."""
    lines = []
    for line in context_str.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            content_after_dash = stripped[2:].strip().lower()
            if not (content_after_dash.startswith("no relevant") or 
                    content_after_dash.startswith("no related")):
                lines.append(line)
    return "\n".join(lines) + "\n" if lines else ""


def format_dual_briefing(work_context: str, personal_context: str, 
                         family_context: str, cross_alerts: str) -> str:
    """Format dual-context briefing."""
    sections = ["Good morning, Ryan!\n"]
    
    sections.append("WORK")
    if work_context and "[No relevant memories found]" not in work_context:
        work_items = extract_context_items(work_context)
        if work_items.strip():
            sections.append(work_items)
        else:
            sections.append("- No work items to report\n")
    else:
        sections.append("- No work items to report\n")
    
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
    
    if cross_alerts and cross_alerts.strip():
        sections.append("CROSS-CONTEXT ALERTS")
        sections.append(cross_alerts)
    
    return "\n".join(sections)


def demo_scenario_1():
    """Demo: Full briefing with work, personal, and alerts."""
    print("=" * 70)
    print("SCENARIO 1: Full Briefing (Work + Personal + Alerts)")
    print("=" * 70)
    
    work = """[CONTEXT]
- Team standup at 10 AM (Feb 09)
- PriceSpider contract review deadline Friday
- Sprint planning session at 2 PM"""
    
    personal = """[CONTEXT]
- Dentist appointment Thursday at 2 PM
- Grocery shopping reminder"""
    
    family = """[CONTEXT]
- Kids pickup Friday at 6 PM
- Sarah's soccer practice Saturday 9 AM"""
    
    alerts = """- ⚠️ Work meeting at 2 PM conflicts with dentist appointment Thursday
- 📅 Friday is busy: Contract deadline + Kids pickup"""
    
    briefing = format_dual_briefing(work, personal, family, alerts)
    print(briefing)
    print(f"\nLength: {len(briefing)} characters")
    print()


def demo_scenario_2():
    """Demo: Work only briefing."""
    print("=" * 70)
    print("SCENARIO 2: Work Only (No Personal Items)")
    print("=" * 70)
    
    work = """[CONTEXT]
- Code review session at 11 AM
- Deploy to production at 3 PM
- Team retrospective at 4 PM"""
    
    briefing = format_dual_briefing(work, "", "", "")
    print(briefing)
    print(f"\nLength: {len(briefing)} characters")
    print()


def demo_scenario_3():
    """Demo: Personal/Family only briefing."""
    print("=" * 70)
    print("SCENARIO 3: Personal/Family Only (No Work Items)")
    print("=" * 70)
    
    personal = """[CONTEXT]
- Doctor appointment at 10 AM
- Pharmacy pickup reminder"""
    
    family = """[CONTEXT]
- Mike's school event tonight at 6 PM
- Family dinner reservations at 7:30 PM"""
    
    briefing = format_dual_briefing("", personal, family, "")
    print(briefing)
    print(f"\nLength: {len(briefing)} characters")
    print()


def demo_scenario_4():
    """Demo: Empty briefing (no items)."""
    print("=" * 70)
    print("SCENARIO 4: Empty Briefing (No Items Yet)")
    print("=" * 70)
    
    briefing = format_dual_briefing("", "", "", "")
    print(briefing)
    print(f"\nLength: {len(briefing)} characters")
    print()


def demo_scenario_5():
    """Demo: Cross-context alerts only."""
    print("=" * 70)
    print("SCENARIO 5: With Cross-Context Alerts")
    print("=" * 70)
    
    work = """[CONTEXT]
- Weekly sync at 2 PM today
- Q1 planning session tomorrow 10 AM"""
    
    family = """[CONTEXT]
- Kids pickup today at 2:30 PM (tight timing!)"""
    
    alerts = """- ⚠️ Weekly sync (2 PM) leaves only 30 min before kids pickup (2:30 PM)
- 💡 Consider joining sync from car or rescheduling"""
    
    briefing = format_dual_briefing(work, "", family, alerts)
    print(briefing)
    print(f"\nLength: {len(briefing)} characters")
    print()


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "DUAL-CONTEXT BRIEFING DEMO" + " " * 27 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    
    demo_scenario_1()
    demo_scenario_2()
    demo_scenario_3()
    demo_scenario_4()
    demo_scenario_5()
    
    print("=" * 70)
    print("✓ All scenarios demonstrate the dual-context briefing format")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
