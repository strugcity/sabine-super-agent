"""
Cancel Reminder Skill Handler - Step 2.5
========================================

Cancels reminders by ID or by searching for them by title.
Supports fuzzy title matching and handles ambiguous requests.

BDD Specification:
    Feature: Cancel Reminder

      Scenario: Cancel by description
        Given I have a reminder "Pick up glasses" at 10 AM
        When I say "cancel the glasses reminder"
        Then Sabine should find the matching reminder
        And set is_active = FALSE
        And confirm "I've cancelled the reminder about picking up glasses"

      Scenario: Cancel by exact ID
        Given I have a reminder with ID "12345678-..."
        When I provide the exact reminder_id
        Then the reminder should be cancelled immediately
        And confirm with the reminder title

      Scenario: Ambiguous cancellation
        Given I have two reminders containing "meeting"
        When I say "cancel the meeting reminder"
        Then Sabine should list both and ask which one to cancel

      Scenario: Cancel non-existent reminder
        When I say "cancel my dentist reminder"
        And no such reminder exists
        Then Sabine should say "I couldn't find a reminder about that"

      Scenario: Cancel all matching
        Given I have two reminders containing "meeting"
        And confirm_multiple is True
        When I say "cancel all meeting reminders"
        Then both reminders should be cancelled

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 2.4 (Cancel Reminder)
"""

import logging
import os
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


def format_reminder_for_display(reminder: Dict[str, Any]) -> str:
    """
    Format a reminder for display in confirmation or listing.

    Args:
        reminder: Reminder dictionary from database

    Returns:
        Formatted string like "'Pick up glasses' scheduled for Monday at 10:00 AM"
    """
    from datetime import datetime

    title = reminder.get("title", "Untitled")
    scheduled_time_str = reminder.get("scheduled_time", "")

    try:
        if scheduled_time_str.endswith('Z'):
            dt = datetime.fromisoformat(scheduled_time_str[:-1] + '+00:00')
        else:
            dt = datetime.fromisoformat(scheduled_time_str)

        local_time = dt.astimezone(USER_TIMEZONE)
        time_str = local_time.strftime("%I:%M %p").lstrip("0")
        day_str = local_time.strftime("%A")
        return f"'{title}' scheduled for {day_str} at {time_str}"
    except (ValueError, TypeError):
        return f"'{title}'"


def format_ambiguous_matches(reminders: List[Dict[str, Any]]) -> str:
    """
    Format multiple matching reminders for disambiguation.

    Args:
        reminders: List of matching reminders

    Returns:
        Formatted message asking user to clarify
    """
    lines = [
        f"I found {len(reminders)} reminders matching that description. "
        "Which one would you like to cancel?\n"
    ]

    for i, reminder in enumerate(reminders, 1):
        reminder_id = reminder.get("id", "")[:8]
        formatted = format_reminder_for_display(reminder)
        lines.append(f"{i}. {formatted} (ID: {reminder_id}...)")

    lines.append(
        "\nYou can specify the reminder ID, or say something like "
        "'cancel the first one' or 'cancel all of them'."
    )

    return "\n".join(lines)


async def execute(params: dict) -> dict:
    """
    Cancel a reminder by ID or search term.

    Args:
        params: Dict with:
            - reminder_id (optional): Exact UUID of reminder to cancel
            - search_term (optional): Title search term for fuzzy matching
            - confirm_multiple (optional): If True, cancel all matches

    Returns:
        Dict with:
            - status: "success", "error", or "ambiguous"
            - message: User-friendly confirmation or error
            - cancelled_count: Number of reminders cancelled (on success)
            - matches: List of matching reminders (if ambiguous)
    """
    # Import here to avoid circular imports
    from backend.services.reminder_service import get_reminder_service

    # Extract parameters
    reminder_id = params.get("reminder_id")
    search_term = params.get("search_term")
    confirm_multiple = params.get("confirm_multiple", False)

    logger.info(
        f"cancel_reminder called: id={reminder_id}, search='{search_term}', "
        f"confirm_multiple={confirm_multiple}"
    )

    # Validate input - need at least one of reminder_id or search_term
    if not reminder_id and not search_term:
        return {
            "status": "error",
            "message": (
                "I need either a reminder ID or a description to find the reminder. "
                "You can say something like 'cancel the glasses reminder' or provide "
                "the reminder ID from the list."
            ),
        }

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

    # =========================================================================
    # Cancel by exact ID
    # =========================================================================
    if reminder_id:
        try:
            rid = UUID(reminder_id)
        except (ValueError, TypeError):
            return {
                "status": "error",
                "message": (
                    f"'{reminder_id}' doesn't look like a valid reminder ID. "
                    "Reminder IDs are UUIDs like '12345678-1234-1234-1234-123456789012'."
                ),
            }

        # First, get the reminder to show what we're cancelling
        get_result = await service.get_reminder(rid)
        if not get_result.success:
            return {
                "status": "error",
                "message": f"I couldn't find a reminder with ID '{reminder_id[:8]}...'. "
                "It may have already been cancelled or doesn't exist.",
            }

        reminder = get_result.data.get("reminder", {})
        title = reminder.get("title", "Untitled")

        # Cancel the reminder
        cancel_result = await service.cancel_reminder(rid)
        if not cancel_result.success:
            error_msg = cancel_result.error.message if cancel_result.error else "Unknown error"
            return {
                "status": "error",
                "message": f"I couldn't cancel the reminder: {error_msg}",
            }

        return {
            "status": "success",
            "message": f"I've cancelled the reminder about '{title}'.",
            "cancelled_count": 1,
            "cancelled_ids": [str(rid)],
        }

    # =========================================================================
    # Cancel by search term
    # =========================================================================
    search_result = await service.search_reminders_by_title(
        user_id=user_id,
        search_term=search_term,
        active_only=True,
        limit=10,
    )

    if not search_result.success:
        error_msg = search_result.error.message if search_result.error else "Unknown error"
        return {
            "status": "error",
            "message": f"I couldn't search for reminders: {error_msg}",
        }

    matches = search_result.data.get("reminders", [])
    match_count = len(matches)

    # No matches found
    if match_count == 0:
        return {
            "status": "error",
            "message": (
                f"I couldn't find any active reminders matching '{search_term}'. "
                "You can use 'list_reminders' to see all your reminders."
            ),
        }

    # Single match - cancel it
    if match_count == 1:
        reminder = matches[0]
        rid = UUID(reminder["id"])
        title = reminder.get("title", "Untitled")

        cancel_result = await service.cancel_reminder(rid)
        if not cancel_result.success:
            error_msg = cancel_result.error.message if cancel_result.error else "Unknown error"
            return {
                "status": "error",
                "message": f"I couldn't cancel the reminder: {error_msg}",
            }

        return {
            "status": "success",
            "message": f"I've cancelled the reminder about '{title}'.",
            "cancelled_count": 1,
            "cancelled_ids": [str(rid)],
        }

    # Multiple matches
    if not confirm_multiple:
        # Ask for clarification
        return {
            "status": "ambiguous",
            "message": format_ambiguous_matches(matches),
            "matches": matches,
            "match_count": match_count,
        }

    # Cancel all matches
    cancelled_ids = []
    cancelled_titles = []
    errors = []

    for reminder in matches:
        rid = UUID(reminder["id"])
        title = reminder.get("title", "Untitled")

        cancel_result = await service.cancel_reminder(rid)
        if cancel_result.success:
            cancelled_ids.append(str(rid))
            cancelled_titles.append(title)
        else:
            errors.append(f"Failed to cancel '{title}'")

    if cancelled_ids:
        if len(cancelled_ids) == 1:
            message = f"I've cancelled the reminder about '{cancelled_titles[0]}'."
        else:
            titles = ", ".join(f"'{t}'" for t in cancelled_titles)
            message = f"I've cancelled {len(cancelled_ids)} reminders: {titles}."

        if errors:
            message += f" (Note: {len(errors)} reminder(s) couldn't be cancelled)"

        return {
            "status": "success",
            "message": message,
            "cancelled_count": len(cancelled_ids),
            "cancelled_ids": cancelled_ids,
        }
    else:
        return {
            "status": "error",
            "message": "I couldn't cancel any of the matching reminders. Please try again.",
        }
