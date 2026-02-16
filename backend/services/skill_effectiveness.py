"""
Skill Effectiveness Tracker
=============================

Tracks skill execution outcomes and computes a "dopamine score"
that measures how well a promoted skill is performing.

Dopamine score formula:
    0.40 * success_rate          (% of executions with status='success')
  + 0.25 * (1.0 - edit_rate)    (% where user did NOT edit output)
  + 0.20 * (1.0 - repeat_rate)  (% where user did NOT repeat request)
  + 0.15 * gratitude_rate       (% where user sent thank you)

Skills scoring below a configurable threshold (default 0.3) after
a minimum number of executions (default 10) are auto-disabled.

PRD Requirements: TRAIN-001, TRAIN-002, TRAIN-003
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# Minimum executions before scoring is considered reliable
MIN_EXECUTIONS_FOR_SCORING = 5


def _get_supabase_client() -> Optional[Client]:
    """Get Supabase client for effectiveness queries."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.warning("Supabase credentials not configured — skill effectiveness disabled")
        return None
    return create_client(url, key)


async def record_skill_execution(
    skill_version_id: str,
    user_id: str,
    session_id: Optional[str] = None,
    execution_status: str = "success",
    user_edited_output: bool = False,
    user_sent_thank_you: bool = False,
    user_repeated_request: bool = False,
    conversation_turns: Optional[int] = None,
    execution_time_ms: Optional[int] = None,
    error_message: Optional[str] = None,
) -> Optional[str]:
    """
    Record a single skill execution in the telemetry table.

    Parameters
    ----------
    skill_version_id : str
        UUID of the skill_versions row that was executed.
    user_id : str
        UUID of the user who triggered the execution.
    session_id : str, optional
        Conversation session ID for tracing.
    execution_status : str
        One of 'success', 'error', 'timeout'.
    user_edited_output : bool
        True if the user edited the skill's output.
    user_sent_thank_you : bool
        True if the user sent a gratitude signal.
    user_repeated_request : bool
        True if the user repeated the same request (indicating failure).
    conversation_turns : int, optional
        Number of conversation turns in the session.
    execution_time_ms : int, optional
        Wall-clock execution time in milliseconds.
    error_message : str, optional
        Error message if execution_status is 'error' or 'timeout'.

    Returns
    -------
    str or None
        UUID of the inserted row, or None on failure.
    """
    client = _get_supabase_client()
    if not client:
        return None

    try:
        row: Dict[str, Any] = {
            "skill_version_id": skill_version_id,
            "user_id": user_id,
            "execution_status": execution_status,
            "user_edited_output": user_edited_output,
            "user_sent_thank_you": user_sent_thank_you,
            "user_repeated_request": user_repeated_request,
        }

        if session_id is not None:
            row["session_id"] = session_id
        if conversation_turns is not None:
            row["conversation_turns"] = conversation_turns
        if execution_time_ms is not None:
            row["execution_time_ms"] = execution_time_ms
        if error_message is not None:
            row["error_message"] = error_message

        result = client.table("skill_executions").insert(row).execute()

        if result.data:
            exec_id: str = result.data[0]["id"]
            logger.info(
                "Recorded skill execution: version=%s status=%s id=%s",
                skill_version_id, execution_status, exec_id,
            )
            return exec_id

        logger.warning(
            "Insert returned no data for skill execution: version=%s",
            skill_version_id,
        )
        return None

    except Exception as e:
        logger.error(
            "Failed to record skill execution for version=%s: %s",
            skill_version_id, e,
        )
        return None


async def compute_effectiveness(
    skill_version_id: str,
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """
    Compute the dopamine effectiveness score for a skill version.

    Parameters
    ----------
    skill_version_id : str
        UUID of the skill version to score.
    lookback_days : int
        Number of days to look back for executions (default: 30).

    Returns
    -------
    dict
        If enough data: {"score": float, "total_executions": int,
        "success_rate": float, "edit_rate": float,
        "repeat_rate": float, "gratitude_rate": float}

        If insufficient data: {"score": None,
        "reason": "insufficient_data", "total_executions": int}
    """
    client = _get_supabase_client()
    if not client:
        return {"score": None, "reason": "supabase_not_configured", "total_executions": 0}

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

        result = client.table("skill_executions")\
            .select("execution_status, user_edited_output, user_sent_thank_you, user_repeated_request")\
            .eq("skill_version_id", skill_version_id)\
            .gte("created_at", cutoff)\
            .execute()

        executions = result.data if result.data else []
        total = len(executions)

        if total < MIN_EXECUTIONS_FOR_SCORING:
            return {
                "score": None,
                "reason": "insufficient_data",
                "total_executions": total,
            }

        # Compute rates
        success_count = sum(1 for e in executions if e.get("execution_status") == "success")
        edit_count = sum(1 for e in executions if e.get("user_edited_output") is True)
        repeat_count = sum(1 for e in executions if e.get("user_repeated_request") is True)
        gratitude_count = sum(1 for e in executions if e.get("user_sent_thank_you") is True)

        success_rate = success_count / total
        edit_rate = edit_count / total
        repeat_rate = repeat_count / total
        gratitude_rate = gratitude_count / total

        # Dopamine score
        score = (
            0.40 * success_rate
            + 0.25 * (1.0 - edit_rate)
            + 0.20 * (1.0 - repeat_rate)
            + 0.15 * gratitude_rate
        )

        return {
            "score": round(score, 4),
            "total_executions": total,
            "success_rate": round(success_rate, 4),
            "edit_rate": round(edit_rate, 4),
            "repeat_rate": round(repeat_rate, 4),
            "gratitude_rate": round(gratitude_rate, 4),
        }

    except Exception as e:
        logger.error(
            "Failed to compute effectiveness for version=%s: %s",
            skill_version_id, e,
        )
        return {"score": None, "reason": "error", "error": str(e), "total_executions": 0}


async def score_all_skills(
    user_id: str,
    lookback_days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Score all active skill versions for a user.

    Fetches every active skill_version, computes effectiveness,
    and updates the scoring columns in the database.

    Parameters
    ----------
    user_id : str
        UUID of the user whose skills to score.
    lookback_days : int
        Lookback window in days (default: 30).

    Returns
    -------
    list[dict]
        List of scored skill records with effectiveness data.
    """
    client = _get_supabase_client()
    if not client:
        return []

    try:
        # Fetch all active skill versions for user
        result = client.table("skill_versions")\
            .select("id, skill_name, version")\
            .eq("user_id", user_id)\
            .eq("is_active", True)\
            .execute()

        versions = result.data if result.data else []

        if not versions:
            logger.info("No active skill versions found for user=%s", user_id)
            return []

        scored: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for version in versions:
            version_id: str = version["id"]
            effectiveness = await compute_effectiveness(version_id, lookback_days)

            score = effectiveness.get("score")
            total = effectiveness.get("total_executions", 0)

            # Update skill_versions with scoring data
            update_data: Dict[str, Any] = {
                "total_executions": total,
                "last_scored_at": now_iso,
            }
            if score is not None:
                update_data["effectiveness_score"] = score

            client.table("skill_versions")\
                .update(update_data)\
                .eq("id", version_id)\
                .execute()

            scored.append({
                "skill_version_id": version_id,
                "skill_name": version["skill_name"],
                "version": version["version"],
                **effectiveness,
            })

        logger.info(
            "Scored %d active skills for user=%s",
            len(scored), user_id,
        )
        return scored

    except Exception as e:
        logger.error("Failed to score skills for user=%s: %s", user_id, e)
        return []


async def auto_disable_underperformers(
    user_id: str,
    threshold: float = 0.3,
    min_executions: int = 10,
) -> List[Dict[str, Any]]:
    """
    Find and disable skills that are underperforming.

    A skill is disabled if its effectiveness_score is below the
    threshold AND it has at least min_executions total executions.

    Parameters
    ----------
    user_id : str
        UUID of the user whose skills to check.
    threshold : float
        Score below which a skill is considered underperforming (default: 0.3).
    min_executions : int
        Minimum execution count before auto-disable kicks in (default: 10).

    Returns
    -------
    list[dict]
        List of disabled skill records.
    """
    client = _get_supabase_client()
    if not client:
        return []

    try:
        # Find active skills below threshold with enough executions
        result = client.table("skill_versions")\
            .select("id, skill_name, version, effectiveness_score, total_executions")\
            .eq("user_id", user_id)\
            .eq("is_active", True)\
            .lt("effectiveness_score", threshold)\
            .gte("total_executions", min_executions)\
            .execute()

        underperformers = result.data if result.data else []

        if not underperformers:
            logger.info(
                "No underperforming skills found for user=%s (threshold=%.2f, min_exec=%d)",
                user_id, threshold, min_executions,
            )
            return []

        disabled: List[Dict[str, Any]] = []

        for skill in underperformers:
            version_id: str = skill["id"]
            try:
                # Lazy import to avoid circular dependencies
                from backend.services.skill_promotion import disable_skill

                await disable_skill(version_id)

                disabled.append({
                    "skill_version_id": version_id,
                    "skill_name": skill["skill_name"],
                    "version": skill["version"],
                    "effectiveness_score": skill["effectiveness_score"],
                    "total_executions": skill["total_executions"],
                    "reason": "auto_disabled_low_effectiveness",
                })

                logger.info(
                    "Auto-disabled underperforming skill: %s v%s (score=%.3f, execs=%d)",
                    skill["skill_name"], skill["version"],
                    skill["effectiveness_score"], skill["total_executions"],
                )

            except Exception as e:
                logger.error(
                    "Failed to auto-disable skill %s: %s",
                    skill["skill_name"], e,
                )

        # Log to audit trail
        if disabled:
            try:
                from backend.services.audit_logging import log_tool_execution

                await log_tool_execution(
                    tool_name="skill_effectiveness",
                    tool_action="auto_disable",
                    input_params={
                        "user_id": user_id,
                        "threshold": threshold,
                        "min_executions": min_executions,
                    },
                    output_data={
                        "disabled_count": len(disabled),
                        "disabled_skills": [d["skill_name"] for d in disabled],
                    },
                    status="success",
                    user_id=user_id,
                )
            except Exception as e:
                logger.error("Failed to log auto-disable audit: %s", e)

        logger.info(
            "Auto-disabled %d underperforming skills for user=%s",
            len(disabled), user_id,
        )
        return disabled

    except Exception as e:
        logger.error(
            "Failed to check for underperforming skills for user=%s: %s",
            user_id, e,
        )
        return []
