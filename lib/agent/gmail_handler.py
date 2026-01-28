"""
Gmail Handler - AI-Powered Email Responses (Headless MCP)

This module handles incoming Gmail notifications and generates intelligent
AI responses using the LangGraph agent with full context awareness.

Features:
- AI-generated responses via run_agent()
- File-based locking to prevent duplicate processing (race condition fix)
- Loop prevention (skips auto-replies, self-emails)
- Authorized sender filtering
- Uses headless Gmail MCP (credentials passed as tool parameters)
- Dual-token architecture: USER_REFRESH_TOKEN for reading, AGENT_REFRESH_TOKEN for sending
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

# Cross-platform file locking
if sys.platform == 'win32':
    import msvcrt
    LOCK_EX = msvcrt.LK_NBLCK
    LOCK_UN = msvcrt.LK_UNLCK
else:
    import fcntl
    LOCK_EX = fcntl.LOCK_EX | fcntl.LOCK_NB
    LOCK_UN = fcntl.LOCK_UN

logger = logging.getLogger(__name__)

# Subjects that indicate auto-replies (to prevent loops)
AUTO_REPLY_INDICATORS = [
    "sabine will respond soon",
    "automated acknowledgment",
    "auto-reply",
    "automatic reply",
    "out of office",
    "automated response",
    "do not reply",
    "noreply",
    "no-reply",
]

# Track processed message IDs to avoid duplicate replies
PROCESSED_FILE = Path(__file__).parent / ".processed_emails.json"
LOCK_FILE = Path(__file__).parent / ".processed_emails.lock"


def get_config() -> Dict[str, Any]:
    """
    Get configuration values at runtime (after .env is loaded).
    Returns dict with all config values.
    """
    config = {
        "assistant_email": os.getenv("ASSISTANT_EMAIL", "sabine@strugcity.com").lower(),
        "agent_email": os.getenv("AGENT_EMAIL", "sabine@strugcity.com").lower(),
        "user_google_email": os.getenv("USER_GOOGLE_EMAIL", "rknollmaier@gmail.com").lower(),
        "authorized_emails": [
            e.strip().lower()
            for e in os.getenv("GMAIL_AUTHORIZED_EMAILS", "").split(",")
            if e.strip()
        ],
        "user_id": os.getenv("AGENT_USER_ID") or os.getenv("DEFAULT_USER_ID", "00000000-0000-0000-0000-000000000001"),
        # OAuth credentials
        "google_client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "google_client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "user_refresh_token": os.getenv("USER_REFRESH_TOKEN", ""),
        "agent_refresh_token": os.getenv("AGENT_REFRESH_TOKEN", ""),
    }

    logger.debug(f"Config loaded - Assistant: {config['assistant_email']}, User: {config['user_google_email']}")
    logger.debug(f"Authorized emails: {config['authorized_emails']}")
    logger.debug(f"Client ID present: {bool(config['google_client_id'])}")
    logger.debug(f"User refresh token present: {bool(config['user_refresh_token'])}")
    logger.debug(f"Agent refresh token present: {bool(config['agent_refresh_token'])}")

    return config


def acquire_lock() -> Optional[Any]:
    """
    Acquire an exclusive lock to prevent race conditions.
    Returns file handle if successful, None if lock is held by another process.
    Cross-platform: works on Windows (msvcrt) and Unix (fcntl).
    """
    try:
        LOCK_FILE.touch(exist_ok=True)
        logger.debug(f"Lock file exists: {LOCK_FILE}")

        if sys.platform == 'win32':
            f = open(LOCK_FILE, 'r+')
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                logger.info("Lock acquired successfully (Windows)")
                return f
            except (IOError, OSError) as e:
                logger.info(f"Lock already held by another process (Windows): {e}")
                f.close()
                return None
        else:
            fd = os.open(str(LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o666)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.info("Lock acquired successfully (Unix)")
                return fd
            except (BlockingIOError, OSError) as e:
                logger.info(f"Lock already held by another process (Unix): {e}")
                os.close(fd)
                return None

    except Exception as e:
        logger.error(f"Error acquiring lock: {e}", exc_info=True)
        return None


def release_lock(lock_handle: Any):
    """Release the lock. Cross-platform."""
    try:
        if sys.platform == 'win32':
            if hasattr(lock_handle, 'fileno'):
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                lock_handle.close()
                logger.debug("Lock released (Windows)")
        else:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)
            os.close(lock_handle)
            logger.debug("Lock released (Unix)")
    except Exception as e:
        logger.warning(f"Error releasing lock: {e}")


def load_processed_ids() -> Set[str]:
    """Load set of already processed message IDs."""
    try:
        if PROCESSED_FILE.exists():
            data = json.loads(PROCESSED_FILE.read_text())
            return set(data.get("ids", [])[-1000:])
    except Exception as e:
        logger.warning(f"Could not load processed IDs: {e}")
    return set()


def save_processed_id(message_id: str):
    """Save a processed message ID."""
    try:
        ids = load_processed_ids()
        ids.add(message_id)
        id_list = list(ids)[-1000:]
        PROCESSED_FILE.write_text(json.dumps({"ids": id_list}))
    except Exception as e:
        logger.warning(f"Could not save processed ID: {e}")


def extract_sender_email(message_content: str) -> Optional[str]:
    """Extract sender email from message content."""
    patterns = [
        r'From:\s*[^<]*<([^>]+)>',
        r'From:\s*([^\s<>]+@[^\s<>]+)',
        r'from[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    ]

    for pattern in patterns:
        match = re.search(pattern, message_content, re.IGNORECASE)
        if match:
            return match.group(1).lower().strip()

    return None


def extract_sender_name(message_content: str) -> Optional[str]:
    """Extract sender name from message content."""
    match = re.search(r'From:\s*([^<]+)<[^>]+>', message_content, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name and name != "":
            return name
    return None


def extract_message_id(result: str) -> Optional[str]:
    """Extract message ID from get_recent_emails result (JSON format)."""
    try:
        # Try parsing as JSON first (headless-gmail returns JSON)
        data = json.loads(result)
        if isinstance(data, list) and len(data) > 0:
            return data[0].get("id") or data[0].get("message_id")
        if isinstance(data, dict):
            return data.get("id") or data.get("message_id")
    except json.JSONDecodeError:
        pass

    # Fallback to regex patterns
    patterns = [
        r'"id"\s*:\s*"([^"]+)"',
        r'"message_id"\s*:\s*"([^"]+)"',
        r'ID[:\s]+([a-zA-Z0-9]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_subject(message_content: str) -> Optional[str]:
    """Extract subject from message content."""
    # Try JSON format first
    try:
        data = json.loads(message_content)
        if isinstance(data, dict):
            return data.get("subject")
    except json.JSONDecodeError:
        pass

    # Fallback to header parsing
    match = re.search(r'Subject:\s*(.+?)(?:\n|$)', message_content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def extract_body(message_content: str) -> str:
    """Extract email body from message content."""
    # Try JSON format first (headless-gmail returns structured data)
    try:
        data = json.loads(message_content)
        if isinstance(data, dict):
            body = data.get("body") or data.get("snippet") or data.get("body_preview") or ""
            return body.strip()
    except json.JSONDecodeError:
        pass

    # Fallback to header parsing (after headers)
    parts = re.split(r'\n\n|\r\n\r\n', message_content, maxsplit=1)
    if len(parts) > 1:
        body = parts[1].strip()
        lines = body.split('\n')
        clean_lines = []
        for line in lines:
            if line.strip().startswith('>'):
                break
            clean_lines.append(line)
        return '\n'.join(clean_lines).strip()
    return message_content.strip()


async def get_access_token(mcp, config: Dict[str, Any], token_type: str = "user") -> Optional[str]:
    """
    Get a fresh access token using the refresh token.

    Args:
        mcp: MCPClient instance
        config: Configuration dict with credentials
        token_type: "user" for USER_REFRESH_TOKEN, "agent" for AGENT_REFRESH_TOKEN

    Returns:
        Access token string or None if failed
    """
    refresh_token = config["user_refresh_token"] if token_type == "user" else config["agent_refresh_token"]

    if not refresh_token:
        logger.error(f"No {token_type} refresh token configured")
        return None

    try:
        result = await mcp.call_tool("gmail_refresh_token", {
            "google_refresh_token": refresh_token,
            "google_client_id": config["google_client_id"],
            "google_client_secret": config["google_client_secret"],
        })

        # Parse result to get access token
        try:
            data = json.loads(result)
            access_token = data.get("access_token")
            if access_token:
                logger.info(f"Successfully refreshed {token_type} access token")
                return access_token
        except json.JSONDecodeError:
            # Try regex fallback
            match = re.search(r'"access_token"\s*:\s*"([^"]+)"', result)
            if match:
                logger.info(f"Successfully refreshed {token_type} access token (regex)")
                return match.group(1)

        logger.error(f"Could not extract access token from refresh result: {result[:200]}")
        return None

    except Exception as e:
        logger.error(f"Error refreshing {token_type} token: {e}")
        return None


async def generate_ai_response(
    sender_email: str,
    sender_name: Optional[str],
    subject: str,
    body: str,
    user_id: str
) -> str:
    """
    Generate an AI response using the LangGraph agent.
    """
    # Import here to avoid circular imports
    from lib.agent.core import run_agent

    sender_display = sender_name if sender_name else sender_email

    agent_prompt = f"""You received a new email that needs a response. Please compose a helpful, friendly reply.

**From:** {sender_display} <{sender_email}>
**Subject:** {subject}

**Email Body:**
{body}

---

Instructions for your response:
1. Address the sender by their first name if known, otherwise use a friendly greeting
2. Be helpful and provide relevant information based on the email content
3. If they are asking about weather, use your weather tool to get accurate information
4. If they are asking about schedule or calendar, check the relevant information
5. Keep your response concise but complete
6. Sign off warmly as Sabine assistant

Please write ONLY the email body (no subject line, no 'To:' header). The response will be sent directly."""

    try:
        session_id = f"email-response-{int(time.time())}"

        result = await run_agent(
            user_id=user_id,
            session_id=session_id,
            user_message=agent_prompt,
            conversation_history=None,
            use_caching=False
        )

        if result.get("success") and result.get("response"):
            logger.info(f"AI generated response ({len(result['response'])} chars)")
            return result["response"]
        else:
            logger.error(f"Agent failed: {result.get('error', 'Unknown error')}")
            return generate_fallback_response(sender_name or "there", subject)

    except Exception as e:
        logger.error(f"Error generating AI response: {e}")
        return generate_fallback_response(sender_name or "there", subject)


def generate_fallback_response(sender_name: str, subject: str) -> str:
    """Generate a fallback response if AI generation fails."""
    return f"""Hi {sender_name},

Thank you for your email regarding "{subject}".

I've received your message and will review it shortly. I'll get back to you with a more detailed response soon.

Best regards,
Sabine Assistant
"""


async def handle_new_email_notification(history_id: str) -> Dict[str, Any]:
    """
    Handle a new email notification by:
    1. Acquiring a lock to prevent race conditions
    2. Finding the most recent inbox email from an authorized sender (using USER token)
    3. Generating an AI response using the LangGraph agent
    4. Sending the response via MCP (using AGENT token)
    5. Tracking processed emails to avoid duplicates

    Returns:
        Dict with status and details
    """
    # Import here to avoid circular imports
    from lib.agent.mcp_client import MCPClient

    logger.info(f"Handling email notification for historyId: {history_id}")

    lock_fd = acquire_lock()
    if lock_fd is None:
        logger.info("Another process is handling email notifications, skipping")
        return {"success": True, "action": "skipped_concurrent"}

    try:
        config = get_config()

        # Validate credentials
        if not config["google_client_id"] or not config["google_client_secret"]:
            logger.error("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET")
            return {"success": False, "error": "Missing OAuth credentials"}

        if not config["user_refresh_token"]:
            logger.error("Missing USER_REFRESH_TOKEN")
            return {"success": False, "error": "Missing user refresh token"}

        if not config["agent_refresh_token"]:
            logger.error("Missing AGENT_REFRESH_TOKEN")
            return {"success": False, "error": "Missing agent refresh token"}

        processed_ids = load_processed_ids()

        # Use MCPClient context manager to keep session open for all tool calls
        async with MCPClient(
            command="/app/deploy/start-mcp-server.sh",
            args=[]  # headless-gmail doesn't need --transport stdio flag
        ) as mcp:
            # Get access tokens
            logger.info("Refreshing user access token...")
            user_access_token = await get_access_token(mcp, config, "user")
            if not user_access_token:
                return {"success": False, "error": "Failed to get user access token"}

            logger.info("Refreshing agent access token...")
            agent_access_token = await get_access_token(mcp, config, "agent")
            if not agent_access_token:
                return {"success": False, "error": "Failed to get agent access token"}

            # Search for recent inbox emails in AGENT's inbox (sabine@strugcity.com)
            # This is where user emails TO Sabine arrive
            logger.info("Getting recent emails from agent's inbox (sabine@strugcity.com)...")
            search_result = await mcp.call_tool("gmail_get_recent_emails", {
                "google_access_token": agent_access_token,
                "max_results": 10,
                "unread_only": True
            })

            if not search_result:
                logger.error("get_recent_emails returned empty result")
                return {"success": False, "error": "Failed to search emails"}

            logger.info(f"get_recent_emails result: {search_result[:500]}...")

            # Parse result - response format is {"emails": [...]}
            try:
                result_data = json.loads(search_result)
                # Handle {"emails": [...]} format
                if isinstance(result_data, dict) and "emails" in result_data:
                    emails = result_data["emails"]
                elif isinstance(result_data, list):
                    emails = result_data
                else:
                    emails = []

                if not emails or len(emails) == 0:
                    logger.info("No recent unread emails found")
                    return {"success": True, "action": "no_emails"}
            except json.JSONDecodeError:
                if "No messages" in search_result or "0 messages" in search_result.lower():
                    logger.info("No recent inbox emails found")
                    return {"success": True, "action": "no_emails"}
                emails = []

            # Get first email
            if len(emails) > 0:
                email_data = emails[0]
                message_id = email_data.get("id") or email_data.get("message_id")
                sender = email_data.get("from", "").lower()
                subject = email_data.get("subject", "")
                body_preview = email_data.get("body") or email_data.get("snippet", "")
            else:
                logger.warning("No emails in parsed result")
                return {"success": True, "action": "no_parseable_emails"}

            if not message_id:
                logger.warning("Could not extract message ID from result")
                return {"success": True, "action": "no_parseable_message"}

            if message_id in processed_ids:
                logger.info(f"Message {message_id} already processed, skipping")
                return {"success": True, "action": "already_processed", "message_id": message_id}

            save_processed_id(message_id)
            logger.info(f"Message {message_id} marked as processing")

            # Get full message content if needed (from agent's inbox)
            if not sender or not body_preview:
                logger.info(f"Getting full content for message {message_id}...")
                message_content = await mcp.call_tool("gmail_get_email_body_chunk", {
                    "google_access_token": agent_access_token,
                    "message_id": message_id
                })

                if message_content:
                    try:
                        content_data = json.loads(message_content)
                        if not sender:
                            sender = content_data.get("from", "").lower()
                        if not subject:
                            subject = content_data.get("subject", "")
                        if not body_preview:
                            body_preview = content_data.get("body", "")
                    except json.JSONDecodeError:
                        if not sender:
                            sender = extract_sender_email(message_content)
                        if not subject:
                            subject = extract_subject(message_content)
                        if not body_preview:
                            body_preview = extract_body(message_content)

            # Extract sender email if we have a "Name <email>" format
            if sender and '<' in sender:
                match = re.search(r'<([^>]+)>', sender)
                if match:
                    sender_name = sender.split('<')[0].strip()
                    sender = match.group(1).lower()
                else:
                    sender_name = None
            else:
                sender_name = None

            if not sender:
                logger.warning("Could not determine sender")
                return {"success": False, "error": "Could not determine sender"}

            logger.info(f"Sender: {sender_name} <{sender}>")

            # Loop prevention: skip self-emails
            if sender == config["assistant_email"] or sender == config["agent_email"]:
                logger.info(f"Sender is the assistant ({sender}), skipping to prevent loop")
                return {"success": True, "action": "self_email_skipped", "sender": sender}

            # Authorization check
            if sender not in config["authorized_emails"]:
                logger.info(f"Sender {sender} not in authorized list {config['authorized_emails']}, skipping reply")
                return {"success": True, "action": "unauthorized_sender", "sender": sender}

            original_subject = subject or ""
            subject_lower = original_subject.lower()

            # Loop prevention: skip auto-replies
            for indicator in AUTO_REPLY_INDICATORS:
                if indicator in subject_lower:
                    logger.info(f"Subject contains auto-reply indicator '{indicator}', skipping to prevent loop")
                    return {"success": True, "action": "auto_reply_skipped", "subject": original_subject}

            # Loop prevention: skip noreply addresses
            if any(ind in sender for ind in ['noreply', 'no-reply', 'donotreply', 'mailer-daemon']):
                logger.info(f"Sender {sender} appears to be a no-reply address, skipping")
                return {"success": True, "action": "noreply_sender_skipped", "sender": sender}

            email_body = body_preview or ""
            logger.info(f"Email body ({len(email_body)} chars): {email_body[:200]}...")

            if not original_subject:
                original_subject = "your email"
            reply_subject = f"Re: {original_subject}" if not original_subject.lower().startswith("re:") else original_subject

            # Generate AI response
            logger.info(f"Generating AI response for email from {sender}...")
            ai_response = await generate_ai_response(
                sender_email=sender,
                sender_name=sender_name,
                subject=original_subject,
                body=email_body,
                user_id=config["user_id"]
            )

            logger.info(f"AI response: {ai_response[:200]}...")

            # Send reply using AGENT token (sends FROM sabine@strugcity.com)
            logger.info(f"Sending AI-generated reply to {sender} from agent account...")
            send_result = await mcp.call_tool("gmail_send_email", {
                "google_access_token": agent_access_token,
                "to": sender,
                "subject": reply_subject,
                "body": ai_response
            })

            logger.info(f"Send result: {send_result}")

            if send_result and ("success" in send_result.lower() or "sent" in send_result.lower() or "id" in send_result.lower()):
                logger.info(f"AI response sent to {sender}")
                return {
                    "success": True,
                    "action": "replied",
                    "recipient": sender,
                    "message_id": message_id,
                    "subject": reply_subject,
                    "response_type": "ai_generated"
                }
            else:
                logger.warning(f"Failed to send reply to {sender}: {send_result}")
                return {"success": False, "error": f"Failed to send reply: {send_result}"}

    except Exception as e:
        logger.error(f"Error handling email notification: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    finally:
        if lock_fd is not None:
            release_lock(lock_fd)
