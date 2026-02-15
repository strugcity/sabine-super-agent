"""
Skill Digest Service
=====================

Generates a weekly summary of skill acquisition activity:
- Gaps detected this week
- Proposals awaiting review
- Skills promoted/disabled

Sent via the existing Slack webhook in ``backend/worker/alerts.py``.

PRD Reference: Phase 3 — Observability
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

logger = logging.getLogger(__name__)


def _get_supabase_client() -> Optional[Client]:
    """Get Supabase client for digest queries."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.warning("Supabase credentials not configured — digest disabled")
        return None
    return create_client(url, key)


async def generate_weekly_digest() -> Dict[str, Any]:
    """
    Generate a weekly skill acquisition digest.

    Queries the last 7 days of skill_gaps, skill_proposals, and
    skill_versions activity and formats a summary.

    Returns
    -------
    dict
        Digest data with gaps_opened, proposals_pending,
        skills_promoted, skills_disabled, summary_text.
    """
    client = _get_supabase_client()
    if not client:
        return {"status": "skipped", "reason": "Supabase not configured"}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    # Count gaps opened this week
    gaps_result = client.table("skill_gaps")\
        .select("id, tool_name, status", count="exact")\
        .gte("created_at", cutoff)\
        .execute()
    gaps_opened = gaps_result.count if gaps_result.count is not None else len(gaps_result.data or [])
    gap_tools: List[str] = [
        g.get("tool_name", "unknown")
        for g in (gaps_result.data or [])
        if g.get("tool_name")
    ]

    # Count proposals pending review
    pending_result = client.table("skill_proposals")\
        .select("id, skill_name", count="exact")\
        .eq("status", "pending")\
        .execute()
    proposals_pending = pending_result.count if pending_result.count is not None else len(pending_result.data or [])
    pending_names: List[str] = [
        p.get("skill_name", "unknown")
        for p in (pending_result.data or [])
    ]

    # Count skills promoted this week
    promoted_result = client.table("skill_versions")\
        .select("id, skill_name, version", count="exact")\
        .gte("promoted_at", cutoff)\
        .eq("is_active", True)\
        .execute()
    skills_promoted = promoted_result.count if promoted_result.count is not None else len(promoted_result.data or [])

    # Count skills disabled this week
    disabled_result = client.table("skill_versions")\
        .select("id, skill_name", count="exact")\
        .gte("disabled_at", cutoff)\
        .eq("is_active", False)\
        .execute()
    skills_disabled = disabled_result.count if disabled_result.count is not None else len(disabled_result.data or [])

    # Build summary text
    lines: List[str] = [
        "*Sabine Skill Digest — Weekly Summary*",
        f"_Period: {cutoff[:10]} to {datetime.now(timezone.utc).strftime('%Y-%m-%d')}_",
        "",
    ]

    if gaps_opened > 0:
        tools_str = ", ".join(gap_tools[:5])
        lines.append(f":mag: *{gaps_opened} new gaps detected* — {tools_str}")
    else:
        lines.append(":white_check_mark: No new gaps detected")

    if proposals_pending > 0:
        names_str = ", ".join(pending_names[:5])
        lines.append(f":inbox_tray: *{proposals_pending} proposals awaiting review* — {names_str}")
    else:
        lines.append(":sparkles: No proposals pending")

    if skills_promoted > 0:
        lines.append(f":rocket: *{skills_promoted} skills promoted* this week")

    if skills_disabled > 0:
        lines.append(f":no_entry_sign: *{skills_disabled} skills disabled* this week")

    if gaps_opened == 0 and proposals_pending == 0 and skills_promoted == 0:
        lines.append("\n_Quiet week — no skill acquisition activity._")

    summary_text = "\n".join(lines)

    return {
        "status": "generated",
        "gaps_opened": gaps_opened,
        "proposals_pending": proposals_pending,
        "skills_promoted": skills_promoted,
        "skills_disabled": skills_disabled,
        "summary_text": summary_text,
    }


async def send_weekly_digest() -> Dict[str, Any]:
    """
    Generate and send the weekly skill digest via Slack webhook.

    Uses the same Slack webhook mechanism as ``backend/worker/alerts.py``.

    Returns
    -------
    dict
        {"status": "sent"|"skipped"|"failed", ...}
    """
    digest = await generate_weekly_digest()

    if digest.get("status") != "generated":
        logger.info("Digest skipped: %s", digest.get("reason", "unknown"))
        return digest

    # Check if there's anything worth sending
    if (
        digest["gaps_opened"] == 0
        and digest["proposals_pending"] == 0
        and digest["skills_promoted"] == 0
        and digest["skills_disabled"] == 0
    ):
        logger.info("No skill activity this week — skipping digest")
        return {"status": "skipped", "reason": "no activity"}

    # Send via Slack webhook
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set — cannot send digest")
        return {"status": "skipped", "reason": "no webhook configured"}

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                webhook_url,
                json={"text": digest["summary_text"]},
            )
            response.raise_for_status()

        logger.info(
            "Weekly digest sent: gaps=%d, pending=%d, promoted=%d",
            digest["gaps_opened"],
            digest["proposals_pending"],
            digest["skills_promoted"],
        )

        return {
            "status": "sent",
            **{k: v for k, v in digest.items() if k != "status"},
        }

    except Exception as e:
        logger.error("Failed to send weekly digest: %s", e)
        return {"status": "failed", "error": str(e)}
