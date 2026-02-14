"""
Integration tests for the rq queue routes and WAL-queue bridge.

All tests use mocking for Redis and Supabase so no live connections
are required.

Run with:  pytest tests/test_queue_integration.py -v

Coverage:
- GET  /api/queue/health       (queue_routes.py)
- POST /api/queue/enqueue      (queue_routes.py)
- GET  /api/queue/stats        (queue_routes.py)
- POST /api/queue/retry-failed (queue_routes.py)
- enqueue_wal_for_processing   (wal_queue_bridge.py)
- enqueue_pending_wal_entries  (wal_queue_bridge.py)

Strategy for lazy imports:
    The route handlers and bridge module use lazy ``from X import Y`` inside
    function bodies to avoid import-time side effects.  To intercept those we
    patch at the *source* module (e.g. ``backend.services.redis_client``) so
    the lazy import resolves to our mock.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Minimal FastAPI app that mounts only the queue router (avoids pulling in
# heavy deps from the full server.py).
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.agent.routers.queue_routes import router as queue_router

_test_app = FastAPI()
_test_app.include_router(queue_router)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def _reset_redis_singleton() -> None:
    """Ensure the Redis singleton is cleared between tests."""
    import backend.services.redis_client as mod

    mod._redis_client = None
    yield
    mod._redis_client = None


@pytest.fixture()
def api_key_header() -> Dict[str, str]:
    """Return an X-API-Key header that will pass ``verify_api_key``."""
    return {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _patch_api_key() -> None:  # type: ignore[misc]
    """Ensure the shared AGENT_API_KEY matches our test header."""
    with patch("lib.agent.shared.AGENT_API_KEY", "test-key"):
        yield


@pytest.fixture()
def client() -> TestClient:
    """Return a ``TestClient`` bound to the test app."""
    return TestClient(_test_app)


# =============================================================================
# GET /api/queue/health
# =============================================================================

class TestQueueHealth:
    """Tests for GET /api/queue/health."""

    def test_healthy_response(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """When Redis and the queue are available the response should report healthy."""
        from backend.services.redis_client import RedisHealthStatus

        mock_health = RedisHealthStatus(
            connected=True,
            ping_ms=0.5,
            info={"redis_version": "7.2.4"},
        )

        mock_stats: Dict[str, Any] = {
            "queue_name": "sabine-slow-path",
            "pending": 3,
            "started": 1,
            "failed": 0,
            "completed": 42,
            "workers": 1,
        }

        # Patch at the *source* module so lazy imports pick up mocks.
        with (
            patch(
                "backend.services.redis_client.check_redis_health",
                new_callable=AsyncMock,
                return_value=mock_health,
            ),
            patch(
                "backend.services.queue.get_queue_stats",
                return_value=mock_stats,
            ),
        ):
            resp = client.get("/api/queue/health", headers=api_key_header)

        assert resp.status_code == 200
        body = resp.json()
        assert body["redis_connected"] is True
        assert body["queue_name"] == "sabine-slow-path"
        assert body["pending_jobs"] == 3
        assert body["failed_jobs"] == 0
        assert body["workers"] == 1
        assert body["redis_ping_ms"] == 0.5
        assert body["error"] is None

    def test_unhealthy_response(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """When Redis is down the response should report unhealthy."""
        from backend.services.redis_client import RedisHealthStatus

        mock_health = RedisHealthStatus(
            connected=False,
            error="Connection refused",
        )
        mock_stats: Dict[str, Any] = {
            "queue_name": "sabine-slow-path",
            "pending": 0,
            "started": 0,
            "failed": 0,
            "completed": 0,
            "workers": 0,
            "error": "Connection refused",
        }

        with (
            patch(
                "backend.services.redis_client.check_redis_health",
                new_callable=AsyncMock,
                return_value=mock_health,
            ),
            patch(
                "backend.services.queue.get_queue_stats",
                return_value=mock_stats,
            ),
        ):
            resp = client.get("/api/queue/health", headers=api_key_header)

        assert resp.status_code == 200
        body = resp.json()
        assert body["redis_connected"] is False
        assert body["error"] is not None

    def test_requires_api_key(self, client: TestClient) -> None:
        """Health endpoint should reject requests without an API key."""
        resp = client.get("/api/queue/health")
        assert resp.status_code == 401


# =============================================================================
# POST /api/queue/enqueue
# =============================================================================

class TestQueueEnqueue:
    """Tests for POST /api/queue/enqueue."""

    def test_successful_enqueue(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """A valid WAL entry ID should be enqueued and return 202."""
        with patch(
            "backend.services.queue.enqueue_wal_processing",
            return_value="rq-job-xyz",
        ):
            resp = client.post(
                "/api/queue/enqueue",
                json={"wal_entry_id": str(uuid4())},
                headers=api_key_header,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "enqueued"
        assert body["job_id"] == "rq-job-xyz"

    def test_enqueue_returns_none(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """When the queue is unavailable enqueue returns None and status 202 with failed."""
        with patch(
            "backend.services.queue.enqueue_wal_processing",
            return_value=None,
        ):
            resp = client.post(
                "/api/queue/enqueue",
                json={"wal_entry_id": str(uuid4())},
                headers=api_key_header,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "failed"
        assert body["job_id"] is None

    def test_enqueue_raises_returns_503(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """If enqueue raises an exception the endpoint should return 503."""
        with patch(
            "backend.services.queue.enqueue_wal_processing",
            side_effect=ConnectionError("Redis gone"),
        ):
            resp = client.post(
                "/api/queue/enqueue",
                json={"wal_entry_id": str(uuid4())},
                headers=api_key_header,
            )

        assert resp.status_code == 503

    def test_rejects_missing_wal_entry_id(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """Request body without wal_entry_id should be rejected with 422."""
        resp = client.post(
            "/api/queue/enqueue",
            json={},
            headers=api_key_header,
        )
        assert resp.status_code == 422

    def test_requires_api_key(self, client: TestClient) -> None:
        """Enqueue endpoint should reject requests without an API key."""
        resp = client.post(
            "/api/queue/enqueue",
            json={"wal_entry_id": str(uuid4())},
        )
        assert resp.status_code == 401


# =============================================================================
# GET /api/queue/stats
# =============================================================================

class TestQueueStats:
    """Tests for GET /api/queue/stats."""

    def test_returns_valid_structure(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """Stats endpoint should return all expected fields."""
        mock_stats: Dict[str, Any] = {
            "queue_name": "sabine-slow-path",
            "pending": 10,
            "started": 2,
            "failed": 1,
            "completed": 50,
            "workers": 1,
        }

        with patch(
            "backend.services.queue.get_queue_stats",
            return_value=mock_stats,
        ):
            resp = client.get("/api/queue/stats", headers=api_key_header)

        assert resp.status_code == 200
        body = resp.json()
        assert body["queue_name"] == "sabine-slow-path"
        assert body["pending"] == 10
        assert body["started"] == 2
        assert body["failed"] == 1
        assert body["completed"] == 50
        assert body["workers"] == 1

    def test_stats_error_returns_503(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """When get_queue_stats raises, the endpoint should return 503."""
        with patch(
            "backend.services.queue.get_queue_stats",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            resp = client.get("/api/queue/stats", headers=api_key_header)

        assert resp.status_code == 503


# =============================================================================
# POST /api/queue/retry-failed
# =============================================================================

class TestRetryFailed:
    """Tests for POST /api/queue/retry-failed."""

    def test_retry_requeues_jobs(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """Should requeue all failed jobs and report the count."""
        mock_registry = MagicMock()
        mock_registry.get_job_ids.return_value = ["job-1", "job-2"]
        mock_registry.requeue = MagicMock()

        mock_queue = MagicMock()
        mock_queue.failed_job_registry = mock_registry

        # Patch the rq.Queue class at source so the lazy import picks it up,
        # and also patch get_redis_client so it does not try to connect.
        with (
            patch("rq.Queue", return_value=mock_queue),
            patch(
                "backend.services.redis_client.get_redis_client",
                return_value=MagicMock(),
            ),
        ):
            resp = client.post("/api/queue/retry-failed", headers=api_key_header)

        assert resp.status_code == 200
        body = resp.json()
        assert body["requeued"] == 2
        assert body["errors"] == []

    def test_retry_reports_individual_errors(
        self, client: TestClient, api_key_header: Dict[str, str]
    ) -> None:
        """If a single requeue fails, it should be reported in the errors list."""
        mock_registry = MagicMock()
        mock_registry.get_job_ids.return_value = ["job-ok", "job-bad"]
        mock_registry.requeue.side_effect = [None, RuntimeError("corrupt job")]

        mock_queue = MagicMock()
        mock_queue.failed_job_registry = mock_registry

        with (
            patch("rq.Queue", return_value=mock_queue),
            patch(
                "backend.services.redis_client.get_redis_client",
                return_value=MagicMock(),
            ),
        ):
            resp = client.post("/api/queue/retry-failed", headers=api_key_header)

        assert resp.status_code == 200
        body = resp.json()
        assert body["requeued"] == 1
        assert len(body["errors"]) == 1
        assert "job-bad" in body["errors"][0]


# =============================================================================
# WAL-Queue Bridge: enqueue_wal_for_processing
# =============================================================================

class TestEnqueueWalForProcessing:
    """Tests for ``enqueue_wal_for_processing()``."""

    @pytest.mark.asyncio
    async def test_returns_job_id_on_success(self) -> None:
        """Should return a job ID when the queue accepts the entry."""
        with patch(
            "backend.services.queue.enqueue_wal_processing",
            return_value="rq-bridge-123",
        ):
            from backend.services.wal_queue_bridge import enqueue_wal_for_processing

            result = await enqueue_wal_for_processing("wal-uuid-1")

        assert result == "rq-bridge-123"

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self) -> None:
        """Should return None (not raise) when the queue is unavailable."""
        with patch(
            "backend.services.queue.enqueue_wal_processing",
            side_effect=ConnectionError("Redis gone"),
        ):
            from backend.services.wal_queue_bridge import enqueue_wal_for_processing

            result = await enqueue_wal_for_processing("wal-uuid-2")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_enqueue_returns_none(self) -> None:
        """When the underlying enqueue returns None, the bridge should as well."""
        with patch(
            "backend.services.queue.enqueue_wal_processing",
            return_value=None,
        ):
            from backend.services.wal_queue_bridge import enqueue_wal_for_processing

            result = await enqueue_wal_for_processing("wal-uuid-3")

        assert result is None


# =============================================================================
# WAL-Queue Bridge: enqueue_pending_wal_entries
# =============================================================================

class TestEnqueuePendingWalEntries:
    """Tests for ``enqueue_pending_wal_entries()``."""

    @pytest.mark.asyncio
    async def test_enqueues_pending_entries(self) -> None:
        """Should find pending entries and enqueue them as a batch."""
        fake_entry_1 = MagicMock()
        fake_entry_1.id = uuid4()
        fake_entry_1.raw_payload = {"user_id": "user-a", "message": "hello"}

        fake_entry_2 = MagicMock()
        fake_entry_2.id = uuid4()
        fake_entry_2.raw_payload = {"user_id": "user-b", "message": "hi"}

        mock_wal_service = MagicMock()
        mock_wal_service.get_pending_entries = AsyncMock(
            return_value=[fake_entry_1, fake_entry_2]
        )

        # Patch at the source modules that the lazy imports resolve to.
        with (
            patch(
                "backend.services.wal.WALService",
                return_value=mock_wal_service,
            ),
            patch(
                "backend.services.queue.enqueue_wal_batch",
                return_value="batch-job-1",
            ) as mock_batch,
        ):
            from backend.services.wal_queue_bridge import enqueue_pending_wal_entries

            job_ids = await enqueue_pending_wal_entries()

        assert len(job_ids) == 1
        assert job_ids[0] == "batch-job-1"
        # Verify the batch was called with both entry IDs
        called_ids = mock_batch.call_args[1].get("wal_entry_ids") or mock_batch.call_args[0][0]
        assert len(called_ids) == 2

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self) -> None:
        """When user_id is provided, only that user entries should be enqueued."""
        entry_a = MagicMock()
        entry_a.id = uuid4()
        entry_a.raw_payload = {"user_id": "user-a"}

        entry_b = MagicMock()
        entry_b.id = uuid4()
        entry_b.raw_payload = {"user_id": "user-b"}

        mock_wal_service = MagicMock()
        mock_wal_service.get_pending_entries = AsyncMock(
            return_value=[entry_a, entry_b]
        )

        with (
            patch(
                "backend.services.wal.WALService",
                return_value=mock_wal_service,
            ),
            patch(
                "backend.services.queue.enqueue_wal_batch",
                return_value="batch-user-a",
            ) as mock_batch,
        ):
            from backend.services.wal_queue_bridge import enqueue_pending_wal_entries

            job_ids = await enqueue_pending_wal_entries(user_id="user-a")

        assert len(job_ids) == 1
        called_ids = mock_batch.call_args[1].get("wal_entry_ids") or mock_batch.call_args[0][0]
        assert len(called_ids) == 1
        assert str(entry_a.id) in called_ids

    @pytest.mark.asyncio
    async def test_no_pending_entries(self) -> None:
        """Should return an empty list when there are no pending entries."""
        mock_wal_service = MagicMock()
        mock_wal_service.get_pending_entries = AsyncMock(return_value=[])

        with patch(
            "backend.services.wal.WALService",
            return_value=mock_wal_service,
        ):
            from backend.services.wal_queue_bridge import enqueue_pending_wal_entries

            job_ids = await enqueue_pending_wal_entries()

        assert job_ids == []

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self) -> None:
        """If the WAL service raises, the bridge should return empty (not raise)."""
        mock_wal_service = MagicMock()
        mock_wal_service.get_pending_entries = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )

        with patch(
            "backend.services.wal.WALService",
            return_value=mock_wal_service,
        ):
            from backend.services.wal_queue_bridge import enqueue_pending_wal_entries

            job_ids = await enqueue_pending_wal_entries()

        assert job_ids == []


# =============================================================================
# Pydantic Response Model Tests
# =============================================================================

class TestResponseModels:
    """Verify that all Pydantic response models serialize correctly."""

    def test_queue_health_response_model(self) -> None:
        from lib.agent.routers.queue_routes import QueueHealthResponse

        r = QueueHealthResponse(
            redis_connected=True,
            queue_name="sabine-slow-path",
            pending_jobs=5,
            failed_jobs=0,
            workers=1,
            redis_ping_ms=1.0,
        )
        data = r.model_dump()
        assert data["redis_connected"] is True
        assert data["error"] is None

    def test_enqueue_response_model(self) -> None:
        from lib.agent.routers.queue_routes import EnqueueResponse

        r = EnqueueResponse(job_id="abc-123", status="enqueued")
        data = r.model_dump()
        assert data["status"] == "enqueued"
        assert data["job_id"] == "abc-123"

    def test_queue_stats_response_model(self) -> None:
        from lib.agent.routers.queue_routes import QueueStatsResponse

        r = QueueStatsResponse(queue_name="test-q", pending=10, workers=2)
        data = r.model_dump()
        assert data["pending"] == 10
        assert data["workers"] == 2
        assert data["failed"] == 0  # default

    def test_retry_failed_response_model(self) -> None:
        from lib.agent.routers.queue_routes import RetryFailedResponse

        r = RetryFailedResponse(requeued=3, errors=["job-1 failed"])
        data = r.model_dump()
        assert data["requeued"] == 3
        assert len(data["errors"]) == 1
