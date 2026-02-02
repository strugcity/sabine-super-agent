"""
List Reminders Skill Handler - Step 2.4
=======================================

Lists all active reminders for the user, sorted by scheduled time.
Returns a formatted list showing reminder details.

BDD Specification:
    Feature: List Reminders

      Scenario: List all active reminders
        Given I have 3 active reminders and 1 completed
        When I say "what reminders do I have?"
        Then Sabine should list only the 3 active reminders
        And they should be sorted by scheduled_time
        And show title, time, and repeat pattern if any

      Scenario: No active reminders
        Given I have no active reminders
        When I say "what reminders do I have?"
        Then Sabine should say "You don't have any active reminders"

      Scenario: Format reminders for easy reading
        Given I have reminders with various types and patterns
        When I list my reminders
        Then each reminder should show:
          - Title
          - Scheduled time in user's timezone
          - Reminder type (SMS, email, Slack)
          - Recurrence pattern if recurring

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 2.3 (List Reminders)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import pytz

logger = logging.getLogger(__name__)

# User's timezone - US Central (same as other skills)
USER_TIMEZONE = pytz.timezone("America/Chicago")

# Default user ID for single-user mode
_env_user_id = os.getenv("DEFAULT_USER_ID", "")
if not _env_user_id or _env_user_id.startswith("00000000"):
    DEFAULT_USER_ID = "75abac49-2b45-44ab-a57d-8ca6ecad2b8c"  # Real user from database
else:
    DEFAULT_USER_ID = _env_user_id


def format_reminder_time(scheduled_time_str: str) -> str:
    """
    Format a scheduled time string for user-friendly display.

    Args:
        scheduled_time_str: ISO 8601 datetime string

    Returns:
        Formatted string like "Monday, February 3rd at 10:00 AM"
    """
    try:
        # Parse the datetime string
        if scheduled_time_str.endswith('Z'):
            dt = datetime.fromisoformat(scheduled_time_str[:-1] + '+00:00')
        else:
            dt = datetime.fromisoformat(scheduled_time_str)

        # Convert to user's timezone
        local_time = dt.astimezone(USER_TIMEZONE)

        # Format time and date
        time_str = local_time.strftime("%I:%M %p").lstrip("0")  # "10:00 AM"

        # Add ordinal suffix to day
        day = local_time.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1] if day % 10 <= 3 else "th"

        date_str = local_time.strftime(f"%A, %B {day}{suffix}")  # "Monday, February 3rd"

        return f"{date_str} at {time_str}"

    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to format time '{scheduled_time_str}': {e}")
        return scheduled_time_str


def format_reminder_type(reminder_type: str) -> str:
    """Format reminder type for display."""
    type_map = {
        "sms": "SMS",
        "email": "Email",
        "slack": "Slack",
        "calendar_event": "Calendar",
    }
    return type_map.get(reminder_type, reminder_type.title())


def format_repeat_pattern(repeat_pattern: Optional[str]) -> str:
    """Format repeat pattern for display."""
    if not repeat_pattern:
        return ""

    pattern_map = {
        "daily": "Repeats daily",
        "weekly": "Repeats weekly",
        "monthly": "Repeats monthly",
        "yearly": "Repeats yearly",
    }
    return pattern_map.get(repeat_pattern, f"Repeats {repeat_pattern}")


def format_reminder_list(reminders: List[Dict[str, Any]]) -> str:
    """
    Format a list of reminders for conversational display.

    Args:
        reminders: List of reminder dictionaries from the database

    Returns:
        Formatted string for user-friendly display
    """
    if not reminders:
        return "You don't have any active reminders."

    count = len(reminders)
    plural = "s" if count != 1 else ""
    lines = [f"You have {count} active reminder{plural}:\n"]

    for i, reminder in enumerate(reminders, 1):
        title = reminder.get("title", "Untitled")
        scheduled_time = reminder.get("scheduled_time", "")
        reminder_type = reminder.get("reminder_type", "sms")
        repeat_pattern = reminder.get("repeat_pattern")
        reminder_id = reminder.get("id", "")[:8]  # Short ID for reference

        # Format the time
        time_display = format_reminder_time(scheduled_time)

        # Format the type
        type_display = format_reminder_type(reminder_type)

        # Build the reminder line
        line = f"{i}. **{title}**"
        line += f"\n   {time_display} via {type_display}"

        # Add repeat pattern if present
        if repeat_pattern:
            line += f"\n   {format_repeat_pattern(repeat_pattern)}"

        # Add short ID for reference
        line += f"\n   (ID: {reminder_id}...)"

        lines.append(line)

    return "\n\n".join(lines)


async def execute(params: dict) -> dict:
    """
    List active reminders for the user.

    Args:
        params: Dict with:
            - limit (optional): Maximum reminders to return (default: 20)
            - include_completed (optional): Include completed reminders (default: false)

    Returns:
        Dict with:
            - status: "success" or "error"
            - message: Formatted reminder list or error message
            - reminders: List of reminder data (on success)
            - count: Number of reminders returned
    """
    # Import here to avoid circular imports
    from backend.services.reminder_service import get_reminder_service

    # Extract parameters
    limit = params.get("limit", 20)
    include_completed = params.get("include_completed", False)

    logger.info(f"list_reminders called: limit={limit}, include_completed={include_completed}")

    # Validate limit
    if not isinstance(limit, int) or limit < 1:
        limit = 20
    if limit > 100:
        limit = 100

    # Get user ID
    try:
        user_id = UUID(DEFAULT_USER_ID)
    except (ValueError, TypeError):
        logger.error(f"Invalid DEFAULT_USER_ID: {DEFAULT_USER_ID}")
        return {
            "status": "error",
            "message": "Configuration error: Invalid user ID. Please contact support.",
        }

    # Get reminder service
    service = get_reminder_service()

    # List reminders
    result = await service.list_active_reminders(user_id=user_id, limit=limit)

    if not result.success:
        error_msg = result.error.message if result.error else "Unknown error"
        logger.error(f"Failed to list reminders: {error_msg}")
        return {
            "status": "error",
            "message": f"I couldn't retrieve your reminders: {error_msg}",
        }

    # Get reminders from result
    reminders = result.data.get("reminders", [])
    count = result.data.get("count", 0)

    # Filter out completed if not requested
    if not include_completed:
        reminders = [r for r in reminders if not r.get("is_completed", False)]

    # Format the response
    formatted_message = format_reminder_list(reminders)

    logger.info(f"Returning {len(reminders)} reminders for user {user_id}")

    return {
        "status": "success",
        "message": formatted_message,
        "reminders": reminders,
        "count": len(reminders),
    }
