"""
Gmail Handler - AI-Powered Email Responses

This module handles incoming Gmail notifications and generates intelligent
AI responses using the LangGraph agent with full context awareness.

Features:
- AI-generated responses via run_agent()
- File-based locking to prevent duplicate processing (race condition fix)
- Loop prevention (skips auto-replies, self-emails)
- Authorized sender filtering
"""

import asyncio
import json
import logging
import os
import re
import sys
import httpx
import time
from pathlib import Path
from typing import Optional, Dict, Any, Set, List, Union

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


def get_config() -> tuple[str, str, List[str], str]:
    """
    Get configuration values at runtime (after .env is loaded).
    Returns: (mcp_server_url, assistant_email, authorized_emails, user_id)
    """
    mcp_server_url = os.getenv("MCP_SERVERS", "http://localhost:8000/mcp").split(",")[0]
    assistant_email = os.getenv("ASSISTANT_EMAIL", "sabine@strugcity.com").lower()
    authorized_raw = os.getenv("GMAIL_AUTHORIZED_EMAILS", "")
    authorized_emails = [e.strip().lower() for e in authorized_raw.split(",") if e.strip()]
    # User ID for agent context (from Supabase) - use DEFAULT_USER_ID as fallback
    user_id = os.getenv("AGENT_USER_ID") or os.getenv("DEFAULT_USER_ID", "00000000-0000-0000-0000-000000000001")

    logger.debug(f"Config loaded - MCP: {mcp_server_url}, Assistant: {assistant_email}, Authorized: {authorized_emails}")

    return mcp_server_url, assistant_email, authorized_emails, user_id


def acquire_lock() -> Optional[Any]:
    """
    Acquire an exclusive lock to prevent race conditions.
    Returns file handle if successful, None if lock is held by another process.
    Cross-platform: works on Windows (msvcrt) and Unix (fcntl).
    """
    try:
        # Ensure lock file exists
        LOCK_FILE.touch(exist_ok=True)

        if sys.platform == 'win32':
            # Windows: use msvcrt for file locking
            f = open(LOCK_FILE, 'r+')
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return f
            except (IOError, OSError):
                f.close()
                return None
        else:
            # Unix: use fcntl for file locking
            fd = os.open(str(LOCK_FILE), os.O_RDWR)
            try:
                fcntl.flock(fd, LOCK_EX)
                return fd
            except (BlockingIOError, OSError):
                os.close(fd)
                return None

    except Exception as e:
        logger.info(f"Could not acquire lock (another process is handling): {e}")
        return None


def release_lock(lock_handle: Any):
    """Release the lock. Cross-platform."""
    try:
        if sys.platform == 'win32':
            # Windows: unlock and close file handle
            if hasattr(lock_handle, 'fileno'):
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                lock_handle.close()
        else:
            # Unix: unlock and close file descriptor
            fcntl.flock(lock_handle, LOCK_UN)
            os.close(lock_handle)
    except Exception as e:
        logger.warning(f"Error releasing lock: {e}")


def load_processed_ids() -> Set[str]:
    """Load set of already processed message IDs."""
    try:
        if PROCESSED_FILE.exists():
            data = json.loads(PROCESSED_FILE.read_text())
            # Keep only last 1000 IDs to prevent unbounded growth
            return set(data.get("ids", [])[-1000:])
    except Exception as e:
        logger.warning(f"Could not load processed IDs: {e}")
    return set()


def save_processed_id(message_id: str):
    """Save a processed message ID."""
    try:
        ids = load_processed_ids()
        ids.add(message_id)
        # Keep only last 1000
        id_list = list(ids)[-1000:]
        PROCESSED_FILE.write_text(json.dumps({"ids": id_list}))
    except Exception as e:
        logger.warning(f"Could not save processed ID: {e}")


async def initialize_mcp_session() -> Optional[str]:
    """Initialize MCP session and return session ID."""
    mcp_server_url, _, _, _ = get_config()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                mcp_server_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "gmail-handler", "version": "1.0.0"}
                    }
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            )

            if response.status_code == 200:
                session_id = response.headers.get("mcp-session-id")
                logger.info(f"MCP session initialized: {session_id}")
                return session_id

    except Exception as e:
        logger.error(f"Failed to initialize MCP session: {e}")

    return None


async def call_mcp_tool(session_id: str, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Call an MCP tool and return the result."""
    mcp_server_url, assistant_email, _, _ = get_config()
    try:
        # Auto-inject email for Gmail tools
        if tool_name.startswith(('search_gmail', 'get_gmail', 'send_gmail', 'list_gmail')):
            if 'user_google_email' not in arguments:
                arguments['user_google_email'] = assistant_email

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                mcp_server_url,
                json={
                    "jsonrpc": "2.0",
                    "id": f"call_{tool_name}",
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": session_id
                }
            )

            if response.status_code == 200:
                # Parse SSE response
                lines = response.text.strip().split('\n')
                for line in lines:
                    if line.startswith('data: '):
                        data = json.loads(line[6:])

                        if "result" in data:
                            result = data["result"]
                            if isinstance(result, dict) and "content" in result:
                                content = result["content"]
                                if isinstance(content, list) and len(content) > 0:
                                    return content[0].get("text", str(result))
                                return str(content)
                            return str(result)
                        elif "error" in data:
                            error_msg = data["error"].get("message", "Unknown error")
                            logger.error(f"MCP tool error: {error_msg}")
                            return None

    except Exception as e:
        logger.error(f"Error calling MCP tool {tool_name}: {e}")

    return None


def extract_sender_email(message_content: str) -> Optional[str]:
    """Extract sender email from message content."""
    # Look for From: header patterns
    patterns = [
        r'From:\s*[^<]*<([^>]+)>',  # From: Name <email@example.com>
        r'From:\s*([^\s<>]+@[^\s<>]+)',  # From: email@example.com
        r'from[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',  # from: email
    ]

    for pattern in patterns:
        match = re.search(pattern, message_content, re.IGNORECASE)
        if match:
            return match.group(1).lower().strip()

    return None


def extract_sender_name(message_content: str) -> Optional[str]:
    """Extract sender name from message content."""
    # Look for From: Name <email> pattern
    match = re.search(r'From:\s*([^<]+)<[^>]+>', message_content, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if name and name != "":
            return name
    return None


def extract_message_id(search_result: str) -> Optional[str]:
    """Extract message ID from search result."""
    # Look for message ID patterns like "ID: abc123" or "Message ID: abc123"
    patterns = [
        r'ID[:\s]+([a-zA-Z0-9]+)',
        r'message[_\s]?id[:\s]+([a-zA-Z0-9]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, search_result, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_subject(message_content: str) -> Optional[str]:
    """Extract subject from message content."""
    match = re.search(r'Subject:\s*(.+?)(?:\n|$)', message_content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def extract_body(message_content: str) -> str:
    """Extract email body from message content (after headers)."""
    # Try to find body after double newline (end of headers)
    parts = re.split(r'\n\n|\r\n\r\n', message_content, maxsplit=1)
    if len(parts) > 1:
        body = parts[1].strip()
        # Clean up any remaining metadata
        # Remove quoted replies (lines starting with >)
        lines = body.split('\n')
        clean_lines = []
        for line in lines:
            if line.strip().startswith('>'):
                break  # Stop at quoted reply
            clean_lines.append(line)
        return '\n'.join(clean_lines).strip()
    return message_content.strip()


async def generate_ai_response(
    sender_email: str,
    sender_name: Optional[str],
    subject: str,
    body: str,
    user_id: str
) -> str:
    """
    Generate an AI response using the LangGraph agent.

    This calls the run_agent function from core.py which:
    - Loads deep context (user rules, custody schedule, memories)
    - Has access to all MCP tools (weather, calendar, etc.)
    - Can perform multi-step reasoning
    """
    from lib.agent.core import run_agent

    # Format the email as a message for the agent
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
3. If they're asking about weather, use your weather tool to get accurate information
4. If they're asking about schedule or calendar, check the relevant information
5. Keep your response concise but complete
6. Sign off warmly as Sabine's assistant

Please write ONLY the email body (no subject line, no "To:" header). The response will be sent directly."""

    try:
        # Generate a unique session ID for this email response
        session_id = f"email-response-{int(time.time())}"

        result = await run_agent(
            user_id=user_id,
            session_id=session_id,
            user_message=agent_prompt,
            conversation_history=None,
            use_caching=False  # Use full agent with tools
        )

        if result.get("success") and result.get("response"):
            logger.info(f"AI generated response ({len(result['response'])} chars)")
            return result["response"]
        else:
            logger.error(f"Agent failed: {result.get('error', 'Unknown error')}")
            # Fall back to generic response
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
Sabine's Assistant"""


async def handle_new_email_notification(history_id: str) -> Dict[str, Any]:
    """
    Handle a new email notification by:
    1. Acquiring a lock to prevent race conditions
    2. Finding the most recent inbox email from an authorized sender
    3. Generating an AI response using the LangGraph agent
    4. Sending the response via MCP
    5. Tracking processed emails to avoid duplicates

    Returns:
        Dict with status and details
    """
    logger.info(f"Handling email notification for historyId: {history_id}")

    # Try to acquire lock - if we can't, another process is handling this
    lock_fd = acquire_lock()
    if lock_fd is None:
        logger.info("Another process is handling email notifications, skipping")
        return {"success": True, "action": "skipped_concurrent"}

    try:
        # Get config at runtime (after .env is loaded)
        _, assistant_email, authorized_emails, user_id = get_config()
        logger.info(f"Authorized emails: {authorized_emails}")

        # Initialize MCP session
        session_id = await initialize_mcp_session()
        if not session_id:
            return {"success": False, "error": "Failed to initialize MCP session"}

        processed_ids = load_processed_ids()

        # Search for recent inbox emails (includes both read and unread)
        # This catches emails even if they were auto-marked as read
        logger.info("Searching for recent inbox emails...")
        search_result = await call_mcp_tool(
            session_id,
            "search_gmail_messages",
            {"query": "in:inbox newer_than:1h -from:me"}
        )

        if not search_result:
            logger.error("Search returned empty result")
            return {"success": False, "error": "Failed to search emails"}

        # Check if no emails found
        if "No messages found" in search_result or "0 messages" in search_result.lower():
            logger.info("No recent inbox emails found")
            return {"success": True, "action": "no_emails"}

        logger.info(f"Search result: {search_result[:300]}...")

        # Extract message ID from search result
        message_id = extract_message_id(search_result)
        if not message_id:
            logger.warning("Could not extract message ID from search result")
            return {"success": True, "action": "no_parseable_message"}

        # Check if already processed (race condition prevention)
        if message_id in processed_ids:
            logger.info(f"Message {message_id} already processed, skipping")
            return {"success": True, "action": "already_processed", "message_id": message_id}

        # Mark as processing IMMEDIATELY to prevent race conditions
        save_processed_id(message_id)
        logger.info(f"Message {message_id} marked as processing")

        # Get full message content to find sender
        logger.info(f"Getting content for message {message_id}...")
        message_content = await call_mcp_tool(
            session_id,
            "get_gmail_message_content",
            {"message_id": message_id}
        )

        if not message_content:
            logger.warning(f"Could not get content for message {message_id}")
            return {"success": False, "error": "Failed to get message content"}

        logger.info(f"Message content: {message_content[:500]}...")

        # Extract sender
        sender = extract_sender_email(message_content)
        if not sender:
            logger.warning("Could not extract sender from message")
            return {"success": False, "error": "Could not determine sender"}

        sender_name = extract_sender_name(message_content)
        logger.info(f"Sender: {sender_name} <{sender}>")

        # LOOP PREVENTION: Skip if sender is the assistant itself
        if sender.lower() == assistant_email:
            logger.info(f"Sender is the assistant ({sender}), skipping to prevent loop")
            return {"success": True, "action": "self_email_skipped", "sender": sender}

        # Check if sender is authorized
        if sender.lower() not in authorized_emails:
            logger.info(f"Sender {sender} not in authorized list, skipping reply")
            return {"success": True, "action": "unauthorized_sender", "sender": sender}

        # LOOP PREVENTION: Check if this is an auto-reply (check subject and sender)
        original_subject = extract_subject(message_content) or ""
        subject_lower = original_subject.lower()

        for indicator in AUTO_REPLY_INDICATORS:
            if indicator in subject_lower:
                logger.info(f"Subject contains auto-reply indicator '{indicator}', skipping to prevent loop")
                return {"success": True, "action": "auto_reply_skipped", "subject": original_subject}

        # Also check if sender email contains noreply indicators
        if any(ind in sender.lower() for ind in ['noreply', 'no-reply', 'donotreply', 'mailer-daemon']):
            logger.info(f"Sender {sender} appears to be a no-reply address, skipping")
            return {"success": True, "action": "noreply_sender_skipped", "sender": sender}

        # Extract email body
        email_body = extract_body(message_content)
        logger.info(f"Email body ({len(email_body)} chars): {email_body[:200]}...")

        # Build reply subject
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
            user_id=user_id
        )

        logger.info(f"AI response: {ai_response[:200]}...")

        # Send reply to the actual sender
        logger.info(f"Sending AI-generated reply to {sender}...")
        send_result = await call_mcp_tool(
            session_id,
            "send_gmail_message",
            {
                "to": sender,
                "subject": reply_subject,
                "body": ai_response
            }
        )

        if send_result and ("sent" in send_result.lower() or "message id" in send_result.lower()):
            logger.info(f"✓ AI response sent to {sender}")
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
        # Always release the lock
        if lock_fd is not None:
            release_lock(lock_fd)
