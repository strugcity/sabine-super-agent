"""
Test suite for Error Handling and Exception System

Tests the custom exception classes, structured error returns,
and error context preservation.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.exceptions import (
    SABINEError,
    ErrorCategory,
    AuthenticationError,
    AuthorizationError,
    RepoAccessDeniedError,
    ValidationError,
    InvalidRoleError,
    DatabaseError,
    TaskNotFoundError,
    TaskClaimError,
    ExternalServiceError,
    GitHubAPIError,
    LLMAPIError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
    AgentError,
    AgentNoToolsError,
    AgentToolFailuresError,
    TaskQueueError,
    ConfigurationError,
    MissingCredentialsError,
    OperationResult,
)


# =============================================================================
# Base Exception Tests
# =============================================================================

def test_sabine_error_basic():
    """Test basic SABINEError creation and attributes."""
    error = SABINEError(
        message="Test error",
        status_code=500,
        category=ErrorCategory.INTERNAL
    )

    assert error.message == "Test error"
    assert error.status_code == 500
    assert error.category == ErrorCategory.INTERNAL
    assert str(error) == "Test error"
    print("  [OK] Basic SABINEError works correctly")


def test_sabine_error_with_context():
    """Test SABINEError with context dictionary."""
    error = SABINEError(
        message="Operation failed",
        status_code=400,
        category=ErrorCategory.VALIDATION,
        context={"field": "email", "value": "invalid"}
    )

    assert "field=email" in str(error)
    assert "value=invalid" in str(error)
    assert error.context["field"] == "email"
    print("  [OK] SABINEError with context works correctly")


def test_sabine_error_to_dict():
    """Test SABINEError serialization to dict."""
    error = SABINEError(
        message="Test error",
        status_code=500,
        category=ErrorCategory.INTERNAL,
        context={"key": "value"}
    )

    error_dict = error.to_dict()
    assert error_dict["error"] == "Test error"
    assert error_dict["status_code"] == 500
    assert error_dict["category"] == "internal"
    assert error_dict["context"]["key"] == "value"
    print("  [OK] SABINEError.to_dict() works correctly")


def test_sabine_error_chaining():
    """Test SABINEError with original_error for error chaining."""
    original = ValueError("Original cause")
    error = SABINEError(
        message="Wrapper error",
        status_code=500,
        category=ErrorCategory.INTERNAL,
        original_error=original
    )

    assert error.original_error is original
    error_dict = error.to_dict()
    assert "Original cause" in error_dict["original_error"]
    print("  [OK] SABINEError chaining works correctly")


# =============================================================================
# Authentication/Authorization Error Tests
# =============================================================================

def test_authentication_error():
    """Test AuthenticationError has correct defaults."""
    error = AuthenticationError()
    assert error.status_code == 401
    assert error.category == ErrorCategory.AUTHENTICATION
    print("  [OK] AuthenticationError has correct defaults")


def test_authorization_error():
    """Test AuthorizationError has correct defaults."""
    error = AuthorizationError()
    assert error.status_code == 403
    assert error.category == ErrorCategory.AUTHORIZATION
    print("  [OK] AuthorizationError has correct defaults")


def test_repo_access_denied_error():
    """Test RepoAccessDeniedError captures repo details."""
    error = RepoAccessDeniedError(
        role="frontend-ops-sabine",
        target_repo="sabine-super-agent",
        allowed_repos=["dream-team-strug"]
    )

    assert error.status_code == 403
    assert "frontend-ops-sabine" in str(error)
    assert "sabine-super-agent" in str(error)
    assert error.context["allowed_repos"] == ["dream-team-strug"]
    print("  [OK] RepoAccessDeniedError captures repo details")


# =============================================================================
# Validation Error Tests
# =============================================================================

def test_validation_error():
    """Test ValidationError has correct defaults."""
    error = ValidationError(message="Invalid input", field="email")
    assert error.status_code == 400
    assert error.category == ErrorCategory.VALIDATION
    assert error.context["field"] == "email"
    print("  [OK] ValidationError has correct defaults")


def test_invalid_role_error():
    """Test InvalidRoleError captures role details."""
    error = InvalidRoleError(
        role="unknown-role",
        available_roles=["backend-architect-sabine", "frontend-ops-sabine"]
    )

    assert error.status_code == 400
    assert "unknown-role" in str(error)
    assert "backend-architect-sabine" in str(error.context["available_roles"])
    print("  [OK] InvalidRoleError captures role details")


# =============================================================================
# Database Error Tests
# =============================================================================

def test_database_error():
    """Test DatabaseError has correct defaults."""
    error = DatabaseError(
        message="Query failed",
        operation="select",
        table="task_queue"
    )

    assert error.status_code == 500
    assert error.category == ErrorCategory.DATABASE
    assert error.context["operation"] == "select"
    assert error.context["table"] == "task_queue"
    print("  [OK] DatabaseError has correct defaults")


def test_task_not_found_error():
    """Test TaskNotFoundError has 404 status code."""
    error = TaskNotFoundError(task_id="abc-123")

    assert error.status_code == 404
    assert "abc-123" in str(error)
    print("  [OK] TaskNotFoundError has 404 status code")


def test_task_claim_error():
    """Test TaskClaimError has 409 status code."""
    error = TaskClaimError(
        task_id="abc-123",
        reason="Task already in progress"
    )

    assert error.status_code == 409
    assert error.context["reason"] == "Task already in progress"
    print("  [OK] TaskClaimError has 409 status code")


# =============================================================================
# External Service Error Tests
# =============================================================================

def test_external_service_error():
    """Test ExternalServiceError captures service name."""
    error = ExternalServiceError(
        service="SomeAPI",
        message="Connection refused",
        http_status=503
    )

    assert error.status_code == 502  # Bad Gateway
    assert error.category == ErrorCategory.EXTERNAL_SERVICE
    assert error.context["service"] == "SomeAPI"
    assert error.context["http_status"] == 503
    print("  [OK] ExternalServiceError captures service details")


def test_github_api_error():
    """Test GitHubAPIError captures GitHub-specific context."""
    error = GitHubAPIError(
        message="Rate limit exceeded",
        http_status=429,
        repo="strugcity/sabine-super-agent",
        operation="create_file"
    )

    assert error.context["repo"] == "strugcity/sabine-super-agent"
    assert error.context["operation"] == "create_file"
    assert error.context["http_status"] == 429
    print("  [OK] GitHubAPIError captures GitHub context")


def test_llm_api_error():
    """Test LLMAPIError captures model info."""
    error = LLMAPIError(
        message="Token limit exceeded",
        http_status=400,
        model="claude-3-sonnet"
    )

    assert error.context["model"] == "claude-3-sonnet"
    print("  [OK] LLMAPIError captures model info")


# =============================================================================
# Tool Execution Error Tests
# =============================================================================

def test_tool_execution_error():
    """Test ToolExecutionError captures tool details."""
    error = ToolExecutionError(
        tool_name="github_issues",
        message="File already exists",
        action="create_file"
    )

    assert error.status_code == 500
    assert error.category == ErrorCategory.TOOL_EXECUTION
    assert error.context["tool_name"] == "github_issues"
    assert error.context["action"] == "create_file"
    print("  [OK] ToolExecutionError captures tool details")


def test_tool_not_found_error():
    """Test ToolNotFoundError has 404 status code."""
    error = ToolNotFoundError(
        tool_name="unknown_tool",
        available_tools=["github_issues", "run_python_sandbox"]
    )

    assert error.status_code == 404
    assert "unknown_tool" in str(error)
    print("  [OK] ToolNotFoundError has 404 status code")


def test_tool_timeout_error():
    """Test ToolTimeoutError has 504 status code."""
    error = ToolTimeoutError(
        tool_name="run_python_sandbox",
        timeout_seconds=30
    )

    assert error.status_code == 504
    assert error.context["timeout_seconds"] == 30
    print("  [OK] ToolTimeoutError has 504 status code")


# =============================================================================
# Agent Error Tests
# =============================================================================

def test_agent_error():
    """Test AgentError captures role and task context."""
    error = AgentError(
        message="Agent execution failed",
        role="backend-architect-sabine",
        task_id="task-123"
    )

    assert error.status_code == 500
    assert error.category == ErrorCategory.AGENT
    assert error.context["role"] == "backend-architect-sabine"
    assert error.context["task_id"] == "task-123"
    print("  [OK] AgentError captures role and task context")


def test_agent_no_tools_error():
    """Test AgentNoToolsError for tool verification failures."""
    error = AgentNoToolsError(
        role="frontend-ops-sabine",
        task_id="task-456",
        expected_tools=["github_issues"]
    )

    assert "did not call any required tools" in str(error)
    assert error.context["expected_tools"] == ["github_issues"]
    print("  [OK] AgentNoToolsError for tool verification")


def test_agent_tool_failures_error():
    """Test AgentToolFailuresError captures failure details."""
    error = AgentToolFailuresError(
        role="backend-architect-sabine",
        task_id="task-789",
        failure_count=2,
        failures=[
            {"tool": "github_issues", "error": "Auth failed"},
            {"tool": "run_python_sandbox", "error": "Timeout"}
        ]
    )

    assert "2 tool(s) failed" in str(error)
    assert error.context["failure_count"] == 2
    assert len(error.context["failures"]) == 2
    print("  [OK] AgentToolFailuresError captures failure details")


# =============================================================================
# Configuration Error Tests
# =============================================================================

def test_configuration_error():
    """Test ConfigurationError for missing config."""
    error = ConfigurationError(
        message="Missing required configuration",
        config_key="ANTHROPIC_API_KEY"
    )

    assert error.status_code == 500
    assert error.category == ErrorCategory.CONFIGURATION
    assert error.context["config_key"] == "ANTHROPIC_API_KEY"
    print("  [OK] ConfigurationError for missing config")


def test_missing_credentials_error():
    """Test MissingCredentialsError for service credentials."""
    error = MissingCredentialsError(
        service="Supabase",
        required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    )

    assert "Supabase" in str(error)
    assert error.context["service"] == "Supabase"
    assert len(error.context["required_keys"]) == 2
    print("  [OK] MissingCredentialsError for service credentials")


# =============================================================================
# OperationResult Tests
# =============================================================================

def test_operation_result_success():
    """Test OperationResult.ok() for successful operations."""
    result = OperationResult.ok({"id": "123", "status": "created"})

    assert result.success == True
    assert result.data["id"] == "123"
    assert result.error is None
    print("  [OK] OperationResult.ok() works correctly")


def test_operation_result_failure():
    """Test OperationResult.fail() for failed operations."""
    error = TaskNotFoundError(task_id="abc-123")
    result = OperationResult.fail(error)

    assert result.success == False
    assert result.error is error
    assert result.data == {}
    print("  [OK] OperationResult.fail() works correctly")


def test_operation_result_to_dict_success():
    """Test OperationResult.to_dict() for success."""
    result = OperationResult.ok({"key": "value"})
    result_dict = result.to_dict()

    assert result_dict["success"] == True
    assert result_dict["data"]["key"] == "value"
    print("  [OK] OperationResult.to_dict() success works")


def test_operation_result_to_dict_failure():
    """Test OperationResult.to_dict() for failure."""
    error = ValidationError(message="Bad input", field="email")
    result = OperationResult.fail(error)
    result_dict = result.to_dict()

    assert result_dict["success"] == False
    assert result_dict["error"]["error"] == "Bad input"
    assert result_dict["error"]["status_code"] == 400
    print("  [OK] OperationResult.to_dict() failure works")


# =============================================================================
# Error Classification Tests
# =============================================================================

def test_error_category_values():
    """Test ErrorCategory enum values."""
    assert ErrorCategory.AUTHENTICATION.value == "authentication"
    assert ErrorCategory.AUTHORIZATION.value == "authorization"
    assert ErrorCategory.VALIDATION.value == "validation"
    assert ErrorCategory.DATABASE.value == "database"
    assert ErrorCategory.EXTERNAL_SERVICE.value == "external_service"
    assert ErrorCategory.TOOL_EXECUTION.value == "tool_execution"
    assert ErrorCategory.AGENT.value == "agent"
    assert ErrorCategory.TASK_QUEUE.value == "task_queue"
    assert ErrorCategory.CONFIGURATION.value == "configuration"
    assert ErrorCategory.INTERNAL.value == "internal"
    print("  [OK] All ErrorCategory values correct")


def test_http_status_mapping():
    """Test that exceptions have appropriate HTTP status codes."""
    test_cases = [
        (AuthenticationError(), 401),
        (AuthorizationError(), 403),
        (ValidationError(), 400),
        (TaskNotFoundError(task_id="x"), 404),
        (TaskClaimError(task_id="x"), 409),
        (ExternalServiceError(service="test"), 502),
        (ToolTimeoutError(tool_name="test", timeout_seconds=30), 504),
    ]

    for error, expected_status in test_cases:
        assert error.status_code == expected_status, \
            f"{type(error).__name__} should have status {expected_status}, got {error.status_code}"

    print("  [OK] All HTTP status codes mapped correctly")


# =============================================================================
# Error Chaining Tests
# =============================================================================

def test_error_chain_preservation():
    """Test that error chains preserve original context."""
    # Simulate a chain of errors
    original = ConnectionError("Network unreachable")
    db_error = DatabaseError(
        message="Failed to connect",
        operation="connect",
        original_error=original
    )
    service_error = ExternalServiceError(
        service="Database",
        message="Service unavailable",
        original_error=db_error
    )

    # Check the chain is preserved
    assert service_error.original_error is db_error
    assert db_error.original_error is original
    assert "Network unreachable" in str(db_error.original_error)
    print("  [OK] Error chain preserved correctly")


def test_raise_from_pattern():
    """Test that exceptions work with 'raise from' pattern."""
    try:
        try:
            raise ValueError("Original cause")
        except ValueError as e:
            raise SABINEError(
                message="Wrapper error",
                status_code=500,
                category=ErrorCategory.INTERNAL,
                original_error=e
            ) from e
    except SABINEError as wrapped:
        assert wrapped.__cause__ is not None
        assert str(wrapped.__cause__) == "Original cause"
        print("  [OK] 'raise from' pattern works correctly")


# =============================================================================
# TaskQueueService.is_retryable_error Classification Tests
# =============================================================================

# task_queue.py imports supabase at module level, but is_retryable_error is a
# pure static method (string ops only).  Mock the heavy deps so the module
# loads without a real DB connection.
import unittest.mock as _mock
sys.modules.setdefault("supabase", _mock.MagicMock())

from backend.services.task_queue import TaskQueueService


def test_is_retryable_rate_limit():
    """Rate-limit errors are transient and should be retried."""
    assert TaskQueueService.is_retryable_error(
        "Error code: 429 - rate_limit_error: You exceeded your rate limit"
    ) is True
    assert TaskQueueService.is_retryable_error(
        "Rate limit exceeded for model claude-sonnet-4"
    ) is True
    assert TaskQueueService.is_retryable_error(
        "quota exceeded, please try again later"
    ) is True
    print("  [OK] Rate-limit errors classified as retryable")


def test_is_retryable_credits_exhausted():
    """Billing / credits errors are permanent until operator action — not retried."""
    assert TaskQueueService.is_retryable_error(
        "Insufficient credits: your balance is 0.00"
    ) is False
    assert TaskQueueService.is_retryable_error(
        "Out of credits — please reload your account"
    ) is False
    assert TaskQueueService.is_retryable_error(
        "Credits exhausted for organization abc-123"
    ) is False
    assert TaskQueueService.is_retryable_error(
        "No credits remaining on this API key"
    ) is False
    # Mixed-case should still match (normalised to lower)
    assert TaskQueueService.is_retryable_error(
        "INSUFFICIENT CREDITS: balance depleted"
    ) is False
    print("  [OK] Credits-exhaustion errors classified as non-retryable")


def test_is_retryable_transient_server_errors():
    """5xx server errors are transient and should be retried."""
    assert TaskQueueService.is_retryable_error("500 Internal Server Error") is True
    assert TaskQueueService.is_retryable_error("502 Bad Gateway") is True
    assert TaskQueueService.is_retryable_error("503 Service Unavailable") is True
    assert TaskQueueService.is_retryable_error("504 Gateway Timeout") is True
    assert TaskQueueService.is_retryable_error("Connection reset by peer") is True
    assert TaskQueueService.is_retryable_error("Socket timeout after 30s") is True
    print("  [OK] Transient server errors classified as retryable")


def test_is_retryable_permanent_auth_errors():
    """Auth and permission errors are permanent and should not be retried."""
    assert TaskQueueService.is_retryable_error("401 Unauthorized") is False
    assert TaskQueueService.is_retryable_error("403 Forbidden: no access") is False
    assert TaskQueueService.is_retryable_error("Unauthorized: invalid API key") is False
    print("  [OK] Auth/permission errors classified as non-retryable")


def test_is_retryable_permanent_validation_errors():
    """Validation / not-found errors are permanent and should not be retried."""
    assert TaskQueueService.is_retryable_error("Validation failed: field 'role' required") is False
    assert TaskQueueService.is_retryable_error("404 Not Found: task does not exist") is False
    assert TaskQueueService.is_retryable_error("Invalid role: unknown-agent") is False
    print("  [OK] Validation/not-found errors classified as non-retryable")


def test_is_retryable_unknown_defaults_to_true():
    """Unrecognised errors default to retryable (optimistic)."""
    assert TaskQueueService.is_retryable_error("Something unexpected happened") is True
    assert TaskQueueService.is_retryable_error("") is True
    print("  [OK] Unknown errors default to retryable")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Error Handling Tests")
    print("=" * 60)

    print("\n1. Testing base SABINEError...")
    test_sabine_error_basic()

    print("\n2. Testing SABINEError with context...")
    test_sabine_error_with_context()

    print("\n3. Testing SABINEError.to_dict()...")
    test_sabine_error_to_dict()

    print("\n4. Testing SABINEError chaining...")
    test_sabine_error_chaining()

    print("\n5. Testing AuthenticationError...")
    test_authentication_error()

    print("\n6. Testing AuthorizationError...")
    test_authorization_error()

    print("\n7. Testing RepoAccessDeniedError...")
    test_repo_access_denied_error()

    print("\n8. Testing ValidationError...")
    test_validation_error()

    print("\n9. Testing InvalidRoleError...")
    test_invalid_role_error()

    print("\n10. Testing DatabaseError...")
    test_database_error()

    print("\n11. Testing TaskNotFoundError...")
    test_task_not_found_error()

    print("\n12. Testing TaskClaimError...")
    test_task_claim_error()

    print("\n13. Testing ExternalServiceError...")
    test_external_service_error()

    print("\n14. Testing GitHubAPIError...")
    test_github_api_error()

    print("\n15. Testing LLMAPIError...")
    test_llm_api_error()

    print("\n16. Testing ToolExecutionError...")
    test_tool_execution_error()

    print("\n17. Testing ToolNotFoundError...")
    test_tool_not_found_error()

    print("\n18. Testing ToolTimeoutError...")
    test_tool_timeout_error()

    print("\n19. Testing AgentError...")
    test_agent_error()

    print("\n20. Testing AgentNoToolsError...")
    test_agent_no_tools_error()

    print("\n21. Testing AgentToolFailuresError...")
    test_agent_tool_failures_error()

    print("\n22. Testing ConfigurationError...")
    test_configuration_error()

    print("\n23. Testing MissingCredentialsError...")
    test_missing_credentials_error()

    print("\n24. Testing OperationResult.ok()...")
    test_operation_result_success()

    print("\n25. Testing OperationResult.fail()...")
    test_operation_result_failure()

    print("\n26. Testing OperationResult.to_dict() success...")
    test_operation_result_to_dict_success()

    print("\n27. Testing OperationResult.to_dict() failure...")
    test_operation_result_to_dict_failure()

    print("\n28. Testing ErrorCategory values...")
    test_error_category_values()

    print("\n29. Testing HTTP status mapping...")
    test_http_status_mapping()

    print("\n30. Testing error chain preservation...")
    test_error_chain_preservation()

    print("\n31. Testing 'raise from' pattern...")
    test_raise_from_pattern()

    print("\n32. Testing is_retryable_error: rate-limit errors...")
    test_is_retryable_rate_limit()

    print("\n33. Testing is_retryable_error: credits-exhaustion errors...")
    test_is_retryable_credits_exhausted()

    print("\n34. Testing is_retryable_error: transient server errors...")
    test_is_retryable_transient_server_errors()

    print("\n35. Testing is_retryable_error: permanent auth errors...")
    test_is_retryable_permanent_auth_errors()

    print("\n36. Testing is_retryable_error: permanent validation errors...")
    test_is_retryable_permanent_validation_errors()

    print("\n37. Testing is_retryable_error: unknown errors default retryable...")
    test_is_retryable_unknown_defaults_to_true()

    print("\n" + "=" * 60)
    print("All error handling tests passed!")
    print("=" * 60)
