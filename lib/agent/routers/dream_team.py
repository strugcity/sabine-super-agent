"""
Dream Team Router - Task queue and orchestration endpoints.

Endpoints:
- POST /tasks - Create a new task
- GET /tasks/{id} - Get task details  
- And 24 more task-related endpoints
- GET /orchestration/status - Get orchestration status
- GET /roles - List available roles
- GET /repos - List valid repositories
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.services.task_queue import Task, get_task_queue_service
from backend.services.exceptions import (
    DependencyNotFoundError,
    CircularDependencyError,
    FailedDependencyError,
)
from lib.agent.shared import (
    verify_api_key,
    ROLE_REPO_AUTHORIZATION,
    VALID_REPOS,
    validate_role_repo_authorization,
    CreateTaskRequest,
    TaskResponse,
    CancelTaskRequest,
    RequeueTaskRequest,
)
# Import helper functions from task_runner module
from lib.agent.task_runner import _dispatch_task, _run_task_agent

logger = logging.getLogger(__name__)

# Create router (no prefix since we have multiple: /tasks, /orchestration, /roles, /repos)
router = APIRouter(tags=["dream-team"])


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/roles")
async def list_roles():
    """
    List all available roles for specialized agent personas.

    Roles are defined in docs/roles/*.md files and provide specialized
    system prompts for different agent behaviors (architect, backend, frontend, etc.).

    Returns role IDs and titles that can be passed to POST /invoke with the 'role' parameter.
    """
    try:
        from lib.agent.core import get_available_roles, load_role_manifest

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


@router.get("/repos")
async def list_repos():
    """
    List valid repositories and role-repository authorization mapping.

    This helps orchestrators understand which roles can target which repositories.
    """
    return {
        "success": True,
        "valid_repos": VALID_REPOS,
        "role_authorization": ROLE_REPO_AUTHORIZATION,
        "usage": "When creating tasks via POST /tasks, include 'target_repo' matching the role's authorization"
    }


@router.post("/tasks")
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


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, _: bool = Depends(verify_api_key)):
    """Get details of a specific task."""
    try:
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


@router.get("/tasks/{task_id}/dependencies")
async def get_task_dependencies(task_id: str, _: bool = Depends(verify_api_key)):
    """
    Get detailed dependency status for a task.

    Returns information about each dependency including:
    - Status (queued, in_progress, completed, failed)
    - Whether it's blocking this task
    - Error message if failed
    """
    try:
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


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    result: Optional[Dict] = None,
    _: bool = Depends(verify_api_key)
):
    """
    Mark a task as completed.

    This will trigger auto-dispatch of any dependent tasks.
    Only tasks in IN_PROGRESS status can be completed.
    """
    try:
        service = get_task_queue_service()

        # Set up dispatch callback if not already set
        if not service._dispatch_callback:
            service.set_dispatch_callback(_dispatch_task)

        op_result = await service.complete_task_result(UUID(task_id), result=result)

        if not op_result.success:
            error_msg = op_result.error.message if op_result.error else "Unknown error"
            status_code = op_result.error.status_code if op_result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

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


@router.post("/tasks/{task_id}/fail")
async def fail_task(
    task_id: str,
    error: str = "Unknown error",
    force: bool = False,
    _: bool = Depends(verify_api_key)
):
    """
    Mark a task as failed.

    Args:
        task_id: The task ID to fail
        error: Error message describing the failure
        force: If True, allow failing already-terminal tasks (admin override)
    """
    try:
        service = get_task_queue_service()
        result = await service.fail_task_result(UUID(task_id), error=error, force=force)

        if not result.success:
            error_msg = result.error.message if result.error else "Unknown error"
            status_code = result.error.status_code if result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

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


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    _: bool = Depends(verify_api_key)
):
    """
    Retry a failed task.

    Resets the task status to 'queued' so it can be dispatched again.
    Only works for tasks that are:
    - Currently in 'failed' status
    - Marked as retryable (is_retryable=True)
    - Have not exceeded max_retries
    """
    try:
        service = get_task_queue_service()
        result = await service.retry_task(UUID(task_id))

        if not result.success:
            error_msg = result.error.message if result.error else "Unknown error"
            status_code = result.error.status_code if result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

        return {
            "success": True,
            **result.data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retry task: {str(e)}")


@router.post("/tasks/{task_id}/force-retry")
async def force_retry_task(
    task_id: str,
    reason: str,
    _: bool = Depends(verify_api_key)
):
    """
    Force retry a failed task, bypassing retry limits.

    Use this when:
    - A task failed with is_retryable=False but the external issue was fixed
    - A task exceeded max_retries but the root cause was addressed
    - Manual operator intervention is needed

    Args:
        task_id: The task ID to force retry
        reason: Required reason for audit trail (why is this being force-retried?)
    """
    try:
        service = get_task_queue_service()
        result = await service.force_retry_task(UUID(task_id), reason=reason)

        if not result.success:
            error_msg = result.error.message if result.error else "Unknown error"
            status_code = result.error.status_code if result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

        return {
            "success": True,
            **result.data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error force-retrying task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to force-retry task: {str(e)}")


@router.post("/tasks/{task_id}/rerun")
async def rerun_task(
    task_id: str,
    reason: str,
    _: bool = Depends(verify_api_key)
):
    """
    Re-queue a completed task for re-execution.

    Use this when:
    - A task completed but needs to be run again
    - Results need to be regenerated
    - Downstream processing requires a fresh run

    Args:
        task_id: The task ID to rerun
        reason: Required reason for audit trail (why is this being rerun?)
    """
    try:
        service = get_task_queue_service()
        result = await service.rerun_task(UUID(task_id), reason=reason)

        if not result.success:
            error_msg = result.error.message if result.error else "Unknown error"
            status_code = result.error.status_code if result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

        return {
            "success": True,
            **result.data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rerunning task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rerun task: {str(e)}")


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Optional[CancelTaskRequest] = None,
    reason: Optional[str] = None,
    cascade: bool = True,
    _: bool = Depends(verify_api_key)
):
    """
    Cancel a queued task (mark as failed without running).

    Use this when:
    - A queued task is no longer needed
    - The task will never be able to run (known dependency issues)
    - Manual cleanup of orphaned tasks

    Args:
        task_id: The task ID to cancel
        request: Optional JSON body with reason, cancel_status, previous_status, cascade
        reason: Required reason for audit trail (why is this being cancelled?)
        cascade: If True, also cancel dependent queued tasks (default: True)
    """
    try:
        service = get_task_queue_service()
        if request is None:
            if not reason:
                raise HTTPException(status_code=400, detail="Reason is required for cancellation")
            request = CancelTaskRequest(reason=reason, cascade=cascade)

        result = await service.cancel_task(
            UUID(task_id),
            reason=request.reason,
            cancel_status=request.cancel_status,
            previous_status=request.previous_status,
            cascade=request.cascade
        )

        if not result.success:
            error_msg = result.error.message if result.error else "Unknown error"
            status_code = result.error.status_code if result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

        return {
            "success": True,
            **result.data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")


@router.get("/tasks/retryable")
async def get_retryable_tasks(
    limit: int = 10,
    _: bool = Depends(verify_api_key)
):
    """
    Get tasks that are eligible for retry.

    Returns failed tasks where:
    - is_retryable = True
    - retry_count < max_retries
    - next_retry_at <= now (backoff period has elapsed)
    """
    try:
        service = get_task_queue_service()
        tasks = await service.get_retryable_tasks(limit=limit)

        return {
            "success": True,
            "count": len(tasks),
            "tasks": [
                {
                    "id": str(task.id),
                    "role": task.role,
                    "retry_count": task.retry_count,
                    "max_retries": task.max_retries,
                    "next_retry_at": task.next_retry_at.isoformat() if task.next_retry_at else None,
                    "error": task.error,
                    "created_at": task.created_at.isoformat() if task.created_at else None
                }
                for task in tasks
            ]
        }

    except Exception as e:
        logger.error(f"Error getting retryable tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get retryable tasks: {str(e)}")


@router.post("/tasks/retry-all")
async def retry_all_eligible_tasks(
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key)
):
    """
    Process all tasks that are ready for retry.

    This triggers retry for all eligible tasks in the background.
    """
    try:
        service = get_task_queue_service()
        result = await service.process_retryable_tasks()

        return {
            "success": True,
            **result
        }

    except Exception as e:
        logger.error(f"Error processing retryable tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process retryable tasks: {str(e)}")


@router.get("/tasks/stuck")
async def get_stuck_tasks(
    limit: int = 10,
    _: bool = Depends(verify_api_key)
):
    """
    Get tasks that appear to be stuck (IN_PROGRESS longer than timeout).

    Returns tasks where:
    - status = 'in_progress'
    - started_at + timeout_seconds < now
    """
    try:
        service = get_task_queue_service()
        tasks = await service.get_stuck_tasks(limit=limit)

        return {
            "success": True,
            "count": len(tasks),
            "tasks": [
                {
                    "id": str(task.id),
                    "role": task.role,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "timeout_seconds": task.timeout_seconds,
                    "last_heartbeat_at": task.last_heartbeat_at.isoformat() if task.last_heartbeat_at else None,
                    "retry_count": task.retry_count,
                    "max_retries": task.max_retries,
                    "error": task.error
                }
                for task in tasks
            ]
        }

    except Exception as e:
        logger.error(f"Error getting stuck tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stuck tasks: {str(e)}")


@router.post("/tasks/{task_id}/heartbeat")
async def update_task_heartbeat(
    task_id: str,
    _: bool = Depends(verify_api_key)
):
    """
    Update the heartbeat timestamp for a running task.

    Long-running tasks should call this periodically to prevent
    being detected as stuck by the watchdog.
    """
    try:
        service = get_task_queue_service()
        success = await service.update_heartbeat(UUID(task_id))

        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Could not update heartbeat for task {task_id}"
            )

        return {
            "success": True,
            "task_id": task_id,
            "heartbeat_at": datetime.now(timezone.utc).isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating heartbeat for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update heartbeat: {str(e)}")


@router.post("/tasks/{task_id}/requeue")
async def requeue_stuck_task(
    task_id: str,
    request: Optional[RequeueTaskRequest] = None,
    error: str = "Manually requeued",
    _: bool = Depends(verify_api_key)
):
    """
    Requeue a stuck task (reset to queued status).

    Accepts an optional JSON body with reason, clear_error, and clear_result fields.
    Falls back to the legacy query-param interface when no body is provided.
    """
    try:
        service = get_task_queue_service()
        if request is None:
            request = RequeueTaskRequest(reason=error)

        result = await service.requeue_task(
            UUID(task_id),
            reason=request.reason,
            clear_error=request.clear_error,
            clear_result=request.clear_result
        )

        if not result.success:
            error_msg = result.error.message if result.error else "Unknown error"
            status_code = result.error.status_code if result.error else 400
            raise HTTPException(status_code=status_code, detail=error_msg)

        return {
            "success": True,
            **result.data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error requeuing task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to requeue task: {str(e)}")


@router.post("/tasks/watchdog")
async def run_watchdog(
    _: bool = Depends(verify_api_key)
):
    """
    Run the stuck task watchdog.

    Finds all stuck tasks (IN_PROGRESS longer than timeout) and either:
    - Requeues them for retry (if retry_count < max_retries)
    - Marks as permanently failed (if max retries exceeded)

    Also sends a Slack alert if any stuck tasks are found.
    """
    try:
        from lib.agent.slack_manager import send_stuck_task_alert

        service = get_task_queue_service()
        result = await service.process_stuck_tasks()

        # Send Slack alert if any stuck tasks were processed
        if result["processed"] > 0:
            all_stuck = result["requeued"] + result["failed"]
            await send_stuck_task_alert(
                stuck_tasks=all_stuck,
                requeued_count=len(result["requeued"]),
                failed_count=len(result["failed"])
            )

        return {
            "success": True,
            **result
        }

    except Exception as e:
        logger.error(f"Error running watchdog: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to run watchdog: {str(e)}")


@router.get("/tasks/health")
async def get_task_queue_health(
    _: bool = Depends(verify_api_key)
):
    """
    Get task queue health metrics.

    Returns overall health status including:
    - total_queued: Tasks waiting to run
    - total_in_progress: Tasks currently running
    - blocked_by_failed_deps: Tasks blocked by failed dependencies
    - stale_queued_1h: Tasks queued over 1 hour
    - stale_queued_24h: Tasks queued over 24 hours
    - stuck_tasks: In-progress tasks past their timeout
    - pending_retries: Failed tasks eligible for retry
    """
    try:
        service = get_task_queue_service()
        health = await service.get_task_queue_health()

        # Determine if there are any issues
        issues = (
            health.get("blocked_by_failed_deps", 0) > 0 or
            health.get("stale_queued_24h", 0) > 0 or
            health.get("stuck_tasks", 0) > 0
        )

        return {
            "success": True,
            "healthy": not issues,
            "metrics": health
        }

    except Exception as e:
        logger.error(f"Error getting task queue health: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get health: {str(e)}")


@router.get("/tasks/blocked")
async def get_blocked_tasks(
    limit: int = 50,
    _: bool = Depends(verify_api_key)
):
    """
    Get tasks blocked by failed dependencies.

    These tasks will never run without manual intervention because
    at least one of their dependencies has failed.
    """
    try:
        service = get_task_queue_service()
        blocked = await service.get_blocked_tasks(limit=limit)

        return {
            "success": True,
            "count": len(blocked),
            "tasks": blocked
        }

    except Exception as e:
        logger.error(f"Error getting blocked tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get blocked tasks: {str(e)}")


@router.get("/tasks/stale")
async def get_stale_tasks(
    threshold_minutes: int = 60,
    limit: int = 50,
    _: bool = Depends(verify_api_key)
):
    """
    Get tasks that have been queued for too long.

    Args:
        threshold_minutes: How long is considered "too long" (default: 60)
        limit: Maximum results to return
    """
    try:
        service = get_task_queue_service()
        stale = await service.get_stale_queued_tasks(
            threshold_minutes=threshold_minutes,
            limit=limit
        )

        return {
            "success": True,
            "count": len(stale),
            "threshold_minutes": threshold_minutes,
            "tasks": stale
        }

    except Exception as e:
        logger.error(f"Error getting stale tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stale tasks: {str(e)}")


@router.get("/tasks/orphaned")
async def get_orphaned_tasks(
    limit: int = 50,
    _: bool = Depends(verify_api_key)
):
    """
    Get tasks where ALL dependencies have failed.

    These tasks have zero chance of running without recreating
    their entire dependency chain.
    """
    try:
        service = get_task_queue_service()
        orphaned = await service.get_orphaned_tasks(limit=limit)

        return {
            "success": True,
            "count": len(orphaned),
            "tasks": orphaned
        }

    except Exception as e:
        logger.error(f"Error getting orphaned tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get orphaned tasks: {str(e)}")


@router.post("/tasks/health-check")
async def run_health_check(
    alert_blocked: bool = True,
    alert_stale_threshold_minutes: int = 60,
    alert_orphaned: bool = True,
    auto_fix_blocked: bool = False,
    _: bool = Depends(verify_api_key)
):
    """
    Run a comprehensive health check with alerts and optional auto-fix.

    This endpoint should be called periodically by a scheduler or
    monitoring system (e.g., every 5-10 minutes).

    Args:
        alert_blocked: Whether to alert on blocked tasks (default: True)
        alert_stale_threshold_minutes: Stale task threshold (default: 60)
        alert_orphaned: Whether to alert on orphaned tasks (default: True)
        auto_fix_blocked: Whether to auto-fail blocked tasks (default: False)

    Returns health check results including alert counts and auto-fix results.
    """
    try:
        service = get_task_queue_service()

        if auto_fix_blocked:
            # Use the extended version with auto-fix
            result = await service.run_health_check_with_auto_fix(
                alert_blocked=alert_blocked,
                alert_stale_threshold_minutes=alert_stale_threshold_minutes,
                alert_orphaned=alert_orphaned,
                auto_fix_blocked=True
            )
        else:
            result = await service.run_health_check(
                alert_blocked=alert_blocked,
                alert_stale_threshold_minutes=alert_stale_threshold_minutes,
                alert_orphaned=alert_orphaned
            )

        return {
            "success": True,
            **result
        }

    except Exception as e:
        logger.error(f"Error running health check: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to run health check: {str(e)}")


@router.post("/tasks/auto-fail-blocked")
async def auto_fail_blocked_tasks(
    limit: int = 100,
    _: bool = Depends(verify_api_key)
):
    """
    Automatically fail all tasks blocked by failed dependencies.

    This is a cleanup operation that finds tasks with failed dependencies
    and fails them with cascade=True, preventing orphaned chains.

    Args:
        limit: Maximum number of blocked tasks to process (default: 100)

    Returns results including count of tasks failed and any errors.
    """
    try:
        service = get_task_queue_service()
        result = await service.auto_fail_blocked_tasks(limit=limit)

        return {
            "success": True,
            **result
        }

    except Exception as e:
        logger.error(f"Error auto-failing blocked tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to auto-fail blocked tasks: {str(e)}")


@router.post("/tasks/dispatch")
async def dispatch_tasks(
    background_tasks: BackgroundTasks,
    max_tasks: int = 10,
    _: bool = Depends(verify_api_key)
):
    """
    Manually trigger dispatch of all unblocked tasks.

    Uses atomic claiming with FOR UPDATE SKIP LOCKED to prevent race conditions.
    Multiple workers can safely call this endpoint simultaneously - each task
    will only be dispatched once.

    Args:
        max_tasks: Maximum number of tasks to dispatch (default: 10)
    """
    try:
        service = get_task_queue_service()

        # Use atomic claim to prevent race conditions
        # This claims and returns tasks in a single atomic operation
        claimed_tasks = await service.claim_unblocked_tasks_atomic(max_tasks=max_tasks)

        if not claimed_tasks:
            return {
                "success": True,
                "dispatched": 0,
                "message": "No unblocked tasks to dispatch"
            }

        dispatched = []
        for task in claimed_tasks:
            logger.info(f"Handshake: Dispatching Task {task.id} to {task.role}")
            # Run in background to not block the response
            # Task is already claimed atomically, so use fresh task data
            background_tasks.add_task(_run_task_agent, task)
            dispatched.append({
                "task_id": str(task.id),
                "role": task.role
            })

        return {
            "success": True,
            "dispatched": len(dispatched),
            "tasks": dispatched,
            "message": f"Dispatched {len(dispatched)} tasks (atomic claim)"
        }

    except Exception as e:
        logger.error(f"Error dispatching tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to dispatch tasks: {str(e)}")


@router.get("/orchestration/status")
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
