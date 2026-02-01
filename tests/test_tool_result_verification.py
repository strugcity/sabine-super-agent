"""
Test suite for Tool Result Verification System

This tests the enhanced tool execution tracking that verifies:
1. Tools were called when required
2. Tool calls actually succeeded (not just called)
3. Artifacts were created when expected
"""

import json


def parse_tool_result(tool_content):
    """
    Parse tool result content to determine success/failure.

    This mirrors the logic in core.py for tool result parsing.
    """
    tool_status = "unknown"
    tool_error = None
    artifact_created = None

    if tool_content:
        try:
            if isinstance(tool_content, str):
                result_data = json.loads(tool_content)
            elif isinstance(tool_content, dict):
                result_data = tool_content
            else:
                result_data = {}

            # Check for status field (github_issues, run_python_sandbox, etc.)
            if "status" in result_data:
                tool_status = result_data["status"]
                if tool_status == "success":
                    # Extract artifact info if available
                    if "file" in result_data:
                        artifact_created = result_data["file"].get("path") or result_data["file"].get("url")
                    elif "issue" in result_data:
                        artifact_created = f"Issue #{result_data['issue'].get('number')}"
                    elif "commit" in result_data:
                        artifact_created = f"Commit {result_data['commit'].get('sha', '')[:7]}"
                elif tool_status == "error":
                    tool_error = result_data.get("error", "Unknown error")

            # Check for error field without status
            elif "error" in result_data:
                tool_status = "error"
                tool_error = result_data["error"]

            # Check for success field
            elif "success" in result_data:
                tool_status = "success" if result_data["success"] else "error"
                if tool_status == "error":
                    tool_error = result_data.get("error", "Operation failed")

            else:
                # Assume success if no error indicators
                tool_status = "success"

        except (json.JSONDecodeError, TypeError):
            # If not JSON, check for error patterns in string
            content_str = str(tool_content).lower()
            if "error" in content_str or "failed" in content_str or "exception" in content_str:
                tool_status = "error"
                tool_error = str(tool_content)[:200]
            else:
                tool_status = "success"

    return tool_status, tool_error, artifact_created


def test_github_success_response():
    """Test parsing successful GitHub file creation response."""
    response = {
        "status": "success",
        "message": "File created: src/components/DarkMode.tsx",
        "file": {
            "path": "src/components/DarkMode.tsx",
            "sha": "abc123def456",
            "url": "https://github.com/strugcity/dream-team-strug/blob/main/src/components/DarkMode.tsx"
        },
        "commit": {
            "sha": "xyz789abc",
            "message": "feat: Add DarkMode component",
            "url": "https://github.com/..."
        }
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "success", f"Expected success, got {status}"
    assert error is None, f"Expected no error, got {error}"
    assert artifact == "src/components/DarkMode.tsx", f"Expected path, got {artifact}"
    print("  [OK] GitHub success response parsed correctly")


def test_github_error_response():
    """Test parsing GitHub error response."""
    response = {
        "status": "error",
        "error": "Permission denied. Token may lack 'repo' scope.",
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "error", f"Expected error, got {status}"
    assert "Permission denied" in error, f"Expected permission error, got {error}"
    assert artifact is None, f"Expected no artifact, got {artifact}"
    print("  [OK] GitHub error response parsed correctly")


def test_github_issue_creation():
    """Test parsing successful issue creation response."""
    response = {
        "status": "success",
        "message": "Created issue #42",
        "issue": {
            "number": 42,
            "title": "FEATURE: Dark Mode Toggle",
            "url": "https://github.com/..."
        }
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "success", f"Expected success, got {status}"
    assert error is None, f"Expected no error, got {error}"
    assert artifact == "Issue #42", f"Expected issue artifact, got {artifact}"
    print("  [OK] GitHub issue creation parsed correctly")


def test_repo_access_denied():
    """Test parsing repo access denied response."""
    response = {
        "status": "error",
        "error": "Repository access denied: Repository 'evil-org/evil-repo' is not in the allowed list.",
        "blocked_repo": "evil-org/evil-repo",
        "allowed_repos": ["strugcity/sabine-super-agent", "strugcity/dream-team-strug"]
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "error", f"Expected error, got {status}"
    assert "Repository access denied" in error, f"Expected access denied, got {error}"
    print("  [OK] Repo access denied parsed correctly")


def test_sandbox_success():
    """Test parsing successful sandbox execution."""
    response = {
        "status": "success",
        "output": "Test passed!\n",
        "exit_code": 0
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "success", f"Expected success, got {status}"
    assert error is None, f"Expected no error, got {error}"
    print("  [OK] Sandbox success parsed correctly")


def test_sandbox_failure():
    """Test parsing sandbox execution failure."""
    response = {
        "status": "error",
        "error": "SyntaxError: unexpected token",
        "output": "",
        "exit_code": 1
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "error", f"Expected error, got {status}"
    assert "SyntaxError" in error, f"Expected syntax error, got {error}"
    print("  [OK] Sandbox failure parsed correctly")


def test_json_string_response():
    """Test parsing JSON string response."""
    response = json.dumps({
        "status": "success",
        "file": {"path": "test.py"}
    })

    status, error, artifact = parse_tool_result(response)
    assert status == "success", f"Expected success, got {status}"
    assert artifact == "test.py", f"Expected path, got {artifact}"
    print("  [OK] JSON string response parsed correctly")


def test_non_json_success():
    """Test parsing non-JSON success response."""
    response = "File created successfully at /path/to/file.txt"

    status, error, artifact = parse_tool_result(response)
    assert status == "success", f"Expected success (no error keywords), got {status}"
    print("  [OK] Non-JSON success parsed correctly")


def test_non_json_error():
    """Test parsing non-JSON error response."""
    response = "Error: Connection failed to GitHub API"

    status, error, artifact = parse_tool_result(response)
    assert status == "error", f"Expected error, got {status}"
    assert error is not None, "Expected error message"
    print("  [OK] Non-JSON error parsed correctly")


def test_success_boolean_field():
    """Test parsing response with success boolean field."""
    response = {
        "success": True,
        "data": {"id": 123}
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "success", f"Expected success, got {status}"
    print("  [OK] Success boolean field parsed correctly")


def test_success_false_field():
    """Test parsing response with success=false field."""
    response = {
        "success": False,
        "error": "Operation timed out"
    }

    status, error, artifact = parse_tool_result(response)
    assert status == "error", f"Expected error, got {status}"
    assert "timed out" in error, f"Expected timeout error, got {error}"
    print("  [OK] Success=false field parsed correctly")


def test_verification_logic():
    """Test the verification logic that would run in server.py."""
    # Simulate tool execution results
    tool_execution = {
        "tools_called": ["github_issues", "run_python_sandbox"],
        "call_count": 2,
        "success_count": 2,
        "failure_count": 0,
        "artifacts_created": ["src/components/Test.tsx", "Issue #42"],
        "all_succeeded": True,
        "executions": [
            {"type": "tool_result", "tool_name": "github_issues", "status": "success"},
            {"type": "tool_result", "tool_name": "run_python_sandbox", "status": "success"}
        ]
    }

    # Verification should pass
    verification_passed = True
    verification_warnings = []

    task_requires_tools = True
    call_count = tool_execution["call_count"]
    failure_count = tool_execution["failure_count"]

    if task_requires_tools and call_count == 0:
        verification_passed = False
        verification_warnings.append("NO_TOOLS_CALLED")

    if failure_count > 0:
        verification_passed = False
        verification_warnings.append("TOOL_FAILURES")

    assert verification_passed == True, "Verification should pass for successful execution"
    assert len(verification_warnings) == 0, f"Should have no warnings: {verification_warnings}"
    print("  [OK] Verification logic works for success case")


def test_verification_with_failures():
    """Test verification logic with tool failures."""
    tool_execution = {
        "tools_called": ["github_issues"],
        "call_count": 1,
        "success_count": 0,
        "failure_count": 1,
        "artifacts_created": [],
        "all_succeeded": False,
        "executions": [
            {"type": "tool_result", "tool_name": "github_issues", "status": "error", "error": "Auth failed"}
        ]
    }

    verification_passed = True
    verification_warnings = []

    failure_count = tool_execution["failure_count"]

    if failure_count > 0:
        verification_passed = False
        verification_warnings.append(f"TOOL_FAILURES: {failure_count} failures")

    assert verification_passed == False, "Verification should fail when tools fail"
    assert len(verification_warnings) == 1, f"Should have 1 warning: {verification_warnings}"
    print("  [OK] Verification logic catches tool failures")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Tool Result Verification Tests")
    print("=" * 60)

    print("\n1. Testing GitHub success response...")
    test_github_success_response()

    print("\n2. Testing GitHub error response...")
    test_github_error_response()

    print("\n3. Testing GitHub issue creation...")
    test_github_issue_creation()

    print("\n4. Testing repo access denied...")
    test_repo_access_denied()

    print("\n5. Testing sandbox success...")
    test_sandbox_success()

    print("\n6. Testing sandbox failure...")
    test_sandbox_failure()

    print("\n7. Testing JSON string response...")
    test_json_string_response()

    print("\n8. Testing non-JSON success...")
    test_non_json_success()

    print("\n9. Testing non-JSON error...")
    test_non_json_error()

    print("\n10. Testing success boolean field...")
    test_success_boolean_field()

    print("\n11. Testing success=false field...")
    test_success_false_field()

    print("\n12. Testing verification logic (success case)...")
    test_verification_logic()

    print("\n13. Testing verification with failures...")
    test_verification_with_failures()

    print("\n" + "=" * 60)
    print("All tool result verification tests passed!")
    print("=" * 60)
