"""
Database Models for Sabine Context Engine
==========================================

This module defines Pydantic V2 models that map to the Supabase database schema.
These models ensure type safety and validation for the Context Engine.

Architecture: "Monolithic Brain" with Hybrid Storage
- Entities: Structured "Nouns" (Projects, People, Events)
- Memories: Unstructured vector-based context
- Tasks: Action items linked to Entities
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class DomainEnum(str, Enum):
    """Core context domains for Sabine."""
    WORK = "work"
    FAMILY = "family"
    PERSONAL = "personal"
    LOGISTICS = "logistics"


class EntityStatus(str, Enum):
    """Entity lifecycle status."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class TaskStatus(str, Enum):
    """Task lifecycle status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Task priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# =============================================================================
# Entity Models
# =============================================================================

class Entity(BaseModel):
    """
    Entity: The "Nouns" - Projects, People, Events, etc.

    Represents concrete objects that Sabine tracks across domains.
    Attributes field allows flexible, entity-specific data storage.
    """
    id: Optional[UUID] = None
    name: str = Field(..., description="Entity name")
    type: str = Field(...,
                      description="Entity type: project, person, event, location, etc.")
    domain: DomainEnum = Field(...,
                               description="Which domain this entity belongs to")
    attributes: Dict[str, Any] = Field(
        default_factory=dict, description="Flexible JSON for entity-specific data")
    status: EntityStatus = Field(
        default=EntityStatus.ACTIVE, description="Entity lifecycle status")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Q1 Product Launch",
                "type": "project",
                "domain": "work",
                "attributes": {
                    "deadline": "2026-03-31",
                    "team": ["Alice", "Bob"],
                    "budget": 50000
                },
                "status": "active"
            }
        }


class EntityCreate(BaseModel):
    """Schema for creating a new Entity."""
    name: str
    type: str
    domain: DomainEnum
    attributes: Dict[str, Any] = Field(default_factory=dict)
    status: EntityStatus = EntityStatus.ACTIVE


class EntityUpdate(BaseModel):
    """Schema for updating an existing Entity."""
    name: Optional[str] = None
    type: Optional[str] = None
    domain: Optional[DomainEnum] = None
    attributes: Optional[Dict[str, Any]] = None
    status: Optional[EntityStatus] = None


# =============================================================================
# Memory Models
# =============================================================================

class Memory(BaseModel):
    """
    Memory: Unstructured context with vector embeddings.

    Stores fuzzy, semantic memories that can be retrieved via similarity search.
    Links to entities via UUID array.
    """
    id: Optional[UUID] = None
    content: str = Field(..., description="Memory content (text)")
    embedding: Optional[List[float]] = Field(
        default=None, description="Vector embedding (1536 dimensions)")
    entity_links: List[UUID] = Field(
        default_factory=list, description="Array of entity UUIDs this memory references")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional context")
    importance_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Memory importance (0-1)")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator('embedding')
    @classmethod
    def validate_embedding_dimension(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Ensure embedding is 1536 dimensions if provided."""
        if v is not None and len(v) != 1536:
            raise ValueError(
                f"Embedding must be 1536 dimensions, got {len(v)}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "content": "Baseball game moved to 5 PM on Saturday",
                "entity_links": ["550e8400-e29b-41d4-a716-446655440000"],
                "metadata": {
                    "source": "sms",
                    "timestamp": "2026-01-29T12:00:00Z"
                },
                "importance_score": 0.8
            }
        }


class MemoryCreate(BaseModel):
    """Schema for creating a new Memory."""
    content: str
    embedding: Optional[List[float]] = None
    entity_links: List[UUID] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator('embedding')
    @classmethod
    def validate_embedding_dimension(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Ensure embedding is 1536 dimensions if provided."""
        if v is not None and len(v) != 1536:
            raise ValueError(
                f"Embedding must be 1536 dimensions, got {len(v)}")
        return v


class MemoryUpdate(BaseModel):
    """Schema for updating an existing Memory."""
    content: Optional[str] = None
    embedding: Optional[List[float]] = None
    entity_links: Optional[List[UUID]] = None
    metadata: Optional[Dict[str, Any]] = None
    importance_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator('embedding')
    @classmethod
    def validate_embedding_dimension(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        """Ensure embedding is 1536 dimensions if provided."""
        if v is not None and len(v) != 1536:
            raise ValueError(
                f"Embedding must be 1536 dimensions, got {len(v)}")
        return v


# =============================================================================
# Task Models
# =============================================================================

class Task(BaseModel):
    """
    Task: Action items linked to Entities.

    Represents concrete to-do items that may be associated with
    projects, people, or events (Entities).
    """
    id: Optional[UUID] = None
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(
        default=None, description="Detailed task description")
    entity_id: Optional[UUID] = Field(
        default=None, description="Optional link to an entity")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING, description="Task lifecycle status")
    priority: TaskPriority = Field(
        default=TaskPriority.MEDIUM, description="Task priority")
    due_date: Optional[datetime] = Field(
        default=None, description="Task due date")
    completed_at: Optional[datetime] = Field(
        default=None, description="Task completion timestamp")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional task context")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Review Q1 budget proposal",
                "description": "Review and approve the Q1 budget by end of week",
                "entity_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "pending",
                "priority": "high",
                "due_date": "2026-02-05T17:00:00Z",
                "metadata": {
                    "assignee": "Alice",
                    "tags": ["budget", "finance"]
                }
            }
        }


class TaskCreate(BaseModel):
    """Schema for creating a new Task."""
    title: str
    description: Optional[str] = None
    entity_id: Optional[UUID] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    """Schema for updating an existing Task."""
    title: Optional[str] = None
    description: Optional[str] = None
    entity_id: Optional[UUID] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
