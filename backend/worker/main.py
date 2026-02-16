"""
Sabine 2.0 rq Worker Entry Point
=================================

Starts an rq worker that listens on the ``sabine-slow-path`` queue
and a lightweight health-check HTTP server for Railway probes.

Usage::

    python -m backend.worker.main

Environment variables:
    REDIS_URL             -- Redis connection string (default: redis://localhost:6379/0)
    WORKER_HEALTH_PORT    -- Health-check HTTP port (default: 8082)
    LOG_LEVEL             -- Logging verbosity (default: INFO)
    SALIENCE_CRON_HOUR    -- Hour (UTC) for nightly salience recalc (default: 4)
    SALIENCE_CRON_MINUTE  -- Minute for nightly salience recalc (default: 0)
    ARCHIVE_CRON_HOUR     -- Hour (UTC) for nightly archive job (default: 4)
    ARCHIVE_CRON_MINUTE   -- Minute for nightly archive job (default: 30)
    GAP_DETECTION_CRON_HOUR  -- Hour (UTC) for weekly gap detection (default: 3)
    GAP_DETECTION_CRON_MINUTE -- Minute for weekly gap detection (default: 0)
    SKILL_GENERATION_CRON_HOUR  -- Hour (UTC) for weekly skill generation (default: 3)
    SKILL_GENERATION_CRON_MINUTE -- Minute for weekly skill generation (default: 15)
    SKILL_SCORING_CRON_HOUR  -- Hour (UTC) for weekly skill scoring (default: 4)
    SKILL_SCORING_CRON_MINUTE -- Minute for weekly skill scoring (default: 0)

ADR Reference: ADR-002
"""

import logging
import os
import signal
import sys
import types
import uuid
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Logging setup (before any other imports that might log)
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("backend.worker")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redis_url_safe(url: str) -> str:
    """
    Mask the password portion of a Redis URL for safe logging.

    ``redis://:secret@host:6379/0`` becomes ``redis://:*****@host:6379/0``.
    """
    if "@" in url:
        prefix_end = url.index("://") + 3
        at_pos = url.index("@")
        return url[:prefix_end] + "*****" + url[at_pos:]
    return url


# ---------------------------------------------------------------------------
# Nightly job scheduling
# ---------------------------------------------------------------------------

def _register_scheduled_jobs(queue: "Queue", redis_conn: "Redis") -> None:
    """
    Register recurring nightly jobs using rq's built-in scheduler.

    Jobs are enqueued via ``queue.enqueue_at()`` with the rq scheduler
    (enabled by ``worker.work(with_scheduler=True)``).  The scheduler
    de-duplicates by job description so re-registering on restart is safe.

    Scheduled jobs:
        1. **Salience recalculation** (default 04:00 UTC) — MEM-001
        2. **Archive low-salience memories** (default 04:30 UTC) — MEM-002
        3. **Gap detection** (default 03:00 UTC Sunday) — SKILL-001, SKILL-002
        4. **Skill digest** (default 03:30 UTC Sunday) — weekly summary via Slack
        5. **Skill generation batch** (default 03:15 UTC Sunday) — auto gap→proposal
        6. **Skill effectiveness scoring** (default 04:00 UTC Sunday)
    """
    from datetime import timedelta

    salience_hour: int = int(os.getenv("SALIENCE_CRON_HOUR", "4"))
    salience_minute: int = int(os.getenv("SALIENCE_CRON_MINUTE", "0"))
    archive_hour: int = int(os.getenv("ARCHIVE_CRON_HOUR", "4"))
    archive_minute: int = int(os.getenv("ARCHIVE_CRON_MINUTE", "30"))

    try:
        # Calculate next run time for salience recalculation
        now = datetime.now(timezone.utc)
        salience_time = now.replace(
            hour=salience_hour, minute=salience_minute, second=0, microsecond=0,
        )
        if salience_time <= now:
            salience_time += timedelta(days=1)

        archive_time = now.replace(
            hour=archive_hour, minute=archive_minute, second=0, microsecond=0,
        )
        if archive_time <= now:
            archive_time += timedelta(days=1)

        # Schedule salience recalculation (repeats daily via meta key)
        queue.enqueue_at(
            salience_time,
            "backend.worker.jobs.run_salience_recalculation",
            meta={"repeat": 86400, "description": "nightly-salience-recalc"},
            job_timeout="30m",
            description="nightly-salience-recalc",
        )
        logger.info(
            "Scheduled nightly salience recalc at %02d:%02d UTC (next: %s)",
            salience_hour, salience_minute, salience_time.isoformat(),
        )

        # Schedule archive job (repeats daily via meta key)
        queue.enqueue_at(
            archive_time,
            "backend.worker.jobs.run_archive_job",
            meta={"repeat": 86400, "description": "nightly-archive-job"},
            job_timeout="30m",
            description="nightly-archive-job",
        )
        logger.info(
            "Scheduled nightly archive job at %02d:%02d UTC (next: %s)",
            archive_hour, archive_minute, archive_time.isoformat(),
        )

        # Schedule weekly gap detection (repeats every 7 days)
        gap_hour: int = int(os.getenv("GAP_DETECTION_CRON_HOUR", "3"))
        gap_minute: int = int(os.getenv("GAP_DETECTION_CRON_MINUTE", "0"))
        # Find next Sunday
        gap_time = now.replace(
            hour=gap_hour, minute=gap_minute, second=0, microsecond=0,
        )
        # Move to next Sunday (weekday 6)
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and gap_time <= now:
            days_until_sunday = 7
        gap_time += timedelta(days=days_until_sunday)

        queue.enqueue_at(
            gap_time,
            "backend.worker.jobs.run_gap_detection",
            meta={"repeat": 604800, "description": "weekly-gap-detection"},  # 604800 = 7 days
            job_timeout="15m",
            description="weekly-gap-detection",
        )
        logger.info(
            "Scheduled weekly gap detection at %02d:%02d UTC Sunday (next: %s)",
            gap_hour, gap_minute, gap_time.isoformat(),
        )

        # Schedule weekly skill generation batch (Sunday 03:15 UTC, after gap detection)
        generation_time = gap_time.replace(minute=15)
        queue.enqueue_at(
            generation_time,
            "backend.worker.jobs.run_skill_generation_batch",
            meta={"repeat": 604800, "description": "weekly-skill-generation"},
            job_timeout="30m",
            description="weekly-skill-generation",
        )
        logger.info(
            "Scheduled weekly skill generation at %02d:15 UTC Sunday (next: %s)",
            gap_hour, generation_time.isoformat(),
        )

        # Schedule weekly skill digest (Sunday 03:30 UTC, after gap detection)
        digest_time = gap_time.replace(minute=30)
        queue.enqueue_at(
            digest_time,
            "backend.worker.jobs.run_weekly_digest",
            meta={"repeat": 604800, "description": "weekly-skill-digest"},
            job_timeout="5m",
            description="weekly-skill-digest",
        )
        logger.info(
            "Scheduled weekly skill digest at %02d:30 UTC Sunday (next: %s)",
            gap_hour, digest_time.isoformat(),
        )

        # Schedule weekly skill effectiveness scoring (Sunday 04:00 UTC, after digest)
        scoring_time = gap_time.replace(hour=4, minute=0)
        queue.enqueue_at(
            scoring_time,
            "backend.worker.jobs.run_skill_effectiveness_scoring",
            meta={"repeat": 604800, "description": "weekly-skill-scoring"},
            job_timeout="15m",
            description="weekly-skill-scoring",
        )
        logger.info(
            "Scheduled weekly skill effectiveness scoring at 04:00 UTC Sunday (next: %s)",
            scoring_time.isoformat(),
        )

    except Exception as exc:
        logger.warning(
            "Failed to register scheduled jobs (non-fatal): %s", exc,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Worker startup
# ---------------------------------------------------------------------------

def run_worker() -> None:
    """
    Initialise and start the rq worker.

    Steps:
    1. Load environment (dotenv if present).
    2. Connect to Redis via the shared singleton.
    3. Start the health-check HTTP server in a background thread.
    4. Register SIGTERM / SIGINT for graceful shutdown.
    5. Start the rq ``Worker`` loop (blocking).
    """
    # 1. Load environment ---------------------------------------------------
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
        load_dotenv()
        logger.debug(".env loaded via python-dotenv")
    except ImportError:
        logger.debug("python-dotenv not installed; using environment as-is")

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    logger.info("=" * 60)
    logger.info("Sabine 2.0 Worker starting")
    logger.info("  Redis URL : %s", _redis_url_safe(redis_url))
    logger.info("  Log level : %s", LOG_LEVEL)
    logger.info("=" * 60)

    # 2. Connect to Redis ---------------------------------------------------
    try:
        from backend.services.redis_client import get_redis_client

        redis_conn = get_redis_client()
        pong: bool = redis_conn.ping()
        if not pong:
            logger.error("Redis PING returned False -- aborting")
            sys.exit(1)
        logger.info("Redis connection verified (PING OK)")
    except ImportError:
        logger.error(
            "redis package is not installed. "
            "Install with: pip install redis"
        )
        sys.exit(1)
    except Exception as exc:
        logger.error("Failed to connect to Redis: %s", exc, exc_info=True)
        sys.exit(1)

    # 3. Start health server ------------------------------------------------
    try:
        from backend.worker.health import start_health_server

        start_health_server()
    except Exception as exc:
        logger.warning(
            "Health server failed to start (non-fatal): %s", exc,
        )

    # 4. Import queue constant and create rq primitives ---------------------
    try:
        from rq import Queue, Worker  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "rq package is not installed. Install with: pip install rq"
        )
        sys.exit(1)

    from backend.services.queue import QUEUE_NAME

    queue = Queue(QUEUE_NAME, connection=redis_conn)
    logger.info("Listening on queue: %s", QUEUE_NAME)

    # 4b. Register nightly scheduled jobs -----------------------------------
    _register_scheduled_jobs(queue, redis_conn)

    # 5. Graceful shutdown --------------------------------------------------
    worker: Optional["Worker"] = None

    def _shutdown_handler(
        signum: int, frame: Optional[types.FrameType],
    ) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s -- requesting graceful shutdown", sig_name)
        if worker is not None:
            worker.request_stop(signum, frame)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    # 6. Start the rq worker loop (blocking) --------------------------------
    worker = Worker(
        queues=[queue],
        connection=redis_conn,
        name=f"sabine-worker-{uuid.uuid4().hex[:8]}",
    )

    logger.info(
        "Worker %s started -- waiting for jobs on [%s]",
        worker.name, QUEUE_NAME,
    )

    try:
        worker.work(with_scheduler=True, logging_level=LOG_LEVEL)
    except Exception as exc:
        logger.error("Worker exited with error: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("Worker shut down cleanly")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_worker()
