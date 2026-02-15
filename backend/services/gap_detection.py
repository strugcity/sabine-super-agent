"""
Gap Detection Service
======================

Analyzes tool audit logs to identify capability gaps that could be
addressed by new skills. Runs as a weekly scheduled job.

Gap types detected:
- repeated_failure: Same tool fails 3+ times in 7 days
- missing_tool: Tool not found errors (future)
- edit_heavy: User edits output heavily (future telemetry)

PRD Requirements: SKILL-001, SKILL-002, SKILL-003
"""

import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# Minimum failures in window to qualify as a gap
MIN_FAILURE_COUNT = 3

# Lookback window in hours (7 days)
LOOKBACK_HOURS = 168


def _get_supabase_client() -> Optional[Client]:
    """Get Supabase client for gap detection queries."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.warning("Supabase credentials not configured — gap detection disabled")
        return None
    return create_client(url, key)


async def get_failure_summary(
    hours: int = LOOKBACK_HOURS,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    Fetch recent tool failures from the audit log.

    Parameters
    ----------
    hours : int
        Lookback window in hours (default: 168 = 7 days).
    limit : int
        Maximum rows to fetch.

    Returns
    -------
    list[dict]
        Raw failure records from tool_audit_log.
    """
    from backend.services.audit_logging import get_recent_failures

    failures = await get_recent_failures(hours=hours, limit=limit)
    logger.info("Fetched %d failure records from audit log (last %dh)", len(failures), hours)
    return failures


def group_failures_by_tool(failures: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Group failures by tool_name and compute summary statistics.

    Parameters
    ----------
    failures : list[dict]
        Raw failure records.

    Returns
    -------
    dict
        Keyed by tool_name, values contain count, error_types, user_ids,
        first_seen, last_seen.
    """
    groups: Dict[str, Dict[str, Any]] = {}

    for failure in failures:
        tool_name = failure.get("tool_name", "unknown")
        if tool_name not in groups:
            groups[tool_name] = {
                "tool_name": tool_name,
                "count": 0,
                "error_types": Counter(),
                "user_ids": set(),
                "error_messages": [],
                "first_seen": failure.get("created_at"),
                "last_seen": failure.get("created_at"),
            }

        g = groups[tool_name]
        g["count"] += 1

        error_type = failure.get("error_type", "unknown")
        g["error_types"][error_type] += 1

        user_id = failure.get("user_id")
        if user_id:
            g["user_ids"].add(user_id)

        error_msg = failure.get("error_message", "")
        if error_msg and len(g["error_messages"]) < 5:
            g["error_messages"].append(error_msg[:200])

        # Track time bounds
        created = failure.get("created_at", "")
        if created:
            if not g["first_seen"] or created < g["first_seen"]:
                g["first_seen"] = created
            if not g["last_seen"] or created > g["last_seen"]:
                g["last_seen"] = created

    return groups


async def detect_gaps(
    user_id: Optional[str] = None,
    min_failures: int = MIN_FAILURE_COUNT,
    hours: int = LOOKBACK_HOURS,
) -> List[Dict[str, Any]]:
    """
    Analyze audit logs and detect skill gaps.

    For each tool with >= min_failures failures in the window,
    creates or updates a skill_gaps record.

    Parameters
    ----------
    user_id : str, optional
        If provided, only analyze failures for this user.
    min_failures : int
        Minimum failure count to qualify as a gap.
    hours : int
        Lookback window in hours.

    Returns
    -------
    list[dict]
        List of detected/updated gaps.
    """
    client = _get_supabase_client()
    if not client:
        return []

    # Fetch failures
    failures = await get_failure_summary(hours=hours)

    # Optionally filter by user
    if user_id:
        failures = [f for f in failures if f.get("user_id") == user_id]

    if not failures:
        logger.info("No failures found in the last %d hours", hours)
        return []

    # Group by tool
    groups = group_failures_by_tool(failures)

    # Filter to tools with enough failures
    significant = {
        name: data for name, data in groups.items()
        if data["count"] >= min_failures
    }

    if not significant:
        logger.info(
            "No tools with >= %d failures (found %d tools with failures)",
            min_failures, len(groups),
        )
        return []

    logger.info(
        "Found %d tools with >= %d failures: %s",
        len(significant), min_failures,
        list(significant.keys()),
    )

    # Upsert gaps
    detected_gaps: List[Dict[str, Any]] = []

    for tool_name, data in significant.items():
        # Build pattern description from error types
        error_summary = ", ".join(
            f"{etype}({count})"
            for etype, count in data["error_types"].most_common(3)
        )
        pattern_desc = (
            f"Tool '{tool_name}' failed {data['count']} times in {hours}h. "
            f"Error types: {error_summary}. "
            f"Sample: {data['error_messages'][0][:100] if data['error_messages'] else 'N/A'}"
        )

        # For each affected user, create/update a gap
        affected_users = list(data["user_ids"]) if data["user_ids"] else [user_id] if user_id else []

        for uid in affected_users:
            if not uid:
                continue

            gap = await _upsert_gap(
                client=client,
                user_id=uid,
                tool_name=tool_name,
                gap_type="repeated_failure",
                pattern_description=pattern_desc,
                occurrence_count=data["count"],
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
            )
            if gap:
                detected_gaps.append(gap)

    logger.info("Detected/updated %d skill gaps", len(detected_gaps))
    return detected_gaps


async def _upsert_gap(
    client: Client,
    user_id: str,
    tool_name: str,
    gap_type: str,
    pattern_description: str,
    occurrence_count: int,
    first_seen: Optional[str],
    last_seen: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Insert or update a skill gap record.

    If an open gap exists for the same user + tool, update it.
    Otherwise, create a new gap.

    Returns the gap record or None on failure.
    """
    try:
        # Check for existing open gap
        existing = client.table("skill_gaps")\
            .select("*")\
            .eq("user_id", user_id)\
            .eq("tool_name", tool_name)\
            .in_("status", ["open", "researching"])\
            .limit(1)\
            .execute()

        now_iso = datetime.now(timezone.utc).isoformat()

        if existing.data:
            # Update existing gap
            gap_id = existing.data[0]["id"]
            updated = client.table("skill_gaps")\
                .update({
                    "occurrence_count": occurrence_count,
                    "pattern_description": pattern_description,
                    "last_seen_at": last_seen or now_iso,
                })\
                .eq("id", gap_id)\
                .execute()

            logger.debug("Updated gap %s for tool %s", gap_id, tool_name)
            return updated.data[0] if updated.data else existing.data[0]
        else:
            # Insert new gap
            new_gap = {
                "user_id": user_id,
                "gap_type": gap_type,
                "tool_name": tool_name,
                "pattern_description": pattern_description,
                "occurrence_count": occurrence_count,
                "first_seen_at": first_seen or now_iso,
                "last_seen_at": last_seen or now_iso,
                "status": "open",
            }
            result = client.table("skill_gaps").insert(new_gap).execute()

            if result.data:
                logger.info("Created new gap for tool %s (user=%s)", tool_name, user_id)
                return result.data[0]
            return None

    except Exception as e:
        logger.error("Failed to upsert gap for tool %s: %s", tool_name, e)
        return None


async def dismiss_gap(gap_id: str) -> Dict[str, Any]:
    """
    Dismiss a skill gap (mark as not worth fixing).

    Parameters
    ----------
    gap_id : str
        UUID of the gap to dismiss.

    Returns
    -------
    dict
        {"status": "dismissed", "gap_id": ...}
    """
    client = _get_supabase_client()
    if not client:
        raise RuntimeError("Supabase not configured")

    client.table("skill_gaps")\
        .update({"status": "dismissed"})\
        .eq("id", gap_id)\
        .execute()

    logger.info("Dismissed gap %s", gap_id)
    return {"status": "dismissed", "gap_id": gap_id}


async def get_open_gaps(user_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all open skill gaps for a user.

    Parameters
    ----------
    user_id : str
        User whose gaps to fetch.

    Returns
    -------
    list[dict]
        Open gap records.
    """
    client = _get_supabase_client()
    if not client:
        return []

    result = client.table("skill_gaps")\
        .select("*")\
        .eq("user_id", user_id)\
        .in_("status", ["open", "researching"])\
        .order("occurrence_count", desc=True)\
        .execute()

    return result.data if result.data else []
