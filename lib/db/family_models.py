"""
Family Entity Graph Models for Sabine Calendar Inference
=========================================================

This module defines specialized Pydantic models for the Family Entity Graph,
which powers the calendar subscription inference engine.

Design Philosophy:
- Extends the existing Entity model (type="family_member", domain="family")
- Uses the flexible `attributes` JSONB field for family-specific data
- Maintains backward compatibility with existing memory/entity pipelines

The Family Entity Graph stores:
- Family member profiles (Jack, Anna, Charlie)
- Keyword mappings for calendar inference (BTBA → Jack)
- Categorized aliases (sports, school, activities)
- Confidence weights for fuzzy matching
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums for Family Context
# =============================================================================

class KeywordCategory(str, Enum):
    """Categories for calendar keyword matching."""
    SPORTS = "sports"
    SCHOOL = "school"
    ACTIVITIES = "activities"
    MEDICAL = "medical"
    SOCIAL = "social"


class RelationshipType(str, Enum):
    """Family relationship types."""
    CHILD = "child"
    PARENT = "parent"
    SPOUSE = "spouse"
    SIBLING = "sibling"
    OTHER = "other"


# =============================================================================
# Keyword Mapping Models
# =============================================================================

class KeywordMapping(BaseModel):
    """
    A set of keywords within a category that map to a family member.

    Example:
        category: "sports"
        keywords: ["btba", "bandits", "baseball"]
        weight: 1.0
    """
    keywords: List[str] = Field(
        ...,
        description="List of keywords/aliases (lowercase, normalized)"
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Confidence weight for this category (0.0-2.0)"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional context (e.g., 'Spring 2026 season')"
    )

    @field_validator('keywords')
    @classmethod
    def normalize_keywords(cls, v: List[str]) -> List[str]:
        """Ensure all keywords are lowercase and stripped."""
        return [kw.lower().strip() for kw in v if kw.strip()]


class CalendarKeywords(BaseModel):
    """
    Complete keyword configuration for a family member.

    Maps categories (sports, school, etc.) to keyword sets with weights.
    """
    sports: Optional[KeywordMapping] = None
    school: Optional[KeywordMapping] = None
    activities: Optional[KeywordMapping] = None
    medical: Optional[KeywordMapping] = None
    social: Optional[KeywordMapping] = None

    # Allow additional custom categories
    extra: Dict[str, KeywordMapping] = Field(
        default_factory=dict,
        description="Custom categories beyond the standard set"
    )

    def all_keywords(self) -> Dict[str, KeywordMapping]:
        """Return all keyword mappings as a flat dictionary."""
        result = {}
        for category in KeywordCategory:
            mapping = getattr(self, category.value, None)
            if mapping:
                result[category.value] = mapping
        result.update(self.extra)
        return result

    def find_matches(self, text: str) -> List[tuple[str, str, float]]:
        """
        Find all keyword matches in the given text.

        Returns: List of (category, matched_keyword, weight) tuples
        """
        text_lower = text.lower()
        matches = []
        for category, mapping in self.all_keywords().items():
            for keyword in mapping.keywords:
                if keyword in text_lower:
                    matches.append((category, keyword, mapping.weight))
        return matches


# =============================================================================
# Family Member Profile
# =============================================================================

class FamilyMemberProfile(BaseModel):
    """
    Complete profile for a family member, stored in Entity.attributes.

    This is the schema for the `attributes` JSONB field when
    Entity.type = "family_member" and Entity.domain = "family".
    """
    # Basic info
    age: Optional[int] = Field(default=None, ge=0, le=120)
    grade: Optional[str] = Field(default=None, description="School grade (e.g., '9th')")
    birthday: Optional[str] = Field(default=None, description="Birthday (MM-DD format)")
    relationship: RelationshipType = Field(
        default=RelationshipType.CHILD,
        description="Relationship to primary user"
    )

    # Calendar inference keywords
    calendar_keywords: CalendarKeywords = Field(
        default_factory=CalendarKeywords,
        description="Keyword mappings for calendar inference"
    )

    # Additional metadata
    schools: List[str] = Field(
        default_factory=list,
        description="Schools attended (current and past)"
    )
    teams: List[str] = Field(
        default_factory=list,
        description="Sports teams (current and past)"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Free-form notes about this family member"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "age": 14,
                "grade": "9th",
                "birthday": "03-15",
                "relationship": "child",
                "calendar_keywords": {
                    "sports": {
                        "keywords": ["btba", "bandits", "baseball"],
                        "weight": 1.0,
                        "notes": "Spring 2026 season"
                    },
                    "school": {
                        "keywords": ["jefferson", "jefferson high", "jhs"],
                        "weight": 0.8
                    }
                },
                "schools": ["Jefferson High School"],
                "teams": ["BTBA Bandits"],
                "notes": "Plays catcher, practices Tue/Thu"
            }
        }


# =============================================================================
# Family Context (Aggregate View)
# =============================================================================

class FamilyMember(BaseModel):
    """
    A family member with their entity ID and profile.
    Used for inference operations.
    """
    entity_id: UUID
    name: str
    profile: FamilyMemberProfile


class FamilyContext(BaseModel):
    """
    The complete Family Entity Graph for a household.

    This is the aggregate view used by the inference engine.
    It's constructed by querying all entities where:
        type = "family_member" AND domain = "family" AND status = "active"
    """
    members: List[FamilyMember] = Field(
        default_factory=list,
        description="All family members in the household"
    )

    # Household-level settings
    primary_timezone: str = Field(
        default="America/Chicago",
        description="Household timezone for calendar operations"
    )
    inference_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score to auto-assign (below = ask user)"
    )

    def get_member_by_name(self, name: str) -> Optional[FamilyMember]:
        """Find a family member by name (case-insensitive)."""
        name_lower = name.lower()
        for member in self.members:
            if member.name.lower() == name_lower:
                return member
        return None

    def infer_owner(self, text: str) -> tuple[Optional[FamilyMember], float, List[dict]]:
        """
        Infer which family member owns a calendar based on text content.

        Args:
            text: Combined text from calendar metadata (name, events, locations)

        Returns:
            (matched_member or None, confidence_score, evidence_list)
        """
        scores: Dict[str, tuple[float, List[dict]]] = {}

        for member in self.members:
            matches = member.profile.calendar_keywords.find_matches(text)
            if matches:
                total_score = sum(m[2] for m in matches)
                evidence = [
                    {"category": m[0], "keyword": m[1], "weight": m[2]}
                    for m in matches
                ]
                scores[member.name] = (total_score, evidence)

        if not scores:
            return None, 0.0, []

        # Find best match
        best_name = max(scores, key=lambda k: scores[k][0])
        best_score, evidence = scores[best_name]

        # Normalize to 0-1 range (assuming max reasonable score ~3.0)
        confidence = min(best_score / 3.0, 1.0)

        best_member = self.get_member_by_name(best_name)
        return best_member, confidence, evidence


# =============================================================================
# Seed Data Helper
# =============================================================================

def create_family_member_entity_dict(
    name: str,
    profile: FamilyMemberProfile
) -> Dict[str, Any]:
    """
    Create an entity dictionary ready for Supabase insertion.

    Usage:
        entity_dict = create_family_member_entity_dict("Jack", jack_profile)
        supabase.table("entities").insert(entity_dict).execute()
    """
    return {
        "name": name,
        "type": "family_member",
        "domain": "family",
        "attributes": profile.model_dump(mode='json'),
        "status": "active"
    }
