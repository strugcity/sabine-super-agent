"""
Tests for Redis client singleton and queue producer.

All tests use mocking so no live Redis instance is required.
Run with:  pytest tests/test_redis_client.py -v

Strategy for lazy imports:
    Both ``redis_client.py`` and ``queue.py`` use lazy ``from X import Y``
    inside function bodies.  To intercept those we patch at the *source*
    package level (e.g. ``redis.Redis``) so that when the lazy import runs
    it picks up our mock.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """
    Ensure the Redis singleton is cleared before *and* after every test so
    tests are fully isolated.
    """
    import backend.services.redis_client as mod
    mod._redis_client = None
    yield
    mod._redis_client = None


@pytest.fixture()
def mock_redis_instance() -> MagicMock:
    """
    Return a mock Redis client instance with sensible defaults for PING
    and INFO responses.
    """
    instance = MagicMock()
    instance.ping.return_value = True
    instance.info.return_value = {
        "redis_version": "7.2.4",
        "uptime_in_seconds": 12345,
        "connected_clients": 3,
        "used_memory_human": "1.20M",
    }
    return instance


# =============================================================================
# Singleton tests
# =============================================================================

class TestGetRedisClient:
    """Tests for ``get_redis_client()``."""

    def test_returns_same_instance(self, mock_redis_instance: MagicMock) -> None:
        """The singleton should return the exact same object on repeated calls."""
        import backend.services.redis_client as mod

        # Patch at the source package so the lazy ``from redis import Redis``
        # inside get_redis_client() picks up our mock class.
        mock_cls = MagicMock()
        mock_cls.from_url.return_value = mock_redis_instance

        with patch("redis.Redis", mock_cls):
            first = mod.get_redis_client()
            second = mod.get_redis_client()

        assert first is second
        # ``from_url`` should be called only once (singleton)
        mock_cls.from_url.assert_called_once()

    def test_reset_clears_singleton(self) -> None:
        """``reset_redis_client()`` should force a fresh client on next call."""
        import backend.services.redis_client as mod

        mock_cls = MagicMock()
        # Return a *new* MagicMock on every call so we can assert identity
        mock_cls.from_url.side_effect = [MagicMock(), MagicMock()]

        with patch("redis.Redis", mock_cls):
            first = mod.get_redis_client()
            mod.reset_redis_client()
            second = mod.get_redis_client()

        assert first is not second
        assert mock_cls.from_url.call_count == 2


# =============================================================================
# Health-check tests
# =============================================================================

class TestCheckRedisHealth:
    """Tests for ``check_redis_health()``."""

    @pytest.mark.asyncio
    async def test_healthy_connection(self, mock_redis_instance: MagicMock) -> None:
        """When Redis is reachable, health should report ``connected=True``."""
        import backend.services.redis_client as mod

        # Inject a mock client directly into the singleton slot so
        # check_redis_health() does not try to connect to a real server.
        mod._redis_client = mock_redis_instance

        status = await mod.check_redis_health()

        assert status.connected is True
        assert status.ping_ms >= 0.0
        assert status.error is None
        assert "redis_version" in status.info

    @pytest.mark.asyncio
    async def test_unhealthy_connection(self) -> None:
        """When Redis is unreachable, health should report ``connected=False``."""
        import backend.services.redis_client as mod

        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("Connection refused")
        mod._redis_client = mock_client

        status = await mod.check_redis_health()

        assert status.connected is False
        assert status.error is not None
        assert "Connection refused" in status.error

    @pytest.mark.asyncio
    async def test_ping_returns_false(self) -> None:
        """If PING returns False, connected should be False."""
        import backend.services.redis_client as mod

        mock_client = MagicMock()
        mock_client.ping.return_value = False
        mod._redis_client = mock_client

        status = await mod.check_redis_health()

        assert status.connected is False
        assert status.error == "PING returned False"


# =============================================================================
# Health status model tests
# =============================================================================

class TestRedisHealthStatusModel:
    """Tests for the ``RedisHealthStatus`` Pydantic model."""

    def test_healthy_serialisation(self) -> None:
        """A healthy status should serialise all fields."""
        from backend.services.redis_client import RedisHealthStatus

        status = RedisHealthStatus(
            connected=True,
            ping_ms=1.23,
            info={"redis_version": "7.2.4"},
        )
        data: Dict[str, Any] = status.model_dump()
        assert data["connected"] is True
        assert data["ping_ms"] == 1.23
        assert data["error"] is None

    def test_unhealthy_serialisation(self) -> None:
        """An unhealthy status should include the error string."""
        from backend.services.redis_client import RedisHealthStatus

        status = RedisHealthStatus(
            connected=False,
            error="Connection refused",
        )
        data: Dict[str, Any] = status.model_dump()
        assert data["connected"] is False
        assert data["error"] == "Connection refused"


# =============================================================================
# Queue stats tests
# =============================================================================

class TestGetQueueStats:
    """Tests for ``get_queue_stats()``."""

    def test_stats_structure_when_redis_available(self) -> None:
        """Stats should return all expected keys when Redis is up."""
        import backend.services.redis_client as redis_mod

        # Inject a mock Redis client into the singleton
        mock_conn = MagicMock()
        redis_mod._redis_client = mock_conn

        mock_queue = MagicMock()
        mock_queue.__len__ = MagicMock(return_value=5)
        mock_queue.started_job_registry.count = 1
        mock_queue.failed_job_registry.count = 2
        mock_queue.finished_job_registry.count = 10
        mock_queue.name = "sabine-slow-path"

        mock_worker = MagicMock()
        mock_worker.state = "idle"

        # Patch the rq classes at their source so lazy imports find them
        with (
            patch("rq.Queue", return_value=mock_queue),
            patch("rq.Worker") as mock_worker_cls,
        ):
            mock_worker_cls.all.return_value = [mock_worker]

            from backend.services.queue import get_queue_stats
            stats = get_queue_stats()

        assert "queue_name" in stats
        assert stats["queue_name"] == "sabine-slow-path"
        assert "pending" in stats
        assert "failed" in stats
        assert "workers" in stats

    def test_stats_graceful_when_redis_unavailable(self) -> None:
        """Stats should return zero counts and an error key when Redis is down."""
        import backend.services.redis_client as redis_mod

        # Ensure the singleton raises when accessed
        redis_mod._redis_client = None

        # Make get_redis_client raise
        with patch(
            "backend.services.redis_client.get_redis_client",
            side_effect=ConnectionError("Redis not available"),
        ):
            from backend.services.queue import get_queue_stats
            stats = get_queue_stats()

        assert stats["queue_name"] == "sabine-slow-path"
        assert stats["pending"] == 0
        assert "error" in stats


# =============================================================================
# Enqueue tests
# =============================================================================

class TestEnqueueWalProcessing:
    """Tests for ``enqueue_wal_processing()``."""

    def test_enqueue_returns_job_id(self) -> None:
        """A successful enqueue should return the rq job ID."""
        import backend.services.redis_client as redis_mod

        # Inject a mock Redis client
        mock_conn = MagicMock()
        redis_mod._redis_client = mock_conn

        mock_job = MagicMock()
        mock_job.id = "rq-job-abc123"

        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = mock_job

        with (
            patch("rq.Queue", return_value=mock_queue),
            patch("rq.Retry"),
        ):
            from backend.services.queue import enqueue_wal_processing
            result = enqueue_wal_processing("some-wal-uuid")

        assert result == "rq-job-abc123"

    def test_enqueue_returns_none_on_failure(self) -> None:
        """When Redis is unavailable, enqueue should return None (not raise)."""
        import backend.services.redis_client as redis_mod

        # Ensure the singleton raises
        redis_mod._redis_client = None

        with patch(
            "backend.services.redis_client.get_redis_client",
            side_effect=ConnectionError("unavailable"),
        ):
            from backend.services.queue import enqueue_wal_processing
            result = enqueue_wal_processing("some-wal-uuid")

        assert result is None

    def test_enqueue_batch_empty_list(self) -> None:
        """Enqueuing an empty batch should return None without touching Redis."""
        from backend.services.queue import enqueue_wal_batch
        result = enqueue_wal_batch([])
        assert result is None


# =============================================================================
# Model tests
# =============================================================================

class TestQueueModels:
    """Tests for Pydantic models in queue.py."""

    def test_enqueue_result_success(self) -> None:
        from backend.services.queue import EnqueueResult

        r = EnqueueResult(job_id="abc", success=True)
        assert r.success is True
        assert r.job_id == "abc"
        assert r.error is None

    def test_enqueue_result_failure(self) -> None:
        from backend.services.queue import EnqueueResult

        r = EnqueueResult(success=False, error="Redis down")
        assert r.success is False
        assert r.job_id is None

    def test_queue_stats_defaults(self) -> None:
        from backend.services.queue import QueueStats

        s = QueueStats(queue_name="test-queue")
        assert s.pending == 0
        assert s.failed == 0
        assert s.workers == 0


# =============================================================================
# URL masking helper test
# =============================================================================

class TestRedisUrlSafe:
    """Tests for ``_redis_url_safe()``."""

    def test_masks_password(self) -> None:
        import backend.services.redis_client as mod

        original = mod.REDIS_URL
        try:
            mod.REDIS_URL = "redis://:supersecret@redis.railway.internal:6379/0"
            result = mod._redis_url_safe()
            assert "supersecret" not in result
            assert "*****" in result
            assert "redis.railway.internal:6379/0" in result
        finally:
            mod.REDIS_URL = original

    def test_no_password_unchanged(self) -> None:
        import backend.services.redis_client as mod

        original = mod.REDIS_URL
        try:
            mod.REDIS_URL = "redis://localhost:6379/0"
            result = mod._redis_url_safe()
            assert result == "redis://localhost:6379/0"
        finally:
            mod.REDIS_URL = original
