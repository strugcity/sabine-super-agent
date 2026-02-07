"""
FastAPI Server - Personal Super Agent

This server exposes the LangGraph agent via HTTP endpoints.
It receives requests from the Next.js proxy (Twilio webhook handler)
and returns agent responses.

Run with:
    python lib/agent/server.py

Or with uvicorn:
    uvicorn lib.agent.server:app --host 0.0.0.0 --port 8001 --reload

Note: Railway sets PORT env var automatically. The server respects both
PORT and API_PORT environment variables for flexibility.
"""

from lib.agent.core import run_agent, run_agent_with_caching, create_agent, get_cache_metrics, reset_cache_metrics
from lib.agent.registry import get_all_tools, get_mcp_diagnostics, MCP_SERVERS
from lib.agent.gmail_handler import handle_new_email_notification
from lib.agent.memory import ingest_user_message
from lib.agent.retrieval import retrieve_context
from lib.agent.parsing import parse_file, is_supported_mime_type, SUPPORTED_MIME_TYPES
from lib.agent.scheduler import get_scheduler, SabineScheduler
from backend.services.wal import WALService
from backend.services.task_queue import TaskQueueService, Task, TaskStatus, get_task_queue_service
from backend.services.exceptions import (
    SABINEError,
    AuthorizationError,
    RepoAccessDeniedError,
    ValidationError,
    InvalidRoleError,
    DatabaseError,
    TaskNotFoundError,
    DependencyNotFoundError,
    CircularDependencyError,
    FailedDependencyError,
    AgentError,
    AgentNoToolsError,
    AgentToolFailuresError,
    OperationResult,
)
from backend.services.output_sanitization import (
    sanitize_api_response,
    sanitize_agent_output,
    sanitize_error_message,
    sanitize_for_logging,
)
import asyncio
import hmac
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends, Header, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import uvicorn

# Add project root to path BEFORE importing local modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Now import local modules after path is set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Authentication
# =============================================================================

# API key for authenticating requests to protected endpoints
# Set via AGENT_API_KEY environment variable
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")

# API key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)) -> bool:
    """
    Verify the API key from the X-API-Key header.

    Uses constant-time comparison to prevent timing attacks.

    Raises:
        HTTPException: 401 if API key is missing or invalid
    """
    if not AGENT_API_KEY:
        logger.error("AGENT_API_KEY not configured - rejecting all requests")
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: API key not set"
        )

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Include X-API-Key header."
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, AGENT_API_KEY):
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    return True

# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Personal Super Agent API",
    description="LangGraph agent powered by Claude 3.5 Sonnet with MCP integrations",
    version="1.0.0"
)

# Add CORS middleware
# Note: FastAPI CORSMiddleware doesn't support wildcard subdomains, so we list explicit origins
# For production, you can also use allow_origin_regex for pattern matching
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://dream-team-strug.vercel.app",
        "https://dream-team-strug-git-main-strugcity.vercel.app",
        "https://dream-team-strug-strugcity.vercel.app",
    ],
    allow_origin_regex=r"https://dream-team-strug.*\.vercel\.app",  # Catch preview deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Request/Response Models
# =============================================================================


class InvokeRequest(BaseModel):
    """Request body for /invoke endpoint."""
    message: str = Field(..., description="User message to send to the agent")
    user_id: str = Field(..., description="User UUID")
    session_id: Optional[str] = Field(
        None, description="Conversation session ID")
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Previous conversation history"
    )
    use_caching: bool = Field(
        False,
        description="Use direct API with prompt caching (faster, but no tool execution loops)"
    )
    role: Optional[str] = Field(
        None,
        description="Role ID for specialized persona (e.g., 'backend-architect-sabine'). "
                    "See GET /roles for available roles."
    )


class InvokeResponse(BaseModel):
    """Response from /invoke endpoint."""
    success: bool
    response: str
    user_id: str
    session_id: str
    timestamp: str
    error: Optional[str] = None
    role: Optional[str] = None
    role_title: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    tools_loaded: int
    database_connected: bool


class MemoryIngestRequest(BaseModel):
    """Request body for /memory/ingest endpoint."""
    user_id: str = Field(..., description="User UUID")
    content: str = Field(..., description="Content to ingest as memory")
    source: str = Field(
        default="api", description="Source of the memory (sms, email, api, etc.)")


class MemoryQueryRequest(BaseModel):
    """Request body for /memory/query endpoint."""
    user_id: str = Field(..., description="User UUID")
    query: str = Field(..., description="Query to search for relevant context")
    memory_threshold: Optional[float] = Field(
        default=0.6, description="Similarity threshold (0-1)")
    memory_limit: Optional[int] = Field(
        default=5, description="Max memories to retrieve")
    entity_limit: Optional[int] = Field(
        default=10, description="Max entities to retrieve")

class CancelTaskRequest(BaseModel):
    """Request body for /tasks/{task_id}/cancel endpoint."""
    reason: str = Field(..., description="Reason for cancellation (audit trail)")
    cancel_status: Optional[str] = Field(
        default=None,
        description="Explicit cancel status (cancelled_failed|cancelled_in_progress|cancelled_other)"
    )
    previous_status: Optional[str] = Field(
        default=None,
        description="Status observed by the caller at time of cancellation"
    )
    cascade: bool = Field(default=True, description="Cancel dependent queued tasks")

class RequeueTaskRequest(BaseModel):
    """Request body for /tasks/{task_id}/requeue endpoint."""
    reason: Optional[str] = Field(default=None, description="Optional audit reason")
    clear_error: bool = Field(default=True, description="Clear error fields on requeue")
    clear_result: bool = Field(default=True, description="Clear result fields on requeue")


# Role-Repository Authorization Mapping
# =============================================================================
# Each role is authorized to work in specific repositories.
# This prevents agents from accidentally (or maliciously) targeting wrong repos.

ROLE_REPO_AUTHORIZATION = {
    # Backend roles -> sabine-super-agent (Python backend, agent logic)
    "backend-architect-sabine": ["sabine-super-agent"],
    "data-ai-engineer-sabine": ["sabine-super-agent"],
    "SABINE_ARCHITECT": ["sabine-super-agent"],

    # Frontend roles -> dream-team-strug (Next.js dashboard)
    "frontend-ops-sabine": ["dream-team-strug"],

    # Cross-functional roles can access multiple repos
    "product-manager-sabine": ["sabine-super-agent", "dream-team-strug"],
    "qa-security-sabine": ["sabine-super-agent", "dream-team-strug"],
}

# Valid repository identifiers (owner/repo format)
VALID_REPOS = {
    "sabine-super-agent": {"owner": "strugcity", "repo": "sabine-super-agent"},
    "dream-team-strug": {"owner": "strugcity", "repo": "dream-team-strug"},
}


def validate_role_repo_authorization(role: str, target_repo: str) -> tuple[bool, str]:
    """
    Validate that a role is authorized to work in the target repository.

    Args:
        role: The agent role (e.g., 'backend-architect-sabine')
        target_repo: The target repository identifier (e.g., 'sabine-super-agent')

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check if repo is valid
    if target_repo not in VALID_REPOS:
        valid_repos = list(VALID_REPOS.keys())
        return False, f"Invalid target_repo '{target_repo}'. Valid options: {valid_repos}"

    # Check if role exists in authorization mapping
    if role not in ROLE_REPO_AUTHORIZATION:
        # Unknown roles default to requiring explicit authorization
        return False, f"Role '{role}' not found in authorization mapping. Add it to ROLE_REPO_AUTHORIZATION."

    # Check if role is authorized for this repo
    authorized_repos = ROLE_REPO_AUTHORIZATION[role]
    if target_repo not in authorized_repos:
        return False, (
            f"Role '{role}' is not authorized for repo '{target_repo}'. "
            f"Authorized repos for this role: {authorized_repos}"
        )

    return True, ""


class CreateTaskRequest(BaseModel):
    """Request to create a new task."""
    role: str = Field(..., description="Agent role to handle this task (e.g., 'backend-architect-sabine')")
    target_repo: str = Field(..., description="Target repository for this task (e.g., 'sabine-super-agent' or 'dream-team-strug')")
    payload: Dict = Field(default_factory=dict, description="Instructions/context for the agent")
    depends_on: List[str] = Field(default_factory=list, description="List of task IDs that must complete first")
    priority: int = Field(default=0, description="Task priority (higher = more important)")


class TaskResponse(BaseModel):
    """Response containing task information."""
    id: str
    role: str
    target_repo: Optional[str] = None
    status: str
    priority: int
    payload: Dict
    depends_on: List[str]
    result: Optional[Dict] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


# =============================================================================
# Helper Functions
# =============================================================================

def _task_requires_tool_execution(payload: dict) -> bool:
    """
    Determine if a task payload indicates that tool execution is required.

    This heuristic checks for keywords that suggest the task needs to produce
    actual artifacts (files, issues, code execution) rather than just analysis.

    Args:
        payload: The task payload dictionary

    Returns:
        True if the task likely requires tool execution, False otherwise
    """
    # Keywords that suggest tool execution is needed
    action_keywords = [
        # File/code creation keywords
        "implement", "create", "write", "build", "add", "generate",
        "deploy", "install", "configure", "setup", "update", "modify",
        # GitHub-specific
        "commit", "push", "pull request", "pr", "issue", "file",
        # Execution keywords
        "run", "execute", "test", "compile",
        # Specific tool hints
        "github_issues", "create_file", "update_file", "run_python",
    ]

    # Keywords that suggest analysis-only (no tools needed)
    analysis_keywords = [
        "analyze", "review", "assess", "evaluate", "describe",
        "explain", "summarize", "list", "identify", "recommend",
        "plan", "design", "spec", "specification", "requirements",
    ]

    # Convert payload to searchable string
    payload_text = str(payload).lower()

    # Check for action keywords
    has_action_keywords = any(kw in payload_text for kw in action_keywords)

    # Check for analysis keywords (these might not need tools)
    has_analysis_keywords = any(kw in payload_text for kw in analysis_keywords)

    # Check for explicit tool requirements in payload
    explicit_tool_requirement = (
        payload.get("requires_tools", False) or
        payload.get("deliverables") is not None or
        payload.get("target_files") is not None or
        "MUST use" in str(payload) or
        "use github_issues" in payload_text or
        "use the tool" in payload_text
    )

    # If explicit requirement, always require tools
    if explicit_tool_requirement:
        return True

    # If has action keywords but not purely analysis, likely needs tools
    if has_action_keywords and not (has_analysis_keywords and not has_action_keywords):
        return True

    return False


async def _dispatch_task(task: Task):
    """
    Dispatch callback for auto-dispatch after task completion.

    Called by TaskQueueService when a task completes.

    Uses atomic claiming to prevent race conditions - if another worker
    already claimed this task, the claim will fail and we skip execution.
    """
    service = get_task_queue_service()

    # Claim the task atomically
    # This returns the fresh task data if successful, None if already claimed
    claim_result = await service.claim_task_result(task.id)

    if claim_result.success:
        # Refresh task data from claim result for accurate started_at
        # Note: claim_task_result returns minimal data, so we use the original task
        # but could fetch fresh if needed
        logger.info(f"Handshake: Auto-dispatching Task {task.id} to {task.role}")
        await _run_task_agent(task)
    else:
        # Task already claimed by another worker - this is expected in concurrent scenarios
        logger.debug(
            f"Task {task.id} already claimed (likely by concurrent dispatch), skipping"
        )


async def _run_task_agent(task: Task):
    """
    Run the agent for a task.

    Extracts the message from payload and runs the appropriate agent.
    Sends real-time updates to Slack (threaded by task).

    Context Propagation: If this task depends on other tasks, their results
    are fetched and included as context for this agent.
    """
    from lib.agent.slack_manager import send_task_update, log_agent_event, clear_task_thread

    service = get_task_queue_service()

    # Ensure dispatch callback is set for auto-dispatch chain
    if not service._dispatch_callback:
        service.set_dispatch_callback(_dispatch_task)

    try:
        # Extract message from payload - check multiple fields for flexibility
        # Priority: message > objective > instructions > fallback to full payload
        message = (
            task.payload.get("message") or
            task.payload.get("objective") or
            task.payload.get("instructions") or
            ""
        )
        if not message:
            message = f"Execute task: {task.payload}"

        # === CONTEXT PROPAGATION ===
        # Fetch results from parent tasks (dependencies) and include as context
        parent_context = ""
        if task.depends_on and len(task.depends_on) > 0:
            logger.info(f"Task {task.id} has {len(task.depends_on)} parent dependencies - fetching context")
            parent_results = []

            for parent_id in task.depends_on:
                parent_task = await service.get_task(parent_id)
                if parent_task and parent_task.result:
                    parent_response = parent_task.result.get("response", "")
                    if parent_response:
                        parent_results.append({
                            "task_id": str(parent_id),
                            "role": parent_task.role,
                            "task_name": parent_task.payload.get("name", "Unknown Task"),
                            "output": parent_response
                        })
                        logger.info(f"  - Got context from parent task {parent_id} ({parent_task.role}): {len(parent_response)} chars")

            if parent_results:
                parent_context = "\n\n=== CONTEXT FROM PREVIOUS TASKS ===\n"
                parent_context += "The following tasks have been completed before yours. Use their outputs as context:\n\n"

                for i, result in enumerate(parent_results, 1):
                    parent_context += f"--- Task {i}: {result['task_name']} (by {result['role']}) ---\n"
                    parent_context += f"{result['output']}\n\n"

                parent_context += "=== END OF PREVIOUS TASK CONTEXT ===\n\n"
                parent_context += "Now, here is YOUR task:\n\n"

                logger.info(f"Built parent context ({len(parent_context)} chars) from {len(parent_results)} tasks")

        # === REPO CONTEXT INJECTION ===
        # Extract repo targeting from payload (injected by create_task)
        repo_context = ""
        if "_repo_context" in task.payload:
            rc = task.payload["_repo_context"]
            repo_context = f"""
=== REPOSITORY TARGETING (MANDATORY) ===
Target Repository: {rc.get('owner')}/{rc.get('repo')}
{rc.get('instruction', '')}

When using github_issues tool, you MUST use:
- owner: "{rc.get('owner')}"
- repo: "{rc.get('repo')}"

DO NOT use any other repository. This is enforced by the orchestration system.
=== END REPOSITORY TARGETING ===

"""
            logger.info(f"Injected repo context: {rc.get('owner')}/{rc.get('repo')}")

        # Combine repo context, parent context, and task message
        full_message = repo_context + parent_context + message

        logger.info(f"Task message extracted ({len(full_message)} chars, {len(parent_context)} from parents, {len(repo_context)} repo context): {message[:200]}...")

        user_id = task.payload.get("user_id", "00000000-0000-0000-0000-000000000001")

        logger.info(f"Running agent for task {task.id} (role: {task.role})")

        # Send task_started event to Slack
        await send_task_update(
            task_id=task.id,
            role=task.role,
            event_type="task_started",
            message=f"Starting task execution",
            details=message[:200] if len(message) > 200 else message
        )

        # Run the agent with the task's role (using full_message which includes parent context)
        result = await run_agent(
            user_id=user_id,
            session_id=f"task-{task.id}",
            user_message=full_message,
            role=task.role
        )

        if result.get("success"):
            # === TOOL EXECUTION VERIFICATION ===
            # Check if the agent actually used tools (especially for code/file tasks)
            tool_execution = result.get("tool_execution", {})
            tools_called = tool_execution.get("tools_called", [])
            call_count = tool_execution.get("call_count", 0)
            executions = tool_execution.get("executions", [])

            # Determine if this task requires tool execution
            # Tasks with these keywords in payload likely need actual tool usage
            task_requires_tools = _task_requires_tool_execution(task.payload)

            # Extract enhanced tool execution metrics
            success_count = tool_execution.get("success_count", 0)
            failure_count = tool_execution.get("failure_count", 0)
            artifacts_created = tool_execution.get("artifacts_created", [])
            all_succeeded = tool_execution.get("all_succeeded", False)

            # Log tool execution details
            logger.info(f"Task {task.id} tool execution summary:")
            logger.info(f"  - Tools called: {tools_called}")
            logger.info(f"  - Call count: {call_count}")
            logger.info(f"  - Success/Failure: {success_count}/{failure_count}")
            logger.info(f"  - Artifacts created: {artifacts_created}")
            logger.info(f"  - Task requires tools: {task_requires_tools}")

            # Build verification result with enhanced checks
            verification_passed = True
            verification_warnings = []

            # Check 1: Tools were called if required
            if task_requires_tools and call_count == 0:
                verification_passed = False
                verification_warnings.append(
                    "NO_TOOLS_CALLED: Task requires tool execution but no tools were called. "
                    "Agent may have only planned/described work without executing it."
                )

            # Check 2: All tool calls succeeded (no failures)
            if failure_count > 0:
                verification_passed = False
                # Get failure details
                failed_tools = [
                    e for e in executions
                    if e.get("type") == "tool_result" and e.get("status") == "error"
                ]
                failure_details = "; ".join([
                    f"{t['tool_name']}: {t.get('error', 'unknown error')}"
                    for t in failed_tools[:3]  # Limit to first 3
                ])
                verification_warnings.append(
                    f"TOOL_FAILURES: {failure_count} tool call(s) failed. Details: {failure_details}"
                )

            # Check 3: For implementation tasks, verify artifacts were created
            if task_requires_tools and call_count > 0 and success_count > 0:
                # If we expected file operations but got no artifacts, warn
                payload_text = str(task.payload).lower()
                expects_files = any(kw in payload_text for kw in [
                    "create_file", "update_file", "write file", "create issue"
                ])
                if expects_files and not artifacts_created:
                    verification_warnings.append(
                        "NO_ARTIFACTS: Task expected file/issue creation but no artifacts were confirmed. "
                        "The operation may have failed silently."
                    )

            verification_warning = " | ".join(verification_warnings) if verification_warnings else None

            # Send completion update to Slack (with verification status)
            response_preview = result.get("response", "")[:300]
            if verification_passed:
                completion_message = f"Task completed successfully ({success_count} tool calls succeeded)"
                if artifacts_created:
                    completion_message += f"\nArtifacts: {', '.join(artifacts_created[:3])}"
            else:
                completion_message = f"⚠️ Task completed with issues: {verification_warning}"

            await send_task_update(
                task_id=task.id,
                role=task.role,
                event_type="task_completed" if verification_passed else "task_completed_unverified",
                message=completion_message,
                details=f"Tools used: {tools_called or 'None'}\n\n{response_preview}"
            )

            # Store result with enhanced tool execution metadata
            task_result = {
                "response": result.get("response"),
                "tool_execution": {
                    "tools_called": tools_called,
                    "call_count": call_count,
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "artifacts_created": artifacts_created,
                    "all_succeeded": all_succeeded,
                    "verification_passed": verification_passed,
                    "verification_warnings": verification_warnings
                }
            }

            # === PERSISTENT AUDIT LOGGING WITH TASK CONTEXT ===
            # Log tool executions to database with task_id for traceability
            if executions:
                try:
                    from backend.services.audit_logging import log_tool_executions_batch
                    user_id = task.payload.get("user_id", "00000000-0000-0000-0000-000000000001")
                    logged_count = await log_tool_executions_batch(
                        executions=executions,
                        task_id=task.id,
                        user_id=user_id,
                        agent_role=task.role,
                    )
                    logger.info(f"Task {task.id}: {logged_count} tool executions logged to audit trail")
                except ImportError:
                    logger.debug("Audit logging service not available")
                except Exception as e:
                    logger.warning(f"Task {task.id} audit logging failed (non-fatal): {e}")

            await service.complete_task(
                task.id,
                result=task_result,
                auto_dispatch=True  # Trigger next tasks in chain
            )

            # Clean up Slack thread tracking to prevent memory leak (P3 fix)
            clear_task_thread(task.id)

            if verification_passed:
                logger.info(f"Task {task.id} completed successfully (verified: {success_count}/{call_count} tool calls succeeded)")
            else:
                logger.warning(f"Task {task.id} completed with VERIFICATION WARNINGS: {verification_warnings}")
        else:
            error_msg = result.get("error", "Agent execution failed")
            # Sanitize error message before storing/sending
            sanitized_error_msg = sanitize_error_message(error_msg)

            # Use fail_task_with_retry for automatic retry on transient errors
            fail_result = await service.fail_task_with_retry(
                task.id,
                error=sanitized_error_msg
            )

            # Send appropriate Slack update based on retry status
            if fail_result.success and fail_result.data.get("retry_scheduled"):
                retry_info = fail_result.data
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="task_failed",
                    message=f"Task failed (attempt {retry_info['retry_count']}/{retry_info['max_retries']}), "
                            f"will retry in {retry_info['backoff_seconds']}s: {sanitized_error_msg}"
                )
                logger.warning(
                    f"Task {task.id} failed (attempt {retry_info['retry_count']}), "
                    f"retry scheduled for {retry_info['next_retry_at']}"
                )
            else:
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="task_failed",
                    message=f"Task permanently failed: {sanitized_error_msg}"
                )
                # Clean up Slack thread tracking for permanent failures (P3 fix)
                clear_task_thread(task.id)
                logger.error(f"Task {task.id} permanently failed: {sanitize_for_logging(error_msg)}")

    except Exception as e:
        # Sanitize exception before logging and storing
        sanitized_exc = sanitize_error_message(e)
        logger.error(f"Error running agent for task {task.id}: {sanitize_for_logging(str(e))}")

        # Use fail_task_with_retry for exceptions too (often transient network/API errors)
        fail_result = await service.fail_task_with_retry(task.id, error=sanitized_exc)

        # Send error update to Slack
        try:
            if fail_result.success and fail_result.data.get("retry_scheduled"):
                retry_info = fail_result.data
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="error",
                    message=f"Exception (attempt {retry_info['retry_count']}/{retry_info['max_retries']}), "
                            f"will retry in {retry_info['backoff_seconds']}s: {sanitized_exc}"
                )
            else:
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="error",
                    message=f"Exception during task execution: {sanitized_exc}"
                )
                # Clean up Slack thread tracking for permanent failures (P3 fix)
                clear_task_thread(task.id)
        except Exception as slack_error:
            # Don't fail the main operation if Slack update fails
            logger.warning(f"Slack notification failed for task {task.id}: {slack_error}")


# Import for timestamp
from datetime import datetime, timezone



# =============================================================================
# Mount Routers
# =============================================================================
# Import routers after all models and helper functions are defined
# to avoid circular import issues

from lib.agent.routers import (
    sabine_router,
    gmail_router,
    memory_router,
    dream_team_router,
    observability_router,
)

# Mount all routers
app.include_router(sabine_router)
app.include_router(gmail_router)
app.include_router(memory_router)
app.include_router(dream_team_router)
app.include_router(observability_router)


# =============================================================================
# Startup/Shutdown Events
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info("=" * 60)
    logger.info("Personal Super Agent API Starting...")
    logger.info("=" * 60)

    # Load environment variables from project root
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    # Check required environment variables
    required_vars = ["ANTHROPIC_API_KEY",
                     "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.warning(
            f"Missing environment variables: {', '.join(missing_vars)}")
        logger.warning("Some functionality may be limited")
    else:
        logger.info("✓ All required environment variables present")

    # Preload tools
    try:
        tools = await get_all_tools()
        logger.info(f"✓ Loaded {len(tools)} tools")
        for tool in tools:
            logger.info(f"  - {tool.name}")
    except Exception as e:
        logger.error(f"Failed to load tools: {e}")

    # Start the proactive scheduler
    try:
        scheduler = get_scheduler()
        await scheduler.start()
        logger.info("✓ Proactive scheduler started")
        for job in scheduler.get_jobs():
            logger.info(f"  - {job['name']}: next run at {job['next_run']}")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

    # Start the reminder scheduler (for scheduled SMS/email reminders)
    try:
        from lib.agent.reminder_scheduler import initialize_reminder_scheduler
        reminder_scheduler = await initialize_reminder_scheduler()
        logger.info("✓ Reminder scheduler started")
        reminder_jobs = reminder_scheduler.get_reminder_jobs()
        if reminder_jobs:
            logger.info(f"  - Restored {len(reminder_jobs)} reminder jobs from database")
    except Exception as e:
        logger.error(f"Failed to start reminder scheduler: {e}")

    # Start the email poller (fallback for Gmail push notification delays)
    try:
        from lib.agent.email_poller import initialize_email_poller
        email_poller = await initialize_email_poller()
        logger.info("✓ Email poller started")
        status = email_poller.get_status()
        logger.info(f"  - Polling every {status['interval_minutes']} minutes")
    except Exception as e:
        logger.error(f"Failed to start email poller: {e}")

    # Start Slack Socket Mode (The Gantry)
    try:
        from lib.agent.slack_manager import start_socket_mode

        slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
        slack_app_token = os.getenv("SLACK_APP_TOKEN")

        if slack_bot_token and slack_app_token:
            success = await start_socket_mode()
            if success:
                logger.info("✓ The Gantry (Slack Socket Mode) connected")
            else:
                logger.warning("Failed to start Slack Socket Mode")
        else:
            logger.info("Slack tokens not configured - Gantry disabled")
    except Exception as e:
        logger.error(f"Failed to start Slack Socket Mode: {e}")

    # Get the port for logging
    api_port = os.getenv("PORT") or os.getenv("API_PORT", "8001")
    logger.info("=" * 60)
    logger.info("API Ready!")
    logger.info(f"Listening on http://0.0.0.0:{api_port}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("Personal Super Agent API shutting down...")

    # Stop Slack Socket Mode
    try:
        from lib.agent.slack_manager import stop_socket_mode
        await stop_socket_mode()
        logger.info("✓ Slack Socket Mode stopped")
    except Exception as e:
        logger.error(f"Error stopping Slack Socket Mode: {e}")

    # Gracefully shutdown the scheduler
    try:
        scheduler = get_scheduler()
        if scheduler.is_running():
            await scheduler.shutdown()
            logger.info("✓ Scheduler stopped gracefully")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")

    # Shutdown reminder scheduler
    try:
        from lib.agent.reminder_scheduler import get_reminder_scheduler
        reminder_scheduler = get_reminder_scheduler()
        if reminder_scheduler.is_running():
            await reminder_scheduler.shutdown()
            logger.info("✓ Reminder scheduler stopped gracefully")
    except Exception as e:
        logger.error(f"Error stopping reminder scheduler: {e}")

    # Shutdown email poller
    try:
        from lib.agent.email_poller import get_email_poller
        email_poller = get_email_poller()
        if email_poller.is_running():
            await email_poller.shutdown()
            logger.info("✓ Email poller stopped gracefully")
    except Exception as e:
        logger.error(f"Error stopping email poller: {e}")


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Load environment variables from project root
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    # Get configuration
    # Railway sets PORT env var, we also support API_PORT for backwards compatibility
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("API_PORT", "8001"))
    # Disable reload - it causes issues with PowerShell jobs and file locking
    # Set UVICORN_RELOAD=true to enable if needed
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"

    logger.info(f"Starting server on {host}:{port}")
    logger.info(f"Reload: {reload}")

    # Run server
    uvicorn.run(
        "lib.agent.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
