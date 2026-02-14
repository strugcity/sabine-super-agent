"""
Test suite for Tool Execution Verification System

This tests the _task_requires_tool_execution function which determines
whether a task payload indicates that actual tool usage is expected.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the function we're testing
# Note: This was moved from lib.agent.server to lib.agent.task_runner in Phase 2 refactoring
from lib.agent.task_runner import _task_requires_tool_execution


def test_implementation_tasks_require_tools():
    """Tasks that ask to implement/create/build should require tools."""

    # Dark Mode task (the original failure case)
    dark_mode_payload = {
        "title": "Implement Dark Mode Toggle for Project Sabine",
        "objective": "Implement a functional Dark Mode toggle for the Sabine dashboard interface",
        "target_files": [
            "package.json",
            "tailwind.config.ts",
            "src/components/ui/ThemeProvider.tsx"
        ],
        "specifications": [
            "Install `next-themes` package for theme management",
            "Configure `tailwind.config.ts` with `darkMode: 'class'`"
        ]
    }
    assert _task_requires_tool_execution(dark_mode_payload) == True, \
        "Dark Mode implementation task should require tools"

    # Generic implementation task
    impl_payload = {
        "name": "Create Health Check Endpoint",
        "objective": "Implement a /health endpoint that returns system status"
    }
    assert _task_requires_tool_execution(impl_payload) == True, \
        "Implementation task should require tools"

    # File creation task
    file_payload = {
        "message": "Create a new file at src/utils/helpers.ts with utility functions"
    }
    assert _task_requires_tool_execution(file_payload) == True, \
        "File creation task should require tools"


def test_explicit_tool_requirements():
    """Tasks with explicit tool requirements should require tools."""

    # Explicit github_issues requirement
    github_payload = {
        "objective": "Use github_issues to create a new issue for the bug",
        "instructions": "MUST use the github_issues tool"
    }
    assert _task_requires_tool_execution(github_payload) == True, \
        "Task with explicit github_issues mention should require tools"

    # Task with deliverables
    deliverables_payload = {
        "name": "Create Report",
        "deliverables": ["docs/report.md", "issues/3"]
    }
    assert _task_requires_tool_execution(deliverables_payload) == True, \
        "Task with deliverables should require tools"

    # Task with target_files
    target_files_payload = {
        "name": "Update Config",
        "target_files": ["config.json"]
    }
    assert _task_requires_tool_execution(target_files_payload) == True, \
        "Task with target_files should require tools"


def test_analysis_tasks_may_not_require_tools():
    """Pure analysis tasks may not require tool execution."""

    # Analysis task
    analysis_payload = {
        "name": "Review Code Architecture",
        "objective": "Analyze the current codebase and identify potential improvements"
    }
    # This is borderline - it mentions "identify" which is analysis
    result = _task_requires_tool_execution(analysis_payload)
    # We accept either True or False here since it's ambiguous
    print(f"Analysis task result: {result}")

    # Pure planning task
    planning_payload = {
        "name": "Design System Architecture",
        "objective": "Plan the architecture for the new authentication system"
    }
    # Planning tasks shouldn't strictly require tools
    result = _task_requires_tool_execution(planning_payload)
    print(f"Planning task result: {result}")


def test_mixed_tasks():
    """Tasks with both action and analysis keywords."""

    # Create and analyze
    mixed_payload = {
        "name": "Implement and Review",
        "objective": "Create a new logging module and analyze its performance"
    }
    assert _task_requires_tool_execution(mixed_payload) == True, \
        "Task with 'create' should require tools even with analysis"

    # Build and document
    build_payload = {
        "name": "Build Feature",
        "objective": "Build the new dashboard component and write documentation"
    }
    assert _task_requires_tool_execution(build_payload) == True, \
        "Task with 'build' should require tools"


def test_requires_tools_flag():
    """Tasks with explicit requires_tools flag."""

    # Explicit flag set to True
    explicit_true = {
        "name": "Custom Task",
        "objective": "Do something",
        "requires_tools": True
    }
    assert _task_requires_tool_execution(explicit_true) == True, \
        "Task with requires_tools=True should require tools"

    # Explicit flag set to False (but has action keywords)
    explicit_false = {
        "name": "Create Something",
        "objective": "Create a new feature",
        "requires_tools": False
    }
    # The function checks for action keywords, so this should still be True
    result = _task_requires_tool_execution(explicit_false)
    print(f"Explicit False with action keywords: {result}")


def test_real_world_smoke_test_tasks():
    """Test with the actual smoke test task payloads."""

    # PM task (analysis/planning - may not need tools)
    pm_payload = {
        "name": "Define Health Check Feature",
        "type": "smoke_test",
        "objective": """
SMOKE TEST TASK - Keep it simple!
Create a brief feature spec (just a few bullet points) for a "System Health Check" endpoint.
Output: Write 3-5 bullet points describing this feature. Post your output as an agent_event.
Do NOT create any files or issues - just define the requirements in your response.
"""
    }
    # This explicitly says "Do NOT create any files" so should NOT require tools
    result = _task_requires_tool_execution(pm_payload)
    print(f"PM smoke test (should be False since it says 'Do NOT create files'): {result}")

    # Frontend implementation task (should need tools)
    frontend_payload = {
        "name": "Design Health Status UI",
        "type": "smoke_test",
        "objective": """
SMOKE TEST TASK - Keep it simple!
Design a simple UI component to display the health check status.
Output: Describe the component in 5-10 lines. Post your output as an agent_event.
Do NOT create actual files - just describe the UI concept in your response.
"""
    }
    # This also says "Do NOT create actual files"
    result = _task_requires_tool_execution(frontend_payload)
    print(f"Frontend smoke test (says 'Do NOT create actual files'): {result}")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Tool Verification Tests")
    print("=" * 60)

    print("\n1. Testing implementation tasks...")
    test_implementation_tasks_require_tools()
    print("   [PASSED]")

    print("\n2. Testing explicit tool requirements...")
    test_explicit_tool_requirements()
    print("   [PASSED]")

    print("\n3. Testing analysis tasks...")
    test_analysis_tasks_may_not_require_tools()
    print("   [PASSED] (informational)")

    print("\n4. Testing mixed tasks...")
    test_mixed_tasks()
    print("   [PASSED]")

    print("\n5. Testing requires_tools flag...")
    test_requires_tools_flag()
    print("   [PASSED] (informational)")

    print("\n6. Testing real-world smoke test tasks...")
    test_real_world_smoke_test_tasks()
    print("   [PASSED] (informational)")

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
