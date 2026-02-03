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

# Add CORS middleware (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
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


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": "Personal Super Agent API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "POST /invoke": "Run the agent with a user message",
            "POST /invoke/cached": "Run agent with prompt caching (faster)",
            "GET /health": "Health check and system status",
            "GET /tools": "List available tools",
            "GET /cache/metrics": "Get prompt cache metrics",
            "POST /cache/reset": "Reset cache metrics"
        }
    }


@app.get("/cache/metrics")
async def cache_metrics():
    """
    Get prompt caching metrics.

    Returns statistics on cache hit rate, token savings, and latency.
    """
    return {
        "success": True,
        "metrics": get_cache_metrics()
    }


@app.post("/cache/reset")
async def cache_reset():
    """
    Reset prompt caching metrics.

    Useful for starting fresh benchmarks.
    """
    reset_cache_metrics()
    return {
        "success": True,
        "message": "Cache metrics reset"
    }


# =============================================================================
# Write-Ahead Log (WAL) Endpoints - Sabine 2.0
# =============================================================================

@app.get("/wal/stats")
async def wal_stats(_: bool = Depends(verify_api_key)):
    """
    Get Write-Ahead Log statistics.

    Returns counts by status (pending, processing, completed, failed).
    Useful for monitoring the Fast Path -> Slow Path pipeline.
    """
    try:
        wal_service = WALService()
        stats = await wal_service.get_stats()
        return {
            "success": True,
            "stats": stats,
            "description": {
                "pending": "Awaiting Slow Path processing",
                "processing": "Currently being processed by worker",
                "completed": "Successfully processed and consolidated",
                "failed": "Processing failed after max retries (requires manual review)"
            }
        }
    except Exception as e:
        logger.error(f"Error getting WAL stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get WAL stats: {str(e)}")


@app.get("/wal/pending")
async def wal_pending(limit: int = 10, _: bool = Depends(verify_api_key)):
    """
    Get pending WAL entries (for debugging/monitoring).

    Args:
        limit: Maximum number of entries to return (default: 10)

    Returns:
        List of pending WAL entries with their payloads.
    """
    try:
        wal_service = WALService()
        entries = await wal_service.get_pending_entries(limit=limit)
        return {
            "success": True,
            "count": len(entries),
            "entries": [
                {
                    "id": str(entry.id),
                    "created_at": entry.created_at.isoformat(),
                    "status": entry.status,
                    "retry_count": entry.retry_count,
                    "payload_preview": str(entry.raw_payload.get("message", ""))[:100]
                }
                for entry in entries
            ]
        }
    except Exception as e:
        logger.error(f"Error getting pending WAL entries: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get pending entries: {str(e)}")


@app.get("/wal/failed")
async def wal_failed(limit: int = 10, _: bool = Depends(verify_api_key)):
    """
    Get permanently failed WAL entries (requires manual review).

    Args:
        limit: Maximum number of entries to return (default: 10)

    Returns:
        List of failed WAL entries with error details.
    """
    try:
        wal_service = WALService()
        entries = await wal_service.get_failed_entries(limit=limit)
        return {
            "success": True,
            "count": len(entries),
            "entries": [
                {
                    "id": str(entry.id),
                    "created_at": entry.created_at.isoformat(),
                    "retry_count": entry.retry_count,
                    "last_error": entry.last_error,
                    "payload_preview": str(entry.raw_payload.get("message", ""))[:100]
                }
                for entry in entries
            ]
        }
    except Exception as e:
        logger.error(f"Error getting failed WAL entries: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get failed entries: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns system status, tool count, and database connectivity.
    """
    try:
        # Check if tools can be loaded
        tools = await get_all_tools()
        tools_count = len(tools)

        # Check database connection
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        database_connected = bool(supabase_url and supabase_key)

        return HealthResponse(
            status="healthy",
            version="1.0.0",
            tools_loaded=tools_count,
            database_connected=database_connected
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503, detail=f"Service unhealthy: {str(e)}")


@app.get("/tools")
async def list_tools():
    """
    List all available tools (local skills + MCP integrations).

    Returns tool names and descriptions.
    """
    try:
        tools = await get_all_tools()

        return {
            "success": True,
            "count": len(tools),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description
                }
                for tool in tools
            ]
        }
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list tools: {str(e)}")


@app.get("/tools/diagnostics")
async def mcp_diagnostics():
    """
    Get detailed diagnostics about MCP server loading.

    Returns per-server status, errors, and loaded tools.
    Useful for debugging MCP integration issues.
    """
    try:
        diagnostics = await get_mcp_diagnostics()
        return {
            "success": True,
            "mcp_servers_env": os.getenv("MCP_SERVERS", "not set"),
            "github_token_set": bool(os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_ACCESS_TOKEN")),
            **diagnostics
        }
    except Exception as e:
        logger.error(f"Error getting MCP diagnostics: {e}")
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@app.get("/e2b/test")
async def test_e2b_sandbox(code: str = "print('Hello from E2B!')"):
    """
    Diagnostic endpoint to test E2B sandbox directly.

    Returns detailed error information for debugging.
    Pass ?code=... to execute custom code.
    """
    import os

    e2b_key = os.getenv("E2B_API_KEY")
    if not e2b_key:
        return {
            "success": False,
            "error": "E2B_API_KEY not set",
            "key_present": False
        }

    try:
        from lib.skills.e2b_sandbox.handler import execute

        result = await execute({
            "code": code,
            "timeout": 30
        })

        return {
            "success": result.get("status") == "success",
            "key_present": True,
            "key_prefix": e2b_key[:10] + "...",
            "code_executed": code,
            "result": result
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "key_present": True,
            "key_prefix": e2b_key[:10] + "...",
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }


@app.get("/roles")
async def list_roles():
    """
    List all available roles for specialized agent personas.

    Roles are defined in docs/roles/*.md files and provide specialized
    system prompts for different agent behaviors (architect, backend, frontend, etc.).

    Returns role IDs and titles that can be passed to POST /invoke with the 'role' parameter.
    """
    try:
        from .core import get_available_roles, load_role_manifest

        role_ids = get_available_roles()
        roles = []

        for role_id in role_ids:
            manifest = load_role_manifest(role_id)
            if manifest:
                roles.append({
                    "role_id": manifest.role_id,
                    "title": manifest.title,
                    "allowed_tools": manifest.allowed_tools or "all",
                    "model_preference": manifest.model_preference
                })

        return {
            "success": True,
            "count": len(roles),
            "roles": roles,
            "usage": "Pass 'role' parameter to POST /invoke to use a specific persona"
        }
    except Exception as e:
        logger.error(f"Error listing roles: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list roles: {str(e)}")


@app.get("/repos")
async def list_repos():
    """
    List valid repositories and role-repository authorization mapping.

    This helps orchestrators understand which roles can target which repositories.
    """
    # Import after route setup to avoid circular imports
    from lib.agent.server import ROLE_REPO_AUTHORIZATION, VALID_REPOS

    return {
        "success": True,
        "valid_repos": VALID_REPOS,
        "role_authorization": ROLE_REPO_AUTHORIZATION,
        "usage": "When creating tasks via POST /tasks, include 'target_repo' matching the role's authorization"
    }


# =============================================================================
# Task Queue / Orchestration Endpoints (Phase 3: The Pulse)
# =============================================================================

# =============================================================================
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


@app.post("/tasks")
async def create_task(request: CreateTaskRequest, _: bool = Depends(verify_api_key)):
    """
    Create a new task in the orchestration queue.

    Tasks can depend on other tasks - they will stay 'queued' until
    all dependencies are 'completed'.

    IMPORTANT: The `target_repo` field is REQUIRED and must match the role's authorization.
    - Backend roles (backend-architect-sabine, data-ai-engineer-sabine) -> sabine-super-agent
    - Frontend roles (frontend-ops-sabine) -> dream-team-strug
    - Cross-functional roles (product-manager-sabine, qa-security-sabine) -> either repo
    """
    try:
        from uuid import UUID

        # === REPO AUTHORIZATION CHECK ===
        is_authorized, error_msg = validate_role_repo_authorization(
            request.role,
            request.target_repo
        )
        if not is_authorized:
            logger.warning(f"Repo authorization failed: {error_msg}")
            raise HTTPException(
                status_code=403,
                detail=f"Repository authorization failed: {error_msg}"
            )

        # Get repo details for injection into payload
        repo_info = VALID_REPOS[request.target_repo]

        service = get_task_queue_service()

        # Convert string UUIDs to UUID objects
        depends_on = [UUID(dep) for dep in request.depends_on] if request.depends_on else []

        # Inject repo targeting into payload (so agent knows which repo to use)
        enriched_payload = {
            **request.payload,
            "_repo_context": {
                "target_repo": request.target_repo,
                "owner": repo_info["owner"],
                "repo": repo_info["repo"],
                "instruction": f"IMPORTANT: All file operations for this task MUST target repo '{repo_info['owner']}/{repo_info['repo']}'"
            }
        }

        # Use create_task_with_validation to check dependencies
        result = await service.create_task_with_validation(
            role=request.role,
            payload=enriched_payload,
            depends_on=depends_on,
            priority=request.priority
        )

        if not result.success:
            # Handle specific dependency errors with appropriate status codes
            error = result.error
            if isinstance(error, DependencyNotFoundError):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": error.message,
                        "missing_dependency": error.context.get("missing_dependency_id"),
                        "category": "dependency_validation"
                    }
                )
            elif isinstance(error, CircularDependencyError):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": error.message,
                        "dependency_chain": error.context.get("dependency_chain"),
                        "category": "circular_dependency"
                    }
                )
            elif isinstance(error, FailedDependencyError):
                raise HTTPException(
                    status_code=424,  # Failed Dependency
                    detail={
                        "error": error.message,
                        "failed_dependency": error.context.get("failed_dependency_id"),
                        "failure_reason": error.context.get("failure_reason"),
                        "category": "failed_dependency"
                    }
                )
            else:
                raise HTTPException(
                    status_code=error.status_code if error else 500,
                    detail=error.message if error else "Unknown error creating task"
                )

        task_id = result.data["task_id"]
        logger.info(f"Task {task_id} created for role '{request.role}' targeting repo '{request.target_repo}'")

        return {
            "success": True,
            "task_id": str(task_id),
            "role": request.role,
            "target_repo": request.target_repo,
            "status": "queued",
            "message": f"Task created and queued for role '{request.role}' targeting '{request.target_repo}'"
        }

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@app.get("/tasks/{task_id}")
async def get_task(task_id: str, _: bool = Depends(verify_api_key)):
    """Get details of a specific task."""
    try:
        from uuid import UUID

        service = get_task_queue_service()
        task = await service.get_task(UUID(task_id))

        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        return {
            "success": True,
            "task": {
                "id": str(task.id),
                "role": task.role,
                "status": task.status,
                "priority": task.priority,
                "payload": task.payload,
                "depends_on": [str(d) for d in task.depends_on],
                "result": task.result,
                "error": task.error,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task: {str(e)}")


@app.get("/tasks/{task_id}/dependencies")
async def get_task_dependencies(task_id: str, _: bool = Depends(verify_api_key)):
    """
    Get detailed dependency status for a task.

    Returns information about each dependency including:
    - Status (queued, in_progress, completed, failed)
    - Whether it's blocking this task
    - Error message if failed
    """
    try:
        from uuid import UUID

        service = get_task_queue_service()
        result = await service.get_dependency_status(UUID(task_id))

        if not result.success:
            error = result.error
            raise HTTPException(
                status_code=error.status_code if error else 500,
                detail=error.message if error else "Failed to get dependency status"
            )

        return {
            "success": True,
            **result.data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dependencies for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task dependencies: {str(e)}")


@app.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    result: Optional[Dict] = None,
    _: bool = Depends(verify_api_key)
):
    """
    Mark a task as completed.

    This will trigger auto-dispatch of any dependent tasks.
    """
    try:
        from uuid import UUID

        service = get_task_queue_service()

        # Set up dispatch callback if not already set
        if not service._dispatch_callback:
            service.set_dispatch_callback(_dispatch_task)

        success = await service.complete_task(UUID(task_id), result=result)

        if not success:
            raise HTTPException(status_code=400, detail=f"Could not complete task {task_id}")

        return {
            "success": True,
            "task_id": task_id,
            "status": "completed",
            "message": "Task completed. Checking for dependent tasks to dispatch..."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete task: {str(e)}")


@app.post("/tasks/{task_id}/fail")
async def fail_task(
    task_id: str,
    error: str = "Unknown error",
    _: bool = Depends(verify_api_key)
):
    """Mark a task as failed."""
    try:
        from uuid import UUID

        service = get_task_queue_service()
        success = await service.fail_task(UUID(task_id), error=error)

        if not success:
            raise HTTPException(status_code=400, detail=f"Could not fail task {task_id}")

        return {
            "success": True,
            "task_id": task_id,
            "status": "failed",
            "error": error
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error failing task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fail task: {str(e)}")


@app.post("/tasks/dispatch")
async def dispatch_tasks(
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key)
):
    """
    Manually trigger dispatch of all unblocked tasks.

    Finds all queued tasks with dependencies met and dispatches
    them to their assigned agent roles.
    """
    try:
        service = get_task_queue_service()
        unblocked = await service.get_unblocked_tasks()

        if not unblocked:
            return {
                "success": True,
                "dispatched": 0,
                "message": "No unblocked tasks to dispatch"
            }

        dispatched = []
        for task in unblocked:
            # Claim the task first
            claimed = await service.claim_task(task.id)
            if claimed:
                logger.info(f"Handshake: Dispatching Task {task.id} to {task.role}")
                # Run in background to not block the response
                background_tasks.add_task(_run_task_agent, task)
                dispatched.append({
                    "task_id": str(task.id),
                    "role": task.role
                })

        return {
            "success": True,
            "dispatched": len(dispatched),
            "tasks": dispatched,
            "message": f"Dispatched {len(dispatched)} tasks"
        }

    except Exception as e:
        logger.error(f"Error dispatching tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to dispatch tasks: {str(e)}")


@app.get("/orchestration/status")
async def get_orchestration_status():
    """
    Get orchestration status - count of tasks by status.

    Returns a summary of the task queue state.
    """
    try:
        service = get_task_queue_service()
        counts = await service.get_status_counts()
        unblocked = await service.get_unblocked_tasks()

        return {
            "success": True,
            "task_counts": counts,
            "unblocked_count": len(unblocked),
            "total_tasks": sum(counts.values()),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting orchestration status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@app.get("/audit/tools")
async def get_tool_audit_logs(
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    _: bool = Depends(verify_api_key)
):
    """
    Get tool execution audit logs.

    Query persistent audit trail of all tool executions by Dream Team agents.
    Useful for debugging, compliance, and security monitoring.

    Args:
        task_id: Filter by specific task ID
        status: Filter by status ('success', 'error', 'blocked')
        limit: Maximum number of results (default 100)
    """
    try:
        from backend.services.audit_logging import (
            get_task_audit_logs,
            get_recent_failures,
            get_blocked_access_attempts,
            get_supabase_client
        )

        # If task_id provided, get logs for that task
        if task_id:
            from uuid import UUID
            logs = await get_task_audit_logs(UUID(task_id))
            return {
                "success": True,
                "task_id": task_id,
                "count": len(logs),
                "logs": logs
            }

        # If status filter, use appropriate query
        if status == "error":
            logs = await get_recent_failures(limit=limit)
            return {
                "success": True,
                "filter": "recent_failures",
                "count": len(logs),
                "logs": logs
            }

        if status == "blocked":
            logs = await get_blocked_access_attempts(limit=limit)
            return {
                "success": True,
                "filter": "blocked_access",
                "count": len(logs),
                "logs": logs
            }

        # Default: get recent logs
        client = get_supabase_client()
        if not client:
            return {
                "success": False,
                "error": "Audit logging not configured (Supabase client unavailable)"
            }

        result = client.table("tool_audit_log")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        return {
            "success": True,
            "count": len(result.data) if result.data else 0,
            "logs": result.data or []
        }

    except ImportError:
        return {
            "success": False,
            "error": "Audit logging service not available"
        }
    except Exception as e:
        logger.error(f"Error fetching audit logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch audit logs: {str(e)}")


@app.get("/audit/stats")
async def get_tool_audit_stats(
    hours: int = 24,
    _: bool = Depends(verify_api_key)
):
    """
    Get tool execution statistics for monitoring.

    Returns aggregated stats on tool usage, success rates, and performance.
    """
    try:
        from backend.services.audit_logging import get_supabase_client

        client = get_supabase_client()
        if not client:
            return {
                "success": False,
                "error": "Audit logging not configured"
            }

        # Use the database function for stats
        result = client.rpc("get_tool_execution_stats", {"p_hours": hours}).execute()

        return {
            "success": True,
            "period_hours": hours,
            "stats": result.data or []
        }

    except Exception as e:
        logger.error(f"Error fetching audit stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")


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
    """
    service = get_task_queue_service()

    # Claim the task
    claimed = await service.claim_task(task.id)
    if claimed:
        logger.info(f"Handshake: Auto-dispatching Task {task.id} to {task.role}")
        await _run_task_agent(task)


async def _run_task_agent(task: Task):
    """
    Run the agent for a task.

    Extracts the message from payload and runs the appropriate agent.
    Sends real-time updates to Slack (threaded by task).

    Context Propagation: If this task depends on other tasks, their results
    are fetched and included as context for this agent.
    """
    from lib.agent.slack_manager import send_task_update, log_agent_event

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

            if verification_passed:
                logger.info(f"Task {task.id} completed successfully (verified: {success_count}/{call_count} tool calls succeeded)")
            else:
                logger.warning(f"Task {task.id} completed with VERIFICATION WARNINGS: {verification_warnings}")
        else:
            error_msg = result.get("error", "Agent execution failed")
            # Sanitize error message before storing/sending
            sanitized_error_msg = sanitize_error_message(error_msg)

            # Send failure update to Slack
            await send_task_update(
                task_id=task.id,
                role=task.role,
                event_type="task_failed",
                message=f"Task failed: {sanitized_error_msg}"
            )

            await service.fail_task(
                task.id,
                error=sanitized_error_msg
            )
            logger.error(f"Task {task.id} failed: {sanitize_for_logging(error_msg)}")

    except Exception as e:
        # Sanitize exception before logging and storing
        sanitized_exc = sanitize_error_message(e)
        logger.error(f"Error running agent for task {task.id}: {sanitize_for_logging(str(e))}")

        # Send error update to Slack
        try:
            await send_task_update(
                task_id=task.id,
                role=task.role,
                event_type="error",
                message=f"Exception during task execution: {sanitized_exc}"
            )
        except Exception as slack_error:
            # Don't fail the main operation if Slack update fails
            logger.warning(f"Slack notification failed for task {task.id}: {slack_error}")

        await service.fail_task(task.id, error=sanitized_exc)


# Import for timestamp
from datetime import datetime, timezone


@app.post("/invoke", response_model=InvokeResponse)
async def invoke_agent(
    request: InvokeRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key)
):
    """
    Invoke the Personal Super Agent with a user message.

    This is the main endpoint that the Next.js proxy calls.
    It runs the LangGraph agent and returns the response.

    Phase 4 Integration: Context Engine
    - Retrieves relevant memories and entities before generating response
    - Ingests the user message in the background after response is sent

    Args:
        request: InvokeRequest with message, user_id, session_id, etc.
                 Set use_caching=True for faster responses with prompt caching
        background_tasks: FastAPI background tasks for async ingestion

    Returns:
        InvokeResponse with agent's reply
    """
    logger.info(
        f"Received invoke request for user {request.user_id} (caching: {request.use_caching})")
    logger.info(f"Message: {request.message}")

    try:
        # Generate session ID if not provided
        session_id = request.session_id or f"session-{request.user_id[:8]}"

        # SABINE 2.0: Write-Ahead Log (Fast Path)
        # Capture the interaction BEFORE processing for durability
        wal_entry_id = None
        try:
            from datetime import datetime, timezone
            wal_service = WALService()
            wal_payload = {
                "user_id": request.user_id,
                "message": request.message,
                "source": "api_invoke",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "metadata": {
                    "use_caching": request.use_caching,
                    "has_conversation_history": bool(request.conversation_history),
                }
            }
            wal_entry = await wal_service.create_entry(wal_payload)
            wal_entry_id = wal_entry.id
            logger.info(f"✓ WAL entry created: {wal_entry_id}")
        except Exception as wal_error:
            # WAL failure should not block the request - log and continue
            logger.warning(f"WAL write failed (non-blocking): {wal_error}")

        # PHASE 4: Retrieve context from Context Engine
        try:
            from uuid import UUID
            retrieved_context = await retrieve_context(
                user_id=UUID(request.user_id),
                query=request.message
            )
            logger.info(
                f"✓ Retrieved context ({len(retrieved_context)} chars)")

            # Prepend context to the message for the agent
            # The agent will receive both the context and the user's query
            enhanced_message = f"Context from Memory:\n{retrieved_context}\n\nUser Query: {request.message}"

        except Exception as e:
            logger.warning(
                f"Context retrieval failed, continuing without: {e}")
            enhanced_message = request.message
            retrieved_context = None

        # Run the agent (with optional caching and role-based persona)
        result = await run_agent(
            user_id=request.user_id,
            session_id=session_id,
            user_message=enhanced_message,  # Use enhanced message with context
            conversation_history=request.conversation_history,
            use_caching=request.use_caching,
            role=request.role  # Pass role for specialized persona
        )

        # PHASE 4: Ingest message as background task (after response)
        # This prevents adding latency to the user's response
        if result["success"]:
            from uuid import UUID
            background_tasks.add_task(
                ingest_user_message,
                user_id=UUID(request.user_id),
                content=request.message,  # Ingest original message, not enhanced
                source="api"
            )
            logger.info("✓ Queued message ingestion as background task")

        if result["success"]:
            # Log cache metrics if available
            cache_info = result.get("cache_metrics", {})
            if cache_info.get("status"):
                logger.info(f"Cache: {cache_info.get('status')} | "
                            f"Read: {cache_info.get('cache_read_tokens', 0)} tokens")

            # Sanitize the agent output before returning
            sanitized_response = sanitize_agent_output(
                result["response"],
                redact_credentials=True,
                redact_pii=False  # Don't redact PII in agent responses by default
            )

            logger.info(f"Agent response: {sanitize_for_logging(result['response'][:100])}...")
            return InvokeResponse(
                success=True,
                response=sanitized_response,
                user_id=request.user_id,
                session_id=session_id,
                timestamp=result["timestamp"],
                role=result.get("role"),
                role_title=result.get("role_title")
            )
        else:
            # Log detailed error information
            error_type = result.get("error_type", "unknown")
            error_category = result.get("error_category", "internal")
            http_status = result.get("http_status", 500)

            logger.error(
                f"Agent failed: {sanitize_for_logging(result.get('error'))} "
                f"[type={error_type}, category={error_category}, status={http_status}]"
            )

            # Sanitize error message before returning
            sanitized_error = sanitize_error_message(result.get("error"))

            # Return appropriate HTTP status code based on error classification
            raise HTTPException(
                status_code=http_status,
                detail={
                    "success": False,
                    "error": sanitized_error,
                    "error_type": error_type,
                    "error_category": error_category,
                    "user_id": request.user_id,
                    "session_id": session_id,
                    "timestamp": result.get("timestamp"),
                    "role": result.get("role")
                }
            )

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping
        raise
    except Exception as e:
        # Sanitize exception message before logging and returning
        sanitized_error = sanitize_error_message(e)
        logger.error(f"Exception in invoke endpoint: {sanitize_for_logging(str(e))}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke agent: {sanitized_error}"
        )


@app.post("/invoke/cached")
async def invoke_agent_cached(request: InvokeRequest, _: bool = Depends(verify_api_key)):
    """
    Invoke the agent with prompt caching enabled.

    This endpoint uses direct Anthropic API calls with prompt caching
    for faster responses (up to 2x) and lower costs (up to 90% savings).

    Best for:
    - Simple queries that don't require tool execution loops
    - Repeated queries with the same context
    - High-volume scenarios where cost matters

    Note: This mode doesn't support multi-step tool execution.
    For complex queries requiring multiple tool calls, use /invoke instead.
    """
    logger.info(f"Received CACHED invoke request for user {request.user_id}")

    try:
        session_id = request.session_id or f"session-{request.user_id[:8]}"

        result = await run_agent_with_caching(
            user_id=request.user_id,
            session_id=session_id,
            user_message=request.message,
            conversation_history=request.conversation_history
        )

        if result["success"]:
            cache_metrics = result.get("cache_metrics", {})
            logger.info(
                f"Cached response: {result.get('latency_ms', 0):.0f}ms | "
                f"Cache: {cache_metrics.get('status', 'N/A')} | "
                f"Read: {cache_metrics.get('cache_read_tokens', 0)} tokens"
            )

            # Sanitize the agent output before returning
            sanitized_response = sanitize_agent_output(
                result["response"],
                redact_credentials=True
            )

            return {
                "success": True,
                "response": sanitized_response,
                "user_id": request.user_id,
                "session_id": session_id,
                "timestamp": result["timestamp"],
                "cache_metrics": cache_metrics,
                "latency_ms": result.get("latency_ms", 0)
            }
        else:
            # Use HTTP status from error classification if available
            http_status = result.get("http_status", 500)

            # Sanitize error message
            sanitized_error = sanitize_error_message(result.get("error"))

            error_detail = {
                "success": False,
                "response": "Error processing request",
                "error": sanitized_error,
                "error_type": result.get("error_type"),
                "error_category": result.get("error_category"),
                "user_id": request.user_id,
                "session_id": session_id,
                "timestamp": result.get("timestamp")
            }

            # Raise HTTPException with proper status code
            raise HTTPException(
                status_code=http_status,
                detail=error_detail
            )

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping
        raise
    except Exception as e:
        sanitized_error = sanitize_error_message(e)
        logger.error(
            f"Exception in cached invoke endpoint: {sanitize_for_logging(str(e))}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke cached agent: {sanitized_error}"
        )


@app.post("/test")
async def test_agent(_: bool = Depends(verify_api_key)):
    """
    Test endpoint for quick verification.

    Runs a simple test query to verify the agent is working.
    """
    test_user_id = "00000000-0000-0000-0000-000000000000"
    test_session_id = "test-session"
    test_message = "Hello! Can you tell me what tools you have access to?"

    try:
        result = await run_agent(
            user_id=test_user_id,
            session_id=test_session_id,
            user_message=test_message
        )

        return {
            "success": True,
            "test_message": test_message,
            "agent_response": result.get("response", "No response"),
            "timestamp": result.get("timestamp")
        }

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# Gmail handler endpoint (simple, no agent)
class GmailHandleRequest(BaseModel):
    historyId: str


class GmailWatchRenewRequest(BaseModel):
    webhookUrl: str


@app.post("/gmail/handle")
async def handle_gmail_notification(request: GmailHandleRequest, _: bool = Depends(verify_api_key)):
    """
    Simple Gmail notification handler.

    Directly calls MCP tools without using the complex agent.
    This is more reliable for simple auto-reply functionality.
    """
    try:
        result = await handle_new_email_notification(request.historyId)
        return result

    except Exception as e:
        logger.error(f"Gmail handler failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/gmail/diagnostic")
async def gmail_diagnostic():
    """
    Diagnostic endpoint to verify Gmail credentials configuration.

    Returns partial credential info (first/last chars) for debugging.
    Note: No auth required - only shows prefixes, not full credentials.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    user_token = os.getenv("USER_REFRESH_TOKEN", "")
    agent_token = os.getenv("AGENT_REFRESH_TOKEN", "")
    auth_emails = os.getenv("GMAIL_AUTHORIZED_EMAILS", "")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    return {
        "google_client_id": {
            "set": bool(client_id),
            "prefix": client_id[:20] + "..." if len(client_id) > 20 else client_id,
            "length": len(client_id)
        },
        "google_client_secret": {
            "set": bool(client_secret),
            "prefix": client_secret[:10] + "..." if len(client_secret) > 10 else client_secret,
            "length": len(client_secret)
        },
        "user_refresh_token": {
            "set": bool(user_token),
            "prefix": user_token[:20] + "..." if len(user_token) > 20 else user_token,
            "length": len(user_token)
        },
        "agent_refresh_token": {
            "set": bool(agent_token),
            "prefix": agent_token[:20] + "..." if len(agent_token) > 20 else agent_token,
            "length": len(agent_token)
        },
        "anthropic_api_key": {
            "set": bool(anthropic_key),
            "prefix": anthropic_key[:15] + "..." if len(anthropic_key) > 15 else anthropic_key,
            "length": len(anthropic_key)
        },
        "gmail_authorized_emails": auth_emails,
        "assistant_email": os.getenv("ASSISTANT_EMAIL", ""),
        "agent_email": os.getenv("AGENT_EMAIL", ""),
        "user_google_email": os.getenv("USER_GOOGLE_EMAIL", "")
    }


@app.get("/gmail/debug-inbox")
async def gmail_debug_inbox(_: bool = Depends(verify_api_key)):
    """
    Debug endpoint to see what emails Railway can see in the agent's inbox.
    """
    import json
    from lib.agent.mcp_client import MCPClient
    from lib.agent.gmail_handler import get_config, get_access_token, load_processed_ids

    config = get_config()
    processed_ids = load_processed_ids()

    try:
        async with MCPClient(
            command="/app/deploy/start-mcp-server.sh",
            args=[]
        ) as mcp:
            # Get agent access token
            agent_access_token = await get_access_token(mcp, config, "agent")
            if not agent_access_token:
                return {"error": "Failed to get agent access token"}

            # Get recent emails
            search_result = await mcp.call_tool("gmail_get_recent_emails", {
                "google_access_token": agent_access_token,
                "max_results": 5,
                "unread_only": True
            })

            result_data = json.loads(search_result)
            if isinstance(result_data, dict) and "emails" in result_data:
                emails = result_data["emails"]
            else:
                emails = result_data if isinstance(result_data, list) else []

            # Summarize emails
            email_summary = []
            for email in emails:
                email_id = email.get("id", "")
                email_summary.append({
                    "id": email_id,
                    "from": email.get("from", ""),
                    "to": email.get("to", ""),
                    "subject": email.get("subject", ""),
                    "already_processed": email_id in processed_ids
                })

            return {
                "success": True,
                "authorized_emails": config["authorized_emails"],
                "processed_ids_count": len(processed_ids),
                "processed_ids_sample": list(processed_ids)[:5],
                "emails_found": len(emails),
                "emails": email_summary
            }

    except Exception as e:
        return {"error": str(e)}


@app.post("/gmail/renew-watch")
async def renew_gmail_watch(request: GmailWatchRenewRequest, _: bool = Depends(verify_api_key)):
    """
    Renew Gmail push notification watch.

    Called by Vercel cron every 6 days to keep the watch active.
    Gmail watches expire after 7 days.
    """
    try:
        import subprocess
        import sys

        # Run the setup script
        script_path = project_root / "scripts" / "setup_gmail_watch.py"
        result = subprocess.run(
            [sys.executable, str(script_path),
             "--webhook-url", request.webhookUrl],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            logger.info(f"Gmail watch renewed successfully")
            return {
                "success": True,
                "message": "Gmail watch renewed",
                "output": result.stdout
            }
        else:
            logger.error(f"Gmail watch renewal failed: {result.stderr}")
            return {
                "success": False,
                "error": result.stderr or "Unknown error"
            }

    except subprocess.TimeoutExpired:
        logger.error("Gmail watch renewal timed out")
        return {
            "success": False,
            "error": "Timeout"
        }
    except Exception as e:
        logger.error(f"Gmail watch renewal failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Context Engine Endpoints (Phase 4)
# =============================================================================

@app.post("/memory/ingest")
async def memory_ingest_endpoint(
    request: MemoryIngestRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Manually trigger memory ingestion (for testing/dashboard).

    This endpoint allows explicit ingestion of content into the Context Engine.
    Normally ingestion happens automatically in the background after /invoke.

    Args:
        request: MemoryIngestRequest with user_id, content, and optional source

    Returns:
        {
            "success": bool,
            "message": str,
            "entities_created": int,
            "entities_updated": int,
            "memory_id": str (UUID)
        }
    """
    logger.info(f"Manual memory ingestion for user {request.user_id}")
    logger.info(
        f"Content length: {len(request.content)} chars, Source: {request.source}")

    try:
        from uuid import UUID
        result = await ingest_user_message(
            user_id=UUID(request.user_id),
            content=request.content,
            source=request.source or "manual"
        )

        logger.info(f"✓ Ingestion complete: {result.get('entities_created', 0)} entities created, "
                    f"{result.get('entities_updated', 0)} updated")

        return {
            "success": True,
            "message": "Memory ingestion completed successfully",
            "entities_created": result.get("entities_created", 0),
            "entities_updated": result.get("entities_updated", 0),
            "memory_id": str(result.get("memory_id")) if result.get("memory_id") else None
        }

    except Exception as e:
        logger.error(f"Memory ingestion failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Memory ingestion failed: {str(e)}"
        )


@app.post("/memory/query")
async def memory_query_endpoint(
    request: MemoryQueryRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Debug endpoint to test context retrieval.

    Returns the formatted context string that would be injected
    into the agent's prompt for a given query.

    Args:
        request: MemoryQueryRequest with user_id, query, and optional thresholds/limits

    Returns:
        {
            "success": bool,
            "context": str (formatted context),
            "context_length": int (characters),
            "metadata": {
                "memories_found": int,
                "entities_found": int,
                "query": str
            }
        }
    """
    logger.info(f"Memory query for user {request.user_id}")
    logger.info(f"Query: {request.query}")

    try:
        from uuid import UUID
        context = await retrieve_context(
            user_id=UUID(request.user_id),
            query=request.query,
            memory_threshold=request.memory_threshold or 0.7,
            memory_limit=request.memory_limit or 10,
            entity_limit=request.entity_limit or 20
        )

        # Parse the context to extract metadata
        memories_section = context.split("[RELATED ENTITIES]")[
            0] if "[RELATED ENTITIES]" in context else context
        entities_section = context.split("[RELATED ENTITIES]")[
            1] if "[RELATED ENTITIES]" in context else ""

        memories_count = memories_section.count(
            "Memory:") if "Memory:" in memories_section else 0
        entities_count = entities_section.count("•") if entities_section else 0

        logger.info(
            f"✓ Retrieved {memories_count} memories, {entities_count} entities")

        return {
            "success": True,
            "context": context,
            "context_length": len(context),
            "metadata": {
                "memories_found": memories_count,
                "entities_found": entities_count,
                "query": request.query
            }
        }

    except Exception as e:
        logger.error(f"Memory query failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Memory query failed: {str(e)}"
        )


@app.post("/memory/upload")
async def memory_upload_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    source: str = Form(default="file_upload"),
    _: bool = Depends(verify_api_key)
):
    """
    Upload a file for knowledge ingestion.

    This endpoint accepts files (PDF, CSV, Excel, Images), parses them to
    extract text content, saves to Supabase Storage, and ingests the
    extracted text into the Context Engine as a background task.

    Supported file types:
    - PDF: Text extraction with pypdf
    - CSV: Row summaries with pandas
    - Excel (.xlsx, .xls): Sheet/row summaries with pandas
    - Images (JPEG, PNG, GIF, WebP): Claude vision description
    - Text/JSON: Direct content extraction

    Args:
        file: The uploaded file (multipart form data)
        user_id: User UUID (form field)
        source: Source identifier (form field, default: "file_upload")

    Returns:
        {
            "success": bool,
            "message": str,
            "file_name": str,
            "file_size": int,
            "mime_type": str,
            "storage_path": str (Supabase Storage path),
            "extracted_text_preview": str (first 500 chars),
            "ingestion_status": "queued" | "started"
        }
    """
    logger.info(f"📤 File upload received: {file.filename}")
    logger.info(f"  MIME type: {file.content_type}")
    logger.info(f"  User ID: {user_id}")

    try:
        # Validate MIME type
        mime_type = file.content_type or "application/octet-stream"
        if not is_supported_mime_type(mime_type):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {mime_type}. "
                       f"Supported types: {list(SUPPORTED_MIME_TYPES.keys())}"
            )

        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        filename = file.filename or "unknown_file"

        logger.info(f"  File size: {file_size:,} bytes")

        # Validate file size (50MB max)
        max_size = 52428800  # 50MB
        if file_size > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {file_size:,} bytes. Maximum: {max_size:,} bytes"
            )

        # Parse file to extract text
        logger.info(f"🔄 Parsing file...")
        extracted_text, parse_metadata = await parse_file(
            file_content=file_content,
            mime_type=mime_type,
            filename=filename
        )

        logger.info(f"✓ Extracted {len(extracted_text):,} characters")

        # Save to Supabase Storage
        storage_path = None
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)

                # Generate unique storage path
                from datetime import datetime
                import uuid
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
                storage_path = f"{user_id}/{timestamp}_{unique_id}_{safe_filename}"

                # Upload to storage bucket
                storage_response = supabase.storage.from_("knowledge_base").upload(
                    path=storage_path,
                    file=file_content,
                    file_options={"content-type": mime_type}
                )

                logger.info(f"✓ Saved to storage: {storage_path}")

                # Track in knowledge_files table
                supabase.table("knowledge_files").insert({
                    "file_name": filename,
                    "file_path": storage_path,
                    "file_size": file_size,
                    "mime_type": mime_type,
                    "status": "processing",
                    "extracted_text": extracted_text,
                    "extracted_at": datetime.utcnow().isoformat(),
                    "metadata": parse_metadata
                }).execute()

                logger.info(f"✓ Tracked in knowledge_files table")

        except Exception as storage_error:
            logger.warning(f"Storage upload failed (continuing with ingestion): {storage_error}")
            storage_path = None

        # Queue memory ingestion as background task
        from uuid import UUID as UUIDType

        async def ingest_file_content():
            """Background task to ingest extracted file content."""
            try:
                result = await ingest_user_message(
                    user_id=UUIDType(user_id),
                    content=f"[File: {filename}]\n\n{extracted_text}",
                    source=source
                )
                logger.info(f"✓ File content ingested: {result.get('memory_id')}")

                # Update knowledge_files status if we have storage_path
                if storage_path:
                    try:
                        supabase_url = os.getenv("SUPABASE_URL")
                        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                        if supabase_url and supabase_key:
                            supabase = create_client(supabase_url, supabase_key)
                            supabase.table("knowledge_files").update({
                                "status": "completed",
                                "memory_id": str(result.get("memory_id")) if result.get("memory_id") else None
                            }).eq("file_path", storage_path).execute()
                    except Exception as update_error:
                        logger.warning(f"Failed to update knowledge_files status: {update_error}")

            except Exception as ingest_error:
                logger.error(f"File ingestion failed: {ingest_error}")
                # Update status to failed
                if storage_path:
                    try:
                        supabase_url = os.getenv("SUPABASE_URL")
                        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                        if supabase_url and supabase_key:
                            supabase = create_client(supabase_url, supabase_key)
                            supabase.table("knowledge_files").update({
                                "status": "failed",
                                "error_message": str(ingest_error)
                            }).eq("file_path", storage_path).execute()
                    except Exception:
                        pass

        background_tasks.add_task(ingest_file_content)
        logger.info("✓ Queued file content for background ingestion")

        return {
            "success": True,
            "message": "File uploaded and queued for ingestion",
            "file_name": filename,
            "file_size": file_size,
            "mime_type": mime_type,
            "storage_path": storage_path,
            "extracted_text_preview": extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text,
            "extracted_text_length": len(extracted_text),
            "parse_metadata": parse_metadata,
            "ingestion_status": "queued"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"File upload failed: {str(e)}"
        )


@app.get("/memory/upload/supported-types")
async def get_supported_upload_types():
    """
    Get list of supported file types for upload.

    Returns the MIME types and their categories for the file upload endpoint.
    """
    return {
        "success": True,
        "supported_types": SUPPORTED_MIME_TYPES,
        "max_file_size_bytes": 52428800,  # 50MB
        "max_file_size_human": "50 MB"
    }


# =============================================================================
# Scheduler Endpoints (Phase 7 - Proactive Agent)
# =============================================================================

class TriggerBriefingRequest(BaseModel):
    """Request body for manual briefing trigger."""
    user_name: str = Field(default="Paul", description="Name to use in greeting")
    phone_number: Optional[str] = Field(
        default=None, description="Override phone number (uses USER_PHONE env var if not provided)")
    skip_sms: bool = Field(
        default=False, description="Skip sending SMS (just generate briefing)")


@app.get("/scheduler/status")
async def scheduler_status():
    """
    Get scheduler status and upcoming jobs.

    Returns current scheduler state and next run times for all jobs.
    """
    try:
        scheduler = get_scheduler()
        return {
            "success": True,
            "running": scheduler.is_running(),
            "jobs": scheduler.get_jobs()
        }
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        return {
            "success": False,
            "running": False,
            "error": str(e)
        }


@app.post("/scheduler/trigger-briefing")
async def trigger_briefing(
    request: TriggerBriefingRequest = TriggerBriefingRequest(),
    _: bool = Depends(verify_api_key)
):
    """
    Manually trigger the morning briefing (for testing).

    This endpoint allows immediate execution of the morning briefing job
    outside of its scheduled time. Useful for testing and debugging.

    Args:
        request: Optional configuration for the briefing

    Returns:
        {
            "success": bool,
            "status": "success" | "failed",
            "briefing": str (the generated briefing text),
            "sms_sent": bool,
            "context_summary": dict (counts of items found)
        }
    """
    logger.info("Manual briefing trigger received")

    try:
        scheduler = get_scheduler()

        # If skip_sms is True, pass None for phone to prevent sending
        phone = None if request.skip_sms else request.phone_number

        result = await scheduler.trigger_briefing_now(
            user_name=request.user_name,
            phone_number=phone
        )

        return {
            "success": result["status"] == "success",
            **result
        }

    except Exception as e:
        logger.error(f"Manual briefing trigger failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Briefing trigger failed: {str(e)}"
        )


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
