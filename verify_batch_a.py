"""
Verification script for Phase 2 Batch A: Tool Set Definitions
"""

import sys

def verify_batch_a():
    """Verify that Batch A is implemented correctly."""
    
    print("=" * 60)
    print("Phase 2 Batch A Verification")
    print("=" * 60)
    
    all_passed = True
    
    # Test 1: tool_sets.py exists and imports correctly
    print("\n[Test 1] Checking tool_sets.py exists and imports...")
    try:
        from lib.agent.tool_sets import (
            SABINE_TOOLS,
            DREAM_TEAM_TOOLS,
            get_tool_names,
            is_tool_allowed,
            AgentRole,
        )
        print("✓ PASS: tool_sets.py imports successfully")
    except Exception as e:
        print(f"✗ FAIL: Could not import tool_sets.py: {e}")
        all_passed = False
        return all_passed
    
    # Test 2: SABINE_TOOLS has correct tools
    print("\n[Test 2] Checking SABINE_TOOLS definition...")
    expected_sabine = {
        "get_calendar_events",
        "create_calendar_event",
        "get_custody_schedule",
        "get_weather",
        "create_reminder",
        "cancel_reminder",
        "list_reminders",
    }
    if SABINE_TOOLS == expected_sabine:
        print(f"✓ PASS: SABINE_TOOLS has {len(SABINE_TOOLS)} tools")
    else:
        print(f"✗ FAIL: SABINE_TOOLS mismatch")
        print(f"  Expected: {expected_sabine}")
        print(f"  Got: {SABINE_TOOLS}")
        all_passed = False
    
    # Test 3: DREAM_TEAM_TOOLS has correct tools
    print("\n[Test 3] Checking DREAM_TEAM_TOOLS definition...")
    expected_dream = {
        "github_issues",
        "run_python_sandbox",
        "sync_project_board",
        "send_team_update",
    }
    if DREAM_TEAM_TOOLS == expected_dream:
        print(f"✓ PASS: DREAM_TEAM_TOOLS has {len(DREAM_TEAM_TOOLS)} tools")
    else:
        print(f"✗ FAIL: DREAM_TEAM_TOOLS mismatch")
        print(f"  Expected: {expected_dream}")
        print(f"  Got: {DREAM_TEAM_TOOLS}")
        all_passed = False
    
    # Test 4: get_tool_names() works correctly
    print("\n[Test 4] Testing get_tool_names() function...")
    try:
        assistant_tools = get_tool_names("assistant")
        coder_tools = get_tool_names("coder")
        
        if assistant_tools == SABINE_TOOLS:
            print("✓ PASS: get_tool_names('assistant') returns SABINE_TOOLS")
        else:
            print("✗ FAIL: get_tool_names('assistant') mismatch")
            all_passed = False
        
        if coder_tools == DREAM_TEAM_TOOLS:
            print("✓ PASS: get_tool_names('coder') returns DREAM_TEAM_TOOLS")
        else:
            print("✗ FAIL: get_tool_names('coder') mismatch")
            all_passed = False
    except Exception as e:
        print(f"✗ FAIL: get_tool_names() error: {e}")
        all_passed = False
    
    # Test 5: is_tool_allowed() works correctly
    print("\n[Test 5] Testing is_tool_allowed() function...")
    try:
        if is_tool_allowed("get_calendar_events", "assistant"):
            print("✓ PASS: is_tool_allowed('get_calendar_events', 'assistant') = True")
        else:
            print("✗ FAIL: is_tool_allowed should allow calendar for assistant")
            all_passed = False
        
        if not is_tool_allowed("github_issues", "assistant"):
            print("✓ PASS: is_tool_allowed('github_issues', 'assistant') = False")
        else:
            print("✗ FAIL: is_tool_allowed should block github for assistant")
            all_passed = False
    except Exception as e:
        print(f"✗ FAIL: is_tool_allowed() error: {e}")
        all_passed = False
    
    # Test 6: registry.py imports get_scoped_tools
    print("\n[Test 6] Checking registry.py has get_scoped_tools()...")
    try:
        from lib.agent.registry import get_scoped_tools, get_all_tools
        print("✓ PASS: get_scoped_tools imported successfully")
    except Exception as e:
        print(f"✗ FAIL: Could not import get_scoped_tools: {e}")
        all_passed = False
        return all_passed
    
    # Test 7: get_all_tools() still works (backward compatibility)
    print("\n[Test 7] Checking get_all_tools() backward compatibility...")
    try:
        import asyncio
        tools = asyncio.run(get_all_tools())
        print(f"✓ PASS: get_all_tools() returns {len(tools)} tools")
    except Exception as e:
        print(f"✗ FAIL: get_all_tools() error: {e}")
        all_passed = False
    
    # Test 8: get_scoped_tools() returns correct subset
    print("\n[Test 8] Testing get_scoped_tools() filtering...")
    try:
        import asyncio
        
        all_tools = asyncio.run(get_all_tools())
        assistant_scoped = asyncio.run(get_scoped_tools("assistant"))
        coder_scoped = asyncio.run(get_scoped_tools("coder"))
        
        all_tool_names = {t.name for t in all_tools}
        assistant_names = {t.name for t in assistant_scoped}
        coder_names = {t.name for t in coder_scoped}
        
        # Check that scoped tools are subsets of all tools
        if assistant_names.issubset(all_tool_names):
            print(f"✓ PASS: assistant tools ({len(assistant_names)}) are subset of all tools")
        else:
            print("✗ FAIL: assistant tools contain tools not in all_tools")
            all_passed = False
        
        if coder_names.issubset(all_tool_names):
            print(f"✓ PASS: coder tools ({len(coder_names)}) are subset of all tools")
        else:
            print("✗ FAIL: coder tools contain tools not in all_tools")
            all_passed = False
        
        # Check that scoped tools match expected sets (within available tools)
        expected_assistant = SABINE_TOOLS.intersection(all_tool_names)
        expected_coder = DREAM_TEAM_TOOLS.intersection(all_tool_names)
        
        if assistant_names == expected_assistant:
            print(f"✓ PASS: assistant tools match SABINE_TOOLS definition")
        else:
            print("✗ FAIL: assistant tools don't match SABINE_TOOLS")
            print(f"  Expected: {expected_assistant}")
            print(f"  Got: {assistant_names}")
            all_passed = False
        
        if coder_names == expected_coder:
            print(f"✓ PASS: coder tools match DREAM_TEAM_TOOLS definition")
        else:
            print("✗ FAIL: coder tools don't match DREAM_TEAM_TOOLS")
            print(f"  Expected: {expected_coder}")
            print(f"  Got: {coder_names}")
            all_passed = False
        
    except Exception as e:
        print(f"✗ FAIL: get_scoped_tools() error: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    passed = verify_batch_a()
    sys.exit(0 if passed else 1)
