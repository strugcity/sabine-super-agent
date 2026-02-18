"""
Redis client singleton for Sabine 2.0 job queue.

Provides a shared Redis connection used by:
- rq job queue (producer in FastAPI, consumer in worker)
- Queue health checks
- Future: caching layer

ADR Reference: ADR-002 (Redis + rq selected for Slow Path job queue)

Singleton Pattern: Matches ``get_supabase_client()`` in ``backend/services/wal.py``.
The module-level ``_redis_client`` is lazily initialised on first call to
``get_redis_client()`` and reused for the lifetime of the process.

IMPORTANT — two separate clients:
- ``get_redis_client()``    : ``decode_responses=True``  — for application code (FastAPI,
                               health checks, salience scores).  Returns Python strings.
- ``get_rq_redis_client()`` : ``decode_responses=False`` — REQUIRED for rq's Queue and
                               Worker.  rq serialises jobs as pickle (binary data); with
                               ``decode_responses=True`` redis-py tries to UTF-8-decode
                               the raw pickle bytes, causing UnicodeDecodeError on every
                               ``Job.fetch_many()`` call, and rq's ``intermediate_queue``
                               calls ``.decode()`` on already-decoded strings, causing
                               ``AttributeError: 'str' object has no attribute 'decode'``.
                               See deploy-ws.log 2026-02-18 for the production crash.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")


# =============================================================================
# Models
# =============================================================================

class RedisHealthStatus(BaseModel):
    """Health-check result for the Redis connection."""

    connected: bool = Field(
        ..., description="True if a PING was successful"
    )
    ping_ms: float = Field(
        default=0.0, description="Round-trip PING latency in milliseconds"
    )
    info: Dict[str, Any] = Field(
        default_factory=dict,
        description="Subset of Redis INFO useful for diagnostics",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message when connected is False",
    )


# =============================================================================
# Singleton Client (application use — decode_responses=True)
# =============================================================================

_redis_client: Optional[Any] = None  # typed as Any to allow lazy import


def get_redis_client() -> Any:
    """
    Get or create the Redis client singleton (``decode_responses=True``).

    Returns Python strings for all Redis responses.  Suitable for application
    code (FastAPI endpoints, salience scores, health checks via ``ping_redis``).

    **Do NOT pass this connection to rq's Queue or Worker.**  rq requires raw
    bytes (``decode_responses=False``).  Use ``get_rq_redis_client()`` instead.

    Raises
    ------
    redis.exceptions.ConnectionError
        If Redis is unreachable *and* there is no prior cached client.
    ImportError
        If the ``redis`` package is not installed.
    """
    global _redis_client
    if _redis_client is None:
        # Lazy import so modules that import redis_client don't pay the cost
        # unless they actually request a connection.
        from redis import Redis  # type: ignore[import-untyped]

        _redis_client = Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        logger.info("Redis client initialised (url=%s)", _redis_url_safe())
    return _redis_client


def reset_redis_client() -> None:
    """
    Reset the singleton (useful in tests or connection-recovery scenarios).

    If the existing client has an open connection pool it is closed first.
    """
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception:
            pass  # best-effort cleanup
    _redis_client = None
    logger.debug("Redis client singleton reset")


# =============================================================================
# rq-Compatible Client (decode_responses=False — required for rq)
# =============================================================================

def get_rq_redis_client() -> Any:
    """
    Create a fresh Redis connection suitable for use with rq's Queue and Worker.

    **Key difference from** ``get_redis_client()``: this connection uses
    ``decode_responses=False``, meaning Redis responses are returned as raw
    ``bytes``.  rq 2.x requires raw bytes because:

    1. Job payloads are serialised with ``pickle``, which produces binary data
       that cannot be UTF-8 decoded.  Passing ``decode_responses=True`` causes
       ``UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80`` when rq's
       scheduler calls ``Job.fetch_many()``.

    2. rq's ``IntermediateQueue.get_job_ids()`` calls ``job_id.decode()`` on
       every item it reads from Redis.  With ``decode_responses=True`` the items
       are already Python strings; calling ``.decode()`` on a ``str`` raises
       ``AttributeError: 'str' object has no attribute 'decode'``.

    This function is intentionally **not** a singleton — it creates a new
    connection each call.  The caller (``backend/worker/main.py``) holds the
    reference for the lifetime of the worker process.

    Returns
    -------
    redis.Redis
        A connected Redis client with ``decode_responses=False``.
    """
    from redis import Redis  # type: ignore[import-untyped]

    client = Redis.from_url(
        REDIS_URL,
        decode_responses=False,   # rq MUST receive raw bytes, not strings
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    logger.info("rq Redis client created (url=%s, decode_responses=False)", _redis_url_safe())
    return client


# =============================================================================
# Health Check
# =============================================================================

def ping_redis(timeout_s: float = 1.0) -> bool:
    """
    Fast synchronous Redis liveness probe with an independent short timeout.

    Used by the worker's health-check HTTP handler so that a probe never
    blocks for more than ``timeout_s`` seconds.  The main singleton uses a
    5-second socket timeout (needed for job operations); that is too slow for
    a health endpoint that Railway probes every 15 seconds with its own 5s
    deadline.

    Creates a *transient* connection for the probe — does not touch or replace
    the singleton used by job workers.

    Parameters
    ----------
    timeout_s : float
        Socket connect + read timeout in seconds.  Default 1.0.

    Returns
    -------
    bool
        ``True`` if PING succeeded, ``False`` on any error.
    """
    try:
        from redis import Redis  # type: ignore[import-untyped]

        probe = Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=timeout_s,
            socket_timeout=timeout_s,
            retry_on_timeout=False,
        )
        result: bool = probe.ping()
        probe.close()
        return result
    except Exception:
        return False


async def check_redis_health() -> RedisHealthStatus:
    """
    Probe the Redis connection and return a structured health report.

    This function is *async* so it can be called directly from FastAPI
    endpoint handlers.  The underlying ``redis-py`` calls are synchronous,
    so they are wrapped with ``asyncio.to_thread()`` to avoid blocking the
    event loop.

    Returns
    -------
    RedisHealthStatus
        ``connected=True`` with timing info on success, or
        ``connected=False`` with the error string on failure.
    """
    import asyncio

    try:
        client = get_redis_client()

        start = time.monotonic()
        pong: bool = await asyncio.to_thread(client.ping)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        if not pong:
            return RedisHealthStatus(
                connected=False,
                ping_ms=elapsed_ms,
                error="PING returned False",
            )

        # Gather a small subset of server info for diagnostics.
        raw_info: Dict[str, Any] = await asyncio.to_thread(
            client.info, section="server"
        )
        info_subset: Dict[str, Any] = {
            "redis_version": raw_info.get("redis_version", "unknown"),
            "uptime_in_seconds": raw_info.get("uptime_in_seconds", -1),
            "connected_clients": raw_info.get("connected_clients", -1),
            "used_memory_human": raw_info.get("used_memory_human", "unknown"),
        }

        return RedisHealthStatus(
            connected=True,
            ping_ms=round(elapsed_ms, 2),
            info=info_subset,
        )

    except ImportError:
        logger.error(
            "redis package is not installed. "
            "Install with: pip install redis"
        )
        return RedisHealthStatus(
            connected=False,
            error="redis package not installed",
        )
    except Exception as exc:
        logger.warning(
            "Redis health check failed: %s", exc, exc_info=True
        )
        return RedisHealthStatus(
            connected=False,
            error=str(exc),
        )


# =============================================================================
# Helpers
# =============================================================================

def _redis_url_safe() -> str:
    """
    Return the ``REDIS_URL`` with password masked for safe logging.

    ``redis://:secret@host:6379/0`` becomes ``redis://:*****@host:6379/0``.
    """
    url = REDIS_URL
    if "@" in url:
        # Mask everything between :// and @
        prefix_end = url.index("://") + 3
        at_pos = url.index("@")
        url = url[:prefix_end] + "*****" + url[at_pos:]
    return url
