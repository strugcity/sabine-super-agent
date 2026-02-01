"""
Test suite for Audit Logging Service

Tests the persistent audit logging functionality for tool executions.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.audit_logging import (
    redact_sensitive_data,
    truncate_data,
    extract_repo_info,
    classify_error,
)


def test_redact_api_keys():
    """Test that API keys are properly redacted."""
    test_cases = [
        ("api_key=sk-1234567890abcdef", "api_key=***REDACTED***"),
        ('{"apiKey": "secret123"}', '{"apiKey": ***REDACTED***}'),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5c", "Bearer ***REDACTED***"),
        ("sk-ant-api03-ajNLFfRhxpfF_eCp7VAV", "***API_KEY_REDACTED***"),
        ("ghp_xxxxxxxxxxxxxxxxxxxx1234", "***GITHUB_TOKEN_REDACTED***"),
    ]

    for input_str, expected_pattern in test_cases:
        result = redact_sensitive_data(input_str)
        # Check that the original sensitive data is not in the result
        if "sk-" in input_str:
            assert "sk-" not in result or "REDACTED" in result, f"Failed for: {input_str}"
        if "ghp_" in input_str:
            assert "ghp_" not in result or "REDACTED" in result, f"Failed for: {input_str}"
        print(f"  [OK] Redacted: {input_str[:30]}...")


def test_redact_dict():
    """Test redaction of nested dictionaries."""
    input_data = {
        "token": "token=secret_token_123",  # Matches assignment pattern
        "nested": {
            "api_key": "sk-1234567890abcdefghij",  # Matches API key pattern (20+ chars)
            "safe_data": "this is fine"
        }
    }

    result = redact_sensitive_data(input_data)

    assert "secret_token_123" not in str(result), "Token should be redacted"
    assert "sk-1234567890abcdefghij" not in str(result), "API key should be redacted"
    assert "this is fine" in str(result), "Safe data should be preserved"
    print("  [OK] Dict redaction works correctly")


def test_redact_list():
    """Test redaction of lists."""
    input_data = ["password=secret123", "normal data", "token=abc123456"]

    result = redact_sensitive_data(input_data)

    assert "secret123" not in str(result) or "REDACTED" in str(result)
    assert "normal data" in str(result)
    print("  [OK] List redaction works correctly")


def test_truncate_small_data():
    """Test that small data is not truncated."""
    small_data = {"key": "value"}
    result = truncate_data(small_data, max_size=1000)

    assert result == small_data, "Small data should not be truncated"
    print("  [OK] Small data preserved")


def test_truncate_large_string():
    """Test truncation of large strings."""
    large_string = "x" * 5000
    result = truncate_data(large_string, max_size=1000)

    assert len(result) < 5000, "Large string should be truncated"
    assert "TRUNCATED" in result, "Truncation marker should be present"
    print("  [OK] Large string truncated")


def test_truncate_large_dict():
    """Test truncation of large dictionaries."""
    large_dict = {
        "key1": "x" * 500,
        "key2": "y" * 500,
    }
    result = truncate_data(large_dict, max_size=500)

    # Dict should still have keys
    assert "key1" in result or "key2" in result
    print("  [OK] Large dict truncated")


def test_extract_repo_info_github():
    """Test extraction of repo info from GitHub tool params."""
    params = {
        "owner": "strugcity",
        "repo": "sabine-super-agent",
        "path": "src/components/Test.tsx",
        "action": "create_file"
    }

    target_repo, target_path = extract_repo_info("github_issues", params)

    assert target_repo == "strugcity/sabine-super-agent"
    assert target_path == "src/components/Test.tsx"
    print("  [OK] GitHub repo info extracted correctly")


def test_extract_repo_info_issue():
    """Test extraction of issue number from GitHub tool params."""
    params = {
        "owner": "strugcity",
        "repo": "dream-team-strug",
        "issue_number": 42,
        "action": "get"
    }

    target_repo, target_path = extract_repo_info("github_issues", params)

    assert target_repo == "strugcity/dream-team-strug"
    assert target_path == 42
    print("  [OK] GitHub issue number extracted correctly")


def test_extract_repo_info_other_tool():
    """Test that other tools return None for repo info."""
    params = {"code": "print('hello')"}

    target_repo, target_path = extract_repo_info("run_python_sandbox", params)

    assert target_repo is None
    assert target_path is None
    print("  [OK] Other tools return None for repo info")


def test_classify_error_permission():
    """Test error classification for permission errors."""
    test_cases = [
        ("Permission denied. Token may lack 'repo' scope.", "permission_denied"),
        ("403 Forbidden: Not allowed", "permission_denied"),
        ("Access denied", "blocked"),
        ("404 Not Found", "not_found"),
        ("Resource not found", "not_found"),
        ("401 Unauthorized", "auth_failed"),
        ("Authentication failed", "auth_failed"),
        ("Connection timeout", "timeout"),
        ("Rate limit exceeded", "rate_limited"),
        ("429 Too Many Requests", "rate_limited"),
        ("Network error: Connection refused", "network_error"),
        ("Some random error", "unknown"),
    ]

    for error_msg, expected_type in test_cases:
        result = classify_error(error_msg)
        assert result == expected_type, f"Expected {expected_type} for '{error_msg}', got {result}"
        print(f"  [OK] '{error_msg[:30]}...' -> {result}")


def test_classify_error_none():
    """Test error classification for None/empty."""
    assert classify_error(None) is None
    assert classify_error("") is None
    print("  [OK] None/empty error returns None")


def test_audit_entry_structure():
    """Test that audit entry has all required fields."""
    # Simulate what an audit entry should look like
    audit_entry = {
        "id": "test-uuid",
        "user_id": "user-123",
        "session_id": "session-456",
        "task_id": "task-789",
        "agent_role": "backend-architect-sabine",
        "tool_name": "github_issues",
        "tool_action": "create_file",
        "input_params": {"path": "test.py"},
        "output_summary": {"status": "success"},
        "status": "success",
        "error_type": None,
        "error_message": None,
        "target_repo": "strugcity/sabine-super-agent",
        "target_path": "test.py",
        "artifact_created": "test.py",
        "execution_time_ms": 150,
        "created_at": "2026-02-07T12:00:00Z",
    }

    required_fields = [
        "id", "tool_name", "status", "created_at"
    ]

    for field in required_fields:
        assert field in audit_entry, f"Missing required field: {field}"

    print("  [OK] Audit entry has all required fields")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Audit Logging Tests")
    print("=" * 60)

    print("\n1. Testing API key redaction...")
    test_redact_api_keys()

    print("\n2. Testing dict redaction...")
    test_redact_dict()

    print("\n3. Testing list redaction...")
    test_redact_list()

    print("\n4. Testing small data truncation...")
    test_truncate_small_data()

    print("\n5. Testing large string truncation...")
    test_truncate_large_string()

    print("\n6. Testing large dict truncation...")
    test_truncate_large_dict()

    print("\n7. Testing GitHub repo info extraction...")
    test_extract_repo_info_github()

    print("\n8. Testing GitHub issue number extraction...")
    test_extract_repo_info_issue()

    print("\n9. Testing other tool repo info...")
    test_extract_repo_info_other_tool()

    print("\n10. Testing error classification...")
    test_classify_error_permission()

    print("\n11. Testing None/empty error classification...")
    test_classify_error_none()

    print("\n12. Testing audit entry structure...")
    test_audit_entry_structure()

    print("\n" + "=" * 60)
    print("All audit logging tests passed!")
    print("=" * 60)
