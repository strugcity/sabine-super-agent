"""
Checkpoint Manager for Slow Path Batch Processing
===================================================

Provides crash-recovery checkpointing for WAL batch consolidation.
Checkpoints are stored in Redis with a 24-hour TTL so that stale
checkpoints auto-expire.

Key schema: ``sabine:checkpoint:{batch_id}``

Stored fields:
    - ``last_processed_index``  -- Index (0-based) of the last entry
      successfully processed in the batch.
    - ``timestamp``             -- ISO-8601 UTC timestamp of the checkpoint.
    - ``entries_processed``     -- Cumulative count of entries processed so far.
    - ``entries_remaining``     -- Entries not yet processed in the batch.

ADR Reference: ADR-002 (rq worker, checkpointing)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Redis key prefix for checkpoints
_CHECKPOINT_PREFIX: str = "sabine:checkpoint"

# Checkpoint TTL in seconds (24 hours)
_CHECKPOINT_TTL: int = 86_400


class CheckpointManager:
    """
    Redis-backed checkpoint manager for batch WAL processing.

    Usage::

        mgr = CheckpointManager(batch_id="batch-abc123")

        # Save progress after every N entries
        mgr.save(last_processed_index=49, metadata={"entries_processed": 50, ...})

        # On restart, load the last checkpoint
        cp = mgr.load()
        if cp:
            resume_from = cp["last_processed_index"] + 1

        # After batch completes, remove the checkpoint
        mgr.clear()
    """

    def __init__(self, batch_id: str, redis_client: Optional[Any] = None) -> None:
        """
        Initialise the checkpoint manager.

        Parameters
        ----------
        batch_id : str
            Unique identifier for the batch being processed.
        redis_client : optional
            Injected Redis client for testing.  If ``None``, the shared
            singleton from ``backend.services.redis_client`` is used.
        """
        self.batch_id: str = batch_id
        self._redis_client: Optional[Any] = redis_client

    @property
    def _key(self) -> str:
        """Redis key for this batch's checkpoint."""
        return f"{_CHECKPOINT_PREFIX}:{self.batch_id}"

    def _get_redis(self) -> Any:
        """Return the Redis client, lazily importing the singleton."""
        if self._redis_client is not None:
            return self._redis_client
        # Lazy import to avoid circular dependencies at module load time
        from backend.services.redis_client import get_redis_client
        return get_redis_client()

    def save(
        self,
        last_processed_index: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Persist a checkpoint to Redis.

        Parameters
        ----------
        last_processed_index : int
            Zero-based index of the last successfully processed entry.
        metadata : dict, optional
            Additional metadata to store (``entries_processed``,
            ``entries_remaining``, etc.).
        """
        payload: Dict[str, Any] = {
            "batch_id": self.batch_id,
            "last_processed_index": last_processed_index,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            payload.update(metadata)

        try:
            client = self._get_redis()
            client.setex(
                self._key,
                _CHECKPOINT_TTL,
                json.dumps(payload),
            )
            logger.debug(
                "Checkpoint saved for batch %s at index %d",
                self.batch_id,
                last_processed_index,
            )
        except Exception as exc:
            logger.error(
                "Failed to save checkpoint for batch %s: %s",
                self.batch_id,
                exc,
                exc_info=True,
            )
            raise

    def load(self) -> Optional[Dict[str, Any]]:
        """
        Load the most recent checkpoint for this batch.

        Returns
        -------
        dict or None
            The checkpoint payload if one exists, otherwise ``None``.
        """
        try:
            client = self._get_redis()
            raw: Optional[str] = client.get(self._key)
            if raw is None:
                logger.debug(
                    "No checkpoint found for batch %s", self.batch_id,
                )
                return None
            checkpoint: Dict[str, Any] = json.loads(raw)
            logger.info(
                "Loaded checkpoint for batch %s: index=%d",
                self.batch_id,
                checkpoint.get("last_processed_index", -1),
            )
            return checkpoint
        except Exception as exc:
            logger.error(
                "Failed to load checkpoint for batch %s: %s",
                self.batch_id,
                exc,
                exc_info=True,
            )
            return None

    def clear(self) -> None:
        """
        Remove the checkpoint for this batch after successful completion.
        """
        try:
            client = self._get_redis()
            client.delete(self._key)
            logger.info(
                "Checkpoint cleared for batch %s", self.batch_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to clear checkpoint for batch %s: %s",
                self.batch_id,
                exc,
                exc_info=True,
            )
            raise
