"""
Fast Path Timing Instrumentation for Sabine 2.0
================================================

Provides timing utilities for measuring Fast Path pipeline step latencies.

Features:
- Context manager ``TimingBlock`` for instrumenting individual pipeline steps
- ``FastPathTimings`` Pydantic model for structured timing data
- INFO-level logging of step-by-step and total latencies after each execution

Performance Target: Total Fast Path execution < 200ms (WAL write < 100ms)

Owner: @backend-architect-sabine
"""

import logging
import time
from contextlib import contextmanager
from typing import Generator, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================

class FastPathTimings(BaseModel):
    """
    Structured timing data for a single Fast Path pipeline execution.

    All durations are recorded in milliseconds (ms).
    """

    wal_write_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time to write WAL entry to Supabase (ms)",
    )
    entity_extraction_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time to extract entities from message (ms)",
    )
    embedding_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time to generate embedding vector (ms)",
    )
    memory_retrieval_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time to retrieve relevant memories (ms)",
    )
    conflict_detection_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time to detect entity conflicts (ms)",
    )
    queue_enqueue_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time to enqueue WAL entry for Slow Path (ms)",
    )
    total_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Total end-to-end Fast Path latency (ms)",
    )

    def log_summary(self, user_id: str, session_id: Optional[str] = None) -> None:
        """
        Log a structured summary of all timing data at INFO level.

        Args:
            user_id: User ID for contextual logging.
            session_id: Optional session ID for contextual logging.
        """
        ctx = f"user={user_id}"
        if session_id:
            ctx += f" session={session_id}"

        logger.info(
            "Fast Path timings [%s]: "
            "wal_write=%.1fms "
            "entity_extraction=%.1fms "
            "embedding=%.1fms "
            "memory_retrieval=%.1fms "
            "conflict_detection=%.1fms "
            "queue_enqueue=%.1fms "
            "total=%.1fms",
            ctx,
            self.wal_write_ms,
            self.entity_extraction_ms,
            self.embedding_ms,
            self.memory_retrieval_ms,
            self.conflict_detection_ms,
            self.queue_enqueue_ms,
            self.total_ms,
        )

        # Warn if total latency exceeds budget
        if self.total_ms > 200.0:
            logger.warning(
                "Fast Path latency exceeded 200ms budget: %.1fms [%s]",
                self.total_ms,
                ctx,
            )


# =============================================================================
# Timing Context Manager
# =============================================================================

class TimingBlock:
    """
    Reusable timing context manager for instrumenting code blocks.

    Records elapsed wall-clock time in milliseconds.

    Usage::

        timer = TimingBlock("wal_write")
        with timer:
            await wal_service.create_entry(payload)
        print(f"WAL write took {timer.elapsed_ms:.1f}ms")
    """

    def __init__(self, label: str) -> None:
        """
        Initialise the timing block.

        Args:
            label: Human-readable label for logging (e.g., "wal_write").
        """
        self.label: str = label
        self.elapsed_ms: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> "TimingBlock":
        """Record start time."""
        self._start = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Calculate elapsed time in milliseconds."""
        self.elapsed_ms = (time.monotonic() - self._start) * 1000.0
        logger.debug(
            "TimingBlock [%s]: %.1fms", self.label, self.elapsed_ms,
        )


@contextmanager
def timing_block(label: str) -> Generator[TimingBlock, None, None]:
    """
    Functional context manager wrapping ``TimingBlock``.

    Usage::

        with timing_block("wal_write") as t:
            await wal_service.create_entry(payload)
        print(t.elapsed_ms)

    Args:
        label: Human-readable label for the timed block.

    Yields:
        TimingBlock instance with ``elapsed_ms`` populated on exit.
    """
    block = TimingBlock(label)
    block._start = time.monotonic()
    try:
        yield block
    finally:
        block.elapsed_ms = (time.monotonic() - block._start) * 1000.0
        logger.debug(
            "timing_block [%s]: %.1fms", label, block.elapsed_ms,
        )
