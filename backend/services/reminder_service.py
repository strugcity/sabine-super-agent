"""
Reminder Service - Step 1.2: CRUD Operations
=============================================

This module implements the Reminder Service for creating, reading, updating,
and deleting reminders. It provides the data layer for the hybrid reminder
system supporting SMS, email, Slack, and calendar notifications.

Key Features:
1. Full CRUD operations for reminders
2. Active reminder filtering and sorting
3. Soft delete (cancel) support
4. Completion tracking for recurring reminders
5. Structured error handling with OperationResult

Owner: @backend-architect-sabine
PRD Reference: Reminder System Development Plan - Step 1.2
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from supabase import Client, create_client

from backend.services.exceptions import (
    DatabaseError,
    MissingCredentialsError,
    OperationResult,
    SABINEError,
)

# Import reminder models from the committed file
# Note: These are in the remote repo; locally we define inline for now
# TODO: Sync lib/db/models/reminder.py locally after git pull

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

REMINDERS_TABLE = "reminders"


# =============================================================================
# Custom Exceptions for Reminder Service
# =============================================================================

class ReminderNotFoundError(DatabaseError):
    """Raised when a reminder is not found."""

    def __init__(
        self,
        reminder_id: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(
            message=f"Reminder not found: {reminder_id}",
            operation="select",
            table=REMINDERS_TABLE,
            context={"reminder_id": reminder_id},
            original_error=original_error,
        )
        self.status_code = 404  # Not Found


class ReminderValidationError(SABINEError):
    """Raised when reminder validation fails."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        from backend.services.exceptions import ErrorCategory
        ctx = context or {}
        if field:
            ctx["field"] = field

        super().__init__(
            message=message,
            status_code=400,
            category=ErrorCategory.VALIDATION,
            context=ctx,
            original_error=original_error,
        )


# =============================================================================
# Reminder Service
# =============================================================================

class ReminderService:
    """
    Service for managing reminders with full CRUD operations.

    Provides methods for:
    - Creating reminders with validation
    - Retrieving reminders by ID or user
    - Updating reminder properties
    - Soft-deleting (cancelling) reminders
    - Marking reminders as completed

    All methods return OperationResult for structured error handling.
    """

    def __init__(self, supabase_client: Optional[Client] = None):
        """
        Initialize the ReminderService.

        Args:
            supabase_client: Optional Supabase client. If not provided,
                           creates one from environment variables.
        """
        if supabase_client:
            self.client = supabase_client
        elif SUPABASE_URL and SUPABASE_SERVICE_KEY:
            self.client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        else:
            logger.warning("Supabase credentials not configured - ReminderService will not work")
            self.client = None

    # =========================================================================
    # Create Operations
    # =========================================================================

    async def create_reminder(
        self,
        user_id: UUID,
        title: str,
        scheduled_time: datetime,
        description: Optional[str] = None,
        reminder_type: str = "sms",
        repeat_pattern: Optional[str] = None,
        notification_channels: Optional[Dict[str, bool]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OperationResult:
        """
        Create a new reminder.

        Args:
            user_id: UUID of the user who owns this reminder
            title: Reminder title (required, non-empty)
            scheduled_time: When to trigger the reminder (must be in future)
            description: Optional detailed description
            reminder_type: Notification type (sms, email, slack, calendar_event)
            repeat_pattern: Recurrence pattern (daily, weekly, monthly, yearly) or None
            notification_channels: Channel configuration (e.g., {"sms": True})
            metadata: Additional context (scheduler job ID, tags, etc.)

        Returns:
            OperationResult with created reminder data on success
        """
        # Validate inputs BEFORE checking database connectivity
        # This allows unit testing of validation logic without Supabase

        # Validate title
        if not title or not title.strip():
            return OperationResult.fail(
                ReminderValidationError(
                    message="Title is required and cannot be empty",
                    field="title"
                )
            )

        # Validate scheduled_time is in the future
        now = datetime.now(timezone.utc)
        if scheduled_time.tzinfo is None:
            return OperationResult.fail(
                ReminderValidationError(
                    message="scheduled_time must be timezone-aware",
                    field="scheduled_time"
                )
            )
        if scheduled_time <= now:
            return OperationResult.fail(
                ReminderValidationError(
                    message=f"scheduled_time must be in the future. Got {scheduled_time}, current time is {now}",
                    field="scheduled_time"
                )
            )

        # Validate reminder_type
        valid_types = {"sms", "email", "slack", "calendar_event"}
        if reminder_type not in valid_types:
            return OperationResult.fail(
                ReminderValidationError(
                    message=f"Invalid reminder_type: {reminder_type}. Must be one of {valid_types}",
                    field="reminder_type"
                )
            )

        # Validate repeat_pattern
        valid_patterns = {None, "daily", "weekly", "monthly", "yearly"}
        if repeat_pattern not in valid_patterns:
            return OperationResult.fail(
                ReminderValidationError(
                    message=f"Invalid repeat_pattern: {repeat_pattern}. Must be one of {valid_patterns}",
                    field="repeat_pattern"
                )
            )

        # Default notification channels
        if notification_channels is None:
            notification_channels = {"sms": True}

        # Validate at least one channel is enabled
        if not any(notification_channels.values()):
            return OperationResult.fail(
                ReminderValidationError(
                    message="At least one notification channel must be enabled",
                    field="notification_channels"
                )
            )

        # NOW check database connectivity (after all validation passes)
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        reminder_data = {
            "user_id": str(user_id),
            "title": title.strip(),
            "description": description,
            "reminder_type": reminder_type,
            "scheduled_time": scheduled_time.isoformat(),
            "repeat_pattern": repeat_pattern,
            "notification_channels": notification_channels,
            "metadata": metadata or {},
            "is_active": True,
            "is_completed": False,
        }

        try:
            response = self.client.table(REMINDERS_TABLE).insert(reminder_data).execute()

            if response.data and len(response.data) > 0:
                created = response.data[0]
                logger.info(f"Created reminder {created['id']} for user {user_id}")
                return OperationResult.ok({
                    "reminder_id": created["id"],
                    "reminder": created,
                })
            else:
                return OperationResult.fail(
                    DatabaseError(
                        message="No data returned from insert",
                        operation="insert",
                        table=REMINDERS_TABLE,
                    )
                )

        except Exception as e:
            logger.error(f"Failed to create reminder: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to create reminder: {str(e)}",
                    operation="insert",
                    table=REMINDERS_TABLE,
                    original_error=e,
                )
            )

    # =========================================================================
    # Read Operations
    # =========================================================================

    async def get_reminder(self, reminder_id: UUID) -> OperationResult:
        """
        Get a specific reminder by ID.

        Args:
            reminder_id: The reminder UUID

        Returns:
            OperationResult with reminder data on success
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            response = self.client.table(REMINDERS_TABLE).select("*").eq(
                "id", str(reminder_id)
            ).execute()

            if response.data and len(response.data) > 0:
                return OperationResult.ok({"reminder": response.data[0]})

            return OperationResult.fail(
                ReminderNotFoundError(reminder_id=str(reminder_id))
            )

        except Exception as e:
            logger.error(f"Error getting reminder {reminder_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to retrieve reminder: {str(e)}",
                    operation="select",
                    table=REMINDERS_TABLE,
                    context={"reminder_id": str(reminder_id)},
                    original_error=e,
                )
            )

    async def list_active_reminders(
        self,
        user_id: UUID,
        limit: int = 100,
    ) -> OperationResult:
        """
        List all active reminders for a user, sorted by scheduled_time.

        Args:
            user_id: The user's UUID
            limit: Maximum number of reminders to return (default 100)

        Returns:
            OperationResult with list of reminders on success
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            response = self.client.table(REMINDERS_TABLE).select("*").eq(
                "user_id", str(user_id)
            ).eq(
                "is_active", True
            ).order(
                "scheduled_time", desc=False
            ).limit(limit).execute()

            reminders = response.data or []
            logger.info(f"Found {len(reminders)} active reminders for user {user_id}")

            return OperationResult.ok({
                "reminders": reminders,
                "count": len(reminders),
            })

        except Exception as e:
            logger.error(f"Error listing reminders for user {user_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to list reminders: {str(e)}",
                    operation="select",
                    table=REMINDERS_TABLE,
                    context={"user_id": str(user_id)},
                    original_error=e,
                )
            )

    async def list_due_reminders(
        self,
        before_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> OperationResult:
        """
        List reminders that are due for triggering (for scheduler polling).

        Args:
            before_time: Get reminders scheduled before this time (default: now)
            limit: Maximum number of reminders to return

        Returns:
            OperationResult with list of due reminders
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        if before_time is None:
            before_time = datetime.now(timezone.utc)

        try:
            response = self.client.table(REMINDERS_TABLE).select("*").eq(
                "is_active", True
            ).eq(
                "is_completed", False
            ).lte(
                "scheduled_time", before_time.isoformat()
            ).order(
                "scheduled_time", desc=False
            ).limit(limit).execute()

            reminders = response.data or []
            logger.info(f"Found {len(reminders)} due reminders")

            return OperationResult.ok({
                "reminders": reminders,
                "count": len(reminders),
            })

        except Exception as e:
            logger.error(f"Error listing due reminders: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to list due reminders: {str(e)}",
                    operation="select",
                    table=REMINDERS_TABLE,
                    original_error=e,
                )
            )

    async def search_reminders_by_title(
        self,
        user_id: UUID,
        search_term: str,
        active_only: bool = True,
        limit: int = 10,
    ) -> OperationResult:
        """
        Search for reminders by title using case-insensitive partial matching.

        Args:
            user_id: The user's UUID
            search_term: Search term to match against reminder titles
            active_only: If True, only search active reminders (default: True)
            limit: Maximum number of results to return (default: 10)

        Returns:
            OperationResult with list of matching reminders
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        if not search_term or not search_term.strip():
            return OperationResult.fail(
                ReminderValidationError(
                    message="Search term cannot be empty",
                    field="search_term"
                )
            )

        try:
            # Build query with case-insensitive ILIKE search
            query = self.client.table(REMINDERS_TABLE).select("*").eq(
                "user_id", str(user_id)
            ).ilike(
                "title", f"%{search_term.strip()}%"
            )

            if active_only:
                query = query.eq("is_active", True)

            response = query.order(
                "scheduled_time", desc=False
            ).limit(limit).execute()

            reminders = response.data or []
            logger.info(
                f"Found {len(reminders)} reminders matching '{search_term}' for user {user_id}"
            )

            return OperationResult.ok({
                "reminders": reminders,
                "count": len(reminders),
                "search_term": search_term.strip(),
            })

        except Exception as e:
            logger.error(f"Error searching reminders: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to search reminders: {str(e)}",
                    operation="select",
                    table=REMINDERS_TABLE,
                    context={"user_id": str(user_id), "search_term": search_term},
                    original_error=e,
                )
            )

    # =========================================================================
    # Update Operations
    # =========================================================================

    async def update_reminder(
        self,
        reminder_id: UUID,
        title: Optional[str] = None,
        description: Optional[str] = None,
        reminder_type: Optional[str] = None,
        scheduled_time: Optional[datetime] = None,
        repeat_pattern: Optional[str] = None,
        notification_channels: Optional[Dict[str, bool]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OperationResult:
        """
        Update a reminder's properties.

        Only provided fields will be updated. Pass None to keep existing values.

        Args:
            reminder_id: The reminder UUID
            title: New title (if provided)
            description: New description (if provided)
            reminder_type: New notification type (if provided)
            scheduled_time: New scheduled time (if provided, must be in future)
            repeat_pattern: New recurrence pattern (if provided)
            notification_channels: New channel config (if provided)
            metadata: New metadata (if provided)

        Returns:
            OperationResult with updated reminder on success
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        # Build update data from non-None values
        update_data: Dict[str, Any] = {}

        if title is not None:
            if not title.strip():
                return OperationResult.fail(
                    ReminderValidationError(
                        message="Title cannot be empty",
                        field="title"
                    )
                )
            update_data["title"] = title.strip()

        if description is not None:
            update_data["description"] = description

        if reminder_type is not None:
            valid_types = {"sms", "email", "slack", "calendar_event"}
            if reminder_type not in valid_types:
                return OperationResult.fail(
                    ReminderValidationError(
                        message=f"Invalid reminder_type: {reminder_type}",
                        field="reminder_type"
                    )
                )
            update_data["reminder_type"] = reminder_type

        if scheduled_time is not None:
            if scheduled_time.tzinfo is None:
                return OperationResult.fail(
                    ReminderValidationError(
                        message="scheduled_time must be timezone-aware",
                        field="scheduled_time"
                    )
                )
            now = datetime.now(timezone.utc)
            if scheduled_time <= now:
                return OperationResult.fail(
                    ReminderValidationError(
                        message="scheduled_time must be in the future",
                        field="scheduled_time"
                    )
                )
            update_data["scheduled_time"] = scheduled_time.isoformat()

        if repeat_pattern is not None:
            valid_patterns = {"daily", "weekly", "monthly", "yearly"}
            if repeat_pattern and repeat_pattern not in valid_patterns:
                return OperationResult.fail(
                    ReminderValidationError(
                        message=f"Invalid repeat_pattern: {repeat_pattern}",
                        field="repeat_pattern"
                    )
                )
            update_data["repeat_pattern"] = repeat_pattern if repeat_pattern else None

        if notification_channels is not None:
            if not any(notification_channels.values()):
                return OperationResult.fail(
                    ReminderValidationError(
                        message="At least one notification channel must be enabled",
                        field="notification_channels"
                    )
                )
            update_data["notification_channels"] = notification_channels

        if metadata is not None:
            update_data["metadata"] = metadata

        if not update_data:
            return OperationResult.fail(
                ReminderValidationError(
                    message="No update fields provided"
                )
            )

        try:
            response = self.client.table(REMINDERS_TABLE).update(
                update_data
            ).eq("id", str(reminder_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Updated reminder {reminder_id}")
                return OperationResult.ok({"reminder": response.data[0]})

            return OperationResult.fail(
                ReminderNotFoundError(reminder_id=str(reminder_id))
            )

        except Exception as e:
            logger.error(f"Error updating reminder {reminder_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to update reminder: {str(e)}",
                    operation="update",
                    table=REMINDERS_TABLE,
                    context={"reminder_id": str(reminder_id)},
                    original_error=e,
                )
            )

    # =========================================================================
    # Status Operations
    # =========================================================================

    async def cancel_reminder(self, reminder_id: UUID) -> OperationResult:
        """
        Cancel (soft-delete) a reminder by setting is_active = False.

        Cancelled reminders will no longer appear in list_active_reminders
        and will not be triggered by the scheduler.

        Args:
            reminder_id: The reminder UUID

        Returns:
            OperationResult with success status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        try:
            response = self.client.table(REMINDERS_TABLE).update({
                "is_active": False
            }).eq("id", str(reminder_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Cancelled reminder {reminder_id}")
                return OperationResult.ok({
                    "reminder_id": str(reminder_id),
                    "status": "cancelled",
                })

            return OperationResult.fail(
                ReminderNotFoundError(reminder_id=str(reminder_id))
            )

        except Exception as e:
            logger.error(f"Error cancelling reminder {reminder_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to cancel reminder: {str(e)}",
                    operation="update",
                    table=REMINDERS_TABLE,
                    context={"reminder_id": str(reminder_id)},
                    original_error=e,
                )
            )

    async def complete_reminder(self, reminder_id: UUID) -> OperationResult:
        """
        Mark a reminder as completed.

        Sets is_completed = True and updates last_triggered_at to now.
        For recurring reminders, this indicates the last occurrence was fired.

        Args:
            reminder_id: The reminder UUID

        Returns:
            OperationResult with success status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        now = datetime.now(timezone.utc)

        try:
            response = self.client.table(REMINDERS_TABLE).update({
                "is_completed": True,
                "last_triggered_at": now.isoformat(),
            }).eq("id", str(reminder_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Completed reminder {reminder_id}")
                return OperationResult.ok({
                    "reminder_id": str(reminder_id),
                    "status": "completed",
                    "completed_at": now.isoformat(),
                })

            return OperationResult.fail(
                ReminderNotFoundError(reminder_id=str(reminder_id))
            )

        except Exception as e:
            logger.error(f"Error completing reminder {reminder_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to complete reminder: {str(e)}",
                    operation="update",
                    table=REMINDERS_TABLE,
                    context={"reminder_id": str(reminder_id)},
                    original_error=e,
                )
            )

    async def update_last_triggered(
        self,
        reminder_id: UUID,
        triggered_at: Optional[datetime] = None,
    ) -> OperationResult:
        """
        Update the last_triggered_at timestamp for a recurring reminder.

        Use this when a recurring reminder fires to track the last occurrence.

        Args:
            reminder_id: The reminder UUID
            triggered_at: When it was triggered (default: now)

        Returns:
            OperationResult with success status
        """
        if not self.client:
            return OperationResult.fail(
                MissingCredentialsError(
                    service="Supabase",
                    required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
                )
            )

        if triggered_at is None:
            triggered_at = datetime.now(timezone.utc)

        try:
            response = self.client.table(REMINDERS_TABLE).update({
                "last_triggered_at": triggered_at.isoformat(),
            }).eq("id", str(reminder_id)).execute()

            if response.data and len(response.data) > 0:
                logger.info(f"Updated last_triggered_at for reminder {reminder_id}")
                return OperationResult.ok({
                    "reminder_id": str(reminder_id),
                    "last_triggered_at": triggered_at.isoformat(),
                })

            return OperationResult.fail(
                ReminderNotFoundError(reminder_id=str(reminder_id))
            )

        except Exception as e:
            logger.error(f"Error updating last_triggered_at for reminder {reminder_id}: {e}")
            return OperationResult.fail(
                DatabaseError(
                    message=f"Failed to update reminder: {str(e)}",
                    operation="update",
                    table=REMINDERS_TABLE,
                    context={"reminder_id": str(reminder_id)},
                    original_error=e,
                )
            )


# =============================================================================
# Module-level convenience functions
# =============================================================================

_service_instance: Optional[ReminderService] = None


def get_reminder_service() -> ReminderService:
    """Get or create the global ReminderService instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ReminderService()
    return _service_instance
