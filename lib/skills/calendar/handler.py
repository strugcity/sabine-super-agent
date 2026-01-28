"""
Google Calendar Skill Handler

Retrieves calendar events using Google Calendar API with OAuth2 refresh tokens.
Uses the same credential architecture as the Gmail handler (USER_REFRESH_TOKEN).
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Google Calendar API endpoint
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Token endpoint for refreshing access tokens
TOKEN_URL = "https://oauth2.googleapis.com/token"


async def get_access_token() -> Optional[str]:
    """
    Get a fresh access token using the USER_REFRESH_TOKEN.

    Uses the user's refresh token since we want to read the user's calendars,
    not Sabine's calendar.
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


def get_time_range(time_range: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> tuple:
    """
    Calculate start and end datetime based on time_range parameter.

    Returns:
        Tuple of (start_datetime, end_datetime) in ISO format
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_range == "today":
        start = today_start
        end = today_start + timedelta(days=1)
    elif time_range == "tomorrow":
        start = today_start + timedelta(days=1)
        end = today_start + timedelta(days=2)
    elif time_range == "this_week":
        # Start from today, end at end of week (Sunday)
        start = today_start
        days_until_sunday = 6 - now.weekday()  # weekday() returns 0-6 (Mon-Sun)
        end = today_start + timedelta(days=days_until_sunday + 1)
    elif time_range == "next_week":
        # Start from next Monday
        days_until_monday = 7 - now.weekday() if now.weekday() != 0 else 7
        start = today_start + timedelta(days=days_until_monday)
        end = start + timedelta(days=7)
    elif time_range == "custom" and start_date and end_date:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date) + timedelta(days=1)  # Include end date
    else:
        # Default to today
        start = today_start
        end = today_start + timedelta(days=1)

    # Format as RFC3339
    return (
        start.isoformat() + "Z",
        end.isoformat() + "Z"
    )


async def list_calendars(access_token: str) -> List[Dict[str, Any]]:
    """
    List all calendars the user has access to.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CALENDAR_API_BASE}/users/me/calendarList",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("items", [])
            else:
                logger.error(f"Failed to list calendars: {response.status_code}")
                return []

    except Exception as e:
        logger.error(f"Error listing calendars: {e}")
        return []


async def get_events(
    access_token: str,
    calendar_id: str,
    time_min: str,
    time_max: str,
    max_results: int = 10
) -> List[Dict[str, Any]]:
    """
    Get events from a specific calendar.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "maxResults": max_results,
                    "singleEvents": "true",
                    "orderBy": "startTime"
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("items", [])
            else:
                logger.error(f"Failed to get events from {calendar_id}: {response.status_code}")
                return []

    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return []


def format_event(event: Dict[str, Any]) -> str:
    """
    Format a calendar event for display.
    """
    summary = event.get("summary", "No Title")

    # Handle all-day events vs timed events
    start = event.get("start", {})
    end = event.get("end", {})

    if "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
        time_str = f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}"
        date_str = start_dt.strftime('%A, %B %d')
    else:
        # All-day event
        date_str = start.get("date", "Unknown date")
        time_str = "All day"

    location = event.get("location", "")
    location_str = f"\n   Location: {location}" if location else ""

    description = event.get("description", "")
    desc_preview = description[:100] + "..." if len(description) > 100 else description
    desc_str = f"\n   Notes: {desc_preview}" if desc_preview else ""

    return f"- {summary}\n   {date_str}, {time_str}{location_str}{desc_str}"


async def execute(params: dict) -> dict:
    """
    Get calendar events based on the specified time range.

    Args:
        params: Dict with 'time_range' (required), 'start_date', 'end_date', 'max_results'

    Returns:
        Dict with calendar events or error message
    """
    time_range = params.get("time_range", "today")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    max_results = params.get("max_results", 10)

    logger.info(f"Getting calendar events for time_range={time_range}")

    # Get access token
    access_token = await get_access_token()
    if not access_token:
        return {
            "status": "error",
            "message": "Failed to authenticate with Google Calendar. Please check credentials."
        }

    # Calculate time range
    time_min, time_max = get_time_range(time_range, start_date, end_date)
    logger.info(f"Time range: {time_min} to {time_max}")

    # Get list of calendars
    calendars = await list_calendars(access_token)
    if not calendars:
        return {
            "status": "error",
            "message": "No calendars found or unable to access calendars."
        }

    # Collect events from all calendars
    all_events = []
    calendar_names = []

    for calendar in calendars:
        calendar_id = calendar.get("id")
        calendar_name = calendar.get("summary", "Unknown")

        # Skip calendars that are hidden or not selected
        if not calendar.get("selected", True):
            continue

        events = await get_events(access_token, calendar_id, time_min, time_max, max_results)

        if events:
            calendar_names.append(calendar_name)
            for event in events:
                event["_calendar_name"] = calendar_name
                all_events.append(event)

    # Sort all events by start time
    def get_start_time(event):
        start = event.get("start", {})
        if "dateTime" in start:
            return start["dateTime"]
        return start.get("date", "")

    all_events.sort(key=get_start_time)

    # Limit total results
    all_events = all_events[:max_results]

    if not all_events:
        range_desc = {
            "today": "today",
            "tomorrow": "tomorrow",
            "this_week": "this week",
            "next_week": "next week",
            "custom": f"from {start_date} to {end_date}"
        }.get(time_range, time_range)

        return {
            "status": "success",
            "message": f"No events scheduled for {range_desc}.",
            "events": [],
            "calendars_checked": calendar_names
        }

    # Format events for display
    formatted_events = []
    for event in all_events:
        formatted = format_event(event)
        calendar_name = event.get("_calendar_name", "")
        if calendar_name and len(calendar_names) > 1:
            formatted = f"[{calendar_name}] {formatted}"
        formatted_events.append(formatted)

    range_desc = {
        "today": "Today's",
        "tomorrow": "Tomorrow's",
        "this_week": "This week's",
        "next_week": "Next week's",
        "custom": "Scheduled"
    }.get(time_range, "Upcoming")

    return {
        "status": "success",
        "message": f"{range_desc} calendar events ({len(all_events)} found):\n\n" + "\n\n".join(formatted_events),
        "events": [
            {
                "summary": e.get("summary"),
                "start": e.get("start"),
                "end": e.get("end"),
                "location": e.get("location"),
                "calendar": e.get("_calendar_name")
            }
            for e in all_events
        ],
        "calendars_checked": calendar_names
    }
