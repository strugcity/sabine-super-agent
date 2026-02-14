"""
Fast Path Pipeline Tests
========================

Comprehensive test suite for the Fast Path pipeline service
(``backend/services/fast_path.py``) and its timing instrumentation
(``backend/services/fast_path_timing.py``).

Test Categories:
1. WAL entry creation (every message must produce a WAL entry)
2. Entity extraction stub (basic NER patterns)
3. Embedding generation stub (deterministic placeholder)
4. Parallel execution (entity extraction + embedding via asyncio.gather)
5. Conflict detection (read-only comparison with existing entities)
6. No-mutation guarantee (no INSERT/UPDATE to entity tables)
7. Queue enqueue (WAL entry pushed to Slow Path)
8. FastPathResult structure and timing data
9. Timing instrumentation (context manager, Pydantic model)
10. Error handling and graceful degradation

All Supabase and Redis interactions are mocked so no real connections
are required.
"""

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Pre-import modules so patches work correctly on lazy imports
import backend.services.fast_path as fast_path_mod
from backend.services.fast_path import (
    ExtractedEntity,
    ConflictFlag,
    FastPathResult,
    extract_entities_stub,
    generate_embedding_stub,
    detect_conflicts,
    retrieve_memories_readonly,
    process_fast_path,
)
from backend.services.fast_path_timing import (
    FastPathTimings,
    TimingBlock,
    timing_block,
)


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_SESSION_ID = "test-session-abc"
TEST_MESSAGE = "Meet Alice at Central Park tomorrow at 3 PM"
TEST_WAL_ENTRY_ID = str(uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wal_entry_mock(entry_id: str = TEST_WAL_ENTRY_ID) -> MagicMock:
    """Build a mock WAL entry returned by WALService.create_entry()."""
    entry = MagicMock()
    entry.id = UUID(entry_id) if isinstance(entry_id, str) else entry_id
    entry.status = "pending"
    entry.raw_payload = {
        "user_id": TEST_USER_ID,
        "message": TEST_MESSAGE,
        "source": "fast_path",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return entry


def _mock_supabase_table(data: list[dict[str, Any]] | None = None) -> MagicMock:
    """Create a mock Supabase table with chainable query methods."""
    mock_response = MagicMock()
    mock_response.data = data if data is not None else []

    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.in_.return_value = mock_table
    mock_table.order.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = mock_response
    return mock_table


def _wal_and_queue_patches(
    wal_entry: MagicMock | None = None,
    queue_job_id: str | None = "job-123",
    queue_side_effect: Exception | None = None,
):
    """
    Return a list of context managers that mock the WAL service and queue bridge.

    Since process_fast_path uses lazy imports inside functions, we must
    patch at the *source* module where the name is defined.
    """
    if wal_entry is None:
        wal_entry = _make_wal_entry_mock()

    mock_wal_instance = AsyncMock()
    mock_wal_instance.create_entry = AsyncMock(return_value=wal_entry)

    patches = {
        "wal_cls": patch(
            "backend.services.wal.WALService",
            return_value=mock_wal_instance,
        ),
        "enqueue": patch(
            "backend.services.wal_queue_bridge.enqueue_wal_for_processing",
            new_callable=AsyncMock,
            return_value=queue_job_id,
            side_effect=queue_side_effect,
        ),
        "supabase_client": patch(
            "backend.services.wal.get_supabase_client",
            return_value=MagicMock(),
        ),
    }
    return patches, mock_wal_instance


# =============================================================================
# 1. WAL Entry Creation Tests
# =============================================================================

class TestWALEntryCreation:
    """Every incoming message MUST produce a WAL entry."""

    @pytest.mark.asyncio
    async def test_wal_entry_created_for_message(self) -> None:
        """WAL create_entry is called with correct payload structure."""
        patches, mock_wal = _wal_and_queue_patches()

        # Also mock Supabase for memory retrieval and conflict detection
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"] as mock_cls,
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
                session_id=TEST_SESSION_ID,
            )

        # Verify WAL was called exactly once
        mock_wal.create_entry.assert_called_once()

        # Verify payload shape
        payload = mock_wal.create_entry.call_args[0][0]
        assert payload["user_id"] == TEST_USER_ID
        assert payload["message"] == TEST_MESSAGE
        assert payload["source"] == "fast_path"
        assert "timestamp" in payload
        assert payload["session_id"] == TEST_SESSION_ID

    @pytest.mark.asyncio
    async def test_wal_entry_id_in_result(self) -> None:
        """Result must contain the WAL entry ID."""
        patches, mock_wal = _wal_and_queue_patches()
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        assert result.wal_entry_id == TEST_WAL_ENTRY_ID

    @pytest.mark.asyncio
    async def test_wal_write_failure_raises(self) -> None:
        """If WAL write fails, the pipeline must raise (critical path)."""
        mock_wal_instance = AsyncMock()
        mock_wal_instance.create_entry = AsyncMock(
            side_effect=Exception("Supabase connection error")
        )

        with patch(
            "backend.services.wal.WALService",
            return_value=mock_wal_instance,
        ):
            with pytest.raises(Exception, match="Supabase connection error"):
                await process_fast_path(
                    user_id=TEST_USER_ID,
                    message=TEST_MESSAGE,
                )


# =============================================================================
# 2. Entity Extraction Tests
# =============================================================================

class TestEntityExtraction:
    """Stub entity extraction must return structured entities."""

    @pytest.mark.asyncio
    async def test_extracts_proper_nouns(self) -> None:
        """Proper nouns in mid-sentence positions are extracted."""
        entities = await extract_entities_stub(
            "I had lunch with Alice and Bob yesterday"
        )
        names = [e.name for e in entities]
        assert "Alice" in names
        assert "Bob" in names

    @pytest.mark.asyncio
    async def test_extracts_dates(self) -> None:
        """Date patterns are extracted with type=date."""
        entities = await extract_entities_stub(
            "The meeting is on January 15, 2026"
        )
        date_entities = [e for e in entities if e.type == "date"]
        assert len(date_entities) >= 1

    @pytest.mark.asyncio
    async def test_extracts_time_patterns(self) -> None:
        """Time patterns like '3 PM' are extracted."""
        entities = await extract_entities_stub(
            "Call me at 3 PM or 9:00 AM"
        )
        time_entities = [e for e in entities if e.type == "date"]
        assert len(time_entities) >= 1

    @pytest.mark.asyncio
    async def test_entity_has_valid_structure(self) -> None:
        """Each extracted entity has name, type, and confidence."""
        entities = await extract_entities_stub("Visit Alice in Portland")
        for entity in entities:
            assert entity.name
            assert entity.type in (
                "person", "place", "org", "date", "project", "event", "unknown"
            )
            assert 0.0 <= entity.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_empty_message_returns_empty(self) -> None:
        """Empty message produces no entities."""
        entities = await extract_entities_stub("")
        assert entities == []


# =============================================================================
# 3. Embedding Generation Tests
# =============================================================================

class TestEmbeddingGeneration:
    """Stub embedding must return deterministic 1536-dim vectors."""

    @pytest.mark.asyncio
    async def test_embedding_has_correct_dimensions(self) -> None:
        """Embedding vector must be 1536 dimensions."""
        emb = await generate_embedding_stub("test message")
        assert len(emb) == 1536

    @pytest.mark.asyncio
    async def test_embedding_is_deterministic(self) -> None:
        """Same message produces same embedding."""
        emb1 = await generate_embedding_stub("deterministic test")
        emb2 = await generate_embedding_stub("deterministic test")
        assert emb1 == emb2

    @pytest.mark.asyncio
    async def test_different_messages_produce_different_embeddings(self) -> None:
        """Different messages produce different embeddings."""
        emb1 = await generate_embedding_stub("message one")
        emb2 = await generate_embedding_stub("message two")
        assert emb1 != emb2


# =============================================================================
# 4. Parallel Execution Tests
# =============================================================================

class TestParallelExecution:
    """Entity extraction and embedding must run in parallel via asyncio.gather."""

    @pytest.mark.asyncio
    async def test_extraction_and_embedding_run_concurrently(self) -> None:
        """
        Verify both stubs are called and their results appear in the
        final result, confirming parallel execution path is exercised.
        """
        patches, mock_wal = _wal_and_queue_patches()
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
            patch.object(
                fast_path_mod,
                "extract_entities_stub",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_extract,
            patch.object(
                fast_path_mod,
                "generate_embedding_stub",
                new_callable=AsyncMock,
                return_value=[0.1] * 1536,
            ) as mock_embed,
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        # Both stubs were called
        mock_extract.assert_called_once_with(TEST_MESSAGE)
        mock_embed.assert_called_once_with(TEST_MESSAGE)

        # Embedding generated flag set
        assert result.embedding_generated is True


# =============================================================================
# 5. Conflict Detection Tests
# =============================================================================

class TestConflictDetection:
    """Conflict detection compares extracted vs existing entities (read-only)."""

    @pytest.mark.asyncio
    async def test_type_mismatch_detected(self) -> None:
        """
        If an extracted entity has a different type than the existing
        entity, a type_mismatch conflict is flagged.
        """
        extracted = [
            ExtractedEntity(name="Alice", type="org", confidence=0.8),
        ]

        # Mock Supabase response: Alice exists as type=person
        mock_table = _mock_supabase_table([
            {"id": str(uuid4()), "name": "Alice", "type": "person",
             "attributes": {}, "status": "active"},
        ])
        mock_client = MagicMock()
        mock_client.table.return_value = mock_table

        with patch(
            "backend.services.wal.get_supabase_client",
            return_value=mock_client,
        ):
            conflicts = await detect_conflicts(extracted, TEST_USER_ID)

        assert len(conflicts) >= 1
        type_conflicts = [c for c in conflicts if c.conflict_type == "type_mismatch"]
        assert len(type_conflicts) == 1
        assert type_conflicts[0].entity_name == "Alice"

    @pytest.mark.asyncio
    async def test_attribute_mismatch_detected(self) -> None:
        """
        If an existing entity has attributes, an attribute_mismatch
        conflict is flagged for the Slow Path to resolve.
        """
        extracted = [
            ExtractedEntity(name="Bob", type="person", confidence=0.9),
        ]

        # Mock: Bob exists with attributes
        mock_table = _mock_supabase_table([
            {"id": str(uuid4()), "name": "Bob", "type": "person",
             "attributes": {"role": "manager"}, "status": "active"},
        ])
        mock_client = MagicMock()
        mock_client.table.return_value = mock_table

        with patch(
            "backend.services.wal.get_supabase_client",
            return_value=mock_client,
        ):
            conflicts = await detect_conflicts(extracted, TEST_USER_ID)

        attr_conflicts = [c for c in conflicts if c.conflict_type == "attribute_mismatch"]
        assert len(attr_conflicts) == 1
        assert attr_conflicts[0].existing["attributes"]["role"] == "manager"

    @pytest.mark.asyncio
    async def test_no_conflicts_when_no_existing_entities(self) -> None:
        """No conflicts when there are no matching existing entities."""
        extracted = [
            ExtractedEntity(name="NewPerson", type="person", confidence=0.9),
        ]

        mock_table = _mock_supabase_table([])
        mock_client = MagicMock()
        mock_client.table.return_value = mock_table

        with patch(
            "backend.services.wal.get_supabase_client",
            return_value=mock_client,
        ):
            conflicts = await detect_conflicts(extracted, TEST_USER_ID)

        assert conflicts == []

    @pytest.mark.asyncio
    async def test_empty_extracted_returns_no_conflicts(self) -> None:
        """Empty extraction list returns empty conflicts (no DB call)."""
        conflicts = await detect_conflicts([], TEST_USER_ID)
        assert conflicts == []


# =============================================================================
# 6. No-Mutation Guarantee Tests
# =============================================================================

class TestNoMutationGuarantee:
    """
    The Fast Path must NOT perform any INSERT or UPDATE on entity
    or memory tables. Only the WAL table is written to.
    """

    @pytest.mark.asyncio
    async def test_no_entity_inserts_or_updates(self) -> None:
        """
        Verify that no insert/update/upsert calls are made to the
        entities or memories tables during the full pipeline.
        """
        patches, mock_wal = _wal_and_queue_patches()

        # Track mutation calls per table
        mutation_calls: Dict[str, List[str]] = {}

        def tracking_table(name: str) -> MagicMock:
            mock_t = _mock_supabase_table()
            # Wrap mutation methods to record calls
            for method_name in ("insert", "update", "upsert", "delete"):
                original = getattr(mock_t, method_name)

                def make_tracker(tbl: str, meth: str) -> MagicMock:
                    def tracker(*args: Any, **kwargs: Any) -> MagicMock:
                        mutation_calls.setdefault(tbl, []).append(meth)
                        return mock_t
                    return MagicMock(side_effect=tracker)

                setattr(mock_t, method_name, make_tracker(name, method_name))
            return mock_t

        mock_client = MagicMock()
        mock_client.table = MagicMock(side_effect=tracking_table)

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        # No mutations should have occurred on entities or memories
        for table_name in ("entities", "memories"):
            assert table_name not in mutation_calls, (
                f"Unexpected mutation on '{table_name}': {mutation_calls.get(table_name)}"
            )

        assert result.wal_entry_id == TEST_WAL_ENTRY_ID


# =============================================================================
# 7. Queue Enqueue Tests
# =============================================================================

class TestQueueEnqueue:
    """WAL entry must be enqueued for Slow Path after creation."""

    @pytest.mark.asyncio
    async def test_enqueue_called_with_wal_entry_id(self) -> None:
        """enqueue_wal_for_processing is called with the WAL entry ID."""
        patches, mock_wal = _wal_and_queue_patches(queue_job_id="job-enq")
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"] as mock_enqueue,
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        mock_enqueue.assert_called_once_with(
            wal_entry_id=TEST_WAL_ENTRY_ID,
            priority="default",
        )
        assert result.queue_job_id == "job-enq"

    @pytest.mark.asyncio
    async def test_enqueue_failure_does_not_crash_pipeline(self) -> None:
        """Queue enqueue failure is handled gracefully (non-critical)."""
        patches, mock_wal = _wal_and_queue_patches(
            queue_side_effect=Exception("Redis down"),
            queue_job_id=None,
        )
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            # Should NOT raise
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        # Pipeline completed; job_id is None due to failure
        assert result.queue_job_id is None
        assert result.wal_entry_id == TEST_WAL_ENTRY_ID


# =============================================================================
# 8. FastPathResult Structure and Timing Tests
# =============================================================================

class TestFastPathResult:
    """FastPathResult must contain valid structure and timing data."""

    @pytest.mark.asyncio
    async def test_result_contains_timing_data(self) -> None:
        """Result timings dict has all expected keys."""
        patches, _ = _wal_and_queue_patches()
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        expected_keys = {
            "wal_write_ms",
            "entity_extraction_ms",
            "embedding_ms",
            "memory_retrieval_ms",
            "conflict_detection_ms",
            "queue_enqueue_ms",
            "total_ms",
        }
        assert expected_keys.issubset(set(result.timings.keys()))

    @pytest.mark.asyncio
    async def test_timing_values_are_non_negative(self) -> None:
        """All timing values must be >= 0."""
        patches, _ = _wal_and_queue_patches()
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        for key, value in result.timings.items():
            assert value >= 0.0, f"Timing {key} is negative: {value}"

    @pytest.mark.asyncio
    async def test_total_ms_is_positive(self) -> None:
        """Total ms must be a positive number (execution took real time)."""
        patches, _ = _wal_and_queue_patches()
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
            )

        assert result.timings["total_ms"] > 0.0

    @pytest.mark.asyncio
    async def test_result_user_id_and_session(self) -> None:
        """Result reflects the user_id and session_id that were passed in."""
        patches, _ = _wal_and_queue_patches()
        mock_client = MagicMock()
        mock_client.table = MagicMock(return_value=_mock_supabase_table())

        with (
            patches["wal_cls"],
            patches["enqueue"],
            patch(
                "backend.services.wal.get_supabase_client",
                return_value=mock_client,
            ),
        ):
            result = await process_fast_path(
                user_id=TEST_USER_ID,
                message=TEST_MESSAGE,
                session_id=TEST_SESSION_ID,
            )

        assert result.user_id == TEST_USER_ID
        assert result.session_id == TEST_SESSION_ID


# =============================================================================
# 9. Timing Instrumentation Tests
# =============================================================================

class TestTimingInstrumentation:
    """Tests for FastPathTimings and TimingBlock."""

    def test_timing_block_records_elapsed(self) -> None:
        """TimingBlock records elapsed_ms > 0 after exiting."""
        timer = TimingBlock("test")
        with timer:
            time.sleep(0.01)  # 10ms

        assert timer.elapsed_ms > 0.0
        assert timer.label == "test"

    def test_timing_block_context_manager_function(self) -> None:
        """timing_block() context manager works correctly."""
        with timing_block("func_test") as t:
            time.sleep(0.01)

        assert t.elapsed_ms > 0.0

    def test_fast_path_timings_model_defaults(self) -> None:
        """FastPathTimings has all fields defaulting to 0.0."""
        timings = FastPathTimings()
        assert timings.wal_write_ms == 0.0
        assert timings.entity_extraction_ms == 0.0
        assert timings.embedding_ms == 0.0
        assert timings.memory_retrieval_ms == 0.0
        assert timings.conflict_detection_ms == 0.0
        assert timings.queue_enqueue_ms == 0.0
        assert timings.total_ms == 0.0

    def test_fast_path_timings_model_dump(self) -> None:
        """FastPathTimings serialises to a dict with all keys."""
        timings = FastPathTimings(
            wal_write_ms=10.5,
            entity_extraction_ms=5.2,
            embedding_ms=3.1,
            memory_retrieval_ms=8.0,
            conflict_detection_ms=2.0,
            queue_enqueue_ms=1.0,
            total_ms=29.8,
        )
        data = timings.model_dump()
        assert data["wal_write_ms"] == 10.5
        assert data["total_ms"] == 29.8

    def test_fast_path_timings_log_summary(self) -> None:
        """log_summary does not raise and logs at INFO level."""
        timings = FastPathTimings(total_ms=150.0)
        # Should not raise
        timings.log_summary(user_id="test-user", session_id="test-session")

    def test_fast_path_timings_warns_on_slow(self) -> None:
        """log_summary warns when total_ms > 200."""
        timings = FastPathTimings(total_ms=350.0)

        with patch("backend.services.fast_path_timing.logger") as mock_logger:
            timings.log_summary(user_id="slow-user")
            mock_logger.warning.assert_called_once()


# =============================================================================
# 10. Pydantic Model Validation Tests
# =============================================================================

class TestPydanticModels:
    """Validate Pydantic model constraints."""

    def test_extracted_entity_confidence_bounds(self) -> None:
        """Confidence must be between 0.0 and 1.0."""
        entity = ExtractedEntity(name="Test", type="person", confidence=0.5)
        assert entity.confidence == 0.5

        with pytest.raises(Exception):
            ExtractedEntity(name="Test", type="person", confidence=1.5)

        with pytest.raises(Exception):
            ExtractedEntity(name="Test", type="person", confidence=-0.1)

    def test_conflict_flag_structure(self) -> None:
        """ConflictFlag accepts all expected fields."""
        conflict = ConflictFlag(
            entity_name="Alice",
            conflict_type="type_mismatch",
            existing={"type": "person"},
            new={"type": "org"},
        )
        assert conflict.entity_name == "Alice"
        assert conflict.conflict_type == "type_mismatch"

    def test_fast_path_result_defaults(self) -> None:
        """FastPathResult defaults are sensible."""
        result = FastPathResult(
            wal_entry_id="test-id",
            user_id="user-id",
        )
        assert result.extracted_entities == []
        assert result.conflicts == []
        assert result.retrieved_memories == []
        assert result.embedding_generated is False
        assert result.queue_job_id is None
        assert result.timings == {}
        assert result.session_id is None
