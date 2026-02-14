"""
Startup Preflight Checks
=========================

Validates that all required environment variables and external services
are reachable **before** the server starts accepting requests.

Called from ``server.py`` during the ``@app.on_event("startup")`` hook.
Any CRITICAL failure raises ``SystemExit`` so the process dies immediately
rather than serving broken 500s.

Usage::

    from lib.agent.preflight import run_preflight_checks

    @app.on_event("startup")
    async def startup_event():
        run_preflight_checks()   # dies if critical vars missing
        ...
"""

import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =========================================================================
# Environment variable definitions
# =========================================================================

# (var_name, is_critical, description)
# CRITICAL = server should refuse to start
# WARNING  = log a warning but continue (degraded functionality)
_ENV_REQUIREMENTS: List[Tuple[str, bool, str]] = [
    # --- Critical: server cannot function without these ---
    ("ANTHROPIC_API_KEY", True, "Required for Claude LLM calls"),
    ("SUPABASE_URL", True, "Required for all database operations"),
    ("SUPABASE_SERVICE_ROLE_KEY", True, "Required for all database operations"),
    ("AGENT_API_KEY", True, "Required for API authentication"),

    # --- Warning: degraded functionality ---
    ("REDIS_URL", False, "Needed for job queue and salience settings (defaults to localhost)"),
    ("SLACK_BOT_TOKEN", False, "Needed for Slack integration (The Gantry)"),
    ("SLACK_APP_TOKEN", False, "Needed for Slack Socket Mode"),
    ("SLACK_ALERT_WEBHOOK_URL", False, "Needed for failure alerting to Slack"),
    ("TWILIO_ACCOUNT_SID", False, "Needed for SMS functionality"),
    ("TWILIO_AUTH_TOKEN", False, "Needed for SMS functionality"),
    ("USER_GOOGLE_EMAIL", False, "Needed for Gmail integration"),
]


def run_preflight_checks(
    fail_on_critical: bool = True,
) -> Dict[str, bool]:
    """
    Validate all required environment variables at startup.

    Parameters
    ----------
    fail_on_critical : bool
        If ``True`` (default), raises ``SystemExit(1)`` when any critical
        variable is missing.  Set to ``False`` in tests.

    Returns
    -------
    dict
        Mapping of ``{var_name: is_set}`` for all checked variables.
    """
    logger.info("Running preflight checks...")

    results: Dict[str, bool] = {}
    critical_missing: List[str] = []
    warning_missing: List[str] = []

    for var_name, is_critical, description in _ENV_REQUIREMENTS:
        value = os.getenv(var_name)
        is_set = bool(value and value.strip())
        results[var_name] = is_set

        if not is_set:
            if is_critical:
                critical_missing.append(var_name)
                logger.critical(
                    "PREFLIGHT FAIL: %s is not set — %s",
                    var_name, description,
                )
            else:
                warning_missing.append(var_name)
                logger.warning(
                    "PREFLIGHT WARN: %s is not set — %s",
                    var_name, description,
                )

    # Summary
    total = len(_ENV_REQUIREMENTS)
    passed = sum(1 for v in results.values() if v)

    if critical_missing:
        logger.critical(
            "PREFLIGHT FAILED: %d/%d vars set. "
            "Missing critical: %s",
            passed, total, ", ".join(critical_missing),
        )
        if fail_on_critical:
            sys.exit(1)
    elif warning_missing:
        logger.warning(
            "PREFLIGHT PASSED WITH WARNINGS: %d/%d vars set. "
            "Missing optional: %s",
            passed, total, ", ".join(warning_missing),
        )
    else:
        logger.info(
            "PREFLIGHT PASSED: All %d environment variables are set", total,
        )

    return results


def check_redis_reachable(timeout_seconds: float = 3.0) -> bool:
    """
    Best-effort check that Redis is reachable.

    Does NOT block startup if Redis is down (it's a warning-level dep),
    but logs clearly so operators know.

    Returns
    -------
    bool
        True if Redis responded to PING.
    """
    try:
        from backend.services.redis_client import get_redis_client
        client = get_redis_client()
        pong = client.ping()
        if pong:
            logger.info("PREFLIGHT: Redis is reachable")
            return True
        logger.warning("PREFLIGHT: Redis PING returned False")
        return False
    except Exception as exc:
        logger.warning(
            "PREFLIGHT: Redis is not reachable — %s. "
            "Queue features will be unavailable.",
            exc,
        )
        return False
