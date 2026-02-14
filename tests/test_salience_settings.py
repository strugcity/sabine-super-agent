"""
Tests for lib.agent.routers.salience_settings
===============================================

Tests the GET/PUT /api/settings/salience endpoints using a fake Redis
and FastAPI TestClient (no real Redis or auth required).
"""

import json
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.agent.routers.salience_settings import (
    SalienceWeightsRequest,
    SalienceWeightsResponse,
    _DEFAULT_WEIGHTS,
    router,
)


# =========================================================================
# Fake Redis
# =========================================================================

class FakeRedis:
    """Minimal in-memory Redis stub."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value


# =========================================================================
# Test app setup
# =========================================================================

_fake_redis = FakeRedis()


def _override_verify_api_key() -> bool:
    return True


def _override_get_redis() -> FakeRedis:
    return _fake_redis


@pytest.fixture(autouse=True)
def _reset_redis() -> None:
    """Clear fake Redis between tests."""
    _fake_redis._store.clear()


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    # Override auth dependency
    from lib.agent.shared import verify_api_key
    app.dependency_overrides[verify_api_key] = _override_verify_api_key
    # Patch the internal _get_redis helper
    with patch(
        "lib.agent.routers.salience_settings._get_redis",
        _override_get_redis,
    ):
        yield TestClient(app)


# =========================================================================
# GET /api/settings/salience
# =========================================================================

class TestGetSalienceWeights:

    def test_returns_defaults_when_no_custom(self, client: TestClient) -> None:
        resp = client.get("/api/settings/salience", params={"user_id": "user-1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_default"] is True
        assert data["w_recency"] == _DEFAULT_WEIGHTS["w_recency"]
        assert data["user_id"] == "user-1"

    def test_returns_custom_after_put(self, client: TestClient) -> None:
        # Store custom weights first
        _fake_redis.setex(
            "sabine:salience_weights:user-2",
            86400,
            json.dumps({"w_recency": 0.1, "w_frequency": 0.3, "w_emotional": 0.3, "w_causal": 0.3}),
        )
        resp = client.get("/api/settings/salience", params={"user_id": "user-2"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_default"] is False
        assert data["w_recency"] == 0.1


# =========================================================================
# PUT /api/settings/salience
# =========================================================================

class TestUpdateSalienceWeights:

    def test_valid_update(self, client: TestClient) -> None:
        resp = client.put(
            "/api/settings/salience",
            params={"user_id": "user-3"},
            json={
                "w_recency": 0.25,
                "w_frequency": 0.25,
                "w_emotional": 0.25,
                "w_causal": 0.25,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_default"] is False
        assert data["w_recency"] == 0.25

    def test_weights_not_summing_to_one_returns_400(self, client: TestClient) -> None:
        resp = client.put(
            "/api/settings/salience",
            params={"user_id": "user-4"},
            json={
                "w_recency": 0.5,
                "w_frequency": 0.5,
                "w_emotional": 0.5,
                "w_causal": 0.5,
            },
        )
        assert resp.status_code == 400
        assert "sum to 1.0" in resp.json()["detail"]

    def test_negative_weight_returns_422(self, client: TestClient) -> None:
        resp = client.put(
            "/api/settings/salience",
            params={"user_id": "user-5"},
            json={
                "w_recency": -0.1,
                "w_frequency": 0.4,
                "w_emotional": 0.4,
                "w_causal": 0.3,
            },
        )
        assert resp.status_code == 422  # Pydantic validation


# =========================================================================
# Pydantic models
# =========================================================================

class TestModels:

    def test_request_model(self) -> None:
        r = SalienceWeightsRequest(
            w_recency=0.4, w_frequency=0.2,
            w_emotional=0.2, w_causal=0.2,
        )
        assert r.w_recency == 0.4

    def test_response_model(self) -> None:
        r = SalienceWeightsResponse(
            user_id="u1",
            w_recency=0.4, w_frequency=0.2,
            w_emotional=0.2, w_causal=0.2,
            is_default=True,
        )
        assert r.is_default is True
