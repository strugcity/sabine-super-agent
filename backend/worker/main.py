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

ADR Reference: ADR-002
"""

import logging
import os
import signal
import sys
import types
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
        name=f"sabine-worker-{os.getpid()}",
    )

    logger.info(
        "Worker %s started -- waiting for jobs on [%s]",
        worker.name, QUEUE_NAME,
    )

    try:
        worker.work(with_scheduler=False, logging_level=LOG_LEVEL)
    except Exception as exc:
        logger.error("Worker exited with error: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("Worker shut down cleanly")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_worker()
