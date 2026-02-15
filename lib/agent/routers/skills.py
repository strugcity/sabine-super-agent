"""
Skills Management Router (Phase 3)
====================================

API endpoints for the autonomous skill acquisition pipeline:
- View detected capability gaps
- Review and approve/reject skill proposals
- Manage active skill inventory (disable, rollback)
- Manually trigger skill generation from description

PRD Requirements: SKILL-007, SKILL-008, SKILL-009, SKILL-010, SKILL-011
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.agent.shared import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SkillGapResponse(BaseModel):
    """A detected skill gap."""
    id: str
    gap_type: str
    tool_name: Optional[str] = None
    pattern_description: str
    occurrence_count: int
    status: str
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None


class SkillProposalResponse(BaseModel):
    """A generated skill proposal."""
    id: str
    gap_id: Optional[str] = None
    skill_name: str
    description: str
    manifest_json: Dict[str, Any]
    sandbox_passed: bool
    roi_estimate: Optional[str] = None
    status: str
    created_at: Optional[str] = None


class SkillVersionResponse(BaseModel):
    """An active skill version."""
    id: str
    skill_name: str
    version: str
    description: Optional[str] = None
    is_active: bool
    promoted_at: Optional[str] = None


class ApproveRejectRequest(BaseModel):
    """Request to approve or reject a proposal."""
    reason: Optional[str] = Field(
        default=None,
        description="Optional reason for rejection",
    )


class PrototypeRequest(BaseModel):
    """Request to generate a skill from a description."""
    description: str = Field(
        ..., min_length=10,
        description="Description of the skill to generate (min 10 chars)",
    )


class PromoteResponse(BaseModel):
    """Response from skill promotion."""
    status: str
    skill_version_id: Optional[str] = None
    skill_name: str
    version: Optional[str] = None


class SkillActionResponse(BaseModel):
    """Generic response for skill actions."""
    status: str
    message: str


# =============================================================================
# Gap Endpoints
# =============================================================================

@router.get("/gaps", response_model=List[SkillGapResponse])
async def list_gaps(
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> List[SkillGapResponse]:
    """
    List open skill gaps for a user.

    Returns gaps ordered by occurrence count (most frequent first).
    """
    from backend.services.gap_detection import get_open_gaps

    gaps = await get_open_gaps(user_id)
    return [SkillGapResponse(**g) for g in gaps]


@router.post("/gaps/{gap_id}/dismiss", response_model=SkillActionResponse)
async def dismiss_gap_endpoint(
    gap_id: str,
    _: bool = Depends(verify_api_key),
) -> SkillActionResponse:
    """
    Dismiss a skill gap (mark as not worth fixing).
    """
    from backend.services.gap_detection import dismiss_gap

    result = await dismiss_gap(gap_id)
    return SkillActionResponse(
        status=result["status"],
        message=f"Gap {gap_id} dismissed",
    )


# =============================================================================
# Proposal Endpoints
# =============================================================================

@router.get("/proposals", response_model=List[SkillProposalResponse])
async def list_proposals(
    user_id: str = Query(..., description="User UUID"),
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: pending, approved, rejected, promoted",
    ),
    _: bool = Depends(verify_api_key),
) -> List[SkillProposalResponse]:
    """
    List skill proposals for a user.

    Optionally filter by status. Defaults to showing all proposals.
    """
    import os
    from supabase import create_client

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    client = create_client(url, key)

    query = client.table("skill_proposals")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)

    if status:
        query = query.eq("status", status)

    result = query.execute()
    proposals = result.data or []

    return [SkillProposalResponse(**p) for p in proposals]


@router.post("/proposals/{proposal_id}/approve", response_model=PromoteResponse)
async def approve_proposal(
    proposal_id: str,
    _: bool = Depends(verify_api_key),
) -> PromoteResponse:
    """
    Approve a skill proposal and promote it to the active registry.

    This will:
    1. Update proposal status to 'approved'
    2. Create a skill_versions entry
    3. Deactivate any previous version of the same skill
    4. Make the skill available in the tool registry (hot-reload)
    """
    import os
    from supabase import create_client

    # First update status to approved
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    client = create_client(url, key)
    client.table("skill_proposals")\
        .update({"status": "approved"})\
        .eq("id", proposal_id)\
        .execute()

    # Then promote
    from backend.services.skill_promotion import promote_skill

    try:
        result = await promote_skill(proposal_id)
        return PromoteResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to promote skill: %s", e)
        raise HTTPException(status_code=500, detail=f"Promotion failed: {str(e)}")


@router.post("/proposals/{proposal_id}/reject", response_model=SkillActionResponse)
async def reject_proposal(
    proposal_id: str,
    request: ApproveRejectRequest,
    _: bool = Depends(verify_api_key),
) -> SkillActionResponse:
    """
    Reject a skill proposal.
    """
    import os
    from supabase import create_client
    from datetime import datetime, timezone

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    client = create_client(url, key)
    client.table("skill_proposals")\
        .update({
            "status": "rejected",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })\
        .eq("id", proposal_id)\
        .execute()

    logger.info("Rejected proposal %s: %s", proposal_id, request.reason)

    return SkillActionResponse(
        status="rejected",
        message=f"Proposal {proposal_id} rejected" + (f": {request.reason}" if request.reason else ""),
    )


# =============================================================================
# Inventory Endpoints
# =============================================================================

@router.get("/inventory", response_model=List[SkillVersionResponse])
async def list_inventory(
    user_id: str = Query(..., description="User UUID"),
    include_inactive: bool = Query(default=False, description="Include disabled skills"),
    _: bool = Depends(verify_api_key),
) -> List[SkillVersionResponse]:
    """
    List active (and optionally inactive) skills for a user.
    """
    import os
    from supabase import create_client

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    client = create_client(url, key)

    query = client.table("skill_versions")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("promoted_at", desc=True)

    if not include_inactive:
        query = query.eq("is_active", True)

    result = query.execute()
    versions = result.data or []

    response_list: List[SkillVersionResponse] = []
    for v in versions:
        manifest = v.get("manifest_json", {})
        response_list.append(SkillVersionResponse(
            id=v["id"],
            skill_name=v["skill_name"],
            version=v["version"],
            description=manifest.get("description") if isinstance(manifest, dict) else None,
            is_active=v["is_active"],
            promoted_at=v.get("promoted_at"),
        ))

    return response_list


@router.post("/{skill_version_id}/disable", response_model=SkillActionResponse)
async def disable_skill_endpoint(
    skill_version_id: str,
    _: bool = Depends(verify_api_key),
) -> SkillActionResponse:
    """
    Disable an active skill.
    """
    from backend.services.skill_promotion import disable_skill

    try:
        result = await disable_skill(skill_version_id)
        return SkillActionResponse(
            status=result["status"],
            message=f"Skill {result['skill_name']} v{result['version']} disabled",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to disable skill: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{skill_name}/rollback", response_model=SkillActionResponse)
async def rollback_skill_endpoint(
    skill_name: str,
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> SkillActionResponse:
    """
    Rollback a skill to its previous version.
    """
    from backend.services.skill_promotion import rollback_skill

    try:
        result = await rollback_skill(skill_name, user_id)
        return SkillActionResponse(
            status=result["status"],
            message=(
                f"Rolled back {skill_name}: "
                f"v{result['from_version']} -> v{result['to_version']}"
                if result.get("to_version")
                else f"Disabled {skill_name} v{result['from_version']} (no previous version)"
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to rollback skill: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Manual Trigger
# =============================================================================

@router.post("/prototype", response_model=SkillProposalResponse)
async def prototype_skill(
    request: PrototypeRequest,
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> SkillProposalResponse:
    """
    Generate and test a skill from a free-text description.

    This is the manual trigger -- bypasses gap detection and goes
    straight to generation + sandbox testing.
    """
    from backend.services.skill_generator import generate_skill_from_description

    result = await generate_skill_from_description(
        user_id=user_id,
        description=request.description,
    )

    if result.get("status") == "failed":
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Skill generation failed"),
        )

    # Fetch the created proposal to return full data
    import os
    from supabase import create_client

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    client = create_client(url, key)
    proposal = client.table("skill_proposals")\
        .select("*")\
        .eq("id", result["proposal_id"])\
        .single()\
        .execute()

    if not proposal.data:
        raise HTTPException(status_code=500, detail="Proposal created but not found")

    return SkillProposalResponse(**proposal.data)
