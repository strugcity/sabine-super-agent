"""
Tests for Reminder Notifications - Phase 3.1 Verification
=========================================================

BDD-style tests verifying the reminder notification system.
Run with: pytest tests/test_reminder_notifications.py -v

Tests cover:
1. Message formatting (SMS, email, Slack)
2. SMS notification sending
3. Email notification sending
4. Unified notification dispatcher
5. Reminder firing logic
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

from lib.agent.reminder_notifications import (
    format_reminder_message,
    format_reminder_email_html,
    send_sms_notification,
    send_email_notification,
    send_reminder_notification,
    fire_reminder,
    process_due_reminders,
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
        "description": "From the optometrist on Main Street",
        "reminder_type": "sms",
        "scheduled_time": scheduled.isoformat(),
        "repeat_pattern": None,
        "notification_channels": {"sms": True},
        "is_active": True,
        "is_completed": False,
    }


@pytest.fixture
def recurring_reminder():
    """Create a recurring reminder dict."""
    scheduled = datetime.now(timezone.utc) + timedelta(days=1)
    return {
        "id": str(uuid4()),
        "user_id": "75abac49-2b45-44ab-a57d-8ca6ecad2b8c",
        "title": "Weekly team meeting",
        "description": "Standup with the engineering team",
        "reminder_type": "email",
        "scheduled_time": scheduled.isoformat(),
        "repeat_pattern": "weekly",
        "notification_channels": {"email": True},
        "is_active": True,
        "is_completed": False,
    }


@pytest.fixture
def multi_channel_reminder():
    """Create a reminder with multiple channels."""
    scheduled = datetime.now(timezone.utc) + timedelta(hours=1)
    return {
        "id": str(uuid4()),
        "user_id": "75abac49-2b45-44ab-a57d-8ca6ecad2b8c",
        "title": "Important meeting",
        "description": "Don't forget the presentation",
        "reminder_type": "sms",
        "scheduled_time": scheduled.isoformat(),
        "repeat_pattern": None,
        "notification_channels": {"sms": True, "email": True},
        "is_active": True,
        "is_completed": False,
    }


# =============================================================================
# Unit Tests: Message Formatting
# =============================================================================

class TestMessageFormatting:
    """Test message formatting functions."""

    def test_format_sms_message(self, sample_reminder):
        """Format SMS message is concise."""
        msg = format_reminder_message(sample_reminder, "sms")
        assert "⏰ Reminder:" in msg
        assert "Pick up glasses" in msg
        # SMS should be reasonably short
        assert len(msg) < 200

    def test_format_sms_truncates_description(self):
        """Long descriptions are truncated for SMS."""
        reminder = {
            "title": "Test",
            "description": "A" * 200,  # Very long description
            "scheduled_time": datetime.now(timezone.utc).isoformat(),
        }
        msg = format_reminder_message(reminder, "sms")
        assert "..." in msg
        assert len(msg) < 300

    def test_format_sms_shows_repeat_pattern(self, recurring_reminder):
        """SMS shows repeat pattern."""
        msg = format_reminder_message(recurring_reminder, "sms")
        assert "weekly" in msg.lower()

    def test_format_email_message(self, sample_reminder):
        """Format email message is detailed."""
        msg = format_reminder_message(sample_reminder, "email")
        assert "Pick up glasses" in msg
        assert "From the optometrist" in msg
        assert "Sabine" in msg

    def test_format_email_html(self, sample_reminder):
        """Format HTML email properly."""
        html = format_reminder_email_html(sample_reminder)
        assert "<html>" in html
        assert "Pick up glasses" in html
        assert "From the optometrist" in html
        assert "background-color" in html  # Has styling

    def test_format_slack_message(self, sample_reminder):
        """Format Slack message with markdown."""
        msg = format_reminder_message(sample_reminder, "slack")
        assert "*Reminder*" in msg  # Bold syntax
        assert "Pick up glasses" in msg


# =============================================================================
# Unit Tests: SMS Notification
# =============================================================================

class TestSMSNotification:
    """Test SMS notification sending."""

    @pytest.mark.asyncio
    async def test_sms_no_phone_number(self, sample_reminder):
        """SMS returns error when no phone configured."""
        with patch.dict(os.environ, {"USER_PHONE": ""}):
            # Need to reload to pick up env change
            result = await send_sms_notification(sample_reminder, phone_number=None)

        # Without phone, should fail
        assert result["channel"] == "sms"
        # Either no phone or would_send (if Twilio not configured)

    @pytest.mark.asyncio
    async def test_sms_twilio_not_configured(self, sample_reminder):
        """SMS logs message when Twilio not configured."""
        result = await send_sms_notification(sample_reminder, phone_number="+15551234567")

        assert result["channel"] == "sms"
        # Should have would_send message showing what would be sent
        if not result.get("success"):
            assert "would_send" in result or "error" in result


# =============================================================================
# Unit Tests: Email Notification
# =============================================================================

class TestEmailNotification:
    """Test email notification sending."""

    @pytest.mark.asyncio
    async def test_email_no_recipient(self, sample_reminder):
        """Email returns error when no recipient configured."""
        result = await send_email_notification(sample_reminder, to_email=None)

        assert result["channel"] == "email"
        # Should fail without recipient
        if not os.getenv("USER_GOOGLE_EMAIL"):
            assert not result.get("success")

    @pytest.mark.asyncio
    async def test_email_no_credentials(self, sample_reminder):
        """Email returns error when Gmail credentials not configured."""
        with patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "AGENT_REFRESH_TOKEN": "",
        }):
            result = await send_email_notification(
                sample_reminder,
                to_email="test@example.com"
            )

        assert result["channel"] == "email"
        assert not result.get("success")
        assert "credentials" in result.get("error", "").lower()


# =============================================================================
# Unit Tests: Unified Dispatcher
# =============================================================================

class TestNotificationDispatcher:
    """Test unified notification dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatcher_single_channel(self, sample_reminder):
        """Dispatcher handles single channel."""
        with patch(
            "lib.agent.reminder_notifications.send_sms_notification",
            new_callable=AsyncMock
        ) as mock_sms:
            mock_sms.return_value = {"success": True, "channel": "sms"}

            result = await send_reminder_notification(
                sample_reminder,
                channels={"sms": True}
            )

        assert result["reminder_id"] == sample_reminder["id"]
        assert "sms" in result["channels_attempted"]
        mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatcher_multiple_channels(self, multi_channel_reminder):
        """Dispatcher handles multiple channels."""
        with patch(
            "lib.agent.reminder_notifications.send_sms_notification",
            new_callable=AsyncMock
        ) as mock_sms, patch(
            "lib.agent.reminder_notifications.send_email_notification",
            new_callable=AsyncMock
        ) as mock_email:
            mock_sms.return_value = {"success": True, "channel": "sms"}
            mock_email.return_value = {"success": True, "channel": "email"}

            result = await send_reminder_notification(multi_channel_reminder)

        assert "sms" in result["channels_attempted"]
        assert "email" in result["channels_attempted"]
        assert result["success"]

    @pytest.mark.asyncio
    async def test_dispatcher_partial_failure(self, multi_channel_reminder):
        """Dispatcher reports partial success when some channels fail."""
        with patch(
            "lib.agent.reminder_notifications.send_sms_notification",
            new_callable=AsyncMock
        ) as mock_sms, patch(
            "lib.agent.reminder_notifications.send_email_notification",
            new_callable=AsyncMock
        ) as mock_email:
            mock_sms.return_value = {"success": True, "channel": "sms"}
            mock_email.return_value = {"success": False, "channel": "email", "error": "Failed"}

            result = await send_reminder_notification(multi_channel_reminder)

        assert result["success"]  # At least one succeeded
        assert result["partial_success"]  # But not all
        assert "sms" in result["channels_succeeded"]
        assert "email" in result["channels_failed"]

    @pytest.mark.asyncio
    async def test_dispatcher_defaults_to_sms(self, sample_reminder):
        """Dispatcher defaults to SMS when no channels specified."""
        reminder_no_channels = {**sample_reminder, "notification_channels": {}}

        with patch(
            "lib.agent.reminder_notifications.send_sms_notification",
            new_callable=AsyncMock
        ) as mock_sms:
            mock_sms.return_value = {"success": True, "channel": "sms"}

            result = await send_reminder_notification(reminder_no_channels)

        assert "sms" in result["channels_attempted"]


# =============================================================================
# Unit Tests: Fire Reminder
# =============================================================================

class TestFireReminder:
    """Test reminder firing logic."""

    @pytest.mark.asyncio
    async def test_fire_one_time_reminder(self, sample_reminder):
        """Fire one-time reminder marks it as completed."""
        from backend.services.exceptions import OperationResult

        mock_service = MagicMock()
        mock_service.get_reminder = AsyncMock(
            return_value=OperationResult.ok({"reminder": sample_reminder})
        )
        mock_service.complete_reminder = AsyncMock(
            return_value=OperationResult.ok({"status": "completed"})
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ), patch(
            "lib.agent.reminder_notifications.send_reminder_notification",
            new_callable=AsyncMock
        ) as mock_notify:
            mock_notify.return_value = {"success": True, "channels_succeeded": ["sms"]}

            result = await fire_reminder(UUID(sample_reminder["id"]))

        assert result["status"] == "success"
        assert result["action"] == "completed"
        mock_service.complete_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_recurring_reminder(self, recurring_reminder):
        """Fire recurring reminder updates last_triggered but stays active."""
        from backend.services.exceptions import OperationResult

        mock_service = MagicMock()
        mock_service.get_reminder = AsyncMock(
            return_value=OperationResult.ok({"reminder": recurring_reminder})
        )
        mock_service.update_last_triggered = AsyncMock(
            return_value=OperationResult.ok({"status": "triggered"})
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ), patch(
            "lib.agent.reminder_notifications.send_reminder_notification",
            new_callable=AsyncMock
        ) as mock_notify:
            mock_notify.return_value = {"success": True, "channels_succeeded": ["email"]}

            result = await fire_reminder(UUID(recurring_reminder["id"]))

        assert result["status"] == "success"
        assert result["action"] == "triggered_recurring"
        mock_service.update_last_triggered.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_inactive_reminder_skipped(self, sample_reminder):
        """Fire skips inactive reminders."""
        from backend.services.exceptions import OperationResult

        inactive_reminder = {**sample_reminder, "is_active": False}
        mock_service = MagicMock()
        mock_service.get_reminder = AsyncMock(
            return_value=OperationResult.ok({"reminder": inactive_reminder})
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await fire_reminder(UUID(sample_reminder["id"]))

        assert result["status"] == "skipped"
        assert "not active" in result["error"]


# =============================================================================
# Unit Tests: Process Due Reminders
# =============================================================================

class TestProcessDueReminders:
    """Test batch processing of due reminders."""

    @pytest.mark.asyncio
    async def test_process_no_due_reminders(self):
        """Process returns empty when no reminders due."""
        from backend.services.exceptions import OperationResult

        mock_service = MagicMock()
        mock_service.list_due_reminders = AsyncMock(
            return_value=OperationResult.ok({"reminders": [], "count": 0})
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await process_due_reminders()

        assert result["reminders_found"] == 0
        assert result["reminders_processed"] == 0

    @pytest.mark.asyncio
    async def test_process_multiple_due_reminders(self, sample_reminder, recurring_reminder):
        """Process handles multiple due reminders."""
        from backend.services.exceptions import OperationResult

        mock_service = MagicMock()
        mock_service.list_due_reminders = AsyncMock(
            return_value=OperationResult.ok({
                "reminders": [sample_reminder, recurring_reminder],
                "count": 2
            })
        )
        mock_service.get_reminder = AsyncMock(side_effect=[
            OperationResult.ok({"reminder": sample_reminder}),
            OperationResult.ok({"reminder": recurring_reminder}),
        ])
        mock_service.complete_reminder = AsyncMock(
            return_value=OperationResult.ok({})
        )
        mock_service.update_last_triggered = AsyncMock(
            return_value=OperationResult.ok({})
        )

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ), patch(
            "lib.agent.reminder_notifications.send_reminder_notification",
            new_callable=AsyncMock
        ) as mock_notify:
            mock_notify.return_value = {"success": True, "channels_succeeded": ["sms"]}

            result = await process_due_reminders()

        assert result["reminders_found"] == 2
        assert result["reminders_processed"] == 2


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running reminder notification tests...")
    pytest.main([__file__, "-v"])
