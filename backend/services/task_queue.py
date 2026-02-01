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
            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.IN_PROGRESS.value
            }).eq("id", str(task_id)).eq("status", TaskStatus.QUEUED.value).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Claimed task {task_id}")
                return OperationResult.ok({"task_id": str(task_id)})

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

    async def fail_task(self, task_id: UUID, error: str) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: The task ID to fail
            error: Error message/description

        Returns:
            True if updated successfully, False otherwise

        Note: For better error handling, use fail_task_result() instead.
        """
        op_result = await self.fail_task_result(task_id, error)
        return op_result.success

    async def fail_task_result(self, task_id: UUID, error: str) -> OperationResult:
        """
        Mark a task as failed with structured error handling.

        Args:
            task_id: The task ID to fail
            error: Error message/description

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
            response = self.client.table(TASK_QUEUE_TABLE).update({
                "status": TaskStatus.FAILED.value,
                "error": error
            }).eq("id", str(task_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Failed task {task_id}: {error}")
                return OperationResult.ok({"task_id": str(task_id), "error": error})

            logger.warning(f"Could not fail task {task_id}")
            return OperationResult.fail(
                TaskNotFoundError(task_id=str(task_id))
            )

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

    # =========================================================================
    # Dependency Validation
    # =========================================================================

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
            # Fetch all dependency tasks
            dep_ids_str = [str(d) for d in depends_on]
            response = self.client.table(TASK_QUEUE_TABLE).select(
                "id", "status", "depends_on", "error"
            ).in_("id", dep_ids_str).execute()

            found_tasks = {row["id"]: row for row in (response.data or [])}

            # Check 1: All dependencies must exist
            for dep_id in depends_on:
                if str(dep_id) not in found_tasks:
                    return OperationResult.fail(
                        DependencyNotFoundError(
                            task_id=str(new_task_id) if new_task_id else None,
                            missing_dependency_id=str(dep_id)
                        )
                    )

            # Check 2: No failed dependencies
            for dep_id_str, task_data in found_tasks.items():
                if task_data["status"] == TaskStatus.FAILED.value:
                    return OperationResult.fail(
                        FailedDependencyError(
                            task_id=str(new_task_id) if new_task_id else None,
                            failed_dependency_id=dep_id_str,
                            failure_reason=task_data.get("error")
                        )
                    )

            # Check 3: No circular dependencies
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

            # Get the dependency's dependencies
            task_data = found_tasks.get(dep_id_str)
            if task_data and task_data.get("depends_on"):
                # Fetch nested dependencies if not already fetched
                nested_deps = task_data["depends_on"]
                if nested_deps:
                    # Convert to UUIDs
                    nested_dep_uuids = [
                        UUID(d) if isinstance(d, str) else d
                        for d in nested_deps
                    ]

                    # Fetch any unfetched tasks
                    unfetched = [
                        str(d) for d in nested_dep_uuids
                        if str(d) not in found_tasks
                    ]
                    if unfetched and self.client:
                        response = self.client.table(TASK_QUEUE_TABLE).select(
                            "id", "status", "depends_on", "error"
                        ).in_("id", unfetched).execute()

                        for row in (response.data or []):
                            found_tasks[row["id"]] = row

                    # Recurse
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
