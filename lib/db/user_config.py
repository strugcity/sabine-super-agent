"""
User Configuration Store (DEBT-004)
====================================

Provides async helpers for reading and writing per-user configuration
values from the ``user_config`` table.

Initial use case: phone number for SMS reminder delivery.
Future: timezone overrides, notification preferences, etc.

Usage::

    phone = await get_user_config(user_id, "phone_number")
    await set_user_config(user_id, "phone_number", "+15551234567")
"""

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field
from supabase import Client, create_client

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

USER_CONFIG_TABLE = "user_config"

_supabase_client: Optional[Client] = None


def _get_supabase() -> Optional[Client]:
    """Get or create the Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            logger.warning(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set; "
                "user_config operations will be unavailable"
            )
            return None
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase_client


# =============================================================================
# Pydantic Models
# =============================================================================


class UserConfigEntry(BaseModel):
    """A single user configuration entry."""
    user_id: str = Field(..., description="User UUID")
    config_key: str = Field(..., description="Configuration key")
    config_value: str = Field(..., description="Configuration value")


class UserConfigUpdateRequest(BaseModel):
    """Request body for setting a user config value."""
    user_id: str = Field(..., description="User UUID")
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


class UserConfigResponse(BaseModel):
    """Response for user config operations."""
    success: bool
    user_id: str
    config_key: str
    config_value: str
    message: str = ""


# =============================================================================
# Core Functions
# =============================================================================


async def get_user_config(
    user_id: str,
    key: str,
    default: str = "",
) -> str:
    """
    Fetch a user configuration value from the ``user_config`` table.

    Args:
        user_id: User UUID string.
        key: Configuration key to look up.
        default: Value to return if the key is not found.

    Returns:
        The config value, or *default* if not found or on error.
    """
    client = _get_supabase()
    if client is None:
        logger.debug("No Supabase client; returning default for %s", key)
        return default

    try:
        response = (
            client.table(USER_CONFIG_TABLE)
            .select("config_value")
            .eq("user_id", user_id)
            .eq("config_key", key)
            .limit(1)
            .execute()
        )

        if response.data and len(response.data) > 0:
            value = response.data[0]["config_value"]
            logger.debug("user_config[%s][%s] = %s", user_id[:8], key, value[:20] if value else "")
            return value

        logger.debug("user_config[%s][%s] not found, using default", user_id[:8], key)
        return default

    except Exception as e:
        logger.warning("Failed to read user_config %s/%s: %s", user_id[:8], key, e)
        return default


async def set_user_config(
    user_id: str,
    key: str,
    value: str,
) -> bool:
    """
    Set (upsert) a user configuration value.

    Args:
        user_id: User UUID string.
        key: Configuration key.
        value: Configuration value.

    Returns:
        True on success, False on failure.
    """
    client = _get_supabase()
    if client is None:
        logger.error("No Supabase client; cannot set user_config %s/%s", user_id[:8], key)
        return False

    try:
        response = (
            client.table(USER_CONFIG_TABLE)
            .upsert(
                {
                    "user_id": user_id,
                    "config_key": key,
                    "config_value": value,
                },
                on_conflict="user_id,config_key",
            )
            .execute()
        )

        if response.data and len(response.data) > 0:
            logger.info("user_config[%s][%s] set successfully", user_id[:8], key)
            return True

        logger.warning("user_config upsert returned no data for %s/%s", user_id[:8], key)
        return False

    except Exception as e:
        logger.error("Failed to set user_config %s/%s: %s", user_id[:8], key, e)
        return False


async def delete_user_config(
    user_id: str,
    key: str,
) -> bool:
    """
    Delete a user configuration entry.

    Args:
        user_id: User UUID string.
        key: Configuration key to delete.

    Returns:
        True on success, False on failure.
    """
    client = _get_supabase()
    if client is None:
        logger.error("No Supabase client; cannot delete user_config %s/%s", user_id[:8], key)
        return False

    try:
        response = (
            client.table(USER_CONFIG_TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("config_key", key)
            .execute()
        )

        logger.info("user_config[%s][%s] deleted", user_id[:8], key)
        return True

    except Exception as e:
        logger.error("Failed to delete user_config %s/%s: %s", user_id[:8], key, e)
        return False
