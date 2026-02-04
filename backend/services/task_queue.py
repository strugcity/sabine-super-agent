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
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from supabase import Client, create_client

from backend.services.exceptions import (
    DatabaseError,
    TaskNotFoundError,
    TaskClaimError,
    TaskQueueError,
    TaskDependencyError,
    DependencyNotFoundError,
    CircularDependencyError,
    FailedDependencyError,
    MissingCredentialsError,
    OperationResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

TASK_QUEUE_TABLE = "task_queue"

# Retry configuration
DEFAULT_MAX_RETRIES = 3
# Exponential backoff intervals (in seconds): 30s, 5m, 15m
BACKOFF_INTERVALS = [30, 300, 900]


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
    # Retry mechanism fields
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None
    is_retryable: bool = True
    # Timeout detection fields
    started_at: Optional[datetime] = None
    timeout_seconds: int = 1800  # Default: 30 minutes
    last_heartbeat_at: Optional[datetime] = None

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
    max_retries: int = 3  # Configurable max retries (default: 3)
    timeout_seconds: int = 1800  # Configurable timeout (default: 30 minutes)


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
        session_id: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: int = 1800
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
            max_retries: Maximum retry attempts on failure (default: 3)
            timeout_seconds: Max execution time before task is stuck (default: 30 min)

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
            "session_id": session_id,
            "max_retries": max_retries,
            "retry_count": 0,
            "is_retryable": True,
            "timeout_seconds": timeout_seconds
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

        Note: For better error handling, use claim_task_result() instead.
        """
        result = await self.claim_task_result(task_id)
        return result.success

    async def claim_task_result(self, task_id: UUID) -> OperationResult:
        """
        Claim a task with structured error handling.

        This method distinguishes between:
        - Task already claimed (409 Conflict)
        - Database error (500)
        - Client not initialized (configuration error)

        Args:
            task_id: The task ID to claim

        Returns:
            OperationResult indicating success or specific failure reason
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Set started_at timestamp when claiming task for timeout detection
            started_at = datetime.now(timezone.utc)

            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.IN_PROGRESS.value,
                "started_at": started_at.isoformat(),
                "last_heartbeat_at": started_at.isoformat()
            }).eq("id", str(task_id)).eq("status", TaskStatus.QUEUED.value).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Claimed task {task_id} at {started_at.isoformat()}")
                return OperationResult.ok({
                    "task_id": str(task_id),
                    "started_at": started_at.isoformat()
                })

            # Task couldn't be claimed - may be already claimed or doesn't exist
            logger.warning(f"Could not claim task {task_id} - may already be claimed")
            return OperationResult.fail(
                TaskClaimError(
                    task_id=str(task_id),
                    reason="Task may already be claimed or does not exist in queued status"
                )
            )

        except Exception as e:
            logger.error(f"Error claiming task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to claim task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    # =========================================================================
    # Atomic Claim Methods (Race Condition Prevention)
    # =========================================================================

    async def claim_next_task_atomic(
        self,
        role: Optional[str] = None,
        validate_deps: bool = True
    ) -> Optional[Task]:
        """
        Atomically claim and return the next available task.

        This method prevents race conditions by using FOR UPDATE SKIP LOCKED
        at the database level. Only one worker can claim each task, even if
        multiple workers are calling this method simultaneously.

        Args:
            role: Optional role filter. If None, claims any available task.
            validate_deps: If True, validate dependencies before returning.
                          Tasks with failed dependencies will be auto-failed
                          and the method will try to claim another task.

        Returns:
            The claimed Task object, or None if no tasks available.
        """
        if not self.client:
            return None

        max_attempts = 5  # Limit attempts to avoid infinite loops
        attempts = 0

        while attempts < max_attempts:
            attempts += 1

            try:
                if role:
                    # Claim next task for specific role
                    response = self.client.rpc(
                        "claim_next_task_for_role",
                        {"target_role": role}
                    ).execute()
                else:
                    # Claim next unblocked task (any role)
                    response = self.client.rpc(
                        "claim_next_unblocked_task",
                        {}
                    ).execute()

                if not response.data or len(response.data) == 0:
                    return None  # No more tasks available

                task = self._parse_task(response.data[0])

                # Validate dependencies before returning
                if validate_deps:
                    is_valid = await self.validate_dependencies_before_dispatch(task)
                    if not is_valid:
                        # Task was auto-failed due to failed dependency
                        # Try to claim another task
                        logger.info(
                            f"Task {task.id} auto-failed (failed dependency), "
                            f"attempting to claim another task"
                        )
                        continue

                logger.info(
                    f"Atomically claimed task {task.id} for role '{task.role}' "
                    f"(priority: {task.priority})"
                )
                return task

            except Exception as e:
                logger.error(f"Error in atomic claim: {e}")
                return None

        logger.warning(f"Max claim attempts ({max_attempts}) reached, no valid tasks")
        return None

    async def claim_unblocked_tasks_atomic(
        self,
        max_tasks: int = 5,
        validate_deps: bool = True
    ) -> List[Task]:
        """
        Atomically claim multiple unblocked tasks.

        This method prevents race conditions by using FOR UPDATE SKIP LOCKED
        at the database level. Each task is individually locked, so multiple
        workers calling this simultaneously will each get different tasks.

        Args:
            max_tasks: Maximum number of tasks to claim (default: 5)
            validate_deps: If True, validate dependencies before returning.
                          Tasks with failed dependencies will be auto-failed
                          and excluded from the returned list.

        Returns:
            List of claimed Task objects (may be empty if none available)
        """
        if not self.client:
            return []

        try:
            # Claim more tasks than requested to account for potential auto-fails
            claim_count = max_tasks + 5 if validate_deps else max_tasks

            response = self.client.rpc(
                "claim_unblocked_tasks",
                {"max_tasks": claim_count}
            ).execute()

            if not response.data:
                return []

            claimed_tasks = [self._parse_task(row) for row in response.data]

            if not validate_deps:
                # Skip validation, return all claimed tasks
                if claimed_tasks:
                    logger.info(
                        f"Atomically claimed {len(claimed_tasks)} tasks: "
                        f"{[str(t.id)[:8] for t in claimed_tasks]}"
                    )
                return claimed_tasks[:max_tasks]

            # Validate each task's dependencies
            valid_tasks = []
            auto_failed_count = 0

            for task in claimed_tasks:
                is_valid = await self.validate_dependencies_before_dispatch(task)
                if is_valid:
                    valid_tasks.append(task)
                    if len(valid_tasks) >= max_tasks:
                        break
                else:
                    auto_failed_count += 1

            if auto_failed_count > 0:
                logger.info(
                    f"Auto-failed {auto_failed_count} tasks with failed dependencies "
                    f"during bulk claim"
                )

            if valid_tasks:
                logger.info(
                    f"Atomically claimed {len(valid_tasks)} valid tasks: "
                    f"{[str(t.id)[:8] for t in valid_tasks]}"
                )

            return valid_tasks

        except Exception as e:
            logger.error(f"Error in atomic bulk claim: {e}")
            return []

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

        Note: For better error handling, use complete_task_result() instead.
        """
        op_result = await self.complete_task_result(task_id, result, auto_dispatch)
        return op_result.success

    async def complete_task_result(
        self,
        task_id: UUID,
        result: Optional[Dict[str, Any]] = None,
        auto_dispatch: bool = True
    ) -> OperationResult:
        """
        Mark a task as completed with structured error handling.

        Args:
            task_id: The task ID to complete
            result: Optional result data from the agent
            auto_dispatch: If True, trigger dispatch of dependent tasks

        Returns:
            OperationResult indicating success or specific failure reason
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Validate task exists and is in correct state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Only IN_PROGRESS tasks can be completed
            if task.status == TaskStatus.COMPLETED:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Task already completed",
                        operation="complete",
                        status_code=409  # Conflict
                    )
                )

            if task.status != TaskStatus.IN_PROGRESS:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot complete task: status is '{task.status}', expected 'in_progress'",
                        operation="complete",
                        status_code=409  # Conflict
                    )
                )

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

                return OperationResult.ok({"task_id": str(task_id)})

            logger.warning(f"Could not complete task {task_id}")
            return OperationResult.fail(
                TaskNotFoundError(task_id=str(task_id))
            )

        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to complete task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def fail_task(self, task_id: UUID, error: str, cascade: bool = True) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: The task ID to fail
            error: Error message/description
            cascade: If True, propagate failure to dependent tasks (default: True)

        Returns:
            True if updated successfully, False otherwise

        Note: For better error handling, use fail_task_result() instead.
        """
        op_result = await self.fail_task_result(task_id, error, cascade=cascade)
        return op_result.success

    async def get_dependent_tasks(self, task_id: UUID) -> List[Task]:
        """
        Find all tasks that depend on the given task.

        This searches for tasks where the given task_id is in their depends_on array.
        Only returns tasks that are still QUEUED (not already completed/failed/in_progress).

        Args:
            task_id: The task ID to find dependents for

        Returns:
            List of Task objects that depend on this task
        """
        if not self.client:
            return []

        try:
            # Use PostgreSQL array contains operator via Supabase
            # This finds rows where depends_on array contains task_id
            response = self.client.table(TASK_QUEUE_TABLE).select("*").contains(
                "depends_on", [str(task_id)]
            ).eq("status", TaskStatus.QUEUED.value).execute()

            if response.data:
                return [self._parse_task(row) for row in response.data]
            return []

        except Exception as e:
            logger.error(f"Error finding dependent tasks for {task_id}: {e}")
            return []

    async def fail_task_result(
        self,
        task_id: UUID,
        error: str,
        cascade: bool = True,
        _cascade_source: Optional[UUID] = None,
        force: bool = False
    ) -> OperationResult:
        """
        Mark a task as failed with structured error handling.

        When cascade=True (default), this also fails all dependent tasks that are
        still in QUEUED state, preventing orphaned dependency chains.

        Args:
            task_id: The task ID to fail
            error: Error message/description
            cascade: If True, propagate failure to dependent tasks (default: True)
            _cascade_source: Internal use - the original failed task ID for cascade messages
            force: If True, allow failing already-terminal tasks (for admin recovery)

        Returns:
            OperationResult indicating success or specific failure reason.
            The result data includes 'cascaded_failures' count if cascade occurred.
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Validate task exists and check current state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Check if task is already in a terminal state
            if not force and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot fail task: already in terminal state '{task.status}'",
                        operation="fail",
                        status_code=409  # Conflict
                    )
                )

            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.FAILED.value,
                "error": error
            }).eq("id", str(task_id)).execute()

            if not (response.data and len(response.data) > 0):
                logger.warning(f"Could not fail task {task_id}")
                return OperationResult.fail(
                    TaskNotFoundError(task_id=str(task_id))
                )

            logger.info(f"Failed task {task_id}: {error}")

            # Cascade failure to dependent tasks
            cascaded_count = 0
            cascaded_task_ids = []

            if cascade:
                dependent_tasks = await self.get_dependent_tasks(task_id)

                if dependent_tasks:
                    # Use the original source for the error message, or this task if it's the origin
                    source_id = _cascade_source or task_id
                    logger.info(
                        f"Cascading failure from task {task_id} to {len(dependent_tasks)} dependent tasks"
                    )

                    for dep_task in dependent_tasks:
                        cascade_error = (
                            f"Blocked by failed dependency: Task {source_id} failed with error: "
                            f"{error[:200]}{'...' if len(error) > 200 else ''}"
                        )

                        # Recursively fail dependent tasks (they may have their own dependents)
                        cascade_result = await self.fail_task_result(
                            dep_task.id,
                            error=cascade_error,
                            cascade=True,
                            _cascade_source=source_id
                        )

                        if cascade_result.success:
                            cascaded_count += 1
                            cascaded_task_ids.append(str(dep_task.id))
                            # Add any nested cascade counts
                            cascaded_count += cascade_result.data.get("cascaded_failures", 0)
                            cascaded_task_ids.extend(
                                cascade_result.data.get("cascaded_task_ids", [])
                            )

                    if cascaded_count > 0:
                        logger.warning(
                            f"Cascade failure: {cascaded_count} dependent tasks failed due to {task_id}"
                        )

            # Send Slack alert for cascade failures (only at the top level, not recursively)
            if cascade and cascaded_count > 0 and _cascade_source is None:
                try:
                    from lib.agent.slack_manager import send_cascade_failure_alert

                    # Get the role from the failed task for the alert
                    task_role = "unknown"
                    if response.data and len(response.data) > 0:
                        task_role = response.data[0].get("role", "unknown")

                    await send_cascade_failure_alert(
                        source_task_id=task_id,
                        source_role=task_role,
                        source_error=error,
                        cascaded_task_ids=cascaded_task_ids,
                        cascaded_count=cascaded_count
                    )
                except Exception as slack_error:
                    # Don't fail the operation if Slack notification fails
                    logger.warning(f"Failed to send cascade failure Slack alert: {slack_error}")

            return OperationResult.ok({
                "task_id": str(task_id),
                "error": error,
                "cascaded_failures": cascaded_count,
                "cascaded_task_ids": cascaded_task_ids
            })

        except Exception as e:
            logger.error(f"Error failing task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to mark task as failed: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def get_task(self, task_id: UUID) -> Optional[Task]:
        """
        Get a specific task by ID.

        Args:
            task_id: The task ID

        Returns:
            Task if found, None otherwise

        Note: For better error handling, use get_task_result() instead.
        """
        result = await self.get_task_result(task_id)
        return result.data.get("task") if result.success else None

    async def get_task_result(self, task_id: UUID) -> OperationResult:
        """
        Get a specific task by ID with structured error handling.

        This method distinguishes between:
        - Task not found (404)
        - Database error (500)
        - Client not initialized (configuration error)

        Args:
            task_id: The task ID

        Returns:
            OperationResult with task in data["task"] if successful
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            response = self.client.table(TASK_QUEUE_TABLE).select("*").eq(
                "id", str(task_id)
            ).execute()

            if response.data and len(response.data) > 0:
                task = self._parse_task(response.data[0])
                return OperationResult.ok({"task": task})

            # Task not found - distinct from database error
            return OperationResult.fail(
                TaskNotFoundError(task_id=str(task_id))
            )

        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to retrieve task: {str(e)}",
                    operation="select",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

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

        Note: Uses get_unblocked_tasks() to find candidates, then the dispatch
        callback is responsible for atomic claiming. If multiple auto-dispatch
        calls happen simultaneously, the atomic claim in the callback ensures
        each task is only executed once.
        """
        if not self._dispatch_callback:
            logger.debug("No dispatch callback set, skipping auto-dispatch")
            return

        try:
            # Get unblocked tasks (candidates for dispatch)
            # The dispatch callback will handle atomic claiming
            unblocked = await self.get_unblocked_tasks()

            for task in unblocked:
                logger.info(f"Handshake: Attempting to dispatch Task {task.id} to {task.role}")
                try:
                    # The callback is responsible for atomic claiming
                    # If task is already claimed, callback should handle gracefully
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
            session_id=data.get("session_id"),
            # Retry mechanism fields
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            next_retry_at=data.get("next_retry_at"),
            is_retryable=data.get("is_retryable", True),
            # Timeout detection fields
            started_at=data.get("started_at"),
            timeout_seconds=data.get("timeout_seconds", 1800),
            last_heartbeat_at=data.get("last_heartbeat_at")
        )

    # =========================================================================
    # Dependency Validation
    # =========================================================================

    async def _fetch_dependency_tree(
        self,
        root_task_ids: List[UUID],
        max_depth: int = 100
    ) -> Dict[str, Dict]:
        """
        Fetch the complete dependency tree in a single query.

        Uses a PostgreSQL recursive CTE to traverse all dependencies from
        the root tasks. This eliminates the N+1 query pattern that would
        occur when fetching dependencies one level at a time.

        Args:
            root_task_ids: List of task IDs to start traversal from
            max_depth: Maximum recursion depth (default: 100)

        Returns:
            Dict mapping task_id (string) to task data dict containing:
            - id, status, depends_on, error, depth
        """
        if not root_task_ids or not self.client:
            return {}

        try:
            # Convert UUIDs to strings for the RPC call
            root_ids_str = [str(tid) for tid in root_task_ids]

            response = self.client.rpc(
                "get_dependency_tree",
                {
                    "start_task_ids": root_ids_str,
                    "max_depth": max_depth
                }
            ).execute()

            if response.data:
                # Build dict mapping task_id -> task_data
                return {
                    row["task_id"]: {
                        "id": row["task_id"],
                        "status": row["status"],
                        "depends_on": row["depends_on"],
                        "error": row["error"],
                        "depth": row["depth"]
                    }
                    for row in response.data
                }

            return {}

        except Exception as e:
            logger.warning(
                f"RPC get_dependency_tree failed, falling back to manual fetch: {e}"
            )
            # Fallback to the original approach if RPC not available
            return await self._fetch_dependency_tree_fallback(root_task_ids, max_depth)

    async def _fetch_dependency_tree_fallback(
        self,
        root_task_ids: List[UUID],
        max_depth: int = 100
    ) -> Dict[str, Dict]:
        """
        Fallback method to fetch dependency tree without RPC.

        This uses the original N+1 approach but is only used when the
        database RPC function is not available.
        """
        if not root_task_ids or not self.client:
            return {}

        found_tasks: Dict[str, Dict] = {}
        to_fetch = [str(tid) for tid in root_task_ids]
        depth = 0

        while to_fetch and depth < max_depth:
            # Fetch current batch
            response = self.client.table(TASK_QUEUE_TABLE).select(
                "id", "status", "depends_on", "error"
            ).in_("id", to_fetch).execute()

            if not response.data:
                break

            # Add to found_tasks and collect next level dependencies
            next_to_fetch = []
            for row in response.data:
                task_id = row["id"]
                if task_id not in found_tasks:
                    found_tasks[task_id] = {
                        **row,
                        "depth": depth
                    }

                    # Collect nested dependencies for next iteration
                    if row.get("depends_on"):
                        for dep_id in row["depends_on"]:
                            dep_id_str = str(dep_id) if not isinstance(dep_id, str) else dep_id
                            if dep_id_str not in found_tasks:
                                next_to_fetch.append(dep_id_str)

            to_fetch = list(set(next_to_fetch))  # Deduplicate
            depth += 1

        return found_tasks

    async def validate_dependencies(
        self,
        depends_on: List[UUID],
        check_circular: bool = True,
        new_task_id: Optional[UUID] = None,
    ) -> OperationResult:
        """
        Validate that all dependency task IDs exist and are valid.

        Checks:
        1. All dependency IDs exist in the database
        2. No dependencies have failed status
        3. No circular dependencies (if check_circular=True)

        Args:
            depends_on: List of task IDs that this task depends on
            check_circular: Whether to check for circular dependencies
            new_task_id: Optional ID of the task being created (for circular check)

        Returns:
            OperationResult with validation status
        """
        if not depends_on:
            return OperationResult.ok({"validated": True, "dependencies": []})

        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            dep_ids_str = [str(d) for d in depends_on]

            # If we need to check circular dependencies, fetch the complete tree
            # upfront to avoid N+1 queries during recursion
            if check_circular and new_task_id:
                # Fetch complete dependency tree in a single query
                found_tasks = await self._fetch_dependency_tree(depends_on)
            else:
                # Just fetch direct dependencies (no circular check needed)
                response = self.client.table(TASK_QUEUE_TABLE).select(
                    "id", "status", "depends_on", "error"
                ).in_("id", dep_ids_str).execute()
                found_tasks = {row["id"]: row for row in (response.data or [])}

            # Check 1: All direct dependencies must exist
            for dep_id in depends_on:
                if str(dep_id) not in found_tasks:
                    return OperationResult.fail(
                        DependencyNotFoundError(
                            task_id=str(new_task_id) if new_task_id else None,
                            missing_dependency_id=str(dep_id)
                        )
                    )

            # Check 2: No failed direct dependencies
            for dep_id in depends_on:
                dep_id_str = str(dep_id)
                task_data = found_tasks.get(dep_id_str)
                if task_data and task_data["status"] == TaskStatus.FAILED.value:
                    return OperationResult.fail(
                        FailedDependencyError(
                            task_id=str(new_task_id) if new_task_id else None,
                            failed_dependency_id=dep_id_str,
                            failure_reason=task_data.get("error")
                        )
                    )

            # Check 3: No circular dependencies (tree already fetched above)
            if check_circular and new_task_id:
                circular_result = await self._check_circular_dependency(
                    new_task_id=new_task_id,
                    depends_on=depends_on,
                    found_tasks=found_tasks
                )
                if not circular_result.success:
                    return circular_result

            logger.info(f"Dependency validation passed for {len(depends_on)} dependencies")
            return OperationResult.ok({
                "validated": True,
                "dependencies": dep_ids_str,
                "dependency_statuses": {
                    tid: tdata["status"] for tid, tdata in found_tasks.items()
                }
            })

        except Exception as e:
            logger.error(f"Error validating dependencies: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to validate dependencies: {str(e)}",
                    operation="select",
                    table=TASK_QUEUE_TABLE,
                    original_error=e,
                )
            )

    async def _check_circular_dependency(
        self,
        new_task_id: UUID,
        depends_on: List[UUID],
        found_tasks: Dict[str, Dict],
        visited: Optional[set] = None,
        chain: Optional[List[str]] = None,
    ) -> OperationResult:
        """
        Recursively check for circular dependencies.

        A circular dependency exists if following the dependency chain
        leads back to the new task being created.

        Args:
            new_task_id: The ID of the task being created
            depends_on: Direct dependencies of the current node
            found_tasks: Already-fetched task data
            visited: Set of visited task IDs
            chain: Current dependency chain for error reporting

        Returns:
            OperationResult - success if no circular dependency, fail otherwise
        """
        if visited is None:
            visited = set()
        if chain is None:
            chain = [str(new_task_id)]

        for dep_id in depends_on:
            dep_id_str = str(dep_id)

            # If we've reached the new task, we have a cycle
            if dep_id == new_task_id:
                chain.append(dep_id_str)
                return OperationResult.fail(
                    CircularDependencyError(
                        task_id=str(new_task_id),
                        dependency_chain=chain
                    )
                )

            # Skip already visited to prevent infinite loops
            if dep_id_str in visited:
                continue

            visited.add(dep_id_str)
            chain.append(dep_id_str)

            # Get the dependency's dependencies from pre-fetched tree
            # Note: found_tasks should already contain the complete tree
            # via _fetch_dependency_tree() - no additional queries needed
            task_data = found_tasks.get(dep_id_str)
            if task_data and task_data.get("depends_on"):
                nested_deps = task_data["depends_on"]
                if nested_deps:
                    # Convert to UUIDs
                    nested_dep_uuids = [
                        UUID(d) if isinstance(d, str) else d
                        for d in nested_deps
                    ]

                    # Recurse with pre-fetched data (no database query)
                    result = await self._check_circular_dependency(
                        new_task_id=new_task_id,
                        depends_on=nested_dep_uuids,
                        found_tasks=found_tasks,
                        visited=visited,
                        chain=chain.copy()
                    )
                    if not result.success:
                        return result

            chain.pop()

        return OperationResult.ok({"circular_check": "passed"})

    async def get_dependency_status(self, task_id: UUID) -> OperationResult:
        """
        Get detailed status of all dependencies for a task.

        Returns information about each dependency including:
        - Status (queued, in_progress, completed, failed)
        - Whether it's blocking this task
        - Error message if failed

        Args:
            task_id: The task ID to check dependencies for

        Returns:
            OperationResult with dependency status details
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Get the task
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]
            if not task.depends_on:
                return OperationResult.ok({
                    "task_id": str(task_id),
                    "has_dependencies": False,
                    "dependencies": [],
                    "all_met": True,
                    "blocking_count": 0
                })

            # Fetch dependency tasks
            dep_ids_str = [str(d) for d in task.depends_on]
            response = self.client.table(TASK_QUEUE_TABLE).select(
                "id", "status", "error", "role", "created_at"
            ).in_("id", dep_ids_str).execute()

            dependencies = []
            blocking_count = 0
            all_met = True

            for dep_id in task.depends_on:
                dep_id_str = str(dep_id)
                dep_data = next(
                    (row for row in (response.data or []) if row["id"] == dep_id_str),
                    None
                )

                if dep_data:
                    is_blocking = dep_data["status"] != TaskStatus.COMPLETED.value
                    if is_blocking:
                        blocking_count += 1
                        all_met = False

                    dependencies.append({
                        "id": dep_id_str,
                        "status": dep_data["status"],
                        "role": dep_data["role"],
                        "is_blocking": is_blocking,
                        "error": dep_data.get("error") if dep_data["status"] == TaskStatus.FAILED.value else None,
                        "created_at": dep_data["created_at"]
                    })
                else:
                    # Dependency task not found
                    dependencies.append({
                        "id": dep_id_str,
                        "status": "NOT_FOUND",
                        "is_blocking": True,
                        "error": "Dependency task does not exist"
                    })
                    blocking_count += 1
                    all_met = False

            return OperationResult.ok({
                "task_id": str(task_id),
                "has_dependencies": True,
                "dependencies": dependencies,
                "all_met": all_met,
                "blocking_count": blocking_count,
                "total_dependencies": len(task.depends_on)
            })

        except Exception as e:
            logger.error(f"Error getting dependency status for task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to get dependency status: {str(e)}",
                    operation="select",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def create_task_with_validation(
        self,
        role: str,
        payload: Dict[str, Any],
        depends_on: Optional[List[UUID]] = None,
        priority: int = 0,
        created_by: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> OperationResult:
        """
        Create a new task with dependency validation.

        This is the recommended method for creating tasks as it validates:
        1. All dependency IDs exist
        2. No dependencies have failed
        3. No circular dependencies would be created

        Args:
            role: The agent role to handle this task
            payload: Instructions/context for the agent
            depends_on: List of task IDs that must complete first
            priority: Task priority (higher = more important)
            created_by: Optional identifier for who created this task
            session_id: Optional session/conversation ID

        Returns:
            OperationResult with task_id if successful
        """
        depends_on = depends_on or []

        # Validate dependencies first
        if depends_on:
            # Generate a temporary ID for circular check
            temp_id = uuid4()

            validation_result = await self.validate_dependencies(
                depends_on=depends_on,
                check_circular=True,
                new_task_id=temp_id
            )

            if not validation_result.success:
                logger.warning(
                    f"Dependency validation failed for new task: "
                    f"{validation_result.error.message if validation_result.error else 'Unknown error'}"
                )
                return validation_result

        # Create the task
        try:
            task_id = await self.create_task(
                role=role,
                payload=payload,
                depends_on=depends_on,
                priority=priority,
                created_by=created_by,
                session_id=session_id
            )

            return OperationResult.ok({
                "task_id": str(task_id),
                "role": role,
                "status": TaskStatus.QUEUED.value,
                "dependencies_count": len(depends_on)
            })

        except Exception as e:
            logger.error(f"Error creating task with validation: {e}")
            return OperationResult.fail(
                TaskQueueError(
                    message=f"Failed to create task: {str(e)}",
                    operation="create",
                    original_error=e,
                )
            )

    # =========================================================================
    # Retry Mechanism
    # =========================================================================

    @staticmethod
    def get_backoff_seconds(retry_count: int) -> int:
        """
        Get the backoff delay in seconds for the given retry attempt.

        Uses exponential backoff: 30s, 5m, 15m

        Args:
            retry_count: Current retry attempt (0-indexed)

        Returns:
            Delay in seconds before next retry
        """
        if retry_count >= len(BACKOFF_INTERVALS):
            return BACKOFF_INTERVALS[-1]
        return BACKOFF_INTERVALS[retry_count]

    @staticmethod
    def is_retryable_error(error: str) -> bool:
        """
        Determine if an error is retryable based on the error message.

        Retryable errors (transient):
        - Rate limiting (429, rate limit, quota)
        - Timeouts (timeout, timed out)
        - Network errors (connection, network)
        - Server errors (500, 502, 503, 504)
        - Temporary failures (temporary, retry)

        Non-retryable errors (permanent):
        - Validation errors (validation, invalid, malformed)
        - Authentication errors (auth, unauthorized, 401, 403)
        - Not found errors (not found, 404)
        - Configuration errors (config, missing)

        Args:
            error: Error message string

        Returns:
            True if the error is retryable, False otherwise
        """
        error_lower = error.lower()

        # Non-retryable patterns (check first - these are permanent failures)
        non_retryable_patterns = [
            "validation", "invalid", "malformed",
            "unauthorized", "401", "403", "forbidden",
            "not found", "404",
            "config", "missing credential",
            "circular dependency", "dependency not found",
            "no_tools_called",  # Agent didn't use tools when required
            "no tools called",  # Alternative format
        ]

        for pattern in non_retryable_patterns:
            if pattern in error_lower:
                return False

        # Retryable patterns (transient failures)
        retryable_patterns = [
            "rate limit", "429", "quota", "throttl",
            "timeout", "timed out",
            "connection", "network", "socket",
            "500", "502", "503", "504", "server error",
            "temporary", "retry", "try again",
            "overload", "busy", "unavailable",
        ]

        for pattern in retryable_patterns:
            if pattern in error_lower:
                return True

        # Default: assume retryable (be optimistic)
        return True

    async def fail_task_with_retry(
        self,
        task_id: UUID,
        error: str,
        is_retryable: Optional[bool] = None,
        cascade: bool = True
    ) -> OperationResult:
        """
        Mark a task as failed with automatic retry scheduling.

        If the error is retryable and retry_count < max_retries:
        - Sets next_retry_at based on exponential backoff
        - Marks task as FAILED but with is_retryable=True
        - Task can be picked up by retry worker or retry_task() call

        If not retryable or max retries exceeded:
        - Marks as permanently FAILED with is_retryable=False
        - Triggers cascade failure to dependent tasks

        Args:
            task_id: The task ID to fail
            error: Error message/description
            is_retryable: Override auto-detection of retry eligibility
            cascade: If True and permanent failure, propagate to dependents

        Returns:
            OperationResult with retry information
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Get current task state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]
            current_retry_count = task.retry_count
            max_retries = task.max_retries

            # Determine if error is retryable
            if is_retryable is None:
                is_retryable = self.is_retryable_error(error)

            # Check if we can retry
            can_retry = is_retryable and current_retry_count < max_retries
            new_retry_count = current_retry_count + 1

            if can_retry:
                # Schedule retry with exponential backoff
                backoff_seconds = self.get_backoff_seconds(current_retry_count)
                next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)

                update_data = {
                    "status": TaskStatus.FAILED.value,
                    "error": error,
                    "retry_count": new_retry_count,
                    "next_retry_at": next_retry_at.isoformat(),
                    "is_retryable": True
                }

                response = self.client.table(TASK_QUEUE_TABLE).update(
                    update_data
                ).eq("id", str(task_id)).execute()

                if response.data and len(response.data) > 0:
                    logger.info(
                        f"Task {task_id} failed (attempt {new_retry_count}/{max_retries}), "
                        f"will retry in {backoff_seconds}s at {next_retry_at.isoformat()}"
                    )
                    return OperationResult.ok({
                        "task_id": str(task_id),
                        "error": error,
                        "retry_scheduled": True,
                        "retry_count": new_retry_count,
                        "max_retries": max_retries,
                        "next_retry_at": next_retry_at.isoformat(),
                        "backoff_seconds": backoff_seconds,
                        "is_retryable": True,
                        "cascaded_failures": 0,
                        "cascaded_task_ids": []
                    })

            # Permanent failure - no more retries
            logger.warning(
                f"Task {task_id} permanently failed after {new_retry_count} attempts: {error}"
            )

            # Use the existing fail_task_result for permanent failure (handles cascade)
            return await self.fail_task_result(
                task_id=task_id,
                error=f"[PERMANENT FAILURE after {new_retry_count} attempts] {error}",
                cascade=cascade
            )

        except Exception as e:
            logger.error(f"Error in fail_task_with_retry for task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to process task failure with retry: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def retry_task(self, task_id: UUID) -> OperationResult:
        """
        Retry a failed task by resetting its status to QUEUED.

        Only works if:
        - Task is currently in FAILED status
        - Task has is_retryable=True
        - Task has retry_count < max_retries

        Args:
            task_id: The task ID to retry

        Returns:
            OperationResult with retry status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Get current task state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Validate task can be retried
            if task.status != TaskStatus.FAILED:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot retry task: status is '{task.status}', expected 'failed'",
                        operation="retry"
                    )
                )

            if not task.is_retryable:
                return OperationResult.fail(
                    TaskQueueError(
                        message="Cannot retry task: marked as non-retryable (permanent failure)",
                        operation="retry"
                    )
                )

            if task.retry_count >= task.max_retries:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot retry task: max retries ({task.max_retries}) exceeded",
                        operation="retry"
                    )
                )

            # Reset task to QUEUED
            update_data = {
                "status": TaskStatus.QUEUED.value,
                "next_retry_at": None,
                "error": None  # Clear error for fresh attempt
            }

            response = self.client.table(TASK_QUEUE_TABLE).update(
                update_data
            ).eq("id", str(task_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(
                    f"Retried task {task_id} (attempt {task.retry_count + 1}/{task.max_retries})"
                )
                return OperationResult.ok({
                    "task_id": str(task_id),
                    "status": TaskStatus.QUEUED.value,
                    "retry_count": task.retry_count,
                    "max_retries": task.max_retries,
                    "message": f"Task reset to queued for retry attempt {task.retry_count + 1}"
                })

            return OperationResult.fail(
                TaskNotFoundError(task_id=str(task_id))
            )

        except Exception as e:
            logger.error(f"Error retrying task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to retry task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def get_retryable_tasks(self, limit: int = 10) -> List[Task]:
        """
        Get failed tasks that are eligible for retry.

        Returns tasks where:
        - status = 'failed'
        - is_retryable = True
        - retry_count < max_retries
        - next_retry_at <= now (or is NULL)

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of Task objects ready for retry
        """
        if not self.client:
            return []

        try:
            # Use the database function for consistency
            response = self.client.rpc(
                "get_retryable_tasks"
            ).execute()

            if response.data:
                tasks = [self._parse_task(row) for row in response.data[:limit]]
                logger.debug(f"Found {len(tasks)} retryable tasks")
                return tasks

            return []

        except Exception as e:
            logger.error(f"Error getting retryable tasks: {e}")
            return []

    async def process_retryable_tasks(self) -> Dict[str, Any]:
        """
        Process all tasks that are ready for retry.

        This is meant to be called by a background worker or scheduled job.

        Returns:
            Summary of retry processing results
        """
        retried = []
        failed = []

        tasks = await self.get_retryable_tasks()

        for task in tasks:
            result = await self.retry_task(task.id)
            if result.success:
                retried.append(str(task.id))
            else:
                failed.append({
                    "task_id": str(task.id),
                    "error": result.error.message if result.error else "Unknown error"
                })

        if retried:
            logger.info(f"Processed {len(retried)} task retries")

        return {
            "processed": len(tasks),
            "retried": retried,
            "failed": failed
        }

    # =========================================================================
    # Manual Recovery Operations
    # =========================================================================

    async def force_retry_task(
        self,
        task_id: UUID,
        reason: str
    ) -> OperationResult:
        """
        Force retry a failed task, bypassing retry limits and retryable checks.

        Use this when:
        - A task failed with is_retryable=False but the external issue was fixed
        - A task exceeded max_retries but the root cause was addressed
        - Manual operator intervention is needed to recover from failures

        Args:
            task_id: The task ID to force retry
            reason: Required reason for audit trail (why is this being force-retried?)

        Returns:
            OperationResult with retry status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        if not reason or not reason.strip():
            return OperationResult.fail(
                TaskQueueError(
                    message="Reason is required for force-retry (audit trail)",
                    operation="force_retry"
                )
            )

        try:
            # Get current task state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Validate task is in FAILED status
            if task.status != TaskStatus.FAILED:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot force-retry task: status is '{task.status}', expected 'failed'",
                        operation="force_retry",
                        status_code=409
                    )
                )

            # Reset to QUEUED, preserving retry_count for history
            # Note: We do NOT reset retry_count - it shows total attempts
            update_data = {
                "status": TaskStatus.QUEUED.value,
                "error": f"Force retry: {reason.strip()}",
                "is_retryable": True,
                "next_retry_at": None,
                "started_at": None,
                "last_heartbeat_at": None
            }

            response = self.client.table(TASK_QUEUE_TABLE).update(
                update_data
            ).eq("id", str(task_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Force-retried task {task_id}: {reason}")
                return OperationResult.ok({
                    "task_id": str(task_id),
                    "previous_status": "failed",
                    "new_status": "queued",
                    "reason": reason.strip(),
                    "retry_count": task.retry_count  # Preserved for audit
                })

            return OperationResult.fail(
                TaskNotFoundError(task_id=str(task_id))
            )

        except Exception as e:
            logger.error(f"Error force-retrying task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to force-retry task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def rerun_task(
        self,
        task_id: UUID,
        reason: str
    ) -> OperationResult:
        """
        Re-queue a completed task for re-execution.

        Use this when:
        - A task completed but needs to be run again
        - Results need to be regenerated
        - Downstream processing requires a fresh run

        Args:
            task_id: The task ID to rerun
            reason: Required reason for audit trail (why is this being rerun?)

        Returns:
            OperationResult with rerun status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        if not reason or not reason.strip():
            return OperationResult.fail(
                TaskQueueError(
                    message="Reason is required for rerun (audit trail)",
                    operation="rerun"
                )
            )

        try:
            # Get current task state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Validate task is in COMPLETED status
            if task.status != TaskStatus.COMPLETED:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot rerun task: status is '{task.status}', expected 'completed'",
                        operation="rerun",
                        status_code=409
                    )
                )

            # Reset to QUEUED
            update_data = {
                "status": TaskStatus.QUEUED.value,
                "result": None,  # Clear previous result
                "error": f"Rerun requested: {reason.strip()}",
                "started_at": None,
                "last_heartbeat_at": None
            }

            response = self.client.table(TASK_QUEUE_TABLE).update(
                update_data
            ).eq("id", str(task_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Rerun task {task_id}: {reason}")
                return OperationResult.ok({
                    "task_id": str(task_id),
                    "previous_status": "completed",
                    "new_status": "queued",
                    "reason": reason.strip()
                })

            return OperationResult.fail(
                TaskNotFoundError(task_id=str(task_id))
            )

        except Exception as e:
            logger.error(f"Error rerunning task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to rerun task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def cancel_task(
        self,
        task_id: UUID,
        reason: str,
        cascade: bool = True
    ) -> OperationResult:
        """
        Cancel a queued task (mark as failed without running).

        Use this when:
        - A queued task is no longer needed
        - The task will never be able to run (known dependency issues)
        - Manual cleanup of orphaned tasks

        Args:
            task_id: The task ID to cancel
            reason: Required reason for audit trail (why is this being cancelled?)
            cascade: If True, also cancel dependent queued tasks (default: True)

        Returns:
            OperationResult with cancellation status and cascade info
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        if not reason or not reason.strip():
            return OperationResult.fail(
                TaskQueueError(
                    message="Reason is required for cancellation (audit trail)",
                    operation="cancel"
                )
            )

        try:
            # Get current task state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Validate task is in QUEUED status
            if task.status != TaskStatus.QUEUED:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot cancel task: status is '{task.status}', expected 'queued'",
                        operation="cancel",
                        status_code=409
                    )
                )

            # Mark as failed with cancellation message
            error_msg = f"Cancelled: {reason.strip()}"

            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.FAILED.value,
                "error": error_msg,
                "is_retryable": False  # Cancelled tasks should not be auto-retried
            }).eq("id", str(task_id)).execute()

            if not (response.data and len(response.data) > 0):
                return OperationResult.fail(
                    TaskNotFoundError(task_id=str(task_id))
                )

            logger.info(f"Cancelled task {task_id}: {reason}")

            # Cascade cancellation to dependent tasks
            cascaded_count = 0
            cascaded_task_ids = []

            if cascade:
                dependent_tasks = await self.get_dependent_tasks(task_id)

                for dep_task in dependent_tasks:
                    cascade_error = f"Cancelled: Parent task {task_id} was cancelled ({reason.strip()})"
                    cascade_result = await self.cancel_task(
                        dep_task.id,
                        reason=f"Parent task {task_id} was cancelled",
                        cascade=True  # Recursively cascade
                    )
                    if cascade_result.success:
                        cascaded_count += 1
                        cascaded_task_ids.append(str(dep_task.id))
                        # Include nested cascades
                        if "cascaded_count" in cascade_result.data:
                            cascaded_count += cascade_result.data["cascaded_count"]
                            cascaded_task_ids.extend(cascade_result.data.get("cascaded_task_ids", []))

            return OperationResult.ok({
                "task_id": str(task_id),
                "previous_status": "queued",
                "new_status": "failed",
                "reason": reason.strip(),
                "cascaded_count": cascaded_count,
                "cascaded_task_ids": cascaded_task_ids
            })

        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to cancel task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    # =========================================================================
    # Timeout Detection and Stuck Task Recovery
    # =========================================================================

    async def get_stuck_tasks(self, limit: int = 10) -> List[Task]:
        """
        Get tasks that have been IN_PROGRESS longer than their timeout.

        Returns tasks where:
        - status = 'in_progress'
        - started_at + timeout_seconds < now

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of Task objects that appear to be stuck
        """
        if not self.client:
            return []

        try:
            # Use the database function for consistency
            response = self.client.rpc(
                "get_stuck_tasks",
                {"max_results": limit}
            ).execute()

            if response.data:
                tasks = [self._parse_task(row) for row in response.data]
                if tasks:
                    logger.warning(f"Found {len(tasks)} stuck tasks")
                return tasks

            return []

        except Exception as e:
            logger.error(f"Error getting stuck tasks: {e}")
            return []

    async def update_heartbeat(self, task_id: UUID) -> bool:
        """
        Update the heartbeat timestamp for a running task.

        Long-running tasks should call this periodically to signal
        they are still alive and prevent timeout detection.

        Args:
            task_id: The task ID to update

        Returns:
            True if updated successfully
        """
        if not self.client:
            return False

        try:
            response = self.client.rpc(
                "update_task_heartbeat",
                {"target_task_id": str(task_id)}
            ).execute()

            return response.data is True

        except Exception as e:
            logger.error(f"Error updating heartbeat for task {task_id}: {e}")
            return False

    async def requeue_stuck_task(
        self,
        task_id: UUID,
        error: str = "Task timed out - no response from agent"
    ) -> OperationResult:
        """
        Requeue a stuck task or mark as permanently failed.

        If retry_count < max_retries:
        - Resets status to 'queued'
        - Increments retry_count
        - Clears started_at

        If max retries exceeded:
        - Marks as permanently failed
        - Triggers cascade failure

        Args:
            task_id: The stuck task ID
            error: Error message describing the timeout

        Returns:
            OperationResult with requeue status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            # Get current task state
            task_result = await self.get_task_result(task_id)
            if not task_result.success:
                return task_result

            task = task_result.data["task"]

            # Only requeue if still in_progress
            if task.status != TaskStatus.IN_PROGRESS:
                return OperationResult.fail(
                    TaskQueueError(
                        message=f"Cannot requeue task: status is '{task.status}', expected 'in_progress'",
                        operation="requeue"
                    )
                )

            # Calculate how long the task has been running
            elapsed_seconds = 0
            if task.started_at:
                if isinstance(task.started_at, str):
                    started = datetime.fromisoformat(task.started_at.replace('Z', '+00:00'))
                else:
                    started = task.started_at
                elapsed_seconds = int((datetime.now(timezone.utc) - started).total_seconds())

            timeout_error = f"[TIMEOUT after {elapsed_seconds}s] {error}"

            # Check if we can retry
            if task.retry_count < task.max_retries:
                # Requeue for retry
                update_data = {
                    "status": TaskStatus.QUEUED.value,
                    "retry_count": task.retry_count + 1,
                    "started_at": None,
                    "last_heartbeat_at": None,
                    "error": timeout_error
                }

                response = self.client.table(TASK_QUEUE_TABLE).update(
                    update_data
                ).eq("id", str(task_id)).execute()

                if response.data and len(response.data) > 0:
                    logger.warning(
                        f"Requeued stuck task {task_id} (attempt {task.retry_count + 1}/{task.max_retries}) "
                        f"after {elapsed_seconds}s timeout"
                    )
                    return OperationResult.ok({
                        "task_id": str(task_id),
                        "action": "requeued",
                        "retry_count": task.retry_count + 1,
                        "max_retries": task.max_retries,
                        "elapsed_seconds": elapsed_seconds,
                        "error": timeout_error
                    })

            # Max retries exceeded - permanent failure
            logger.error(
                f"Task {task_id} permanently failed after {task.retry_count + 1} timeout(s)"
            )

            # Use fail_task_result for permanent failure (handles cascade)
            return await self.fail_task_result(
                task_id=task_id,
                error=f"[PERMANENT TIMEOUT after {task.retry_count + 1} attempts] {error}",
                cascade=True
            )

        except Exception as e:
            logger.error(f"Error requeuing stuck task {task_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to requeue stuck task: {str(e)}",
                    operation="update",
                    table=TASK_QUEUE_TABLE,
                    context={"task_id": str(task_id)},
                    original_error=e,
                )
            )

    async def process_stuck_tasks(self) -> Dict[str, Any]:
        """
        Process all stuck tasks by requeuing or failing them.

        This is the watchdog function meant to be called periodically
        (e.g., every 60 seconds) by a background worker.

        Returns:
            Summary of stuck task processing results
        """
        requeued = []
        failed = []
        errors = []

        tasks = await self.get_stuck_tasks()

        for task in tasks:
            # Calculate elapsed time for logging
            elapsed = "unknown"
            if task.started_at:
                if isinstance(task.started_at, str):
                    started = datetime.fromisoformat(task.started_at.replace('Z', '+00:00'))
                else:
                    started = task.started_at
                elapsed = f"{int((datetime.now(timezone.utc) - started).total_seconds())}s"

            result = await self.requeue_stuck_task(
                task.id,
                error=f"Task exceeded {task.timeout_seconds}s timeout (ran for {elapsed})"
            )

            if result.success:
                action = result.data.get("action", "failed")
                if action == "requeued":
                    requeued.append({
                        "task_id": str(task.id),
                        "role": task.role,
                        "elapsed": elapsed,
                        "retry_count": result.data.get("retry_count")
                    })
                else:
                    # Permanently failed
                    failed.append({
                        "task_id": str(task.id),
                        "role": task.role,
                        "elapsed": elapsed,
                        "cascaded_failures": result.data.get("cascaded_failures", 0)
                    })
            else:
                errors.append({
                    "task_id": str(task.id),
                    "error": result.error.message if result.error else "Unknown error"
                })

        if requeued or failed:
            logger.warning(
                f"Watchdog processed {len(tasks)} stuck tasks: "
                f"{len(requeued)} requeued, {len(failed)} permanently failed"
            )

        return {
            "processed": len(tasks),
            "requeued": requeued,
            "failed": failed,
            "errors": errors
        }

    # =========================================================================
    # Blocked Task Detection (P1 #5)
    # =========================================================================

    async def get_blocked_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get tasks that are blocked by failed dependencies.

        These tasks will never run without manual intervention because
        at least one of their dependencies has failed.

        Returns:
            List of blocked task info dicts with dependency failure details
        """
        try:
            response = self.client.rpc(
                "get_blocked_tasks",
                {"max_results": limit}
            ).execute()

            if response.data:
                return response.data

            return []

        except Exception as e:
            logger.error(f"Error fetching blocked tasks: {e}")
            # Fallback to manual query if RPC not available
            return await self._get_blocked_tasks_fallback(limit)

    async def _get_blocked_tasks_fallback(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fallback method if RPC function not available."""
        try:
            # Get all queued tasks with dependencies
            response = self.client.table("task_queue").select(
                "id, role, prompt, created_at, depends_on"
            ).eq("status", "queued").not_.is_("depends_on", "null").execute()

            if not response.data:
                return []

            blocked = []
            for task in response.data:
                if not task.get("depends_on"):
                    continue

                # Check each dependency
                for dep_id in task["depends_on"]:
                    dep_response = self.client.table("task_queue").select(
                        "id, role, status, error"
                    ).eq("id", dep_id).single().execute()

                    if dep_response.data and dep_response.data.get("status") == "failed":
                        blocked.append({
                            "task_id": task["id"],
                            "task_role": task["role"],
                            "task_prompt": task["prompt"][:200] if task.get("prompt") else None,
                            "created_at": task["created_at"],
                            "failed_dependency_id": dep_response.data["id"],
                            "failed_dependency_role": dep_response.data.get("role"),
                            "failed_dependency_error": (
                                dep_response.data.get("error", "")[:200]
                                if dep_response.data.get("error") else None
                            )
                        })
                        break  # One failed dep is enough to be blocked

                if len(blocked) >= limit:
                    break

            return blocked

        except Exception as e:
            logger.error(f"Fallback blocked tasks query failed: {e}")
            return []

    async def get_stale_queued_tasks(
        self,
        threshold_minutes: int = 60,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get tasks that have been queued for longer than the threshold.

        These may indicate a problem with dependencies or dispatching.

        Args:
            threshold_minutes: How long is considered "too long" (default: 60)
            limit: Maximum results to return

        Returns:
            List of stale task info dicts
        """
        try:
            response = self.client.rpc(
                "get_stale_queued_tasks",
                {
                    "threshold_minutes": threshold_minutes,
                    "max_results": limit
                }
            ).execute()

            if response.data:
                return response.data

            return []

        except Exception as e:
            logger.error(f"Error fetching stale queued tasks: {e}")
            # Fallback to manual query
            return await self._get_stale_queued_tasks_fallback(threshold_minutes, limit)

    async def _get_stale_queued_tasks_fallback(
        self,
        threshold_minutes: int = 60,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fallback method if RPC function not available."""
        try:
            from datetime import datetime, timezone, timedelta

            threshold_time = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)

            response = self.client.table("task_queue").select(
                "id, role, prompt, created_at, depends_on"
            ).eq("status", "queued").lt(
                "created_at", threshold_time.isoformat()
            ).order("created_at").limit(limit).execute()

            if not response.data:
                return []

            stale = []
            now = datetime.now(timezone.utc)

            for task in response.data:
                created = datetime.fromisoformat(
                    task["created_at"].replace("Z", "+00:00")
                )
                queued_minutes = (now - created).total_seconds() / 60

                dep_count = len(task.get("depends_on") or [])

                stale.append({
                    "task_id": task["id"],
                    "task_role": task["role"],
                    "task_prompt": task["prompt"][:200] if task.get("prompt") else None,
                    "created_at": task["created_at"],
                    "queued_minutes": round(queued_minutes, 1),
                    "dependency_count": dep_count,
                    "pending_dependencies": dep_count  # Approximation
                })

            return stale

        except Exception as e:
            logger.error(f"Fallback stale tasks query failed: {e}")
            return []

    async def get_orphaned_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get tasks where ALL dependencies have failed.

        These tasks have zero chance of ever running without manual
        re-creation of their dependency chain.

        Returns:
            List of orphaned task info dicts
        """
        try:
            response = self.client.rpc(
                "get_orphaned_tasks",
                {"max_results": limit}
            ).execute()

            if response.data:
                return response.data

            return []

        except Exception as e:
            logger.error(f"Error fetching orphaned tasks: {e}")
            return []

    async def get_task_queue_health(self) -> Dict[str, Any]:
        """
        Get overall health metrics for the task queue.

        Returns dict with:
        - total_queued: Number of queued tasks
        - total_in_progress: Number of in-progress tasks
        - blocked_by_failed_deps: Tasks blocked by failed dependencies
        - stale_queued_1h: Tasks queued for over 1 hour
        - stale_queued_24h: Tasks queued for over 24 hours
        - stuck_tasks: In-progress tasks past their timeout
        - pending_retries: Failed tasks eligible for retry
        """
        try:
            response = self.client.rpc("get_task_queue_health", {}).execute()

            if response.data and len(response.data) > 0:
                return response.data[0]

            return await self._get_task_queue_health_fallback()

        except Exception as e:
            logger.error(f"Error fetching task queue health: {e}")
            return await self._get_task_queue_health_fallback()

    async def _get_task_queue_health_fallback(self) -> Dict[str, Any]:
        """Fallback method if RPC function not available."""
        try:
            from datetime import datetime, timezone, timedelta

            now = datetime.now(timezone.utc)
            one_hour_ago = (now - timedelta(hours=1)).isoformat()
            one_day_ago = (now - timedelta(hours=24)).isoformat()

            # Get basic counts
            queued = self.client.table("task_queue").select(
                "id", count="exact"
            ).eq("status", "queued").execute()

            in_progress = self.client.table("task_queue").select(
                "id", count="exact"
            ).eq("status", "in_progress").execute()

            stale_1h = self.client.table("task_queue").select(
                "id", count="exact"
            ).eq("status", "queued").lt("created_at", one_hour_ago).execute()

            stale_24h = self.client.table("task_queue").select(
                "id", count="exact"
            ).eq("status", "queued").lt("created_at", one_day_ago).execute()

            # Get blocked count
            blocked_tasks = await self.get_blocked_tasks(limit=1000)

            return {
                "total_queued": queued.count or 0,
                "total_in_progress": in_progress.count or 0,
                "blocked_by_failed_deps": len(blocked_tasks),
                "stale_queued_1h": stale_1h.count or 0,
                "stale_queued_24h": stale_24h.count or 0,
                "stuck_tasks": 0,  # Would need more complex query
                "pending_retries": 0  # Would need more complex query
            }

        except Exception as e:
            logger.error(f"Fallback health check failed: {e}")
            return {
                "total_queued": 0,
                "total_in_progress": 0,
                "blocked_by_failed_deps": 0,
                "stale_queued_1h": 0,
                "stale_queued_24h": 0,
                "stuck_tasks": 0,
                "pending_retries": 0,
                "error": str(e)
            }

    async def run_health_check(
        self,
        alert_blocked: bool = True,
        alert_stale_threshold_minutes: int = 60,
        alert_orphaned: bool = True
    ) -> Dict[str, Any]:
        """
        Run a comprehensive health check and generate alerts for issues.

        This should be called periodically (e.g., every 5-10 minutes) by
        a scheduler or monitoring system.

        Args:
            alert_blocked: Whether to alert on blocked tasks
            alert_stale_threshold_minutes: Threshold for stale task alerts
            alert_orphaned: Whether to alert on fully orphaned tasks

        Returns:
            Health check results with alert counts
        """
        results = {
            "health": {},
            "alerts_sent": 0,
            "blocked_tasks": [],
            "stale_tasks": [],
            "orphaned_tasks": []
        }

        # Get overall health
        results["health"] = await self.get_task_queue_health()

        # Check for blocked tasks
        if alert_blocked:
            blocked = await self.get_blocked_tasks(limit=20)
            results["blocked_tasks"] = blocked

            if blocked:
                # Import here to avoid circular imports
                from lib.agent.slack_manager import send_blocked_tasks_alert
                await send_blocked_tasks_alert(blocked)
                results["alerts_sent"] += 1

        # Check for stale queued tasks
        if alert_stale_threshold_minutes > 0:
            stale = await self.get_stale_queued_tasks(
                threshold_minutes=alert_stale_threshold_minutes,
                limit=20
            )
            results["stale_tasks"] = stale

            if stale:
                from lib.agent.slack_manager import send_stale_tasks_alert
                await send_stale_tasks_alert(stale, alert_stale_threshold_minutes)
                results["alerts_sent"] += 1

        # Check for fully orphaned tasks
        if alert_orphaned:
            orphaned = await self.get_orphaned_tasks(limit=20)
            results["orphaned_tasks"] = orphaned

            if orphaned:
                from lib.agent.slack_manager import send_orphaned_tasks_alert
                await send_orphaned_tasks_alert(orphaned)
                results["alerts_sent"] += 1

        if results["alerts_sent"] > 0:
            logger.warning(
                f"Health check completed: {results['alerts_sent']} alerts sent. "
                f"Blocked: {len(results['blocked_tasks'])}, "
                f"Stale: {len(results['stale_tasks'])}, "
                f"Orphaned: {len(results['orphaned_tasks'])}"
            )
        else:
            logger.info("Health check completed: No issues detected")

        return results

    # =========================================================================
    # Pre-Dispatch Validation (P1 #6)
    # =========================================================================

    async def validate_dependencies_before_dispatch(self, task: Task) -> bool:
        """
        Validate task dependencies before dispatch.

        If any dependency has failed, this method will auto-fail the task
        with cascade=True to prevent orphaned dependency chains.

        Args:
            task: The task to validate

        Returns:
            True if task is valid for dispatch, False if it was auto-failed
        """
        if not task.depends_on or len(task.depends_on) == 0:
            return True  # No dependencies, always valid

        try:
            # Try using the RPC function first
            response = self.client.rpc(
                "validate_task_for_dispatch",
                {"target_task_id": str(task.id)}
            ).execute()

            if response.data and len(response.data) > 0:
                result = response.data[0]

                if result.get("should_fail"):
                    # Task has a failed dependency - auto-fail it
                    failed_dep_id = result.get("failed_dep_id")
                    failed_dep_role = result.get("failed_dep_role", "unknown")
                    failed_dep_error = result.get("failed_dep_error", "Unknown error")

                    error_msg = (
                        f"Auto-failed: dependency {str(failed_dep_id)[:8]}... "
                        f"({failed_dep_role}) failed: {failed_dep_error[:100]}"
                    )

                    logger.warning(
                        f"Task {task.id} has failed dependency {failed_dep_id}, "
                        f"auto-failing with cascade"
                    )

                    await self.fail_task_result(
                        task.id,
                        error=error_msg,
                        cascade=True
                    )
                    return False

                return result.get("is_valid", True)

        except Exception as e:
            logger.warning(f"RPC validate_task_for_dispatch failed, using fallback: {e}")

        # Fallback: manually check dependencies
        return await self._validate_dependencies_fallback(task)

    async def _validate_dependencies_fallback(self, task: Task) -> bool:
        """Fallback validation if RPC function not available."""
        try:
            for dep_id in task.depends_on:
                response = self.client.table("task_queue").select(
                    "id, role, status, error"
                ).eq("id", str(dep_id)).single().execute()

                if response.data and response.data.get("status") == TaskStatus.FAILED.value:
                    # Found a failed dependency
                    failed_role = response.data.get("role", "unknown")
                    failed_error = response.data.get("error", "Unknown error")[:100]

                    error_msg = (
                        f"Auto-failed: dependency {str(dep_id)[:8]}... "
                        f"({failed_role}) failed: {failed_error}"
                    )

                    logger.warning(
                        f"Task {task.id} has failed dependency {dep_id}, "
                        f"auto-failing with cascade"
                    )

                    await self.fail_task_result(
                        task.id,
                        error=error_msg,
                        cascade=True
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Fallback dependency validation failed: {e}")
            # On error, assume valid to avoid blocking legitimate tasks
            return True

    async def auto_fail_blocked_tasks(self, limit: int = 100) -> Dict[str, Any]:
        """
        Automatically fail all tasks blocked by failed dependencies.

        This is a cleanup operation that finds tasks with failed dependencies
        and fails them with cascade=True, preventing orphaned chains.

        Args:
            limit: Maximum number of blocked tasks to process

        Returns:
            Dict with counts of tasks processed, failed, and any errors
        """
        results = {
            "found": 0,
            "failed": [],
            "errors": []
        }

        try:
            blocked_tasks = await self.get_blocked_tasks(limit=limit)
            results["found"] = len(blocked_tasks)

            if not blocked_tasks:
                logger.info("No blocked tasks found to auto-fail")
                return results

            # Track unique task IDs we've already processed (avoid duplicates)
            processed_ids = set()

            for blocked in blocked_tasks:
                task_id_str = blocked.get("task_id")
                if not task_id_str or task_id_str in processed_ids:
                    continue

                processed_ids.add(task_id_str)

                try:
                    task_id = UUID(task_id_str)
                    failed_dep_id = blocked.get("failed_dependency_id", "unknown")
                    failed_dep_role = blocked.get("failed_dependency_role", "unknown")
                    failed_dep_error = blocked.get("failed_dependency_error", "Unknown")

                    error_msg = (
                        f"Auto-failed by cleanup: dependency {str(failed_dep_id)[:8]}... "
                        f"({failed_dep_role}) failed: {failed_dep_error[:100]}"
                    )

                    result = await self.fail_task_result(
                        task_id,
                        error=error_msg,
                        cascade=True
                    )

                    if result.success:
                        results["failed"].append({
                            "task_id": task_id_str,
                            "role": blocked.get("task_role"),
                            "failed_dep_id": str(failed_dep_id),
                            "cascaded": result.data.get("cascaded_failures", 0)
                        })
                    else:
                        error_text = result.error.message if result.error else "Unknown"
                        results["errors"].append({
                            "task_id": task_id_str,
                            "error": error_text
                        })

                except Exception as e:
                    results["errors"].append({
                        "task_id": task_id_str,
                        "error": str(e)
                    })

            if results["failed"]:
                total_cascaded = sum(t.get("cascaded", 0) for t in results["failed"])
                logger.warning(
                    f"Auto-failed {len(results['failed'])} blocked tasks "
                    f"(+{total_cascaded} cascaded)"
                )

                # Send Slack alert about auto-fix
                try:
                    from lib.agent.slack_manager import send_auto_fail_alert
                    await send_auto_fail_alert(
                        failed_count=len(results["failed"]),
                        cascaded_count=total_cascaded,
                        sample_tasks=results["failed"][:5]
                    )
                except ImportError:
                    pass  # Alert function may not exist yet

            return results

        except Exception as e:
            logger.error(f"Error in auto_fail_blocked_tasks: {e}")
            results["errors"].append({"error": str(e)})
            return results

    async def run_health_check_with_auto_fix(
        self,
        alert_blocked: bool = True,
        alert_stale_threshold_minutes: int = 60,
        alert_orphaned: bool = True,
        auto_fix_blocked: bool = False
    ) -> Dict[str, Any]:
        """
        Run a comprehensive health check with optional auto-fix for blocked tasks.

        This extends run_health_check() with the ability to automatically
        fail blocked tasks when detected.

        Args:
            alert_blocked: Whether to alert on blocked tasks
            alert_stale_threshold_minutes: Threshold for stale task alerts
            alert_orphaned: Whether to alert on fully orphaned tasks
            auto_fix_blocked: Whether to auto-fail blocked tasks

        Returns:
            Health check results with alert counts and auto-fix results
        """
        # Run the standard health check first
        results = await self.run_health_check(
            alert_blocked=alert_blocked,
            alert_stale_threshold_minutes=alert_stale_threshold_minutes,
            alert_orphaned=alert_orphaned
        )

        # Auto-fix blocked tasks if requested
        if auto_fix_blocked and results.get("blocked_tasks"):
            auto_fix_results = await self.auto_fail_blocked_tasks(limit=100)
            results["auto_fix"] = auto_fix_results

            if auto_fix_results.get("failed"):
                logger.info(
                    f"Auto-fix: Failed {len(auto_fix_results['failed'])} blocked tasks"
                )

        return results


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
