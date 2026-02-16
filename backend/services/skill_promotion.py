"""
Skill Promotion Service
========================

Handles the lifecycle of skill proposals:
- Promote: approved proposal -> skill_versions + registry refresh
- Disable: deactivate a live skill
- Rollback: disable current, activate previous version

PRD Requirements: SKILL-009, SKILL-010, SKILL-011
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


async def promote_skill(proposal_id: str) -> Dict[str, Any]:
    """
    Promote an approved skill proposal to the skill_versions table.

    Steps:
    1. Fetch the proposal (must be status='approved')
    2. Insert into skill_versions
    3. Update proposal status to 'promoted'
    4. Update the gap status to 'resolved'
    5. Log to audit trail

    Parameters
    ----------
    proposal_id : str
        UUID of the skill proposal to promote.

    Returns
    -------
    dict
        {"status": "promoted", "skill_version_id": ..., "skill_name": ...}
    """
    from backend.services.audit_logging import log_tool_execution

    # Lazy import Supabase
    import os
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase credentials not configured")
    client = create_client(url, key)

    # 1. Fetch proposal
    result = client.table("skill_proposals").select("*").eq("id", proposal_id).single().execute()
    proposal = result.data
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal["status"] not in ("approved", "pending"):
        raise ValueError(f"Proposal {proposal_id} has status '{proposal['status']}', expected 'approved'")

    # 2. Check for existing active version and deactivate
    existing = client.table("skill_versions")\
        .select("id")\
        .eq("user_id", proposal["user_id"])\
        .eq("skill_name", proposal["skill_name"])\
        .eq("is_active", True)\
        .execute()

    if existing.data:
        for old_version in existing.data:
            client.table("skill_versions")\
                .update({
                    "is_active": False,
                    "disabled_at": datetime.now(timezone.utc).isoformat(),
                })\
                .eq("id", old_version["id"])\
                .execute()
            logger.info("Deactivated previous version: %s", old_version["id"])

    # 3. Determine version number
    all_versions = client.table("skill_versions")\
        .select("version")\
        .eq("user_id", proposal["user_id"])\
        .eq("skill_name", proposal["skill_name"])\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()

    if all_versions.data:
        last_version = all_versions.data[0]["version"]
        parts = last_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        new_version = ".".join(parts)
    else:
        new_version = "1.0.0"

    # 4. Insert skill version
    version_entry = {
        "proposal_id": proposal_id,
        "user_id": proposal["user_id"],
        "skill_name": proposal["skill_name"],
        "version": new_version,
        "manifest_json": proposal["manifest_json"],
        "handler_code": proposal["handler_code"],
        "is_active": True,
    }
    version_result = client.table("skill_versions").insert(version_entry).execute()
    skill_version_id = version_result.data[0]["id"] if version_result.data else None

    # 5. Update proposal status
    client.table("skill_proposals")\
        .update({"status": "promoted", "reviewed_at": datetime.now(timezone.utc).isoformat()})\
        .eq("id", proposal_id)\
        .execute()

    # 6. Update gap status if linked
    if proposal.get("gap_id"):
        client.table("skill_gaps")\
            .update({"status": "resolved", "resolved_by_skill": skill_version_id})\
            .eq("id", proposal["gap_id"])\
            .execute()

    # 7. Audit log
    await log_tool_execution(
        tool_name="skill_promotion",
        tool_action="promote",
        input_params={"proposal_id": proposal_id, "skill_name": proposal["skill_name"]},
        output_data={"skill_version_id": skill_version_id, "version": new_version},
        status="success",
        user_id=proposal["user_id"],
    )

    # Refresh the tool registry so the new skill is immediately available
    try:
        from lib.agent.registry import refresh_skill_registry
        await refresh_skill_registry(proposal["user_id"])
        logger.info("Registry refreshed after promoting %s", proposal["skill_name"])
    except Exception as e:
        logger.warning("Failed to refresh registry after promotion: %s", e)

    logger.info(
        "Promoted skill: %s v%s (proposal=%s, version_id=%s)",
        proposal["skill_name"], new_version, proposal_id, skill_version_id,
    )

    return {
        "status": "promoted",
        "skill_version_id": skill_version_id,
        "skill_name": proposal["skill_name"],
        "version": new_version,
    }


async def disable_skill(skill_version_id: str) -> Dict[str, Any]:
    """
    Disable an active skill version.

    Parameters
    ----------
    skill_version_id : str
        UUID of the skill_versions row.

    Returns
    -------
    dict
        {"status": "disabled", "skill_name": ..., "version": ...}
    """
    from backend.services.audit_logging import log_tool_execution

    import os
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase credentials not configured")
    client = create_client(url, key)

    # Fetch current version
    result = client.table("skill_versions").select("*").eq("id", skill_version_id).single().execute()
    version = result.data
    if not version:
        raise ValueError(f"Skill version {skill_version_id} not found")

    # Disable
    client.table("skill_versions")\
        .update({
            "is_active": False,
            "disabled_at": datetime.now(timezone.utc).isoformat(),
        })\
        .eq("id", skill_version_id)\
        .execute()

    # Audit log
    await log_tool_execution(
        tool_name="skill_promotion",
        tool_action="disable",
        input_params={"skill_version_id": skill_version_id},
        status="success",
        user_id=version["user_id"],
    )

    # Refresh the tool registry to remove the disabled skill
    try:
        from lib.agent.registry import refresh_skill_registry
        await refresh_skill_registry(version["user_id"])
        logger.info("Registry refreshed after disabling %s", version["skill_name"])
    except Exception as e:
        logger.warning("Failed to refresh registry after disable: %s", e)

    logger.info("Disabled skill: %s v%s", version["skill_name"], version["version"])

    return {
        "status": "disabled",
        "skill_name": version["skill_name"],
        "version": version["version"],
    }


async def rollback_skill(skill_name: str, user_id: str) -> Dict[str, Any]:
    """
    Rollback a skill to the previous version.

    Disables current active version and activates the most recent
    inactive version.

    Parameters
    ----------
    skill_name : str
        Name of the skill to rollback.
    user_id : str
        Owner user ID.

    Returns
    -------
    dict
        {"status": "rolled_back", "from_version": ..., "to_version": ...}
    """
    from backend.services.audit_logging import log_tool_execution

    import os
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase credentials not configured")
    client = create_client(url, key)

    # Find current active version
    active = client.table("skill_versions")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("skill_name", skill_name)\
        .eq("is_active", True)\
        .execute()

    if not active.data:
        raise ValueError(f"No active version found for skill '{skill_name}'")

    current = active.data[0]

    # Disable current
    client.table("skill_versions")\
        .update({
            "is_active": False,
            "disabled_at": datetime.now(timezone.utc).isoformat(),
        })\
        .eq("id", current["id"])\
        .execute()

    # Find previous version (most recent inactive)
    previous = client.table("skill_versions")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("skill_name", skill_name)\
        .eq("is_active", False)\
        .neq("id", current["id"])\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()

    to_version = None
    if previous.data:
        prev = previous.data[0]
        client.table("skill_versions")\
            .update({"is_active": True, "disabled_at": None})\
            .eq("id", prev["id"])\
            .execute()
        to_version = prev["version"]
        logger.info("Rolled back %s: %s -> %s", skill_name, current["version"], to_version)
    else:
        logger.warning("No previous version to rollback to for %s", skill_name)

    # Audit
    await log_tool_execution(
        tool_name="skill_promotion",
        tool_action="rollback",
        input_params={"skill_name": skill_name, "from": current["version"], "to": to_version},
        status="success",
        user_id=user_id,
    )

    # Refresh the tool registry to swap skill versions
    try:
        from lib.agent.registry import refresh_skill_registry
        await refresh_skill_registry(user_id)
        logger.info("Registry refreshed after rollback of %s", skill_name)
    except Exception as e:
        logger.warning("Failed to refresh registry after rollback: %s", e)

    return {
        "status": "rolled_back",
        "skill_name": skill_name,
        "from_version": current["version"],
        "to_version": to_version,
    }
