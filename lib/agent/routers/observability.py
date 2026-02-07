"""
Observability Router - Health, metrics, and monitoring endpoints.

Endpoints:
- GET / - Root endpoint
- GET /health - System health check
- GET /tools - List available tools
- GET /tools/diagnostics - MCP diagnostics
- And many more observability endpoints
"""

import logging
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

# Import core functions and services
from lib.agent.core import run_agent, get_cache_metrics, reset_cache_metrics
from lib.agent.registry import get_all_tools, get_mcp_diagnostics, MCP_SERVERS
from lib.agent.scheduler import get_scheduler
from backend.services.wal import WALService
from backend.services.task_queue import get_task_queue_service

# Import from server.py for auth
from lib.agent.server import verify_api_key

logger = logging.getLogger(__name__)


# =============================================================================
# Response Models
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    tools_loaded: int
    database_connected: bool


class TriggerBriefingRequest(BaseModel):
    """Request body for manual briefing trigger."""
    user_name: str = Field(default="Paul", description="Name to use in greeting")
    phone_number: Optional[str] = Field(
        default=None, description="Override phone number (uses USER_PHONE env var if not provided)")
    skip_sms: bool = Field(
        default=False, description="Skip sending SMS (just generate briefing)")


# =============================================================================
# Router Setup
# =============================================================================

# Create router (no prefix - mixed paths)
router = APIRouter(tags=["observability"])


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/")
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


@router.get("/cache/metrics")
async def cache_metrics():
    """
    Get prompt caching metrics.

    Returns statistics on cache hit rate, token savings, and latency.
    """
    return {
        "success": True,
        "metrics": get_cache_metrics()
    }


@router.post("/cache/reset")
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

@router.get("/wal/stats")
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


@router.get("/wal/pending")
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


@router.get("/wal/failed")
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


@router.get("/health", response_model=HealthResponse)
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


@router.get("/tools")
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


@router.get("/tools/diagnostics")
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


@router.get("/e2b/test")
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


# =============================================================================
# Metrics Endpoints
# =============================================================================

@router.post("/metrics/record")
async def record_metrics(
    _: bool = Depends(verify_api_key)
):
    """
    Record current metrics snapshot to time-series tables.

    This should be called periodically by a scheduler (e.g., every 5 minutes)
    to build up historical trend data.

    Records:
    - Queue depth and health metrics
    - Role-level performance metrics
    """
    try:
        service = get_task_queue_service()

        # Record task metrics
        task_metrics_id = await service.record_task_metrics()

        # Record role metrics
        roles_recorded = await service.record_role_metrics()

        return {
            "success": True,
            "task_metrics_id": task_metrics_id,
            "roles_recorded": roles_recorded
        }

    except Exception as e:
        logger.error(f"Error recording metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record metrics: {str(e)}")


@router.get("/metrics/latest")
async def get_latest_metrics(
    _: bool = Depends(verify_api_key)
):
    """
    Get the most recent metrics snapshot.

    Returns the latest recorded metrics including queue depth,
    success rates, and duration statistics.
    """
    try:
        service = get_task_queue_service()
        metrics = await service.get_latest_metrics()

        if not metrics:
            return {
                "success": True,
                "metrics": None,
                "message": "No metrics recorded yet. Call POST /metrics/record first."
            }

        return {
            "success": True,
            "metrics": metrics
        }

    except Exception as e:
        logger.error(f"Error getting latest metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@router.get("/metrics/trend")
async def get_metrics_trend(
    hours: int = 24,
    _: bool = Depends(verify_api_key)
):
    """
    Get metrics trend over the specified time period.

    Args:
        hours: Number of hours to look back (default: 24)

    Returns time-series data for queue depth, success rates, and health.
    """
    try:
        service = get_task_queue_service()
        trend = await service.get_metrics_trend(hours=hours)

        return {
            "success": True,
            "hours": hours,
            "data_points": len(trend),
            "trend": trend
        }

    except Exception as e:
        logger.error(f"Error getting metrics trend: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get trend: {str(e)}")


@router.get("/metrics/roles")
async def get_role_performance(
    hours: int = 24,
    _: bool = Depends(verify_api_key)
):
    """
    Get performance metrics broken down by agent role.

    Args:
        hours: Time window in hours (default: 24)

    Returns success rates, duration stats, and failure counts per role.
    """
    try:
        service = get_task_queue_service()
        roles = await service.get_role_performance(hours=hours)

        return {
            "success": True,
            "hours": hours,
            "roles": roles
        }

    except Exception as e:
        logger.error(f"Error getting role performance: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get role metrics: {str(e)}")


@router.get("/metrics/errors")
async def get_error_breakdown(
    hours: int = 24,
    _: bool = Depends(verify_api_key)
):
    """
    Get error breakdown by error type.

    Args:
        hours: Time window in hours (default: 24)

    Returns error counts and percentages by category.
    """
    try:
        service = get_task_queue_service()
        errors = await service.get_error_breakdown(hours=hours)

        return {
            "success": True,
            "hours": hours,
            "errors": errors
        }

    except Exception as e:
        logger.error(f"Error getting error breakdown: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get error breakdown: {str(e)}")


@router.get("/metrics/prometheus")
async def get_prometheus_metrics():
    """
    Get metrics in Prometheus text format.

    This endpoint can be scraped by Prometheus for monitoring.
    No authentication required for scraping compatibility.
    """
    try:
        service = get_task_queue_service()
        health = await service.get_task_queue_health()
        latest = await service.get_latest_metrics()

        # Build Prometheus text format
        lines = [
            "# HELP dream_team_queue_depth Number of tasks in queue by status",
            "# TYPE dream_team_queue_depth gauge",
            f'dream_team_queue_depth{{status="queued"}} {health.get("total_queued", 0)}',
            f'dream_team_queue_depth{{status="in_progress"}} {health.get("total_in_progress", 0)}',
            "",
            "# HELP dream_team_blocked_tasks Tasks blocked by failed dependencies",
            "# TYPE dream_team_blocked_tasks gauge",
            f"dream_team_blocked_tasks {health.get('blocked_by_failed_deps', 0)}",
            "",
            "# HELP dream_team_stuck_tasks Tasks stuck past timeout",
            "# TYPE dream_team_stuck_tasks gauge",
            f"dream_team_stuck_tasks {health.get('stuck_tasks', 0)}",
            "",
            "# HELP dream_team_stale_tasks Tasks queued too long",
            "# TYPE dream_team_stale_tasks gauge",
            f'dream_team_stale_tasks{{threshold="1h"}} {health.get("stale_queued_1h", 0)}',
            f'dream_team_stale_tasks{{threshold="24h"}} {health.get("stale_queued_24h", 0)}',
            "",
            "# HELP dream_team_pending_retries Failed tasks pending retry",
            "# TYPE dream_team_pending_retries gauge",
            f"dream_team_pending_retries {health.get('pending_retries', 0)}",
        ]

        # Add metrics from latest snapshot if available
        if latest:
            lines.extend([
                "",
                "# HELP dream_team_success_rate_1h Task success rate in last hour",
                "# TYPE dream_team_success_rate_1h gauge",
                f"dream_team_success_rate_1h {latest.get('success_rate_1h', 0) or 0}",
                "",
                "# HELP dream_team_completed_1h Tasks completed in last hour",
                "# TYPE dream_team_completed_1h counter",
                f"dream_team_completed_1h {latest.get('total_completed_1h', 0)}",
                "",
                "# HELP dream_team_failed_1h Tasks failed in last hour",
                "# TYPE dream_team_failed_1h counter",
                f"dream_team_failed_1h {latest.get('total_failed_1h', 0)}",
                "",
                "# HELP dream_team_task_duration_ms Task duration in milliseconds",
                "# TYPE dream_team_task_duration_ms gauge",
                f'dream_team_task_duration_ms{{quantile="avg"}} {latest.get("avg_duration_ms", 0) or 0}',
                f'dream_team_task_duration_ms{{quantile="p95"}} {latest.get("p95_duration_ms", 0) or 0}',
            ])

        return PlainTextResponse(
            content="\n".join(lines) + "\n",
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    except Exception as e:
        logger.error(f"Error generating Prometheus metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate metrics: {str(e)}")


# =============================================================================
# Audit Endpoints
# =============================================================================

@router.get("/audit/tools")
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


@router.get("/audit/stats")
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


# =============================================================================
# Test Endpoint
# =============================================================================

@router.post("/test")
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


# =============================================================================
# Scheduler Endpoints
# =============================================================================

@router.get("/scheduler/status")
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


@router.post("/scheduler/trigger-briefing")
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
