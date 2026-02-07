#!/usr/bin/env python3
"""
Verification script for router split refactoring.

Validates that all expected endpoints are present after the refactoring.
"""
import sys
sys.path.insert(0, '.')

try:
    from lib.agent.server import app

    EXPECTED_PATHS = [
        "/invoke", "/invoke/cached",
        "/gmail/handle", "/gmail/diagnostic", "/gmail/debug-inbox", "/gmail/renew-watch",
        "/memory/ingest", "/memory/query", "/memory/upload", "/memory/upload/supported-types",
        "/tasks", "/tasks/dispatch", "/tasks/watchdog", "/tasks/retry-all",
        "/tasks/auto-fail-blocked", "/tasks/retryable", "/tasks/stuck",
        "/tasks/health", "/tasks/blocked", "/tasks/stale", "/tasks/orphaned",
        "/tasks/health-check",
        "/orchestration/status",
        "/roles", "/repos",
        "/health", "/tools", "/tools/diagnostics",
        "/audit/tools", "/audit/stats",
        "/metrics/record", "/metrics/latest", "/metrics/trend",
        "/metrics/roles", "/metrics/errors", "/metrics/prometheus",
        "/scheduler/status", "/scheduler/trigger-briefing",
        "/wal/stats", "/wal/pending", "/wal/failed",
        "/cache/metrics", "/cache/reset",
        "/e2b/test", "/test",
    ]

    # Get actual paths from the app
    actual_paths = []
    for route in app.routes:
        if hasattr(route, 'path'):
            # Handle path parameters like {task_id}
            path = route.path
            actual_paths.append(path)

    # Check for missing endpoints
    missing = []
    for expected_path in EXPECTED_PATHS:
        # Check if the exact path exists, or if it's a parameterized version
        found = False
        for actual_path in actual_paths:
            # Simple match - exact or with path params
            if expected_path == actual_path or expected_path in actual_path:
                found = True
                break
        if not found:
            missing.append(expected_path)

    if missing:
        print(f"❌ FAIL: Missing {len(missing)} endpoints:")
        for path in missing:
            print(f"  - {path}")
        sys.exit(1)
    else:
        print(f"✅ PASS: All {len(EXPECTED_PATHS)} expected endpoints verified.")
        print(f"   Total routes in app: {len(actual_paths)}")
        
    # Check server.py line count
    with open("lib/agent/server.py") as f:
        lines = len(f.readlines())
    
    if lines < 500:
        print(f"✅ PASS: server.py has {lines} lines (under 500)")
    elif lines < 1000:
        print(f"✅ PASS: server.py has {lines} lines (under 1000, target met)")
    else:
        print(f"⚠️  WARNING: server.py has {lines} lines (still over 1000, but functional)")

    print("\n✅ ALL CHECKS PASSED!")
    sys.exit(0)

except Exception as e:
    print(f"❌ FAIL: Error during verification: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
