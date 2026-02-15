"""
Tests for Gap Detection Service
================================

Unit tests for the autonomous skill gap detection service.
Tests all functions with full mocking of Supabase client.

Run with: pytest tests/test_gap_detection.py -v
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.gap_detection import (
    detect_gaps,
    dismiss_gap,
    get_open_gaps,
    get_failure_summary,
    group_failures_by_tool,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for gap detection."""
    with patch("backend.services.gap_detection._get_supabase_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_audit_failures():
    """Mock audit logging get_recent_failures."""
    with patch("backend.services.gap_detection.get_failure_summary", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def sample_failures() -> List[Dict[str, Any]]:
    """Sample failure records for testing."""
    return [
        {
            "tool_name": "search_emails",
            "error_type": "timeout",
            "error_message": "Request timed out after 30s",
            "user_id": "user-123",
            "created_at": "2026-02-10T10:00:00Z",
        },
        {
            "tool_name": "search_emails",
            "error_type": "timeout",
            "error_message": "Connection timeout",
            "user_id": "user-123",
            "created_at": "2026-02-11T10:00:00Z",
        },
        {
            "tool_name": "search_emails",
            "error_type": "api_error",
            "error_message": "API returned 500",
            "user_id": "user-123",
            "created_at": "2026-02-12T10:00:00Z",
        },
        {
            "tool_name": "create_calendar_event",
            "error_type": "auth_error",
            "error_message": "OAuth token expired",
            "user_id": "user-456",
            "created_at": "2026-02-13T10:00:00Z",
        },
    ]


# =============================================================================
# Test: group_failures_by_tool()
# =============================================================================

class TestGroupFailuresByTool:
    """Test the group_failures_by_tool pure function."""

    def test_empty_list_returns_empty_dict(self):
        """Empty list input returns empty dict."""
        result = group_failures_by_tool([])
        assert result == {}

    def test_single_failure_creates_correct_grouping(self):
        """Single failure record creates correct grouping with count=1."""
        failures = [
            {
                "tool_name": "test_tool",
                "error_type": "timeout",
                "error_message": "Test error",
                "user_id": "user-123",
                "created_at": "2026-02-10T10:00:00Z",
            }
        ]
        result = group_failures_by_tool(failures)

        assert "test_tool" in result
        group = result["test_tool"]
        assert group["tool_name"] == "test_tool"
        assert group["count"] == 1
        assert group["error_types"]["timeout"] == 1
        assert "user-123" in group["user_ids"]
        assert len(group["error_messages"]) == 1
        assert group["first_seen"] == "2026-02-10T10:00:00Z"
        assert group["last_seen"] == "2026-02-10T10:00:00Z"

    def test_multiple_failures_same_tool_aggregates(self, sample_failures):
        """Multiple failures for same tool: counter aggregation, user_id set, error_messages list."""
        result = group_failures_by_tool(sample_failures[:3])  # All search_emails

        assert "search_emails" in result
        group = result["search_emails"]
        assert group["count"] == 3
        assert group["error_types"]["timeout"] == 2
        assert group["error_types"]["api_error"] == 1
        assert "user-123" in group["user_ids"]
        assert len(group["error_messages"]) == 3

    def test_multiple_tools_create_separate_groups(self, sample_failures):
        """Multiple different tools create separate groups."""
        result = group_failures_by_tool(sample_failures)

        assert "search_emails" in result
        assert "create_calendar_event" in result
        assert result["search_emails"]["count"] == 3
        assert result["create_calendar_event"]["count"] == 1

    def test_time_bounds_tracking(self, sample_failures):
        """Time bounds tracking: first_seen and last_seen set correctly."""
        result = group_failures_by_tool(sample_failures[:3])

        group = result["search_emails"]
        assert group["first_seen"] == "2026-02-10T10:00:00Z"
        assert group["last_seen"] == "2026-02-12T10:00:00Z"

    def test_missing_fields_handled_gracefully(self):
        """Handles failures with missing optional fields."""
        failures = [
            {"tool_name": "test_tool"},  # Missing most fields
            {"tool_name": "test_tool", "error_type": "error1"},
        ]
        result = group_failures_by_tool(failures)

        assert "test_tool" in result
        assert result["test_tool"]["count"] == 2


# =============================================================================
# Test: detect_gaps()
# =============================================================================

class TestDetectGaps:
    """Test the detect_gaps async function."""

    @pytest.mark.asyncio
    async def test_no_failures_returns_empty_list(self, mock_supabase, mock_audit_failures):
        """No failures found returns empty list."""
        mock_audit_failures.return_value = []

        result = await detect_gaps()

        assert result == []
        mock_audit_failures.assert_called_once()

    @pytest.mark.asyncio
    async def test_failures_below_threshold_returns_empty(self, mock_supabase, mock_audit_failures):
        """Failures below min_failures threshold returns empty list."""
        mock_audit_failures.return_value = [
            {"tool_name": "test_tool", "user_id": "user-123", "created_at": "2026-02-10T10:00:00Z"},
            {"tool_name": "test_tool", "user_id": "user-123", "created_at": "2026-02-11T10:00:00Z"},
        ]

        result = await detect_gaps(min_failures=3)

        assert result == []

    @pytest.mark.asyncio
    async def test_failures_at_threshold_creates_gap(self, mock_supabase, mock_audit_failures):
        """Failures at threshold creates gap records via _upsert_gap."""
        mock_audit_failures.return_value = [
            {
                "tool_name": "test_tool",
                "error_type": "timeout",
                "error_message": "Error 1",
                "user_id": "user-123",
                "created_at": "2026-02-10T10:00:00Z",
            },
            {
                "tool_name": "test_tool",
                "error_type": "timeout",
                "error_message": "Error 2",
                "user_id": "user-123",
                "created_at": "2026-02-11T10:00:00Z",
            },
            {
                "tool_name": "test_tool",
                "error_type": "timeout",
                "error_message": "Error 3",
                "user_id": "user-123",
                "created_at": "2026-02-12T10:00:00Z",
            },
        ]

        # Mock _upsert_gap to return a gap (no existing gap case)
        mock_existing = MagicMock()
        mock_existing.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value = mock_existing

        mock_insert = MagicMock()
        mock_insert.data = [{"id": "gap-123", "tool_name": "test_tool"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_insert

        result = await detect_gaps(min_failures=3)

        assert len(result) == 1
        assert result[0]["id"] == "gap-123"

    @pytest.mark.asyncio
    async def test_user_id_filter_works(self, mock_supabase, mock_audit_failures):
        """user_id filter correctly filters results."""
        mock_audit_failures.return_value = [
            {"tool_name": "tool1", "user_id": "user-123", "error_type": "error1", "created_at": "2026-02-10T10:00:00Z"},
            {"tool_name": "tool1", "user_id": "user-123", "error_type": "error1", "created_at": "2026-02-11T10:00:00Z"},
            {"tool_name": "tool1", "user_id": "user-123", "error_type": "error1", "created_at": "2026-02-12T10:00:00Z"},
            {"tool_name": "tool1", "user_id": "user-456", "error_type": "error1", "created_at": "2026-02-13T10:00:00Z"},
        ]

        # Mock no existing gap
        mock_existing = MagicMock()
        mock_existing.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value = mock_existing

        mock_insert = MagicMock()
        mock_insert.data = [{"id": "gap-123", "tool_name": "tool1", "user_id": "user-123"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_insert

        result = await detect_gaps(user_id="user-123", min_failures=3)

        assert len(result) == 1
        assert result[0]["user_id"] == "user-123"

    @pytest.mark.asyncio
    async def test_existing_gap_updates_not_duplicates(self, mock_supabase, mock_audit_failures):
        """Existing open gap for same tool+user updates (not duplicates)."""
        mock_audit_failures.return_value = [
            {"tool_name": "tool1", "user_id": "user-123", "error_type": "error1", "created_at": "2026-02-10T10:00:00Z"},
            {"tool_name": "tool1", "user_id": "user-123", "error_type": "error1", "created_at": "2026-02-11T10:00:00Z"},
            {"tool_name": "tool1", "user_id": "user-123", "error_type": "error1", "created_at": "2026-02-12T10:00:00Z"},
        ]

        # Mock existing gap found
        mock_existing = MagicMock()
        mock_existing.data = [{"id": "gap-existing", "tool_name": "tool1", "user_id": "user-123"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value = mock_existing

        # Mock update
        mock_update = MagicMock()
        mock_update.data = [{"id": "gap-existing", "tool_name": "tool1", "occurrence_count": 3}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        result = await detect_gaps(min_failures=3)

        assert len(result) == 1
        assert result[0]["id"] == "gap-existing"

    @pytest.mark.asyncio
    async def test_no_supabase_returns_empty(self):
        """When Supabase not configured, returns empty list."""
        with patch("backend.services.gap_detection._get_supabase_client", return_value=None):
            result = await detect_gaps()
            assert result == []


# =============================================================================
# Test: dismiss_gap()
# =============================================================================

class TestDismissGap:
    """Test the dismiss_gap async function."""

    @pytest.mark.asyncio
    async def test_success_updates_status(self, mock_supabase):
        """Success updates status to 'dismissed'."""
        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        result = await dismiss_gap("gap-123")

        assert result["status"] == "dismissed"
        assert result["gap_id"] == "gap-123"
        mock_supabase.table.assert_called_with("skill_gaps")

    @pytest.mark.asyncio
    async def test_no_supabase_raises_error(self):
        """Supabase not configured raises RuntimeError."""
        with patch("backend.services.gap_detection._get_supabase_client", return_value=None):
            with pytest.raises(RuntimeError, match="Supabase not configured"):
                await dismiss_gap("gap-123")


# =============================================================================
# Test: get_open_gaps()
# =============================================================================

class TestGetOpenGaps:
    """Test the get_open_gaps async function."""

    @pytest.mark.asyncio
    async def test_returns_matching_gaps_ordered(self, mock_supabase):
        """Returns matching gaps ordered by occurrence_count desc."""
        mock_result = MagicMock()
        mock_result.data = [
            {"id": "gap-1", "tool_name": "tool1", "occurrence_count": 10},
            {"id": "gap-2", "tool_name": "tool2", "occurrence_count": 5},
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.order.return_value.execute.return_value = mock_result

        result = await get_open_gaps("user-123")

        assert len(result) == 2
        assert result[0]["occurrence_count"] == 10
        assert result[1]["occurrence_count"] == 5

    @pytest.mark.asyncio
    async def test_no_gaps_returns_empty_list(self, mock_supabase):
        """No gaps returns empty list."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.order.return_value.execute.return_value = mock_result

        result = await get_open_gaps("user-123")

        assert result == []

    @pytest.mark.asyncio
    async def test_no_supabase_returns_empty(self):
        """When Supabase not configured, returns empty list."""
        with patch("backend.services.gap_detection._get_supabase_client", return_value=None):
            result = await get_open_gaps("user-123")
            assert result == []


# =============================================================================
# Test: get_failure_summary()
# =============================================================================

class TestGetFailureSummary:
    """Test the get_failure_summary async function."""

    @pytest.mark.asyncio
    async def test_delegates_to_audit_logging(self):
        """Delegates to audit_logging.get_recent_failures correctly."""
        with patch("backend.services.audit_logging.get_recent_failures", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {"tool_name": "tool1", "error_type": "timeout"},
                {"tool_name": "tool2", "error_type": "api_error"},
            ]

            result = await get_failure_summary(hours=168, limit=500)

            assert len(result) == 2
            mock_get.assert_called_once_with(hours=168, limit=500)

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_failures(self):
        """Returns empty list when no failures found."""
        with patch("backend.services.audit_logging.get_recent_failures", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []

            result = await get_failure_summary()

            assert result == []


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running gap detection service tests...")
    pytest.main([__file__, "-v"])
