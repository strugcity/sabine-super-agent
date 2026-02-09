"""
Proactive Scheduler - Phase 7: Autonomous Agent Actions
========================================================

This module implements Sabine's background scheduler for proactive tasks
that don't require user initiation (e.g., Morning Briefings, Reminders).

Core Capabilities:
1. Morning Briefing - Daily summary of tasks, events, and context
2. Scheduled Reminders - Time-based notifications
3. Event-Driven Actions - Triggered by external events

Architecture:
- Uses APScheduler for background job management
- Integrates with Context Engine for memory/entity retrieval
- Uses Claude for synthesis and natural language generation
- Sends notifications via Twilio SMS

Configuration:
- SCHEDULER_TIMEZONE: Default CST (America/Chicago)
- BRIEFING_HOUR: Hour to send morning briefing (default: 8)
- USER_PHONE: Target phone number for notifications

Owner: @backend-architect-sabine
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from supabase import Client

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
USER_PHONE = os.getenv("USER_PHONE")

# Scheduler configuration
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "America/Chicago")  # CST
BRIEFING_HOUR = int(os.getenv("BRIEFING_HOUR", "8"))  # 8 AM
BRIEFING_MINUTE = int(os.getenv("BRIEFING_MINUTE", "0"))

# Default user ID (single-user system for now)
DEFAULT_USER_ID = UUID(os.getenv("DEFAULT_USER_ID", "00000000-0000-0000-0000-000000000001"))

# Claude model for synthesis
SYNTHESIS_MODEL = "claude-sonnet-4-20250514"


# =============================================================================
# Supabase Client
# =============================================================================

def get_supabase_client() -> Client:
    """Get or create Supabase client."""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    return create_client(url, key)


# =============================================================================
# Context Retrieval for Briefing
# =============================================================================

async def get_briefing_context(user_id: UUID) -> str:
    """
    Build a dual-context morning briefing with work/personal sections.

    Uses domain-aware retrieval to separate work and personal/family context,
    plus cross-context scanning for potential conflicts.

    Args:
        user_id: User UUID for filtering

    Returns:
        Formatted dual-context briefing string
    """
    try:
        from lib.agent.retrieval import retrieve_context, cross_context_scan
    except ImportError as e:
        logger.error(f"Failed to import retrieval functions: {e}")
        # Fallback if retrieval not available
        return "Good morning, Ryan! Unable to load context - retrieval system unavailable."

    try:
        logger.info("🔍 Building dual-context morning briefing...")

        # Retrieve work context
        logger.info("  → Retrieving work context...")
        work_context = await retrieve_context(
            user_id=user_id,
            query="work tasks meetings deadlines this week",
            role_filter="assistant",
            domain_filter="work",
            memory_limit=5,
            entity_limit=10,
        )

        # Retrieve personal/family context
        logger.info("  → Retrieving personal context...")
        personal_context = await retrieve_context(
            user_id=user_id,
            query="personal family events appointments this week",
            role_filter="assistant",
            domain_filter="personal",
            memory_limit=5,
            entity_limit=10,
        )

        # Also get family context
        logger.info("  → Retrieving family context...")
        family_context = await retrieve_context(
            user_id=user_id,
            query="kids custody schedule family events",
            role_filter="assistant",
            domain_filter="family",
            memory_limit=3,
            entity_limit=5,
        )

        # Cross-context scan for conflicts
        logger.info("  → Scanning for cross-context conflicts...")
        cross_alerts = ""
        try:
            cross_alerts = await cross_context_scan(
                user_id=user_id,
                query="schedule meetings appointments events today this week",
                primary_domain="work",
            )
        except Exception as e:
            logger.warning(f"Cross-context scan failed (may not be available): {e}")

        # Format the dual-context briefing
        briefing = format_dual_briefing(work_context, personal_context, family_context, cross_alerts)
        logger.info(f"✓ Dual-context briefing generated ({len(briefing)} chars)")

        return briefing

    except Exception as e:
        logger.error(f"Failed to get dual-context briefing: {e}", exc_info=True)
        return f"Good morning, Ryan! I had trouble preparing your briefing today: {str(e)}"


# =============================================================================
# Dual-Context Formatting
# =============================================================================

def extract_context_items(context_str: str) -> str:
    """
    Extract the memory and entity bullet points from a formatted context string.

    Args:
        context_str: Formatted context from retrieve_context()

    Returns:
        Extracted bullet points (newline-separated)

    Example:
        >>> extract_context_items("[CONTEXT]\\n- Memory 1\\n- Entity 1")
        "- Memory 1\\n- Entity 1\\n"
    """
    lines = []
    for line in context_str.split("\n"):
        stripped = line.strip()
        # Include lines that start with "- " but skip "No relevant" / "No related" messages
        if stripped.startswith("- "):
            # Check if this is a "No relevant/related" message
            content_after_dash = stripped[2:].strip().lower()
            if not (content_after_dash.startswith("no relevant") or 
                    content_after_dash.startswith("no related")):
                lines.append(line)
    return "\n".join(lines) + "\n" if lines else ""


def format_dual_briefing(
    work_context: str,
    personal_context: str,
    family_context: str,
    cross_alerts: str,
) -> str:
    """
    Format a structured dual-context morning briefing.

    Output format:
    ---
    Good morning, Ryan!

    WORK
    - [work memories and entities]

    PERSONAL/FAMILY
    - [personal + family memories and entities]

    CROSS-CONTEXT ALERTS
    - [any conflicts or overlaps detected]
    ---

    Args:
        work_context: Work domain context from retrieve_context()
        personal_context: Personal domain context from retrieve_context()
        family_context: Family domain context from retrieve_context()
        cross_alerts: Cross-context alerts from cross_context_scan()

    Returns:
        Formatted briefing string
    """
    sections = ["Good morning, Ryan!\n"]

    # Work section
    sections.append("WORK")
    if work_context and "[No relevant memories found]" not in work_context:
        # Extract just the memory/entity lines from the formatted context
        work_items = extract_context_items(work_context)
        if work_items.strip():
            sections.append(work_items)
        else:
            sections.append("- No work items to report\n")
    else:
        sections.append("- No work items to report\n")

    # Personal/Family section
    sections.append("PERSONAL/FAMILY")
    combined_personal = ""
    if personal_context and "[No relevant memories found]" not in personal_context:
        combined_personal += extract_context_items(personal_context)
    if family_context and "[No relevant memories found]" not in family_context:
        combined_personal += extract_context_items(family_context)

    if combined_personal.strip():
        sections.append(combined_personal)
    else:
        sections.append("- No personal items to report\n")

    # Cross-context alerts (if any)
    if cross_alerts and cross_alerts.strip():
        sections.append("CROSS-CONTEXT ALERTS")
        sections.append(cross_alerts)

    return "\n".join(sections)


# =============================================================================
# Claude Synthesis
# =============================================================================

async def synthesize_briefing(context: str, user_name: str = "Ryan") -> str:
    """
    Use Claude to synthesize context into a concise morning briefing.

    The context is now a pre-formatted dual-context briefing string.
    Claude's job is to make it more concise and natural while preserving structure.

    Args:
        context: Pre-formatted dual-context briefing string
        user_name: Name to address in the briefing

    Returns:
        Formatted briefing text suitable for SMS (max ~1600 chars)
    """
    try:
        # If context is very short or empty, return as-is
        if not context or len(context) < 50:
            return f"Good morning, {user_name}! No major items on your radar today. Have a great day!"

        # Check for SMS length limit (1600 chars for concatenated SMS)
        SMS_LIMIT = 1600
        if len(context) <= SMS_LIMIT:
            # Context is already concise, return as-is
            logger.info(f"Briefing ready ({len(context)} chars, within SMS limit)")
            return context

        # Context is too long, need to synthesize/truncate
        if not ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set - truncating briefing")
            # Simple truncation fallback
            return context[:SMS_LIMIT-50] + "\n\n[Briefing truncated for SMS]"

        # Use Claude to synthesize into a more concise version
        logger.info(f"Synthesizing long briefing ({len(context)} chars) with Claude...")

        llm = ChatAnthropic(
            model=SYNTHESIS_MODEL,
            temperature=0.7,
            anthropic_api_key=ANTHROPIC_API_KEY,
            max_tokens=600
        )

        system_prompt = f"""You are Sabine, an Executive Assistant AI. Condense this morning briefing for {user_name}.

RULES:
1. Keep it under 1500 characters for SMS delivery
2. Preserve the WORK / PERSONAL/FAMILY / CROSS-CONTEXT ALERTS structure
3. Prioritize cross-context alerts (conflicts) - these are most important
4. Keep today's items, summarize or drop less urgent items
5. Use bullet points for scannability
6. Be warm but concise

FORMAT (preserve this structure):
Good morning, {user_name}!

WORK
- [Most important work items]

PERSONAL/FAMILY
- [Most important personal/family items]

CROSS-CONTEXT ALERTS (if any)
- [Any conflicts or overlaps]"""

        human_prompt = f"""Condense this briefing to under 1500 characters while preserving the structure and most important items:

{context}"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt)
        ]

        response = await llm.ainvoke(messages)
        briefing = response.content.strip()

        logger.info(f"Synthesized briefing ({len(briefing)} chars)")
        return briefing

    except Exception as e:
        logger.error(f"Failed to synthesize briefing: {e}", exc_info=True)
        # Return truncated original if synthesis fails
        if context and len(context) > SMS_LIMIT:
            return context[:SMS_LIMIT-50] + "\n\n[Briefing truncated]"
        return context or f"Good morning, {user_name}! I had trouble preparing your briefing today."


# =============================================================================
# Notification Delivery
# =============================================================================

async def send_sms(to_number: str, message: str) -> bool:
    """
    Send an SMS message via Twilio.

    Args:
        to_number: Recipient phone number (E.164 format)
        message: Message text

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
            logger.warning("Twilio credentials not configured - skipping SMS")
            logger.info(f"Would send SMS to {to_number}: {message[:100]}...")
            return False

        from twilio.rest import Client as TwilioClient

        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Split long messages if needed (SMS limit is 160 chars, but Twilio handles concatenation)
        sms = client.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=to_number
        )

        logger.info(f"SMS sent successfully: {sms.sid}")
        return True

    except Exception as e:
        logger.error(f"Failed to send SMS: {e}", exc_info=True)
        return False


# =============================================================================
# Morning Briefing Job
# =============================================================================

async def run_morning_briefing(
    user_id: Optional[UUID] = None,
    user_name: str = "Ryan",
    phone_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute the morning briefing job.

    Steps:
    1. Retrieve dual-context from Context Engine
    2. Synthesize briefing with Claude (if needed for length)
    3. Send via SMS (if configured)

    Args:
        user_id: User UUID (defaults to DEFAULT_USER_ID)
        user_name: Name to use in greeting
        phone_number: Override phone number (defaults to USER_PHONE env var)

    Returns:
        Result dictionary with status and details
    """
    logger.info("=" * 50)
    logger.info("Starting Morning Briefing Job")
    logger.info("=" * 50)

    user_id = user_id or DEFAULT_USER_ID
    phone = phone_number or USER_PHONE

    result = {
        "status": "pending",
        "user_id": str(user_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "briefing": None,
        "sms_sent": False,
        "error": None
    }

    try:
        # Step 1: Retrieve dual-context
        logger.info("Step 1: Retrieving dual-context...")
        context = await get_briefing_context(user_id)

        result["context_length"] = len(context)

        # Step 2: Synthesize briefing (condense if needed)
        logger.info("Step 2: Synthesizing briefing (if needed)...")
        briefing = await synthesize_briefing(context, user_name)
        result["briefing"] = briefing

        # Step 3: Send SMS
        if phone:
            logger.info(f"Step 3: Sending SMS to {phone[:4]}***...")
            sms_sent = await send_sms(phone, briefing)
            result["sms_sent"] = sms_sent
        else:
            logger.warning("Step 3: No phone number configured - skipping SMS")
            result["sms_sent"] = False

        result["status"] = "success"
        logger.info("Morning Briefing Job completed successfully")

    except Exception as e:
        logger.error(f"Morning Briefing Job failed: {e}", exc_info=True)
        result["status"] = "failed"
        result["error"] = str(e)

    logger.info("=" * 50)
    return result


# =============================================================================
# Scheduler Class
# =============================================================================

class SabineScheduler:
    """
    Background scheduler for Sabine's proactive tasks.

    Manages scheduled jobs like:
    - Morning Briefing (daily at configured time)
    - Future: Reminder notifications, follow-up prompts

    Usage:
        scheduler = SabineScheduler()
        await scheduler.start()
        # ... app runs ...
        await scheduler.shutdown()
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
        self._started = False

        logger.info(f"SabineScheduler initialized (timezone: {SCHEDULER_TIMEZONE})")

    def _setup_jobs(self):
        """Configure all scheduled jobs."""

        # Morning Briefing - runs daily at configured time
        self.scheduler.add_job(
            self._run_morning_briefing_wrapper,
            CronTrigger(
                hour=BRIEFING_HOUR,
                minute=BRIEFING_MINUTE,
                timezone=SCHEDULER_TIMEZONE
            ),
            id="morning_briefing",
            name="Daily Morning Briefing",
            replace_existing=True
        )

        logger.info(
            f"Scheduled morning briefing for {BRIEFING_HOUR:02d}:{BRIEFING_MINUTE:02d} {SCHEDULER_TIMEZONE}"
        )

    async def _run_morning_briefing_wrapper(self):
        """Wrapper to run the async morning briefing job."""
        try:
            result = await run_morning_briefing()
            logger.info(f"Morning briefing result: {result['status']}")
        except Exception as e:
            logger.error(f"Morning briefing wrapper error: {e}", exc_info=True)

    async def start(self):
        """Start the scheduler."""
        if self._started:
            logger.warning("Scheduler already started")
            return

        self._setup_jobs()
        self.scheduler.start()
        self._started = True

        logger.info("SabineScheduler started")

        # Log next run times
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            logger.info(f"  Job '{job.name}' next run: {next_run}")

    async def shutdown(self):
        """Gracefully shutdown the scheduler."""
        if not self._started:
            logger.warning("Scheduler not running")
            return

        logger.info("Shutting down SabineScheduler...")
        self.scheduler.shutdown(wait=True)
        self._started = False
        logger.info("SabineScheduler stopped")

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._started and self.scheduler.running

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get list of scheduled jobs and their next run times."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger)
            })
        return jobs

    async def trigger_briefing_now(
        self,
        user_id: Optional[UUID] = None,
        user_name: str = "Ryan",
        phone_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Manually trigger the morning briefing (for testing).

        Args:
            user_id: Override user ID
            user_name: Override user name
            phone_number: Override phone number

        Returns:
            Briefing result dictionary
        """
        logger.info("Manual briefing trigger requested")
        return await run_morning_briefing(user_id, user_name, phone_number)


# =============================================================================
# Module-level singleton
# =============================================================================

_scheduler_instance: Optional[SabineScheduler] = None


def get_scheduler() -> SabineScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SabineScheduler()
    return _scheduler_instance
