"""
Reminder Scheduler Integration - Phase 3.2
==========================================

Integrates reminders with APScheduler for time-based triggering.

Features:
- Add scheduler jobs for new reminders
- Remove jobs when reminders are cancelled
- Restore jobs from database on server restart
- Support for one-time (DateTrigger) and recurring (CronTrigger) reminders

BDD Specification:
    Feature: Scheduler Integration

      Scenario: Add job for new reminder
        When a reminder is created for 10:00 AM tomorrow
        Then a DateTrigger job should be added to APScheduler
        And the job ID should match the reminder ID
        And get_jobs() should include this job

      Scenario: Add job for recurring reminder
        When a weekly reminder is created
        Then a CronTrigger job should be added
        And it should fire every week at the same time

      Scenario: Remove job when reminder cancelled
        When a reminder is cancelled
        Then the corresponding scheduler job should be removed
        And get_jobs() should no longer include it

      Scenario: Restore jobs on server restart
        Given there are 5 active reminders in the database
        When the server restarts
        Then all 5 scheduler jobs should be recreated
        And they should have correct trigger times

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 3.2
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.base import JobLookupError

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "America/Chicago")
USER_TIMEZONE = pytz.timezone(SCHEDULER_TIMEZONE)

# Job ID prefix for reminder jobs
REMINDER_JOB_PREFIX = "reminder_"

# Polling interval for due reminders (fallback mechanism)
DUE_REMINDER_POLL_MINUTES = int(os.getenv("DUE_REMINDER_POLL_MINUTES", "5"))


# =============================================================================
# Trigger Creation
# =============================================================================

def create_trigger_for_reminder(
    scheduled_time: datetime,
    repeat_pattern: Optional[str] = None
) -> Any:
    """
    Create an APScheduler trigger for a reminder.

    Args:
        scheduled_time: When the reminder should fire
        repeat_pattern: Recurrence pattern (daily, weekly, monthly, yearly) or None

    Returns:
        DateTrigger for one-time, CronTrigger for recurring
    """
    # Ensure timezone-aware
    if scheduled_time.tzinfo is None:
        scheduled_time = USER_TIMEZONE.localize(scheduled_time)

    # Convert to user's timezone for cron expressions
    local_time = scheduled_time.astimezone(USER_TIMEZONE)

    if repeat_pattern is None:
        # One-time reminder: use DateTrigger
        return DateTrigger(run_date=scheduled_time, timezone=USER_TIMEZONE)

    elif repeat_pattern == "daily":
        # Daily at the same time
        return CronTrigger(
            hour=local_time.hour,
            minute=local_time.minute,
            timezone=USER_TIMEZONE
        )

    elif repeat_pattern == "weekly":
        # Weekly on the same day and time
        # day_of_week: 0=Monday, 6=Sunday
        return CronTrigger(
            day_of_week=local_time.weekday(),
            hour=local_time.hour,
            minute=local_time.minute,
            timezone=USER_TIMEZONE
        )

    elif repeat_pattern == "monthly":
        # Monthly on the same day and time
        return CronTrigger(
            day=local_time.day,
            hour=local_time.hour,
            minute=local_time.minute,
            timezone=USER_TIMEZONE
        )

    elif repeat_pattern == "yearly":
        # Yearly on the same date and time
        return CronTrigger(
            month=local_time.month,
            day=local_time.day,
            hour=local_time.hour,
            minute=local_time.minute,
            timezone=USER_TIMEZONE
        )

    else:
        # Unknown pattern, treat as one-time
        logger.warning(f"Unknown repeat_pattern '{repeat_pattern}', using DateTrigger")
        return DateTrigger(run_date=scheduled_time, timezone=USER_TIMEZONE)


def get_job_id(reminder_id: UUID) -> str:
    """Generate a job ID for a reminder."""
    return f"{REMINDER_JOB_PREFIX}{reminder_id}"


def extract_reminder_id(job_id: str) -> Optional[UUID]:
    """Extract reminder UUID from job ID."""
    if job_id.startswith(REMINDER_JOB_PREFIX):
        try:
            return UUID(job_id[len(REMINDER_JOB_PREFIX):])
        except ValueError:
            return None
    return None


# =============================================================================
# Reminder Scheduler Class
# =============================================================================

class ReminderScheduler:
    """
    Manages APScheduler jobs for reminders.

    This class extends the base SabineScheduler with reminder-specific
    functionality for adding, removing, and restoring reminder jobs.

    Usage:
        scheduler = ReminderScheduler()
        await scheduler.start()

        # Add a reminder job
        await scheduler.add_reminder_job(reminder_id, scheduled_time)

        # Remove when cancelled
        await scheduler.remove_reminder_job(reminder_id)

        # On restart
        await scheduler.restore_reminder_jobs()
    """

    def __init__(self, scheduler: Optional[AsyncIOScheduler] = None):
        """
        Initialize the reminder scheduler.

        Args:
            scheduler: Optional existing scheduler to use.
                       If None, creates a new one.
        """
        if scheduler is None:
            self.scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
            self._owns_scheduler = True
        else:
            self.scheduler = scheduler
            self._owns_scheduler = False

        self._started = False
        logger.info(f"ReminderScheduler initialized (timezone: {SCHEDULER_TIMEZONE})")

    async def start(self):
        """Start the scheduler and restore reminder jobs."""
        if self._started:
            logger.warning("ReminderScheduler already started")
            return

        # Add due reminder polling job (fallback mechanism)
        self.scheduler.add_job(
            self._poll_due_reminders,
            CronTrigger(minute=f"*/{DUE_REMINDER_POLL_MINUTES}", timezone=SCHEDULER_TIMEZONE),
            id="reminder_poll",
            name="Poll Due Reminders",
            replace_existing=True
        )

        if self._owns_scheduler:
            self.scheduler.start()

        self._started = True

        # Restore jobs from database
        await self.restore_reminder_jobs()

        logger.info("ReminderScheduler started")

    async def shutdown(self):
        """Stop the scheduler."""
        if not self._started:
            return

        if self._owns_scheduler:
            self.scheduler.shutdown(wait=True)

        self._started = False
        logger.info("ReminderScheduler stopped")

    async def _poll_due_reminders(self):
        """
        Polling job that catches any due reminders.

        This is a fallback mechanism in case a scheduled job was missed
        or the reminder was created while the server was down.
        """
        try:
            from lib.agent.reminder_notifications import process_due_reminders
            result = await process_due_reminders()
            if result.get("reminders_processed", 0) > 0:
                logger.info(f"Polling processed {result['reminders_processed']} due reminders")
        except Exception as e:
            logger.error(f"Error polling due reminders: {e}")

    async def add_reminder_job(
        self,
        reminder_id: UUID,
        scheduled_time: datetime,
        repeat_pattern: Optional[str] = None,
        title: Optional[str] = None,
    ) -> bool:
        """
        Add a scheduler job for a reminder.

        Args:
            reminder_id: The reminder UUID
            scheduled_time: When to fire the reminder
            repeat_pattern: Recurrence pattern (optional)
            title: Reminder title for logging (optional)

        Returns:
            True if job was added successfully
        """
        job_id = get_job_id(reminder_id)
        job_name = f"Reminder: {title}" if title else f"Reminder {reminder_id}"

        try:
            # Remove existing job if any (for updates)
            await self.remove_reminder_job(reminder_id)

            # Create appropriate trigger
            trigger = create_trigger_for_reminder(scheduled_time, repeat_pattern)

            # Add the job
            self.scheduler.add_job(
                self._fire_reminder_wrapper,
                trigger,
                id=job_id,
                name=job_name,
                args=[reminder_id],
                replace_existing=True
            )

            job = self.scheduler.get_job(job_id)
            next_run = job.next_run_time if job else "unknown"

            logger.info(
                f"Added reminder job: {job_id} "
                f"(pattern={repeat_pattern or 'one-time'}, next_run={next_run})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to add reminder job {job_id}: {e}")
            return False

    async def remove_reminder_job(self, reminder_id: UUID) -> bool:
        """
        Remove a scheduler job for a reminder.

        Args:
            reminder_id: The reminder UUID

        Returns:
            True if job was removed (or didn't exist)
        """
        job_id = get_job_id(reminder_id)

        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed reminder job: {job_id}")
            return True

        except JobLookupError:
            # Job doesn't exist, which is fine
            logger.debug(f"Reminder job {job_id} not found (already removed)")
            return True

        except Exception as e:
            logger.error(f"Failed to remove reminder job {job_id}: {e}")
            return False

    async def restore_reminder_jobs(self) -> Dict[str, Any]:
        """
        Restore all reminder jobs from the database.

        Called on server startup to recreate jobs for active reminders.

        Returns:
            Dict with restore results
        """
        from backend.services.reminder_service import get_reminder_service

        logger.info("Restoring reminder jobs from database...")

        result = {
            "restored": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        try:
            service = get_reminder_service()

            # Get all active reminders for all users
            # Note: In multi-tenant, we'd need to iterate per user
            # For now, we use the service's raw Supabase client
            if not service.client:
                logger.warning("Supabase not configured, cannot restore reminder jobs")
                return result

            response = service.client.table("reminders").select("*").eq(
                "is_active", True
            ).eq(
                "is_completed", False
            ).execute()

            reminders = response.data or []
            logger.info(f"Found {len(reminders)} active reminders to restore")

            for reminder in reminders:
                reminder_id = UUID(reminder["id"])
                scheduled_time_str = reminder.get("scheduled_time")
                repeat_pattern = reminder.get("repeat_pattern")
                title = reminder.get("title")

                # Parse scheduled time
                try:
                    if scheduled_time_str.endswith('Z'):
                        scheduled_time = datetime.fromisoformat(
                            scheduled_time_str[:-1] + '+00:00'
                        )
                    else:
                        scheduled_time = datetime.fromisoformat(scheduled_time_str)
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid scheduled_time for reminder {reminder_id}: {e}")
                    result["failed"] += 1
                    result["errors"].append(f"{reminder_id}: Invalid time")
                    continue

                # Skip if one-time reminder is in the past
                now = datetime.now(timezone.utc)
                if repeat_pattern is None and scheduled_time <= now:
                    logger.debug(f"Skipping past one-time reminder {reminder_id}")
                    result["skipped"] += 1
                    continue

                # Add the job
                success = await self.add_reminder_job(
                    reminder_id=reminder_id,
                    scheduled_time=scheduled_time,
                    repeat_pattern=repeat_pattern,
                    title=title,
                )

                if success:
                    result["restored"] += 1
                else:
                    result["failed"] += 1
                    result["errors"].append(f"{reminder_id}: Failed to add job")

            logger.info(
                f"Reminder jobs restored: {result['restored']} restored, "
                f"{result['skipped']} skipped, {result['failed']} failed"
            )

            return result

        except Exception as e:
            logger.error(f"Failed to restore reminder jobs: {e}", exc_info=True)
            result["errors"].append(f"Database error: {str(e)}")
            return result

    async def _fire_reminder_wrapper(self, reminder_id: UUID):
        """
        Wrapper to fire a reminder from the scheduler.

        This is called by APScheduler when a reminder job triggers.
        """
        try:
            from lib.agent.reminder_notifications import fire_reminder

            logger.info(f"Scheduler firing reminder: {reminder_id}")
            result = await fire_reminder(reminder_id)

            if result.get("status") == "success":
                # For one-time reminders, remove the job
                if result.get("action") == "completed":
                    await self.remove_reminder_job(reminder_id)

            logger.info(f"Reminder fire result: {result.get('status')}")

        except Exception as e:
            logger.error(f"Error in reminder wrapper for {reminder_id}: {e}", exc_info=True)

    def get_reminder_jobs(self) -> List[Dict[str, Any]]:
        """
        Get list of all scheduled reminder jobs.

        Returns:
            List of job info dictionaries
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith(REMINDER_JOB_PREFIX):
                reminder_id = extract_reminder_id(job.id)
                jobs.append({
                    "job_id": job.id,
                    "reminder_id": str(reminder_id) if reminder_id else None,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })
        return jobs

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._started and self.scheduler.running


# =============================================================================
# Module-level singleton
# =============================================================================

_reminder_scheduler: Optional[ReminderScheduler] = None


def get_reminder_scheduler() -> ReminderScheduler:
    """Get or create the global reminder scheduler instance."""
    global _reminder_scheduler
    if _reminder_scheduler is None:
        _reminder_scheduler = ReminderScheduler()
    return _reminder_scheduler


async def initialize_reminder_scheduler():
    """Initialize and start the reminder scheduler."""
    scheduler = get_reminder_scheduler()
    await scheduler.start()
    return scheduler
