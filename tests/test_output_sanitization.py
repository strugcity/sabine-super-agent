"""
Test suite for Output Sanitization

Tests the output sanitization module including:
1. Sensitive data redaction (API keys, tokens, passwords)
2. PII protection (emails, phones, SSNs)
3. Path sanitization
4. Error message cleaning
5. Field filtering
6. Response truncation
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.output_sanitization import (
    redact_sensitive_strings,
    sanitize_path,
    sanitize_error_message,
    filter_internal_fields,
    redact_sensitive_fields,
    escape_html,
    truncate_response,
    sanitize_api_response,
    sanitize_agent_output,
    sanitize_tool_output,
    sanitize_for_logging,
)


# =============================================================================
# API Key Redaction Tests
# =============================================================================

def test_redact_anthropic_key():
    """Test that Anthropic API keys are redacted."""
    text = "Using key sk-ant-api03-abcdefghijklmnop123456"
    result = redact_sensitive_strings(text)

    assert "sk-ant-api03" not in result
    assert "***ANTHROPIC_KEY***" in result
    print("  [OK] Anthropic API key redacted")


def test_redact_openai_key():
    """Test that OpenAI API keys are redacted."""
    text = "My API key is sk-proj-abcdefghijklmnopqrstuvwxyz"
    result = redact_sensitive_strings(text)

    assert "sk-proj-abcdefghijklmnopqrstuvwxyz" not in result
    assert "***OPENAI_KEY***" in result
    print("  [OK] OpenAI API key redacted")


def test_redact_github_token():
    """Test that GitHub tokens are redacted."""
    test_cases = [
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "gho_abcdefghijklmnopqrstuvwxyz1234567890",
        "github_pat_abcdefghijklmnopqrstuvwxyz123",
    ]

    for token in test_cases:
        # Test with token embedded in text
        result = redact_sensitive_strings(f"Using {token} for auth")
        assert token not in result, f"Token {token[:10]}... should be redacted"
        # Check that some form of redaction marker is present
        assert "***" in result, f"Redaction marker should be present for {token[:10]}..."

    print("  [OK] GitHub tokens redacted")


def test_redact_slack_token():
    """Test that Slack tokens are redacted."""
    text = "Slack bot token: xoxb-123456-789012-abcdefghijklmn"
    result = redact_sensitive_strings(text)

    assert "xoxb-" not in result or "***SLACK_TOKEN***" in result
    print("  [OK] Slack token redacted")


def test_redact_jwt():
    """Test that JWTs are redacted."""
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4iLCJpYXQiOjE1MTYyMzkwMjJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    result = redact_sensitive_strings(f"Bearer {jwt}")

    assert "eyJhbGciOi" not in result
    assert "***JWT" in result
    print("  [OK] JWT redacted")


def test_redact_connection_string():
    """Test that connection strings are redacted."""
    test_cases = [
        "postgres://user:password@localhost:5432/db",
        "mysql://root:secret@127.0.0.1/mydb",
        "mongodb://admin:p4ssw0rd@cluster.mongodb.net/app",
        "redis://default:redis123@redis.server.com:6379",
    ]

    for conn_str in test_cases:
        result = redact_sensitive_strings(conn_str)
        assert "password" not in result and "secret" not in result and "p4ssw0rd" not in result
        assert "***CONNECTION_STRING***" in result

    print("  [OK] Connection strings redacted")


def test_redact_aws_key():
    """Test that AWS keys are redacted."""
    text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    result = redact_sensitive_strings(text)

    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "***AWS_ACCESS_KEY***" in result
    print("  [OK] AWS access key redacted")


def test_redact_assignment_pattern():
    """Test that key=value patterns are redacted."""
    test_cases = [
        ('api_key="sk123456789012345"', "api_key=***REDACTED***"),
        ("token='mySecretToken123'", "token=***REDACTED***"),
        ("password=supersecret123", "password=***REDACTED***"),
        ("secret: verysecretvalue", "secret=***REDACTED***"),
    ]

    for text, _ in test_cases:
        result = redact_sensitive_strings(text)
        # Check that the secret value is not in the result
        assert "sk123456789012345" not in result or "REDACTED" in result
        assert "mySecretToken123" not in result or "REDACTED" in result
        assert "supersecret123" not in result or "REDACTED" in result

    print("  [OK] Assignment patterns redacted")


# =============================================================================
# PII Redaction Tests
# =============================================================================

def test_redact_email():
    """Test that email addresses are redacted when PII mode is enabled."""
    text = "Contact me at john.doe@example.com for more info"

    # Without PII redaction
    result_no_pii = redact_sensitive_strings(text, include_pii=False)
    assert "john.doe@example.com" in result_no_pii

    # With PII redaction
    result_pii = redact_sensitive_strings(text, include_pii=True)
    assert "john.doe@example.com" not in result_pii
    assert "***EMAIL***" in result_pii

    print("  [OK] Email addresses redacted (PII mode)")


def test_redact_phone():
    """Test that phone numbers are redacted when PII mode is enabled."""
    test_cases = [
        "Call me at 555-123-4567",
        "Phone: (555) 123-4567",
        "Contact: +1-555-123-4567",
    ]

    for text in test_cases:
        result = redact_sensitive_strings(text, include_pii=True)
        assert "555" not in result or "***PHONE***" in result

    print("  [OK] Phone numbers redacted (PII mode)")


def test_redact_ssn():
    """Test that SSNs are redacted when PII mode is enabled."""
    text = "SSN: 123-45-6789"
    result = redact_sensitive_strings(text, include_pii=True)

    assert "123-45-6789" not in result
    assert "***SSN***" in result
    print("  [OK] SSN redacted (PII mode)")


# =============================================================================
# Path Sanitization Tests
# =============================================================================

def test_sanitize_windows_path():
    """Test that Windows paths are sanitized."""
    text = r"Error in C:\Users\admin\Documents\secrets\config.py line 42"
    result = sanitize_path(text)

    assert r"C:\Users\admin" not in result
    assert "***PATH***" in result
    print("  [OK] Windows paths sanitized")


def test_sanitize_unix_path():
    """Test that Unix paths are sanitized."""
    text = "File /home/user/projects/secret/app.py not found"
    result = sanitize_path(text)

    assert "/home/user" not in result
    assert "***PATH***" in result
    print("  [OK] Unix paths sanitized")


def test_sanitize_traceback_paths():
    """Test that Python traceback file paths are sanitized."""
    traceback = '''Traceback (most recent call last):
  File "/home/user/project/app.py", line 42, in main
    raise ValueError("test")
ValueError: test'''

    result = sanitize_path(traceback)
    assert "/home/user/project/app.py" not in result
    print("  [OK] Traceback paths sanitized")


# =============================================================================
# Error Message Sanitization Tests
# =============================================================================

def test_sanitize_error_with_path():
    """Test that error messages with paths are sanitized."""
    error = "FileNotFoundError: /home/admin/secret/config.json not found"
    result = sanitize_error_message(error)

    assert "/home/admin" not in result
    print("  [OK] Error message paths sanitized")


def test_sanitize_error_with_credentials():
    """Test that error messages with credentials are sanitized."""
    error = "ConnectionError: Failed to connect with token=secret123abc"
    result = sanitize_error_message(error)

    assert "secret123abc" not in result or "REDACTED" in result
    print("  [OK] Error message credentials sanitized")


def test_sanitize_error_truncation():
    """Test that long error messages are truncated."""
    error = "Error: " + "x" * 1000
    result = sanitize_error_message(error, max_length=100)

    assert len(result) <= 100
    assert "..." in result
    print("  [OK] Error messages truncated")


def test_sanitize_exception_object():
    """Test that exception objects can be sanitized."""
    exc = ValueError("Invalid token: sk-ant-api03-secret123")
    result = sanitize_error_message(exc)

    assert "sk-ant-api03-secret123" not in result
    print("  [OK] Exception objects sanitized")


# =============================================================================
# Field Filtering Tests
# =============================================================================

def test_filter_internal_fields():
    """Test that internal fields are removed."""
    data = {
        "response": "Hello",
        "_debug": {"internal": "data"},
        "_internal": True,
        "user_id": "123",
        "_trace": "stack trace here"
    }

    result = filter_internal_fields(data)

    assert "response" in result
    assert "user_id" in result
    assert "_debug" not in result
    assert "_internal" not in result
    assert "_trace" not in result
    print("  [OK] Internal fields filtered")


def test_filter_nested_internal_fields():
    """Test that nested internal fields are removed."""
    data = {
        "outer": {
            "data": "value",
            "_debug": "internal"
        }
    }

    result = filter_internal_fields(data)

    assert "data" in result["outer"]
    assert "_debug" not in result["outer"]
    print("  [OK] Nested internal fields filtered")


# =============================================================================
# Sensitive Field Redaction Tests
# =============================================================================

def test_redact_password_field():
    """Test that password fields are redacted by key name."""
    data = {"username": "admin", "password": "super_secret_123"}
    result = redact_sensitive_fields(data)

    assert result["username"] == "admin"
    assert result["password"] == "***REDACTED***"
    print("  [OK] Password field redacted")


def test_redact_api_key_field():
    """Test that api_key fields are redacted."""
    data = {
        "api_key": "sk-12345",
        "apiKey": "secret",
        "api-key": "hidden"
    }
    result = redact_sensitive_fields(data)

    for key in data:
        assert result[key] == "***REDACTED***"
    print("  [OK] API key fields redacted")


def test_redact_nested_sensitive_fields():
    """Test that nested sensitive fields are redacted."""
    data = {
        "config": {
            "auth": {
                "token": "bearer_xyz123",
                "public_key": "visible"
            }
        }
    }
    result = redact_sensitive_fields(data)

    assert result["config"]["auth"]["token"] == "***REDACTED***"
    # public_key doesn't match sensitive patterns
    print("  [OK] Nested sensitive fields redacted")


def test_redact_list_with_sensitive_data():
    """Test that lists with sensitive data are handled."""
    data = {
        "tokens": ["token1", "token2"],
        "messages": ["Hello", "My api_key=sk-12345678901234567890 is secret"]
    }
    result = redact_sensitive_fields(data)

    # The sensitive patterns in the strings should be redacted
    messages_str = str(result["messages"])
    assert "sk-12345678901234567890" not in messages_str, "API key in list should be redacted"
    print("  [OK] Lists with sensitive data handled")


# =============================================================================
# HTML Escaping Tests
# =============================================================================

def test_escape_html_basic():
    """Test basic HTML escaping."""
    text = "<script>alert('xss')</script>"
    result = escape_html(text)

    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    print("  [OK] HTML escaped")


def test_escape_html_quotes():
    """Test that quotes are escaped."""
    text = 'User said: "Hello & goodbye"'
    result = escape_html(text)

    assert "&amp;" in result
    assert "&quot;" in result
    print("  [OK] HTML quotes escaped")


# =============================================================================
# Response Truncation Tests
# =============================================================================

def test_truncate_small_response():
    """Test that small responses are not truncated."""
    data = {"key": "value"}
    result = truncate_response(data, max_size=1000)

    assert result == data
    print("  [OK] Small responses preserved")


def test_truncate_large_string():
    """Test truncation of large strings."""
    data = "x" * 10000
    result = truncate_response(data, max_size=100)

    assert len(result) <= 150  # Some buffer for truncation message
    assert "TRUNCATED" in result
    print("  [OK] Large strings truncated")


def test_truncate_large_dict():
    """Test truncation of large dictionaries."""
    data = {"key": "x" * 10000}
    result = truncate_response(data, max_size=500)

    assert "TRUNCATED" in str(result)
    print("  [OK] Large dicts truncated")


# =============================================================================
# High-Level Sanitization Tests
# =============================================================================

def test_sanitize_api_response_full():
    """Test comprehensive API response sanitization."""
    response = {
        "success": True,
        "data": {
            "api_key": "sk-secret-key-123",
            "message": "Your token is sk-ant-api03-xyz"
        },
        "_debug": "internal info",
        "error": None
    }

    result = sanitize_api_response(response)

    assert "_debug" not in result
    assert result["data"]["api_key"] == "***REDACTED***"
    assert "sk-ant-api03" not in str(result)
    print("  [OK] Full API response sanitized")


def test_sanitize_api_response_with_error():
    """Test API response sanitization with error message."""
    response = {
        "success": False,
        "error": "Connection failed: password=secret123 at /home/user/app.py"
    }

    result = sanitize_api_response(response)

    assert "secret123" not in result["error"]
    assert "/home/user" not in result["error"]
    print("  [OK] API response error sanitized")


def test_sanitize_agent_output():
    """Test agent output sanitization."""
    output = "Here's your API key: sk-ant-api03-secret and your file is at /home/user/config.json"

    result = sanitize_agent_output(output, redact_credentials=True)

    assert "sk-ant-api03-secret" not in result
    # Note: paths are not sanitized by default in agent output
    print("  [OK] Agent output sanitized")


def test_sanitize_agent_output_with_html():
    """Test agent output with HTML escaping."""
    output = "Result: <script>alert('xss')</script>"

    result = sanitize_agent_output(output, escape_for_html=True)

    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    print("  [OK] Agent output HTML escaped")


def test_sanitize_tool_output_github():
    """Test GitHub tool output sanitization."""
    output = {
        "status": "success",
        "token": "ghp_secret123456789012345678901234567890",
        "data": {"file": "created"}
    }

    result = sanitize_tool_output(output, "github_issues")

    assert "ghp_secret" not in str(result)
    print("  [OK] GitHub tool output sanitized")


def test_sanitize_tool_output_sandbox():
    """Test sandbox tool output sanitization."""
    output = {
        "status": "success",
        "output": "Loaded API key: sk-ant-api03-supersecret",
        "exit_code": 0
    }

    result = sanitize_tool_output(output, "run_python_sandbox")

    assert "sk-ant-api03-supersecret" not in str(result)
    print("  [OK] Sandbox tool output sanitized")


# =============================================================================
# Logging Sanitization Tests
# =============================================================================

def test_sanitize_for_logging():
    """Test sanitization for logging."""
    data = {
        "user": "admin",
        "password": "secret123",
        "path": "/home/admin/config.json",
        "api_key": "sk-ant-api03-key123"
    }

    result = sanitize_for_logging(data)

    assert "secret123" not in result
    assert "sk-ant-api03" not in result
    print("  [OK] Data sanitized for logging")


def test_sanitize_for_logging_truncation():
    """Test that logging output is truncated."""
    data = {"content": "x" * 5000}
    result = sanitize_for_logging(data, max_length=100)

    assert len(result) <= 120  # Some buffer
    print("  [OK] Logging output truncated")


def test_sanitize_for_logging_with_pii():
    """Test that PII is redacted in logs."""
    data = {
        "email": "user@example.com",
        "message": "Contact john@test.com for help"
    }

    result = sanitize_for_logging(data)

    assert "user@example.com" not in result
    assert "john@test.com" not in result
    print("  [OK] PII redacted in logs")


# =============================================================================
# Edge Case Tests
# =============================================================================

def test_sanitize_none_values():
    """Test that None values are handled gracefully."""
    assert redact_sensitive_strings(None) is None
    assert sanitize_path(None) is None
    assert sanitize_error_message(None) == ""
    assert filter_internal_fields(None) is None
    print("  [OK] None values handled")


def test_sanitize_empty_strings():
    """Test that empty strings are handled gracefully."""
    assert redact_sensitive_strings("") == ""
    assert sanitize_path("") == ""
    assert sanitize_error_message("") == ""
    print("  [OK] Empty strings handled")


def test_sanitize_preserves_safe_content():
    """Test that safe content is preserved."""
    safe_text = "Hello, this is a normal message with no secrets."
    result = redact_sensitive_strings(safe_text)

    assert result == safe_text
    print("  [OK] Safe content preserved")


def test_nested_redaction():
    """Test deeply nested data structure redaction."""
    data = {
        "level1": {
            "level2": {
                "level3": {
                    "password": "deep_secret",
                    "safe": "visible"
                }
            }
        }
    }

    result = redact_sensitive_fields(data)

    assert result["level1"]["level2"]["level3"]["password"] == "***REDACTED***"
    assert result["level1"]["level2"]["level3"]["safe"] == "visible"
    print("  [OK] Deeply nested redaction works")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Output Sanitization Tests")
    print("=" * 60)

    print("\n--- API Key Redaction Tests ---")

    print("\n1. Testing Anthropic API key redaction...")
    test_redact_anthropic_key()

    print("\n2. Testing OpenAI API key redaction...")
    test_redact_openai_key()

    print("\n3. Testing GitHub token redaction...")
    test_redact_github_token()

    print("\n4. Testing Slack token redaction...")
    test_redact_slack_token()

    print("\n5. Testing JWT redaction...")
    test_redact_jwt()

    print("\n6. Testing connection string redaction...")
    test_redact_connection_string()

    print("\n7. Testing AWS key redaction...")
    test_redact_aws_key()

    print("\n8. Testing assignment pattern redaction...")
    test_redact_assignment_pattern()

    print("\n--- PII Redaction Tests ---")

    print("\n9. Testing email redaction...")
    test_redact_email()

    print("\n10. Testing phone number redaction...")
    test_redact_phone()

    print("\n11. Testing SSN redaction...")
    test_redact_ssn()

    print("\n--- Path Sanitization Tests ---")

    print("\n12. Testing Windows path sanitization...")
    test_sanitize_windows_path()

    print("\n13. Testing Unix path sanitization...")
    test_sanitize_unix_path()

    print("\n14. Testing traceback path sanitization...")
    test_sanitize_traceback_paths()

    print("\n--- Error Message Tests ---")

    print("\n15. Testing error message path sanitization...")
    test_sanitize_error_with_path()

    print("\n16. Testing error message credential sanitization...")
    test_sanitize_error_with_credentials()

    print("\n17. Testing error message truncation...")
    test_sanitize_error_truncation()

    print("\n18. Testing exception object sanitization...")
    test_sanitize_exception_object()

    print("\n--- Field Filtering Tests ---")

    print("\n19. Testing internal field filtering...")
    test_filter_internal_fields()

    print("\n20. Testing nested internal field filtering...")
    test_filter_nested_internal_fields()

    print("\n--- Sensitive Field Tests ---")

    print("\n21. Testing password field redaction...")
    test_redact_password_field()

    print("\n22. Testing API key field redaction...")
    test_redact_api_key_field()

    print("\n23. Testing nested sensitive field redaction...")
    test_redact_nested_sensitive_fields()

    print("\n24. Testing list sensitive data handling...")
    test_redact_list_with_sensitive_data()

    print("\n--- HTML Escaping Tests ---")

    print("\n25. Testing basic HTML escaping...")
    test_escape_html_basic()

    print("\n26. Testing HTML quote escaping...")
    test_escape_html_quotes()

    print("\n--- Truncation Tests ---")

    print("\n27. Testing small response preservation...")
    test_truncate_small_response()

    print("\n28. Testing large string truncation...")
    test_truncate_large_string()

    print("\n29. Testing large dict truncation...")
    test_truncate_large_dict()

    print("\n--- High-Level Sanitization Tests ---")

    print("\n30. Testing full API response sanitization...")
    test_sanitize_api_response_full()

    print("\n31. Testing API response error sanitization...")
    test_sanitize_api_response_with_error()

    print("\n32. Testing agent output sanitization...")
    test_sanitize_agent_output()

    print("\n33. Testing agent output HTML escaping...")
    test_sanitize_agent_output_with_html()

    print("\n34. Testing GitHub tool output sanitization...")
    test_sanitize_tool_output_github()

    print("\n35. Testing sandbox tool output sanitization...")
    test_sanitize_tool_output_sandbox()

    print("\n--- Logging Sanitization Tests ---")

    print("\n36. Testing logging sanitization...")
    test_sanitize_for_logging()

    print("\n37. Testing logging truncation...")
    test_sanitize_for_logging_truncation()

    print("\n38. Testing logging PII redaction...")
    test_sanitize_for_logging_with_pii()

    print("\n--- Edge Case Tests ---")

    print("\n39. Testing None value handling...")
    test_sanitize_none_values()

    print("\n40. Testing empty string handling...")
    test_sanitize_empty_strings()

    print("\n41. Testing safe content preservation...")
    test_sanitize_preserves_safe_content()

    print("\n42. Testing deeply nested redaction...")
    test_nested_redaction()

    print("\n" + "=" * 60)
    print("All output sanitization tests passed!")
    print("=" * 60)
