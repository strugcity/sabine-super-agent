"""
Slow Path Consolidation Pipeline Tests
========================================

Tests for the Week 3 Slow Path implementation:
- Single WAL entry consolidation
- Batch processing with checkpointing
- Checkpoint recovery (crash simulation)
- Entity resolution (create vs update)
- Conflict resolution (newer-wins strategy)
- Relationship extraction stub
- Failure alerting
- WAL entry status transitions
- Batch stats accuracy
- Pydantic model validation

All external dependencies (Supabase, Redis, Slack) are mocked.

Run with::

    python -m pytest tests/test_slow_path.py -v
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import UUID, uuid4

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# Test Fixtures
# =============================================================================

TEST_USER_ID: str = "00000000-0000-0000-0000-000000000001"
TEST_WAL_ID: str = str(uuid4())
TEST_WAL_ID_2: str = str(uuid4())
TEST_WAL_ID_3: str = str(uuid4())


def _make_wal_entry(
    wal_id: str = TEST_WAL_ID,
    status: str = "pending",
    message: str = "Schedule a meeting with John tomorrow at 3pm",
    user_id: str = TEST_USER_ID,
    entities: Optional[List[Dict[str, Any]]] = None,
    conflicts: Optional[List[Dict[str, Any]]] = None,
    retry_count: int = 0,
) -> MagicMock:
    """Create a mock WAL entry matching the WALEntry Pydantic model."""
    entry = MagicMock()
    entry.id = UUID(wal_id)
    entry.status = status
    entry.retry_count = retry_count
    raw_payload: Dict[str, Any] = {
        "user_id": user_id,
        "message": message,
        "source": "twilio_sms",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if entities is not None:
        raw_payload["entities"] = entities
    if conflicts is not None:
        raw_payload["conflicts"] = conflicts
    entry.raw_payload = raw_payload
    entry.metadata = {}
    entry.created_at = datetime.now(timezone.utc)
    return entry


def _make_supabase_response(data: Optional[List[Dict[str, Any]]] = None) -> MagicMock:
    """Create a mock Supabase response."""
    resp = MagicMock()
    resp.data = data if data is not None else []
    return resp


# =============================================================================
# Test: Pydantic Models
# =============================================================================

class TestPydanticModels:
    """Tests for ConsolidationResult and BatchConsolidationResult."""

    def test_consolidation_result_defaults(self) -> None:
        """ConsolidationResult should have sensible defaults."""
        from lib.db.models import ConsolidationResult

        result = ConsolidationResult(
            wal_entry_id=TEST_WAL_ID,
            status="processed",
        )
        assert result.wal_entry_id == TEST_WAL_ID
        assert result.status == "processed"
        assert result.entities_resolved == 0
        assert result.relationships_extracted == 0
        assert result.conflicts_resolved == 0
        assert result.duration_ms == 0.0
        assert result.error is None

    def test_consolidation_result_with_error(self) -> None:
        """ConsolidationResult should store error messages."""
        from lib.db.models import ConsolidationResult

        result = ConsolidationResult(
            wal_entry_id=TEST_WAL_ID,
            status="failed",
            error="Something went wrong",
        )
        assert result.status == "failed"
        assert result.error == "Something went wrong"

    def test_batch_consolidation_result_defaults(self) -> None:
        """BatchConsolidationResult should have sensible defaults."""
        from lib.db.models import BatchConsolidationResult

        result = BatchConsolidationResult(batch_id="batch-123")
        assert result.batch_id == "batch-123"
        assert result.total == 0
        assert result.processed == 0
        assert result.failed == 0
        assert result.skipped == 0
        assert result.duration_ms == 0.0
        assert result.checkpoint_count == 0

    def test_batch_consolidation_result_serialization(self) -> None:
        """BatchConsolidationResult should serialize to dict/JSON."""
        from lib.db.models import BatchConsolidationResult

        result = BatchConsolidationResult(
            batch_id="batch-456",
            total=100,
            processed=95,
            failed=3,
            skipped=2,
            duration_ms=5432.1,
            checkpoint_count=2,
        )
        d = result.model_dump()
        assert d["total"] == 100
        assert d["processed"] == 95
        assert d["failed"] == 3
        assert d["checkpoint_count"] == 2


# =============================================================================
# Test: Relationship Extraction Stub
# =============================================================================

class TestRelationshipExtractionStub:
    """Tests for extract_relationships_stub."""

    def test_stub_returns_valid_structure(self) -> None:
        """Stub should return list of dicts with expected keys."""
        from backend.worker.slow_path import extract_relationships_stub

        entities = [
            {"name": "John", "type": "person"},
            {"name": "Meeting", "type": "event"},
        ]
        rels = extract_relationships_stub(
            message="Schedule a meeting with John",
            entities=entities,
            source_wal_id=TEST_WAL_ID,
        )

        assert len(rels) == 1
        rel = rels[0]
        assert rel["subject"] == "John"
        assert rel["object"] == "Meeting"
        assert rel["predicate"] == "related_to"
        assert rel["confidence"] == 0.8
        assert rel["source_wal_id"] == TEST_WAL_ID
        assert rel["graph_layer"] == "entity"

    def test_stub_returns_empty_for_fewer_than_two_entities(self) -> None:
        """No relationships can be formed with fewer than 2 entities."""
        from backend.worker.slow_path import extract_relationships_stub

        # Zero entities
        assert extract_relationships_stub("msg", [], TEST_WAL_ID) == []

        # One entity
        assert extract_relationships_stub(
            "msg", [{"name": "A"}], TEST_WAL_ID
        ) == []

    def test_stub_returns_multiple_relationships(self) -> None:
        """Stub should create pairwise relationships for 3+ entities."""
        from backend.worker.slow_path import extract_relationships_stub

        entities = [
            {"name": "A"},
            {"name": "B"},
            {"name": "C"},
        ]
        rels = extract_relationships_stub("msg", entities, TEST_WAL_ID)
        assert len(rels) == 2  # A->B, B->C


# =============================================================================
# Test: Conflict Resolution
# =============================================================================

class TestConflictResolution:
    """Tests for resolve_conflicts."""

    def test_newer_data_wins(self) -> None:
        """Conflicts should be resolved with newer data taking precedence."""
        from backend.worker.slow_path import resolve_conflicts

        conflicts = [
            {
                "field": "phone",
                "old_value": "555-0000",
                "new_value": "555-1111",
                "entity_id": "ent-123",
            },
        ]

        results = resolve_conflicts(
            conflicts=conflicts, wal_entry_id=TEST_WAL_ID,
        )
        assert len(results) == 1
        assert results[0]["resolution"] == "newer_wins"
        assert results[0]["winner"] == "new"
        assert results[0]["resolved_value"] == "555-1111"
        assert results[0]["wal_entry_id"] == TEST_WAL_ID

    def test_empty_conflicts(self) -> None:
        """Empty conflict list should return empty results."""
        from backend.worker.slow_path import resolve_conflicts

        assert resolve_conflicts([], TEST_WAL_ID) == []

    def test_multiple_conflicts(self) -> None:
        """Multiple conflicts should all be resolved."""
        from backend.worker.slow_path import resolve_conflicts

        conflicts = [
            {"field": "email", "old_value": "a@b.com", "new_value": "c@d.com"},
            {"field": "name", "old_value": "Alice", "new_value": "Alicia"},
        ]
        results = resolve_conflicts(conflicts, TEST_WAL_ID)
        assert len(results) == 2
        for r in results:
            assert r["resolution"] == "newer_wins"


# =============================================================================
# Test: Single WAL Entry Consolidation
# =============================================================================

class TestConsolidateWALEntry:
    """Tests for consolidate_wal_entry (single entry)."""

    @patch("backend.services.wal.get_supabase_client")
    def test_entry_not_found_returns_skipped(
        self,
        mock_supabase: MagicMock,
    ) -> None:
        """Non-existent WAL entry should return 'skipped' status."""
        from backend.worker.slow_path import consolidate_wal_entry

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[])
        )
        mock_supabase.return_value = mock_client

        result = consolidate_wal_entry(TEST_WAL_ID)
        assert result.status == "skipped"
        assert result.wal_entry_id == TEST_WAL_ID

    @patch("backend.services.wal.get_supabase_client")
    def test_already_completed_returns_skipped(
        self,
        mock_supabase: MagicMock,
    ) -> None:
        """Completed WAL entry should return 'skipped' status."""
        from backend.worker.slow_path import consolidate_wal_entry

        wal_id = str(uuid4())
        entry_data = {
            "id": wal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": {"message": "test", "user_id": TEST_USER_ID},
            "status": "completed",
            "retry_count": 0,
            "idempotency_key": None,
            "last_error": None,
            "worker_id": None,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "checkpoint_id": None,
            "updated_at": None,
            "metadata": {},
        }

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[entry_data])
        )
        mock_supabase.return_value = mock_client

        result = consolidate_wal_entry(wal_id)
        assert result.status == "skipped"

    @patch("backend.services.wal.get_supabase_client")
    def test_successful_consolidation(
        self,
        mock_supabase: MagicMock,
    ) -> None:
        """Successful consolidation should process entities and mark completed."""
        from backend.worker.slow_path import consolidate_wal_entry

        wal_id = str(uuid4())
        entry_data = {
            "id": wal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": {
                "message": "Schedule meeting with John",
                "user_id": TEST_USER_ID,
                "entities": [
                    {"name": "John", "type": "person", "domain": "work"},
                    {"name": "Meeting", "type": "event", "domain": "work"},
                ],
            },
            "status": "pending",
            "retry_count": 0,
            "idempotency_key": None,
            "last_error": None,
            "worker_id": None,
            "processed_at": None,
            "checkpoint_id": None,
            "updated_at": None,
            "metadata": {},
        }

        mock_client = MagicMock()
        # get_entry_by_id + mark_processing/mark_completed all use table()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[entry_data])
        )
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[{"id": wal_id}])
        )
        # entity lookup returns empty (new entities)
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_response(data=[])
        )
        # entity insert returns new entity
        mock_client.table.return_value.insert.return_value.execute.return_value = (
            _make_supabase_response(data=[{"id": str(uuid4())}])
        )
        mock_supabase.return_value = mock_client

        result = consolidate_wal_entry(wal_id)
        assert result.status == "processed"
        assert result.wal_entry_id == wal_id
        assert result.relationships_extracted == 1  # stub: 2 entities -> 1 rel
        assert result.duration_ms >= 0.0

    @patch("backend.services.wal.get_supabase_client")
    def test_entry_marked_processed_after_consolidation(
        self,
        mock_supabase: MagicMock,
    ) -> None:
        """WAL entry should be marked 'completed' after successful processing."""
        from backend.worker.slow_path import consolidate_wal_entry

        wal_id = str(uuid4())
        entry_data = {
            "id": wal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": {
                "message": "test message",
                "user_id": TEST_USER_ID,
            },
            "status": "pending",
            "retry_count": 0,
            "idempotency_key": None,
            "last_error": None,
            "worker_id": None,
            "processed_at": None,
            "checkpoint_id": None,
            "updated_at": None,
            "metadata": {},
        }

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[entry_data])
        )
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[{"id": wal_id}])
        )
        mock_supabase.return_value = mock_client

        result = consolidate_wal_entry(wal_id)
        assert result.status == "processed"

        # Verify mark_completed was called (update with status='completed')
        update_calls = mock_client.table.return_value.update.call_args_list
        completed_calls = [
            c for c in update_calls
            if c[0] and isinstance(c[0][0], dict)
            and c[0][0].get("status") == "completed"
        ]
        assert len(completed_calls) >= 1, (
            "WAL entry should have been marked as 'completed'"
        )

    @patch("backend.services.wal.get_supabase_client")
    def test_empty_message_still_marks_completed(
        self,
        mock_supabase: MagicMock,
    ) -> None:
        """WAL entry with empty message should still be marked completed."""
        from backend.worker.slow_path import consolidate_wal_entry

        wal_id = str(uuid4())
        entry_data = {
            "id": wal_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": {"message": "", "user_id": TEST_USER_ID},
            "status": "pending",
            "retry_count": 0,
            "idempotency_key": None,
            "last_error": None,
            "worker_id": None,
            "processed_at": None,
            "checkpoint_id": None,
            "updated_at": None,
            "metadata": {},
        }

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[entry_data])
        )
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[{"id": wal_id}])
        )
        mock_supabase.return_value = mock_client

        result = consolidate_wal_entry(wal_id)
        assert result.status == "processed"


# =============================================================================
# Test: Entity Resolution
# =============================================================================

class TestEntityResolution:
    """Tests for resolve_entity / _async_resolve_entity."""

    @patch("backend.services.wal.get_supabase_client")
    def test_new_entity_created(self, mock_supabase: MagicMock) -> None:
        """Entity not in DB should be created."""
        from backend.worker.slow_path import resolve_entity

        new_id = str(uuid4())
        mock_client = MagicMock()
        # Lookup returns empty (entity does not exist)
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_response(data=[])
        )
        # Insert returns new entity
        mock_client.table.return_value.insert.return_value.execute.return_value = (
            _make_supabase_response(data=[{"id": new_id}])
        )
        mock_supabase.return_value = mock_client

        result = resolve_entity(
            entity_data={"name": "Alice", "type": "person", "domain": "work"},
            user_id=TEST_USER_ID,
        )
        assert result["action"] == "created"
        assert result["entity_id"] == new_id

    @patch("backend.services.wal.get_supabase_client")
    def test_existing_entity_updated(self, mock_supabase: MagicMock) -> None:
        """Entity already in DB should be updated with incremented count."""
        from backend.worker.slow_path import resolve_entity

        existing_id = str(uuid4())
        mock_client = MagicMock()
        # Lookup returns existing entity
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            _make_supabase_response(data=[{
                "id": existing_id,
                "name": "Alice",
                "type": "person",
                "domain": "work",
                "attributes": {"mention_count": 5},
            }])
        )
        # Update succeeds
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            _make_supabase_response(data=[{"id": existing_id}])
        )
        mock_supabase.return_value = mock_client

        result = resolve_entity(
            entity_data={"name": "Alice", "type": "person"},
            user_id=TEST_USER_ID,
        )
        assert result["action"] == "updated"
        assert result["entity_id"] == existing_id

        # Verify mention_count was incremented
        update_calls = mock_client.table.return_value.update.call_args_list
        assert len(update_calls) >= 1
        update_data = update_calls[0][0][0]
        assert update_data["attributes"]["mention_count"] == 6

    def test_empty_entity_name_skipped(self) -> None:
        """Entity with empty name should be skipped (no DB call needed)."""
        from backend.worker.slow_path import resolve_entity

        result = resolve_entity(
            entity_data={"name": "", "type": "person"},
            user_id=TEST_USER_ID,
        )
        assert result["action"] == "skipped"
        assert result["entity_id"] is None


# =============================================================================
# Test: Checkpoint Manager
# =============================================================================

class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_save_and_load(self) -> None:
        """Checkpoint should be saveable and loadable."""
        from backend.worker.checkpoint import CheckpointManager

        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # Will be overridden below
        mgr = CheckpointManager(batch_id="test-batch", redis_client=mock_redis)

        # Save checkpoint
        mgr.save(
            last_processed_index=49,
            metadata={"entries_processed": 50, "entries_remaining": 50},
        )
        mock_redis.setex.assert_called_once()
        saved_key = mock_redis.setex.call_args[0][0]
        saved_ttl = mock_redis.setex.call_args[0][1]
        saved_json = mock_redis.setex.call_args[0][2]
        assert saved_key == "sabine:checkpoint:test-batch"
        assert saved_ttl == 86_400
        payload = json.loads(saved_json)
        assert payload["last_processed_index"] == 49
        assert payload["entries_processed"] == 50

    def test_load_returns_none_when_empty(self) -> None:
        """Loading a non-existent checkpoint should return None."""
        from backend.worker.checkpoint import CheckpointManager

        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mgr = CheckpointManager(batch_id="missing", redis_client=mock_redis)

        result = mgr.load()
        assert result is None

    def test_load_returns_checkpoint_data(self) -> None:
        """Loading an existing checkpoint should return its data."""
        from backend.worker.checkpoint import CheckpointManager

        saved_data = json.dumps({
            "batch_id": "test-batch",
            "last_processed_index": 49,
            "entries_processed": 50,
            "entries_remaining": 50,
            "timestamp": "2026-02-13T10:00:00+00:00",
        })

        mock_redis = MagicMock()
        mock_redis.get.return_value = saved_data
        mgr = CheckpointManager(batch_id="test-batch", redis_client=mock_redis)

        result = mgr.load()
        assert result is not None
        assert result["last_processed_index"] == 49

    def test_clear_removes_checkpoint(self) -> None:
        """Clearing should delete the Redis key."""
        from backend.worker.checkpoint import CheckpointManager

        mock_redis = MagicMock()
        mgr = CheckpointManager(batch_id="done-batch", redis_client=mock_redis)

        mgr.clear()
        mock_redis.delete.assert_called_once_with("sabine:checkpoint:done-batch")


# =============================================================================
# Test: Batch Processing with Checkpointing
# =============================================================================

class TestConsolidateWALBatch:
    """Tests for consolidate_wal_batch."""

    @patch("backend.worker.slow_path._async_consolidate_entry")
    @patch("backend.worker.checkpoint.CheckpointManager.load")
    @patch("backend.worker.checkpoint.CheckpointManager.save")
    @patch("backend.worker.checkpoint.CheckpointManager.clear")
    def test_batch_processes_all_entries(
        self,
        mock_clear: MagicMock,
        mock_save: MagicMock,
        mock_load: MagicMock,
        mock_consolidate: MagicMock,
    ) -> None:
        """Batch should process all entries and return accurate stats."""
        from backend.worker.slow_path import consolidate_wal_batch
        from lib.db.models import ConsolidationResult

        mock_load.return_value = None  # No prior checkpoint

        # All entries succeed
        async def fake_consolidate(wal_id: str) -> ConsolidationResult:
            return ConsolidationResult(
                wal_entry_id=wal_id, status="processed",
            )

        mock_consolidate.side_effect = fake_consolidate

        ids = [str(uuid4()) for _ in range(5)]
        result = consolidate_wal_batch(ids, checkpoint_interval=3)

        assert result.total == 5
        assert result.processed == 5
        assert result.failed == 0
        assert result.skipped == 0
        assert result.duration_ms >= 0.0

    @patch("backend.worker.slow_path._async_consolidate_entry")
    @patch("backend.worker.checkpoint.CheckpointManager.load")
    @patch("backend.worker.checkpoint.CheckpointManager.save")
    @patch("backend.worker.checkpoint.CheckpointManager.clear")
    def test_batch_checkpoint_saved_every_n_entries(
        self,
        mock_clear: MagicMock,
        mock_save: MagicMock,
        mock_load: MagicMock,
        mock_consolidate: MagicMock,
    ) -> None:
        """Checkpoint should be saved every checkpoint_interval entries."""
        from backend.worker.slow_path import consolidate_wal_batch
        from lib.db.models import ConsolidationResult

        mock_load.return_value = None

        async def fake_consolidate(wal_id: str) -> ConsolidationResult:
            return ConsolidationResult(
                wal_entry_id=wal_id, status="processed",
            )

        mock_consolidate.side_effect = fake_consolidate

        ids = [str(uuid4()) for _ in range(10)]
        result = consolidate_wal_batch(ids, checkpoint_interval=3)

        # With 10 entries and interval=3, checkpoints at indices:
        # 2 (index 2, 3rd entry), 5, 8, 9 (last entry)
        assert mock_save.call_count == 4
        assert result.checkpoint_count == 4

    @patch("backend.worker.slow_path._async_consolidate_entry")
    @patch("backend.worker.checkpoint.CheckpointManager.load")
    @patch("backend.worker.checkpoint.CheckpointManager.save")
    @patch("backend.worker.checkpoint.CheckpointManager.clear")
    def test_batch_resume_from_checkpoint(
        self,
        mock_clear: MagicMock,
        mock_save: MagicMock,
        mock_load: MagicMock,
        mock_consolidate: MagicMock,
    ) -> None:
        """Batch should resume from last checkpoint on crash recovery."""
        from backend.worker.slow_path import consolidate_wal_batch
        from lib.db.models import ConsolidationResult

        # Simulate prior checkpoint at index 49 (50 entries done)
        mock_load.return_value = {
            "last_processed_index": 49,
            "entries_processed": 48,
            "entries_failed": 2,
            "entries_skipped": 0,
            "checkpoint_count": 1,
        }

        call_count = 0

        async def fake_consolidate(wal_id: str) -> ConsolidationResult:
            nonlocal call_count
            call_count += 1
            return ConsolidationResult(
                wal_entry_id=wal_id, status="processed",
            )

        mock_consolidate.side_effect = fake_consolidate

        ids = [str(uuid4()) for _ in range(100)]
        result = consolidate_wal_batch(ids, checkpoint_interval=100)

        # Should only process entries 50-99 (50 entries, not all 100)
        assert call_count == 50
        # Processed should be 48 (from checkpoint) + 50 (new) = 98
        assert result.processed == 98
        assert result.failed == 2  # carried from checkpoint

    @patch("backend.worker.slow_path._async_consolidate_entry")
    @patch("backend.worker.checkpoint.CheckpointManager.load")
    @patch("backend.worker.checkpoint.CheckpointManager.save")
    @patch("backend.worker.checkpoint.CheckpointManager.clear")
    def test_batch_stats_accurate_with_mixed_results(
        self,
        mock_clear: MagicMock,
        mock_save: MagicMock,
        mock_load: MagicMock,
        mock_consolidate: MagicMock,
    ) -> None:
        """Batch stats should accurately count processed, failed, skipped."""
        from backend.worker.slow_path import consolidate_wal_batch
        from lib.db.models import ConsolidationResult

        mock_load.return_value = None

        statuses = ["processed", "failed", "skipped", "processed", "processed"]

        async def fake_consolidate(wal_id: str) -> ConsolidationResult:
            idx = ids.index(wal_id)
            return ConsolidationResult(
                wal_entry_id=wal_id,
                status=statuses[idx],
                error="oops" if statuses[idx] == "failed" else None,
            )

        mock_consolidate.side_effect = fake_consolidate

        ids = [str(uuid4()) for _ in range(5)]
        result = consolidate_wal_batch(ids, checkpoint_interval=100)

        assert result.total == 5
        assert result.processed == 3
        assert result.failed == 1
        assert result.skipped == 1


# =============================================================================
# Test: Failure Alerting
# =============================================================================

class TestFailureAlerting:
    """Tests for alerts module."""

    def test_failure_alert_logs_critical(self) -> None:
        """send_failure_alert should log at CRITICAL level."""
        from backend.worker.alerts import send_failure_alert
        import logging

        with patch.object(logging.getLogger("backend.worker.alerts"), "critical") as mock_log:
            asyncio.run(send_failure_alert(
                error_summary="DB connection lost",
                wal_entry_id=TEST_WAL_ID,
                retry_count=3,
            ))
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0][0]
            assert "permanently failed" in call_args

    def test_recovery_alert_logs_info(self) -> None:
        """send_recovery_alert should log at INFO level."""
        from backend.worker.alerts import send_recovery_alert
        import logging

        with patch.object(logging.getLogger("backend.worker.alerts"), "info") as mock_log:
            asyncio.run(send_recovery_alert(wal_entry_id=TEST_WAL_ID))
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0][0]
            assert "recovered" in call_args

    @patch("backend.worker.alerts.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    def test_slack_stub_does_not_raise(self) -> None:
        """Slack posting should not raise even with a configured webhook."""
        from backend.worker.alerts import send_failure_alert

        # Should not raise
        asyncio.run(send_failure_alert(
            error_summary="test error",
            wal_entry_id=TEST_WAL_ID,
            retry_count=3,
        ))


# =============================================================================
# Test: Jobs Wiring
# =============================================================================

class TestJobsWiring:
    """Tests that jobs.py correctly delegates to slow_path."""

    @patch("backend.worker.jobs._fire_failure_alert")
    @patch("backend.worker.jobs._record_health")
    @patch("backend.worker.slow_path.consolidate_wal_entry")
    def test_process_wal_entry_delegates_to_slow_path(
        self,
        mock_consolidate: MagicMock,
        mock_health: MagicMock,
        mock_alert: MagicMock,
    ) -> None:
        """process_wal_entry should call consolidate_wal_entry."""
        from backend.worker.jobs import process_wal_entry
        from lib.db.models import ConsolidationResult

        mock_consolidate.return_value = ConsolidationResult(
            wal_entry_id=TEST_WAL_ID,
            status="processed",
            entities_resolved=2,
        )

        result = process_wal_entry(TEST_WAL_ID)
        mock_consolidate.assert_called_once_with(TEST_WAL_ID)
        mock_health.assert_called_once()
        assert result["status"] == "processed"
        assert result["entities_resolved"] == 2

    @patch("backend.worker.jobs._fire_failure_alert")
    @patch("backend.worker.jobs._record_health")
    @patch("backend.worker.slow_path.consolidate_wal_batch")
    def test_process_wal_batch_delegates_to_slow_path(
        self,
        mock_consolidate: MagicMock,
        mock_health: MagicMock,
        mock_alert: MagicMock,
    ) -> None:
        """process_wal_batch should call consolidate_wal_batch."""
        from backend.worker.jobs import process_wal_batch
        from lib.db.models import BatchConsolidationResult

        mock_consolidate.return_value = BatchConsolidationResult(
            batch_id="batch-abc",
            total=5,
            processed=5,
            failed=0,
        )

        ids = [str(uuid4()) for _ in range(5)]
        result = process_wal_batch(ids)
        mock_consolidate.assert_called_once()
        mock_health.assert_called_once()
        assert result["status"] == "processed"
        assert result["total"] == 5

    @patch("backend.worker.jobs._fire_failure_alert")
    @patch("backend.worker.jobs._record_health")
    @patch("backend.worker.slow_path.consolidate_wal_entry")
    def test_failure_alert_fired_on_failed_entry(
        self,
        mock_consolidate: MagicMock,
        mock_health: MagicMock,
        mock_alert: MagicMock,
    ) -> None:
        """Failure alert should fire when an entry fails."""
        from backend.worker.jobs import process_wal_entry
        from lib.db.models import ConsolidationResult

        mock_consolidate.return_value = ConsolidationResult(
            wal_entry_id=TEST_WAL_ID,
            status="failed",
            error="Something broke",
        )

        result = process_wal_entry(TEST_WAL_ID)
        assert result["status"] == "failed"
        mock_alert.assert_called_once()
        alert_kwargs = mock_alert.call_args
        assert "Something broke" in str(alert_kwargs)
