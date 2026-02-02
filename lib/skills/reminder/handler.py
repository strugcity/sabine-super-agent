"""
Reminder Skill Handler - Step 2.2
=================================

Creates scheduled reminders that notify via SMS, email, Slack, or calendar events.
Integrates with the ReminderService for database persistence and validation.

BDD Specification:
    Feature: Create Reminder Handler

      Scenario: Create a one-time SMS reminder
        Given I say "remind me at 10 AM tomorrow about picking up glasses"
        When Sabine calls create_reminder with title and scheduled_time
        Then a reminder should be saved to the database
        And Sabine should confirm with the reminder details

      Scenario: Create a recurring weekly reminder
        Given I say "remind me every Sunday at 4 PM to post the baseball video"
        When Sabine calls create_reminder with repeat_pattern="weekly"
        Then a reminder should be saved with the recurrence pattern
        And Sabine should confirm the recurring schedule

      Scenario: Handle invalid time
        Given a scheduled_time in the past
        When create_reminder is called
        Then the skill should return an error message

      Scenario: Handle missing required fields
        Given create_reminder is called without title or scheduled_time
        Then the skill should return a helpful error message

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 2.2
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import pytz

logger = logging.getLogger(__name__)

# User's timezone - US Central (same as calendar skill)
USER_TIMEZONE = pytz.timezone("America/Chicago")

# Default user ID for single-user mode
# In multi-tenant mode, this would come from the request context
# This user must exist in the users table - we use the primary Sabine user
_env_user_id = os.getenv("DEFAULT_USER_ID", "")
# Handle placeholder values that aren't real user IDs
if not _env_user_id or _env_user_id.startswith("00000000"):
    DEFAULT_USER_ID = "75abac49-2b45-44ab-a57d-8ca6ecad2b8c"  # Real user from database
else:
    DEFAULT_USER_ID = _env_user_id


def parse_scheduled_time(time_str: str) -> Optional[datetime]:
    """
    Parse scheduled_time string into a timezone-aware datetime.

    Supports:
    - ISO 8601 format: "2026-02-03T10:00:00Z" or "2026-02-03T10:00:00-06:00"
    - Date only: "2026-02-03" (assumes midnight in user's timezone)

    Returns:
        Timezone-aware datetime or None if parsing fails
    """
    if not time_str:
        return None

    try:
        # Try ISO 8601 with timezone
        if 'T' in time_str:
            # Handle Z suffix (UTC)
            if time_str.endswith('Z'):
                time_str = time_str[:-1] + '+00:00'

            dt = datetime.fromisoformat(time_str)

            # If no timezone, assume user's timezone
            if dt.tzinfo is None:
                dt = USER_TIMEZONE.localize(dt)

            return dt

        # Date only - assume midnight in user's timezone
        dt = datetime.strptime(time_str, "%Y-%m-%d")
        dt = USER_TIMEZONE.localize(dt.replace(hour=0, minute=0, second=0))
        return dt

    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse scheduled_time '{time_str}': {e}")
        return None


def format_confirmation_message(
    title: str,
    scheduled_time: datetime,
    reminder_type: str,
    repeat_pattern: Optional[str] = None,
    reminder_id: Optional[str] = None,
) -> str:
    """
    Format a user-friendly confirmation message.

    Examples:
        "I'll remind you at 10:00 AM on Monday, February 3rd about 'Pick up glasses' via SMS."
        "I've set up a weekly reminder every Sunday at 4:00 PM about 'Post baseball video' via SMS."
    """
    # Convert to user's timezone for display
    local_time = scheduled_time.astimezone(USER_TIMEZONE)

    # Format time and date
    time_str = local_time.strftime("%I:%M %p").lstrip("0")  # "10:00 AM"
    date_str = local_time.strftime("%A, %B %d")  # "Monday, February 3rd"

    # Add ordinal suffix to day
    day = local_time.day
    if 4 <= day <= 20 or 24 <= day <= 30:
        suffix = "th"
    else:
        suffix = ["st", "nd", "rd"][day % 10 - 1] if day % 10 <= 3 else "th"
    date_str = local_time.strftime(f"%A, %B {day}{suffix}")

    # Format channel
    channel_map = {
        "sms": "SMS",
        "email": "email",
        "slack": "Slack",
        "calendar_event": "calendar event",
    }
    channel = channel_map.get(reminder_type, reminder_type)

    if repeat_pattern:
        # Recurring reminder
        pattern_phrases = {
            "daily": "every day",
            "weekly": f"every {local_time.strftime('%A')}",
            "monthly": f"on the {day}{suffix} of each month",
            "yearly": f"every {local_time.strftime('%B %d')}",
        }
        pattern_phrase = pattern_phrases.get(repeat_pattern, repeat_pattern)

        return (
            f"I've set up a {repeat_pattern} reminder {pattern_phrase} at {time_str} "
            f"about '{title}' via {channel}."
        )
    else:
        # One-time reminder
        return (
            f"I'll remind you at {time_str} on {date_str} "
            f"about '{title}' via {channel}."
        )


async def execute(params: dict) -> dict:
    """
    Create a scheduled reminder.

    Args:
        params: Dict with:
            - title (required): What to remind about
            - scheduled_time (required): When to trigger (ISO 8601 datetime)
            - description (optional): Additional details
            - reminder_type (optional): sms, email, slack, calendar_event (default: sms)
            - repeat_pattern (optional): daily, weekly, monthly, yearly

    Returns:
        Dict with:
            - status: "success" or "error"
            - message: User-friendly confirmation or error message
            - reminder_id: UUID of created reminder (on success)
            - reminder: Full reminder data (on success)
    """
    # Import here to avoid circular imports
    from backend.services.reminder_service import get_reminder_service

    # Extract parameters
    title = params.get("title", "").strip()
    scheduled_time_str = params.get("scheduled_time", "")
    description = params.get("description")
    reminder_type = params.get("reminder_type", "sms")
    repeat_pattern = params.get("repeat_pattern")

    logger.info(f"create_reminder called: title='{title}', time='{scheduled_time_str}', type='{reminder_type}'")

    # =========================================================================
    # Validate Required Parameters
    # =========================================================================

    if not title:
        return {
            "status": "error",
            "message": "I need to know what to remind you about. Please provide a title for the reminder.",
        }

    if not scheduled_time_str:
        return {
            "status": "error",
            "message": "I need to know when to remind you. Please provide a scheduled time.",
        }

    # Parse scheduled_time
    scheduled_time = parse_scheduled_time(scheduled_time_str)
    if not scheduled_time:
        return {
            "status": "error",
            "message": (
                f"I couldn't understand the time '{scheduled_time_str}'. "
                "Please use ISO 8601 format like '2026-02-03T10:00:00Z' or '2026-02-03T10:00:00-06:00'."
            ),
        }

    # Check if time is in the future
    now = datetime.now(timezone.utc)
    if scheduled_time <= now:
        local_time = scheduled_time.astimezone(USER_TIMEZONE)
        return {
            "status": "error",
            "message": (
                f"The time you specified ({local_time.strftime('%I:%M %p on %B %d')}) "
                "is in the past. Please choose a future time for your reminder."
            ),
        }

    # Validate reminder_type
    valid_types = {"sms", "email", "slack", "calendar_event"}
    if reminder_type not in valid_types:
        return {
            "status": "error",
            "message": (
                f"'{reminder_type}' is not a valid reminder type. "
                f"Please choose from: {', '.join(valid_types)}."
            ),
        }

    # Validate repeat_pattern
    valid_patterns = {None, "daily", "weekly", "monthly", "yearly"}
    if repeat_pattern and repeat_pattern not in valid_patterns:
        return {
            "status": "error",
            "message": (
                f"'{repeat_pattern}' is not a valid repeat pattern. "
                "Please choose from: daily, weekly, monthly, yearly."
            ),
        }

    # =========================================================================
    # Create Reminder via Service
    # =========================================================================

    try:
        user_id = UUID(DEFAULT_USER_ID)
    except (ValueError, TypeError):
        logger.error(f"Invalid DEFAULT_USER_ID: {DEFAULT_USER_ID}")
        return {
            "status": "error",
            "message": "Configuration error: Invalid user ID. Please contact support.",
        }

    service = get_reminder_service()

    # Set notification channels based on reminder_type
    notification_channels = {reminder_type: True}

    result = await service.create_reminder(
        user_id=user_id,
        title=title,
        scheduled_time=scheduled_time,
        description=description,
        reminder_type=reminder_type,
        repeat_pattern=repeat_pattern,
        notification_channels=notification_channels,
        metadata={
            "source": "skill",
            "skill_name": "create_reminder",
        },
    )

    if not result.success:
        error_msg = result.error.message if result.error else "Unknown error"
        logger.error(f"Failed to create reminder: {error_msg}")
        return {
            "status": "error",
            "message": f"I couldn't create the reminder: {error_msg}",
        }

    # =========================================================================
    # Return Success Response
    # =========================================================================

    reminder_id = result.data.get("reminder_id")
    reminder_data = result.data.get("reminder", {})

    confirmation = format_confirmation_message(
        title=title,
        scheduled_time=scheduled_time,
        reminder_type=reminder_type,
        repeat_pattern=repeat_pattern,
        reminder_id=reminder_id,
    )

    logger.info(f"Created reminder {reminder_id}: {title}")

    return {
        "status": "success",
        "message": confirmation,
        "reminder_id": reminder_id,
        "reminder": {
            "id": reminder_id,
            "title": title,
            "scheduled_time": scheduled_time.isoformat(),
            "scheduled_time_local": scheduled_time.astimezone(USER_TIMEZONE).strftime("%Y-%m-%d %I:%M %p %Z"),
            "reminder_type": reminder_type,
            "repeat_pattern": repeat_pattern,
            "description": description,
        },
    }
