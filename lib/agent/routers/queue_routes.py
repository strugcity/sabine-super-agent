"""
Queue Management Router - Health, stats, and enqueue endpoints for the rq job queue.

Provides operational visibility into the Slow Path job queue (ADR-002).

Endpoints:
- GET  /api/queue/health       - Redis + queue health status
- POST /api/queue/enqueue      - Manual enqueue a WAL entry (testing)
- GET  /api/queue/stats        - Detailed queue statistics
- POST /api/queue/retry-failed - Re-enqueue all failed jobs
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# Lazy imports for queue/redis services are done inside handlers to avoid
# circular dependencies and import-time side effects (per CLAUDE.md rules).

from lib.agent.shared import verify_api_key

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic v2 Request / Response Models
# =============================================================================

class QueueHealthResponse(BaseModel):
    """Response model for GET /api/queue/health."""

    redis_connected: bool = Field(
        ..., description="Whether Redis PING succeeded"
    )
    queue_name: str = Field(
        ..., description="Name of the rq queue"
    )
    pending_jobs: int = Field(
        default=0, description="Number of jobs waiting to be picked up"
    )
    failed_jobs: int = Field(
        default=0, description="Number of jobs in the failed registry"
    )
    workers: int = Field(
        default=0, description="Number of active workers on this queue"
    )
    redis_ping_ms: Optional[float] = Field(
        default=None,
        description="Redis PING round-trip latency in milliseconds",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if health check failed",
    )


class EnqueueRequest(BaseModel):
    """Request body for POST /api/queue/enqueue."""

    wal_entry_id: str = Field(
        ..., description="UUID of the WAL entry to enqueue"
    )
    priority: str = Field(
        default="default",
        description="Job priority: high, default, or low",
    )


class EnqueueResponse(BaseModel):
    """Response model for POST /api/queue/enqueue."""

    job_id: Optional[str] = Field(
        default=None, description="rq job ID (None if enqueue failed)"
    )
    status: str = Field(
        ..., description="Result status: enqueued or failed"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if enqueue failed"
    )


class QueueStatsResponse(BaseModel):
    """Response model for GET /api/queue/stats."""

    queue_name: str = Field(..., description="Name of the rq queue")
    pending: int = Field(default=0, description="Jobs waiting to run")
    started: int = Field(default=0, description="Jobs currently executing")
    failed: int = Field(default=0, description="Jobs in the failed registry")
    completed: int = Field(
        default=0, description="Jobs in the finished registry"
    )
    workers: int = Field(default=0, description="Active workers")
    error: Optional[str] = Field(
        default=None,
        description="Error message if stats retrieval failed",
    )


class RetryFailedResponse(BaseModel):
    """Response model for POST /api/queue/retry-failed."""

    requeued: int = Field(
        default=0, description="Number of failed jobs requeued"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Errors encountered while requeuing",
    )


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/api/queue", tags=["queue"])


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/health", response_model=QueueHealthResponse)
async def queue_health(_: bool = Depends(verify_api_key)) -> QueueHealthResponse:
    """
    Return queue health status including Redis connectivity and job counts.

    This is a lightweight probe suitable for monitoring dashboards.
    """
    # Lazy imports to avoid import-time side effects
    from backend.services.redis_client import check_redis_health
    from backend.services.queue import get_queue_stats, QUEUE_NAME

    try:
        redis_health = await check_redis_health()
        stats = get_queue_stats()

        return QueueHealthResponse(
            redis_connected=redis_health.connected,
            queue_name=QUEUE_NAME,
            pending_jobs=stats.get("pending", 0),
            failed_jobs=stats.get("failed", 0),
            workers=stats.get("workers", 0),
            redis_ping_ms=redis_health.ping_ms if redis_health.connected else None,
            error=redis_health.error,
        )
    except Exception as exc:
        logger.error("Queue health check failed: %s", exc, exc_info=True)
        return QueueHealthResponse(
            redis_connected=False,
            queue_name="sabine-slow-path",
            error=str(exc),
        )


@router.post("/enqueue", response_model=EnqueueResponse, status_code=202)
async def enqueue_wal_entry(
    request: EnqueueRequest,
    _: bool = Depends(verify_api_key),
) -> EnqueueResponse:
    """
    Manually enqueue a WAL entry for Slow Path processing.

    Intended for testing and backfill scenarios.  In production the WAL-queue
    bridge enqueues entries automatically after WAL writes.
    """
    from backend.services.queue import enqueue_wal_processing

    if not request.wal_entry_id:
        raise HTTPException(
            status_code=422,
            detail="wal_entry_id must be a non-empty string",
        )

    try:
        job_id = enqueue_wal_processing(
            wal_entry_id=request.wal_entry_id,
            priority=request.priority,
        )
        if job_id:
            logger.info(
                "Manually enqueued WAL entry %s as job %s",
                request.wal_entry_id,
                job_id,
            )
            return EnqueueResponse(job_id=job_id, status="enqueued")

        return EnqueueResponse(
            status="failed",
            error="Enqueue returned None (queue may be unavailable)",
        )
    except Exception as exc:
        logger.error(
            "Failed to enqueue WAL entry %s: %s",
            request.wal_entry_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Failed to enqueue WAL entry: {exc}",
        )


@router.get("/stats", response_model=QueueStatsResponse)
async def queue_stats(_: bool = Depends(verify_api_key)) -> QueueStatsResponse:
    """
    Return detailed queue statistics.

    Provides a richer snapshot than the health endpoint, including
    started (in-flight) and completed job counts.
    """
    from backend.services.queue import get_queue_stats

    try:
        raw_stats = get_queue_stats()
        return QueueStatsResponse(**raw_stats)
    except Exception as exc:
        logger.error("Failed to retrieve queue stats: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Failed to retrieve queue stats: {exc}",
        )


@router.post("/retry-failed", response_model=RetryFailedResponse)
async def retry_failed_jobs(
    _: bool = Depends(verify_api_key),
) -> RetryFailedResponse:
    """
    Re-enqueue all jobs in the failed registry.

    Each failed job is re-submitted to the queue with default priority.
    Jobs that cannot be requeued are reported in the ``errors`` list.
    """
    try:
        # Lazy imports
        from rq import Queue  # type: ignore[import-untyped]
        from backend.services.redis_client import get_redis_client
        from backend.services.queue import QUEUE_NAME

        conn = get_redis_client()
        queue = Queue(QUEUE_NAME, connection=conn)

        failed_registry = queue.failed_job_registry
        failed_job_ids = failed_registry.get_job_ids()

        requeued = 0
        errors: list[str] = []

        for job_id in failed_job_ids:
            try:
                failed_registry.requeue(job_id)
                requeued += 1
                logger.info("Requeued failed job %s", job_id)
            except Exception as requeue_exc:
                msg = f"Failed to requeue job {job_id}: {requeue_exc}"
                logger.warning(msg)
                errors.append(msg)

        logger.info(
            "Retry-failed complete: %d requeued, %d errors",
            requeued,
            len(errors),
        )
        return RetryFailedResponse(requeued=requeued, errors=errors)

    except ImportError:
        logger.error("rq package is not installed")
        raise HTTPException(
            status_code=503,
            detail="rq package not installed. Install with: pip install rq",
        )
    except Exception as exc:
        logger.error(
            "Failed to retry failed jobs: %s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=503,
            detail=f"Failed to retry failed jobs: {exc}",
        )
