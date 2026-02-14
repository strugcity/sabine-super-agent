"""
Tests for backend.worker.health
=================================

Tests the health-check helpers and HTTP handler.  The actual HTTP server
is tested by starting it on an ephemeral port and making real requests.
Redis/queue calls are patched so tests don't need a running Redis.
"""

import json
import socket
import time
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from backend.worker.health import (
    _collect_health,
    get_uptime_seconds,
    record_job_processed,
    start_health_server,
    stop_health_server,
)


def _free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 3.0) -> None:
    """Block until the server is listening on *port*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"Server did not start on port {port}")


# =========================================================================
# Unit helpers
# =========================================================================

class TestRecordJobProcessed:
    def test_sets_timestamp(self) -> None:
        record_job_processed()
        from backend.worker import health as _mod
        assert _mod._last_job_processed is not None
        # ISO-8601 format check
        assert "T" in _mod._last_job_processed


class TestGetUptimeSeconds:
    def test_returns_positive_float(self) -> None:
        assert get_uptime_seconds() >= 0.0


class TestCollectHealth:
    def test_returns_dict_with_status(self) -> None:
        """_collect_health should always return a dict with 'status'."""
        h = _collect_health()
        assert isinstance(h, dict)
        assert "status" in h
        assert h["status"] in ("healthy", "degraded", "unhealthy")

    def test_contains_uptime(self) -> None:
        h = _collect_health()
        assert "uptime_seconds" in h
        assert isinstance(h["uptime_seconds"], float)

    def test_redis_failure_marks_unhealthy(self) -> None:
        """If Redis is unreachable the status should be 'unhealthy'."""
        h = _collect_health()
        if not h["redis_connected"]:
            assert h["status"] == "unhealthy"


# =========================================================================
# Integration: real HTTP server on an ephemeral port
# Patch Redis/queue so the handler responds instantly.
# =========================================================================

def _mock_redis() -> MagicMock:
    r = MagicMock()
    r.ping.return_value = True
    return r


def _mock_queue_stats() -> dict:
    return {"pending": 0, "workers": 1, "started": 0, "failed": 0, "completed": 5}


class TestHealthHTTPServer:
    """Start/stop the server and make real HTTP requests."""

    @pytest.fixture(autouse=True)
    def _server(self) -> None:
        """Start on a free port with Redis mocked, stop after the test."""
        self.port = _free_port()
        # Patch the lazy imports that _collect_health uses so we don't
        # block on a real Redis connection.
        with patch(
            "backend.worker.health.get_redis_client",  # won't exist yet
            create=True,
        ), patch(
            "backend.services.redis_client.get_redis_client",
            return_value=_mock_redis(),
        ), patch(
            "backend.services.queue.get_queue_stats",
            return_value=_mock_queue_stats(),
        ):
            start_health_server(port=self.port)
            _wait_for_port(self.port)
            yield  # type: ignore[misc]
            stop_health_server()

    def test_health_endpoint_returns_json(self) -> None:
        url = f"http://127.0.0.1:{self.port}/health"
        with patch(
            "backend.services.redis_client.get_redis_client",
            return_value=_mock_redis(),
        ), patch(
            "backend.services.queue.get_queue_stats",
            return_value=_mock_queue_stats(),
        ):
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = json.loads(resp.read())
        assert "status" in body
        assert body["status"] == "healthy"

    def test_404_for_unknown_path(self) -> None:
        url = f"http://127.0.0.1:{self.port}/unknown"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=5)
        assert exc_info.value.code == 404
