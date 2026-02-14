"""
Job queue producer for Sabine 2.0 Slow Path.

Enqueues WAL entries for background processing by the worker service.
Uses Redis Queue (rq) as the job transport.

ADR Reference: ADR-002

Queue name : ``sabine-slow-path``
Retry policy: 30 s -> 5 min -> 15 min (3 attempts, matching WAL backoff)
Job timeout : 10 minutes per job
Result TTL  : 24 hours (completed jobs)
Failure TTL : 7 days (failed jobs, kept for inspection via rq-dashboard)
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

QUEUE_NAME: str = "sabine-slow-path"

# Retry backoff intervals in seconds (30 s, 5 min, 15 min) per ADR-002
RETRY_INTERVALS: List[int] = [30, 300, 900]
MAX_RETRIES: int = 3

# Job TTL settings
JOB_TIMEOUT: str = "10m"       # max wall-clock time per job execution
RESULT_TTL: int = 86_400       # keep successful results for 24 h
FAILURE_TTL: int = 604_800     # keep failures for 7 days


# =============================================================================
# Enums
# =============================================================================

class JobPriority(str, Enum):
    """
    Priority tiers for enqueued jobs.

    ``high`` jobs are pushed to the front of the queue; ``low`` jobs to the
    back.  ``default`` uses rq's natural FIFO ordering.
    """
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"


# =============================================================================
# Models
# =============================================================================

class EnqueueResult(BaseModel):
    """Result of a job enqueue operation."""

    job_id: Optional[str] = Field(
        default=None,
        description="rq job ID (None if enqueue failed gracefully)",
    )
    success: bool = Field(
        ..., description="Whether the job was enqueued"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if enqueue failed",
    )


class QueueStats(BaseModel):
    """Snapshot of queue health metrics."""

    queue_name: str = Field(
        ..., description="Name of the rq queue"
    )
    pending: int = Field(
        default=0, description="Jobs waiting to be picked up"
    )
    started: int = Field(
        default=0, description="Jobs currently executing"
    )
    failed: int = Field(
        default=0, description="Jobs in the failed registry"
    )
    completed: int = Field(
        default=0, description="Jobs in the finished registry"
    )
    workers: int = Field(
        default=0, description="Number of active workers on this queue"
    )


# =============================================================================
# Queue Producer Functions
# =============================================================================

def enqueue_wal_processing(
    wal_entry_id: str,
    priority: str = "default",
) -> Optional[str]:
    """
    Enqueue a single WAL entry for Slow Path processing.

    Parameters
    ----------
    wal_entry_id : str
        UUID (as string) of the WAL entry to process.
    priority : str
        One of ``"high"``, ``"default"``, ``"low"``.
        ``"high"`` places the job at the front of the queue.

    Returns
    -------
    str | None
        The rq job ID on success, or ``None`` if the queue is unavailable.
    """
    try:
        result = _enqueue_job(
            func_path="backend.worker.jobs.process_wal_entry",
            kwargs={"wal_entry_id": wal_entry_id},
            priority=priority,
        )
        if result.success:
            logger.info(
                "Enqueued WAL entry %s as job %s (priority=%s)",
                wal_entry_id, result.job_id, priority,
            )
        return result.job_id
    except Exception as exc:
        logger.error(
            "Failed to enqueue WAL entry %s: %s",
            wal_entry_id, exc, exc_info=True,
        )
        return None


def enqueue_wal_batch(
    wal_entry_ids: List[str],
    priority: str = "default",
) -> Optional[str]:
    """
    Enqueue a batch of WAL entries as a single job.

    This is more efficient than calling :func:`enqueue_wal_processing` per
    entry when there are many pending entries to process.

    Parameters
    ----------
    wal_entry_ids : list[str]
        List of WAL entry UUIDs.
    priority : str
        Queue priority tier.

    Returns
    -------
    str | None
        The rq job ID on success, or ``None`` if the queue is unavailable.
    """
    if not wal_entry_ids:
        logger.warning("enqueue_wal_batch called with empty list; skipping")
        return None

    try:
        result = _enqueue_job(
            func_path="backend.worker.jobs.process_wal_batch",
            kwargs={"wal_entry_ids": wal_entry_ids},
            priority=priority,
        )
        if result.success:
            logger.info(
                "Enqueued batch of %d WAL entries as job %s (priority=%s)",
                len(wal_entry_ids), result.job_id, priority,
            )
        return result.job_id
    except Exception as exc:
        logger.error(
            "Failed to enqueue WAL batch (%d entries): %s",
            len(wal_entry_ids), exc, exc_info=True,
        )
        return None


def get_queue_stats() -> Dict[str, Any]:
    """
    Return a snapshot of queue health metrics.

    Returns
    -------
    dict
        Serialised :class:`QueueStats`.  If Redis is unavailable, returns a
        dict with ``queue_name`` and zero counts plus an ``error`` key.
    """
    try:
        # Lazy imports to avoid import-time side effects
        from rq import Queue, Worker  # type: ignore[import-untyped]

        from backend.services.redis_client import get_redis_client

        conn = get_redis_client()
        queue = Queue(QUEUE_NAME, connection=conn)

        workers = Worker.all(connection=conn, queue=queue)
        active_workers = [w for w in workers if w.state == "busy" or w.state == "idle"]

        stats = QueueStats(
            queue_name=QUEUE_NAME,
            pending=len(queue),
            started=queue.started_job_registry.count,
            failed=queue.failed_job_registry.count,
            completed=queue.finished_job_registry.count,
            workers=len(active_workers),
        )
        return stats.model_dump()

    except ImportError:
        logger.error(
            "rq package is not installed. Install with: pip install rq"
        )
        return QueueStats(
            queue_name=QUEUE_NAME,
            error="rq package not installed",  # type: ignore[call-arg]
        ).model_dump()
    except Exception as exc:
        logger.warning(
            "Failed to retrieve queue stats: %s", exc, exc_info=True,
        )
        return {
            "queue_name": QUEUE_NAME,
            "pending": 0,
            "started": 0,
            "failed": 0,
            "completed": 0,
            "workers": 0,
            "error": str(exc),
        }


# =============================================================================
# Internal Helpers
# =============================================================================

def _enqueue_job(
    func_path: str,
    kwargs: Dict[str, Any],
    priority: str = "default",
) -> EnqueueResult:
    """
    Low-level helper that enqueues a job to the Slow Path queue.

    Parameters
    ----------
    func_path : str
        Dotted import path to the worker function (e.g.
        ``"backend.worker.jobs.process_wal_entry"``).
    kwargs : dict
        Keyword arguments forwarded to the worker function.
    priority : str
        ``"high"`` uses ``enqueue_at_front``; others use normal enqueue.

    Returns
    -------
    EnqueueResult
    """
    try:
        # Lazy imports to avoid circular dependencies and import-time costs
        from rq import Queue, Retry  # type: ignore[import-untyped]

        from backend.services.redis_client import get_redis_client

        conn = get_redis_client()
        queue = Queue(QUEUE_NAME, connection=conn)

        enqueue_kwargs: Dict[str, Any] = {
            "retry": Retry(max=MAX_RETRIES, interval=RETRY_INTERVALS),
            "job_timeout": JOB_TIMEOUT,
            "result_ttl": RESULT_TTL,
            "failure_ttl": FAILURE_TTL,
        }

        at_front: bool = (priority == JobPriority.HIGH.value)

        job = queue.enqueue(
            func_path,
            at_front=at_front,
            **kwargs,
            **enqueue_kwargs,
        )

        return EnqueueResult(job_id=job.id, success=True)

    except ImportError:
        msg = "rq package is not installed"
        logger.error("%s. Install with: pip install rq", msg)
        return EnqueueResult(success=False, error=msg)

    except Exception as exc:
        logger.error("Job enqueue failed: %s", exc, exc_info=True)
        return EnqueueResult(success=False, error=str(exc))
