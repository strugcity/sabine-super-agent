"""
Reminder Database Models
========================

Pydantic V2 models for the Reminder system supporting multi-channel notifications
(SMS, email, Slack, calendar events) with one-time and recurring patterns.

This module follows the existing codebase patterns from lib/db/models.py
and integrates with the Supabase database schema.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class ReminderType(str, Enum):
    """Notification channel types for reminders."""
    SMS = "sms"
    EMAIL = "email"
    SLACK = "slack"
    CALENDAR_EVENT = "calendar_event"


class RepeatPattern(str, Enum):
    """Recurrence patterns for repeating reminders."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


# =============================================================================
# Core Models
# =============================================================================

class Reminder(BaseModel):
    """
    Reminder: Scheduled notifications with multi-channel support.
    
    Represents reminders that can be sent via SMS, email, Slack, or calendar events.
    Supports one-time and recurring patterns with flexible metadata storage.
    """
    id: Optional[UUID] = None
    user_id: UUID = Field(..., description="User who owns this reminder")
    
    # Core reminder data
    title: str = Field(..., min_length=1, description="Reminder title")
    description: Optional[str] = Field(
        default=None, 
        description="Optional detailed description"
    )
    
    # Type and scheduling
    reminder_type: ReminderType = Field(
        default=ReminderType.SMS, 
        description="Primary notification channel"
    )
    scheduled_time: datetime = Field(
        ..., 
        description="When to trigger the reminder (timezone-aware)"
    )
    
    # Recurrence (None = one-time)
    repeat_pattern: Optional[RepeatPattern] = Field(
        default=None, 
        description="Recurrence pattern (None for one-time reminders)"
    )
    
    # Status tracking
    is_active: bool = Field(
        default=True, 
        description="Whether reminder is active"
    )
    is_completed: bool = Field(
        default=False, 
        description="Whether reminder has been completed"
    )
    last_triggered_at: Optional[datetime] = Field(
        default=None, 
        description="When this reminder was last fired (for recurring reminders)"
    )
    
    # Multi-channel notification config
    notification_channels: Dict[str, bool] = Field(
        default_factory=lambda: {"sms": True},
        description="Configuration for which channels to notify"
    )
    
    # Flexible metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (scheduler job ID, tags, custom data)"
    )
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "title": "Take medication",
                "description": "Daily reminder to take morning vitamins",
                "reminder_type": "sms",
                "scheduled_time": "2026-02-03T08:00:00Z",
                "repeat_pattern": "daily",
                "notification_channels": {
                    "sms": True,
                    "email": False
                },
                "metadata": {
                    "category": "health",
                    "scheduler_job_id": "job_123456"
                }
            }
        }


class ReminderCreate(BaseModel):
    """Schema for creating a new Reminder."""
    user_id: UUID = Field(..., description="User who owns this reminder")
    title: str = Field(
        ..., 
        min_length=1, 
        max_length=255, 
        description="Reminder title"
    )
    description: Optional[str] = Field(
        default=None, 
        max_length=1000, 
        description="Optional detailed description"
    )
    
    # Type and scheduling
    reminder_type: ReminderType = Field(
        default=ReminderType.SMS,
        description="Primary notification channel"
    )
    scheduled_time: datetime = Field(
        ..., 
        description="When to trigger the reminder (timezone-aware)"
    )
    
    # Recurrence (None = one-time)
    repeat_pattern: Optional[RepeatPattern] = Field(
        default=None,
        description="Recurrence pattern (None for one-time reminders)"
    )
    
    # Multi-channel notification config
    notification_channels: Dict[str, bool] = Field(
        default_factory=lambda: {"sms": True},
        description="Configuration for which channels to notify"
    )
    
    # Flexible metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (scheduler job ID, tags, custom data)"
    )
    
    @field_validator('scheduled_time')
    @classmethod
    def validate_future_time(cls, v: datetime) -> datetime:
        """Ensure scheduled_time is in the future."""
        if not v.tzinfo:
            raise ValueError("scheduled_time must be timezone-aware")
        
        now = datetime.now(timezone.utc)
        if v <= now:
            raise ValueError(
                f"scheduled_time must be in the future. "
                f"Got {v}, current time is {now}"
            )
        
        return v
    
    @field_validator('notification_channels')
    @classmethod
    def validate_notification_channels(cls, v: Dict[str, bool]) -> Dict[str, bool]:
        """Ensure at least one notification channel is enabled."""
        if not v or not any(v.values()):
            raise ValueError("At least one notification channel must be enabled")
        
        # Validate channel names
        valid_channels = {"sms", "email", "slack", "calendar_event"}
        for channel in v.keys():
            if channel not in valid_channels:
                raise ValueError(
                    f"Invalid notification channel: {channel}. "
                    f"Must be one of {valid_channels}"
                )
        
        return v


class ReminderUpdate(BaseModel):
    """Schema for updating an existing Reminder."""
    title: Optional[str] = Field(
        default=None, 
        min_length=1, 
        max_length=255,
        description="Updated reminder title"
    )
    description: Optional[str] = Field(
        default=None, 
        max_length=1000,
        description="Updated description"
    )
    reminder_type: Optional[ReminderType] = Field(
        default=None,
        description="Updated notification channel"
    )
    scheduled_time: Optional[datetime] = Field(
        default=None,
        description="Updated trigger time (timezone-aware)"
    )
    repeat_pattern: Optional[RepeatPattern] = Field(
        default=None,
        description="Updated recurrence pattern"
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Updated active status"
    )
    is_completed: Optional[bool] = Field(
        default=None,
        description="Updated completion status"
    )
    notification_channels: Optional[Dict[str, bool]] = Field(
        default=None,
        description="Updated notification channel configuration"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Updated metadata"
    )
    
    @field_validator('scheduled_time')
    @classmethod
    def validate_future_time(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Ensure scheduled_time is in the future if provided."""
        if v is None:
            return v
            
        if not v.tzinfo:
            raise ValueError("scheduled_time must be timezone-aware")
        
        now = datetime.now(timezone.utc)
        if v <= now:
            raise ValueError(
                f"scheduled_time must be in the future. "
                f"Got {v}, current time is {now}"
            )
        
        return v
    
    @field_validator('notification_channels')
    @classmethod
    def validate_notification_channels(
        cls, 
        v: Optional[Dict[str, bool]]
    ) -> Optional[Dict[str, bool]]:
        """Ensure at least one notification channel is enabled if provided."""
        if v is None:
            return v
            
        if not any(v.values()):
            raise ValueError("At least one notification channel must be enabled")
        
        # Validate channel names
        valid_channels = {"sms", "email", "slack", "calendar_event"}
        for channel in v.keys():
            if channel not in valid_channels:
                raise ValueError(
                    f"Invalid notification channel: {channel}. "
                    f"Must be one of {valid_channels}"
                )
        
        return v