"""
Tests for Cancel Reminder Skill Handler - Step 2.5 Verification
===============================================================

BDD-style tests verifying the cancel_reminder skill handler.
Run with: pytest tests/test_cancel_reminder_handler.py -v

Tests cover:
1. Cancel by exact ID
2. Cancel by search term (single match)
3. Ambiguous matches (multiple results)
4. Cancel all matching (confirm_multiple)
5. Error handling (not found, invalid ID)
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytz

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.skills.cancel_reminder.handler import (
    execute,
    format_reminder_for_display,
    format_ambiguous_matches,
    USER_TIMEZONE,
)


# =============================================================================
# Test Configuration
# =============================================================================

SUPABASE_CONFIGURED = bool(
    os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_reminder():
    """Create a sample reminder dict."""
    scheduled = datetime.now(timezone.utc) + timedelta(hours=2)
    return {
        "id": str(uuid4()),
        "user_id": "75abac49-2b45-44ab-a57d-8ca6ecad2b8c",
        "title": "Pick up glasses",
        "description": "From the optometrist",
        "reminder_type": "sms",
        "scheduled_time": scheduled.isoformat(),
        "repeat_pattern": None,
        "is_active": True,
        "is_completed": False,
    }


@pytest.fixture
def multiple_meeting_reminders():
    """Create multiple reminders with 'meeting' in title."""
    base_time = datetime.now(timezone.utc)
    return [
        {
            "id": str(uuid4()),
            "title": "Team meeting",
            "scheduled_time": (base_time + timedelta(hours=2)).isoformat(),
            "reminder_type": "sms",
            "is_active": True,
        },
        {
            "id": str(uuid4()),
            "title": "Client meeting",
            "scheduled_time": (base_time + timedelta(days=1)).isoformat(),
            "reminder_type": "email",
            "is_active": True,
        },
    ]


@pytest.fixture
def mock_service_single_match(sample_reminder):
    """Mock service that returns a single matching reminder."""
    from backend.services.exceptions import OperationResult

    service = MagicMock()
    service.search_reminders_by_title = AsyncMock(
        return_value=OperationResult.ok({
            "reminders": [sample_reminder],
            "count": 1,
            "search_term": "glasses",
        })
    )
    service.get_reminder = AsyncMock(
        return_value=OperationResult.ok({"reminder": sample_reminder})
    )
    service.cancel_reminder = AsyncMock(
        return_value=OperationResult.ok({
            "reminder_id": sample_reminder["id"],
            "status": "cancelled",
        })
    )
    return service


@pytest.fixture
def mock_service_multiple_matches(multiple_meeting_reminders):
    """Mock service that returns multiple matching reminders."""
    from backend.services.exceptions import OperationResult

    service = MagicMock()
    service.search_reminders_by_title = AsyncMock(
        return_value=OperationResult.ok({
            "reminders": multiple_meeting_reminders,
            "count": 2,
            "search_term": "meeting",
        })
    )
    service.cancel_reminder = AsyncMock(
        return_value=OperationResult.ok({"status": "cancelled"})
    )
    return service


@pytest.fixture
def mock_service_no_matches():
    """Mock service that returns no matching reminders."""
    from backend.services.exceptions import OperationResult

    service = MagicMock()
    service.search_reminders_by_title = AsyncMock(
        return_value=OperationResult.ok({
            "reminders": [],
            "count": 0,
            "search_term": "dentist",
        })
    )
    return service


# =============================================================================
# Unit Tests: Format Functions
# =============================================================================

class TestFormatFunctions:
    """Test formatting helper functions."""

    def test_format_reminder_for_display(self):
        """Format reminder with valid time."""
        reminder = {
            "title": "Pick up glasses",
            "scheduled_time": "2026-02-03T16:00:00Z",  # 10 AM Central
        }
        result = format_reminder_for_display(reminder)
        assert "Pick up glasses" in result
        assert "10:00 AM" in result
        assert "Tuesday" in result

    def test_format_reminder_invalid_time(self):
        """Format reminder with invalid time falls back to title only."""
        reminder = {
            "title": "Test Reminder",
            "scheduled_time": "invalid",
        }
        result = format_reminder_for_display(reminder)
        assert "Test Reminder" in result

    def test_format_ambiguous_matches(self, multiple_meeting_reminders):
        """Format multiple matches for disambiguation."""
        result = format_ambiguous_matches(multiple_meeting_reminders)
        assert "2 reminders" in result
        assert "Team meeting" in result
        assert "Client meeting" in result
        assert "Which one" in result


# =============================================================================
# Unit Tests: Input Validation
# =============================================================================

class TestInputValidation:
    """Test input validation."""

    @pytest.mark.asyncio
    async def test_missing_both_id_and_search(self):
        """Error when neither reminder_id nor search_term provided."""
        result = await execute({})
        assert result["status"] == "error"
        assert "need either" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_reminder_id_format(self):
        """Error when reminder_id is not a valid UUID."""
        result = await execute({"reminder_id": "not-a-uuid"})
        assert result["status"] == "error"
        assert "valid reminder id" in result["message"].lower()


# =============================================================================
# Unit Tests: Cancel by ID
# =============================================================================

class TestCancelById:
    """Test cancellation by exact reminder ID."""

    @pytest.mark.asyncio
    async def test_cancel_by_id_success(self, sample_reminder, mock_service_single_match):
        """Successfully cancel reminder by ID."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_single_match
        ):
            result = await execute({"reminder_id": sample_reminder["id"]})

        assert result["status"] == "success"
        assert "cancelled" in result["message"].lower()
        assert "Pick up glasses" in result["message"]
        assert result["cancelled_count"] == 1

    @pytest.mark.asyncio
    async def test_cancel_by_id_not_found(self):
        """Error when reminder ID doesn't exist."""
        from backend.services.exceptions import OperationResult
        from backend.services.reminder_service import ReminderNotFoundError

        mock_service = MagicMock()
        mock_service.get_reminder = AsyncMock(
            return_value=OperationResult.fail(
                ReminderNotFoundError(reminder_id="12345678-1234-1234-1234-123456789012")
            )
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await execute({
                "reminder_id": "12345678-1234-1234-1234-123456789012"
            })

        assert result["status"] == "error"
        assert "couldn't find" in result["message"].lower()


# =============================================================================
# Unit Tests: Cancel by Search Term
# =============================================================================

class TestCancelBySearch:
    """Test cancellation by search term."""

    @pytest.mark.asyncio
    async def test_search_single_match_cancels(self, mock_service_single_match):
        """Single search match is cancelled automatically."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_single_match
        ):
            result = await execute({"search_term": "glasses"})

        assert result["status"] == "success"
        assert "cancelled" in result["message"].lower()
        assert "Pick up glasses" in result["message"]

    @pytest.mark.asyncio
    async def test_search_no_matches(self, mock_service_no_matches):
        """No matches returns helpful error."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_no_matches
        ):
            result = await execute({"search_term": "dentist"})

        assert result["status"] == "error"
        assert "couldn't find" in result["message"].lower()
        assert "dentist" in result["message"]

    @pytest.mark.asyncio
    async def test_search_multiple_matches_asks_clarification(
        self, mock_service_multiple_matches
    ):
        """Multiple matches asks for clarification."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_multiple_matches
        ):
            result = await execute({"search_term": "meeting"})

        assert result["status"] == "ambiguous"
        assert "2 reminders" in result["message"]
        assert "Team meeting" in result["message"]
        assert "Client meeting" in result["message"]
        assert result["match_count"] == 2
        assert len(result["matches"]) == 2

    @pytest.mark.asyncio
    async def test_search_multiple_with_confirm_cancels_all(
        self, mock_service_multiple_matches
    ):
        """Multiple matches with confirm_multiple cancels all."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_multiple_matches
        ):
            result = await execute({
                "search_term": "meeting",
                "confirm_multiple": True,
            })

        assert result["status"] == "success"
        assert result["cancelled_count"] == 2
        assert "Team meeting" in result["message"]
        assert "Client meeting" in result["message"]


# =============================================================================
# Unit Tests: Error Handling
# =============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_service_error_on_search(self):
        """Handle service error during search."""
        from backend.services.exceptions import OperationResult, DatabaseError

        mock_service = MagicMock()
        mock_service.search_reminders_by_title = AsyncMock(
            return_value=OperationResult.fail(
                DatabaseError(message="Connection failed")
            )
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await execute({"search_term": "test"})

        assert result["status"] == "error"
        assert "couldn't search" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_service_error_on_cancel(self, sample_reminder):
        """Handle service error during cancellation."""
        from backend.services.exceptions import OperationResult, DatabaseError

        mock_service = MagicMock()
        mock_service.get_reminder = AsyncMock(
            return_value=OperationResult.ok({"reminder": sample_reminder})
        )
        mock_service.cancel_reminder = AsyncMock(
            return_value=OperationResult.fail(
                DatabaseError(message="Update failed")
            )
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await execute({"reminder_id": sample_reminder["id"]})

        assert result["status"] == "error"
        assert "couldn't cancel" in result["message"].lower()


# =============================================================================
# Integration Tests (Database Required)
# =============================================================================

@pytest.mark.skipif(not SUPABASE_CONFIGURED, reason="Supabase not configured")
class TestIntegration:
    """Test full integration with ReminderService."""

    @pytest.mark.asyncio
    async def test_create_and_cancel_by_id(self):
        """Create a reminder and cancel it by ID."""
        from lib.skills.reminder.handler import execute as create_reminder

        # Create a test reminder
        future_time = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        create_result = await create_reminder({
            "title": "Cancel Test By ID",
            "scheduled_time": future_time,
            "reminder_type": "sms",
        })

        assert create_result["status"] == "success"
        reminder_id = create_result.get("reminder_id")

        try:
            # Cancel by ID
            cancel_result = await execute({"reminder_id": reminder_id})
            assert cancel_result["status"] == "success"
            assert "cancelled" in cancel_result["message"].lower()
            assert cancel_result["cancelled_count"] == 1

        finally:
            # Cleanup (already cancelled, but ensure)
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(reminder_id))

    @pytest.mark.asyncio
    async def test_create_and_cancel_by_search(self):
        """Create a reminder and cancel it by search term."""
        from lib.skills.reminder.handler import execute as create_reminder

        # Create a test reminder with unique title
        unique_title = f"Unique Search Cancel Test {uuid4().hex[:8]}"
        future_time = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        create_result = await create_reminder({
            "title": unique_title,
            "scheduled_time": future_time,
            "reminder_type": "sms",
        })

        assert create_result["status"] == "success"
        reminder_id = create_result.get("reminder_id")

        try:
            # Cancel by search term
            cancel_result = await execute({"search_term": unique_title[:20]})
            assert cancel_result["status"] == "success"
            assert "cancelled" in cancel_result["message"].lower()

        finally:
            # Cleanup
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(reminder_id))

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_by_search(self):
        """Search for non-existent reminder returns error."""
        result = await execute({"search_term": "xyznonexistent123"})
        assert result["status"] == "error"
        assert "couldn't find" in result["message"].lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running cancel_reminder handler tests...")
    pytest.main([__file__, "-v"])
