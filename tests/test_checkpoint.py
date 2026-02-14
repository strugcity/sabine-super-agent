"""
Tests for backend.worker.checkpoint
=====================================

Tests the Redis-backed CheckpointManager using a fake Redis client
(no real Redis required).
"""

import json
from typing import Any, Dict, Optional

import pytest

from backend.worker.checkpoint import CheckpointManager, _CHECKPOINT_PREFIX, _CHECKPOINT_TTL


# =========================================================================
# Fake Redis client
# =========================================================================

class FakeRedis:
    """Minimal in-memory Redis stub for checkpoint tests."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


# =========================================================================
# Tests
# =========================================================================

class TestCheckpointManager:
    """Tests for the CheckpointManager lifecycle."""

    def _make_mgr(self, batch_id: str = "batch-001") -> tuple[CheckpointManager, FakeRedis]:
        redis = FakeRedis()
        mgr = CheckpointManager(batch_id=batch_id, redis_client=redis)
        return mgr, redis

    def test_key_format(self) -> None:
        mgr, _ = self._make_mgr("batch-xyz")
        assert mgr._key == f"{_CHECKPOINT_PREFIX}:batch-xyz"

    def test_save_and_load(self) -> None:
        mgr, _ = self._make_mgr()
        mgr.save(last_processed_index=9)
        cp = mgr.load()
        assert cp is not None
        assert cp["last_processed_index"] == 9
        assert cp["batch_id"] == "batch-001"
        assert "timestamp" in cp

    def test_save_with_metadata(self) -> None:
        mgr, _ = self._make_mgr()
        mgr.save(
            last_processed_index=19,
            metadata={"entries_processed": 20, "entries_remaining": 80},
        )
        cp = mgr.load()
        assert cp is not None
        assert cp["entries_processed"] == 20
        assert cp["entries_remaining"] == 80

    def test_load_returns_none_when_empty(self) -> None:
        mgr, _ = self._make_mgr()
        assert mgr.load() is None

    def test_clear_removes_checkpoint(self) -> None:
        mgr, _ = self._make_mgr()
        mgr.save(last_processed_index=5)
        assert mgr.load() is not None
        mgr.clear()
        assert mgr.load() is None

    def test_overwrite_checkpoint(self) -> None:
        mgr, _ = self._make_mgr()
        mgr.save(last_processed_index=5)
        mgr.save(last_processed_index=15)
        cp = mgr.load()
        assert cp is not None
        assert cp["last_processed_index"] == 15

    def test_separate_batches_isolated(self) -> None:
        redis = FakeRedis()
        mgr_a = CheckpointManager(batch_id="a", redis_client=redis)
        mgr_b = CheckpointManager(batch_id="b", redis_client=redis)

        mgr_a.save(last_processed_index=10)
        mgr_b.save(last_processed_index=20)

        cp_a = mgr_a.load()
        cp_b = mgr_b.load()
        assert cp_a is not None and cp_a["last_processed_index"] == 10
        assert cp_b is not None and cp_b["last_processed_index"] == 20

    def test_save_raises_on_redis_error(self) -> None:
        class BrokenRedis:
            def setex(self, *a: Any, **kw: Any) -> None:
                raise ConnectionError("redis down")

        mgr = CheckpointManager(batch_id="x", redis_client=BrokenRedis())
        with pytest.raises(ConnectionError):
            mgr.save(last_processed_index=0)

    def test_load_returns_none_on_redis_error(self) -> None:
        class BrokenRedis:
            def get(self, *a: Any, **kw: Any) -> None:
                raise ConnectionError("redis down")

        mgr = CheckpointManager(batch_id="x", redis_client=BrokenRedis())
        assert mgr.load() is None

    def test_clear_raises_on_redis_error(self) -> None:
        class BrokenRedis:
            def delete(self, *a: Any, **kw: Any) -> None:
                raise ConnectionError("redis down")

        mgr = CheckpointManager(batch_id="x", redis_client=BrokenRedis())
        with pytest.raises(ConnectionError):
            mgr.clear()
