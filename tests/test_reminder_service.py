"""
Tests for ReminderService - Step 1.2 Verification
==================================================

This module tests the CRUD operations for the ReminderService.
Run with: pytest tests/test_reminder_service.py -v

Requirements:
- SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set
- The reminders table must exist (from Step 1.1 migration)
- A valid user_id must exist in the users table
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.reminder_service import (
    ReminderService,
    ReminderNotFoundError,
    ReminderValidationError,
    get_reminder_service,
)


# =============================================================================
# Test Configuration
# =============================================================================

# Use a real user ID from the database
# This user exists in the Supabase users table
TEST_USER_ID = UUID("75abac49-2b45-44ab-a57d-8ca6ecad2b8c")

# Check if Supabase is configured
SUPABASE_CONFIGURED = bool(
    os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def service():
    """Get a ReminderService instance."""
    return get_reminder_service()


@pytest.fixture
def future_time():
    """Get a datetime 1 hour in the future."""
    return datetime.now(timezone.utc) + timedelta(hours=1)


@pytest.fixture
def past_time():
    """Get a datetime 1 hour in the past."""
    return datetime.now(timezone.utc) - timedelta(hours=1)


# =============================================================================
# Unit Tests (No Database Required)
# =============================================================================

class TestValidation:
    """Test input validation without database."""

    @pytest.mark.asyncio
    async def test_create_reminder_empty_title_fails(self, service, future_time):
        """Reject empty title."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="",
            scheduled_time=future_time,
        )

        assert not result.success
        assert result.error is not None
        assert "title" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_whitespace_title_fails(self, service, future_time):
        """Reject whitespace-only title."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="   ",
            scheduled_time=future_time,
        )

        assert not result.success
        assert result.error is not None
        assert "title" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_past_time_fails(self, service, past_time):
        """Reject scheduled_time in the past."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Test Reminder",
            scheduled_time=past_time,
        )

        assert not result.success
        assert result.error is not None
        assert "future" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_naive_datetime_fails(self, service):
        """Reject timezone-naive datetime."""
        naive_time = datetime.now() + timedelta(hours=1)  # No timezone

        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Test Reminder",
            scheduled_time=naive_time,
        )

        assert not result.success
        assert result.error is not None
        assert "timezone" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_invalid_type_fails(self, service, future_time):
        """Reject invalid reminder_type."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Test Reminder",
            scheduled_time=future_time,
            reminder_type="invalid_type",
        )

        assert not result.success
        assert result.error is not None
        assert "reminder_type" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_invalid_repeat_pattern_fails(self, service, future_time):
        """Reject invalid repeat_pattern."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Test Reminder",
            scheduled_time=future_time,
            repeat_pattern="every_minute",
        )

        assert not result.success
        assert result.error is not None
        assert "repeat_pattern" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_no_channels_fails(self, service, future_time):
        """Reject notification_channels with all False."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Test Reminder",
            scheduled_time=future_time,
            notification_channels={"sms": False, "email": False},
        )

        assert not result.success
        assert result.error is not None
        assert "channel" in result.error.message.lower()


# =============================================================================
# Integration Tests (Database Required)
# =============================================================================

@pytest.mark.skipif(not SUPABASE_CONFIGURED, reason="Supabase not configured")
class TestCRUDOperations:
    """Test CRUD operations against real database."""

    @pytest.mark.asyncio
    async def test_create_reminder_success(self, service, future_time):
        """Create a valid reminder."""
        result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Test Reminder",
            scheduled_time=future_time,
            description="Test description",
            reminder_type="sms",
        )

        assert result.success, f"Failed: {result.error}"
        assert "reminder_id" in result.data
        assert "reminder" in result.data

        # Cleanup
        reminder_id = UUID(result.data["reminder_id"])
        await service.cancel_reminder(reminder_id)

    @pytest.mark.asyncio
    async def test_create_and_get_reminder(self, service, future_time):
        """Create a reminder and retrieve it by ID."""
        # Create
        create_result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Get Test Reminder",
            scheduled_time=future_time,
        )
        assert create_result.success
        reminder_id = UUID(create_result.data["reminder_id"])

        # Get
        get_result = await service.get_reminder(reminder_id)
        assert get_result.success
        assert get_result.data["reminder"]["id"] == str(reminder_id)
        assert get_result.data["reminder"]["title"] == "Get Test Reminder"

        # Cleanup
        await service.cancel_reminder(reminder_id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_reminder_fails(self, service):
        """Getting a non-existent reminder returns not found error."""
        fake_id = uuid4()
        result = await service.get_reminder(fake_id)

        assert not result.success
        assert result.error is not None
        assert isinstance(result.error, ReminderNotFoundError)

    @pytest.mark.asyncio
    async def test_list_active_reminders(self, service, future_time):
        """List active reminders for a user."""
        # Create two reminders
        r1 = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="List Test 1",
            scheduled_time=future_time,
        )
        r2 = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="List Test 2",
            scheduled_time=future_time + timedelta(hours=1),
        )

        assert r1.success and r2.success

        # List
        list_result = await service.list_active_reminders(TEST_USER_ID)
        assert list_result.success
        assert list_result.data["count"] >= 2

        # Verify sorted by scheduled_time
        reminders = list_result.data["reminders"]
        titles = [r["title"] for r in reminders if r["title"].startswith("List Test")]
        assert "List Test 1" in titles
        assert "List Test 2" in titles

        # Cleanup
        await service.cancel_reminder(UUID(r1.data["reminder_id"]))
        await service.cancel_reminder(UUID(r2.data["reminder_id"]))

    @pytest.mark.asyncio
    async def test_update_reminder(self, service, future_time):
        """Update a reminder's properties."""
        # Create
        create_result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Update Test",
            scheduled_time=future_time,
        )
        assert create_result.success
        reminder_id = UUID(create_result.data["reminder_id"])

        # Update
        new_time = future_time + timedelta(hours=2)
        update_result = await service.update_reminder(
            reminder_id,
            title="Updated Title",
            scheduled_time=new_time,
            description="New description",
        )
        assert update_result.success
        assert update_result.data["reminder"]["title"] == "Updated Title"

        # Cleanup
        await service.cancel_reminder(reminder_id)

    @pytest.mark.asyncio
    async def test_cancel_reminder(self, service, future_time):
        """Cancel a reminder (soft delete)."""
        # Create
        create_result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Cancel Test",
            scheduled_time=future_time,
        )
        assert create_result.success
        reminder_id = UUID(create_result.data["reminder_id"])

        # Cancel
        cancel_result = await service.cancel_reminder(reminder_id)
        assert cancel_result.success
        assert cancel_result.data["status"] == "cancelled"

        # Verify not in active list
        list_result = await service.list_active_reminders(TEST_USER_ID)
        reminder_ids = [r["id"] for r in list_result.data["reminders"]]
        assert str(reminder_id) not in reminder_ids

    @pytest.mark.asyncio
    async def test_complete_reminder(self, service, future_time):
        """Complete a reminder."""
        # Create
        create_result = await service.create_reminder(
            user_id=TEST_USER_ID,
            title="Complete Test",
            scheduled_time=future_time,
        )
        assert create_result.success
        reminder_id = UUID(create_result.data["reminder_id"])

        # Complete
        complete_result = await service.complete_reminder(reminder_id)
        assert complete_result.success
        assert complete_result.data["status"] == "completed"
        assert "completed_at" in complete_result.data

        # Verify is_completed is True
        get_result = await service.get_reminder(reminder_id)
        assert get_result.data["reminder"]["is_completed"] is True
        assert get_result.data["reminder"]["last_triggered_at"] is not None

        # Cleanup
        await service.cancel_reminder(reminder_id)


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    # Run validation tests (no database needed)
    print("Running validation tests...")
    pytest.main([__file__, "-v", "-k", "TestValidation"])

    # Run integration tests if configured
    if SUPABASE_CONFIGURED:
        print("\nRunning integration tests...")
        pytest.main([__file__, "-v", "-k", "TestCRUDOperations"])
    else:
        print("\nSkipping integration tests (Supabase not configured)")
        print("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to run them.")
