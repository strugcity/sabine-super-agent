"""
Create Calendar Event Skill Handler - Phase 4.1
===============================================

Creates Google Calendar events with optional reminders.
Supports hybrid approach: calendar event + optional SMS reminder.

BDD Specification:
    Feature: Calendar Event Reminders

      Scenario: Create event with default reminder
        Given I say "add a dentist appointment tomorrow at 2 PM"
        When Sabine creates the calendar event
        Then a Google Calendar event should be created
        And it should have a 15-minute popup reminder by default
        And Sabine should confirm the event was created

      Scenario: Create event with custom reminder
        Given I say "add a meeting tomorrow at 3 PM and remind me 1 hour before"
        When Sabine creates the calendar event
        Then the event should have a 60-minute reminder
        And the reminder method should be notification/popup

      Scenario: Create event with SMS reminder (hybrid)
        Given I say "add a flight tomorrow at 6 AM and text me 2 hours before"
        When Sabine creates the event
        Then a Google Calendar event should be created
        AND a separate SMS reminder should be scheduled for 4 AM

      Scenario: Create all-day event
        Given I say "add Jack's birthday on February 15"
        When Sabine creates the event
        Then an all-day event should be created
        And no specific time should be set

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 4.1
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
import pytz

logger = logging.getLogger(__name__)

# User's timezone - US Central
USER_TIMEZONE = pytz.timezone("America/Chicago")

# Google Calendar API endpoint
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Token endpoint for refreshing access tokens
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Default user ID for creating SMS reminders
_env_user_id = os.getenv("DEFAULT_USER_ID", "")
if not _env_user_id or _env_user_id.startswith("00000000"):
    DEFAULT_USER_ID = "75abac49-2b45-44ab-a57d-8ca6ecad2b8c"
else:
    DEFAULT_USER_ID = _env_user_id


async def get_access_token() -> Optional[str]:
    """
    Get a fresh access token using the USER_REFRESH_TOKEN.

    Uses the user's refresh token since we want to write to the user's calendars.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.getenv("USER_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        logger.error("Missing Google OAuth credentials for calendar")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("access_token")
            else:
                logger.error(f"Failed to refresh token: {response.status_code} - {response.text}")
                return None

    except Exception as e:
        logger.error(f"Error refreshing access token: {e}")
        return None


def parse_datetime(time_str: str) -> Optional[datetime]:
    """
    Parse a datetime string into a timezone-aware datetime.

    Handles:
    - ISO format: 2026-02-03T14:00:00
    - ISO with timezone: 2026-02-03T14:00:00-06:00
    - Date only: 2026-02-03

    Returns:
        Timezone-aware datetime in user's timezone, or None if parse fails
    """
    if not time_str:
        return None

    try:
        # Try ISO format with timezone
        if "+" in time_str or time_str.endswith("Z"):
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return dt.astimezone(USER_TIMEZONE)

        # Try ISO format without timezone
        if "T" in time_str:
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = USER_TIMEZONE.localize(dt)
            return dt

        # Try date only
        dt = datetime.strptime(time_str, "%Y-%m-%d")
        dt = USER_TIMEZONE.localize(dt)
        return dt

    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse datetime '{time_str}': {e}")
        return None


def format_time_for_display(dt: datetime) -> str:
    """Format datetime for user-friendly display."""
    local_dt = dt.astimezone(USER_TIMEZONE)
    return local_dt.strftime("%A, %B %d at %I:%M %p")


def format_date_for_display(date_str: str) -> str:
    """Format date string for user-friendly display."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A, %B %d")
    except ValueError:
        return date_str


async def create_google_calendar_event(
    access_token: str,
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: Optional[str] = None,
    location: Optional[str] = None,
    reminder_minutes: int = 15,
    all_day: bool = False,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """
    Create an event in Google Calendar.

    Args:
        access_token: OAuth access token
        title: Event title/summary
        start_time: Event start datetime
        end_time: Event end datetime
        description: Optional event description
        location: Optional event location
        reminder_minutes: Minutes before event for reminder (0 = no reminder)
        all_day: If True, create all-day event
        calendar_id: Calendar to add event to (default: primary)

    Returns:
        Dict with event details or error
    """
    # Build event body
    event_body: Dict[str, Any] = {
        "summary": title,
    }

    if description:
        event_body["description"] = description

    if location:
        event_body["location"] = location

    # Set start/end times
    if all_day:
        # All-day events use date (not dateTime)
        event_body["start"] = {"date": start_time.strftime("%Y-%m-%d")}
        event_body["end"] = {"date": end_time.strftime("%Y-%m-%d")}
    else:
        # Timed events use dateTime with timezone
        event_body["start"] = {
            "dateTime": start_time.isoformat(),
            "timeZone": str(USER_TIMEZONE),
        }
        event_body["end"] = {
            "dateTime": end_time.isoformat(),
            "timeZone": str(USER_TIMEZONE),
        }

    # Add reminder if specified
    if reminder_minutes > 0:
        event_body["reminders"] = {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": reminder_minutes},
            ],
        }
    else:
        event_body["reminders"] = {"useDefault": False, "overrides": []}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=event_body,
            )

            if response.status_code in (200, 201):
                event_data = response.json()
                return {
                    "success": True,
                    "event_id": event_data.get("id"),
                    "html_link": event_data.get("htmlLink"),
                    "event": event_data,
                }
            else:
                error_text = response.text
                logger.error(f"Failed to create event: {response.status_code} - {error_text}")
                return {
                    "success": False,
                    "error": f"Google Calendar API error: {response.status_code}",
                    "details": error_text,
                }

    except Exception as e:
        logger.error(f"Error creating calendar event: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def create_sms_reminder_for_event(
    event_title: str,
    event_time: datetime,
    reminder_minutes: int,
) -> Dict[str, Any]:
    """
    Create an SMS reminder for a calendar event.

    This creates a reminder in our reminder system that will send
    an SMS notification before the event.

    Args:
        event_title: Title of the event
        event_time: When the event starts
        reminder_minutes: How many minutes before to send SMS

    Returns:
        Dict with reminder creation result
    """
    from backend.services.reminder_service import get_reminder_service

    # Calculate SMS reminder time
    sms_time = event_time - timedelta(minutes=reminder_minutes)

    # Don't create reminders in the past
    now = datetime.now(USER_TIMEZONE)
    if sms_time <= now:
        logger.warning(f"SMS reminder time {sms_time} is in the past, skipping")
        return {
            "success": False,
            "error": "SMS reminder time would be in the past",
        }

    try:
        user_id = UUID(DEFAULT_USER_ID)
    except (ValueError, TypeError):
        logger.error(f"Invalid DEFAULT_USER_ID: {DEFAULT_USER_ID}")
        return {"success": False, "error": "Invalid user configuration"}

    service = get_reminder_service()

    # Create the reminder
    result = await service.create_reminder(
        user_id=user_id,
        title=f"Upcoming: {event_title}",
        description=f"Your event '{event_title}' starts in {reminder_minutes} minutes.",
        reminder_type="sms",
        scheduled_time=sms_time,
        repeat_pattern=None,
        notification_channels={"sms": True},
        metadata={
            "source": "calendar_event",
            "event_title": event_title,
            "event_time": event_time.isoformat(),
        },
    )

    if result.success:
        reminder_data = result.data.get("reminder", {})
        reminder_id = reminder_data.get("id")

        # Schedule the reminder job
        try:
            from lib.agent.reminder_scheduler import get_reminder_scheduler

            scheduler = get_reminder_scheduler()
            if scheduler.is_running():
                await scheduler.add_reminder_job(
                    reminder_id=UUID(reminder_id),
                    scheduled_time=sms_time,
                    repeat_pattern=None,
                    title=f"Upcoming: {event_title}",
                )
        except Exception as e:
            logger.warning(f"Could not schedule SMS reminder job: {e}")

        return {
            "success": True,
            "reminder_id": reminder_id,
            "scheduled_for": sms_time.isoformat(),
        }
    else:
        error_msg = result.error.message if result.error else "Unknown error"
        return {"success": False, "error": error_msg}


async def execute(params: dict) -> dict:
    """
    Create a Google Calendar event with optional reminders.

    Args:
        params: Dict with:
            - title (required): Event title
            - start_time (required): Start time (ISO format or parseable string)
            - end_time (optional): End time (defaults to 1 hour after start)
            - description (optional): Event description
            - location (optional): Event location
            - reminder_minutes (optional): Minutes before for popup reminder (default: 15)
            - all_day (optional): Create all-day event (default: False)
            - calendar_id (optional): Which calendar to use (default: primary)
            - also_sms_reminder (optional): Also send SMS reminder (default: False)
            - sms_reminder_minutes (optional): Minutes before for SMS (default: 60)

    Returns:
        Dict with:
            - status: "success" or "error"
            - message: User-friendly confirmation or error
            - event_id: Google Calendar event ID
            - event_link: Link to view event in Google Calendar
            - sms_reminder: Details if SMS reminder was also created
    """
    # Extract parameters
    title = params.get("title", "").strip()
    start_time_str = params.get("start_time", "")
    end_time_str = params.get("end_time", "")
    description = params.get("description", "")
    location = params.get("location", "")
    reminder_minutes = params.get("reminder_minutes", 15)
    all_day = params.get("all_day", False)
    calendar_id = params.get("calendar_id", "primary")
    also_sms_reminder = params.get("also_sms_reminder", False)
    sms_reminder_minutes = params.get("sms_reminder_minutes", 60)

    logger.info(
        f"create_calendar_event called: title='{title}', start='{start_time_str}', "
        f"all_day={all_day}, sms={also_sms_reminder}"
    )

    # Validate required fields
    if not title:
        return {
            "status": "error",
            "message": "I need a title for the event. What would you like to call it?",
        }

    if not start_time_str:
        return {
            "status": "error",
            "message": "I need a start time for the event. When should it be scheduled?",
        }

    # Parse start time
    start_time = parse_datetime(start_time_str)
    if not start_time:
        return {
            "status": "error",
            "message": (
                f"I couldn't understand the time '{start_time_str}'. "
                "Please use a format like '2026-02-03T14:00:00' or 'YYYY-MM-DD'."
            ),
        }

    # Parse or calculate end time
    if end_time_str:
        end_time = parse_datetime(end_time_str)
        if not end_time:
            # Default to 1 hour after start
            end_time = start_time + timedelta(hours=1)
    else:
        if all_day:
            # All-day events: end is next day
            end_time = start_time + timedelta(days=1)
        else:
            # Default: 1 hour duration
            end_time = start_time + timedelta(hours=1)

    # Validate times are in the future (for non-all-day events)
    now = datetime.now(USER_TIMEZONE)
    if not all_day and start_time <= now:
        return {
            "status": "error",
            "message": (
                f"The start time ({format_time_for_display(start_time)}) is in the past. "
                "Please provide a future time."
            ),
        }

    # Get access token
    access_token = await get_access_token()
    if not access_token:
        return {
            "status": "error",
            "message": (
                "I couldn't connect to Google Calendar. "
                "Please check that the calendar credentials are configured."
            ),
        }

    # Create the calendar event
    result = await create_google_calendar_event(
        access_token=access_token,
        title=title,
        start_time=start_time,
        end_time=end_time,
        description=description,
        location=location,
        reminder_minutes=reminder_minutes,
        all_day=all_day,
        calendar_id=calendar_id,
    )

    if not result.get("success"):
        error = result.get("error", "Unknown error")
        return {
            "status": "error",
            "message": f"I couldn't create the calendar event: {error}",
        }

    event_id = result.get("event_id")
    event_link = result.get("html_link")

    # Build confirmation message
    if all_day:
        time_display = format_date_for_display(start_time.strftime("%Y-%m-%d"))
        confirmation = f"I've added '{title}' to your calendar for {time_display} (all day)."
    else:
        time_display = format_time_for_display(start_time)
        confirmation = f"I've added '{title}' to your calendar for {time_display}."

    if reminder_minutes > 0:
        if reminder_minutes >= 60:
            hours = reminder_minutes // 60
            mins = reminder_minutes % 60
            if mins > 0:
                reminder_str = f"{hours} hour{'s' if hours > 1 else ''} and {mins} minute{'s' if mins > 1 else ''}"
            else:
                reminder_str = f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            reminder_str = f"{reminder_minutes} minute{'s' if reminder_minutes > 1 else ''}"
        confirmation += f" You'll get a reminder {reminder_str} before."

    # Create SMS reminder if requested
    sms_result = None
    if also_sms_reminder and not all_day:
        sms_result = await create_sms_reminder_for_event(
            event_title=title,
            event_time=start_time,
            reminder_minutes=sms_reminder_minutes,
        )

        if sms_result.get("success"):
            if sms_reminder_minutes >= 60:
                hours = sms_reminder_minutes // 60
                mins = sms_reminder_minutes % 60
                if mins > 0:
                    sms_str = f"{hours} hour{'s' if hours > 1 else ''} and {mins} minute{'s' if mins > 1 else ''}"
                else:
                    sms_str = f"{hours} hour{'s' if hours > 1 else ''}"
            else:
                sms_str = f"{sms_reminder_minutes} minute{'s' if sms_reminder_minutes > 1 else ''}"
            confirmation += f" I'll also text you {sms_str} before."
        else:
            confirmation += " (Note: I couldn't set up the SMS reminder.)"

    return {
        "status": "success",
        "message": confirmation,
        "event_id": event_id,
        "event_link": event_link,
        "event_details": {
            "title": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "all_day": all_day,
            "reminder_minutes": reminder_minutes,
            "location": location or None,
        },
        "sms_reminder": sms_result if also_sms_reminder else None,
    }
