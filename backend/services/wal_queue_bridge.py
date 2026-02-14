"""
WAL-Queue Bridge - Connects WAL writes to the rq job queue.

This module is the glue between:
- ``backend/services/wal.py``   (WAL entry CRUD)
- ``backend/services/queue.py`` (rq job enqueue)

It is called *after* a WAL entry is persisted to Supabase and pushes
the entry ID into the Slow Path queue for asynchronous processing.

ADR Reference: ADR-002 (Redis + rq for Slow Path)
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Public API
# =============================================================================

async def enqueue_wal_for_processing(
    wal_entry_id: str,
    priority: str = "default",
) -> Optional[str]:
    """
    Enqueue a single WAL entry for Slow Path processing.

    Should be called immediately after a WAL entry is created in the
    Fast Path.  If the queue is unavailable the function returns ``None``
    without raising -- the WAL entry remains in Supabase with
    ``status='pending'`` and can be picked up later via
    :func:`enqueue_pending_wal_entries`.

    Parameters
    ----------
    wal_entry_id : str
        UUID (as string) of the WAL entry.
    priority : str
        One of ``"high"``, ``"default"``, ``"low"``.

    Returns
    -------
    str | None
        The rq job ID on success, or ``None`` if enqueue failed.
    """
    # Lazy import to avoid circular dependencies
    from backend.services.queue import enqueue_wal_processing

    try:
        job_id = enqueue_wal_processing(
            wal_entry_id=wal_entry_id,
            priority=priority,
        )
        if job_id:
            logger.info(
                "WAL-queue bridge: enqueued entry %s as job %s (priority=%s)",
                wal_entry_id,
                job_id,
                priority,
            )
        else:
            logger.warning(
                "WAL-queue bridge: enqueue returned None for entry %s "
                "(queue may be unavailable)",
                wal_entry_id,
            )
        return job_id

    except Exception as exc:
        logger.error(
            "WAL-queue bridge: failed to enqueue entry %s: %s",
            wal_entry_id,
            exc,
            exc_info=True,
        )
        return None


async def enqueue_pending_wal_entries(
    user_id: Optional[str] = None,
    batch_size: int = 100,
) -> List[str]:
    """
    Find all unprocessed WAL entries and enqueue them for processing.

    This is useful for:
    - **Backfill:** after deploying the queue for the first time.
    - **Recovery:** after a Redis outage where entries were written to the
      WAL but never enqueued.
    - **Manual replay:** via the ``/api/queue/enqueue`` route or a CLI script.

    Parameters
    ----------
    user_id : str | None
        If provided, only enqueue pending entries for this user.
        If ``None``, enqueue *all* pending entries (no user filter).
    batch_size : int
        Maximum number of pending entries to fetch in one call.

    Returns
    -------
    list[str]
        List of rq job IDs for successfully enqueued entries.
    """
    # Lazy imports
    from backend.services.wal import WALService
    from backend.services.queue import enqueue_wal_batch

    job_ids: List[str] = []

    try:
        wal_service = WALService()
        pending_entries = await wal_service.get_pending_entries(limit=batch_size)

        if not pending_entries:
            logger.info(
                "WAL-queue bridge: no pending entries to enqueue"
            )
            return job_ids

        # Optionally filter by user_id
        if user_id:
            pending_entries = [
                e for e in pending_entries
                if e.raw_payload.get("user_id") == user_id
            ]
            if not pending_entries:
                logger.info(
                    "WAL-queue bridge: no pending entries for user %s",
                    user_id,
                )
                return job_ids

        # Collect entry IDs
        entry_ids: List[str] = [str(e.id) for e in pending_entries]

        logger.info(
            "WAL-queue bridge: enqueuing batch of %d pending entries",
            len(entry_ids),
        )

        # Enqueue as a single batch job for efficiency
        job_id = enqueue_wal_batch(
            wal_entry_ids=entry_ids,
            priority="default",
        )

        if job_id:
            job_ids.append(job_id)
            logger.info(
                "WAL-queue bridge: batch enqueued as job %s (%d entries)",
                job_id,
                len(entry_ids),
            )
        else:
            logger.warning(
                "WAL-queue bridge: batch enqueue returned None for %d entries",
                len(entry_ids),
            )

    except Exception as exc:
        logger.error(
            "WAL-queue bridge: failed to enqueue pending entries: %s",
            exc,
            exc_info=True,
        )

    return job_ids
