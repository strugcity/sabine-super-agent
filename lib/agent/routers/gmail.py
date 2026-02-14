"""
Gmail Router - Gmail integration endpoints.

Endpoints:
- POST /gmail/handle - Handle Gmail push notifications
- GET  /gmail/diagnostic - Diagnostic info for Gmail credentials
- GET  /gmail/debug-inbox - Debug agent inbox
- POST /gmail/renew-watch - Renew Gmail push notification watch
"""

import logging
import os
import subprocess
import sys
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

# Import from server.py
from lib.agent.shared import verify_api_key
from lib.agent.gmail_handler import (
    handle_new_email_notification,
    get_config,
    get_access_token,
    load_processed_ids,
    TokenExpiredError,
)
from lib.agent.mcp_client import MCPClient

logger = logging.getLogger(__name__)

# Get project root
project_root = Path(__file__).parent.parent.parent.parent

# Create router with /gmail prefix
router = APIRouter(prefix="/gmail", tags=["gmail"])


class GmailHandleRequest(BaseModel):
    historyId: str


class GmailWatchRenewRequest(BaseModel):
    webhookUrl: str


@router.post("/handle")
async def handle_gmail_notification(request: GmailHandleRequest, _: bool = Depends(verify_api_key)):
    """
    Simple Gmail notification handler.

    Directly calls MCP tools without using the complex agent.
    This is more reliable for simple auto-reply functionality.
    """
    try:
        result = await handle_new_email_notification(request.historyId)
        return result

    except Exception as e:
        logger.error(f"Gmail handler failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/diagnostic")
async def gmail_diagnostic():
    """
    Diagnostic endpoint to verify Gmail credentials configuration.

    Returns partial credential info (first/last chars) for debugging.
    Note: No auth required - only shows prefixes, not full credentials.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    user_token = os.getenv("USER_REFRESH_TOKEN", "")
    agent_token = os.getenv("AGENT_REFRESH_TOKEN", "")
    auth_emails = os.getenv("GMAIL_AUTHORIZED_EMAILS", "")

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    return {
        "google_client_id": {
            "set": bool(client_id),
            "prefix": client_id[:20] + "..." if len(client_id) > 20 else client_id,
            "length": len(client_id)
        },
        "google_client_secret": {
            "set": bool(client_secret),
            "prefix": client_secret[:10] + "..." if len(client_secret) > 10 else client_secret,
            "length": len(client_secret)
        },
        "user_refresh_token": {
            "set": bool(user_token),
            "prefix": user_token[:20] + "..." if len(user_token) > 20 else user_token,
            "length": len(user_token)
        },
        "agent_refresh_token": {
            "set": bool(agent_token),
            "prefix": agent_token[:20] + "..." if len(agent_token) > 20 else agent_token,
            "length": len(agent_token)
        },
        "anthropic_api_key": {
            "set": bool(anthropic_key),
            "prefix": anthropic_key[:15] + "..." if len(anthropic_key) > 15 else anthropic_key,
            "length": len(anthropic_key)
        },
        "gmail_authorized_emails": auth_emails,
        "assistant_email": os.getenv("ASSISTANT_EMAIL", ""),
        "agent_email": os.getenv("AGENT_EMAIL", ""),
        "user_google_email": os.getenv("USER_GOOGLE_EMAIL", "")
    }


@router.get("/debug-inbox")
async def gmail_debug_inbox(_: bool = Depends(verify_api_key)):
    """
    Debug endpoint to see what emails Railway can see in the agent's inbox.
    """
    config = get_config()
    processed_ids = load_processed_ids()

    try:
        async with MCPClient(
            command="/app/deploy/start-mcp-server.sh",
            args=[]
        ) as mcp:
            # Get agent access token
            agent_access_token = await get_access_token(mcp, config, "agent")
            if not agent_access_token:
                return {"error": "Failed to get agent access token"}

            # Get recent emails
            search_result = await mcp.call_tool("gmail_get_recent_emails", {
                "google_access_token": agent_access_token,
                "max_results": 5,
                "unread_only": True
            })

            result_data = json.loads(search_result)
            if isinstance(result_data, dict) and "emails" in result_data:
                emails = result_data["emails"]
            else:
                emails = result_data if isinstance(result_data, list) else []

            # Summarize emails
            email_summary = []
            for email in emails:
                email_id = email.get("id", "")
                email_summary.append({
                    "id": email_id,
                    "from": email.get("from", ""),
                    "to": email.get("to", ""),
                    "subject": email.get("subject", ""),
                    "already_processed": email_id in processed_ids
                })

            return {
                "success": True,
                "authorized_emails": config["authorized_emails"],
                "processed_ids_count": len(processed_ids),
                "processed_ids_sample": list(processed_ids)[:5],
                "emails_found": len(emails),
                "emails": email_summary
            }

    except Exception as e:
        return {"error": str(e)}


@router.post("/renew-watch")
async def renew_gmail_watch(request: GmailWatchRenewRequest, _: bool = Depends(verify_api_key)):
    """
    Renew Gmail push notification watch.

    Called by Vercel cron every 6 days to keep the watch active.
    Gmail watches expire after 7 days.
    """
    try:
        # Run the setup script
        script_path = project_root / "scripts" / "setup_gmail_watch.py"
        result = subprocess.run(
            [sys.executable, str(script_path),
             "--webhook-url", request.webhookUrl],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            logger.info(f"Gmail watch renewed successfully")
            return {
                "success": True,
                "message": "Gmail watch renewed",
                "output": result.stdout
            }
        else:
            logger.error(f"Gmail watch renewal failed: {result.stderr}")
            return {
                "success": False,
                "error": result.stderr or "Unknown error"
            }

    except subprocess.TimeoutExpired:
        logger.error("Gmail watch renewal timed out")
        return {
            "success": False,
            "error": "Timeout"
        }
    except Exception as e:
        logger.error(f"Gmail watch renewal failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/token-health")
async def gmail_token_health(_: bool = Depends(verify_api_key)):
    """
    Proactively test both Google OAuth refresh tokens.

    Returns the health status of each token (user + agent). If a token
    returns ``invalid_grant``, the response includes ``"expired": true``
    so monitoring can trigger a re-auth alert before email processing
    breaks silently.
    """
    config = get_config()
    results: dict = {}

    for token_type in ("user", "agent"):
        token_key = f"{token_type}_refresh_token"
        if not config.get(token_key):
            results[token_type] = {
                "healthy": False,
                "expired": False,
                "error": f"No {token_type} refresh token configured",
            }
            continue

        try:
            async with MCPClient(
                command="/app/deploy/start-mcp-server.sh",
                args=[],
                timeout=15,
            ) as mcp:
                access_token = await get_access_token(mcp, config, token_type)
                results[token_type] = {
                    "healthy": access_token is not None,
                    "expired": False,
                    "has_access_token": access_token is not None,
                }

        except TokenExpiredError as te:
            logger.warning("Token health check: %s token expired — %s", token_type, te)
            results[token_type] = {
                "healthy": False,
                "expired": True,
                "error": str(te),
            }

        except Exception as e:
            logger.error("Token health check error for %s: %s", token_type, e)
            results[token_type] = {
                "healthy": False,
                "expired": False,
                "error": str(e),
            }

    all_healthy = all(r.get("healthy") for r in results.values())
    any_expired = any(r.get("expired") for r in results.values())

    return {
        "healthy": all_healthy,
        "any_expired": any_expired,
        "tokens": results,
        "action_required": (
            "Re-authorize Google OAuth tokens via reauthorize_google.py"
            if any_expired
            else None
        ),
    }
