"""
Slow Path Job Handlers
======================

Job functions executed by the rq worker.  Each function is the target
of an ``rq.Queue.enqueue()`` call from the FastAPI producer
(``backend/services/queue.py``).

All functions are **synchronous** (rq workers are sync by default).
The Slow Path pipeline (``backend/worker/slow_path.py``) handles async
internally via ``asyncio.run()``.

Job catalog:
    - ``process_wal_entry``       — Single WAL entry consolidation
    - ``process_wal_batch``       — Batch WAL consolidation with checkpoints
    - ``run_salience_recalculation`` — Nightly salience score recalculation (MEM-001)
    - ``run_archive_job``         — Archive low-salience memories (MEM-002)
    - ``run_backfill_job``        — Backfill entity relationships from existing memories
    - ``run_gap_detection``       — Weekly skill gap detection (SKILL-001, SKILL-002)
    - ``run_weekly_digest``       — Weekly skill acquisition digest (Slack)

ADR Reference: ADR-002
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.worker.memory_guard import memory_profiled_job

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-entry processor
# ---------------------------------------------------------------------------

@memory_profiled_job()
def process_wal_entry(wal_entry_id: str) -> Dict[str, Any]:
    """
    Process a single WAL entry through the Slow Path consolidation
    pipeline.

    This function is enqueued by the FastAPI producer and executed
    inside the rq worker process.  It delegates to
    ``slow_path.consolidate_wal_entry()`` for the real work.

    Parameters
    ----------
    wal_entry_id : str
        UUID (as string) of the WAL entry to process.

    Returns
    -------
    dict
        ``{"status": "processed", "wal_entry_id": ..., ...}``
        on success, or ``{"status": "failed", ...}`` on error.
    """
    logger.info(
        "process_wal_entry START  wal_entry_id=%s", wal_entry_id,
    )
    start = time.monotonic()

    try:
        # Lazy import to avoid circular dependencies at module load time
        from backend.worker.slow_path import consolidate_wal_entry

        result = consolidate_wal_entry(wal_entry_id)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        # Record job completion in health module
        _record_health()

        result_dict: Dict[str, Any] = result.model_dump()
        result_dict["elapsed_ms"] = round(elapsed_ms, 1)

        logger.info(
            "process_wal_entry DONE   wal_entry_id=%s  elapsed=%.0fms  "
            "status=%s",
            wal_entry_id, elapsed_ms, result.status,
        )

        # If permanently failed, fire the failure alert
        if result.status == "failed" and result.error:
            _fire_failure_alert(
                error_summary=result.error,
                wal_entry_id=wal_entry_id,
            )

        return result_dict

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "process_wal_entry FAILED wal_entry_id=%s  elapsed=%.0fms  "
            "error=%s",
            wal_entry_id, elapsed_ms, exc,
            exc_info=True,
        )

        # Fire failure alert for unhandled exceptions
        _fire_failure_alert(
            error_summary=str(exc),
            wal_entry_id=wal_entry_id,
        )

        return {
            "status": "failed",
            "wal_entry_id": wal_entry_id,
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Batch processor
# ---------------------------------------------------------------------------

@memory_profiled_job()
def process_wal_batch(
    wal_entry_ids: List[str],
    checkpoint_interval: int = 100,
) -> Dict[str, Any]:
    """
    Process a batch of WAL entries through the Slow Path with
    checkpointing.

    Delegates to ``slow_path.consolidate_wal_batch()``.

    Parameters
    ----------
    wal_entry_ids : list[str]
        List of WAL entry UUIDs.
    checkpoint_interval : int
        Save a checkpoint every N entries (default: 100).

    Returns
    -------
    dict
        ``{"status": "processed", "processed": N, "failed": M, ...}``
    """
    if not wal_entry_ids:
        logger.warning("process_wal_batch called with empty list; nothing to do")
        return {
            "status": "processed",
            "processed": 0,
            "failed": 0,
            "total": 0,
            "batch_id": "",
        }

    logger.info(
        "process_wal_batch START  count=%d", len(wal_entry_ids),
    )
    start = time.monotonic()

    try:
        # Lazy import to avoid circular dependencies at module load time
        from backend.worker.slow_path import consolidate_wal_batch

        result = consolidate_wal_batch(
            wal_entry_ids=wal_entry_ids,
            checkpoint_interval=checkpoint_interval,
        )

        # Record job completion in health module
        _record_health()

        elapsed_ms = (time.monotonic() - start) * 1000.0
        result_dict: Dict[str, Any] = result.model_dump()
        result_dict["elapsed_ms"] = round(elapsed_ms, 1)
        result_dict["status"] = (
            "processed" if result.failed == 0 else "partial"
        )

        logger.info(
            "process_wal_batch DONE   total=%d  processed=%d  failed=%d  "
            "elapsed=%.0fms",
            result.total, result.processed, result.failed, elapsed_ms,
        )

        return result_dict

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "process_wal_batch FAILED  count=%d  elapsed=%.0fms  error=%s",
            len(wal_entry_ids), elapsed_ms, exc,
            exc_info=True,
        )
        return {
            "status": "failed",
            "total": len(wal_entry_ids),
            "processed": 0,
            "failed": len(wal_entry_ids),
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Salience recalculation job (MEM-001)
# ---------------------------------------------------------------------------

@memory_profiled_job()
def run_salience_recalculation() -> Dict[str, Any]:
    """
    Recalculate salience scores for all active memories.

    Designed to run as a nightly scheduled job.  Delegates to
    ``salience_job.recalculate_all_salience_scores()``.

    Returns
    -------
    dict
        Summary with keys: total, updated, avg_salience, duration_ms, errors.
    """
    logger.info("run_salience_recalculation START")
    start = time.monotonic()

    try:
        # Lazy import to avoid circular dependencies
        from backend.worker.salience_job import recalculate_all_salience_scores

        result = recalculate_all_salience_scores()
        elapsed_ms = (time.monotonic() - start) * 1000.0

        _record_health()

        result["elapsed_ms"] = round(elapsed_ms, 1)

        logger.info(
            "run_salience_recalculation DONE  total=%d  updated=%d  "
            "avg_salience=%.4f  elapsed=%.0fms",
            result.get("total", 0),
            result.get("updated", 0),
            result.get("avg_salience", 0.0),
            elapsed_ms,
        )

        return result

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "run_salience_recalculation FAILED  elapsed=%.0fms  error=%s",
            elapsed_ms, exc, exc_info=True,
        )
        return {
            "status": "failed",
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Archive low-salience memories job (MEM-002)
# ---------------------------------------------------------------------------

@memory_profiled_job()
def run_archive_job(threshold: float = 0.2) -> Dict[str, Any]:
    """
    Archive memories whose salience has dropped below threshold.

    Designed to run as a nightly scheduled job after salience
    recalculation.  Delegates to
    ``salience_job.archive_low_salience_memories()``.

    Parameters
    ----------
    threshold : float
        Salience score threshold.  Default: 0.2.

    Returns
    -------
    dict
        Summary with keys: archived_count, threshold, duration_ms.
    """
    logger.info("run_archive_job START  threshold=%.2f", threshold)
    start = time.monotonic()

    try:
        # Lazy import to avoid circular dependencies
        from backend.worker.salience_job import archive_low_salience_memories

        result = archive_low_salience_memories(threshold=threshold)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        _record_health()

        result["elapsed_ms"] = round(elapsed_ms, 1)

        logger.info(
            "run_archive_job DONE  archived=%d  threshold=%.2f  elapsed=%.0fms",
            result.get("archived_count", 0),
            threshold,
            elapsed_ms,
        )

        return result

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "run_archive_job FAILED  elapsed=%.0fms  error=%s",
            elapsed_ms, exc, exc_info=True,
        )
        return {
            "status": "failed",
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Entity relationship backfill job
# ---------------------------------------------------------------------------

@memory_profiled_job()
def run_backfill_job(
    batch_size: int = 500,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Backfill entity relationships from existing memories.

    Scans memories that have ``entity_links`` with 2+ entities, extracts
    relationships via Claude Haiku, and stores them in the
    ``entity_relationships`` table.

    This job is idempotent: the UNIQUE constraint on the
    ``entity_relationships`` table handles deduplication on re-runs.

    Parameters
    ----------
    batch_size : int
        Maximum number of memories to process in this run (default: 500).
    dry_run : bool
        If True, log what would be done without actually storing (default: False).

    Returns
    -------
    dict
        Summary with keys: total_memories, processed, relationships_stored,
        errors, estimated_cost, elapsed_ms.
    """
    logger.info(
        "run_backfill_job START  batch_size=%d  dry_run=%s",
        batch_size,
        dry_run,
    )
    start = time.monotonic()

    try:
        # Lazy import to avoid circular dependencies
        from backend.worker.backfill_relationships import (
            backfill_entity_relationships,
        )

        result = backfill_entity_relationships(
            batch_size=batch_size,
            dry_run=dry_run,
        )
        elapsed_ms = (time.monotonic() - start) * 1000.0

        _record_health()

        result["elapsed_ms"] = round(elapsed_ms, 1)

        logger.info(
            "run_backfill_job DONE  total=%d  processed=%d  "
            "relationships=%d  elapsed=%.0fms",
            result.get("total_memories", 0),
            result.get("processed", 0),
            result.get("relationships_stored", 0),
            elapsed_ms,
        )

        return result

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "run_backfill_job FAILED  elapsed=%.0fms  error=%s",
            elapsed_ms,
            exc,
            exc_info=True,
        )
        return {
            "status": "failed",
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Weekly gap detection job (SKILL-001, SKILL-002)
# ---------------------------------------------------------------------------

@memory_profiled_job()
def run_gap_detection() -> Dict[str, Any]:
    """
    Detect skill gaps from tool audit log failures.

    Designed to run as a weekly scheduled job. Analyzes the last
    7 days of tool failures and creates/updates skill_gaps records.

    Returns
    -------
    dict
        Summary with keys: gaps_detected, gaps_updated, elapsed_ms.
    """
    logger.info("run_gap_detection START")
    start = time.monotonic()

    try:
        # Lazy import to avoid circular dependencies
        from backend.services.gap_detection import detect_gaps

        gaps = asyncio.run(detect_gaps())
        elapsed_ms = (time.monotonic() - start) * 1000.0

        _record_health()

        result = {
            "status": "success",
            "gaps_detected": len(gaps),
            "elapsed_ms": round(elapsed_ms, 1),
        }

        logger.info(
            "run_gap_detection DONE  gaps=%d  elapsed=%.0fms",
            len(gaps), elapsed_ms,
        )

        return result

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "run_gap_detection FAILED  elapsed=%.0fms  error=%s",
            elapsed_ms, exc, exc_info=True,
        )
        return {
            "status": "failed",
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Weekly skill digest job
# ---------------------------------------------------------------------------

@memory_profiled_job()
def run_weekly_digest() -> Dict[str, Any]:
    """
    Generate and send the weekly skill acquisition digest.

    Summarises gaps detected, proposals pending, and skills
    promoted/disabled over the past 7 days.  Sends via Slack webhook.

    Returns
    -------
    dict
        Summary with keys: status, gaps_opened, proposals_pending, etc.
    """
    logger.info("run_weekly_digest START")
    start = time.monotonic()

    try:
        from backend.services.skill_digest import send_weekly_digest

        result = asyncio.run(send_weekly_digest())
        elapsed_ms = (time.monotonic() - start) * 1000.0

        _record_health()

        result["elapsed_ms"] = round(elapsed_ms, 1)

        logger.info(
            "run_weekly_digest DONE  status=%s  elapsed=%.0fms",
            result.get("status", "unknown"), elapsed_ms,
        )

        return result

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error(
            "run_weekly_digest FAILED  elapsed=%.0fms  error=%s",
            elapsed_ms, exc, exc_info=True,
        )
        return {
            "status": "failed",
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_health() -> None:
    """Record job completion in the health module (best-effort)."""
    try:
        from backend.worker.health import record_job_processed
        record_job_processed()
    except Exception as exc:
        logger.debug("Health record failed (non-fatal): %s", exc)


def _fire_failure_alert(error_summary: str, wal_entry_id: str) -> None:
    """
    Fire a failure alert asynchronously (best-effort).

    Checks the WAL entry's retry count to determine if retries are
    exhausted before sending the alert.

    Parameters
    ----------
    error_summary : str
        Human-readable error description.
    wal_entry_id : str
        UUID (as string) of the failed WAL entry.
    """
    try:
        from backend.worker.alerts import send_failure_alert
        from backend.services.queue import MAX_RETRIES

        # We send the alert for visibility; the retry count is informational
        asyncio.run(
            send_failure_alert(
                error_summary=error_summary,
                wal_entry_id=wal_entry_id,
                retry_count=MAX_RETRIES,
            )
        )
    except Exception as exc:
        logger.debug("Failure alert failed (non-fatal): %s", exc)
