"""
Tests for List Reminders Skill Handler - Step 2.4 Verification
==============================================================

BDD-style tests verifying the list_reminders skill handler.
Run with: pytest tests/test_list_reminders_handler.py -v

Tests cover:
1. Formatting functions (time, type, pattern)
2. Empty list handling
3. Multiple reminders listing
4. Integration with ReminderService
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

from lib.skills.list_reminders.handler import (
    execute,
    format_reminder_time,
    format_reminder_type,
    format_repeat_pattern,
    format_reminder_list,
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
def sample_reminders():
    """Create multiple sample reminders."""
    base_time = datetime.now(timezone.utc)
    return [
        {
            "id": str(uuid4()),
            "title": "Pick up glasses",
            "reminder_type": "sms",
            "scheduled_time": (base_time + timedelta(hours=2)).isoformat(),
            "repeat_pattern": None,
            "is_active": True,
            "is_completed": False,
        },
        {
            "id": str(uuid4()),
            "title": "Team meeting",
            "reminder_type": "slack",
            "scheduled_time": (base_time + timedelta(days=1)).isoformat(),
            "repeat_pattern": "weekly",
            "is_active": True,
            "is_completed": False,
        },
        {
            "id": str(uuid4()),
            "title": "Pay rent",
            "reminder_type": "email",
            "scheduled_time": (base_time + timedelta(days=5)).isoformat(),
            "repeat_pattern": "monthly",
            "is_active": True,
            "is_completed": False,
        },
    ]


@pytest.fixture
def mock_service_with_reminders(sample_reminders):
    """Create a mock service that returns sample reminders."""
    from backend.services.exceptions import OperationResult

    service = MagicMock()
    service.list_active_reminders = AsyncMock(
        return_value=OperationResult.ok({
            "reminders": sample_reminders,
            "count": len(sample_reminders),
        })
    )
    return service


@pytest.fixture
def mock_service_empty():
    """Create a mock service that returns no reminders."""
    from backend.services.exceptions import OperationResult

    service = MagicMock()
    service.list_active_reminders = AsyncMock(
        return_value=OperationResult.ok({
            "reminders": [],
            "count": 0,
        })
    )
    return service


# =============================================================================
# Unit Tests: Format Functions
# =============================================================================

class TestFormatTime:
    """Test the format_reminder_time function."""

    def test_format_utc_time(self):
        """Format UTC time to user timezone."""
        # 4 PM UTC should be 10 AM Central (CST is UTC-6)
        result = format_reminder_time("2026-02-03T16:00:00Z")
        assert "10:00 AM" in result
        assert "February" in result
        assert "3" in result

    def test_format_time_with_offset(self):
        """Format time with timezone offset."""
        result = format_reminder_time("2026-02-03T10:00:00-06:00")
        assert "10:00 AM" in result
        assert "February" in result

    def test_format_includes_day_name(self):
        """Format should include day of week."""
        result = format_reminder_time("2026-02-03T16:00:00Z")
        assert "Tuesday" in result  # Feb 3, 2026 is a Tuesday

    def test_format_ordinal_suffix_st(self):
        """Test ordinal suffix for 1st, 21st, 31st."""
        result = format_reminder_time("2026-02-01T16:00:00Z")
        assert "1st" in result

    def test_format_ordinal_suffix_nd(self):
        """Test ordinal suffix for 2nd, 22nd."""
        result = format_reminder_time("2026-02-02T16:00:00Z")
        assert "2nd" in result

    def test_format_ordinal_suffix_rd(self):
        """Test ordinal suffix for 3rd, 23rd."""
        result = format_reminder_time("2026-02-03T16:00:00Z")
        assert "3rd" in result

    def test_format_ordinal_suffix_th(self):
        """Test ordinal suffix for 4th-20th, 24th-30th."""
        result = format_reminder_time("2026-02-15T16:00:00Z")
        assert "15th" in result

    def test_format_invalid_time_returns_original(self):
        """Invalid time string returns the original."""
        result = format_reminder_time("not a date")
        assert result == "not a date"


class TestFormatType:
    """Test the format_reminder_type function."""

    def test_format_sms(self):
        """SMS type formatted correctly."""
        assert format_reminder_type("sms") == "SMS"

    def test_format_email(self):
        """Email type formatted correctly."""
        assert format_reminder_type("email") == "Email"

    def test_format_slack(self):
        """Slack type formatted correctly."""
        assert format_reminder_type("slack") == "Slack"

    def test_format_calendar(self):
        """Calendar type formatted correctly."""
        assert format_reminder_type("calendar_event") == "Calendar"

    def test_format_unknown_type(self):
        """Unknown type is title-cased."""
        assert format_reminder_type("webhook") == "Webhook"


class TestFormatRepeatPattern:
    """Test the format_repeat_pattern function."""

    def test_format_none_pattern(self):
        """None pattern returns empty string."""
        assert format_repeat_pattern(None) == ""

    def test_format_daily(self):
        """Daily pattern formatted correctly."""
        assert format_repeat_pattern("daily") == "Repeats daily"

    def test_format_weekly(self):
        """Weekly pattern formatted correctly."""
        assert format_repeat_pattern("weekly") == "Repeats weekly"

    def test_format_monthly(self):
        """Monthly pattern formatted correctly."""
        assert format_repeat_pattern("monthly") == "Repeats monthly"

    def test_format_yearly(self):
        """Yearly pattern formatted correctly."""
        assert format_repeat_pattern("yearly") == "Repeats yearly"

    def test_format_unknown_pattern(self):
        """Unknown pattern uses generic format."""
        assert format_repeat_pattern("biweekly") == "Repeats biweekly"


# =============================================================================
# Unit Tests: Format Reminder List
# =============================================================================

class TestFormatReminderList:
    """Test the format_reminder_list function."""

    def test_empty_list_message(self):
        """Empty list returns friendly message."""
        result = format_reminder_list([])
        assert "don't have any active reminders" in result.lower()

    def test_single_reminder(self):
        """Single reminder shows singular form."""
        reminders = [{
            "id": "12345678-1234-1234-1234-123456789012",
            "title": "Test Reminder",
            "scheduled_time": "2026-02-03T16:00:00Z",
            "reminder_type": "sms",
            "repeat_pattern": None,
        }]
        result = format_reminder_list(reminders)
        assert "1 active reminder" in result
        assert "Test Reminder" in result
        assert "SMS" in result

    def test_multiple_reminders(self):
        """Multiple reminders shows plural form."""
        reminders = [
            {
                "id": "12345678-1234-1234-1234-123456789012",
                "title": "Reminder 1",
                "scheduled_time": "2026-02-03T16:00:00Z",
                "reminder_type": "sms",
                "repeat_pattern": None,
            },
            {
                "id": "87654321-4321-4321-4321-210987654321",
                "title": "Reminder 2",
                "scheduled_time": "2026-02-04T16:00:00Z",
                "reminder_type": "email",
                "repeat_pattern": "weekly",
            },
        ]
        result = format_reminder_list(reminders)
        assert "2 active reminders" in result
        assert "Reminder 1" in result
        assert "Reminder 2" in result
        assert "Repeats weekly" in result

    def test_includes_short_id(self):
        """Result includes short ID for reference."""
        reminders = [{
            "id": "12345678-1234-1234-1234-123456789012",
            "title": "Test",
            "scheduled_time": "2026-02-03T16:00:00Z",
            "reminder_type": "sms",
            "repeat_pattern": None,
        }]
        result = format_reminder_list(reminders)
        assert "12345678" in result  # First 8 chars of UUID


# =============================================================================
# Unit Tests: Handler Execution
# =============================================================================

class TestHandlerExecution:
    """Test the execute function with mocked service."""

    @pytest.mark.asyncio
    async def test_list_with_reminders(self, mock_service_with_reminders):
        """Handler returns formatted list when reminders exist."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_with_reminders
        ):
            result = await execute({})

        assert result["status"] == "success"
        assert "reminders" in result
        assert result["count"] == 3
        assert "Pick up glasses" in result["message"]
        assert "Team meeting" in result["message"]
        assert "Pay rent" in result["message"]

    @pytest.mark.asyncio
    async def test_list_empty(self, mock_service_empty):
        """Handler returns friendly message when no reminders."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_empty
        ):
            result = await execute({})

        assert result["status"] == "success"
        assert result["count"] == 0
        assert "don't have any active reminders" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_limit_parameter(self, mock_service_with_reminders):
        """Handler respects limit parameter."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_with_reminders
        ):
            result = await execute({"limit": 5})

        # Verify service was called with correct limit
        mock_service_with_reminders.list_active_reminders.assert_called_once()
        call_args = mock_service_with_reminders.list_active_reminders.call_args
        assert call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_limit_capped_at_100(self, mock_service_with_reminders):
        """Handler caps limit at 100."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_with_reminders
        ):
            result = await execute({"limit": 500})

        call_args = mock_service_with_reminders.list_active_reminders.call_args
        assert call_args.kwargs["limit"] == 100

    @pytest.mark.asyncio
    async def test_invalid_limit_defaults(self, mock_service_with_reminders):
        """Handler uses default for invalid limit."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service_with_reminders
        ):
            result = await execute({"limit": "invalid"})

        call_args = mock_service_with_reminders.list_active_reminders.call_args
        assert call_args.kwargs["limit"] == 20

    @pytest.mark.asyncio
    async def test_service_error_handling(self):
        """Handler returns error message on service failure."""
        from backend.services.exceptions import OperationResult, DatabaseError

        mock_service = MagicMock()
        mock_service.list_active_reminders = AsyncMock(
            return_value=OperationResult.fail(
                DatabaseError(message="Connection failed")
            )
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await execute({})

        assert result["status"] == "error"
        assert "couldn't retrieve" in result["message"].lower()


# =============================================================================
# Integration Tests (Database Required)
# =============================================================================

@pytest.mark.skipif(not SUPABASE_CONFIGURED, reason="Supabase not configured")
class TestIntegration:
    """Test full integration with ReminderService."""

    @pytest.mark.asyncio
    async def test_list_returns_success(self):
        """List reminders returns success status."""
        result = await execute({})
        assert result["status"] == "success"
        assert "message" in result
        assert "reminders" in result
        assert "count" in result

    @pytest.mark.asyncio
    async def test_list_with_seeded_reminder(self):
        """List shows reminders created via create_reminder."""
        from datetime import timedelta
        from lib.skills.reminder.handler import execute as create_reminder

        # Create a test reminder
        future_time = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        create_result = await create_reminder({
            "title": "List Test Reminder",
            "scheduled_time": future_time,
            "reminder_type": "sms",
        })

        assert create_result["status"] == "success"
        reminder_id = create_result.get("reminder_id")

        try:
            # List reminders
            list_result = await execute({})
            assert list_result["status"] == "success"
            assert list_result["count"] >= 1

            # Find our test reminder in the list
            found = any(
                r.get("title") == "List Test Reminder"
                for r in list_result.get("reminders", [])
            )
            assert found, "Created reminder should appear in list"

        finally:
            # Cleanup
            if reminder_id:
                from backend.services.reminder_service import get_reminder_service
                service = get_reminder_service()
                await service.cancel_reminder(UUID(reminder_id))


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running list_reminders handler tests...")
    pytest.main([__file__, "-v"])
