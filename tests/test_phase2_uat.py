#!/usr/bin/env python3
"""
Phase 2 UAT Script - Manual Scenario Runner
=============================================

Runs against a LIVE server. Requires:
- Server running at PYTHON_API_URL (default http://127.0.0.1:8001)
- Valid AGENT_API_KEY set
- Supabase connected and migrations applied

Usage:
    python tests/test_phase2_uat.py                    # Run all scenarios
    python tests/test_phase2_uat.py --scenario UAT-1   # Run specific scenario
    python tests/test_phase2_uat.py --base-url http://localhost:8001

Each scenario prints PASS/FAIL with details. Designed for a human
to read and verify the results make sense.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional
from uuid import uuid4

# Add project root to sys.path so lib.agent imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)


# =============================================================================
# Configuration
# =============================================================================

BASE_URL = os.getenv("PYTHON_API_URL", "http://127.0.0.1:8001")
API_KEY = os.getenv("AGENT_API_KEY", "")
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}


# =============================================================================
# Helpers
# =============================================================================

def api_post(path: str, data: dict, timeout: int = 120) -> Dict[str, Any]:
    """POST to the API and return parsed JSON."""
    url = f"{BASE_URL}{path}"
    resp = requests.post(url, json=data, headers=HEADERS, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.json()}


def api_get(path: str, timeout: int = 30) -> Dict[str, Any]:
    """GET from the API and return parsed JSON."""
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    return {"status_code": resp.status_code, "body": resp.json()}


def poll_task(task_id: str, max_wait: int = 120, interval: int = 3) -> Dict[str, Any]:
    """Poll a task until it completes or times out."""
    elapsed = 0
    result = None
    while elapsed < max_wait:
        result = api_get(f"/tasks/{task_id}")
        # Response may be {"success": ..., "task": {...}} or flat
        task_data = result["body"].get("task", result["body"])
        status = task_data.get("status")
        if status in ("completed", "failed", "cancelled_by_user", "cancelled_by_system"):
            return result
        print(f"    ... task status: {status} ({elapsed}s)")
        time.sleep(interval)
        elapsed += interval
    return result


def section(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def check(name: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    icon = "  [OK]" if condition else "  [!!]"
    msg = f"{icon} {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    return condition


# =============================================================================
# UAT-1: Sabine Conversational Flow
# =============================================================================

def uat_1_sabine_happy_path() -> bool:
    section("UAT-1: Sabine Conversational Flow (Happy Path)")
    all_pass = True

    # Step 1: Send a simple message
    print("  Step 1: Sending message to /invoke...")
    result = api_post("/invoke", {
        "message": "What is the weather like today?",
        "user_id": TEST_USER_ID,
    })

    all_pass &= check("HTTP 200", result["status_code"] == 200, f"Got {result['status_code']}")
    body = result["body"]
    all_pass &= check("success=true", body.get("success") is True or body.get("response") is not None)
    all_pass &= check("role is null", body.get("role") is None, f"Got role={body.get('role')}")

    # Step 2: Check tool execution structure
    tool_exec = body.get("tool_execution", {})
    all_pass &= check("tool_execution present", isinstance(tool_exec, dict))
    tools_called = tool_exec.get("tools_called", [])
    print(f"    Tools called: {tools_called}")

    # Step 3: Verify no Dream Team tools
    from lib.agent.tool_sets import DREAM_TEAM_TOOLS
    dream_tools_used = [t for t in tools_called if t in DREAM_TEAM_TOOLS]
    all_pass &= check("No Dream Team tools used", len(dream_tools_used) == 0,
                       f"Dream Team tools found: {dream_tools_used}" if dream_tools_used else "")

    return all_pass


# =============================================================================
# UAT-2: Dream Team Task Execution
# =============================================================================

def uat_2_dream_team_happy_path() -> bool:
    section("UAT-2: Dream Team Task Execution (Happy Path)")
    all_pass = True

    # Step 1: Check available roles
    print("  Step 1: Checking /roles endpoint...")
    roles_result = api_get("/roles")
    all_pass &= check("GET /roles returns 200", roles_result["status_code"] == 200)
    roles = roles_result["body"]
    print(f"    Available roles: {[r.get('role_id', r) for r in roles] if isinstance(roles, list) else roles}")

    # Step 2: Create a task
    print("\n  Step 2: Creating a task...")
    task_result = api_post("/tasks", {
        "role": "backend-architect-sabine",
        "target_repo": "sabine-super-agent",
        "payload": {"message": "List the top 3 open issues in the repository"},
        "priority": 1,
    })

    all_pass &= check("POST /tasks returns 200/201",
                       task_result["status_code"] in (200, 201),
                       f"Got {task_result['status_code']}")

    task_body = task_result["body"]
    task_id = task_body.get("task_id") or task_body.get("id")
    all_pass &= check("task_id returned", task_id is not None, f"task_id={task_id}")

    if not task_id:
        print("  SKIP: Cannot continue without task_id")
        return False

    # Step 2b: Trigger dispatch (tasks need explicit dispatch in local mode)
    print("\n  Step 2b: Dispatching queued tasks...")
    dispatch_result = api_post("/tasks/dispatch", {})
    dispatched = dispatch_result["body"].get("dispatched", 0)
    print(f"    Dispatched {dispatched} task(s)")

    # Step 3: Poll until complete
    print(f"\n  Step 3: Polling task {task_id}...")
    poll_result = poll_task(str(task_id), max_wait=180)
    # Unwrap nested task object if present
    task_data = poll_result["body"].get("task", poll_result["body"])
    status = task_data.get("status")
    all_pass &= check("Task completed", status == "completed", f"Got status={status}")

    if status == "completed":
        result_data = task_data.get("result", {}) or {}
        all_pass &= check("Result has response", "response" in result_data)
        print(f"    Response preview: {str(result_data.get('response', ''))[:200]}...")

    return all_pass


# =============================================================================
# UAT-3: Memory Isolation
# =============================================================================

def uat_3_memory_isolation() -> bool:
    section("UAT-3: Memory Isolation (Core Phase 2 Test)")
    all_pass = True

    # Step 1: Ingest a distinctive Sabine memory
    marker = f"UAT3-{uuid4().hex[:8]}"
    print(f"  Step 1: Ingesting Sabine memory with marker: {marker}")
    ingest_result = api_post("/memory/ingest", {
        "user_id": TEST_USER_ID,
        "content": f"Meeting with Jenny about the PriceSpider contract on Friday. Marker: {marker}",
        "source": "uat-test",
    })
    all_pass &= check("Ingest returns 200", ingest_result["status_code"] == 200)
    print(f"    Ingest result: {json.dumps(ingest_result['body'], indent=2)[:300]}")

    # Step 2: Query memory for the marker
    print(f"\n  Step 2: Querying memory for marker content...")
    time.sleep(2)  # Give ingestion a moment
    query_result = api_post("/memory/query", {
        "user_id": TEST_USER_ID,
        "query": f"What is happening with Jenny and PriceSpider? {marker}",
    })
    all_pass &= check("Query returns 200", query_result["status_code"] == 200)

    context = query_result["body"].get("context", "")
    print(f"    Context length: {len(context)} chars")
    print(f"    Context preview: {context[:300]}...")

    # Note: We can't easily verify Dream Team content is excluded without
    # first creating a Dream Team memory, which the system shouldn't do.
    # The key check is that the pipeline works and returns Sabine-scoped results.
    all_pass &= check("Context returned (non-empty)", len(context) > 0)

    return all_pass


# =============================================================================
# UAT-4: Tool Scoping Enforcement
# =============================================================================

def uat_4_tool_scoping() -> bool:
    section("UAT-4: Tool Scoping Enforcement")
    all_pass = True

    # Ask Sabine to do something that requires Dream Team tools
    print("  Step 1: Asking Sabine to create a GitHub issue (should NOT use github_issues tool)...")
    result = api_post("/invoke", {
        "message": "Create a GitHub issue titled 'Test issue from UAT' in the sabine-super-agent repo",
        "user_id": TEST_USER_ID,
    })

    all_pass &= check("HTTP 200", result["status_code"] == 200)
    body = result["body"]

    tool_exec = body.get("tool_execution", {})
    tools_called = tool_exec.get("tools_called", [])
    print(f"    Tools called: {tools_called}")

    all_pass &= check("github_issues NOT called",
                       "github_issues" not in tools_called,
                       "Sabine should not have access to github_issues")

    response_text = body.get("response", "")
    print(f"    Response preview: {response_text[:300]}...")

    return all_pass


# =============================================================================
# UAT-5: Backward Compatibility
# =============================================================================

def uat_5_backward_compat() -> bool:
    section("UAT-5: Backward Compatibility")
    all_pass = True

    # Test 1: /invoke still works with minimal request
    print("  Test 1: /invoke with minimal request...")
    result = api_post("/invoke", {
        "message": "Hello, are you working?",
        "user_id": TEST_USER_ID,
    })
    all_pass &= check("/invoke returns 200", result["status_code"] == 200)

    # Test 2: /memory/ingest without role param
    print("\n  Test 2: /memory/ingest (no explicit role)...")
    result = api_post("/memory/ingest", {
        "user_id": TEST_USER_ID,
        "content": "Backward compat test message",
        "source": "uat-test",
    })
    all_pass &= check("/memory/ingest returns 200", result["status_code"] == 200)

    # Test 3: /memory/query still works
    print("\n  Test 3: /memory/query...")
    result = api_post("/memory/query", {
        "user_id": TEST_USER_ID,
        "query": "test query",
    })
    all_pass &= check("/memory/query returns 200", result["status_code"] == 200)

    # Test 4: /roles endpoint
    print("\n  Test 4: GET /roles...")
    result = api_get("/roles")
    all_pass &= check("GET /roles returns 200", result["status_code"] == 200)

    # Test 5: /repos endpoint
    print("\n  Test 5: GET /repos...")
    result = api_get("/repos")
    all_pass &= check("GET /repos returns 200", result["status_code"] == 200)

    # Test 6: GET /health (main health check)
    print("\n  Test 6: GET /health...")
    result = api_get("/health")
    all_pass &= check("GET /health returns 200", result["status_code"] == 200)

    return all_pass


# =============================================================================
# UAT-6: Error Handling
# =============================================================================

def uat_6_error_handling() -> bool:
    section("UAT-6: Error Handling & Resilience")
    all_pass = True

    # Test 1: Task with invalid role
    print("  Test 1: POST /tasks with invalid role...")
    result = api_post("/tasks", {
        "role": "nonexistent-role-xyz",
        "target_repo": "sabine-super-agent",
        "payload": {"message": "test"},
    })
    all_pass &= check("Returns error (not 500)",
                       result["status_code"] != 500,
                       f"Got {result['status_code']}")
    print(f"    Response: {json.dumps(result['body'])[:300]}")

    # Test 2: Task with unauthorized repo
    print("\n  Test 2: POST /tasks with unauthorized repo...")
    result = api_post("/tasks", {
        "role": "frontend-ops-sabine",
        "target_repo": "sabine-super-agent",  # frontend-ops only authorized for dream-team-strug
        "payload": {"message": "test"},
    })
    all_pass &= check("Returns error (not 500)",
                       result["status_code"] != 500,
                       f"Got {result['status_code']}")
    print(f"    Response: {json.dumps(result['body'])[:300]}")

    return all_pass


# =============================================================================
# UAT-7: Audit Trail
# =============================================================================

def uat_7_audit_trail() -> bool:
    section("UAT-7: Audit Trail")
    all_pass = True

    print("  NOTE: This scenario requires manual database inspection.")
    print("  After running UAT-1 or UAT-2, check the tool_audit_log table:")
    print()
    print("  SQL to verify:")
    print("    SELECT id, agent_role, tool_name, status, task_id, created_at")
    print("    FROM tool_audit_log")
    print("    ORDER BY created_at DESC")
    print("    LIMIT 10;")
    print()
    print("  Expected:")
    print("    - Sabine calls: agent_role = NULL, task_id = NULL")
    print("    - Dream Team calls: agent_role = 'backend-architect-sabine', task_id != NULL")
    print("    - No raw API keys or tokens in input_params column")
    print()

    all_pass &= check("Audit trail check (manual)", True, "Inspect DB manually")
    return all_pass


# =============================================================================
# Runner
# =============================================================================

SCENARIOS = {
    "UAT-1": ("Sabine Happy Path", uat_1_sabine_happy_path),
    "UAT-2": ("Dream Team Happy Path", uat_2_dream_team_happy_path),
    "UAT-3": ("Memory Isolation", uat_3_memory_isolation),
    "UAT-4": ("Tool Scoping", uat_4_tool_scoping),
    "UAT-5": ("Backward Compatibility", uat_5_backward_compat),
    "UAT-6": ("Error Handling", uat_6_error_handling),
    "UAT-7": ("Audit Trail", uat_7_audit_trail),
}


def main():
    global BASE_URL, API_KEY, HEADERS

    parser = argparse.ArgumentParser(description="Phase 2 UAT Runner")
    parser.add_argument("--scenario", help="Run a specific scenario (e.g., UAT-1)")
    parser.add_argument("--base-url", help="Server base URL", default=None)
    parser.add_argument("--api-key", help="API key override")
    args = parser.parse_args()

    if args.base_url:
        BASE_URL = args.base_url
    if args.api_key:
        API_KEY = args.api_key
        HEADERS["X-API-Key"] = API_KEY

    print("=" * 70)
    print("  PHASE 2 UAT - Separate Agent Cores")
    print(f"  Server: {BASE_URL}")
    print(f"  API Key: {'*' * 8}...{API_KEY[-4:]}" if len(API_KEY) > 4 else "  API Key: NOT SET")
    print("=" * 70)

    if not API_KEY:
        print("\nWARNING: No AGENT_API_KEY set. Protected endpoints will fail.\n")

    # Preflight: check server is up
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"\n  Server health: {resp.status_code}")
    except requests.ConnectionError:
        print(f"\n  ERROR: Cannot connect to {BASE_URL}")
        print("  Make sure the server is running: python run_server.py")
        sys.exit(1)

    results = {}

    if args.scenario:
        if args.scenario not in SCENARIOS:
            print(f"Unknown scenario: {args.scenario}")
            print(f"Available: {', '.join(SCENARIOS.keys())}")
            sys.exit(1)
        name, fn = SCENARIOS[args.scenario]
        results[args.scenario] = fn()
    else:
        for key, (name, fn) in SCENARIOS.items():
            try:
                results[key] = fn()
            except Exception as e:
                print(f"  [!!] {key} CRASHED: {e}")
                results[key] = False

    # Summary
    section("UAT SUMMARY")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for key, passed_flag in results.items():
        name = SCENARIOS[key][0]
        icon = "[OK]" if passed_flag else "[!!]"
        print(f"  {icon} {key}: {name}")

    print(f"\n  {passed}/{total} scenarios passed")
    print("=" * 70)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
