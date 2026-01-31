"""
Write-Ahead Log (WAL) Service Tests - TDD RED Phase
=====================================================

This test module defines the contract for the WALService before implementation.
Following TDD methodology, these tests are written FIRST and should FAIL until
the WALService is implemented.

Test Cases:
1. test_wal_entry_creation - Verify raw interaction can be saved with pending status
2. test_wal_entry_retrieval_by_status - Verify batch retrieval of pending entries
3. test_wal_entry_idempotency - Ensure duplicate prevention for Twilio retries

Technical Constraints:
- Database: Supabase (PostgreSQL)
- Performance: Write operation < 100ms (Fast Path budget)
- Schema: wal_logs table with id, created_at, raw_payload, status, retry_count

Owner: @backend-architect-sabine
PRD Reference: PRD_Sabine_2.0_Complete.md - Section 4.3 (Dual-Stream Ingestion)
"""

import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)


# =============================================================================
# Test Configuration
# =============================================================================

# Test user and payload data
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_MESSAGE = "Schedule a meeting with John tomorrow at 3pm"
TEST_SOURCE = "twilio_sms"


def create_test_payload(
    user_id: str = TEST_USER_ID,
    message: str = TEST_MESSAGE,
    source: str = TEST_SOURCE,
    timestamp: datetime = None
) -> Dict[str, Any]:
    """Create a standard test payload for WAL entries."""
    return {
        "user_id": user_id,
        "message": message,
        "source": source,
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "metadata": {
            "channel": "sms",
            "phone_number": "+15551234567"
        }
    }


def generate_idempotency_key(user_id: str, message: str, timestamp: datetime) -> str:
    """
    Generate expected idempotency key matching the SQL function logic.

    Formula: MD5(user_id + '::' + message + '::' + timestamp_truncated_to_second)
    """
    timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    content = f"{user_id}::{message}::{timestamp_str}"
    return hashlib.md5(content.encode()).hexdigest()


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase_client():
    """
    Create a mock Supabase client for unit testing.

    This fixture provides a mock that simulates Supabase responses
    without requiring a live database connection.
    """
    mock_client = MagicMock()

    # Mock the table().insert().execute() chain
    mock_table = MagicMock()
    mock_insert = MagicMock()
    mock_select = MagicMock()
    mock_execute = MagicMock()

    mock_client.table.return_value = mock_table
    mock_table.insert.return_value = mock_insert
    mock_table.select.return_value = mock_select
    mock_insert.execute.return_value = mock_execute
    mock_select.eq.return_value = mock_select
    mock_select.order.return_value = mock_select
    mock_select.limit.return_value = mock_select
    mock_select.execute.return_value = mock_execute

    return mock_client


@pytest.fixture
def sample_timestamp():
    """Provide a consistent timestamp for testing idempotency."""
    return datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# Test Case 1: WAL Entry Creation
# =============================================================================

class TestWALEntryCreation:
    """
    Test Suite: WAL Entry Creation

    Verifies that raw interactions can be saved to the wal_logs table
    with a pending status and valid timestamp.
    """

    @pytest.mark.asyncio
    async def test_wal_entry_creation_returns_valid_uuid(self, mock_supabase_client):
        """
        Test that creating a WAL entry returns a valid UUID.

        Expected behavior:
        - WALService.create_entry() accepts a raw payload
        - Returns a WALEntry object with a valid UUID id
        - Entry status is 'pending' by default
        """
        # Import the service (will fail until implemented)
        from backend.services.wal import WALService, WALEntry

        # Arrange
        payload = create_test_payload()
        service = WALService(client=mock_supabase_client)

        # Mock the response
        mock_response_data = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0,
            "idempotency_key": None
        }
        mock_supabase_client.table().insert().execute.return_value.data = [mock_response_data]

        # Act
        entry = await service.create_entry(payload)

        # Assert
        assert entry is not None
        assert isinstance(entry, WALEntry)
        assert isinstance(entry.id, UUID)
        assert entry.status == "pending"

    @pytest.mark.asyncio
    async def test_wal_entry_creation_stores_raw_payload(self, mock_supabase_client):
        """
        Test that the raw payload is stored correctly in JSONB format.

        Expected behavior:
        - The complete payload is stored in raw_payload column
        - Payload can be retrieved without data loss
        """
        from backend.services.wal import WALService, WALEntry

        # Arrange
        payload = create_test_payload()
        payload["metadata"]["custom_field"] = "test_value"
        service = WALService(client=mock_supabase_client)

        # Mock
        mock_response_data = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0
        }
        mock_supabase_client.table().insert().execute.return_value.data = [mock_response_data]

        # Act
        entry = await service.create_entry(payload)

        # Assert
        assert entry.raw_payload == payload
        assert entry.raw_payload["metadata"]["custom_field"] == "test_value"

    @pytest.mark.asyncio
    async def test_wal_entry_creation_sets_pending_status(self, mock_supabase_client):
        """
        Test that new entries default to 'pending' status.

        Expected behavior:
        - New entries have status = 'pending'
        - retry_count = 0
        """
        from backend.services.wal import WALService

        # Arrange
        payload = create_test_payload()
        service = WALService(client=mock_supabase_client)

        # Mock
        mock_response_data = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0
        }
        mock_supabase_client.table().insert().execute.return_value.data = [mock_response_data]

        # Act
        entry = await service.create_entry(payload)

        # Assert
        assert entry.status == "pending"
        assert entry.retry_count == 0

    @pytest.mark.asyncio
    async def test_wal_entry_creation_sets_timestamp(self, mock_supabase_client):
        """
        Test that created_at timestamp is set automatically.

        Expected behavior:
        - created_at is populated with current timestamp
        - Timestamp is in UTC
        """
        from backend.services.wal import WALService

        # Arrange
        payload = create_test_payload()
        service = WALService(client=mock_supabase_client)
        before_creation = datetime.now(timezone.utc)

        # Mock
        creation_time = datetime.now(timezone.utc)
        mock_response_data = {
            "id": str(uuid4()),
            "created_at": creation_time.isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0
        }
        mock_supabase_client.table().insert().execute.return_value.data = [mock_response_data]

        # Act
        entry = await service.create_entry(payload)

        # Assert
        assert entry.created_at is not None
        assert isinstance(entry.created_at, datetime)

    @pytest.mark.asyncio
    async def test_wal_entry_creation_performance_under_100ms(self, mock_supabase_client):
        """
        Test that WAL entry creation completes within 100ms budget.

        Expected behavior:
        - Write operation completes in < 100ms
        - This is a critical Fast Path constraint

        Note: This test uses mocks, so it tests the service logic overhead.
        Integration tests should verify actual database performance.
        """
        import time
        from backend.services.wal import WALService

        # Arrange
        payload = create_test_payload()
        service = WALService(client=mock_supabase_client)

        # Mock (instant response)
        mock_response_data = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0
        }
        mock_supabase_client.table().insert().execute.return_value.data = [mock_response_data]

        # Act
        start_time = time.perf_counter()
        entry = await service.create_entry(payload)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Assert - service logic should add minimal overhead
        assert elapsed_ms < 100, f"WAL creation took {elapsed_ms:.2f}ms, exceeds 100ms budget"


# =============================================================================
# Test Case 2: WAL Entry Retrieval by Status
# =============================================================================

class TestWALEntryRetrievalByStatus:
    """
    Test Suite: WAL Entry Retrieval by Status

    Verifies that the service can retrieve batches of pending entries
    for Slow Path processing.
    """

    @pytest.mark.asyncio
    async def test_retrieve_pending_entries_returns_list(self, mock_supabase_client):
        """
        Test that retrieving pending entries returns a list of WALEntry objects.

        Expected behavior:
        - get_pending_entries() returns List[WALEntry]
        - Entries are sorted by created_at ASC (oldest first)
        """
        from backend.services.wal import WALService, WALEntry

        # Arrange
        service = WALService(client=mock_supabase_client)

        # Mock multiple pending entries
        mock_entries = [
            {
                "id": str(uuid4()),
                "created_at": "2026-01-30T10:00:00+00:00",
                "raw_payload": create_test_payload(),
                "status": "pending",
                "retry_count": 0
            },
            {
                "id": str(uuid4()),
                "created_at": "2026-01-30T10:01:00+00:00",
                "raw_payload": create_test_payload(message="Second message"),
                "status": "pending",
                "retry_count": 0
            }
        ]
        mock_supabase_client.table().select().eq().order().limit().execute.return_value.data = mock_entries

        # Act
        entries = await service.get_pending_entries(limit=10)

        # Assert
        assert isinstance(entries, list)
        assert len(entries) == 2
        assert all(isinstance(e, WALEntry) for e in entries)

    @pytest.mark.asyncio
    async def test_retrieve_pending_entries_respects_limit(self, mock_supabase_client):
        """
        Test that retrieval respects the batch size limit.

        Expected behavior:
        - If limit=5, returns at most 5 entries
        - Default limit is 100 (configurable)
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)
        requested_limit = 5

        # Mock exactly `limit` entries
        mock_entries = [
            {
                "id": str(uuid4()),
                "created_at": f"2026-01-30T10:{i:02d}:00+00:00",
                "raw_payload": create_test_payload(message=f"Message {i}"),
                "status": "pending",
                "retry_count": 0
            }
            for i in range(requested_limit)
        ]
        mock_supabase_client.table().select().eq().order().limit().execute.return_value.data = mock_entries

        # Act
        entries = await service.get_pending_entries(limit=requested_limit)

        # Assert
        assert len(entries) <= requested_limit
        # Verify limit was passed to the query
        mock_supabase_client.table().select().eq().order().limit.assert_called_with(requested_limit)

    @pytest.mark.asyncio
    async def test_retrieve_pending_entries_ordered_by_created_at(self, mock_supabase_client):
        """
        Test that entries are returned in FIFO order (oldest first).

        Expected behavior:
        - Entries sorted by created_at ASC
        - Oldest entries processed first
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)

        # Mock entries with clear timestamp ordering
        mock_entries = [
            {
                "id": str(uuid4()),
                "created_at": "2026-01-30T10:00:00+00:00",  # Oldest
                "raw_payload": create_test_payload(message="First"),
                "status": "pending",
                "retry_count": 0
            },
            {
                "id": str(uuid4()),
                "created_at": "2026-01-30T10:05:00+00:00",  # Newest
                "raw_payload": create_test_payload(message="Second"),
                "status": "pending",
                "retry_count": 0
            }
        ]
        mock_supabase_client.table().select().eq().order().limit().execute.return_value.data = mock_entries

        # Act
        entries = await service.get_pending_entries(limit=10)

        # Assert - verify order() was called with created_at ASC
        mock_supabase_client.table().select().eq().order.assert_called()

    @pytest.mark.asyncio
    async def test_retrieve_pending_entries_filters_by_status(self, mock_supabase_client):
        """
        Test that only 'pending' status entries are retrieved.

        Expected behavior:
        - Only entries with status='pending' returned
        - completed, failed, processing entries excluded
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)

        # Mock - only pending entries returned
        mock_entries = [
            {
                "id": str(uuid4()),
                "created_at": "2026-01-30T10:00:00+00:00",
                "raw_payload": create_test_payload(),
                "status": "pending",
                "retry_count": 0
            }
        ]
        mock_supabase_client.table().select().eq().order().limit().execute.return_value.data = mock_entries

        # Act
        entries = await service.get_pending_entries(limit=10)

        # Assert - verify eq() was called with status filter
        mock_supabase_client.table().select().eq.assert_called_with("status", "pending")

    @pytest.mark.asyncio
    async def test_retrieve_pending_entries_returns_empty_when_none(self, mock_supabase_client):
        """
        Test that empty list returned when no pending entries exist.

        Expected behavior:
        - Returns empty list, not None
        - No exceptions raised
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)

        # Mock empty result
        mock_supabase_client.table().select().eq().order().limit().execute.return_value.data = []

        # Act
        entries = await service.get_pending_entries(limit=10)

        # Assert
        assert entries == []
        assert isinstance(entries, list)


# =============================================================================
# Test Case 3: WAL Entry Idempotency
# =============================================================================

class TestWALEntryIdempotency:
    """
    Test Suite: WAL Entry Idempotency

    Ensures that duplicate entries from Twilio retries are prevented.
    The idempotency key is based on: user_id + message + timestamp (truncated to second)
    """

    @pytest.mark.asyncio
    async def test_idempotency_key_generated_on_creation(
        self, mock_supabase_client, sample_timestamp
    ):
        """
        Test that idempotency key is generated when creating an entry.

        Expected behavior:
        - create_entry() generates idempotency_key from payload
        - Key is stored with the entry
        """
        from backend.services.wal import WALService

        # Arrange
        payload = create_test_payload(timestamp=sample_timestamp)
        service = WALService(client=mock_supabase_client)
        expected_key = generate_idempotency_key(
            TEST_USER_ID, TEST_MESSAGE, sample_timestamp
        )

        # Mock
        mock_response_data = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0,
            "idempotency_key": expected_key
        }
        mock_supabase_client.table().insert().execute.return_value.data = [mock_response_data]

        # Act
        entry = await service.create_entry(payload)

        # Assert
        assert entry.idempotency_key == expected_key

    @pytest.mark.asyncio
    async def test_duplicate_entry_returns_existing(
        self, mock_supabase_client, sample_timestamp
    ):
        """
        Test that creating a duplicate entry returns the existing one.

        Expected behavior:
        - If idempotency_key already exists, return existing entry
        - No new entry created
        - No exception raised (graceful handling)
        """
        from backend.services.wal import WALService

        # Arrange
        payload = create_test_payload(timestamp=sample_timestamp)
        service = WALService(client=mock_supabase_client)
        existing_id = uuid4()
        expected_key = generate_idempotency_key(
            TEST_USER_ID, TEST_MESSAGE, sample_timestamp
        )

        # Mock - simulate unique constraint violation, then return existing
        existing_entry = {
            "id": str(existing_id),
            "created_at": sample_timestamp.isoformat(),
            "raw_payload": payload,
            "status": "pending",
            "retry_count": 0,
            "idempotency_key": expected_key
        }

        # First call raises unique constraint error
        from postgrest.exceptions import APIError
        mock_error = APIError({
            "message": "duplicate key value violates unique constraint",
            "code": "23505"  # PostgreSQL unique violation
        })
        mock_supabase_client.table().insert().execute.side_effect = [
            mock_error,  # First attempt fails
        ]
        # Fallback query returns existing
        mock_supabase_client.table().select().eq().execute.return_value.data = [existing_entry]

        # Act
        entry = await service.create_entry(payload)

        # Assert - should return existing entry, not raise exception
        assert entry.id == existing_id
        assert entry.idempotency_key == expected_key

    @pytest.mark.asyncio
    async def test_idempotency_key_based_on_user_message_timestamp(
        self, mock_supabase_client, sample_timestamp
    ):
        """
        Test that idempotency key is correctly computed from user_id + message + timestamp.

        Expected behavior:
        - Key = MD5(user_id + '::' + message + '::' + timestamp_to_second)
        - Same inputs produce same key
        - Different inputs produce different keys
        """
        from backend.services.wal import WALService

        # Arrange
        payload = create_test_payload(timestamp=sample_timestamp)
        service = WALService(client=mock_supabase_client)

        # Calculate expected key manually
        expected_key = generate_idempotency_key(
            TEST_USER_ID, TEST_MESSAGE, sample_timestamp
        )

        # Act
        computed_key = service.generate_idempotency_key(payload)

        # Assert
        assert computed_key == expected_key

    @pytest.mark.asyncio
    async def test_different_messages_produce_different_keys(
        self, mock_supabase_client, sample_timestamp
    ):
        """
        Test that different messages produce different idempotency keys.

        Expected behavior:
        - "Hello" at T1 != "World" at T1
        - Keys are unique per message content
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)
        payload1 = create_test_payload(message="Hello", timestamp=sample_timestamp)
        payload2 = create_test_payload(message="World", timestamp=sample_timestamp)

        # Act
        key1 = service.generate_idempotency_key(payload1)
        key2 = service.generate_idempotency_key(payload2)

        # Assert
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_different_timestamps_produce_different_keys(
        self, mock_supabase_client
    ):
        """
        Test that different timestamps produce different idempotency keys.

        Expected behavior:
        - Same message at T1 != Same message at T2
        - Timestamp precision is to the second
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)
        timestamp1 = datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc)
        timestamp2 = datetime(2026, 1, 30, 12, 0, 1, tzinfo=timezone.utc)  # 1 second later

        payload1 = create_test_payload(timestamp=timestamp1)
        payload2 = create_test_payload(timestamp=timestamp2)

        # Act
        key1 = service.generate_idempotency_key(payload1)
        key2 = service.generate_idempotency_key(payload2)

        # Assert
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_same_second_produces_same_key(self, mock_supabase_client):
        """
        Test that timestamps within the same second produce the same key.

        Expected behavior:
        - Timestamp is truncated to the second
        - 12:00:00.100 == 12:00:00.999 for idempotency purposes
        - This handles Twilio retries that happen within 1 second
        """
        from backend.services.wal import WALService

        # Arrange
        service = WALService(client=mock_supabase_client)
        timestamp1 = datetime(2026, 1, 30, 12, 0, 0, 100000, tzinfo=timezone.utc)  # .1s
        timestamp2 = datetime(2026, 1, 30, 12, 0, 0, 999000, tzinfo=timezone.utc)  # .999s

        payload1 = create_test_payload(timestamp=timestamp1)
        payload2 = create_test_payload(timestamp=timestamp2)

        # Act
        key1 = service.generate_idempotency_key(payload1)
        key2 = service.generate_idempotency_key(payload2)

        # Assert - same second = same key
        assert key1 == key2


# =============================================================================
# Test Case 4: WAL Entry Status Updates (Bonus - needed for Slow Path)
# =============================================================================

class TestWALEntryStatusUpdates:
    """
    Test Suite: WAL Entry Status Updates

    Verifies status transition logic for the Slow Path worker.
    While not in the original requirements, these are essential for
    the complete WAL lifecycle.
    """

    @pytest.mark.asyncio
    async def test_mark_entry_as_processing(self, mock_supabase_client):
        """
        Test that an entry can be marked as 'processing'.

        Expected behavior:
        - Status changes from 'pending' to 'processing'
        - worker_id is recorded
        """
        from backend.services.wal import WALService

        # Arrange
        entry_id = uuid4()
        worker_id = "worker-001"
        service = WALService(client=mock_supabase_client)

        # Mock
        mock_supabase_client.table().update().eq().execute.return_value.data = [{
            "id": str(entry_id),
            "status": "processing",
            "worker_id": worker_id
        }]

        # Act
        result = await service.mark_processing(entry_id, worker_id)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_entry_as_completed(self, mock_supabase_client):
        """
        Test that an entry can be marked as 'completed'.

        Expected behavior:
        - Status changes from 'processing' to 'completed'
        - processed_at timestamp is set
        """
        from backend.services.wal import WALService

        # Arrange
        entry_id = uuid4()
        service = WALService(client=mock_supabase_client)

        # Mock
        mock_supabase_client.table().update().eq().execute.return_value.data = [{
            "id": str(entry_id),
            "status": "completed",
            "processed_at": datetime.now(timezone.utc).isoformat()
        }]

        # Act
        result = await service.mark_completed(entry_id)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_entry_as_failed_increments_retry(self, mock_supabase_client):
        """
        Test that failing an entry increments retry_count.

        Expected behavior:
        - retry_count incremented
        - last_error recorded
        - If retry_count < max, status returns to 'pending'
        """
        from backend.services.wal import WALService

        # Arrange
        entry_id = uuid4()
        error_message = "Connection timeout"
        service = WALService(client=mock_supabase_client)

        # Mock the select query for current retry_count
        mock_select_response = MagicMock()
        mock_select_response.data = [{"retry_count": 0}]  # Current retry count is 0

        # Mock the update response
        mock_update_response = MagicMock()
        mock_update_response.data = [{
            "id": str(entry_id),
            "status": "pending",
            "retry_count": 1,
            "last_error": error_message
        }]

        # Set up the mock chain for both select and update
        mock_table = MagicMock()
        mock_supabase_client.table.return_value = mock_table

        # Select chain: table().select().eq().execute()
        mock_select = MagicMock()
        mock_select.eq.return_value.execute.return_value = mock_select_response
        mock_table.select.return_value = mock_select

        # Update chain: table().update().eq().execute()
        mock_update = MagicMock()
        mock_update.eq.return_value.execute.return_value = mock_update_response
        mock_table.update.return_value = mock_update

        # Act
        result = await service.mark_failed(entry_id, error_message)

        # Assert
        assert result is True


# =============================================================================
# Integration Test Marker (for future use with real database)
# =============================================================================

@pytest.mark.integration
class TestWALServiceIntegration:
    """
    Integration tests requiring a live Supabase connection.

    These tests are marked with @pytest.mark.integration and should
    be run separately with actual database credentials.

    Run with: pytest -m integration tests/test_wal_service.py
    """

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Integration test - requires live Supabase")
    async def test_full_wal_lifecycle(self):
        """
        Test the complete WAL entry lifecycle with real database.

        1. Create entry -> pending
        2. Mark processing
        3. Mark completed
        4. Verify entry in database
        """
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Integration test - requires live Supabase")
    async def test_idempotency_with_real_constraint(self):
        """
        Test idempotency with actual PostgreSQL unique constraint.

        1. Create entry with idempotency key
        2. Attempt duplicate
        3. Verify original returned, not new entry
        """
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Integration test - requires live Supabase")
    async def test_performance_benchmark(self):
        """
        Benchmark WAL write performance against 100ms budget.

        - Run 100 inserts
        - Measure P50, P95, P99 latency
        - Assert P95 < 100ms
        """
        pass


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
