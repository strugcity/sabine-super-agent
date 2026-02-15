"""
Archive Configuration Router (MEM-004)
========================================

API endpoints for managing per-user archive configuration and
triggering manual archival operations.

Endpoints:
- GET   /api/archive/config  -- Get current archive config for user (or defaults)
- PUT   /api/archive/config  -- Update archive config for user
- POST  /api/archive/trigger -- Manually trigger archival (or dry-run)
- GET   /api/archive/stats   -- Archive statistics for user

Config is stored in Redis: ``sabine:archive_config:{user_id}``

PRD Reference: MEM-004 (Archive Configuration API)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.agent.shared import verify_api_key

logger = logging.getLogger(__name__)

# Redis key prefix for per-user archive config
_REDIS_KEY_PREFIX: str = "sabine:archive_config"

# TTL for cached config in Redis (30 days)
_CONFIG_TTL: int = 30 * 86_400

# Default archive settings (matching backend/worker/salience_job.py constants)
_DEFAULT_CONFIG: Dict[str, Any] = {
    "threshold": 0.2,
    "min_age_days": 90,
    "max_access_count": 2,
}

# Create router with /api/archive prefix
router = APIRouter(prefix="/api/archive", tags=["archive-config"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ArchiveConfigResponse(BaseModel):
    """Response body for archive configuration queries."""
    threshold: float = Field(
        ..., description="Salience score threshold for archival (0.0-1.0)",
    )
    min_age_days: int = Field(
        ..., description="Minimum age in days before a memory can be archived",
    )
    max_access_count: int = Field(
        ..., description="Maximum access count for archival eligibility",
    )
    is_default: bool = Field(
        ..., description="True if these are default settings (no custom override stored)",
    )


class ArchiveConfigRequest(BaseModel):
    """Request body for updating archive configuration."""
    threshold: float = Field(
        ..., ge=0.0, le=1.0,
        description="Salience score threshold for archival (0.0-1.0)",
    )
    min_age_days: int = Field(
        ..., gt=0,
        description="Minimum age in days before a memory can be archived (must be > 0)",
    )
    max_access_count: int = Field(
        ..., ge=0,
        description="Maximum access count for archival eligibility (>= 0)",
    )


class ArchiveTriggerRequest(BaseModel):
    """Request body for manually triggering archival."""
    threshold: float = Field(
        default=0.2, ge=0.0, le=1.0,
        description="Salience score threshold for archival (0.0-1.0)",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, return count of memories that would be archived without archiving",
    )


class ArchiveTriggerResponse(BaseModel):
    """Response body from an archive trigger operation."""
    status: str = Field(
        ..., description="Job status: 'queued', 'completed', or 'dry_run'",
    )
    job_id: Optional[str] = Field(
        default=None, description="rq job ID (None for dry-run or direct completion)",
    )
    estimated_count: int = Field(
        ..., description="Number of memories that would be (or were) archived",
    )


class ArchiveStatsResponse(BaseModel):
    """Response body for archive statistics."""
    total_archived: int = Field(
        ..., description="Total number of archived memories",
    )
    last_archive_run: Optional[str] = Field(
        default=None,
        description="ISO timestamp of the most recently archived memory (or null)",
    )
    avg_salience_of_archived: Optional[float] = Field(
        default=None,
        description="Average salience score of archived memories (or null if none)",
    )


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/config", response_model=ArchiveConfigResponse)
async def get_archive_config(
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> ArchiveConfigResponse:
    """
    Get current archive configuration for a user.

    Returns the user-specific config stored in Redis, or the default
    config if no custom settings have been saved.

    Parameters
    ----------
    user_id : str
        User UUID to look up config for.

    Returns
    -------
    ArchiveConfigResponse
        Current config with ``is_default`` flag.
    """
    logger.info("Getting archive config for user %s", user_id)

    try:
        redis_client = _get_redis()
        key = f"{_REDIS_KEY_PREFIX}:{user_id}"
        raw: Optional[str] = redis_client.get(key)

        if raw is not None:
            data: Dict[str, Any] = json.loads(raw)
            logger.debug("Found custom archive config for user %s: %s", user_id, data)
            return ArchiveConfigResponse(
                threshold=data.get("threshold", _DEFAULT_CONFIG["threshold"]),
                min_age_days=data.get("min_age_days", _DEFAULT_CONFIG["min_age_days"]),
                max_access_count=data.get("max_access_count", _DEFAULT_CONFIG["max_access_count"]),
                is_default=False,
            )

        logger.debug("No custom archive config for user %s; returning defaults", user_id)
        return ArchiveConfigResponse(
            **_DEFAULT_CONFIG,
            is_default=True,
        )

    except Exception as exc:
        logger.error("Failed to get archive config: %s", exc, exc_info=True)
        # Fall back to defaults on Redis failure
        return ArchiveConfigResponse(
            **_DEFAULT_CONFIG,
            is_default=True,
        )


@router.put("/config", response_model=ArchiveConfigResponse)
async def update_archive_config(
    request: ArchiveConfigRequest,
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> ArchiveConfigResponse:
    """
    Update archive configuration for a user.

    Validates constraints and persists to Redis with a 30-day TTL.

    Parameters
    ----------
    request : ArchiveConfigRequest
        New configuration values.
    user_id : str
        User UUID.

    Returns
    -------
    ArchiveConfigResponse
        Updated configuration.

    Raises
    ------
    HTTPException (500)
        If Redis write fails.
    """
    logger.info("Updating archive config for user %s", user_id)

    config_data: Dict[str, Any] = {
        "threshold": request.threshold,
        "min_age_days": request.min_age_days,
        "max_access_count": request.max_access_count,
    }

    try:
        redis_client = _get_redis()
        key = f"{_REDIS_KEY_PREFIX}:{user_id}"
        redis_client.setex(key, _CONFIG_TTL, json.dumps(config_data))

        logger.info(
            "Saved archive config for user %s: %s",
            user_id, config_data,
        )

        return ArchiveConfigResponse(
            **config_data,
            is_default=False,
        )

    except Exception as exc:
        logger.error("Failed to save archive config: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save archive config: {str(exc)}",
        )


@router.post("/trigger", response_model=ArchiveTriggerResponse)
async def trigger_archive(
    request: ArchiveTriggerRequest,
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> ArchiveTriggerResponse:
    """
    Manually trigger memory archival.

    If ``dry_run`` is true, returns the count of memories that would be
    archived without actually archiving them.  Otherwise, enqueues the
    ``run_archive_job`` for background execution via rq.

    Parameters
    ----------
    request : ArchiveTriggerRequest
        Trigger parameters (threshold, dry_run).
    user_id : str
        User UUID.

    Returns
    -------
    ArchiveTriggerResponse
        Status, job ID (if queued), and estimated count.

    Raises
    ------
    HTTPException (500)
        If the count query or job enqueue fails.
    """
    logger.info(
        "Archive trigger for user %s  threshold=%.2f  dry_run=%s",
        user_id, request.threshold, request.dry_run,
    )

    # Estimate the number of candidate memories
    estimated_count = _count_archive_candidates(request.threshold)

    if request.dry_run:
        logger.info("Dry-run archive: %d candidates", estimated_count)
        return ArchiveTriggerResponse(
            status="dry_run",
            job_id=None,
            estimated_count=estimated_count,
        )

    # Enqueue the actual archive job via rq
    try:
        job_id = _enqueue_archive_job(threshold=request.threshold)

        if job_id is not None:
            logger.info(
                "Enqueued archive job %s for user %s  threshold=%.2f",
                job_id, user_id, request.threshold,
            )
            return ArchiveTriggerResponse(
                status="queued",
                job_id=job_id,
                estimated_count=estimated_count,
            )

        # If enqueue returned None (queue unavailable), log and raise
        logger.error("Archive job enqueue returned None for user %s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to enqueue archive job: queue unavailable",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to enqueue archive job: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue archive job: {str(exc)}",
        )


@router.get("/stats", response_model=ArchiveStatsResponse)
async def get_archive_stats(
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> ArchiveStatsResponse:
    """
    Get archive statistics.

    Queries Supabase for total archived memories, the timestamp of the
    most recently archived memory, and the average salience score of
    all archived memories.

    Parameters
    ----------
    user_id : str
        User UUID (reserved for future per-user filtering).

    Returns
    -------
    ArchiveStatsResponse
        Archive statistics.

    Raises
    ------
    HTTPException (500)
        If the database query fails.
    """
    logger.info("Getting archive stats for user %s", user_id)

    try:
        client = _get_supabase()

        # Query archived memories for aggregate stats
        response = (
            client.table("memories")
            .select("id, salience_score, updated_at")
            .eq("is_archived", True)
            .execute()
        )
        archived_rows = response.data or []

        total_archived: int = len(archived_rows)

        if total_archived == 0:
            return ArchiveStatsResponse(
                total_archived=0,
                last_archive_run=None,
                avg_salience_of_archived=None,
            )

        # Calculate average salience of archived memories
        salience_values = [
            row.get("salience_score", 0.0)
            for row in archived_rows
            if row.get("salience_score") is not None
        ]
        avg_salience: Optional[float] = (
            round(sum(salience_values) / len(salience_values), 4)
            if salience_values
            else None
        )

        # Find the most recent updated_at (proxy for archive timestamp)
        timestamps = [
            row.get("updated_at", "")
            for row in archived_rows
            if row.get("updated_at")
        ]
        last_archive_run: Optional[str] = max(timestamps) if timestamps else None

        return ArchiveStatsResponse(
            total_archived=total_archived,
            last_archive_run=last_archive_run,
            avg_salience_of_archived=avg_salience,
        )

    except Exception as exc:
        logger.error("Failed to get archive stats: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get archive stats: {str(exc)}",
        )


# =============================================================================
# Internal Helpers
# =============================================================================

def _get_redis() -> Any:
    """Lazy-load the Redis client singleton."""
    from backend.services.redis_client import get_redis_client
    return get_redis_client()


def _get_supabase() -> Any:
    """Lazy-load the Supabase client singleton."""
    from backend.services.wal import get_supabase_client
    return get_supabase_client()


def _count_archive_candidates(threshold: float) -> int:
    """
    Count how many memories would be archived at the given threshold.

    Uses the same criteria as ``archive_low_salience_memories()`` in
    ``backend/worker/salience_job.py``.

    Parameters
    ----------
    threshold : float
        Salience score threshold for archival.

    Returns
    -------
    int
        Number of archival candidates.
    """
    from datetime import timedelta

    from backend.worker.salience_job import (
        MAX_ARCHIVE_ACCESS_COUNT,
        MIN_ARCHIVE_AGE_DAYS,
    )

    try:
        client = _get_supabase()
        age_cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_ARCHIVE_AGE_DAYS)
        age_cutoff_str = age_cutoff.isoformat()

        response = (
            client.table("memories")
            .select("id", count="exact")
            .eq("is_archived", False)
            .lt("salience_score", threshold)
            .lte("access_count", MAX_ARCHIVE_ACCESS_COUNT)
            .lt("created_at", age_cutoff_str)
            .execute()
        )
        return response.count if response.count is not None else len(response.data or [])

    except Exception as exc:
        logger.error("Failed to count archive candidates: %s", exc, exc_info=True)
        return 0


def _enqueue_archive_job(threshold: float) -> Optional[str]:
    """
    Enqueue an archive job via the rq queue.

    Uses the same ``_enqueue_job`` pattern from ``backend/services/queue.py``.

    Parameters
    ----------
    threshold : float
        Salience score threshold to pass to the archive job.

    Returns
    -------
    str | None
        The rq job ID on success, or None if enqueue failed.
    """
    try:
        from rq import Queue, Retry  # type: ignore[import-untyped]

        from backend.services.redis_client import get_redis_client
        from backend.services.queue import (
            QUEUE_NAME,
            MAX_RETRIES,
            RETRY_INTERVALS,
            JOB_TIMEOUT,
            RESULT_TTL,
            FAILURE_TTL,
        )

        conn = get_redis_client()
        queue = Queue(QUEUE_NAME, connection=conn)

        job = queue.enqueue(
            "backend.worker.jobs.run_archive_job",
            threshold=threshold,
            retry=Retry(max=MAX_RETRIES, interval=RETRY_INTERVALS),
            job_timeout=JOB_TIMEOUT,
            result_ttl=RESULT_TTL,
            failure_ttl=FAILURE_TTL,
        )

        return job.id

    except ImportError:
        logger.error("rq package is not installed. Install with: pip install rq")
        return None
    except Exception as exc:
        logger.error("Failed to enqueue archive job: %s", exc, exc_info=True)
        return None
