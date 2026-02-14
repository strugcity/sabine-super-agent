"""
Tests for lib.agent.routers.memory
====================================

Tests the Pydantic models and endpoint logic for the memory router.
Endpoints that need Supabase or the ingestion pipeline are tested with
mocks; model validation tests are pure unit tests.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.agent.routers.memory import (
    ArchivedMemoryResponse,
    PromoteMemoryResponse,
    PROMOTE_SALIENCE_BOOST,
    router,
)


# =========================================================================
# Test app setup
# =========================================================================

def _override_verify_api_key() -> bool:
    return True


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    from lib.agent.shared import verify_api_key
    app.dependency_overrides[verify_api_key] = _override_verify_api_key
    return TestClient(app)


# =========================================================================
# Pydantic models
# =========================================================================

class TestModels:

    def test_archived_memory_response(self) -> None:
        r = ArchivedMemoryResponse(
            id="mem-1",
            original_memory_id="orig-1",
            content="test",
            salience_score=0.3,
            access_count=2,
            is_archived=True,
        )
        assert r.is_archived is True

    def test_promote_memory_response(self) -> None:
        r = PromoteMemoryResponse(
            success=True,
            memory_id="mem-1",
            new_salience_score=0.6,
            message="promoted",
        )
        assert r.success is True


# =========================================================================
# GET /memory/upload/supported-types
# =========================================================================

class TestSupportedTypes:

    def test_returns_supported_types(self, client: TestClient) -> None:
        resp = client.get("/memory/upload/supported-types")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "supported_types" in data
        assert data["max_file_size_bytes"] == 52428800


# =========================================================================
# POST /memory/ingest (mocked)
# =========================================================================

class TestMemoryIngest:

    @patch("lib.agent.routers.memory.ingest_user_message", new_callable=AsyncMock)
    def test_ingest_success(self, mock_ingest: AsyncMock, client: TestClient) -> None:
        mock_ingest.return_value = {
            "entities_created": 2,
            "entities_updated": 1,
            "memory_id": "00000000-0000-0000-0000-000000000001",
        }
        resp = client.post(
            "/memory/ingest",
            json={"user_id": "00000000-0000-0000-0000-000000000001", "content": "Hello world", "source": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["entities_created"] == 2

    @patch("lib.agent.routers.memory.ingest_user_message", new_callable=AsyncMock)
    def test_ingest_failure_returns_500(self, mock_ingest: AsyncMock, client: TestClient) -> None:
        mock_ingest.side_effect = RuntimeError("boom")
        resp = client.post(
            "/memory/ingest",
            json={"user_id": "00000000-0000-0000-0000-000000000001", "content": "fail"},
        )
        assert resp.status_code == 500


# =========================================================================
# POST /memory/query (mocked)
# =========================================================================

class TestMemoryQuery:

    @patch("lib.agent.routers.memory.retrieve_context", new_callable=AsyncMock)
    def test_query_success(self, mock_retrieve: AsyncMock, client: TestClient) -> None:
        mock_retrieve.return_value = "[RELEVANT MEMORIES]\nMemory: test content"
        resp = client.post(
            "/memory/query",
            json={"user_id": "00000000-0000-0000-0000-000000000001", "query": "what do you know about Jack?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "context" in data

    @patch("lib.agent.routers.memory.retrieve_context", new_callable=AsyncMock)
    def test_query_failure_returns_500(self, mock_retrieve: AsyncMock, client: TestClient) -> None:
        mock_retrieve.side_effect = RuntimeError("db down")
        resp = client.post(
            "/memory/query",
            json={"user_id": "00000000-0000-0000-0000-000000000001", "query": "fail"},
        )
        assert resp.status_code == 500


# =========================================================================
# Constants
# =========================================================================

class TestConstants:

    def test_promote_salience_boost_value(self) -> None:
        assert PROMOTE_SALIENCE_BOOST == 0.6
