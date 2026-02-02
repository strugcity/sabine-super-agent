"""
Reminder Notification Handler - Phase 3.1
==========================================

Handles firing reminders and delivering notifications via multiple channels:
- SMS (Twilio) - pending A2P 10DLC registration
- Email (Gmail MCP)
- Slack (future)

BDD Specification:
    Feature: Reminder Notification Delivery

      Scenario: Send SMS notification for one-time reminder
        Given a reminder is scheduled for 10:00 AM
        When the scheduler fires at 10:00 AM
        Then an SMS should be sent to USER_PHONE
        And the message should include the reminder title
        And the reminder should be marked as completed

      Scenario: Send email notification
        Given a reminder with reminder_type="email"
        When the reminder fires
        Then an email should be sent via Gmail MCP
        And include the reminder title and description

      Scenario: Send SMS for recurring reminder
        Given a weekly reminder is scheduled for Sunday 4 PM
        When the scheduler fires at Sunday 4 PM
        Then an SMS should be sent
        And the reminder should NOT be marked as completed
        And the next occurrence should be scheduled

      Scenario: Handle delivery failure
        Given a notification channel is unavailable
        When the reminder fires
        Then the failure should be logged
        And an error should be recorded in metadata
        And the reminder should remain active for retry

      Scenario: Multi-channel notification
        Given a reminder with notification_channels = {"sms": true, "email": true}
        When the reminder fires
        Then both SMS and email notifications should be sent

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 3.1
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import pytz

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Twilio SMS Configuration (pending A2P 10DLC registration)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
USER_PHONE = os.getenv("USER_PHONE")

# Email Configuration
USER_EMAIL = os.getenv("USER_GOOGLE_EMAIL", "")
AGENT_EMAIL = os.getenv("AGENT_EMAIL", "sabine@strugcity.com")

# Gmail MCP OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
AGENT_REFRESH_TOKEN = os.getenv("AGENT_REFRESH_TOKEN", "")

# User's timezone
USER_TIMEZONE = pytz.timezone(os.getenv("SCHEDULER_TIMEZONE", "America/Chicago"))


# =============================================================================
# Notification Formatters
# =============================================================================

def format_reminder_message(reminder: Dict[str, Any], channel: str = "sms") -> str:
    """
    Format a reminder into a notification message.

    Args:
        reminder: Reminder dictionary from database
        channel: Notification channel ("sms", "email", "slack")

    Returns:
        Formatted message string
    """
    title = reminder.get("title", "Reminder")
    description = reminder.get("description", "")
    repeat_pattern = reminder.get("repeat_pattern")

    # Format scheduled time in user's timezone
    scheduled_time_str = reminder.get("scheduled_time", "")
    try:
        if scheduled_time_str:
            if scheduled_time_str.endswith('Z'):
                dt = datetime.fromisoformat(scheduled_time_str[:-1] + '+00:00')
            else:
                dt = datetime.fromisoformat(scheduled_time_str)
            local_time = dt.astimezone(USER_TIMEZONE)
            time_str = local_time.strftime("%I:%M %p").lstrip("0")
        else:
            time_str = "now"
    except (ValueError, TypeError):
        time_str = "now"

    if channel == "sms":
        # SMS: Keep concise (160 char limit per segment)
        msg = f"⏰ Reminder: {title}"
        if description:
            # Truncate description for SMS
            desc_preview = description[:80] + "..." if len(description) > 80 else description
            msg += f"\n{desc_preview}"
        if repeat_pattern:
            msg += f"\n(Repeats {repeat_pattern})"
        return msg

    elif channel == "email":
        # Email: Can be more detailed
        lines = [
            f"Hi,",
            f"",
            f"This is your scheduled reminder:",
            f"",
            f"📌 **{title}**",
        ]
        if description:
            lines.append(f"")
            lines.append(description)
        lines.append(f"")
        lines.append(f"Scheduled for: {time_str}")
        if repeat_pattern:
            lines.append(f"This reminder repeats {repeat_pattern}.")
        lines.append(f"")
        lines.append(f"Best,")
        lines.append(f"Sabine")
        return "\n".join(lines)

    elif channel == "slack":
        # Slack: Use markdown formatting
        msg = f"⏰ *Reminder*: {title}"
        if description:
            msg += f"\n> {description}"
        if repeat_pattern:
            msg += f"\n_Repeats {repeat_pattern}_"
        return msg

    return f"Reminder: {title}"


def format_reminder_email_html(reminder: Dict[str, Any]) -> str:
    """
    Format a reminder as HTML email body.

    Args:
        reminder: Reminder dictionary from database

    Returns:
        HTML formatted email body
    """
    title = reminder.get("title", "Reminder")
    description = reminder.get("description", "")
    repeat_pattern = reminder.get("repeat_pattern")

    # Format scheduled time
    scheduled_time_str = reminder.get("scheduled_time", "")
    try:
        if scheduled_time_str:
            if scheduled_time_str.endswith('Z'):
                dt = datetime.fromisoformat(scheduled_time_str[:-1] + '+00:00')
            else:
                dt = datetime.fromisoformat(scheduled_time_str)
            local_time = dt.astimezone(USER_TIMEZONE)
            time_str = local_time.strftime("%A, %B %d at %I:%M %p").lstrip("0")
        else:
            time_str = "now"
    except (ValueError, TypeError):
        time_str = "now"

    html = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Hi,</p>

    <p>This is your scheduled reminder:</p>

    <div style="background-color: #f5f5f5; padding: 15px; border-left: 4px solid #4CAF50; margin: 20px 0;">
        <h3 style="margin: 0 0 10px 0; color: #2c3e50;">⏰ {title}</h3>
        {f'<p style="margin: 10px 0; color: #555;">{description}</p>' if description else ''}
        <p style="margin: 10px 0 0 0; font-size: 0.9em; color: #777;">
            Scheduled for: {time_str}
            {f'<br>Repeats {repeat_pattern}' if repeat_pattern else ''}
        </p>
    </div>

    <p>Best,<br>Sabine</p>
</body>
</html>"""
    return html


# =============================================================================
# SMS Notification (Twilio)
# =============================================================================

async def send_sms_notification(
    reminder: Dict[str, Any],
    phone_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send SMS notification for a reminder via Twilio.

    Note: SMS delivery may be limited pending A2P 10DLC campaign registration.

    Args:
        reminder: Reminder dictionary from database
        phone_number: Override phone number (defaults to USER_PHONE)

    Returns:
        Dict with success status and details
    """
    phone = phone_number or USER_PHONE

    if not phone:
        logger.warning("No phone number configured for SMS notification")
        return {
            "success": False,
            "channel": "sms",
            "error": "No phone number configured",
        }

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
        logger.warning("Twilio credentials not configured - SMS not sent")
        message = format_reminder_message(reminder, "sms")
        logger.info(f"Would send SMS to {phone}: {message}")
        return {
            "success": False,
            "channel": "sms",
            "error": "Twilio credentials not configured",
            "would_send": message,
        }

    try:
        from twilio.rest import Client as TwilioClient

        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = format_reminder_message(reminder, "sms")

        sms = client.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=phone
        )

        logger.info(f"SMS reminder sent: {sms.sid}")
        return {
            "success": True,
            "channel": "sms",
            "message_sid": sms.sid,
            "to": phone,
        }

    except Exception as e:
        logger.error(f"Failed to send SMS reminder: {e}")
        return {
            "success": False,
            "channel": "sms",
            "error": str(e),
        }


# =============================================================================
# Email Notification (Gmail MCP)
# =============================================================================

async def send_email_notification(
    reminder: Dict[str, Any],
    to_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send email notification for a reminder via Gmail MCP.

    Args:
        reminder: Reminder dictionary from database
        to_email: Override recipient email (defaults to USER_EMAIL)

    Returns:
        Dict with success status and details
    """
    recipient = to_email or USER_EMAIL

    if not recipient:
        logger.warning("No email address configured for email notification")
        return {
            "success": False,
            "channel": "email",
            "error": "No recipient email configured",
        }

    if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, AGENT_REFRESH_TOKEN]):
        logger.warning("Gmail MCP credentials not configured - email not sent")
        return {
            "success": False,
            "channel": "email",
            "error": "Gmail MCP credentials not configured",
        }

    try:
        from lib.agent.mcp_client import MCPClient

        title = reminder.get("title", "Reminder")
        subject = f"⏰ Reminder: {title}"
        body = format_reminder_message(reminder, "email")
        html_body = format_reminder_email_html(reminder)

        async with MCPClient(
            command="/app/deploy/start-mcp-server.sh",
            args=[]
        ) as mcp:
            # Get fresh access token
            token_result = await mcp.call_tool("gmail_refresh_token", {
                "google_refresh_token": AGENT_REFRESH_TOKEN,
                "google_client_id": GOOGLE_CLIENT_ID,
                "google_client_secret": GOOGLE_CLIENT_SECRET,
            })

            try:
                token_data = json.loads(token_result)
                access_token = token_data.get("access_token")
            except (json.JSONDecodeError, TypeError):
                logger.error(f"Failed to parse token response: {token_result[:200]}")
                return {
                    "success": False,
                    "channel": "email",
                    "error": "Failed to get access token",
                }

            if not access_token:
                return {
                    "success": False,
                    "channel": "email",
                    "error": "No access token in response",
                }

            # Send email
            send_result = await mcp.call_tool("gmail_send_email", {
                "google_access_token": access_token,
                "to": recipient,
                "subject": subject,
                "body": body,
                "html_body": html_body,
            })

            if send_result and ("success" in send_result.lower() or "id" in send_result.lower()):
                logger.info(f"Email reminder sent to {recipient}")
                return {
                    "success": True,
                    "channel": "email",
                    "to": recipient,
                    "subject": subject,
                }
            else:
                logger.warning(f"Email send may have failed: {send_result}")
                return {
                    "success": False,
                    "channel": "email",
                    "error": f"Unexpected response: {send_result[:200]}",
                }

    except Exception as e:
        logger.error(f"Failed to send email reminder: {e}", exc_info=True)
        return {
            "success": False,
            "channel": "email",
            "error": str(e),
        }


# =============================================================================
# Unified Notification Dispatcher
# =============================================================================

async def send_reminder_notification(
    reminder: Dict[str, Any],
    channels: Optional[Dict[str, bool]] = None
) -> Dict[str, Any]:
    """
    Send reminder notification via configured channels.

    Dispatches to all enabled channels and collects results.

    Args:
        reminder: Reminder dictionary from database
        channels: Override notification channels (uses reminder's channels if not provided)

    Returns:
        Dict with overall status and per-channel results
    """
    reminder_id = reminder.get("id", "unknown")
    title = reminder.get("title", "Untitled")

    # Get notification channels
    if channels is None:
        channels = reminder.get("notification_channels", {})

    # Default to SMS if no channels specified
    if not channels:
        channels = {"sms": True}

    logger.info(f"Sending reminder '{title}' (ID: {reminder_id}) via channels: {channels}")

    results = {
        "reminder_id": reminder_id,
        "title": title,
        "channels_attempted": [],
        "channels_succeeded": [],
        "channels_failed": [],
        "details": {},
    }

    # Send to each enabled channel
    tasks = []

    if channels.get("sms"):
        results["channels_attempted"].append("sms")
        tasks.append(("sms", send_sms_notification(reminder)))

    if channels.get("email"):
        results["channels_attempted"].append("email")
        tasks.append(("email", send_email_notification(reminder)))

    # Execute all channel notifications concurrently
    if tasks:
        channel_results = await asyncio.gather(
            *[task[1] for task in tasks],
            return_exceptions=True
        )

        for i, (channel, _) in enumerate(tasks):
            result = channel_results[i]

            if isinstance(result, Exception):
                results["channels_failed"].append(channel)
                results["details"][channel] = {
                    "success": False,
                    "error": str(result),
                }
            elif isinstance(result, dict):
                results["details"][channel] = result
                if result.get("success"):
                    results["channels_succeeded"].append(channel)
                else:
                    results["channels_failed"].append(channel)
            else:
                results["channels_failed"].append(channel)
                results["details"][channel] = {
                    "success": False,
                    "error": f"Unexpected result type: {type(result)}",
                }

    # Determine overall success (at least one channel succeeded)
    results["success"] = len(results["channels_succeeded"]) > 0
    results["partial_success"] = (
        len(results["channels_succeeded"]) > 0 and
        len(results["channels_failed"]) > 0
    )

    logger.info(
        f"Reminder notification complete: "
        f"succeeded={results['channels_succeeded']}, "
        f"failed={results['channels_failed']}"
    )

    return results


# =============================================================================
# Reminder Firing Logic
# =============================================================================

async def fire_reminder(reminder_id: UUID) -> Dict[str, Any]:
    """
    Fire a reminder: send notification and update status.

    This is the main entry point called by the scheduler when a reminder is due.

    Steps:
    1. Fetch reminder from database
    2. Send notification via configured channels
    3. Update reminder status:
       - One-time: Mark as completed
       - Recurring: Update last_triggered_at, keep active
    4. Log the result

    Args:
        reminder_id: UUID of the reminder to fire

    Returns:
        Dict with firing result and notification details
    """
    from backend.services.reminder_service import get_reminder_service

    logger.info(f"Firing reminder: {reminder_id}")

    result = {
        "reminder_id": str(reminder_id),
        "fired_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "notification_result": None,
        "error": None,
    }

    try:
        service = get_reminder_service()

        # Step 1: Fetch reminder
        get_result = await service.get_reminder(reminder_id)
        if not get_result.success:
            error_msg = get_result.error.message if get_result.error else "Not found"
            result["status"] = "failed"
            result["error"] = f"Could not fetch reminder: {error_msg}"
            logger.error(result["error"])
            return result

        reminder = get_result.data.get("reminder", {})

        # Check if reminder is still active
        if not reminder.get("is_active"):
            result["status"] = "skipped"
            result["error"] = "Reminder is not active"
            logger.info(f"Reminder {reminder_id} is not active, skipping")
            return result

        # Step 2: Send notification
        notification_result = await send_reminder_notification(reminder)
        result["notification_result"] = notification_result

        # Step 3: Update reminder status
        repeat_pattern = reminder.get("repeat_pattern")

        if repeat_pattern:
            # Recurring reminder: update last_triggered_at, keep active
            update_result = await service.update_last_triggered(reminder_id)
            if update_result.success:
                result["status"] = "success"
                result["action"] = "triggered_recurring"
                logger.info(f"Recurring reminder {reminder_id} triggered, will repeat {repeat_pattern}")
            else:
                result["status"] = "partial"
                result["error"] = "Notification sent but failed to update status"
        else:
            # One-time reminder: mark as completed
            complete_result = await service.complete_reminder(reminder_id)
            if complete_result.success:
                result["status"] = "success"
                result["action"] = "completed"
                logger.info(f"One-time reminder {reminder_id} completed")
            else:
                result["status"] = "partial"
                result["error"] = "Notification sent but failed to mark complete"

        return result

    except Exception as e:
        logger.error(f"Error firing reminder {reminder_id}: {e}", exc_info=True)
        result["status"] = "failed"
        result["error"] = str(e)
        return result


# =============================================================================
# Batch Processing for Due Reminders
# =============================================================================

async def process_due_reminders() -> Dict[str, Any]:
    """
    Process all reminders that are due for firing.

    This function can be called periodically by the scheduler to catch
    any reminders that might have been missed.

    Returns:
        Dict with processing results
    """
    from backend.services.reminder_service import get_reminder_service

    logger.info("Processing due reminders...")

    result = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "reminders_found": 0,
        "reminders_processed": 0,
        "reminders_succeeded": 0,
        "reminders_failed": 0,
        "details": [],
    }

    try:
        service = get_reminder_service()

        # Get all due reminders
        list_result = await service.list_due_reminders(limit=50)
        if not list_result.success:
            result["error"] = "Failed to list due reminders"
            return result

        reminders = list_result.data.get("reminders", [])
        result["reminders_found"] = len(reminders)

        if not reminders:
            logger.info("No due reminders found")
            return result

        # Process each reminder
        for reminder in reminders:
            reminder_id = UUID(reminder["id"])
            fire_result = await fire_reminder(reminder_id)
            result["reminders_processed"] += 1

            if fire_result.get("status") == "success":
                result["reminders_succeeded"] += 1
            else:
                result["reminders_failed"] += 1

            result["details"].append({
                "reminder_id": str(reminder_id),
                "title": reminder.get("title"),
                "result": fire_result.get("status"),
                "error": fire_result.get("error"),
            })

        logger.info(
            f"Processed {result['reminders_processed']} due reminders: "
            f"{result['reminders_succeeded']} succeeded, {result['reminders_failed']} failed"
        )

        return result

    except Exception as e:
        logger.error(f"Error processing due reminders: {e}", exc_info=True)
        result["error"] = str(e)
        return result
