"""
Email Polling Fallback - Complements Gmail Push Notifications
=============================================================

This module implements a polling fallback mechanism for email processing.
Gmail Push notifications via Pub/Sub can have variable latency (sometimes
up to 20+ minutes). This poller runs every 2 minutes to catch emails that
may have been delayed or missed by the push notification system.

Features:
- Polls for unread emails from authorized senders every 2 minutes
- Skips emails that have already been processed (via Supabase tracking)
- Integrates with existing gmail_handler for processing
- Logs polling activity for monitoring

Architecture:
- Uses APScheduler CronTrigger for interval-based polling
- Reuses gmail_handler.handle_new_email_notification() for processing
- Shares tracking state with push notification handler (Supabase + local cache)

Configuration:
- EMAIL_POLL_INTERVAL_MINUTES: Polling interval (default: 2)
- EMAIL_POLL_ENABLED: Enable/disable polling (default: true)

Owner: @backend-architect-sabine
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "America/Chicago")

# Polling interval in minutes (default: 2 minutes)
EMAIL_POLL_INTERVAL_MINUTES = int(os.getenv("EMAIL_POLL_INTERVAL_MINUTES", "2"))

# Enable/disable email polling (default: enabled)
EMAIL_POLL_ENABLED = os.getenv("EMAIL_POLL_ENABLED", "true").lower() == "true"


# =============================================================================
# Email Poller Class
# =============================================================================

class EmailPoller:
    """
    Background email poller that complements Gmail Push notifications.

    This poller runs at regular intervals to check for unread emails
    that may have been missed or delayed by the push notification system.

    Usage:
        poller = EmailPoller()
        await poller.start()
        # ... app runs ...
        await poller.shutdown()
    """

    # After this many consecutive token failures, stop polling and just alert.
    MAX_TOKEN_FAILURES_BEFORE_BACKOFF = 3

    # Only re-alert every N failures to avoid spamming Slack.
    ALERT_EVERY_N_FAILURES = 10

    def __init__(self, scheduler: Optional[AsyncIOScheduler] = None):
        """
        Initialize the email poller.

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
        self._poll_count = 0
        self._emails_found = 0
        self._last_poll_time: Optional[datetime] = None
        self._consecutive_token_failures = 0
        self._token_alert_sent = False

        logger.info(
            f"EmailPoller initialized "
            f"(interval: {EMAIL_POLL_INTERVAL_MINUTES}min, enabled: {EMAIL_POLL_ENABLED})"
        )

    async def start(self):
        """Start the email poller."""
        if self._started:
            logger.warning("EmailPoller already started")
            return

        if not EMAIL_POLL_ENABLED:
            logger.info("Email polling is disabled via EMAIL_POLL_ENABLED=false")
            return

        # Add the polling job
        self.scheduler.add_job(
            self._poll_for_emails,
            CronTrigger(
                minute=f"*/{EMAIL_POLL_INTERVAL_MINUTES}",
                timezone=SCHEDULER_TIMEZONE
            ),
            id="email_poll",
            name="Poll for Unread Emails",
            replace_existing=True
        )

        if self._owns_scheduler:
            self.scheduler.start()

        self._started = True

        # Log next run time
        job = self.scheduler.get_job("email_poll")
        next_run = job.next_run_time if job else "unknown"
        logger.info(f"EmailPoller started (next poll: {next_run})")

    async def shutdown(self):
        """Stop the email poller."""
        if not self._started:
            return

        try:
            self.scheduler.remove_job("email_poll")
        except Exception as remove_err:
            logger.warning(
                "Failed to remove email_poll job during shutdown: %s",
                remove_err,
            )

        if self._owns_scheduler:
            self.scheduler.shutdown(wait=True)

        self._started = False
        logger.info(
            f"EmailPoller stopped "
            f"(total polls: {self._poll_count}, emails found: {self._emails_found})"
        )

    async def _poll_for_emails(self) -> None:
        """
        Poll for unread emails from authorized senders.

        This is the main polling job that runs at regular intervals.
        It reuses the gmail_handler infrastructure for consistency.

        Token-expiry awareness:
            If the handler returns ``"error": "token_expired"``, we increment a
            consecutive-failure counter.  After ``MAX_TOKEN_FAILURES_BEFORE_BACKOFF``
            failures we skip actual polling (just log) and fire a Slack alert.
            The counter resets as soon as a poll succeeds.
        """
        self._poll_count += 1
        self._last_poll_time = datetime.now(timezone.utc)

        # ── Back-off when tokens are known-bad ──
        if self._consecutive_token_failures >= self.MAX_TOKEN_FAILURES_BEFORE_BACKOFF:
            logger.warning(
                "[Email Poll #%d] Skipping — OAuth token expired "
                "(%d consecutive failures). Waiting for re-auth.",
                self._poll_count,
                self._consecutive_token_failures,
            )
            # Re-alert periodically so the issue stays visible
            if self._consecutive_token_failures % self.ALERT_EVERY_N_FAILURES == 0:
                await self._fire_token_alert("unknown")
            self._consecutive_token_failures += 1
            return

        logger.info(f"[Email Poll #{self._poll_count}] Checking for unread emails...")

        try:
            from lib.agent.gmail_handler import handle_new_email_notification

            result = await handle_new_email_notification(
                history_id=f"poll_{self._poll_count}"
            )

            error = result.get("error", "")
            action = result.get("action", "unknown")
            success = result.get("success", False)

            # ── Token-expired handling ──
            if error == "token_expired":
                self._consecutive_token_failures += 1
                token_type = result.get("token_type", "unknown")
                logger.error(
                    "[Email Poll #%d] OAuth %s token expired "
                    "(failure #%d)",
                    self._poll_count,
                    token_type,
                    self._consecutive_token_failures,
                )
                if not self._token_alert_sent:
                    await self._fire_token_alert(token_type)
                return

            # ── Success — reset failure counter ──
            if self._consecutive_token_failures > 0:
                logger.info(
                    "[Email Poll #%d] Token recovered after %d failures",
                    self._poll_count,
                    self._consecutive_token_failures,
                )
            self._consecutive_token_failures = 0
            self._token_alert_sent = False

            if action == "replied":
                self._emails_found += 1
                recipient = result.get("recipient", "unknown")
                subject = result.get("subject", "")
                logger.info(
                    f"[Email Poll #{self._poll_count}] "
                    f"Found and replied to email from {recipient}: {subject[:50]}"
                )
            elif action == "no_authorized_emails":
                logger.debug(
                    f"[Email Poll #{self._poll_count}] No unread authorized emails"
                )
            elif action == "no_emails":
                logger.debug(
                    f"[Email Poll #{self._poll_count}] No unread emails found"
                )
            elif action == "skipped_concurrent":
                logger.debug(
                    f"[Email Poll #{self._poll_count}] Skipped (concurrent processing)"
                )
            else:
                logger.debug(
                    f"[Email Poll #{self._poll_count}] Result: {action} (success={success})"
                )

        except Exception as e:
            logger.error(
                f"[Email Poll #{self._poll_count}] Error during poll: {e}",
                exc_info=True
            )

    async def _fire_token_alert(self, token_type: str) -> None:
        """Send a Slack/log alert for an expired OAuth token."""
        try:
            from backend.worker.alerts import send_token_expired_alert

            await send_token_expired_alert(
                token_type=token_type,
                detail="Detected during email polling cycle",
                consecutive_failures=self._consecutive_token_failures,
            )
            self._token_alert_sent = True
        except Exception as alert_err:
            logger.warning(
                "Failed to send token-expired alert: %s", alert_err
            )

    async def poll_now(self) -> Dict[str, Any]:
        """
        Manually trigger an email poll (for testing/debugging).

        Returns:
            Dict with poll results
        """
        logger.info("Manual email poll triggered")
        await self._poll_for_emails()
        return {
            "poll_count": self._poll_count,
            "emails_found": self._emails_found,
            "last_poll_time": self._last_poll_time.isoformat() if self._last_poll_time else None
        }

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the email poller."""
        job = self.scheduler.get_job("email_poll") if self._started else None

        return {
            "enabled": EMAIL_POLL_ENABLED,
            "running": self._started,
            "interval_minutes": EMAIL_POLL_INTERVAL_MINUTES,
            "poll_count": self._poll_count,
            "emails_found": self._emails_found,
            "last_poll_time": self._last_poll_time.isoformat() if self._last_poll_time else None,
            "next_poll_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
            "consecutive_token_failures": self._consecutive_token_failures,
            "token_backed_off": self._consecutive_token_failures >= self.MAX_TOKEN_FAILURES_BEFORE_BACKOFF,
        }

    def is_running(self) -> bool:
        """Check if the poller is running."""
        return self._started and self.scheduler.running


# =============================================================================
# Module-level singleton
# =============================================================================

_email_poller: Optional[EmailPoller] = None


def get_email_poller() -> EmailPoller:
    """Get or create the global email poller instance."""
    global _email_poller
    if _email_poller is None:
        _email_poller = EmailPoller()
    return _email_poller


async def initialize_email_poller() -> EmailPoller:
    """Initialize and start the email poller."""
    poller = get_email_poller()
    await poller.start()
    return poller
