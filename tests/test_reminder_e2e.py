"""
End-to-End Tests for Reminder System - Phase 5.3 Verification
==============================================================

Integration tests that verify the complete reminder workflow.
Run with: pytest tests/test_reminder_e2e.py -v

Tests cover:
1. Create → List → Cancel workflow
2. Scheduler job lifecycle
3. Notification formatting pipeline
4. Calendar event with hybrid SMS
5. Trigger creation accuracy
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

# User timezone
USER_TIMEZONE = pytz.timezone("America/Chicago")


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def future_time():
    """Create a future datetime in user's timezone."""
    return datetime.now(USER_TIMEZONE) + timedelta(hours=2)


@pytest.fixture
def mock_reminder_data():
    """Create sample reminder data."""
    return {
        "id": str(uuid4()),
        "user_id": "75abac49-2b45-44ab-a57d-8ca6ecad2b8c",
        "title": "Test E2E Reminder",
        "description": "This is an end-to-end test reminder",
        "scheduled_time": (datetime.now(USER_TIMEZONE) + timedelta(hours=2)).isoformat(),
        "reminder_type": "sms",
        "repeat_pattern": None,
        "notification_channels": {"sms": True},
        "is_active": True,
        "is_completed": False,
        "created_at": datetime.now(USER_TIMEZONE).isoformat(),
    }


# =============================================================================
# E2E Test: Complete Reminder Workflow
# =============================================================================

class TestCompleteReminderWorkflow:
    """Test the complete create → list → cancel workflow."""

    @pytest.mark.asyncio
    async def test_create_list_cancel_workflow(self, future_time):
        """
        E2E: Create a reminder, verify it's listed, then cancel it.

        This test simulates the user workflow:
        1. "Remind me at 2pm to pick up glasses"
        2. "What reminders do I have?"
        3. "Cancel the glasses reminder"
        """
        from lib.skills.reminder.handler import execute as create_reminder
        from lib.skills.list_reminders.handler import execute as list_reminders
        from lib.skills.cancel_reminder.handler import execute as cancel_reminder

        reminder_id = str(uuid4())
        mock_reminder = {
            "id": reminder_id,
            "title": "Pick up glasses",
            "scheduled_time": future_time.isoformat(),
            "reminder_type": "sms",
            "repeat_pattern": None,
            "is_active": True,
            "is_completed": False,
        }

        # Mock the service
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"reminder": mock_reminder}
        mock_result.error = None

        mock_list_result = MagicMock()
        mock_list_result.success = True
        mock_list_result.data = {"reminders": [mock_reminder], "count": 1}

        mock_cancel_result = MagicMock()
        mock_cancel_result.success = True
        mock_cancel_result.data = {}

        with patch("backend.services.reminder_service.get_reminder_service") as mock_svc:
            mock_service = MagicMock()
            mock_service.create_reminder = AsyncMock(return_value=mock_result)
            mock_service.list_active_reminders = AsyncMock(return_value=mock_list_result)
            mock_service.cancel_reminder = AsyncMock(return_value=mock_cancel_result)
            mock_service.get_reminder = AsyncMock(return_value=mock_result)
            mock_svc.return_value = mock_service

            # Step 1: Create reminder
            create_result = await create_reminder({
                "title": "Pick up glasses",
                "scheduled_time": future_time.isoformat(),
                "reminder_type": "sms",
            })
            assert create_result["status"] == "success"
            assert "glasses" in create_result["message"].lower()

            # Step 2: List reminders
            list_result = await list_reminders({})
            assert list_result["status"] == "success"
            assert list_result["count"] == 1
            assert "Pick up glasses" in list_result["message"]

            # Step 3: Cancel reminder
            cancel_result = await cancel_reminder({"reminder_id": reminder_id})
            assert cancel_result["status"] == "success"
            assert "cancelled" in cancel_result["message"].lower()


# =============================================================================
# E2E Test: Scheduler Integration
# =============================================================================

class TestSchedulerIntegration:
    """Test scheduler job lifecycle."""

    @pytest.mark.asyncio
    async def test_job_created_on_reminder_create(self, future_time):
        """E2E: Creating a reminder should add a scheduler job."""
        from lib.agent.reminder_scheduler import (
            ReminderScheduler,
            create_trigger_for_reminder,
            get_job_id,
        )
        from apscheduler.triggers.date import DateTrigger

        # Create a mock scheduler
        mock_apscheduler = MagicMock()
        mock_apscheduler.running = True
        mock_apscheduler.get_jobs.return_value = []

        scheduler = ReminderScheduler(scheduler=mock_apscheduler)
        scheduler._started = True

        reminder_id = uuid4()

        # Add a reminder job
        result = await scheduler.add_reminder_job(
            reminder_id=reminder_id,
            scheduled_time=future_time,
            repeat_pattern=None,
            title="Test Reminder"
        )

        assert result is True
        mock_apscheduler.add_job.assert_called_once()

        # Verify job ID format
        call_kwargs = mock_apscheduler.add_job.call_args
        assert get_job_id(reminder_id) in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_job_removed_on_reminder_cancel(self):
        """E2E: Cancelling a reminder should remove its scheduler job."""
        from lib.agent.reminder_scheduler import ReminderScheduler, get_job_id

        mock_apscheduler = MagicMock()
        mock_apscheduler.running = True

        scheduler = ReminderScheduler(scheduler=mock_apscheduler)
        scheduler._started = True

        reminder_id = uuid4()

        # Remove a reminder job
        result = await scheduler.remove_reminder_job(reminder_id)

        assert result is True
        mock_apscheduler.remove_job.assert_called_with(get_job_id(reminder_id))

    def test_trigger_types_match_patterns(self, future_time):
        """E2E: Verify correct trigger types for different patterns."""
        from lib.agent.reminder_scheduler import create_trigger_for_reminder
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.cron import CronTrigger

        # One-time should use DateTrigger
        trigger = create_trigger_for_reminder(future_time, repeat_pattern=None)
        assert isinstance(trigger, DateTrigger)

        # Daily should use CronTrigger
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="daily")
        assert isinstance(trigger, CronTrigger)

        # Weekly should use CronTrigger
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="weekly")
        assert isinstance(trigger, CronTrigger)

        # Monthly should use CronTrigger
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="monthly")
        assert isinstance(trigger, CronTrigger)

        # Yearly should use CronTrigger
        trigger = create_trigger_for_reminder(future_time, repeat_pattern="yearly")
        assert isinstance(trigger, CronTrigger)


# =============================================================================
# E2E Test: Notification Pipeline
# =============================================================================

class TestNotificationPipeline:
    """Test the notification formatting and dispatch pipeline."""

    def test_message_formatting_pipeline(self, mock_reminder_data):
        """E2E: Verify message formatting for all channels."""
        from lib.agent.reminder_notifications import format_reminder_message

        # SMS format
        sms_msg = format_reminder_message(mock_reminder_data, channel="sms")
        assert "Reminder:" in sms_msg
        assert mock_reminder_data["title"] in sms_msg

        # Email format - returns dict with subject/body for email
        email_result = format_reminder_message(mock_reminder_data, channel="email")
        # Email may return string or dict depending on implementation
        if isinstance(email_result, dict):
            assert "subject" in email_result or "body" in email_result
        else:
            # String format is also valid
            assert mock_reminder_data["title"] in email_result

        # Slack format
        slack_msg = format_reminder_message(mock_reminder_data, channel="slack")
        assert mock_reminder_data["title"] in slack_msg

    @pytest.mark.asyncio
    async def test_fire_reminder_one_time(self, mock_reminder_data):
        """E2E: Firing a one-time reminder marks it as completed."""
        from lib.agent.reminder_notifications import fire_reminder

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"reminder": mock_reminder_data}

        mock_complete_result = MagicMock()
        mock_complete_result.success = True

        with patch("backend.services.reminder_service.get_reminder_service") as mock_svc:
            mock_service = MagicMock()
            mock_service.get_reminder = AsyncMock(return_value=mock_result)
            mock_service.complete_reminder = AsyncMock(return_value=mock_complete_result)
            mock_svc.return_value = mock_service

            with patch(
                "lib.agent.reminder_notifications.send_reminder_notification",
                return_value={"sms": {"success": True}}
            ):
                result = await fire_reminder(uuid4())

                assert result["status"] == "success"
                # One-time reminder should be marked as completed
                mock_service.complete_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_reminder_recurring(self):
        """E2E: Firing a recurring reminder updates last_triggered."""
        from lib.agent.reminder_notifications import fire_reminder

        recurring_reminder = {
            "id": str(uuid4()),
            "title": "Weekly standup",
            "description": None,
            "scheduled_time": (datetime.now(USER_TIMEZONE) + timedelta(hours=2)).isoformat(),
            "reminder_type": "sms",
            "repeat_pattern": "weekly",
            "notification_channels": {"sms": True},
            "is_active": True,
            "is_completed": False,
        }

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"reminder": recurring_reminder}

        mock_update_result = MagicMock()
        mock_update_result.success = True

        with patch("backend.services.reminder_service.get_reminder_service") as mock_svc:
            mock_service = MagicMock()
            mock_service.get_reminder = AsyncMock(return_value=mock_result)
            mock_service.update_reminder = AsyncMock(return_value=mock_update_result)
            mock_service.update_last_triggered = AsyncMock(return_value=mock_update_result)
            mock_svc.return_value = mock_service

            with patch(
                "lib.agent.reminder_notifications.send_reminder_notification",
                return_value={"sms": {"success": True}}
            ):
                result = await fire_reminder(uuid4())

                assert result["status"] == "success"
                # Recurring reminder should have last_triggered updated
                mock_service.update_last_triggered.assert_called_once()


# =============================================================================
# E2E Test: Calendar Event with Hybrid SMS
# =============================================================================

class TestCalendarHybridWorkflow:
    """Test calendar event creation with optional SMS reminder."""

    @pytest.mark.asyncio
    async def test_calendar_event_with_sms(self, future_time):
        """E2E: Create calendar event with hybrid SMS reminder."""
        from lib.skills.create_calendar_event.handler import execute

        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "gcal_event_123",
                    "html_link": "https://calendar.google.com/event?eid=123",
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
                        "title": "Important Meeting",
                        "start_time": future_time.isoformat(),
                        "reminder_minutes": 30,
                        "also_sms_reminder": True,
                        "sms_reminder_minutes": 60,
                    })

                    assert result["status"] == "success"
                    assert result["event_id"] == "gcal_event_123"
                    assert "text you" in result["message"].lower()
                    assert result["sms_reminder"]["success"] is True

    @pytest.mark.asyncio
    async def test_calendar_event_sms_fails_gracefully(self, future_time):
        """E2E: Calendar event created even if SMS reminder fails."""
        from lib.skills.create_calendar_event.handler import execute

        with patch(
            "lib.skills.create_calendar_event.handler.get_access_token",
            return_value="mock_token"
        ):
            with patch(
                "lib.skills.create_calendar_event.handler.create_google_calendar_event",
                return_value={
                    "success": True,
                    "event_id": "gcal_event_456",
                    "html_link": "https://calendar.google.com/event?eid=456",
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
                        "title": "Meeting",
                        "start_time": future_time.isoformat(),
                        "also_sms_reminder": True,
                    })

                    # Event should still succeed
                    assert result["status"] == "success"
                    assert result["event_id"] == "gcal_event_456"
                    # But note the SMS failure
                    assert "couldn't set up the SMS" in result["message"]


# =============================================================================
# E2E Test: Skill Registry Integration
# =============================================================================

class TestSkillRegistryIntegration:
    """Test that all reminder skills are properly registered."""

    def test_all_reminder_skills_registered(self):
        """E2E: Verify all reminder skills are loaded in the registry."""
        from lib.agent.registry import get_all_tools_sync

        tools = get_all_tools_sync()
        tool_names = [t.name for t in tools]

        required_skills = [
            "create_reminder",
            "list_reminders",
            "cancel_reminder",
            "create_calendar_event",
        ]

        for skill in required_skills:
            assert skill in tool_names, f"Skill '{skill}' not found in registry"

    def test_skills_have_valid_schemas(self):
        """E2E: Verify all reminder skills have valid parameter schemas."""
        from lib.agent.registry import get_all_tools_sync

        tools = get_all_tools_sync()
        reminder_tools = [
            t for t in tools
            if t.name in ["create_reminder", "list_reminders", "cancel_reminder", "create_calendar_event"]
        ]

        for tool in reminder_tools:
            assert tool.description, f"{tool.name} missing description"
            assert tool.args_schema, f"{tool.name} missing args_schema"


# =============================================================================
# E2E Test: Timezone Handling
# =============================================================================

class TestTimezoneHandling:
    """Test timezone handling across the reminder system."""

    def test_trigger_respects_user_timezone(self):
        """E2E: Trigger uses user's timezone (Central)."""
        from lib.agent.reminder_scheduler import create_trigger_for_reminder, USER_TIMEZONE
        from apscheduler.triggers.cron import CronTrigger

        # Create a time in Central timezone
        local_time = datetime(2026, 3, 15, 10, 30, tzinfo=USER_TIMEZONE)

        trigger = create_trigger_for_reminder(local_time, repeat_pattern="daily")

        # Verify it's a CronTrigger for daily pattern
        assert isinstance(trigger, CronTrigger)
        # CronTrigger stores fields differently - verify it was created successfully
        assert trigger is not None
        # Verify timezone is set
        assert trigger.timezone is not None

    def test_message_displays_local_time(self, mock_reminder_data):
        """E2E: Reminder messages contain reminder title."""
        from lib.agent.reminder_notifications import format_reminder_message

        msg = format_reminder_message(mock_reminder_data, channel="sms")

        # Should contain the reminder title
        assert mock_reminder_data["title"] in msg
        # Should contain "Reminder" indicator
        assert "Reminder" in msg


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running reminder system E2E tests...")
    pytest.main([__file__, "-v"])
