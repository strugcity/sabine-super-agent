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
- Supabase-backed tracking for persistence across Railway deploys
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Set

from supabase import create_client, Client

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

# Initialize Supabase client for persistent tracking
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_supabase: Optional[Client] = None

def get_supabase() -> Optional[Client]:
    """Get or create Supabase client."""
    global _supabase
    if _supabase is None and SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
            logger.info("Supabase client initialized for email tracking")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase: {e}")
    return _supabase

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

# Sender patterns to ignore (automated systems, notifications, etc.)
BLOCKED_SENDER_PATTERNS = [
    "noreply",
    "no-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "notifications",
    "notification",
    "alert",
    "alerts",
    "system",
    "admin",
    "support",
    "help",
    "info@",
    "news@",
    "newsletter",
    "marketing",
    "promo",
    # Educational platforms
    "schoology",
    "canvas",
    "blackboard",
    "powerschool",
    "infinite campus",
    "skyward",
    "schoolmessenger",
    "parentvue",
    "studentvue",
    "remind",
    "classdojo",
    "seesaw",
    "google classroom",
    "assignment",
    "graded",
]

# Subject patterns to ignore (notifications, automated messages)
BLOCKED_SUBJECT_PATTERNS = [
    "assignment graded",
    "grade posted",
    "grades are available",
    "new grade",
    "quiz grade",
    "test grade",
    "assignment due",
    "reminder:",
    "notification:",
    "alert:",
    "password reset",
    "verify your email",
    "confirm your",
    "welcome to",
    "your order",
    "order confirmation",
    "shipping confirmation",
    "delivery notification",
    "payment received",
    "invoice",
    "receipt",
    "subscription",
    "unsubscribe",
]

# =============================================================================
# In-memory caches for fast duplicate detection (prevents race conditions)
# These supplement the Supabase/file-based tracking
# =============================================================================

# In-memory cache of message IDs currently being processed (prevents race conditions)
_processing_messages: Set[str] = set()
_processing_lock = asyncio.Lock() if 'asyncio' in dir() else None

# In-memory cache for quick duplicate checks (populated on first load)
_cached_processed_ids: Optional[Set[str]] = None
_cached_replied_threads: Optional[Set[str]] = None
_cache_loaded_at: Optional[datetime] = None
_CACHE_TTL_SECONDS = 60  # Refresh cache every 60 seconds

def _get_cached_processed_ids() -> Set[str]:
    """Get cached processed IDs, refreshing if stale."""
    global _cached_processed_ids, _cache_loaded_at
    now = datetime.now()
    if _cached_processed_ids is None or _cache_loaded_at is None or \
       (now - _cache_loaded_at).total_seconds() > _CACHE_TTL_SECONDS:
        _cached_processed_ids = load_processed_ids()
        _cache_loaded_at = now
        logger.debug(f"Refreshed processed IDs cache: {len(_cached_processed_ids)} entries")
    return _cached_processed_ids

def _get_cached_replied_threads() -> Set[str]:
    """Get cached replied threads, refreshing if stale."""
    global _cached_replied_threads, _cache_loaded_at
    now = datetime.now()
    if _cached_replied_threads is None or _cache_loaded_at is None or \
       (now - _cache_loaded_at).total_seconds() > _CACHE_TTL_SECONDS:
        _cached_replied_threads = load_replied_threads()
        _cache_loaded_at = now
        logger.debug(f"Refreshed replied threads cache: {len(_cached_replied_threads)} entries")
    return _cached_replied_threads

def _add_to_cache(message_id: Optional[str] = None, thread_id: Optional[str] = None):
    """Add ID to in-memory cache immediately (before DB write completes)."""
    global _cached_processed_ids, _cached_replied_threads
    if message_id and _cached_processed_ids is not None:
        _cached_processed_ids.add(message_id)
    if thread_id and _cached_replied_threads is not None:
        _cached_replied_threads.add(thread_id)

# =============================================================================
# Supabase-backed tracking (persists across Railway deploys)
# =============================================================================

def load_replied_threads() -> Set[str]:
    """Load thread IDs we've replied to from Supabase."""
    threads = set()

    # Try Supabase first
    supabase = get_supabase()
    if supabase:
        try:
            # Get threads from last 7 days
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            response = supabase.table("email_tracking") \
                .select("thread_id") \
                .eq("tracking_type", "replied_thread") \
                .gte("created_at", cutoff) \
                .execute()

            if response.data:
                threads = set(row["thread_id"] for row in response.data if row.get("thread_id"))
                logger.info(f"Loaded {len(threads)} replied threads from Supabase")
        except Exception as e:
            logger.warning(f"Could not load threads from Supabase: {e}")

    # Also load from local file and merge (belt and suspenders)
    try:
        local_file = Path(__file__).parent / ".replied_threads.json"
        if local_file.exists():
            data = json.loads(local_file.read_text())
            local_threads = set(data.get("threads", [])[-500:])
            threads = threads.union(local_threads)
            logger.debug(f"Merged {len(local_threads)} local threads, total: {len(threads)}")
    except Exception as e:
        logger.warning(f"Could not load local replied threads: {e}")

    return threads


def save_replied_thread(thread_id: str):
    """Save a thread ID to Supabase (and local file as backup)."""
    if not thread_id:
        logger.warning("Attempted to save empty thread_id, skipping")
        return

    # IMMEDIATELY add to in-memory cache to prevent race conditions
    _add_to_cache(thread_id=thread_id)
    logger.debug(f"Added thread {thread_id} to in-memory cache")

    # Save to Supabase - use INSERT with conflict handling instead of upsert
    supabase = get_supabase()
    if supabase:
        try:
            # First check if it already exists
            existing = supabase.table("email_tracking") \
                .select("id") \
                .eq("thread_id", thread_id) \
                .eq("tracking_type", "replied_thread") \
                .execute()

            if not existing.data:
                # Insert new record
                supabase.table("email_tracking").insert({
                    "thread_id": thread_id,
                    "tracking_type": "replied_thread",
                    "created_at": datetime.now().isoformat()
                }).execute()
                logger.info(f"Saved thread {thread_id} to Supabase")
            else:
                logger.debug(f"Thread {thread_id} already exists in Supabase")
        except Exception as e:
            # Log but don't fail - local file is backup
            logger.warning(f"Could not save thread to Supabase: {e}")

    # Also save to local file as backup (always, even if Supabase succeeds)
    try:
        local_file = Path(__file__).parent / ".replied_threads.json"
        threads = set()
        if local_file.exists():
            data = json.loads(local_file.read_text())
            threads = set(data.get("threads", []))
        threads.add(thread_id)
        thread_list = list(threads)[-500:]
        local_file.write_text(json.dumps({"threads": thread_list}))
        logger.debug(f"Saved thread {thread_id} to local file")
    except Exception as e:
        logger.warning(f"Could not save local replied thread: {e}")


def load_processed_ids() -> Set[str]:
    """Load processed message IDs from Supabase."""
    ids = set()

    # Try Supabase first
    supabase = get_supabase()
    if supabase:
        try:
            # Get IDs from last 7 days
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            response = supabase.table("email_tracking") \
                .select("message_id") \
                .eq("tracking_type", "processed_message") \
                .gte("created_at", cutoff) \
                .execute()

            if response.data:
                ids = set(row["message_id"] for row in response.data if row.get("message_id"))
                logger.info(f"Loaded {len(ids)} processed IDs from Supabase")
        except Exception as e:
            logger.warning(f"Could not load IDs from Supabase: {e}")

    # Also load from local file and merge (belt and suspenders)
    try:
        local_file = Path(__file__).parent / ".processed_emails.json"
        if local_file.exists():
            data = json.loads(local_file.read_text())
            local_ids = set(data.get("ids", [])[-1000:])
            ids = ids.union(local_ids)
            logger.debug(f"Merged {len(local_ids)} local IDs, total: {len(ids)}")
    except Exception as e:
        logger.warning(f"Could not load local processed IDs: {e}")

    return ids


def save_processed_id(message_id: str):
    """Save a processed message ID to Supabase (and local file as backup)."""
    if not message_id:
        logger.warning("Attempted to save empty message_id, skipping")
        return

    # IMMEDIATELY add to in-memory cache to prevent race conditions
    _add_to_cache(message_id=message_id)
    logger.debug(f"Added message {message_id} to in-memory cache")

    # Save to Supabase - use INSERT with conflict handling
    supabase = get_supabase()
    if supabase:
        try:
            # First check if it already exists
            existing = supabase.table("email_tracking") \
                .select("id") \
                .eq("message_id", message_id) \
                .eq("tracking_type", "processed_message") \
                .execute()

            if not existing.data:
                # Insert new record
                supabase.table("email_tracking").insert({
                    "message_id": message_id,
                    "tracking_type": "processed_message",
                    "created_at": datetime.now().isoformat()
                }).execute()
                logger.debug(f"Saved message {message_id} to Supabase")
            else:
                logger.debug(f"Message {message_id} already exists in Supabase")
        except Exception as e:
            # Log but don't fail - local file is backup
            logger.warning(f"Could not save message to Supabase: {e}")

    # Also save to local file as backup (always, even if Supabase succeeds)
    try:
        local_file = Path(__file__).parent / ".processed_emails.json"
        ids = set()
        if local_file.exists():
            data = json.loads(local_file.read_text())
            ids = set(data.get("ids", []))
        ids.add(message_id)
        id_list = list(ids)[-1000:]
        local_file.write_text(json.dumps({"ids": id_list}))
    except Exception as e:
        logger.warning(f"Could not save local processed ID: {e}")


# Track processed message IDs to avoid duplicate replies (local file backup)
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
3. If they are asking about weather, use your `get_weather` tool to get accurate information
4. **CRITICAL - For ANY calendar/schedule questions:**
   - Use the `get_calendar_events` tool to get REAL data
   - Parameters for time_range:
     * "today", "tomorrow" - single day
     * "this_weekend", "next_weekend" - Saturday and Sunday only
     * "this_week", "next_week" - full week
     * "custom" - USE THIS for specific dates like "2/13-2/15" or "February 13th weekend"
   - For SPECIFIC DATES (like "weekend of 2/13"), use time_range="custom" with:
     * start_date: "2026-02-13" (YYYY-MM-DD format)
     * end_date: "2026-02-15" (YYYY-MM-DD format)
   - Optional: family_member ("Jack" or "Anna") to filter by person
   - Optional: group_by ("day" or "member") for different views
   - NEVER make up events - always call the tool first!
   - The tool knows custody schedule (Mom/Dad days) and all sports calendars
5. Keep your response concise but complete
6. Sign off warmly as Sabine

**IMPORTANT:** If the question involves schedules, events, "what's on", "who has the kids", custody, or anything time-related, you MUST call `get_calendar_events` before responding. Do NOT guess or make up calendar information.

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

        # Use cached IDs for fast duplicate detection (includes both DB and local file)
        processed_ids = _get_cached_processed_ids()
        replied_threads = _get_cached_replied_threads()

        logger.info(f"Loaded {len(processed_ids)} processed IDs and {len(replied_threads)} replied threads")

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

            # Find first email from an authorized sender that we haven't replied to
            email_data = None
            message_id = None
            thread_id = None
            sender = None
            sender_name = None
            subject = None
            body_preview = None

            for candidate in emails:
                candidate_id = candidate.get("id") or candidate.get("message_id")
                candidate_thread_id = candidate.get("threadId") or candidate.get("thread_id") or candidate_id
                candidate_sender = candidate.get("from", "").lower()
                candidate_subject = candidate.get("subject", "").lower()

                # Extract email from "Name <email>" format
                if candidate_sender and '<' in candidate_sender:
                    match = re.search(r'<([^>]+)>', candidate_sender)
                    if match:
                        candidate_sender_email = match.group(1).lower()
                    else:
                        candidate_sender_email = candidate_sender
                else:
                    candidate_sender_email = candidate_sender

                logger.info(f"Checking email {candidate_id} (thread: {candidate_thread_id}) from {candidate_sender_email}")

                # Skip if currently being processed by another concurrent request
                if candidate_id in _processing_messages:
                    logger.info(f"  -> Currently being processed by another request, skipping")
                    continue

                # Skip already processed message (check in-memory cache first, then DB/file)
                if candidate_id in processed_ids:
                    logger.info(f"  -> Already processed (message ID), skipping")
                    continue

                # Skip threads we've already replied to (prevents replying to same conversation twice)
                if candidate_thread_id in replied_threads:
                    logger.info(f"  -> Already replied to this thread, skipping")
                    save_processed_id(candidate_id)  # Mark as processed so we don't check again
                    continue

                # Skip self-emails (loop prevention)
                if candidate_sender_email == config["assistant_email"] or candidate_sender_email == config["agent_email"]:
                    logger.info(f"  -> Self-email from Sabine, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Skip emails that look like they're part of a reply chain FROM Sabine
                # (e.g., if someone forwarded Sabine's reply back)
                if "sabine" in candidate_sender_email:
                    logger.info(f"  -> Email from Sabine-related address, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Skip noreply addresses
                if any(ind in candidate_sender_email for ind in ['noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster']):
                    logger.info(f"  -> No-reply address, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Skip subjects with auto-reply indicators BEFORE processing
                if any(indicator in candidate_subject for indicator in AUTO_REPLY_INDICATORS):
                    logger.info(f"  -> Subject contains auto-reply indicator, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Skip blocked sender patterns (notifications, automated systems, school platforms)
                if any(pattern in candidate_sender_email for pattern in BLOCKED_SENDER_PATTERNS):
                    logger.info(f"  -> Blocked sender pattern detected, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Also check the full sender field (includes name)
                if any(pattern in candidate_sender for pattern in BLOCKED_SENDER_PATTERNS):
                    logger.info(f"  -> Blocked sender name pattern detected, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Skip blocked subject patterns (grade notifications, automated messages)
                if any(pattern in candidate_subject for pattern in BLOCKED_SUBJECT_PATTERNS):
                    logger.info(f"  -> Blocked subject pattern detected: {candidate_subject[:50]}, skipping")
                    save_processed_id(candidate_id)
                    continue

                # Check authorization
                if candidate_sender_email not in config["authorized_emails"]:
                    logger.info(f"  -> Not authorized ({config['authorized_emails']}), skipping")
                    continue

                # Found a valid email!
                logger.info(f"  -> AUTHORIZED! Processing this email")
                email_data = candidate
                message_id = candidate_id
                thread_id = candidate_thread_id
                sender = candidate_sender_email
                if '<' in candidate.get("from", ""):
                    sender_name = candidate.get("from", "").split('<')[0].strip()
                subject = candidate.get("subject", "")
                body_preview = candidate.get("body") or candidate.get("snippet", "")
                break

            if not email_data:
                logger.info("No unread emails from authorized senders found")
                return {"success": True, "action": "no_authorized_emails"}

            # Add to in-flight processing set to prevent concurrent duplicate handling
            _processing_messages.add(message_id)
            logger.info(f"Message {message_id} added to in-flight processing set")

            try:
                # Mark as processing in persistent storage
                save_processed_id(message_id)
                logger.info(f"Message {message_id} marked as processing")

                # Get full message content if needed (from agent's inbox)
                if not body_preview:
                    logger.info(f"Getting full content for message {message_id}...")
                    message_content = await mcp.call_tool("gmail_get_email_body_chunk", {
                        "google_access_token": agent_access_token,
                        "message_id": message_id
                    })

                    if message_content:
                        try:
                            content_data = json.loads(message_content)
                            if not body_preview:
                                body_preview = content_data.get("body", "")
                        except json.JSONDecodeError:
                            body_preview = extract_body(message_content)

                logger.info(f"Processing email from: {sender_name} <{sender}>")

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

                # Convert plain text to simple HTML for email rendering
                # The MCP gmail_send_email tool requires html_body to display content
                html_response = ai_response.replace('\n', '<br>\n')
                html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6;">
{html_response}
</body>
</html>"""

                # Send reply using AGENT token (sends FROM sabine@strugcity.com)
                logger.info(f"Sending AI-generated reply to {sender} from agent account...")
                send_result = await mcp.call_tool("gmail_send_email", {
                    "google_access_token": agent_access_token,
                    "to": sender,
                    "subject": reply_subject,
                    "body": ai_response,
                    "html_body": html_body
                })

                logger.info(f"Send result: {send_result}")

                if send_result and ("success" in send_result.lower() or "sent" in send_result.lower() or "id" in send_result.lower()):
                    logger.info(f"AI response sent to {sender}")
                    # Mark thread as replied to prevent double-replies
                    if thread_id:
                        save_replied_thread(thread_id)
                        logger.info(f"Thread {thread_id} marked as replied")
                    return {
                        "success": True,
                        "action": "replied",
                        "recipient": sender,
                        "message_id": message_id,
                        "thread_id": thread_id,
                        "subject": reply_subject,
                        "response_type": "ai_generated"
                    }
                else:
                    logger.warning(f"Failed to send reply to {sender}: {send_result}")
                    return {"success": False, "error": f"Failed to send reply: {send_result}"}

            finally:
                # Always remove from in-flight processing set when done
                if message_id and message_id in _processing_messages:
                    _processing_messages.discard(message_id)
                    logger.debug(f"Message {message_id} removed from in-flight processing set")

    except Exception as e:
        logger.error(f"Error handling email notification: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    finally:
        if lock_fd is not None:
            release_lock(lock_fd)
