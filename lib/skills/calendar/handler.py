"""
Google Calendar Skill Handler

Retrieves calendar events using Google Calendar API with OAuth2 refresh tokens.
Uses the same credential architecture as the Gmail handler (USER_REFRESH_TOKEN).

Enhanced for family use cases:
- Custody schedule awareness (Mom/Dad all-day events)
- Multi-kid sports calendar aggregation
- Conflict detection across family members
- "Who has what" queries
"""

import os
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytz

logger = logging.getLogger(__name__)

# User's timezone - US Central
USER_TIMEZONE = pytz.timezone("America/Chicago")

# Family member detection patterns (customize per family)
FAMILY_MEMBERS = {
    "jack": ["jack", "jacks"],
    "anna": ["anna", "annas", "annalee"],
    # Add more kids here as needed
}

# Sports calendar patterns - helps identify which calendars are sports-related
SPORTS_CALENDAR_PATTERNS = [
    r"bandits", r"blast", r"red", r"team", r"schuer",
    r"gamechange", r"sports?engine", r"teamsnap",
    r"\d+[au]",  # Age groups like 12U, 14A
]

# Custody calendar name
CUSTODY_CALENDAR_NAME = "The Kids"
CUSTODY_PATTERNS = ["mom", "dad", "mother", "father"]

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

    IMPORTANT: Uses user's timezone (Central) for all calculations to ensure
    "today", "this weekend", etc. are correct regardless of server timezone.

    Returns:
        Tuple of (start_datetime, end_datetime) in ISO format with timezone
    """
    # Get current time in user's timezone (Central), NOT server time
    now = datetime.now(USER_TIMEZONE)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info(f"Time range calculation: now={now.strftime('%Y-%m-%d %H:%M %Z')}, weekday={now.weekday()} (0=Mon, 6=Sun)")

    if time_range == "today":
        start = today_start
        end = today_start + timedelta(days=1)
    elif time_range == "tomorrow":
        start = today_start + timedelta(days=1)
        end = today_start + timedelta(days=2)
    elif time_range == "this_weekend":
        # Saturday and Sunday of THIS week
        # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday == 0 and now.weekday() == 5:
            # It's Saturday, start today
            days_until_saturday = 0
        elif now.weekday() == 6:
            # It's Sunday, just show today
            days_until_saturday = -1  # Go back to yesterday (Saturday)
        start = today_start + timedelta(days=days_until_saturday)
        end = start + timedelta(days=2)  # Saturday + Sunday
        logger.info(f"this_weekend: days_until_saturday={days_until_saturday}, start={start.strftime('%Y-%m-%d')}, end={end.strftime('%Y-%m-%d')}")
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
    elif time_range == "next_weekend":
        # Saturday and Sunday of NEXT week
        days_until_saturday = (5 - now.weekday()) % 7
        if days_until_saturday <= 1:  # If it's Fri, Sat, or Sun, go to next week's Saturday
            days_until_saturday += 7
        start = today_start + timedelta(days=days_until_saturday)
        end = start + timedelta(days=2)
    elif time_range == "custom" and start_date and end_date:
        start = datetime.fromisoformat(start_date)
        if start.tzinfo is None:
            start = USER_TIMEZONE.localize(start)
        end = datetime.fromisoformat(end_date) + timedelta(days=1)  # Include end date
        if end.tzinfo is None:
            end = USER_TIMEZONE.localize(end)
    else:
        # Default to today
        start = today_start
        end = today_start + timedelta(days=1)

    # Format as RFC3339 with timezone offset (not naive Z suffix)
    return (
        start.isoformat(),
        end.isoformat()
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


def is_custody_event(event: Dict[str, Any], calendar_name: str = "") -> Tuple[bool, str]:
    """
    Check if an event is a custody indicator (Mom/Dad all-day event).

    Returns:
        Tuple of (is_custody, parent_name) e.g., (True, "Mom") or (False, "")
    """
    summary = event.get("summary", "").lower().strip()
    start = event.get("start", {})

    # Must be from "The Kids" calendar (or similar) and be an all-day event
    is_custody_calendar = CUSTODY_CALENDAR_NAME.lower() in calendar_name.lower()
    is_all_day = "date" in start and "dateTime" not in start

    if is_custody_calendar and is_all_day:
        for pattern in CUSTODY_PATTERNS:
            if pattern in summary:
                # Capitalize nicely
                parent = "Mom" if "mom" in summary or "mother" in summary else "Dad"
                return (True, parent)

    return (False, "")


def is_sports_calendar(calendar_name: str) -> bool:
    """Check if a calendar is likely a sports team calendar."""
    name_lower = calendar_name.lower()
    for pattern in SPORTS_CALENDAR_PATTERNS:
        if re.search(pattern, name_lower):
            return True
    return False


def detect_family_member(event: Dict[str, Any], calendar_name: str) -> Optional[str]:
    """
    Try to detect which family member an event is for.

    Checks event summary and calendar name for family member names.
    """
    text_to_check = f"{event.get('summary', '')} {calendar_name}".lower()

    for member, patterns in FAMILY_MEMBERS.items():
        for pattern in patterns:
            if pattern in text_to_check:
                return member.capitalize()

    return None


def find_conflicts(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Find scheduling conflicts (overlapping events).

    Returns list of conflict groups, where each group contains overlapping events.
    """
    conflicts = []

    # Only check timed events (not all-day)
    timed_events = [e for e in events if "dateTime" in e.get("start", {})]

    for i, event1 in enumerate(timed_events):
        for event2 in timed_events[i+1:]:
            start1 = datetime.fromisoformat(event1["start"]["dateTime"].replace("Z", "+00:00"))
            end1 = datetime.fromisoformat(event1["end"]["dateTime"].replace("Z", "+00:00"))
            start2 = datetime.fromisoformat(event2["start"]["dateTime"].replace("Z", "+00:00"))
            end2 = datetime.fromisoformat(event2["end"]["dateTime"].replace("Z", "+00:00"))

            # Check for overlap
            if start1 < end2 and start2 < end1:
                conflicts.append({
                    "event1": event1,
                    "event2": event2,
                    "overlap_start": max(start1, start2),
                    "overlap_end": min(end1, end2)
                })

    return conflicts


def format_event(event: Dict[str, Any], include_member: bool = True) -> str:
    """
    Format a calendar event for display.
    """
    summary = event.get("summary", "No Title")
    calendar_name = event.get("_calendar_name", "")

    # Check for custody event
    is_custody, parent = is_custody_event(event, calendar_name)
    if is_custody:
        date_str = event.get("start", {}).get("date", "Unknown date")
        return f"🏠 {parent}'s day ({date_str})"

    # Detect family member
    member = detect_family_member(event, calendar_name) if include_member else None
    member_prefix = f"[{member}] " if member else ""

    # Handle all-day events vs timed events
    start = event.get("start", {})
    end = event.get("end", {})

    if "dateTime" in start:
        # Parse datetime and convert to user's timezone (Central)
        start_dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))

        # Convert to Central time
        start_local = start_dt.astimezone(USER_TIMEZONE)
        end_local = end_dt.astimezone(USER_TIMEZONE)

        time_str = f"{start_local.strftime('%I:%M %p')} - {end_local.strftime('%I:%M %p')}"
        date_str = start_local.strftime('%A, %B %d')
    else:
        # All-day event
        date_str = start.get("date", "Unknown date")
        time_str = "All day"

    location = event.get("location", "")
    location_str = f"\n   📍 {location}" if location else ""

    description = event.get("description", "")
    desc_preview = description[:100] + "..." if len(description) > 100 else description
    desc_str = f"\n   📝 {desc_preview}" if desc_preview else ""

    # Add sports emoji if it's a sports calendar
    sports_emoji = "⚽ " if is_sports_calendar(calendar_name) else ""

    return f"- {member_prefix}{sports_emoji}{summary}\n   {date_str}, {time_str}{location_str}{desc_str}"


def get_custody_for_range(events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Extract custody information from events.

    Returns list of {date, parent} for each custody day found.
    """
    custody_days = []

    for event in events:
        calendar_name = event.get("_calendar_name", "")
        is_custody, parent = is_custody_event(event, calendar_name)
        if is_custody:
            date = event.get("start", {}).get("date", "")
            custody_days.append({"date": date, "parent": parent})

    return custody_days


def group_events_by_day(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by date for daily summary view."""
    by_day = {}

    for event in events:
        start = event.get("start", {})
        if "dateTime" in start:
            date = start["dateTime"][:10]  # Extract YYYY-MM-DD
        else:
            date = start.get("date", "unknown")

        if date not in by_day:
            by_day[date] = []
        by_day[date].append(event)

    return by_day


def group_events_by_member(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group events by family member for 'who has what' queries."""
    by_member = {"Unassigned": []}

    for event in events:
        calendar_name = event.get("_calendar_name", "")

        # Skip custody events in member grouping
        is_custody, _ = is_custody_event(event, calendar_name)
        if is_custody:
            continue

        member = detect_family_member(event, calendar_name)
        if member:
            if member not in by_member:
                by_member[member] = []
            by_member[member].append(event)
        else:
            by_member["Unassigned"].append(event)

    # Remove empty Unassigned category
    if not by_member["Unassigned"]:
        del by_member["Unassigned"]

    return by_member


async def execute(params: dict) -> dict:
    """
    Get calendar events based on the specified time range.

    Args:
        params: Dict with:
            - 'time_range' (required): today, tomorrow, this_week, next_week, custom
            - 'start_date', 'end_date': for custom range
            - 'max_results': limit results (default 25)
            - 'include_custody': whether to highlight custody schedule (default True)
            - 'check_conflicts': whether to detect scheduling conflicts (default True)
            - 'group_by': 'day', 'member', or None (default None)
            - 'family_member': filter to specific person (e.g., "Jack")

    Returns:
        Dict with calendar events, custody info, and any conflicts
    """
    time_range = params.get("time_range", "today")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    max_results = params.get("max_results", 25)
    include_custody = params.get("include_custody", True)
    check_conflicts = params.get("check_conflicts", True)
    group_by = params.get("group_by")
    family_member_filter = params.get("family_member", "").lower()

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

    # Filter by family member if specified
    if family_member_filter:
        filtered_events = []
        for event in all_events:
            calendar_name = event.get("_calendar_name", "")
            member = detect_family_member(event, calendar_name)
            if member and member.lower() == family_member_filter:
                filtered_events.append(event)
        all_events = filtered_events

    # Limit total results
    all_events = all_events[:max_results]

    # Extract custody information
    custody_info = []
    if include_custody:
        custody_info = get_custody_for_range(all_events)

    # Check for conflicts
    conflicts = []
    if check_conflicts:
        conflicts = find_conflicts(all_events)

    range_desc_map = {
        "today": ("today", "Today's"),
        "tomorrow": ("tomorrow", "Tomorrow's"),
        "this_week": ("this week", "This week's"),
        "next_week": ("next week", "Next week's"),
        "custom": (f"from {start_date} to {end_date}", "Scheduled")
    }
    range_desc_lower, range_desc_title = range_desc_map.get(time_range, (time_range, "Upcoming"))

    if not all_events:
        msg = f"No events scheduled for {range_desc_lower}."
        if family_member_filter:
            msg = f"No events found for {family_member_filter.capitalize()} {range_desc_lower}."
        return {
            "status": "success",
            "message": msg,
            "events": [],
            "custody": custody_info,
            "calendars_checked": calendar_names
        }

    # Build response message
    output_parts = []

    # Add custody summary at the top if relevant
    if custody_info:
        custody_summary = []
        for cd in custody_info:
            try:
                date_obj = datetime.strptime(cd["date"], "%Y-%m-%d")
                date_str = date_obj.strftime("%A, %b %d")
            except:
                date_str = cd["date"]
            custody_summary.append(f"🏠 {date_str}: {cd['parent']}'s day")
        output_parts.append("**Custody Schedule:**\n" + "\n".join(custody_summary))

    # Add conflicts warning if any
    if conflicts:
        conflict_warnings = []
        for c in conflicts:
            e1 = c["event1"].get("summary", "Event 1")
            e2 = c["event2"].get("summary", "Event 2")
            # Convert overlap time to Central
            overlap_local = c["overlap_start"].astimezone(USER_TIMEZONE)
            overlap_time = overlap_local.strftime("%I:%M %p")
            conflict_warnings.append(f"⚠️ CONFLICT: '{e1}' and '{e2}' overlap at {overlap_time}")
        output_parts.append("**Scheduling Conflicts:**\n" + "\n".join(conflict_warnings))

    # Group events if requested
    if group_by == "member":
        by_member = group_events_by_member(all_events)
        member_sections = []
        for member, events in by_member.items():
            formatted = [format_event(e, include_member=False) for e in events]
            member_sections.append(f"**{member}:**\n" + "\n\n".join(formatted))
        output_parts.append("\n\n".join(member_sections))
    elif group_by == "day":
        by_day = group_events_by_day(all_events)
        day_sections = []
        for date_str, events in sorted(by_day.items()):
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_label = date_obj.strftime("%A, %B %d")
            except:
                day_label = date_str
            formatted = [format_event(e) for e in events]
            day_sections.append(f"**{day_label}:**\n" + "\n\n".join(formatted))
        output_parts.append("\n\n".join(day_sections))
    else:
        # Default: simple list
        formatted_events = [format_event(event) for event in all_events]
        title = f"{range_desc_title} events ({len(all_events)} found)"
        if family_member_filter:
            title = f"{family_member_filter.capitalize()}'s {range_desc_lower} events ({len(all_events)} found)"
        output_parts.append(f"**{title}:**\n" + "\n\n".join(formatted_events))

    return {
        "status": "success",
        "message": "\n\n".join(output_parts),
        "events": [
            {
                "summary": e.get("summary"),
                "start": e.get("start"),
                "end": e.get("end"),
                "location": e.get("location"),
                "calendar": e.get("_calendar_name"),
                "family_member": detect_family_member(e, e.get("_calendar_name", ""))
            }
            for e in all_events
        ],
        "custody": custody_info,
        "conflicts": [
            {
                "event1": c["event1"].get("summary"),
                "event2": c["event2"].get("summary"),
                "overlap_time": c["overlap_start"].isoformat()
            }
            for c in conflicts
        ],
        "calendars_checked": calendar_names
    }
