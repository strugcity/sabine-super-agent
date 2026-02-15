"""
Salience Recalculation and Archival Jobs
==========================================

Background jobs for the Sabine 2.0 memory lifecycle:

1. **recalculate_all_salience_scores()** (MEM-001)
   Nightly batch job that recalculates salience scores for all active
   (non-archived) memories.  Uses checkpointing for crash recovery on
   large datasets.

2. **archive_low_salience_memories()** (MEM-002)
   Archives memories whose salience has fallen below a configurable
   threshold, provided they also meet minimum age and access-count
   criteria per ADR-004.

Both functions are synchronous wrappers suitable for rq workers.
They are registered as job handlers in ``backend/worker/jobs.py``.

PRD Reference: MEM-001, MEM-002
ADR Reference: ADR-004 (cold storage archival trigger criteria)
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Batch size for Supabase update operations
BATCH_UPDATE_SIZE: int = 100

# Default archival threshold: memories with salience below this are candidates
DEFAULT_ARCHIVE_THRESHOLD: float = 0.2

# Minimum age in days before a memory can be archived (per ADR-004)
MIN_ARCHIVE_AGE_DAYS: int = 90

# Maximum access count for archival eligibility (per ADR-004)
MAX_ARCHIVE_ACCESS_COUNT: int = 2

# Checkpoint interval for batch recalculation
CHECKPOINT_INTERVAL: int = 200


# =============================================================================
# Nightly Batch Recalculation (MEM-001)
# =============================================================================

def recalculate_all_salience_scores() -> Dict[str, Any]:
    """
    Recalculate salience scores for all non-archived memories.

    This is the synchronous entry point called by rq.  It:
        1. Queries all active (non-archived) memories from Supabase
        2. Determines the global max access_count for normalisation
        3. Calculates salience for each memory using the formula
        4. Batch-updates salience_score in Supabase
        5. Uses CheckpointManager for crash recovery
        6. Logs summary stats

    Returns
    -------
    dict
        Summary with keys: total, updated, avg_salience, duration_ms, errors.
    """
    start = time.monotonic()
    logger.info("salience_recalculate START")

    # Lazy imports to avoid circular dependencies
    from backend.services.salience import SalienceWeights, calculate_salience
    from backend.worker.checkpoint import CheckpointManager

    batch_id = f"salience-recalc-{int(time.time())}"
    checkpoint_mgr = CheckpointManager(batch_id=batch_id)

    try:
        client = _get_supabase_client()
    except Exception as exc:
        logger.error("Failed to get Supabase client: %s", exc, exc_info=True)
        return _error_result(start, str(exc))

    # ------------------------------------------------------------------
    # 1. Load salience weights from Redis (or use defaults)
    # ------------------------------------------------------------------
    weights = _load_weights_from_redis()

    # ------------------------------------------------------------------
    # 2. Query all non-archived memories
    # ------------------------------------------------------------------
    try:
        response = (
            client.table("memories")
            .select("id, last_accessed_at, access_count, metadata, entity_links, salience_score, content, importance_score, is_archived, created_at, updated_at")
            .eq("is_archived", False)
            .execute()
        )
        memories_data: List[Dict[str, Any]] = response.data or []
    except Exception as exc:
        logger.error("Failed to query memories: %s", exc, exc_info=True)
        return _error_result(start, str(exc))

    total = len(memories_data)
    if total == 0:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.info("salience_recalculate DONE: no active memories found")
        return {
            "status": "completed",
            "total": 0,
            "updated": 0,
            "avg_salience": 0.0,
            "duration_ms": round(elapsed_ms, 1),
            "errors": 0,
        }

    logger.info("Found %d active memories to recalculate", total)

    # ------------------------------------------------------------------
    # 3. Determine global max access_count for normalisation
    # ------------------------------------------------------------------
    max_access_count = max(
        (m.get("access_count", 0) for m in memories_data), default=1
    )
    max_access_count = max(max_access_count, 1)  # floor at 1

    # ------------------------------------------------------------------
    # 4. Check for existing checkpoint (crash recovery)
    # ------------------------------------------------------------------
    resume_index = 0
    updated = 0
    errors = 0
    salience_sum = 0.0

    existing_checkpoint = checkpoint_mgr.load()
    if existing_checkpoint is not None:
        resume_index = existing_checkpoint.get("last_processed_index", -1) + 1
        updated = existing_checkpoint.get("updated", 0)
        errors = existing_checkpoint.get("errors", 0)
        salience_sum = existing_checkpoint.get("salience_sum", 0.0)
        logger.info(
            "Resuming from checkpoint: index=%d updated=%d errors=%d",
            resume_index, updated, errors,
        )

    # ------------------------------------------------------------------
    # 5. Calculate salience and batch-update
    # ------------------------------------------------------------------
    pending_updates: List[Dict[str, Any]] = []

    for i in range(resume_index, total):
        mem_data = memories_data[i]
        try:
            # Build a lightweight Memory-like object for the calculator
            memory_obj = _dict_to_memory(mem_data)

            result = calculate_salience(
                memory=memory_obj,
                weights=weights,
                max_access_count=max_access_count,
            )

            pending_updates.append({
                "id": mem_data["id"],
                "salience_score": result.score,
            })
            salience_sum += result.score

        except Exception as exc:
            logger.warning(
                "Salience calc failed for memory %s: %s",
                mem_data.get("id", "unknown"), exc,
            )
            errors += 1

        # Flush batch updates periodically
        if len(pending_updates) >= BATCH_UPDATE_SIZE:
            flushed = _flush_updates(client, pending_updates)
            updated += flushed
            pending_updates = []

        # Checkpoint periodically
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            checkpoint_mgr.save(
                last_processed_index=i,
                metadata={
                    "updated": updated + len(pending_updates),
                    "errors": errors,
                    "salience_sum": salience_sum,
                    "total": total,
                },
            )
            logger.info(
                "Checkpoint at index %d/%d  updated=%d  errors=%d",
                i + 1, total, updated + len(pending_updates), errors,
            )

    # Flush remaining updates
    if pending_updates:
        flushed = _flush_updates(client, pending_updates)
        updated += flushed

    # Clear checkpoint after successful completion
    checkpoint_mgr.clear()

    elapsed_ms = (time.monotonic() - start) * 1000.0
    avg_salience = salience_sum / total if total > 0 else 0.0

    logger.info(
        "salience_recalculate DONE: total=%d  updated=%d  errors=%d  "
        "avg_salience=%.4f  elapsed=%.0fms",
        total, updated, errors, avg_salience, elapsed_ms,
    )

    return {
        "status": "completed",
        "total": total,
        "updated": updated,
        "avg_salience": round(avg_salience, 4),
        "duration_ms": round(elapsed_ms, 1),
        "errors": errors,
    }


# =============================================================================
# Archive Low-Salience Memories (MEM-002)
# =============================================================================

def archive_low_salience_memories(
    threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
) -> Dict[str, Any]:
    """
    Archive memories with low salience scores.

    Loads archive configuration from Redis (falling back to module-level
    defaults) so that per-user overrides set via the Settings API are
    respected at runtime.

    Criteria for archival (all must be met, per ADR-004):
        1. ``salience_score < threshold`` (default 0.2)
        2. ``is_archived = false`` (not already archived)
        3. ``access_count <= max_access_count`` (rarely accessed)
        4. Memory is older than ``min_age_days`` days

    Sets ``is_archived = true`` on matching memories.

    .. todo::
        Phase 2: Move archived memories to ``archived_memories`` table
        with Haiku-generated summaries and S3/R2 backup.

    Parameters
    ----------
    threshold : float
        Salience score threshold for archival.  Default: 0.2.
        This parameter is used as an override; if not explicitly
        provided, the Redis-stored config value is preferred.

    Returns
    -------
    dict
        Summary with keys: archived_count, threshold, duration_ms.
    """
    start = time.monotonic()

    # ------------------------------------------------------------------
    # 0. Load archive config from Redis (or fall back to defaults)
    # ------------------------------------------------------------------
    archive_config = _load_archive_config_from_redis()
    effective_threshold: float = threshold if threshold != DEFAULT_ARCHIVE_THRESHOLD else archive_config["threshold"]
    effective_min_age: int = archive_config["min_age_days"]
    effective_max_access: int = archive_config["max_access_count"]

    logger.info(
        "archive_low_salience START  threshold=%.2f  max_access=%d  min_age_days=%d",
        effective_threshold, effective_max_access, effective_min_age,
    )

    try:
        client = _get_supabase_client()
    except Exception as exc:
        logger.error("Failed to get Supabase client: %s", exc, exc_info=True)
        return _error_result(start, str(exc))

    # Calculate the age cutoff date
    age_cutoff = datetime.now(timezone.utc) - timedelta(days=effective_min_age)
    age_cutoff_str = age_cutoff.isoformat()

    # ------------------------------------------------------------------
    # Query archival candidates
    # ------------------------------------------------------------------
    try:
        response = (
            client.table("memories")
            .select("id, salience_score, access_count, created_at")
            .eq("is_archived", False)
            .lt("salience_score", effective_threshold)
            .lte("access_count", effective_max_access)
            .lt("created_at", age_cutoff_str)
            .execute()
        )
        candidates: List[Dict[str, Any]] = response.data or []
    except Exception as exc:
        logger.error("Failed to query archival candidates: %s", exc, exc_info=True)
        return _error_result(start, str(exc))

    candidate_count = len(candidates)
    if candidate_count == 0:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.info("archive_low_salience DONE: no candidates found")
        return {
            "status": "completed",
            "archived_count": 0,
            "threshold": threshold,
            "duration_ms": round(elapsed_ms, 1),
        }

    logger.info("Found %d archival candidates", candidate_count)

    # ------------------------------------------------------------------
    # Archive in batches
    # ------------------------------------------------------------------
    archived_count = 0
    candidate_ids = [c["id"] for c in candidates]

    for batch_start in range(0, len(candidate_ids), BATCH_UPDATE_SIZE):
        batch_ids = candidate_ids[batch_start:batch_start + BATCH_UPDATE_SIZE]
        try:
            client.table("memories").update(
                {"is_archived": True}
            ).in_("id", batch_ids).execute()
            archived_count += len(batch_ids)
            logger.debug(
                "Archived batch: %d memories (total so far: %d)",
                len(batch_ids), archived_count,
            )
        except Exception as exc:
            logger.error(
                "Failed to archive batch starting at %d: %s",
                batch_start, exc, exc_info=True,
            )

    elapsed_ms = (time.monotonic() - start) * 1000.0

    # TODO(phase2): Move archived memories to archived_memories table
    # with Haiku-generated summaries and S3/R2 backup.

    logger.info(
        "archive_low_salience DONE: archived=%d  threshold=%.2f  elapsed=%.0fms",
        archived_count, effective_threshold, elapsed_ms,
    )

    return {
        "status": "completed",
        "archived_count": archived_count,
        "threshold": effective_threshold,
        "duration_ms": round(elapsed_ms, 1),
    }


# =============================================================================
# Internal Helpers
# =============================================================================

def _get_supabase_client() -> Any:
    """Lazy-load the Supabase client singleton."""
    from backend.services.wal import get_supabase_client
    return get_supabase_client()


def _load_weights_from_redis() -> "SalienceWeights":
    """
    Load salience weights from Redis (user-level or global).

    Falls back to default weights if Redis is unavailable or no
    custom weights are stored.

    Returns
    -------
    SalienceWeights
    """
    from backend.services.salience import SalienceWeights

    try:
        import json
        from backend.services.redis_client import get_redis_client

        redis_client = get_redis_client()
        # Try global weights first (user-specific weights are per-endpoint)
        raw = redis_client.get("sabine:salience_weights:global")
        if raw:
            data = json.loads(raw)
            return SalienceWeights(**data)
    except Exception as exc:
        logger.debug(
            "Could not load salience weights from Redis (using defaults): %s",
            exc,
        )

    return SalienceWeights()


def _load_archive_config_from_redis() -> Dict[str, Any]:
    """
    Load archive configuration from Redis, falling back to defaults.

    Checks the global key ``sabine:archive_config:global`` for settings
    persisted via the Archive Configuration API.

    Returns
    -------
    dict
        Archive config with keys: threshold, min_age_days, max_access_count.
    """
    try:
        import json
        from backend.services.redis_client import get_redis_client

        redis_client = get_redis_client()
        raw = redis_client.get("sabine:archive_config:global")
        if raw:
            data = json.loads(raw)
            logger.debug("Loaded archive config from Redis: %s", data)
            return {
                "threshold": data.get("threshold", DEFAULT_ARCHIVE_THRESHOLD),
                "min_age_days": data.get("min_age_days", MIN_ARCHIVE_AGE_DAYS),
                "max_access_count": data.get("max_access_count", MAX_ARCHIVE_ACCESS_COUNT),
            }
    except Exception as exc:
        logger.debug(
            "Could not load archive config from Redis (using defaults): %s",
            exc,
        )

    return {
        "threshold": DEFAULT_ARCHIVE_THRESHOLD,
        "min_age_days": MIN_ARCHIVE_AGE_DAYS,
        "max_access_count": MAX_ARCHIVE_ACCESS_COUNT,
    }


def _dict_to_memory(data: Dict[str, Any]) -> Any:
    """
    Convert a Supabase row dict to a Memory model for salience calculation.

    Uses lazy import to avoid circular dependencies.

    Parameters
    ----------
    data : dict
        Row from the ``memories`` table.

    Returns
    -------
    Memory
    """
    from lib.db.models import Memory

    return Memory(
        id=data.get("id"),
        content=data.get("content", ""),
        entity_links=data.get("entity_links", []),
        metadata=data.get("metadata", {}),
        importance_score=data.get("importance_score", 0.5),
        salience_score=data.get("salience_score", 0.5),
        last_accessed_at=data.get("last_accessed_at"),
        access_count=data.get("access_count", 0),
        is_archived=data.get("is_archived", False),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _flush_updates(
    client: Any,
    updates: List[Dict[str, Any]],
) -> int:
    """
    Batch-update salience scores in Supabase.

    Uses individual updates per row since Supabase-py does not support
    batch upsert with different values per row in a single call.

    Parameters
    ----------
    client : supabase.Client
        Supabase client instance.
    updates : list[dict]
        List of ``{"id": ..., "salience_score": ...}`` dicts.

    Returns
    -------
    int
        Number of successfully updated rows.
    """
    success_count = 0
    for update in updates:
        try:
            client.table("memories").update(
                {"salience_score": update["salience_score"]}
            ).eq("id", update["id"]).execute()
            success_count += 1
        except Exception as exc:
            logger.warning(
                "Failed to update salience for memory %s: %s",
                update.get("id", "unknown"), exc,
            )
    return success_count


def _error_result(start: float, error_msg: str) -> Dict[str, Any]:
    """Build a standard error result dict."""
    elapsed_ms = (time.monotonic() - start) * 1000.0
    return {
        "status": "failed",
        "error": error_msg,
        "duration_ms": round(elapsed_ms, 1),
    }
