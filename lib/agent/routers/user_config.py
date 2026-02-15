"""
User Config Router (DEBT-004)
==============================

API endpoints for managing per-user configuration values.

Endpoints:
- GET  /api/settings/user-config  -- Get a config value for a user
- PUT  /api/settings/user-config  -- Set (upsert) a config value for a user
- DELETE /api/settings/user-config -- Delete a config value for a user

Initial use case: phone_number for SMS reminder delivery.
Future: timezone, notification preferences, etc.

PRD Reference: DEBT-004 (SMS Phone Number Configuration)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.agent.shared import verify_api_key

logger = logging.getLogger(__name__)

# Create router with /api/settings prefix (shared with salience_settings)
router = APIRouter(prefix="/api/settings", tags=["user-config"])


# =============================================================================
# Request/Response Models
# =============================================================================


class UserConfigSetRequest(BaseModel):
    """Request body for setting a user config value."""
    config_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Configuration key (e.g., 'phone_number', 'timezone')",
    )
    config_value: str = Field(
        ...,
        max_length=1000,
        description="Configuration value",
    )


class UserConfigGetResponse(BaseModel):
    """Response body for getting a user config value."""
    user_id: str = Field(..., description="User UUID")
    config_key: str = Field(..., description="Configuration key")
    config_value: str = Field(..., description="Configuration value")
    found: bool = Field(..., description="Whether the key was found")


class UserConfigSetResponse(BaseModel):
    """Response body for setting a user config value."""
    user_id: str = Field(..., description="User UUID")
    config_key: str = Field(..., description="Configuration key")
    config_value: str = Field(..., description="Configuration value")
    success: bool = Field(..., description="Whether the operation succeeded")


class UserConfigDeleteResponse(BaseModel):
    """Response body for deleting a user config value."""
    user_id: str = Field(..., description="User UUID")
    config_key: str = Field(..., description="Configuration key")
    success: bool = Field(..., description="Whether the operation succeeded")


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/user-config", response_model=UserConfigGetResponse)
async def get_user_config_endpoint(
    user_id: str = Query(..., description="User UUID"),
    config_key: str = Query(..., description="Configuration key to look up"),
    _: bool = Depends(verify_api_key),
) -> UserConfigGetResponse:
    """
    Get a user configuration value.

    Returns the stored value for the given key, or an empty value with
    ``found=False`` if the key does not exist.

    Parameters
    ----------
    user_id : str
        User UUID.
    config_key : str
        Configuration key to look up.

    Returns
    -------
    UserConfigGetResponse
        The config value and whether it was found.
    """
    logger.info("Getting user config: user=%s key=%s", user_id[:8], config_key)

    try:
        # Lazy import to avoid circular dependencies
        from lib.db.user_config import get_user_config

        value = await get_user_config(user_id, config_key, default="")

        found = bool(value)
        return UserConfigGetResponse(
            user_id=user_id,
            config_key=config_key,
            config_value=value,
            found=found,
        )

    except Exception as exc:
        logger.error("Failed to get user config: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get user config: {str(exc)}",
        )


@router.put("/user-config", response_model=UserConfigSetResponse)
async def set_user_config_endpoint(
    request: UserConfigSetRequest,
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> UserConfigSetResponse:
    """
    Set (upsert) a user configuration value.

    Creates or updates the value for the given key.

    Parameters
    ----------
    request : UserConfigSetRequest
        The config key and value to set.
    user_id : str
        User UUID.

    Returns
    -------
    UserConfigSetResponse
        Success status and the stored value.
    """
    logger.info(
        "Setting user config: user=%s key=%s",
        user_id[:8], request.config_key,
    )

    try:
        # Lazy import to avoid circular dependencies
        from lib.db.user_config import set_user_config

        success = await set_user_config(
            user_id=user_id,
            key=request.config_key,
            value=request.config_value,
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to save user config",
            )

        return UserConfigSetResponse(
            user_id=user_id,
            config_key=request.config_key,
            config_value=request.config_value,
            success=True,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to set user config: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to set user config: {str(exc)}",
        )


@router.delete("/user-config", response_model=UserConfigDeleteResponse)
async def delete_user_config_endpoint(
    user_id: str = Query(..., description="User UUID"),
    config_key: str = Query(..., description="Configuration key to delete"),
    _: bool = Depends(verify_api_key),
) -> UserConfigDeleteResponse:
    """
    Delete a user configuration value.

    Parameters
    ----------
    user_id : str
        User UUID.
    config_key : str
        Configuration key to delete.

    Returns
    -------
    UserConfigDeleteResponse
        Success status.
    """
    logger.info(
        "Deleting user config: user=%s key=%s",
        user_id[:8], config_key,
    )

    try:
        # Lazy import to avoid circular dependencies
        from lib.db.user_config import delete_user_config

        success = await delete_user_config(
            user_id=user_id,
            key=config_key,
        )

        return UserConfigDeleteResponse(
            user_id=user_id,
            config_key=config_key,
            success=success,
        )

    except Exception as exc:
        logger.error("Failed to delete user config: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete user config: {str(exc)}",
        )
