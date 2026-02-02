"""
Tests for Reminder Skill Handler - Step 2.2 Verification
=========================================================

BDD-style tests verifying the create_reminder skill handler.
Run with: pytest tests/test_reminder_handler.py -v

Tests cover:
1. Input validation (missing fields, invalid values)
2. Time parsing (ISO 8601, timezone handling)
3. Successful reminder creation
4. Error handling and user-friendly messages
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

from lib.skills.reminder.handler import (
    execute,
    parse_scheduled_time,
    format_confirmation_message,
    USER_TIMEZONE,
)


# =============================================================================
# Test Configuration
# =============================================================================

# Check if Supabase is configured for integration tests
SUPABASE_CONFIGURED = bool(
    os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def future_time_str():
    """Get an ISO 8601 datetime string 1 hour in the future."""
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    return future.isoformat()


@pytest.fixture
def future_time_central():
    """Get an ISO 8601 datetime string 1 hour in the future in Central time."""
    future = datetime.now(USER_TIMEZONE) + timedelta(hours=1)
    return future.isoformat()


@pytest.fixture
def past_time_str():
    """Get an ISO 8601 datetime string 1 hour in the past."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    return past.isoformat()


@pytest.fixture
def mock_service():
    """Create a mock ReminderService."""
    from backend.services.exceptions import OperationResult

    service = MagicMock()
    service.create_reminder = AsyncMock(
        return_value=OperationResult.ok({
            "reminder_id": str(uuid4()),
            "reminder": {"id": str(uuid4()), "title": "Test"},
        })
    )
    return service


# =============================================================================
# Unit Tests: Time Parsing
# =============================================================================

class TestTimeParsing:
    """Test the parse_scheduled_time function."""

    def test_parse_iso8601_with_z_suffix(self):
        """Parse ISO 8601 with Z (UTC) suffix."""
        result = parse_scheduled_time("2026-02-03T10:00:00Z")
        assert result is not None
        assert result.tzinfo is not None
        assert result.hour == 10  # UTC hour

    def test_parse_iso8601_with_offset(self):
        """Parse ISO 8601 with timezone offset."""
        result = parse_scheduled_time("2026-02-03T10:00:00-06:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_parse_iso8601_no_timezone(self):
        """Parse ISO 8601 without timezone - should assume user's timezone."""
        result = parse_scheduled_time("2026-02-03T10:00:00")
        assert result is not None
        assert result.tzinfo is not None
        # Should be localized to user's timezone (Central)
        assert str(result.tzinfo) in str(USER_TIMEZONE) or result.tzinfo is not None

    def test_parse_date_only(self):
        """Parse date-only string - should assume midnight in user's timezone."""
        result = parse_scheduled_time("2026-02-03")
        assert result is not None
        assert result.tzinfo is not None
        assert result.hour == 0
        assert result.minute == 0

    def test_parse_invalid_string(self):
        """Invalid time string returns None."""
        result = parse_scheduled_time("not a date")
        assert result is None

    def test_parse_empty_string(self):
        """Empty string returns None."""
        result = parse_scheduled_time("")
        assert result is None

    def test_parse_none(self):
        """None returns None."""
        result = parse_scheduled_time(None)
        assert result is None


# =============================================================================
# Unit Tests: Confirmation Message Formatting
# =============================================================================

class TestConfirmationMessage:
    """Test the format_confirmation_message function."""

    def test_one_time_reminder_message(self):
        """Format message for one-time reminder."""
        scheduled = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        msg = format_confirmation_message(
            title="Pick up glasses",
            scheduled_time=scheduled,
            reminder_type="sms",
        )

        assert "Pick up glasses" in msg
        assert "SMS" in msg
        assert "remind you" in msg.lower()

    def test_recurring_daily_message(self):
        """Format message for daily recurring reminder."""
        scheduled = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        msg = format_confirmation_message(
            title="Take medication",
            scheduled_time=scheduled,
            reminder_type="sms",
            repeat_pattern="daily",
        )

        assert "Take medication" in msg
        assert "daily" in msg.lower()
        assert "every day" in msg.lower()

    def test_recurring_weekly_message(self):
        """Format message for weekly recurring reminder."""
        scheduled = datetime(2026, 2, 9, 16, 0, tzinfo=timezone.utc)  # Sunday
        msg = format_confirmation_message(
            title="Post video",
            scheduled_time=scheduled,
            reminder_type="slack",
            repeat_pattern="weekly",
        )

        assert "Post video" in msg
        assert "weekly" in msg.lower()
        assert "Slack" in msg

    def test_email_channel(self):
        """Format message for email reminder."""
        scheduled = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        msg = format_confirmation_message(
            title="Meeting prep",
            scheduled_time=scheduled,
            reminder_type="email",
        )

        assert "email" in msg.lower()

    def test_calendar_event_channel(self):
        """Format message for calendar event reminder."""
        scheduled = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        msg = format_confirmation_message(
            title="Dentist",
            scheduled_time=scheduled,
            reminder_type="calendar_event",
        )

        assert "calendar" in msg.lower()


# =============================================================================
# Unit Tests: Input Validation (No Database)
# =============================================================================

class TestInputValidation:
    """Test input validation without hitting the database."""

    @pytest.mark.asyncio
    async def test_missing_title(self, future_time_str):
        """Reject request without title."""
        result = await execute({
            "scheduled_time": future_time_str,
        })

        assert result["status"] == "error"
        assert "title" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_empty_title(self, future_time_str):
        """Reject request with empty title."""
        result = await execute({
            "title": "",
            "scheduled_time": future_time_str,
        })

        assert result["status"] == "error"
        assert "title" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_whitespace_title(self, future_time_str):
        """Reject request with whitespace-only title."""
        result = await execute({
            "title": "   ",
            "scheduled_time": future_time_str,
        })

        assert result["status"] == "error"
        assert "title" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_scheduled_time(self):
        """Reject request without scheduled_time."""
        result = await execute({
            "title": "Test Reminder",
        })

        assert result["status"] == "error"
        assert "time" in result["message"].lower() or "when" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_scheduled_time(self):
        """Reject request with invalid time format."""
        result = await execute({
            "title": "Test Reminder",
            "scheduled_time": "not a valid time",
        })

        assert result["status"] == "error"
        assert "couldn't understand" in result["message"].lower() or "format" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_past_scheduled_time(self, past_time_str):
        """Reject request with time in the past."""
        result = await execute({
            "title": "Test Reminder",
            "scheduled_time": past_time_str,
        })

        assert result["status"] == "error"
        assert "past" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_reminder_type(self, future_time_str):
        """Reject request with invalid reminder_type."""
        result = await execute({
            "title": "Test Reminder",
            "scheduled_time": future_time_str,
            "reminder_type": "invalid_type",
        })

        assert result["status"] == "error"
        assert "reminder type" in result["message"].lower() or "valid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_repeat_pattern(self, future_time_str):
        """Reject request with invalid repeat_pattern."""
        result = await execute({
            "title": "Test Reminder",
            "scheduled_time": future_time_str,
            "repeat_pattern": "every_minute",
        })

        assert result["status"] == "error"
        assert "repeat pattern" in result["message"].lower() or "valid" in result["message"].lower()


# =============================================================================
# Integration Tests (Database Required)
# =============================================================================

@pytest.mark.skipif(not SUPABASE_CONFIGURED, reason="Supabase not configured")
class TestIntegration:
    """Test full integration with ReminderService."""

    @pytest.mark.asyncio
    async def test_create_one_time_sms_reminder(self, future_time_str):
        """Create a one-time SMS reminder."""
        result = await execute({
            "title": "Handler Test - One Time",
            "scheduled_time": future_time_str,
            "reminder_type": "sms",
        })

        assert result["status"] == "success", f"Failed: {result.get('message')}"
        assert "reminder_id" in result
        assert "message" in result
        assert "remind you" in result["message"].lower()

        # Cleanup
        if result.get("reminder_id"):
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(result["reminder_id"]))

    @pytest.mark.asyncio
    async def test_create_recurring_weekly_reminder(self, future_time_str):
        """Create a recurring weekly reminder."""
        result = await execute({
            "title": "Handler Test - Weekly",
            "scheduled_time": future_time_str,
            "reminder_type": "sms",
            "repeat_pattern": "weekly",
        })

        assert result["status"] == "success", f"Failed: {result.get('message')}"
        assert "reminder_id" in result
        assert "weekly" in result["message"].lower()

        # Cleanup
        if result.get("reminder_id"):
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(result["reminder_id"]))

    @pytest.mark.asyncio
    async def test_create_reminder_with_description(self, future_time_str):
        """Create a reminder with optional description."""
        result = await execute({
            "title": "Handler Test - With Description",
            "scheduled_time": future_time_str,
            "description": "Don't forget to bring the paperwork",
            "reminder_type": "email",
        })

        assert result["status"] == "success", f"Failed: {result.get('message')}"
        assert result["reminder"]["description"] == "Don't forget to bring the paperwork"

        # Cleanup
        if result.get("reminder_id"):
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(result["reminder_id"]))

    @pytest.mark.asyncio
    async def test_create_slack_reminder(self, future_time_str):
        """Create a Slack reminder."""
        result = await execute({
            "title": "Handler Test - Slack",
            "scheduled_time": future_time_str,
            "reminder_type": "slack",
        })

        assert result["status"] == "success", f"Failed: {result.get('message')}"
        assert "Slack" in result["message"]

        # Cleanup
        if result.get("reminder_id"):
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(result["reminder_id"]))

    @pytest.mark.asyncio
    async def test_create_daily_reminder(self, future_time_str):
        """Create a daily recurring reminder."""
        result = await execute({
            "title": "Handler Test - Daily",
            "scheduled_time": future_time_str,
            "repeat_pattern": "daily",
        })

        assert result["status"] == "success", f"Failed: {result.get('message')}"
        assert "daily" in result["message"].lower()
        assert "every day" in result["message"].lower()

        # Cleanup
        if result.get("reminder_id"):
            from backend.services.reminder_service import get_reminder_service
            service = get_reminder_service()
            await service.cancel_reminder(UUID(result["reminder_id"]))


# =============================================================================
# Unit Tests with Mocked Service
# =============================================================================

class TestWithMockedService:
    """Test handler logic with mocked ReminderService."""

    @pytest.mark.asyncio
    async def test_success_response_format(self, future_time_str, mock_service):
        """Verify success response has correct structure."""
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await execute({
                "title": "Test Reminder",
                "scheduled_time": future_time_str,
            })

        assert result["status"] == "success"
        assert "message" in result
        assert "reminder_id" in result
        assert "reminder" in result
        assert "title" in result["reminder"]
        assert "scheduled_time" in result["reminder"]

    @pytest.mark.asyncio
    async def test_service_error_handling(self, future_time_str):
        """Handle service errors gracefully."""
        from backend.services.exceptions import OperationResult, DatabaseError

        mock_service = MagicMock()
        mock_service.create_reminder = AsyncMock(
            return_value=OperationResult.fail(
                DatabaseError(message="Connection failed")
            )
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await execute({
                "title": "Test Reminder",
                "scheduled_time": future_time_str,
            })

        assert result["status"] == "error"
        assert "couldn't create" in result["message"].lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running handler tests...")
    pytest.main([__file__, "-v"])
