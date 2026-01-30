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

async def get_briefing_context(user_id: UUID) -> Dict[str, Any]:
    """
    Retrieve relevant context for the morning briefing.

    Queries:
    1. Recent memories (last 24 hours)
    2. Upcoming tasks/events
    3. High-importance items

    Args:
        user_id: User UUID for filtering

    Returns:
        Dictionary with categorized context items
    """
    try:
        supabase = get_supabase_client()

        # Calculate time boundaries (timezone-aware UTC)
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        next_week = now + timedelta(days=7)

        context = {
            "recent_memories": [],
            "upcoming_tasks": [],
            "high_importance": [],
            "entities": [],
            "timestamp": now.isoformat()
        }

        # Query 1: Recent memories (last 24 hours)
        try:
            memories_response = supabase.table("memories").select("*").gte(
                "created_at", yesterday.isoformat()
            ).order("created_at", desc=True).limit(10).execute()

            if memories_response.data:
                context["recent_memories"] = [
                    {
                        "content": m.get("content", "")[:500],  # Truncate long content
                        "source": m.get("source", "unknown"),
                        "created_at": m.get("created_at"),
                        "importance": m.get("importance", 0.5)
                    }
                    for m in memories_response.data
                ]
                logger.info(f"Found {len(context['recent_memories'])} recent memories")
        except Exception as e:
            logger.warning(f"Failed to fetch recent memories: {e}")

        # Query 2: Tasks table (if exists) - look for upcoming items
        try:
            # Check for tasks with dates in the next week
            tasks_response = supabase.table("tasks").select("*").eq(
                "status", "pending"
            ).order("due_date", desc=False).limit(10).execute()

            if tasks_response.data:
                context["upcoming_tasks"] = [
                    {
                        "title": t.get("title", "Untitled"),
                        "description": t.get("description", "")[:200],
                        "due_date": t.get("due_date"),
                        "priority": t.get("priority", "normal")
                    }
                    for t in tasks_response.data
                ]
                logger.info(f"Found {len(context['upcoming_tasks'])} upcoming tasks")
        except Exception as e:
            logger.debug(f"Tasks table query failed (may not exist): {e}")

        # Query 3: High importance memories (importance_score column)
        try:
            important_response = supabase.table("memories").select("*").gte(
                "importance_score", 0.8
            ).order("created_at", desc=True).limit(5).execute()

            if important_response.data:
                context["high_importance"] = [
                    {
                        "content": m.get("content", "")[:300],
                        "importance": m.get("importance_score", 0.8),
                        "created_at": m.get("created_at")
                    }
                    for m in important_response.data
                ]
                logger.info(f"Found {len(context['high_importance'])} high-importance items")
        except Exception as e:
            logger.debug(f"High-importance memories query failed: {e}")

        # Query 4: Active entities (for context)
        try:
            entities_response = supabase.table("entities").select("*").eq(
                "status", "active"
            ).order("updated_at", desc=True).limit(10).execute()

            if entities_response.data:
                context["entities"] = [
                    {
                        "name": e.get("name", "Unknown"),
                        "type": e.get("type", "other"),
                        "domain": e.get("domain", "personal"),
                        "attributes": e.get("attributes", {})
                    }
                    for e in entities_response.data
                ]
                logger.info(f"Found {len(context['entities'])} active entities")
        except Exception as e:
            logger.warning(f"Failed to fetch entities: {e}")

        return context

    except Exception as e:
        logger.error(f"Failed to get briefing context: {e}", exc_info=True)
        return {
            "recent_memories": [],
            "upcoming_tasks": [],
            "high_importance": [],
            "entities": [],
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }


# =============================================================================
# Claude Synthesis
# =============================================================================

async def synthesize_briefing(context: Dict[str, Any], user_name: str = "Paul") -> str:
    """
    Use Claude to synthesize context into a concise morning briefing.

    Args:
        context: Dictionary with memories, tasks, entities
        user_name: Name to address in the briefing

    Returns:
        Formatted briefing text suitable for SMS
    """
    try:
        if not ANTHROPIC_API_KEY:
            logger.error("ANTHROPIC_API_KEY not set for briefing synthesis")
            return f"Good morning, {user_name}! Unable to generate briefing - API key not configured."

        # Check if we have any content
        has_content = (
            context.get("recent_memories") or
            context.get("upcoming_tasks") or
            context.get("high_importance") or
            context.get("entities")
        )

        if not has_content:
            return f"Good morning, {user_name}! No major items on your radar today. Have a great day!"

        # Build context summary for Claude
        context_text = []

        if context.get("recent_memories"):
            context_text.append("RECENT ACTIVITY (Last 24 hours):")
            for m in context["recent_memories"][:5]:
                context_text.append(f"  - [{m['source']}] {m['content'][:200]}")

        if context.get("upcoming_tasks"):
            context_text.append("\nUPCOMING TASKS:")
            for t in context["upcoming_tasks"][:5]:
                due = t.get("due_date", "No date")
                context_text.append(f"  - {t['title']} (Due: {due}, Priority: {t['priority']})")

        if context.get("high_importance"):
            context_text.append("\nHIGH PRIORITY ITEMS:")
            for h in context["high_importance"][:3]:
                context_text.append(f"  - {h['content'][:150]}")

        if context.get("entities"):
            context_text.append("\nACTIVE PROJECTS/PEOPLE:")
            for e in context["entities"][:5]:
                context_text.append(f"  - {e['name']} ({e['type']}, {e['domain']})")

        context_str = "\n".join(context_text)

        # Create Claude client
        llm = ChatAnthropic(
            model=SYNTHESIS_MODEL,
            temperature=0.7,
            anthropic_api_key=ANTHROPIC_API_KEY,
            max_tokens=500
        )

        system_prompt = f"""You are Sabine, an Executive Assistant AI. Write a concise morning briefing for {user_name}.

RULES:
1. Keep it SHORT - this will be sent via SMS (under 400 characters ideally)
2. Use exactly 3 bullet points
3. Focus on what's ACTIONABLE today
4. Be warm but professional
5. If there are deadlines or urgent items, mention them first
6. End with something encouraging

FORMAT:
Good morning, {user_name}!

- [First bullet - most important/urgent item]
- [Second bullet - key task or reminder]
- [Third bullet - context or upcoming event]

[Brief encouraging sign-off]"""

        human_prompt = f"""Based on this context, write the morning briefing:

{context_str}

Remember: Keep it under 400 characters if possible, use 3 bullets, be actionable."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt)
        ]

        response = await llm.ainvoke(messages)
        briefing = response.content.strip()

        logger.info(f"Generated briefing ({len(briefing)} chars)")
        return briefing

    except Exception as e:
        logger.error(f"Failed to synthesize briefing: {e}", exc_info=True)
        return f"Good morning, {user_name}! I had trouble preparing your briefing today. Check in when you have a moment."


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
    user_name: str = "Paul",
    phone_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute the morning briefing job.

    Steps:
    1. Retrieve context from Context Engine
    2. Synthesize briefing with Claude
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
        # Step 1: Retrieve context
        logger.info("Step 1: Retrieving context...")
        context = await get_briefing_context(user_id)

        result["context_summary"] = {
            "recent_memories": len(context.get("recent_memories", [])),
            "upcoming_tasks": len(context.get("upcoming_tasks", [])),
            "high_importance": len(context.get("high_importance", [])),
            "entities": len(context.get("entities", []))
        }

        # Step 2: Synthesize briefing
        logger.info("Step 2: Synthesizing briefing with Claude...")
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
        user_name: str = "Paul",
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
