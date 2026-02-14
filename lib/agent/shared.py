"""
Shared dependencies for FastAPI routers.

This module contains:
- Authentication functions and dependencies
- Request/Response models (Pydantic schemas)
- Role-repository authorization configuration
- Constants and validation functions
"""

import os
import secrets
import logging
from typing import Dict, List, Optional

from fastapi import HTTPException, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

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
    source_channel: Optional[str] = Field(
        None,
        description="Source channel: email-work, email-personal, sms, api. "
                    "Drives domain-aware memory retrieval."
    )
    phone_number: Optional[str] = Field(
        None,
        description="Caller phone number in E.164 format (e.g., +15551234567). "
                    "Required for SMS acknowledgment delivery."
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
    role_filter: Optional[str] = Field(
        default="assistant", description="Filter memories by agent role (e.g., 'assistant', 'backend-architect-sabine')")
    domain_filter: Optional[str] = Field(
        default=None, 
        description="Filter memories by domain (e.g., 'work', 'personal', 'family', 'logistics')"
    )


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
# Role-Repository Authorization
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
