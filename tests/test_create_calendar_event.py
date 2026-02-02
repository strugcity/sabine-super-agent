"""
Tests for Create Calendar Event Skill - Phase 4.1 Verification
==============================================================

BDD-style tests verifying the calendar event creation skill.
Run with: pytest tests/test_create_calendar_event.py -v

Tests cover:
1. Event creation with Google Calendar API
2. Reminder configuration (popup notifications)
3. All-day event handling
4. Hybrid SMS reminder creation
5. Error handling and validation
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytz

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.skills.create_calendar_event.handler import (
    execute,
    parse_datetime,
    format_time_for_display,
    format_date_for_display,
    create_google_calendar_event,
    create_sms_reminder_for_event,
    USER_TIMEZONE,
)


# =============================================================================
# Test Configuration
# =============================================================================

GOOGLE_CONFIGURED = bool(
    os.getenv("GOOGLE_CLIENT_ID") and os.getenv("USER_REFRESH_TOKEN")
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def future_time():
    """Create a future datetime in user's timezone."""
    return datetime.now(USER_TIMEZONE) + timedelta(hours=2)


@pytest.fixture
def mock_access_token():
    """Mock access token for Google API."""
    return "mock_access_token_12345"


@pytest.fixture
def mock_event_response():
    """Mock response from Google Calendar API event creation."""
    return {
        "id": "event123abc",
        "htmlLink": "https://calendar.google.com/event?eid=event123abc",
        "summary": "Test Event",
        "start": {"dateTime": "2026-02-03T14:00:00-06:00"},
        "end": {"dateTime": "2026-02-03T15:00:00-06:00"},
    }


# =============================================================================
# Unit Tests: Datetime Parsing
# =============================================================================

class TestDatetimeParsing:
    """Test datetime parsing functionality."""

    def test_parse_iso_format(self):
        """Parse standard ISO datetime."""
        result = parse_datetime("2026-02-03T14:00:00")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 0

    def test_parse_iso_with_timezone(self):
        """Parse ISO datetime with timezone offset."""
        result = parse_datetime("2026-02-03T14:00:00-06:00")
        assert result is not None
        # Should convert to user timezone
        assert result.tzinfo is not None

    def test_parse_iso_with_utc_z(self):
        """Parse ISO datetime with Z suffix (UTC)."""
        result = parse_datetime("2026-02-03T20:00:00Z")
        assert result is not None
        # 20:00 UTC = 14:00 Central (during standard time)
        assert result.tzinfo is not None

    def test_parse_date_only(self):
        """Parse date-only string."""
        result = parse_datetime("2026-02-03")
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 3
        assert result.hour == 0  # Midnight

    def test_parse_invalid_returns_none(self):
        """Invalid datetime string returns None."""
        result = parse_datetime("not a date")
        assert result is None

    def test_parse_empty_returns_none(self):
        """Empty string returns None."""
        result = parse_datetime("")
        assert result is None


# =============================================================================
# Unit Tests: Display Formatting
# =============================================================================

class TestDisplayFormatting:
    """Test display formatting functions."""

    def test_format_time_for_display(self, future_time):
        """Format datetime for user display."""
        result = format_time_for_display(future_time)
        assert "at" in result
        assert "AM" in result or "PM" in result

    def test_format_date_for_display(self):
        """Format date string for user display."""
        result = format_date_for_display("2026-02-03")
        assert "February" in result
        assert "3" in result


# =============================================================================
# Unit Tests: Google Calendar Event Creation
# =============================================================================

class TestGoogleCalendarEventCreation:
    """Test Google Calendar API event creation."""

    @pytest.mark.asyncio
    async def test_create_timed_event(self, future_time, mock_event_response):
        """Create a standard timed event."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = mock_event_response

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await create_google_calendar_event(
                access_token="test_token",
                title="Test Meeting",
                start_time=future_time,
                end_time=future_time + timedelta(hours=1),
                reminder_minutes=15,
            )

            assert result["success"] is True
            assert result["event_id"] == "event123abc"
            assert "htmlLink" in result or "html_link" in result

    @pytest.mark.asyncio
    async def test_create_all_day_event(self, future_time, mock_event_response):
        """Create an all-day event."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = mock_event_response

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await create_google_calendar_event(
                access_token="test_token",
                title="Birthday Party",
                start_time=future_time,
                end_time=future_time + timedelta(days=1),
                all_day=True,
                reminder_minutes=0,
            )

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_event_with_location(self, future_time, mock_event_response):
        """Create event with location."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = mock_event_response

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await create_google_calendar_event(
                access_token="test_token",
                title="Dentist Appointment",
                start_time=future_time,
                end_time=future_time + timedelta(hours=1),
                location="123 Main St, Chicago, IL",
                reminder_minutes=30,
            )

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_event_api_error(self, future_time):
        """Handle API error gracefully."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = "Forbidden: insufficient permissions"

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await create_google_calendar_event(
                access_token="test_token",
                title="Test Event",
                start_time=future_time,
                end_time=future_time + timedelta(hours=1),
            )

            assert result["success"] is False
            assert "error" in result


# =============================================================================
# Unit Tests: SMS Reminder Creation
# =============================================================================

class TestSMSReminderCreation:
    """Test hybrid SMS reminder creation."""

    @pytest.mark.asyncio
    async def test_create_sms_reminder_success(self, future_time):
        """Create SMS reminder for calendar event."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"reminder": {"id": str(uuid4())}}

        # Patch at the source module where it's imported from
        with patch(
            "backend.services.reminder_service.get_reminder_service"
        ) as mock_service:
            mock_service.return_value.create_reminder = AsyncMock(
                return_value=mock_result
            )

            # Mock scheduler - patch at source
            with patch(
                "lib.agent.reminder_scheduler.get_reminder_scheduler"
            ) as mock_scheduler:
                mock_scheduler.return_value.is_running.return_value = True
                mock_scheduler.return_value.add_reminder_job = AsyncMock()

                result = await create_sms_reminder_for_event(
                    event_title="Test Meeting",
                    event_time=future_time,
                    reminder_minutes=60,
                )

                assert result["success"] is True
                assert "reminder_id" in result
                assert "scheduled_for" in result

    @pytest.mark.asyncio
    async def test_skip_past_sms_reminder(self):
        """Skip SMS reminder if time would be in the past."""
        past_time = datetime.now(USER_TIMEZONE) - timedelta(hours=1)

        result = await create_sms_reminder_for_event(
            event_title="Past Event",
            event_time=past_time,
            reminder_minutes=60,
        )

        assert result["success"] is False
        assert "past" in result["error"].lower()


# =============================================================================
# Unit Tests: Handler Validation
# =============================================================================

class TestHandlerValidation:
    """Test parameter validation in execute handler."""

    @pytest.mark.asyncio
    async def test_missing_title_error(self):
        """Error when title is missing."""
        result = await execute({"start_time": "2026-02-03T14:00:00"})
        assert result["status"] == "error"
        assert "title" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_start_time_error(self):
        """Error when start_time is missing."""
        result = await execute({"title": "Test Event"})
        assert result["status"] == "error"
        assert "start time" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_start_time_error(self):
        """Error when start_time is unparseable."""
        result = await execute({
            "title": "Test Event",
            "start_time": "not a valid time"
        })
        assert result["status"] == "error"
        assert "couldn't understand" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_past_time_error(self):
        """Error when start_time is in the past."""
        past_time = (datetime.now(USER_TIMEZONE) - timedelta(hours=1)).isoformat()

        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            result = await execute({
                "title": "Test Event",
                "start_time": past_time
            })

            assert result["status"] == "error"
            assert "past" in result["message"].lower()


# =============================================================================
# Unit Tests: Handler Success Cases
# =============================================================================

class TestHandlerSuccess:
    """Test successful event creation scenarios."""

    @pytest.mark.asyncio
    async def test_create_basic_event(self, future_time, mock_event_response):
        """Create a basic calendar event."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "event123",
                    "html_link": "https://calendar.google.com/event?eid=123",
                }
            ):
                result = await execute({
                    "title": "Dentist Appointment",
                    "start_time": future_time.isoformat(),
                })

                assert result["status"] == "success"
                assert "Dentist Appointment" in result["message"]
                assert result["event_id"] == "event123"

    @pytest.mark.asyncio
    async def test_create_event_with_custom_reminder(self, future_time):
        """Create event with custom reminder time."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "event456",
                    "html_link": "https://calendar.google.com/event?eid=456",
                }
            ):
                result = await execute({
                    "title": "Important Meeting",
                    "start_time": future_time.isoformat(),
                    "reminder_minutes": 60,
                })

                assert result["status"] == "success"
                assert "1 hour" in result["message"]

    @pytest.mark.asyncio
    async def test_create_all_day_event(self):
        """Create an all-day event."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "event789",
                    "html_link": "https://calendar.google.com/event?eid=789",
                }
            ):
                result = await execute({
                    "title": "Jack's Birthday",
                    "start_time": "2026-02-15",
                    "all_day": True,
                })

                assert result["status"] == "success"
                assert "Jack's Birthday" in result["message"]
                assert "all day" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_event_with_location(self, future_time):
        """Create event with location."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "event_loc",
                    "html_link": "https://calendar.google.com/event?eid=loc",
                }
            ):
                result = await execute({
                    "title": "Dentist",
                    "start_time": future_time.isoformat(),
                    "location": "123 Main St",
                })

                assert result["status"] == "success"
                assert result["event_details"]["location"] == "123 Main St"


# =============================================================================
# Unit Tests: Hybrid SMS+Calendar Reminder
# =============================================================================

class TestHybridReminder:
    """Test hybrid calendar + SMS reminder creation."""

    @pytest.mark.asyncio
    async def test_create_event_with_sms_reminder(self, future_time):
        """Create event with both calendar and SMS reminder."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "event_hybrid",
                    "html_link": "https://calendar.google.com/event?eid=hybrid",
                }
            ):
                with patch(
                    "lib.skills.create_calendar_event.handler.create_sms_reminder_for_event",
                    return_value={
                        "success": True,
                        "reminder_id": str(uuid4()),
                        "scheduled_for": (future_time - timedelta(hours=1)).isoformat(),
                    }
                ):
                    result = await execute({
                        "title": "Flight to NYC",
                        "start_time": future_time.isoformat(),
                        "also_sms_reminder": True,
                        "sms_reminder_minutes": 120,
                    })

                    assert result["status"] == "success"
                    assert "text you" in result["message"].lower()
                    assert result["sms_reminder"] is not None
                    assert result["sms_reminder"]["success"] is True

    @pytest.mark.asyncio
    async def test_event_created_even_if_sms_fails(self, future_time):
        """Calendar event created even if SMS reminder fails."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "event_partial",
                    "html_link": "https://calendar.google.com/event?eid=partial",
                }
            ):
                with patch(
                    "lib.skills.create_calendar_event.handler.create_sms_reminder_for_event",
                    return_value={
                        "success": False,
                        "error": "SMS service unavailable",
                    }
                ):
                    result = await execute({
                        "title": "Important Event",
                        "start_time": future_time.isoformat(),
                        "also_sms_reminder": True,
                    })

                    # Event should still be created
                    assert result["status"] == "success"
                    assert result["event_id"] == "event_partial"
                    # But should note SMS failed
                    assert "couldn't set up the SMS" in result["message"]


# =============================================================================
# Unit Tests: Authentication
# =============================================================================

class TestAuthentication:
    """Test Google OAuth authentication."""

    @pytest.mark.asyncio
    async def test_missing_credentials_error(self, future_time):
        """Error when Google credentials are missing."""
        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value=None
        ):
            result = await execute({
                "title": "Test Event",
                "start_time": future_time.isoformat(),
            })

            assert result["status"] == "error"
            assert "credentials" in result["message"].lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running create_calendar_event tests...")
    pytest.main([__file__, "-v"])
