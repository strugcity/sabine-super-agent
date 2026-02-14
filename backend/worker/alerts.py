"""
Failure Alerting for Slow Path Worker
=======================================

Sends alerts when WAL entries permanently fail (retries exhausted) or
when a previously failed entry is successfully processed on retry.

Alert channels:
    - Slack webhook (stub -- real webhook integration is a follow-up)
    - Python ``logging`` at CRITICAL / INFO level

ADR Reference: ADR-002 (monitoring / alerting for the Slow Path)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Slack webhook URL (stub -- will be set once the Slack integration is live)
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_ALERT_WEBHOOK_URL", "")


# ---------------------------------------------------------------------------
# Failure alert
# ---------------------------------------------------------------------------

async def send_failure_alert(
    error_summary: str,
    wal_entry_id: str,
    retry_count: int,
) -> None:
    """
    Send an alert when a WAL entry permanently fails after retries are
    exhausted.

    This is triggered when the entry has been retried ``MAX_RETRIES`` times
    and each attempt has failed.

    Parameters
    ----------
    error_summary : str
        Human-readable description of the error.
    wal_entry_id : str
        UUID (as string) of the WAL entry that failed.
    retry_count : int
        Total number of retry attempts made.
    """
    timestamp: str = datetime.now(timezone.utc).isoformat()

    message: str = (
        f"[SLOW PATH FAILURE] WAL entry {wal_entry_id} permanently failed "
        f"after {retry_count} retries.\n"
        f"Error: {error_summary}\n"
        f"Timestamp: {timestamp}"
    )

    # Always log at CRITICAL
    logger.critical(
        "WAL entry permanently failed: wal_entry_id=%s  retry_count=%d  "
        "error=%s",
        wal_entry_id,
        retry_count,
        error_summary,
    )

    # Attempt Slack notification
    await _post_to_slack(message)


# ---------------------------------------------------------------------------
# Recovery alert
# ---------------------------------------------------------------------------

async def send_recovery_alert(wal_entry_id: str) -> None:
    """
    Send an alert when a previously failed WAL entry is successfully
    processed on a subsequent retry.

    Parameters
    ----------
    wal_entry_id : str
        UUID (as string) of the recovered WAL entry.
    """
    timestamp: str = datetime.now(timezone.utc).isoformat()

    message: str = (
        f"[SLOW PATH RECOVERY] WAL entry {wal_entry_id} "
        f"successfully processed after prior failure.\n"
        f"Timestamp: {timestamp}"
    )

    logger.info(
        "WAL entry recovered: wal_entry_id=%s", wal_entry_id,
    )

    await _post_to_slack(message)


# ---------------------------------------------------------------------------
# Slack integration
# ---------------------------------------------------------------------------

async def _post_to_slack(message: str) -> None:
    """
    Post a message to the configured Slack incoming webhook.

    When ``SLACK_ALERT_WEBHOOK_URL`` is not set, the message is logged
    and silently skipped.  Network or HTTP errors are logged as warnings
    but never raised -- alerting failures must not crash the worker.

    Parameters
    ----------
    message : str
        The alert text to post.
    """
    if not SLACK_WEBHOOK_URL:
        logger.debug(
            "Slack webhook not configured; alert logged only: %s",
            message[:200],
        )
        return

    try:
        import httpx  # lazy import to avoid circular deps

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                SLACK_WEBHOOK_URL,
                json={"text": message},
            )
            resp.raise_for_status()
            logger.debug("Slack alert sent successfully.")
    except Exception as exc:
        logger.warning(
            "Failed to send Slack alert: %s", exc, exc_info=True,
        )


# ---------------------------------------------------------------------------
# OAuth token-expiry alert
# ---------------------------------------------------------------------------

async def send_token_expired_alert(
    token_type: str,
    detail: str = "",
    consecutive_failures: int = 0,
) -> None:
    """
    Alert when a Google OAuth refresh token is expired/revoked.

    Parameters
    ----------
    token_type : str
        ``"user"`` or ``"agent"`` — which token failed.
    detail : str
        Additional context (e.g., the error message from Google).
    consecutive_failures : int
        How many poll cycles in a row have hit this error.
    """
    timestamp: str = datetime.now(timezone.utc).isoformat()

    message: str = (
        f"[OAUTH TOKEN EXPIRED] Google {token_type} refresh token "
        f"returned invalid_grant.\n"
        f"Consecutive failures: {consecutive_failures}\n"
        f"Detail: {detail}\n"
        f"Action: Re-run reauthorize_google.py or update the refresh "
        f"token in Railway environment variables.\n"
        f"Timestamp: {timestamp}"
    )

    logger.critical(
        "Google OAuth %s token expired — consecutive_failures=%d detail=%s",
        token_type,
        consecutive_failures,
        detail[:200],
    )

    await _post_to_slack(message)
