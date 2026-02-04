"""
Custom Exception Classes for SABINE
====================================

This module provides a hierarchy of custom exceptions that preserve context
through the error chain. All exceptions support:

1. Error chaining with `raise ... from e`
2. HTTP status code mapping for API responses
3. Error classification for monitoring/alerting
4. Original context preservation

Owner: @backend-architect-sabine
PRD Reference: Project Dream Team - Error Handling & Observability
"""

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCategory(str, Enum):
    """Categories for error classification and monitoring."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    DATABASE = "database"
    EXTERNAL_SERVICE = "external_service"
    TOOL_EXECUTION = "tool_execution"
    AGENT = "agent"
    TASK_QUEUE = "task_queue"
    CONFIGURATION = "configuration"
    INTERNAL = "internal"


# =============================================================================
# Base Exception
# =============================================================================

class SABINEError(Exception):
    """
    Base exception class for all SABINE errors.

    Provides:
    - HTTP status code for API responses
    - Error category for monitoring
    - Context dictionary for debugging
    - Proper error chaining support

    Usage:
        try:
            # some operation
        except SomeError as e:
            raise SABINEError(
                message="Failed to process",
                status_code=500,
                category=ErrorCategory.INTERNAL,
                context={"operation": "process"},
            ) from e
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        category: ErrorCategory = ErrorCategory.INTERNAL,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.category = category
        self.context = context or {}
        self.original_error = original_error

        # Build full message with context
        full_message = message
        if context:
            context_str = ", ".join(f"{k}={v}" for k, v in context.items())
            full_message = f"{message} [{context_str}]"

        super().__init__(full_message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result = {
            "error": self.message,
            "category": self.category.value,
            "status_code": self.status_code,
        }
        if self.context:
            result["context"] = self.context
        if self.original_error:
            result["original_error"] = str(self.original_error)
        return result


# =============================================================================
# Authentication & Authorization Errors
# =============================================================================

class AuthenticationError(SABINEError):
    """Raised when authentication fails (401)."""

    def __init__(
        self,
        message: str = "Authentication failed",
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            status_code=401,
            category=ErrorCategory.AUTHENTICATION,
            context=context,
            original_error=original_error,
        )


class AuthorizationError(SABINEError):
    """Raised when authorization fails (403)."""

    def __init__(
        self,
        message: str = "Not authorized",
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            category=ErrorCategory.AUTHORIZATION,
            context=context,
            original_error=original_error,
        )


class RepoAccessDeniedError(AuthorizationError):
    """Raised when an agent tries to access an unauthorized repository."""

    def __init__(
        self,
        role: str,
        target_repo: str,
        allowed_repos: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        context = {
            "role": role,
            "target_repo": target_repo,
        }
        if allowed_repos:
            context["allowed_repos"] = allowed_repos

        super().__init__(
            message=f"Role '{role}' not authorized for repository '{target_repo}'",
            context=context,
            original_error=original_error,
        )


# =============================================================================
# Validation Errors
# =============================================================================

class ValidationError(SABINEError):
    """Raised when input validation fails (400)."""

    def __init__(
        self,
        message: str = "Validation failed",
        field: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        if field:
            ctx["field"] = field

        super().__init__(
            message=message,
            status_code=400,
            category=ErrorCategory.VALIDATION,
            context=ctx,
            original_error=original_error,
        )


class InvalidRoleError(ValidationError):
    """Raised when an invalid role is specified."""

    def __init__(
        self,
        role: str,
        available_roles: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        context = {"role": role}
        if available_roles:
            context["available_roles"] = available_roles

        super().__init__(
            message=f"Invalid role: '{role}'",
            field="role",
            context=context,
            original_error=original_error,
        )


# =============================================================================
# Database Errors
# =============================================================================

class DatabaseError(SABINEError):
    """Raised when a database operation fails."""

    def __init__(
        self,
        message: str = "Database operation failed",
        operation: Optional[str] = None,
        table: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        if operation:
            ctx["operation"] = operation
        if table:
            ctx["table"] = table

        super().__init__(
            message=message,
            status_code=500,
            category=ErrorCategory.DATABASE,
            context=ctx,
            original_error=original_error,
        )


class TaskNotFoundError(DatabaseError):
    """Raised when a task is not found in the queue."""

    def __init__(
        self,
        task_id: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Task not found: {task_id}",
            operation="select",
            table="task_queue",
            context={"task_id": task_id},
            original_error=original_error,
        )
        self.status_code = 404  # Not Found


class TaskClaimError(DatabaseError):
    """Raised when a task cannot be claimed."""

    def __init__(
        self,
        task_id: str,
        reason: str = "Task may already be claimed or completed",
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Cannot claim task {task_id}: {reason}",
            operation="update",
            table="task_queue",
            context={"task_id": task_id, "reason": reason},
            original_error=original_error,
        )
        self.status_code = 409  # Conflict


# =============================================================================
# External Service Errors
# =============================================================================

class ExternalServiceError(SABINEError):
    """Raised when an external service call fails."""

    def __init__(
        self,
        service: str,
        message: str = "External service call failed",
        http_status: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        ctx["service"] = service
        if http_status:
            ctx["http_status"] = http_status

        super().__init__(
            message=f"{service}: {message}",
            status_code=502,  # Bad Gateway
            category=ErrorCategory.EXTERNAL_SERVICE,
            context=ctx,
            original_error=original_error,
        )


class GitHubAPIError(ExternalServiceError):
    """Raised when GitHub API calls fail."""

    def __init__(
        self,
        message: str = "GitHub API call failed",
        http_status: Optional[int] = None,
        repo: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        if repo:
            ctx["repo"] = repo
        if operation:
            ctx["operation"] = operation

        super().__init__(
            service="GitHub",
            message=message,
            http_status=http_status,
            context=ctx,
            original_error=original_error,
        )


class LLMAPIError(ExternalServiceError):
    """Raised when LLM API calls fail."""

    def __init__(
        self,
        message: str = "LLM API call failed",
        http_status: Optional[int] = None,
        model: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        if model:
            ctx["model"] = model

        super().__init__(
            service="LLM",
            message=message,
            http_status=http_status,
            context=ctx,
            original_error=original_error,
        )


# =============================================================================
# Tool Execution Errors
# =============================================================================

class ToolExecutionError(SABINEError):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        message: str = "Tool execution failed",
        action: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        ctx["tool_name"] = tool_name
        if action:
            ctx["action"] = action

        super().__init__(
            message=f"Tool '{tool_name}': {message}",
            status_code=500,
            category=ErrorCategory.TOOL_EXECUTION,
            context=ctx,
            original_error=original_error,
        )


class ToolNotFoundError(ToolExecutionError):
    """Raised when a requested tool is not available."""

    def __init__(
        self,
        tool_name: str,
        available_tools: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        context = {}
        if available_tools:
            context["available_tools"] = available_tools

        super().__init__(
            tool_name=tool_name,
            message="Tool not found",
            context=context,
            original_error=original_error,
        )
        self.status_code = 404


class ToolTimeoutError(ToolExecutionError):
    """Raised when a tool execution times out."""

    def __init__(
        self,
        tool_name: str,
        timeout_seconds: int,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            tool_name=tool_name,
            message=f"Execution timed out after {timeout_seconds}s",
            context={"timeout_seconds": timeout_seconds},
            original_error=original_error,
        )
        self.status_code = 504  # Gateway Timeout


# =============================================================================
# Agent Errors
# =============================================================================

class AgentError(SABINEError):
    """Raised when agent execution fails."""

    def __init__(
        self,
        message: str = "Agent execution failed",
        role: Optional[str] = None,
        task_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        if role:
            ctx["role"] = role
        if task_id:
            ctx["task_id"] = task_id

        super().__init__(
            message=message,
            status_code=500,
            category=ErrorCategory.AGENT,
            context=ctx,
            original_error=original_error,
        )


class AgentNoToolsError(AgentError):
    """Raised when an agent didn't call any required tools."""

    def __init__(
        self,
        role: str,
        task_id: Optional[str] = None,
        expected_tools: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        context = {}
        if expected_tools:
            context["expected_tools"] = expected_tools

        super().__init__(
            message="Agent did not call any required tools",
            role=role,
            task_id=task_id,
            context=context,
            original_error=original_error,
        )


class AgentToolFailuresError(AgentError):
    """Raised when agent tools failed during execution."""

    def __init__(
        self,
        role: str,
        task_id: Optional[str] = None,
        failure_count: int = 0,
        failures: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        context = {"failure_count": failure_count}
        if failures:
            context["failures"] = failures[:5]  # Limit to first 5

        super().__init__(
            message=f"{failure_count} tool(s) failed during execution",
            role=role,
            task_id=task_id,
            context=context,
            original_error=original_error,
        )


# =============================================================================
# Task Queue Errors
# =============================================================================

class TaskQueueError(SABINEError):
    """Raised when task queue operations fail."""

    def __init__(
        self,
        message: str = "Task queue operation failed",
        task_id: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
        status_code: int = 500,
    ):
        ctx = context or {}
        if task_id:
            ctx["task_id"] = task_id
        if operation:
            ctx["operation"] = operation

        super().__init__(
            message=message,
            status_code=status_code,
            category=ErrorCategory.TASK_QUEUE,
            context=ctx,
            original_error=original_error,
        )


class TaskDependencyError(TaskQueueError):
    """Raised when task dependencies are not met."""

    def __init__(
        self,
        task_id: str,
        pending_dependencies: list,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message="Task dependencies not met",
            task_id=task_id,
            operation="execute",
            context={"pending_dependencies": pending_dependencies},
            original_error=original_error,
        )
        self.status_code = 409  # Conflict


class DependencyNotFoundError(TaskQueueError):
    """Raised when a dependency task ID doesn't exist."""

    def __init__(
        self,
        task_id: Optional[str] = None,
        missing_dependency_id: str = "",
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Dependency task not found: {missing_dependency_id}",
            task_id=task_id,
            operation="create",
            context={"missing_dependency_id": missing_dependency_id},
            original_error=original_error,
        )
        self.status_code = 400  # Bad Request


class CircularDependencyError(TaskQueueError):
    """Raised when a circular dependency is detected."""

    def __init__(
        self,
        task_id: Optional[str] = None,
        dependency_chain: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        chain_str = " -> ".join(dependency_chain) if dependency_chain else "unknown"
        super().__init__(
            message=f"Circular dependency detected: {chain_str}",
            task_id=task_id,
            operation="create",
            context={"dependency_chain": dependency_chain or []},
            original_error=original_error,
        )
        self.status_code = 400  # Bad Request


class FailedDependencyError(TaskQueueError):
    """Raised when a dependency task has failed."""

    def __init__(
        self,
        task_id: Optional[str] = None,
        failed_dependency_id: str = "",
        failure_reason: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = {"failed_dependency_id": failed_dependency_id}
        if failure_reason:
            ctx["failure_reason"] = failure_reason

        super().__init__(
            message=f"Dependency task failed: {failed_dependency_id}",
            task_id=task_id,
            operation="execute",
            context=ctx,
            original_error=original_error,
        )
        self.status_code = 424  # Failed Dependency


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(SABINEError):
    """Raised when configuration is missing or invalid."""

    def __init__(
        self,
        message: str = "Configuration error",
        config_key: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        ctx = context or {}
        if config_key:
            ctx["config_key"] = config_key

        super().__init__(
            message=message,
            status_code=500,
            category=ErrorCategory.CONFIGURATION,
            context=ctx,
            original_error=original_error,
        )


class MissingCredentialsError(ConfigurationError):
    """Raised when required credentials are missing."""

    def __init__(
        self,
        service: str,
        required_keys: Optional[list] = None,
        original_error: Optional[Exception] = None,
    ):
        context = {"service": service}
        if required_keys:
            context["required_keys"] = required_keys

        super().__init__(
            message=f"Missing credentials for {service}",
            context=context,
            original_error=original_error,
        )


# =============================================================================
# Result Classes for Operations
# =============================================================================

class OperationResult:
    """
    Structured result for operations that can fail.

    Use this instead of returning None/False when an operation fails,
    to preserve error context.

    Usage:
        result = await some_operation()
        if result.success:
            print(f"Created: {result.data['id']}")
        else:
            print(f"Failed: {result.error.message}")
    """

    def __init__(
        self,
        success: bool,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[SABINEError] = None,
    ):
        self.success = success
        self.data = data or {}
        self.error = error

    @classmethod
    def ok(cls, data: Optional[Dict[str, Any]] = None) -> "OperationResult":
        """Create a successful result."""
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: SABINEError) -> "OperationResult":
        """Create a failed result."""
        return cls(success=False, error=error)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for API responses."""
        if self.success:
            return {"success": True, "data": self.data}
        else:
            return {
                "success": False,
                "error": self.error.to_dict() if self.error else {"error": "Unknown error"},
            }
