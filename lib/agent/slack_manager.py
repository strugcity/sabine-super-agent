"""
Slack Manager - The Gantry
==========================

This module manages the Slack Socket Mode connection for real-time
communication with the #dream-team-ops channel.

The Gantry serves as the infrastructure voice for Strug City's
Virtual Engineering Office, providing:
- Real-time task dispatch notifications
- Agent activity updates (threaded by task)
- System status announcements

Requires:
- SLACK_BOT_TOKEN (xoxb-...) - Bot User OAuth Token
- SLACK_APP_TOKEN (xapp-...) - App-Level Token for Socket Mode
- SLACK_CHANNEL_ID - Target channel for updates (e.g., #dream-team-ops)

Owner: @backend-architect-sabine
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "dream-team-ops")

# Track thread timestamps for task-based threading
# Protected by _task_threads_lock for thread-safety (P3 fix)
_task_threads: Dict[str, str] = {}  # task_id -> thread_ts
_task_threads_lock = threading.Lock()

# Global slack client reference
_slack_app = None
_socket_handler = None
_is_connected = False


# =============================================================================
# Event Logging to Supabase
# =============================================================================

async def log_agent_event(
    event_type: str,
    content: str,
    task_id: Optional[UUID] = None,
    role: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    slack_thread_ts: Optional[str] = None,
    slack_channel: Optional[str] = None
) -> Optional[UUID]:
    """
    Log an agent event to the agent_events table.

    Args:
        event_type: Type of event (task_started, agent_thought, etc.)
        content: Event message/content
        task_id: Optional linked task ID
        role: Agent role that generated this event
        metadata: Additional structured data
        slack_thread_ts: Slack thread timestamp if posted
        slack_channel: Slack channel if posted

    Returns:
        UUID of created event, or None if failed
    """
    try:
        from supabase import create_client

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not supabase_url or not supabase_key:
            logger.warning("Supabase not configured, skipping event log")
            return None

        client = create_client(supabase_url, supabase_key)

        event_data = {
            "event_type": event_type,
            "content": content,
            "role": role,
            "metadata": metadata or {},
            "slack_thread_ts": slack_thread_ts,
            "slack_channel": slack_channel
        }

        if task_id:
            event_data["task_id"] = str(task_id)

        response = client.table("agent_events").insert(event_data).execute()

        if response.data and len(response.data) > 0:
            event_id = UUID(response.data[0]["id"])
            logger.debug(f"Logged event {event_id}: {event_type}")
            return event_id

        return None

    except Exception as e:
        logger.error(f"Failed to log agent event: {e}")
        return None


# =============================================================================
# Slack Client Management
# =============================================================================

def get_slack_app():
    """Get or create the Slack AsyncApp instance."""
    global _slack_app

    if _slack_app is not None:
        return _slack_app

    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set - Slack integration disabled")
        return None

    try:
        from slack_bolt.async_app import AsyncApp

        _slack_app = AsyncApp(token=SLACK_BOT_TOKEN)
        logger.info("Slack AsyncApp initialized")
        return _slack_app

    except ImportError:
        logger.error("slack-bolt not installed. Run: pip install slack-bolt")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Slack app: {e}")
        return None


async def start_socket_mode():
    """
    Start the Slack Socket Mode connection.

    This should be called once during server startup.
    """
    global _socket_handler, _is_connected

    if not SLACK_APP_TOKEN:
        logger.warning("SLACK_APP_TOKEN not set - Socket Mode disabled")
        return False

    app = get_slack_app()
    if not app:
        return False

    try:
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

        _socket_handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)

        # Start in background
        asyncio.create_task(_socket_handler.start_async())
        _is_connected = True

        logger.info("Slack Socket Mode connection started")

        # Post the Gantry introduction
        await post_gantry_introduction()

        return True

    except ImportError:
        logger.error("slack-bolt Socket Mode adapter not available")
        return False
    except Exception as e:
        logger.error(f"Failed to start Socket Mode: {e}")
        return False


async def stop_socket_mode():
    """Stop the Slack Socket Mode connection."""
    global _socket_handler, _is_connected

    if _socket_handler:
        try:
            await _socket_handler.close_async()
            _is_connected = False
            logger.info("Slack Socket Mode connection stopped")
        except Exception as e:
            logger.error(f"Error stopping Socket Mode: {e}")


def is_slack_connected() -> bool:
    """Check if Slack is connected."""
    return _is_connected


# =============================================================================
# The Gantry - Self Introduction
# =============================================================================

async def post_gantry_introduction():
    """
    Post The Gantry's self-introduction to #dream-team-ops.

    Called once on successful Socket Mode connection.
    """
    try:
        # Get available roles
        from lib.agent.core import get_available_roles, load_role_manifest

        roles = get_available_roles()
        role_list = []
        for role_id in roles:
            manifest = load_role_manifest(role_id)
            if manifest:
                role_list.append(f"• *{manifest.title}* (`{role_id}`)")

        roles_text = "\n".join(role_list) if role_list else "• No roles currently configured"

        # Build the introduction message
        intro_blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "The Gantry is now Online",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_Monitoring Strug City engineering workstreams..._"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Active Roles Staffed in the Virtual Office:*\n{roles_text}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "I'm listening for task dispatches and will provide real-time updates here. Use `/tasks` or the API to queue work for the team."
                    }
                ]
            }
        ]

        # Post the introduction
        result = await send_slack_message(
            text="The Gantry is now Online",
            blocks=intro_blocks,
            channel=SLACK_CHANNEL_ID
        )

        if result:
            # Log the system startup event
            await log_agent_event(
                event_type="system_startup",
                content="The Gantry initialized and connected to Slack",
                metadata={
                    "roles_count": len(roles),
                    "channel": SLACK_CHANNEL_ID
                },
                slack_channel=SLACK_CHANNEL_ID
            )
            logger.info("Posted Gantry introduction to Slack")
        else:
            logger.warning("Failed to post Gantry introduction")

    except Exception as e:
        logger.error(f"Error posting Gantry introduction: {e}")


# =============================================================================
# Slack Messaging
# =============================================================================

async def send_slack_message(
    text: str,
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None,
    blocks: Optional[List[Dict]] = None
) -> Optional[Dict]:
    """
    Send a message to Slack.

    Args:
        text: Plain text fallback
        channel: Channel to post to (default: SLACK_CHANNEL_ID)
        thread_ts: Thread timestamp for replies
        blocks: Rich message blocks

    Returns:
        Slack API response dict, or None if failed
    """
    app = get_slack_app()
    if not app:
        logger.warning("Slack not configured, message not sent")
        return None

    channel = channel or SLACK_CHANNEL_ID

    try:
        kwargs = {
            "channel": channel,
            "text": text
        }

        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        if blocks:
            kwargs["blocks"] = blocks

        result = await app.client.chat_postMessage(**kwargs)

        if result["ok"]:
            return {
                "ok": True,
                "ts": result["ts"],
                "channel": result["channel"]
            }
        else:
            logger.error(f"Slack API error: {result.get('error')}")
            return None

    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
        return None


async def send_task_update(
    task_id: UUID,
    role: str,
    event_type: str,
    message: str,
    details: Optional[str] = None
) -> Optional[str]:
    """
    Send a task update to Slack, threading by task_id.

    First update for a task creates a new message.
    Subsequent updates are threaded under the original.

    Args:
        task_id: Task UUID for threading
        role: Agent role performing the task
        event_type: Type of update (started, completed, thought, etc.)
        message: Main update message
        details: Optional additional details

    Returns:
        Thread timestamp if successful
    """
    task_key = str(task_id)

    # Thread-safe read of existing thread
    with _task_threads_lock:
        thread_ts = _task_threads.get(task_key)

    # Build emoji based on event type
    emoji_map = {
        "task_started": "",
        "task_completed": "",
        "task_failed": "",
        "agent_thought": "",
        "tool_call": "",
        "tool_result": "",
        "handshake": "",
        "error": "",
        "info": ""
    }
    emoji = emoji_map.get(event_type, "")

    # Format the message
    formatted_text = f"{emoji} *{event_type.replace('_', ' ').title()}* | `{role}`\n{message}"

    if details:
        formatted_text += f"\n```{details[:500]}```"  # Truncate long details

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Task: `{task_key[:8]}...` | {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f"{emoji} {event_type}: {message}",
        blocks=blocks,
        thread_ts=thread_ts
    )

    if result:
        new_ts = result.get("ts")

        # Thread-safe write if this was the first message
        current_thread_ts = thread_ts
        if not thread_ts and new_ts:
            with _task_threads_lock:
                # Double-check pattern: verify still not set
                if task_key not in _task_threads:
                    _task_threads[task_key] = new_ts
                    current_thread_ts = new_ts
                    logger.debug(f"Created new thread for task {task_key}: {new_ts}")
                else:
                    current_thread_ts = _task_threads[task_key]

        # Log to agent_events
        await log_agent_event(
            event_type=event_type,
            content=message,
            task_id=task_id,
            role=role,
            metadata={"details": details} if details else None,
            slack_thread_ts=current_thread_ts,
            slack_channel=SLACK_CHANNEL_ID
        )

        return current_thread_ts or new_ts

    return None


def get_task_thread(task_id: UUID) -> Optional[str]:
    """Get the Slack thread timestamp for a task (thread-safe)."""
    with _task_threads_lock:
        return _task_threads.get(str(task_id))


async def send_cascade_failure_alert(
    source_task_id: UUID,
    source_role: str,
    source_error: str,
    cascaded_task_ids: List[str],
    cascaded_count: int
) -> Optional[str]:
    """
    Send an alert about cascade failure propagation.

    This is sent when a task failure causes dependent tasks to also fail,
    providing visibility into orphaned dependency chains.

    Args:
        source_task_id: The original task that failed
        source_role: Role of the original failed task
        source_error: Error message from the original failure
        cascaded_task_ids: List of task IDs that were failed due to cascade
        cascaded_count: Total number of tasks failed in cascade

    Returns:
        Message timestamp if successful
    """
    if cascaded_count == 0:
        return None

    # Build a warning message with cascade details
    task_list = ", ".join([f"`{tid[:8]}...`" for tid in cascaded_task_ids[:5]])
    if len(cascaded_task_ids) > 5:
        task_list += f" and {len(cascaded_task_ids) - 5} more"

    formatted_text = (
        f":warning: *Cascade Failure Alert*\n"
        f"Task `{str(source_task_id)[:8]}...` (`{source_role}`) failed and triggered cascade failure.\n"
        f"*{cascaded_count} dependent task(s) have been automatically failed:*\n"
        f"{task_list}\n\n"
        f"*Original error:* {source_error[:200]}{'...' if len(source_error) > 200 else ''}"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":rotating_light: Cascade failure at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} | Source: `{str(source_task_id)[:8]}...`"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f":warning: Cascade failure: {cascaded_count} tasks failed due to {source_task_id}",
        blocks=blocks,
        thread_ts=None  # Send as new message, not threaded
    )

    if result:
        # Log to agent_events
        await log_agent_event(
            event_type="cascade_failure",
            content=f"{cascaded_count} tasks failed due to cascade from {source_task_id}",
            task_id=source_task_id,
            role=source_role,
            metadata={
                "cascaded_task_ids": cascaded_task_ids,
                "cascaded_count": cascaded_count,
                "source_error": source_error[:500]
            }
        )

    return result.get("ts") if result else None


async def send_stuck_task_alert(
    stuck_tasks: List[Dict[str, Any]],
    requeued_count: int,
    failed_count: int
) -> Optional[str]:
    """
    Send an alert about stuck tasks detected by the watchdog.

    Args:
        stuck_tasks: List of stuck task info dicts with task_id, role, elapsed
        requeued_count: Number of tasks requeued for retry
        failed_count: Number of tasks permanently failed

    Returns:
        Message timestamp if successful
    """
    if not stuck_tasks:
        return None

    total = len(stuck_tasks)

    # Build task list
    task_lines = []
    for task in stuck_tasks[:5]:  # Limit to 5 tasks
        task_lines.append(
            f"- `{task.get('task_id', 'unknown')[:8]}...` ({task.get('role', 'unknown')}): "
            f"ran for {task.get('elapsed', 'unknown')}"
        )
    if len(stuck_tasks) > 5:
        task_lines.append(f"- ... and {len(stuck_tasks) - 5} more")

    task_list = "\n".join(task_lines)

    formatted_text = (
        f":rotating_light: *Stuck Task Watchdog Alert*\n"
        f"Detected *{total} stuck task(s)* that exceeded their timeout:\n"
        f"{task_list}\n\n"
        f"*Actions taken:*\n"
        f"- {requeued_count} task(s) requeued for retry\n"
        f"- {failed_count} task(s) permanently failed (max retries exceeded)"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":timer_clock: Watchdog scan at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f":rotating_light: Watchdog: {total} stuck tasks detected",
        blocks=blocks,
        thread_ts=None  # Send as new message
    )

    if result:
        # Log to agent_events
        await log_agent_event(
            event_type="stuck_tasks_detected",
            content=f"Watchdog detected {total} stuck tasks: {requeued_count} requeued, {failed_count} failed",
            metadata={
                "stuck_tasks": stuck_tasks[:10],  # Limit metadata size
                "total_stuck": total,
                "requeued_count": requeued_count,
                "failed_count": failed_count
            }
        )

    return result.get("ts") if result else None


def clear_task_thread(task_id: UUID) -> bool:
    """
    Clear the thread tracking for a completed/failed task (thread-safe).

    This should be called when a task completes or fails to prevent
    memory leaks from accumulating thread mappings.

    Args:
        task_id: The task ID to clear

    Returns:
        True if a thread was cleared, False if no thread existed
    """
    task_key = str(task_id)
    with _task_threads_lock:
        if task_key in _task_threads:
            del _task_threads[task_key]
            logger.debug(f"Cleared thread mapping for task {task_key}")
            return True
    return False


def get_task_threads_count() -> int:
    """
    Get the current number of tracked task threads.

    Useful for monitoring memory usage and debugging leaks.

    Returns:
        Number of task threads currently being tracked
    """
    with _task_threads_lock:
        return len(_task_threads)


# =============================================================================
# Health Check Alerts (P1 #5)
# =============================================================================

async def send_blocked_tasks_alert(
    blocked_tasks: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Send an alert about tasks blocked by failed dependencies.

    These tasks will never run without manual intervention.

    Args:
        blocked_tasks: List of blocked task info dicts from get_blocked_tasks()

    Returns:
        Message timestamp if successful
    """
    if not blocked_tasks:
        return None

    count = len(blocked_tasks)

    # Group by failed dependency for cleaner display
    by_failed_dep: Dict[str, List[Dict]] = {}
    for task in blocked_tasks:
        dep_id = task.get("failed_dependency_id", "unknown")
        if dep_id not in by_failed_dep:
            by_failed_dep[dep_id] = []
        by_failed_dep[dep_id].append(task)

    # Build task list - show up to 5 blocked tasks with their failed deps
    task_lines = []
    shown = 0
    for dep_id, tasks in list(by_failed_dep.items())[:3]:
        dep_role = tasks[0].get("failed_dependency_role", "unknown")
        dep_error = tasks[0].get("failed_dependency_error", "Unknown error")
        task_ids = ", ".join([f"`{t['task_id'][:8]}...`" for t in tasks[:3]])
        if len(tasks) > 3:
            task_ids += f" +{len(tasks) - 3} more"

        task_lines.append(
            f"- *Failed dep:* `{str(dep_id)[:8]}...` ({dep_role})\n"
            f"  Blocking: {task_ids}\n"
            f"  Error: _{dep_error[:100]}{'...' if len(dep_error) > 100 else ''}_"
        )
        shown += len(tasks)

    if count > shown:
        task_lines.append(f"- ... and {count - shown} more blocked tasks")

    task_list = "\n".join(task_lines)

    formatted_text = (
        f":no_entry: *Blocked Tasks Alert*\n"
        f"*{count} task(s)* are blocked by failed dependencies and will never run:\n\n"
        f"{task_list}\n\n"
        f"_These tasks require manual intervention (retry failed deps or cancel blocked tasks)._"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":health: Health check at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f":no_entry: {count} tasks blocked by failed dependencies",
        blocks=blocks,
        thread_ts=None
    )

    if result:
        await log_agent_event(
            event_type="blocked_tasks_alert",
            content=f"{count} tasks blocked by failed dependencies",
            metadata={
                "blocked_count": count,
                "sample_tasks": blocked_tasks[:5]
            }
        )

    return result.get("ts") if result else None


async def send_stale_tasks_alert(
    stale_tasks: List[Dict[str, Any]],
    threshold_minutes: int
) -> Optional[str]:
    """
    Send an alert about tasks that have been queued for too long.

    Args:
        stale_tasks: List of stale task info dicts from get_stale_queued_tasks()
        threshold_minutes: The threshold used for detection

    Returns:
        Message timestamp if successful
    """
    if not stale_tasks:
        return None

    count = len(stale_tasks)

    # Build task list
    task_lines = []
    for task in stale_tasks[:5]:
        queued_mins = task.get("queued_minutes", 0)
        hours = int(queued_mins // 60)
        mins = int(queued_mins % 60)
        time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

        dep_info = ""
        dep_count = task.get("dependency_count", 0)
        pending = task.get("pending_dependencies", 0)
        if dep_count > 0:
            dep_info = f" | Deps: {pending}/{dep_count} pending"

        task_lines.append(
            f"- `{task['task_id'][:8]}...` ({task.get('task_role', 'unknown')}): "
            f"queued {time_str}{dep_info}"
        )

    if count > 5:
        task_lines.append(f"- ... and {count - 5} more stale tasks")

    task_list = "\n".join(task_lines)

    formatted_text = (
        f":hourglass: *Stale Queued Tasks Alert*\n"
        f"*{count} task(s)* have been queued for over {threshold_minutes} minutes:\n\n"
        f"{task_list}\n\n"
        f"_Check if these tasks have unmet dependencies or dispatch issues._"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":health: Health check at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f":hourglass: {count} tasks queued for over {threshold_minutes}m",
        blocks=blocks,
        thread_ts=None
    )

    if result:
        await log_agent_event(
            event_type="stale_tasks_alert",
            content=f"{count} tasks queued for over {threshold_minutes} minutes",
            metadata={
                "stale_count": count,
                "threshold_minutes": threshold_minutes,
                "sample_tasks": stale_tasks[:5]
            }
        )

    return result.get("ts") if result else None


async def send_orphaned_tasks_alert(
    orphaned_tasks: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Send an alert about tasks where ALL dependencies have failed.

    These tasks have zero chance of running without recreating their
    entire dependency chain.

    Args:
        orphaned_tasks: List of orphaned task info dicts from get_orphaned_tasks()

    Returns:
        Message timestamp if successful
    """
    if not orphaned_tasks:
        return None

    count = len(orphaned_tasks)

    # Build task list
    task_lines = []
    for task in orphaned_tasks[:5]:
        total_deps = task.get("total_dependencies", 0)
        failed_deps = task.get("failed_dependencies", 0)

        task_lines.append(
            f"- `{task['task_id'][:8]}...` ({task.get('task_role', 'unknown')}): "
            f"all {failed_deps}/{total_deps} dependencies failed"
        )

    if count > 5:
        task_lines.append(f"- ... and {count - 5} more orphaned tasks")

    task_list = "\n".join(task_lines)

    formatted_text = (
        f":skull: *Orphaned Tasks Alert*\n"
        f"*{count} task(s)* have ALL dependencies failed - they cannot run:\n\n"
        f"{task_list}\n\n"
        f"_These tasks should be cancelled or their dependency chains recreated._"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":health: Health check at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f":skull: {count} tasks fully orphaned (all deps failed)",
        blocks=blocks,
        thread_ts=None
    )

    if result:
        await log_agent_event(
            event_type="orphaned_tasks_alert",
            content=f"{count} tasks with all dependencies failed",
            metadata={
                "orphaned_count": count,
                "sample_tasks": orphaned_tasks[:5]
            }
        )

    return result.get("ts") if result else None


async def send_health_summary(
    health: Dict[str, Any],
    issues_found: bool = False
) -> Optional[str]:
    """
    Send a periodic health summary to Slack.

    Args:
        health: Health metrics dict from get_task_queue_health()
        issues_found: Whether any issues were detected

    Returns:
        Message timestamp if successful
    """
    emoji = ":white_check_mark:" if not issues_found else ":warning:"
    status = "Healthy" if not issues_found else "Issues Detected"

    formatted_text = (
        f"{emoji} *Task Queue Health Summary*\n\n"
        f"*Queue Status:*\n"
        f"- Queued: {health.get('total_queued', 0)}\n"
        f"- In Progress: {health.get('total_in_progress', 0)}\n\n"
        f"*Potential Issues:*\n"
        f"- Blocked by failed deps: {health.get('blocked_by_failed_deps', 0)}\n"
        f"- Stale (>1h): {health.get('stale_queued_1h', 0)}\n"
        f"- Stale (>24h): {health.get('stale_queued_24h', 0)}\n"
        f"- Stuck in-progress: {health.get('stuck_tasks', 0)}\n"
        f"- Pending retries: {health.get('pending_retries', 0)}"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":health: Status: *{status}* | {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f"{emoji} Task Queue: {status}",
        blocks=blocks,
        thread_ts=None
    )

    return result.get("ts") if result else None


async def send_auto_fail_alert(
    failed_count: int,
    cascaded_count: int,
    sample_tasks: List[Dict[str, Any]]
) -> Optional[str]:
    """
    Send an alert about auto-failed blocked tasks.

    This is sent when the auto_fail_blocked_tasks() method runs
    and automatically fails tasks with failed dependencies.

    Args:
        failed_count: Number of tasks directly failed
        cascaded_count: Number of additional tasks failed via cascade
        sample_tasks: Sample of failed tasks for context

    Returns:
        Message timestamp if successful
    """
    if failed_count == 0:
        return None

    # Build task list
    task_lines = []
    for task in sample_tasks[:5]:
        task_lines.append(
            f"- `{task['task_id'][:8]}...` ({task.get('role', 'unknown')}): "
            f"blocked by `{task.get('failed_dep_id', 'unknown')[:8]}...`"
        )

    if failed_count > 5:
        task_lines.append(f"- ... and {failed_count - 5} more")

    task_list = "\n".join(task_lines)

    formatted_text = (
        f":broom: *Auto-Fix: Blocked Tasks Failed*\n"
        f"Automatically failed *{failed_count} blocked task(s)* "
        f"(+{cascaded_count} via cascade):\n\n"
        f"{task_list}\n\n"
        f"_These tasks had failed dependencies and would never have run._"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": formatted_text
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":gear: Auto-fix at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
                }
            ]
        }
    ]

    result = await send_slack_message(
        text=f":broom: Auto-failed {failed_count} blocked tasks (+{cascaded_count} cascaded)",
        blocks=blocks,
        thread_ts=None
    )

    if result:
        await log_agent_event(
            event_type="auto_fail_blocked",
            content=f"Auto-failed {failed_count} blocked tasks (+{cascaded_count} cascaded)",
            metadata={
                "failed_count": failed_count,
                "cascaded_count": cascaded_count,
                "sample_tasks": sample_tasks[:5]
            }
        )

    return result.get("ts") if result else None
