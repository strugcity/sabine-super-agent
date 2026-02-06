"""
Task Approval Phase 1 Tests

Covers:
- TaskStatus includes awaiting_approval
- Task parsing includes approval metadata fields
"""

import sys
import os
from datetime import datetime, timezone
from uuid import uuid4

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.task_queue import TaskQueueService, TaskStatus


def test_task_status_includes_awaiting_approval():
    """Ensure TaskStatus includes awaiting_approval."""
    assert TaskStatus.AWAITING_APPROVAL.value == "awaiting_approval"


def test_parse_task_includes_approval_fields():
    """Ensure approval metadata is parsed onto the Task model."""
    service = TaskQueueService(supabase_client=None)
    now = datetime.now(timezone.utc)

    task_data = {
        "id": str(uuid4()),
        "role": "backend-architect-sabine",
        "status": "awaiting_approval",
        "priority": 1,
        "payload": {"message": "needs approval"},
        "depends_on": [],
        "result": None,
        "error": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "created_by": "operator",
        "session_id": "session-123",
        "approval_required": True,
        "approval_reason": "high risk deploy",
        "approved_by": None,
        "approved_at": None,
        "retry_count": 0,
        "max_retries": 3,
        "next_retry_at": None,
        "is_retryable": True,
        "started_at": None,
        "timeout_seconds": 1800,
        "last_heartbeat_at": None,
    }

    task = service._parse_task(task_data)

    assert task.status == TaskStatus.AWAITING_APPROVAL
    assert task.approval_required is True
    assert task.approval_reason == "high risk deploy"
    assert task.approved_by is None
    assert task.approved_at is None
