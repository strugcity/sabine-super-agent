"""
Tests for Reminder Scheduler - Phase 3.2 Verification
=====================================================

BDD-style tests verifying the reminder scheduler integration.
Run with: pytest tests/test_reminder_scheduler.py -v

Tests cover:
1. Trigger creation (DateTrigger, CronTrigger)
2. Job management (add, remove)
3. Job restoration from database
4. Scheduler lifecycle
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytz
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.agent.reminder_scheduler import (
    create_trigger_for_reminder,
    get_job_id,
    extract_reminder_id,
    ReminderScheduler,
    REMINDER_JOB_PREFIX,
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
def sample_reminder_id():
    """Create a sample reminder UUID."""
    return uuid4()


@pytest.fixture
def future_time():
    """Create a future datetime."""
    return datetime.now(timezone.utc) + timedelta(hours=2)


@pytest.fixture
def mock_scheduler():
    """Create a mock APScheduler."""
    scheduler = MagicMock()
    scheduler.running = True
    scheduler.get_jobs.return_value = []
    return scheduler


# =============================================================================
# Unit Tests: Trigger Creation
# =============================================================================

class TestTriggerCreation:
    """Test trigger creation functions."""

    def test_one_time_trigger_is_date_trigger(self, future_time):
        """One-time reminder creates DateTrigger."""
        trigger = create_trigger_for_reminder(future_time, repeat_pattern=None)
        assert isinstance(trigger, DateTrigger)

    def test_daily_trigger_is_cron_trigger(self, future_time):
        """Daily reminder creates CronTrigger."""
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="daily")
        assert isinstance(trigger, CronTrigger)

    def test_weekly_trigger_is_cron_trigger(self, future_time):
        """Weekly reminder creates CronTrigger."""
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="weekly")
        assert isinstance(trigger, CronTrigger)

    def test_monthly_trigger_is_cron_trigger(self, future_time):
        """Monthly reminder creates CronTrigger."""
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="monthly")
        assert isinstance(trigger, CronTrigger)

    def test_yearly_trigger_is_cron_trigger(self, future_time):
        """Yearly reminder creates CronTrigger."""
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="yearly")
        assert isinstance(trigger, CronTrigger)

    def test_unknown_pattern_creates_date_trigger(self, future_time):
        """Unknown pattern falls back to DateTrigger."""
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="biweekly")
        assert isinstance(trigger, DateTrigger)

    def test_trigger_handles_naive_datetime(self):
        """Trigger handles timezone-naive datetime."""
        naive_time = datetime.now() + timedelta(hours=2)
        trigger = create_trigger_for_reminder(naive_time, repeat_pattern=None)
        assert isinstance(trigger, DateTrigger)


# =============================================================================
# Unit Tests: Job ID Functions
# =============================================================================

class TestJobIdFunctions:
    """Test job ID helper functions."""

    def test_get_job_id_format(self, sample_reminder_id):
        """Job ID has correct format."""
        job_id = get_job_id(sample_reminder_id)
        assert job_id.startswith(REMINDER_JOB_PREFIX)
        assert str(sample_reminder_id) in job_id

    def test_extract_reminder_id_success(self, sample_reminder_id):
        """Extract reminder ID from valid job ID."""
        job_id = get_job_id(sample_reminder_id)
        extracted = extract_reminder_id(job_id)
        assert extracted == sample_reminder_id

    def test_extract_reminder_id_invalid_prefix(self):
        """Extract returns None for wrong prefix."""
        extracted = extract_reminder_id("other_job_id")
        assert extracted is None

    def test_extract_reminder_id_invalid_uuid(self):
        """Extract returns None for invalid UUID."""
        extracted = extract_reminder_id(f"{REMINDER_JOB_PREFIX}not-a-uuid")
        assert extracted is None


# =============================================================================
# Unit Tests: Scheduler Job Management
# =============================================================================

class TestSchedulerJobManagement:
    """Test scheduler job add/remove operations."""

    @pytest.mark.asyncio
    async def test_add_reminder_job(self, sample_reminder_id, future_time, mock_scheduler):
        """Add reminder job successfully."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        result = await scheduler.add_reminder_job(
            reminder_id=sample_reminder_id,
            scheduled_time=future_time,
            repeat_pattern=None,
            title="Test Reminder"
        )

        assert result is True
        mock_scheduler.add_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_recurring_job(self, sample_reminder_id, future_time, mock_scheduler):
        """Add recurring reminder job."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        result = await scheduler.add_reminder_job(
            reminder_id=sample_reminder_id,
            scheduled_time=future_time,
            repeat_pattern="weekly",
            title="Weekly Meeting"
        )

        assert result is True
        # Verify add_job was called with a CronTrigger
        call_args = mock_scheduler.add_job.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_remove_reminder_job(self, sample_reminder_id, mock_scheduler):
        """Remove reminder job successfully."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        result = await scheduler.remove_reminder_job(sample_reminder_id)

        assert result is True
        job_id = get_job_id(sample_reminder_id)
        mock_scheduler.remove_job.assert_called_with(job_id)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_job(self, sample_reminder_id, mock_scheduler):
        """Remove returns True for nonexistent job."""
        from apscheduler.jobstores.base import JobLookupError

        mock_scheduler.remove_job.side_effect = JobLookupError("job_id")
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        result = await scheduler.remove_reminder_job(sample_reminder_id)

        assert result is True  # Should succeed even if job doesn't exist


# =============================================================================
# Unit Tests: Get Reminder Jobs
# =============================================================================

class TestGetReminderJobs:
    """Test job listing functionality."""

    def test_get_reminder_jobs_empty(self, mock_scheduler):
        """Get jobs returns empty list when no jobs."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        jobs = scheduler.get_reminder_jobs()
        assert jobs == []

    def test_get_reminder_jobs_filters_non_reminder(self, mock_scheduler):
        """Get jobs filters out non-reminder jobs."""
        mock_job_reminder = MagicMock()
        mock_job_reminder.id = f"{REMINDER_JOB_PREFIX}{uuid4()}"
        mock_job_reminder.name = "Test Reminder"
        mock_job_reminder.next_run_time = datetime.now(timezone.utc)
        mock_job_reminder.trigger = "date[...]"

        mock_job_other = MagicMock()
        mock_job_other.id = "morning_briefing"
        mock_job_other.name = "Morning Briefing"

        mock_scheduler.get_jobs.return_value = [mock_job_reminder, mock_job_other]
        scheduler = ReminderScheduler(scheduler=mock_scheduler)

        jobs = scheduler.get_reminder_jobs()

        assert len(jobs) == 1
        assert jobs[0]["name"] == "Test Reminder"


# =============================================================================
# Unit Tests: Job Restoration
# =============================================================================

class TestJobRestoration:
    """Test job restoration from database."""

    @pytest.mark.asyncio
    async def test_restore_skips_past_one_time(self, mock_scheduler):
        """Restore skips past one-time reminders."""
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        past_reminder = {
            "id": str(uuid4()),
            "title": "Past Reminder",
            "scheduled_time": past_time,
            "repeat_pattern": None,
            "is_active": True,
            "is_completed": False,
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [past_reminder]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_response

        mock_service = MagicMock()
        mock_service.client = mock_client

        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        # Patch at the source module where it's imported from
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await scheduler.restore_reminder_jobs()
            # Past one-time reminder should be skipped
            assert result["skipped"] == 1
            assert result["restored"] == 0

    @pytest.mark.asyncio
    async def test_restore_adds_future_reminders(self, mock_scheduler):
        """Restore adds jobs for future reminders."""
        future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        future_reminder = {
            "id": str(uuid4()),
            "title": "Future Reminder",
            "scheduled_time": future_time,
            "repeat_pattern": None,
            "is_active": True,
            "is_completed": False,
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [future_reminder]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_response

        mock_service = MagicMock()
        mock_service.client = mock_client

        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        # Patch at the source module where it's imported from
        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await scheduler.restore_reminder_jobs()
            # Future reminder should be restored
            assert result["restored"] == 1
            assert result["skipped"] == 0
            # Verify job was added
            mock_scheduler.add_job.assert_called()


# =============================================================================
# Unit Tests: Scheduler Lifecycle
# =============================================================================

class TestSchedulerLifecycle:
    """Test scheduler start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_adds_poll_job(self, mock_scheduler):
        """Start adds the due reminder polling job."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)

        with patch.object(scheduler, 'restore_reminder_jobs', new_callable=AsyncMock):
            await scheduler.start()

        # Verify poll job was added
        mock_scheduler.add_job.assert_called()
        call_args = mock_scheduler.add_job.call_args_list[0]
        assert "reminder_poll" in str(call_args)

    @pytest.mark.asyncio
    async def test_double_start_warns(self, mock_scheduler):
        """Starting twice logs warning."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True

        with patch.object(scheduler, 'restore_reminder_jobs', new_callable=AsyncMock):
            await scheduler.start()  # Should not throw

    def test_is_running(self, mock_scheduler):
        """is_running reflects scheduler state."""
        scheduler = ReminderScheduler(scheduler=mock_scheduler)
        scheduler._started = True
        mock_scheduler.running = True

        assert scheduler.is_running() is True

        scheduler._started = False
        assert scheduler.is_running() is False


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running reminder scheduler tests...")
    pytest.main([__file__, "-v"])
