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
_task_threads: Dict[str, str] = {}  # task_id -> thread_ts

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

        # If this was the first message, store the thread_ts
        if not thread_ts and new_ts:
            _task_threads[task_key] = new_ts
            logger.debug(f"Created new thread for task {task_key}: {new_ts}")

        # Log to agent_events
        await log_agent_event(
            event_type=event_type,
            content=message,
            task_id=task_id,
            role=role,
            metadata={"details": details} if details else None,
            slack_thread_ts=_task_threads.get(task_key),
            slack_channel=SLACK_CHANNEL_ID
        )

        return _task_threads.get(task_key, new_ts)

    return None


def get_task_thread(task_id: UUID) -> Optional[str]:
    """Get the Slack thread timestamp for a task."""
    return _task_threads.get(str(task_id))


def clear_task_thread(task_id: UUID):
    """Clear the thread tracking for a completed task."""
    task_key = str(task_id)
    if task_key in _task_threads:
        del _task_threads[task_key]
