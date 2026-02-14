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
# Singleton Client
# =============================================================================

_redis_client: Optional[Any] = None  # typed as Any to allow lazy import


def get_redis_client() -> Any:
    """
    Get or create the Redis client singleton.

    Returns the ``redis.Redis`` instance backed by ``REDIS_URL``.

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
# Health Check
# =============================================================================

async def check_redis_health() -> RedisHealthStatus:
    """
    Probe the Redis connection and return a structured health report.

    This function is *async* so it can be called directly from FastAPI
    endpoint handlers.  The underlying ``redis-py`` call is synchronous but
    very fast (<1 ms on a local or managed instance).

    Returns
    -------
    RedisHealthStatus
        ``connected=True`` with timing info on success, or
        ``connected=False`` with the error string on failure.
    """
    try:
        client = get_redis_client()

        start = time.monotonic()
        pong: bool = client.ping()
        elapsed_ms = (time.monotonic() - start) * 1000.0

        if not pong:
            return RedisHealthStatus(
                connected=False,
                ping_ms=elapsed_ms,
                error="PING returned False",
            )

        # Gather a small subset of server info for diagnostics.
        raw_info: Dict[str, Any] = client.info(section="server")
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
