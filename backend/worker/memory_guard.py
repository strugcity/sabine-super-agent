"""
Memory Guard — psutil-based Memory Monitoring for Worker Jobs
=============================================================

Provides the ``@memory_profiled_job`` decorator which wraps worker job
functions with before/after memory measurement, soft/hard limit
enforcement, and peak-memory tracking in Redis.

Memory thresholds:
    - **Soft limit** (75%): 1536 MB  -- logs WARNING
    - **Hard limit** (100%): 2048 MB -- logs CRITICAL, raises MemoryLimitExceeded

Peak memory per job type is persisted in Redis under:
    ``sabine:worker:memory:{job_type}:peak_mb``

ADR Reference: ADR-002 / SLOW-005
"""

import functools
import logging
import time
from typing import Any, Callable, Optional, TypeVar, cast

import psutil
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HARD_LIMIT_MB: int = 2048
DEFAULT_SOFT_LIMIT_RATIO: float = 0.75  # 75% of hard limit

REDIS_KEY_PREFIX: str = "sabine:worker:memory"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MemorySnapshot(BaseModel):
    """Point-in-time memory reading for the current process."""

    rss_mb: float
    vms_mb: float
    percent: float


class MemoryJobReport(BaseModel):
    """Before/after memory report for a single job execution."""

    job_type: str
    before_rss_mb: float
    after_rss_mb: float
    delta_mb: float
    peak_rss_mb: float
    duration_ms: float
    exceeded_soft_limit: bool = False
    exceeded_hard_limit: bool = False


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class MemoryLimitExceeded(Exception):
    """Raised when a job exceeds the hard memory limit."""

    def __init__(self, current_mb: float, limit_mb: float) -> None:
        self.current_mb = current_mb
        self.limit_mb = limit_mb
        super().__init__(
            f"Memory limit exceeded: {current_mb:.1f} MB > {limit_mb:.1f} MB hard limit"
        )


# ---------------------------------------------------------------------------
# Core measurement helpers
# ---------------------------------------------------------------------------

_process: Optional[psutil.Process] = None


def _get_process() -> psutil.Process:
    """Return a cached ``psutil.Process`` handle for the current PID."""
    global _process
    if _process is None:
        _process = psutil.Process()
    return _process


def get_memory_snapshot() -> MemorySnapshot:
    """
    Take a memory snapshot of the current worker process.

    Returns
    -------
    MemorySnapshot
        RSS and VMS in megabytes plus system-wide memory percentage.
    """
    proc = _get_process()
    mem_info = proc.memory_info()
    mem_percent = proc.memory_percent()

    return MemorySnapshot(
        rss_mb=round(mem_info.rss / (1024 * 1024), 1),
        vms_mb=round(mem_info.vms / (1024 * 1024), 1),
        percent=round(mem_percent, 1),
    )


def get_memory_status(
    rss_mb: float,
    hard_limit_mb: int = DEFAULT_HARD_LIMIT_MB,
) -> str:
    """
    Classify memory usage into a status string.

    Parameters
    ----------
    rss_mb : float
        Current RSS in megabytes.
    hard_limit_mb : int
        Hard limit in megabytes (default: 2048).

    Returns
    -------
    str
        ``"healthy"`` | ``"warning"`` | ``"critical"``
    """
    soft_limit_mb = hard_limit_mb * DEFAULT_SOFT_LIMIT_RATIO
    if rss_mb >= hard_limit_mb:
        return "critical"
    if rss_mb >= soft_limit_mb:
        return "warning"
    return "healthy"


# ---------------------------------------------------------------------------
# Redis peak-memory tracking (best-effort)
# ---------------------------------------------------------------------------

def _record_peak_memory(job_type: str, peak_mb: float) -> None:
    """
    Store the peak RSS for *job_type* in Redis if it exceeds the
    previously recorded value.

    This is best-effort; failures are logged and swallowed.
    """
    try:
        from backend.services.redis_client import get_redis_client

        client = get_redis_client()
        key = f"{REDIS_KEY_PREFIX}:{job_type}:peak_mb"

        current_raw: Optional[bytes] = client.get(key)
        current_peak: float = float(current_raw) if current_raw else 0.0

        if peak_mb > current_peak:
            client.set(key, str(round(peak_mb, 1)))
            logger.debug(
                "memory_guard: new peak for %s: %.1f MB (was %.1f MB)",
                job_type, peak_mb, current_peak,
            )
    except Exception as exc:
        logger.debug("memory_guard: Redis peak recording failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

# Generic TypeVar to preserve the wrapped function's signature
F = TypeVar("F", bound=Callable[..., Any])


def memory_profiled_job(
    max_memory_mb: int = DEFAULT_HARD_LIMIT_MB,
) -> Callable[[F], F]:
    """
    Decorator that wraps a worker job function with memory profiling.

    Behaviour:
        1. Snapshots RSS before and after the job runs.
        2. Logs the memory delta.
        3. If RSS exceeds the **soft limit** (75% of *max_memory_mb*),
           logs a WARNING.
        4. If RSS exceeds the **hard limit** (*max_memory_mb*), logs
           CRITICAL and raises ``MemoryLimitExceeded`` so rq marks the
           job as failed.
        5. Records peak RSS in Redis for historical analysis.

    Parameters
    ----------
    max_memory_mb : int
        Hard memory limit in megabytes.  Default: 2048.

    Returns
    -------
    Callable
        The decorated function.
    """
    soft_limit_mb: float = max_memory_mb * DEFAULT_SOFT_LIMIT_RATIO

    def decorator(func: F) -> F:
        job_type: str = func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # --- Before ---
            before = get_memory_snapshot()
            logger.info(
                "memory_guard [%s] BEFORE rss=%.1f MB  vms=%.1f MB",
                job_type, before.rss_mb, before.vms_mb,
            )

            start_time = time.monotonic()

            try:
                result = func(*args, **kwargs)
            except Exception:
                # Still capture after-snapshot on failure for diagnostics
                after = get_memory_snapshot()
                logger.warning(
                    "memory_guard [%s] EXCEPTION rss=%.1f MB  delta=%.1f MB",
                    job_type, after.rss_mb, after.rss_mb - before.rss_mb,
                )
                _record_peak_memory(job_type, after.rss_mb)
                raise

            # --- After ---
            after = get_memory_snapshot()
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            delta_mb = after.rss_mb - before.rss_mb

            report = MemoryJobReport(
                job_type=job_type,
                before_rss_mb=before.rss_mb,
                after_rss_mb=after.rss_mb,
                delta_mb=round(delta_mb, 1),
                peak_rss_mb=after.rss_mb,
                duration_ms=round(elapsed_ms, 1),
            )

            logger.info(
                "memory_guard [%s] AFTER  rss=%.1f MB  delta=%+.1f MB  "
                "elapsed=%.0f ms",
                job_type, after.rss_mb, delta_mb, elapsed_ms,
            )

            # --- Soft limit check ---
            if after.rss_mb >= soft_limit_mb:
                report.exceeded_soft_limit = True
                logger.warning(
                    "memory_guard [%s] SOFT LIMIT WARNING  rss=%.1f MB >= "
                    "%.1f MB (75%% of %d MB)",
                    job_type, after.rss_mb, soft_limit_mb, max_memory_mb,
                )

            # --- Hard limit check ---
            if after.rss_mb >= max_memory_mb:
                report.exceeded_hard_limit = True
                logger.critical(
                    "memory_guard [%s] HARD LIMIT EXCEEDED  rss=%.1f MB >= "
                    "%d MB — failing job",
                    job_type, after.rss_mb, max_memory_mb,
                )
                _record_peak_memory(job_type, after.rss_mb)
                raise MemoryLimitExceeded(
                    current_mb=after.rss_mb,
                    limit_mb=float(max_memory_mb),
                )

            # --- Record peak in Redis ---
            _record_peak_memory(job_type, after.rss_mb)

            return result

        return cast(F, wrapper)
    return decorator
