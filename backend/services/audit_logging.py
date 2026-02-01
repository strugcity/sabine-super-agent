"""
Audit Logging Service - Persistent Tool Execution Auditing
===========================================================

This module provides persistent audit logging for all tool executions by
Dream Team agents. Logs are stored in the Supabase `tool_audit_log` table
for debugging, compliance, and security monitoring.

Key Features:
1. Persistent storage: All tool executions logged to database
2. Structured data: JSON input/output with sensitive data redaction
3. Performance metrics: Execution time tracking
4. Security monitoring: Blocked repo access attempts logged
5. Multi-tenant support: User ID association for filtering

Owner: @backend-architect-sabine
PRD Reference: Project Dream Team - Agent Observability
"""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

TOOL_AUDIT_TABLE = "tool_audit_log"

# Maximum size for stored input/output (to prevent bloat)
MAX_INPUT_SIZE = 2000
MAX_OUTPUT_SIZE = 2000

# Patterns for sensitive data redaction
SENSITIVE_PATTERNS = [
    (r'(api[_-]?key|apikey)["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]+', r'\1=***REDACTED***'),
    (r'(token|secret|password|credential)["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]+', r'\1=***REDACTED***'),
    (r'(bearer\s+)[a-zA-Z0-9_\-\.]+', r'\1***REDACTED***'),
    # Anthropic API keys (sk-ant-...)
    (r'sk-ant-[a-zA-Z0-9_\-]+', '***ANTHROPIC_KEY_REDACTED***'),
    # OpenAI API keys (sk-...)
    (r'sk-[a-zA-Z0-9_\-]{20,}', '***API_KEY_REDACTED***'),
    # GitHub tokens (ghp_...)
    (r'ghp_[a-zA-Z0-9]{20,}', '***GITHUB_TOKEN_REDACTED***'),
    # Supabase keys (eyJ...)
    (r'eyJ[a-zA-Z0-9_\-]{50,}', '***JWT_REDACTED***'),
]


# =============================================================================
# Supabase Client
# =============================================================================

_supabase_client: Optional[Client] = None


def get_supabase_client() -> Optional[Client]:
    """Get or create Supabase client for audit logging."""
    global _supabase_client

    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            logger.warning("Supabase credentials not configured - audit logging disabled")
            return None

        try:
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            logger.info("Supabase client initialized for audit logging")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            return None

    return _supabase_client


# =============================================================================
# Helper Functions
# =============================================================================

def redact_sensitive_data(data: Any) -> Any:
    """
    Redact sensitive data from input/output before logging.

    Handles strings, dicts, and lists recursively.
    """
    if isinstance(data, str):
        result = data
        for pattern, replacement in SENSITIVE_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    elif isinstance(data, dict):
        return {k: redact_sensitive_data(v) for k, v in data.items()}

    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]

    else:
        return data


def truncate_data(data: Any, max_size: int) -> Any:
    """
    Truncate data to fit within size limits.

    Returns a summary dict if the data is too large.
    """
    if data is None:
        return None

    # Convert to string to measure size
    import json
    try:
        data_str = json.dumps(data) if not isinstance(data, str) else data
    except (TypeError, ValueError):
        data_str = str(data)

    if len(data_str) <= max_size:
        return data

    # Truncate and add indicator
    if isinstance(data, dict):
        # For dicts, try to keep keys and truncate values
        truncated = {}
        for key, value in data.items():
            value_str = str(value)
            if len(value_str) > 200:
                truncated[key] = f"{value_str[:200]}... [TRUNCATED]"
            else:
                truncated[key] = value
        return truncated

    elif isinstance(data, str):
        return f"{data[:max_size-30]}... [TRUNCATED, total {len(data)} chars]"

    else:
        return {"_truncated": True, "_preview": str(data)[:max_size]}


def extract_repo_info(tool_name: str, input_params: Dict) -> tuple[Optional[str], Optional[str]]:
    """
    Extract repository and path information from tool input.

    Returns (target_repo, target_path) tuple.
    """
    target_repo = None
    target_path = None

    if tool_name == "github_issues":
        owner = input_params.get("owner", "")
        repo = input_params.get("repo", "")
        if owner and repo:
            target_repo = f"{owner}/{repo}"
        target_path = input_params.get("path") or input_params.get("issue_number")

    return target_repo, target_path


def classify_error(error_message: str) -> Optional[str]:
    """
    Classify error type from error message for easier filtering.
    """
    if not error_message:
        return None

    error_lower = error_message.lower()

    if "permission" in error_lower or "403" in error_lower:
        return "permission_denied"
    elif "not found" in error_lower or "404" in error_lower:
        return "not_found"
    elif "authentication" in error_lower or "401" in error_lower:
        return "auth_failed"
    elif "timeout" in error_lower:
        return "timeout"
    elif "rate limit" in error_lower or "429" in error_lower:
        return "rate_limited"
    elif "network" in error_lower or "connection" in error_lower:
        return "network_error"
    elif "blocked" in error_lower or "denied" in error_lower:
        return "blocked"
    else:
        return "unknown"


# =============================================================================
# Main Audit Logging Functions
# =============================================================================

async def log_tool_execution(
    tool_name: str,
    tool_action: Optional[str] = None,
    input_params: Optional[Dict] = None,
    output_data: Optional[Dict] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    artifact_created: Optional[str] = None,
    execution_time_ms: Optional[int] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[UUID] = None,
    agent_role: Optional[str] = None,
) -> Optional[UUID]:
    """
    Log a tool execution to the audit log.

    This is the main entry point for audit logging. Call this after every
    tool execution (success or failure) to maintain a complete audit trail.

    Args:
        tool_name: Name of the tool (e.g., 'github_issues', 'run_python_sandbox')
        tool_action: Specific action (e.g., 'create_file', 'list')
        input_params: Tool input parameters (will be redacted)
        output_data: Tool output/result (will be truncated)
        status: 'success', 'error', 'timeout', or 'blocked'
        error_message: Error details if status is not 'success'
        artifact_created: What was created (file path, issue #, etc.)
        execution_time_ms: How long the tool call took
        user_id: User who initiated the request
        session_id: Session/conversation context
        task_id: Task ID if this is part of orchestrated execution
        agent_role: Agent role that executed the tool

    Returns:
        UUID of the created audit log entry, or None if logging failed
    """
    client = get_supabase_client()
    if not client:
        logger.debug("Supabase client not available - skipping audit log")
        return None

    try:
        # Redact sensitive data from inputs
        safe_input = redact_sensitive_data(input_params) if input_params else {}
        safe_input = truncate_data(safe_input, MAX_INPUT_SIZE)

        # Create output summary (redacted and truncated)
        output_summary = {}
        if output_data:
            safe_output = redact_sensitive_data(output_data)
            output_summary = truncate_data(safe_output, MAX_OUTPUT_SIZE)

        # Extract repo info from input
        target_repo, target_path = extract_repo_info(tool_name, input_params or {})

        # Classify error type
        error_type = classify_error(error_message) if error_message else None

        # Build audit log entry
        audit_entry = {
            "id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "task_id": str(task_id) if task_id else None,
            "agent_role": agent_role,
            "tool_name": tool_name,
            "tool_action": tool_action,
            "input_params": safe_input,
            "output_summary": output_summary,
            "status": status,
            "error_type": error_type,
            "error_message": error_message[:500] if error_message else None,
            "target_repo": target_repo,
            "target_path": str(target_path) if target_path else None,
            "artifact_created": artifact_created,
            "execution_time_ms": execution_time_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Insert into database
        result = client.table(TOOL_AUDIT_TABLE).insert(audit_entry).execute()

        if result.data:
            audit_id = UUID(audit_entry["id"])
            logger.debug(f"Audit log created: {audit_id} - {tool_name} ({status})")
            return audit_id
        else:
            logger.warning(f"Failed to create audit log entry for {tool_name}")
            return None

    except Exception as e:
        # Don't let audit logging failures break the main flow
        logger.error(f"Error logging tool execution to audit log: {e}")
        return None


async def log_tool_executions_batch(
    executions: List[Dict[str, Any]],
    task_id: Optional[UUID] = None,
    user_id: Optional[str] = None,
    agent_role: Optional[str] = None,
) -> int:
    """
    Log multiple tool executions in a batch.

    This is more efficient than calling log_tool_execution multiple times
    when processing results from an agent run.

    Args:
        executions: List of execution dicts with tool_name, status, etc.
        task_id: Common task ID for all executions
        user_id: Common user ID for all executions
        agent_role: Common agent role for all executions

    Returns:
        Number of successfully logged entries
    """
    client = get_supabase_client()
    if not client:
        return 0

    logged_count = 0

    for execution in executions:
        try:
            # Skip tool_call entries (we only want to log results)
            if execution.get("type") == "tool_call":
                continue

            tool_name = execution.get("tool_name", "unknown")
            status = execution.get("status", "unknown")
            error_message = execution.get("error")
            artifact = execution.get("artifact_created")

            audit_id = await log_tool_execution(
                tool_name=tool_name,
                status=status,
                error_message=error_message,
                artifact_created=artifact,
                task_id=task_id,
                user_id=user_id,
                agent_role=agent_role,
            )

            if audit_id:
                logged_count += 1

        except Exception as e:
            logger.error(f"Error logging execution in batch: {e}")
            continue

    logger.info(f"Batch audit logging: {logged_count}/{len(executions)} entries logged")
    return logged_count


# =============================================================================
# Query Functions (for debugging and monitoring)
# =============================================================================

async def get_task_audit_logs(task_id: UUID) -> List[Dict]:
    """
    Get all audit logs for a specific task.

    Useful for debugging task execution issues.
    """
    client = get_supabase_client()
    if not client:
        return []

    try:
        result = client.table(TOOL_AUDIT_TABLE)\
            .select("*")\
            .eq("task_id", str(task_id))\
            .order("created_at", desc=False)\
            .execute()

        return result.data if result.data else []

    except Exception as e:
        logger.error(f"Error fetching audit logs for task {task_id}: {e}")
        return []


async def get_recent_failures(
    hours: int = 24,
    limit: int = 100
) -> List[Dict]:
    """
    Get recent tool execution failures.

    Useful for monitoring and alerting.
    """
    client = get_supabase_client()
    if not client:
        return []

    try:
        cutoff = datetime.now(timezone.utc).isoformat()
        # Note: Supabase doesn't support date arithmetic in filters directly,
        # so we calculate the cutoff in Python

        result = client.table(TOOL_AUDIT_TABLE)\
            .select("*")\
            .eq("status", "error")\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        return result.data if result.data else []

    except Exception as e:
        logger.error(f"Error fetching recent failures: {e}")
        return []


async def get_blocked_access_attempts(
    hours: int = 24,
    limit: int = 100
) -> List[Dict]:
    """
    Get recent blocked repository access attempts.

    Critical for security monitoring.
    """
    client = get_supabase_client()
    if not client:
        return []

    try:
        result = client.table(TOOL_AUDIT_TABLE)\
            .select("*")\
            .eq("status", "blocked")\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        return result.data if result.data else []

    except Exception as e:
        logger.error(f"Error fetching blocked access attempts: {e}")
        return []


# =============================================================================
# Context Manager for Timing
# =============================================================================

class ToolExecutionTimer:
    """
    Context manager for timing tool executions.

    Usage:
        with ToolExecutionTimer() as timer:
            result = await some_tool_call()
        execution_time_ms = timer.elapsed_ms
    """

    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.elapsed_ms = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.elapsed_ms = int((self.end_time - self.start_time) * 1000)
        return False  # Don't suppress exceptions
