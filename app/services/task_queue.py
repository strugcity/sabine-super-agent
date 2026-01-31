"""
Task Queue Service - Phase 3: The Pulse
========================================

This module implements the Task Queue Service for multi-agent orchestration.
It manages task dependencies and triggers "Agent Handshakes" (auto-dispatch)
when dependencies are met.

Key Features:
1. Dependency tracking: Tasks can depend on other tasks
2. Priority-based scheduling: Higher priority tasks processed first
3. Auto-dispatch: When a task completes, dependent tasks are automatically triggered
4. Role-based routing: Tasks are assigned to specific agent roles

Owner: @backend-architect-sabine
PRD Reference: Project Dream Team - Phase 3 (The Pulse)
"""

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from supabase import Client, create_client

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

TASK_QUEUE_TABLE = "task_queue"


# =============================================================================
# Enums
# =============================================================================

class TaskStatus(str, Enum):
    """Valid task statuses."""
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# Models
# =============================================================================

class Task(BaseModel):
    """Represents a task in the queue."""
    id: UUID
    role: str
    status: TaskStatus
    priority: int = 0
    payload: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[UUID] = Field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    session_id: Optional[str] = None

    class Config:
        use_enum_values = True


class CreateTaskRequest(BaseModel):
    """Request to create a new task."""
    role: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[UUID] = Field(default_factory=list)
    priority: int = 0
    created_by: Optional[str] = None
    session_id: Optional[str] = None


# =============================================================================
# Task Queue Service
# =============================================================================

class TaskQueueService:
    """
    Service for managing the task queue with dependency tracking.

    Provides methods for:
    - Creating tasks with dependencies
    - Getting the next available task for a role
    - Completing/failing tasks
    - Auto-dispatching dependent tasks
    """

    def __init__(self, supabase_client: Optional[Client] = None):
        """
        Initialize the TaskQueueService.

        Args:
            supabase_client: Optional Supabase client. If not provided,
                           creates one from environment variables.
        """
        if supabase_client:
            self.client = supabase_client
        elif SUPABASE_URL and SUPABASE_SERVICE_KEY:
            self.client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        else:
            logger.warning("Supabase credentials not configured - TaskQueueService will not work")
            self.client = None

        # Callback for auto-dispatch (set by server.py)
        self._dispatch_callback = None

    def set_dispatch_callback(self, callback):
        """
        Set the callback function for auto-dispatch.

        The callback should accept a Task and trigger the appropriate agent.
        """
        self._dispatch_callback = callback

    async def create_task(
        self,
        role: str,
        payload: Dict[str, Any],
        depends_on: Optional[List[UUID]] = None,
        priority: int = 0,
        created_by: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> UUID:
        """
        Create a new task in the queue.

        Args:
            role: The agent role to handle this task (e.g., 'backend-architect-sabine')
            payload: Instructions/context for the agent (JSON)
            depends_on: List of task IDs that must complete first
            priority: Task priority (higher = more important)
            created_by: Optional identifier for who created this task
            session_id: Optional session/conversation ID

        Returns:
            The UUID of the created task

        Raises:
            Exception: If task creation fails
        """
        if not self.client:
            raise Exception("Supabase client not initialized")

        depends_on = depends_on or []

        task_data = {
            "role": role,
            "status": TaskStatus.QUEUED.value,
            "priority": priority,
            "payload": payload,
            "depends_on": [str(dep) for dep in depends_on],  # Convert UUIDs to strings
            "created_by": created_by,
            "session_id": session_id
        }

        try:
            response = self.client.table(TASK_QUEUE_TABLE).insert(task_data).execute()

            if response.data and len(response.data) > 0:
                task_id = UUID(response.data[0]["id"])
                logger.info(f"Created task {task_id} for role '{role}' with priority {priority}")
                return task_id
            else:
                raise Exception("No data returned from insert")

        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            raise

    async def get_next_task(self, role: str) -> Optional[Task]:
        """
        Get the next available task for a specific role.

        Returns the highest priority queued task where all dependencies
        are completed.

        Args:
            role: The agent role to get tasks for

        Returns:
            Task if found, None otherwise
        """
        if not self.client:
            return None

        try:
            # Use the Supabase RPC function we created in the migration
            response = self.client.rpc(
                "get_next_task_for_role",
                {"target_role": role}
            ).execute()

            if response.data and len(response.data) > 0:
                task_data = response.data[0]
                return self._parse_task(task_data)

            return None

        except Exception as e:
            logger.error(f"Error getting next task for role '{role}': {e}")
            return None

    async def get_unblocked_tasks(self) -> List[Task]:
        """
        Get all tasks that are ready for dispatch (dependencies met).

        Returns:
            List of Task objects ready for processing
        """
        if not self.client:
            return []

        try:
            response = self.client.rpc("get_unblocked_tasks").execute()

            tasks = []
            if response.data:
                for task_data in response.data:
                    tasks.append(self._parse_task(task_data))

            return tasks

        except Exception as e:
            logger.error(f"Error getting unblocked tasks: {e}")
            return []

    async def claim_task(self, task_id: UUID) -> bool:
        """
        Claim a task by setting its status to 'in_progress'.

        Args:
            task_id: The task ID to claim

        Returns:
            True if claimed successfully, False otherwise
        """
        if not self.client:
            return False

        try:
            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.IN_PROGRESS.value
            }).eq("id", str(task_id)).eq("status", TaskStatus.QUEUED.value).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Claimed task {task_id}")
                return True

            logger.warning(f"Could not claim task {task_id} - may already be claimed")
            return False

        except Exception as e:
            logger.error(f"Error claiming task {task_id}: {e}")
            return False

    async def complete_task(
        self,
        task_id: UUID,
        result: Optional[Dict[str, Any]] = None,
        auto_dispatch: bool = True
    ) -> bool:
        """
        Mark a task as completed and optionally trigger auto-dispatch.

        Args:
            task_id: The task ID to complete
            result: Optional result data from the agent
            auto_dispatch: If True, trigger dispatch of dependent tasks

        Returns:
            True if completed successfully, False otherwise
        """
        if not self.client:
            return False

        try:
            update_data = {
                "status": TaskStatus.COMPLETED.value,
                "result": result or {}
            }

            response = self.client.table(TASK_QUEUE_TABLE).update(
                update_data
            ).eq("id", str(task_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Completed task {task_id}")

                # Trigger auto-dispatch of dependent tasks
                if auto_dispatch:
                    await self._auto_dispatch()

                return True

            logger.warning(f"Could not complete task {task_id}")
            return False

        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}")
            return False

    async def fail_task(self, task_id: UUID, error: str) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: The task ID to fail
            error: Error message/description

        Returns:
            True if updated successfully, False otherwise
        """
        if not self.client:
            return False

        try:
            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.FAILED.value,
                "error": error
            }).eq("id", str(task_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Failed task {task_id}: {error}")
                return True

            logger.warning(f"Could not fail task {task_id}")
            return False

        except Exception as e:
            logger.error(f"Error failing task {task_id}: {e}")
            return False

    async def get_task(self, task_id: UUID) -> Optional[Task]:
        """
        Get a specific task by ID.

        Args:
            task_id: The task ID

        Returns:
            Task if found, None otherwise
        """
        if not self.client:
            return None

        try:
            response = self.client.table(TASK_QUEUE_TABLE).select("*").eq(
                "id", str(task_id)
            ).execute()

            if response.data and len(response.data) > 0:
                return self._parse_task(response.data[0])

            return None

        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            return None

    async def get_status_counts(self) -> Dict[str, int]:
        """
        Get count of tasks by status.

        Returns:
            Dictionary with status counts (e.g., {"queued": 2, "completed": 5})
        """
        if not self.client:
            return {}

        try:
            counts = {}
            for status in TaskStatus:
                response = self.client.table(TASK_QUEUE_TABLE).select(
                    "id", count="exact"
                ).eq("status", status.value).execute()

                counts[status.value] = response.count or 0

            return counts

        except Exception as e:
            logger.error(f"Error getting status counts: {e}")
            return {}

    async def get_tasks_by_status(
        self,
        status: TaskStatus,
        limit: int = 50
    ) -> List[Task]:
        """
        Get tasks with a specific status.

        Args:
            status: The status to filter by
            limit: Maximum number of tasks to return

        Returns:
            List of Task objects
        """
        if not self.client:
            return []

        try:
            response = self.client.table(TASK_QUEUE_TABLE).select("*").eq(
                "status", status.value
            ).order("priority", desc=True).order("created_at").limit(limit).execute()

            tasks = []
            if response.data:
                for task_data in response.data:
                    tasks.append(self._parse_task(task_data))

            return tasks

        except Exception as e:
            logger.error(f"Error getting tasks by status: {e}")
            return []

    async def _auto_dispatch(self):
        """
        Automatically dispatch tasks whose dependencies are now met.

        This is called after a task completes to trigger the "Agent Handshake".
        """
        if not self._dispatch_callback:
            logger.debug("No dispatch callback set, skipping auto-dispatch")
            return

        try:
            unblocked = await self.get_unblocked_tasks()

            for task in unblocked:
                logger.info(f"Handshake: Dispatching Task {task.id} to {task.role}")
                try:
                    await self._dispatch_callback(task)
                except Exception as e:
                    logger.error(f"Error dispatching task {task.id}: {e}")

        except Exception as e:
            logger.error(f"Error in auto-dispatch: {e}")

    def _parse_task(self, data: Dict[str, Any]) -> Task:
        """Parse task data from database into Task model."""
        # Handle depends_on which might be a list of strings
        depends_on = data.get("depends_on", [])
        if depends_on:
            depends_on = [UUID(d) if isinstance(d, str) else d for d in depends_on]

        return Task(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            role=data["role"],
            status=TaskStatus(data["status"]),
            priority=data.get("priority", 0),
            payload=data.get("payload", {}),
            depends_on=depends_on,
            result=data.get("result"),
            error=data.get("error"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            created_by=data.get("created_by"),
            session_id=data.get("session_id")
        )


# =============================================================================
# Module-level convenience functions
# =============================================================================

_service_instance: Optional[TaskQueueService] = None


def get_task_queue_service() -> TaskQueueService:
    """Get or create the global TaskQueueService instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = TaskQueueService()
    return _service_instance
