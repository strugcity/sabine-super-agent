"""
Slack Ops Skill - Team Update Communication

This skill allows agents to send updates to the #dream-team-ops Slack channel.
Messages for the same task are automatically threaded together.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a team update to Slack.

    Args:
        params: Dict with:
            - message (str): Main message content
            - event_type (str): Type of update (default: 'info')
            - task_id (str): Optional task UUID for threading
            - details (str): Optional additional details

    Returns:
        Dict with status, thread_ts, and message info
    """
    message = params.get("message")
    if not message:
        return {
            "status": "error",
            "error": "No message provided",
            "message": "The 'message' parameter is required"
        }

    event_type = params.get("event_type", "info")
    task_id_str = params.get("task_id")
    details = params.get("details")

    # Get the current role from context (if available)
    role = params.get("_role", "unknown-agent")

    try:
        from lib.agent.slack_manager import send_task_update, send_slack_message, log_agent_event

        # If task_id provided, use threaded update
        if task_id_str:
            try:
                task_id = UUID(task_id_str)
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid task_id format: {task_id_str}",
                    "message": "task_id must be a valid UUID"
                }

            thread_ts = await send_task_update(
                task_id=task_id,
                role=role,
                event_type=event_type,
                message=message,
                details=details
            )

            if thread_ts:
                return {
                    "status": "success",
                    "message": "Update sent to Slack (threaded)",
                    "thread_ts": thread_ts,
                    "task_id": task_id_str,
                    "event_type": event_type
                }
            else:
                # Log to events even if Slack failed
                await log_agent_event(
                    event_type=event_type,
                    content=message,
                    task_id=task_id,
                    role=role,
                    metadata={"details": details, "slack_failed": True}
                )
                return {
                    "status": "partial",
                    "message": "Slack send failed, but event was logged",
                    "event_type": event_type
                }

        else:
            # Non-threaded message
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

            formatted_text = f"{emoji} *{event_type.replace('_', ' ').title()}* | `{role}`\n{message}"

            if details:
                formatted_text += f"\n```{details[:500]}```"

            result = await send_slack_message(
                text=f"{emoji} {event_type}: {message}",
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": formatted_text
                    }
                }]
            )

            # Log the event
            await log_agent_event(
                event_type=event_type,
                content=message,
                role=role,
                metadata={"details": details} if details else None
            )

            if result:
                return {
                    "status": "success",
                    "message": "Update sent to Slack",
                    "ts": result.get("ts"),
                    "event_type": event_type
                }
            else:
                return {
                    "status": "partial",
                    "message": "Slack send failed, but event was logged",
                    "event_type": event_type
                }

    except ImportError as e:
        logger.error(f"Slack manager import error: {e}")
        return {
            "status": "error",
            "error": f"Import error: {e}",
            "message": "Slack integration not available"
        }

    except Exception as e:
        logger.error(f"Error sending team update: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to send team update"
        }
