"""
Comments Router - Entity comments endpoints.

Endpoints:
- GET /comments/entity/{entity_id} - Get all comments for an entity
- POST /comments - Create a new comment
- PUT /comments/{comment_id} - Update a comment
- DELETE /comments/{comment_id} - Delete a comment
"""

import logging
import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID as UUIDType

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from lib.agent.shared import verify_api_key
from supabase import create_client

logger = logging.getLogger(__name__)

# Create router with /comments prefix
router = APIRouter(prefix="/comments", tags=["comments"])

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    logger.warning("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")
    supabase = None
else:
    supabase = create_client(supabase_url, supabase_key)


# Pydantic models
class Comment(BaseModel):
    """Entity comment model"""
    id: str
    entity_id: str
    user_id: Optional[str] = None
    content: str
    created_at: str
    updated_at: str


class CreateCommentRequest(BaseModel):
    """Request model for creating a comment"""
    entity_id: str = Field(..., description="UUID of the entity")
    content: str = Field(..., min_length=1, max_length=5000, description="Comment text")
    user_id: Optional[str] = Field(None, description="Optional user ID")


class UpdateCommentRequest(BaseModel):
    """Request model for updating a comment"""
    content: str = Field(..., min_length=1, max_length=5000, description="Updated comment text")


@router.get("/entity/{entity_id}")
async def get_entity_comments(
    entity_id: str,
    _: bool = Depends(verify_api_key)
) -> List[Comment]:
    """
    Get all comments for a specific entity.

    Args:
        entity_id: UUID of the entity

    Returns:
        List of Comment objects ordered by creation date (newest first)
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        # Validate entity_id is a valid UUID
        UUIDType(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entity_id format")

    try:
        response = supabase.table("entity_comments").select("*").eq(
            "entity_id", entity_id
        ).order("created_at", desc=True).execute()

        if response.data is None:
            return []

        return [Comment(**comment) for comment in response.data]

    except Exception as e:
        logger.error(f"Error fetching comments for entity {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch comments: {str(e)}")


@router.post("")
async def create_comment(
    request: CreateCommentRequest,
    _: bool = Depends(verify_api_key)
) -> Comment:
    """
    Create a new comment on an entity.

    Args:
        request: CreateCommentRequest with entity_id, content, and optional user_id

    Returns:
        The created Comment object
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        # Validate entity_id is a valid UUID
        UUIDType(request.entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entity_id format")

    # Validate user_id if provided
    if request.user_id:
        try:
            UUIDType(request.user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")

    try:
        # Verify entity exists
        entity_response = supabase.table("entities").select("id").eq(
            "id", request.entity_id
        ).execute()

        if not entity_response.data or len(entity_response.data) == 0:
            raise HTTPException(status_code=404, detail="Entity not found")

        # Create comment
        comment_data = {
            "entity_id": request.entity_id,
            "content": request.content,
        }
        
        if request.user_id:
            comment_data["user_id"] = request.user_id

        response = supabase.table("entity_comments").insert(comment_data).execute()

        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to create comment")

        return Comment(**response.data[0])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating comment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create comment: {str(e)}")


@router.put("/{comment_id}")
async def update_comment(
    comment_id: str,
    request: UpdateCommentRequest,
    _: bool = Depends(verify_api_key)
) -> Comment:
    """
    Update an existing comment.

    Args:
        comment_id: UUID of the comment to update
        request: UpdateCommentRequest with new content

    Returns:
        The updated Comment object
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        # Validate comment_id is a valid UUID
        UUIDType(comment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid comment_id format")

    try:
        # Verify comment exists
        existing = supabase.table("entity_comments").select("*").eq(
            "id", comment_id
        ).execute()

        if not existing.data or len(existing.data) == 0:
            raise HTTPException(status_code=404, detail="Comment not found")

        # Update comment
        response = supabase.table("entity_comments").update(
            {"content": request.content}
        ).eq("id", comment_id).execute()

        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to update comment")

        return Comment(**response.data[0])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating comment {comment_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update comment: {str(e)}")


@router.delete("/{comment_id}")
async def delete_comment(
    comment_id: str,
    _: bool = Depends(verify_api_key)
) -> dict:
    """
    Delete a comment.

    Args:
        comment_id: UUID of the comment to delete

    Returns:
        Success confirmation
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")

    try:
        # Validate comment_id is a valid UUID
        UUIDType(comment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid comment_id format")

    try:
        # Verify comment exists
        existing = supabase.table("entity_comments").select("id").eq(
            "id", comment_id
        ).execute()

        if not existing.data or len(existing.data) == 0:
            raise HTTPException(status_code=404, detail="Comment not found")

        # Delete comment
        response = supabase.table("entity_comments").delete().eq(
            "id", comment_id
        ).execute()

        return {"success": True, "message": "Comment deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting comment {comment_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete comment: {str(e)}")
