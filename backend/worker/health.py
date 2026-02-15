"""
Worker Health Check Server
==========================

Lightweight HTTP server that exposes a ``GET /health`` endpoint for
Railway's health-check probe.  Runs in a background thread alongside
the rq worker process.

Default port: 8082 (configurable via ``WORKER_HEALTH_PORT`` env var).

Response example::

    {
        "status": "healthy",
        "redis_connected": true,
        "queue_depth": 5,
        "workers_active": 1,
        "last_job_processed": "2026-02-13T10:30:00+00:00",
        "uptime_seconds": 3600,
        "memory_rss_mb": 512.3,
        "memory_vms_mb": 1024.5,
        "memory_percent": 25.1,
        "memory_limit_mb": 2048,
        "memory_status": "healthy"
    }

Memory status thresholds:
    - ``healthy``  : RSS < 1536 MB
    - ``warning``  : 1536 MB <= RSS < 2048 MB
    - ``critical`` : RSS >= 2048 MB
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Railway injects PORT for its healthcheck probe. Prefer that over the
# worker-specific WORKER_HEALTH_PORT so Railway can actually reach us.
HEALTH_PORT: int = int(
    os.getenv("PORT") or os.getenv("WORKER_HEALTH_PORT", "8082")
)

# Module-level state tracking
_start_time: float = time.monotonic()
_last_job_processed: Optional[str] = None


# ---------------------------------------------------------------------------
# Public helpers (called by main.py and jobs.py)
# ---------------------------------------------------------------------------

def record_job_processed() -> None:
    """Record the timestamp of the most recently completed job."""
    global _last_job_processed
    _last_job_processed = datetime.now(timezone.utc).isoformat()


def get_uptime_seconds() -> float:
    """Return seconds since the health server was initialised."""
    return round(time.monotonic() - _start_time, 1)


# ---------------------------------------------------------------------------
# Health data collector
# ---------------------------------------------------------------------------

def _collect_health() -> Dict[str, Any]:
    """
    Gather health metrics from Redis and the rq queue.

    Returns
    -------
    dict
        Health payload ready for JSON serialisation.
    """
    health: Dict[str, Any] = {
        "status": "healthy",
        "redis_connected": False,
        "queue_depth": 0,
        "workers_active": 0,
        "last_job_processed": _last_job_processed,
        "uptime_seconds": get_uptime_seconds(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- Redis connectivity ---
    try:
        from backend.services.redis_client import get_redis_client

        client = get_redis_client()
        pong: bool = client.ping()
        health["redis_connected"] = pong
    except Exception as exc:
        logger.warning("Health: Redis ping failed: %s", exc)
        health["redis_connected"] = False
        health["status"] = "degraded"

    # --- Queue stats ---
    try:
        from backend.services.queue import get_queue_stats

        stats = get_queue_stats()
        health["queue_depth"] = stats.get("pending", 0)
        health["workers_active"] = stats.get("workers", 0)
        health["queue_started"] = stats.get("started", 0)
        health["queue_failed"] = stats.get("failed", 0)
        health["queue_completed"] = stats.get("completed", 0)
    except Exception as exc:
        logger.warning("Health: queue stats failed: %s", exc)

    # --- Memory metrics (SLOW-005) ---
    try:
        from backend.worker.memory_guard import (
            get_memory_snapshot,
            get_memory_status,
            DEFAULT_HARD_LIMIT_MB,
        )

        snap = get_memory_snapshot()
        mem_status = get_memory_status(snap.rss_mb)

        health["memory_rss_mb"] = snap.rss_mb
        health["memory_vms_mb"] = snap.vms_mb
        health["memory_percent"] = snap.percent
        health["memory_limit_mb"] = DEFAULT_HARD_LIMIT_MB
        health["memory_status"] = mem_status

        # Escalate overall status if memory is concerning
        if mem_status == "critical":
            health["status"] = "critical"
        elif mem_status == "warning" and health["status"] == "healthy":
            health["status"] = "warning"
    except Exception as exc:
        logger.warning("Health: memory metrics failed: %s", exc)
        health["memory_rss_mb"] = None
        health["memory_vms_mb"] = None
        health["memory_percent"] = None
        health["memory_limit_mb"] = None
        health["memory_status"] = "unknown"

    # If Redis is down, mark as unhealthy
    if not health["redis_connected"]:
        health["status"] = "unhealthy"

    return health


# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves only ``GET /health``."""

    def do_GET(self) -> None:  # noqa: N802  (required by BaseHTTPRequestHandler)
        """Handle GET requests."""
        if self.path.rstrip("/") == "/health":
            payload = _collect_health()
            body = json.dumps(payload, indent=2).encode("utf-8")
            # Return 200 for healthy/warning, 503 for degraded/unhealthy/critical
            status_ok = payload["status"] in ("healthy", "warning")
            self.send_response(200 if status_ok else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging; route through Python logger."""
        logger.debug("HealthHTTP %s", format % args)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

_server_instance: Optional[HTTPServer] = None
_server_thread: Optional[threading.Thread] = None


def start_health_server(port: Optional[int] = None) -> None:
    """
    Start the health-check HTTP server in a daemon thread.

    Parameters
    ----------
    port : int, optional
        TCP port to listen on.  Defaults to ``WORKER_HEALTH_PORT`` env
        var or 8082.

    This function is **non-blocking**.  The server runs in a background
    thread and shuts down automatically when the main process exits.
    """
    global _server_instance, _server_thread, _start_time

    listen_port = port or HEALTH_PORT
    _start_time = time.monotonic()

    _server_instance = HTTPServer(("0.0.0.0", listen_port), _HealthHandler)
    _server_thread = threading.Thread(
        target=_server_instance.serve_forever,
        name="worker-health-http",
        daemon=True,
    )
    _server_thread.start()
    logger.info("Health server started on port %d", listen_port)


def stop_health_server() -> None:
    """Gracefully shut down the health-check server."""
    global _server_instance
    if _server_instance is not None:
        _server_instance.shutdown()
        logger.info("Health server stopped")
        _server_instance = None
