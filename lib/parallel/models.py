"""
Parallel Session Models
========================

Pydantic v2 models for session status tracking.
File-based (JSON) — no database dependency.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionState(str, Enum):
    """Lifecycle states for a parallel session."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class SessionStatus(BaseModel):
    """
    Status payload written by each parallel session.

    Written to: .parallel/<workspace>/<session_id>/status.json
    """
    session_id: str = Field(..., description="Unique session identifier")
    workspace: str = Field(..., description="Logical group (e.g., 'adrs', 'features')")
    state: SessionState = Field(default=SessionState.PENDING)
    task_description: str = Field(default="", description="What this session is doing")
    progress_pct: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="", description="Latest status message")
    errors: List[str] = Field(default_factory=list)
    started_at: Optional[str] = Field(default=None)
    last_heartbeat: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)
    output_files: List[str] = Field(default_factory=list, description="Files produced")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_terminal(self) -> bool:
        """Check if session is in a terminal state."""
        return self.state in (
            SessionState.COMPLETED,
            SessionState.FAILED,
            SessionState.TIMED_OUT,
        )

    def is_stale(self, timeout_seconds: int = 300) -> bool:
        """Check if the last heartbeat is older than timeout_seconds."""
        if not self.last_heartbeat:
            return True
        last = datetime.fromisoformat(self.last_heartbeat)
        now = datetime.now(timezone.utc)
        return (now - last).total_seconds() > timeout_seconds


class CompletionMarker(BaseModel):
    """
    Written when a session finishes (success or failure).

    Written to: .parallel/<workspace>/<session_id>/COMPLETED or FAILED
    """
    session_id: str
    state: SessionState
    timestamp: str
    output_files: List[str] = Field(default_factory=list)
    error_summary: Optional[str] = None


class WorkspaceSummary(BaseModel):
    """Aggregated status across all sessions in a workspace."""
    workspace: str
    total_sessions: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    timed_out: int = 0
    stale: int = 0
    sessions: List[SessionStatus] = Field(default_factory=list)
