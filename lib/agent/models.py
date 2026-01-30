"""
Agent Models - Pydantic schemas for agent configuration and orchestration.

This module defines data models for:
- RoleManifest: Role-based agent persona configuration
- Future: Task queue entries, orchestration state, etc.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class RoleManifest(BaseModel):
    """
    Schema for role-based agent personas loaded from docs/roles/*.md files.

    Each role defines a specialized agent identity with specific skills,
    responsibilities, and tool access. The SABINE_ARCHITECT orchestrates
    work across these specialized roles.

    Example role files:
    - SABINE_ARCHITECT.md: Senior Agentic Architect (orchestrator)
    - backend-architect-sabine.md: Lead Python & Systems Engineer
    - data-ai-engineer-sabine.md: AI Systems Engineer
    - frontend-ops-sabine.md: Full-Stack Lead
    - product-manager-sabine.md: Senior Product Manager
    - qa-security-sabine.md: Security & QA Lead
    """

    role_id: str = Field(
        ...,
        description="Unique identifier for the role, derived from filename (e.g., 'backend-architect-sabine')"
    )

    title: str = Field(
        ...,
        description="Human-readable role title (e.g., 'Lead Python & Systems Engineer')"
    )

    instructions: str = Field(
        ...,
        description="Full markdown content of the role file, injected into system prompt"
    )

    allowed_tools: List[str] = Field(
        default_factory=list,
        description="Tool whitelist for this role. Empty list means all tools allowed. "
                    "Supports wildcards: ['mcp_*', 'github_*'] matches all MCP and GitHub tools."
    )

    model_preference: Optional[str] = Field(
        default=None,
        description="Preferred model for this role (e.g., 'claude-sonnet', 'claude-opus'). "
                    "None means use default model."
    )

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "role_id": "backend-architect-sabine",
                "title": "Lead Python & Systems Engineer",
                "instructions": "# SYSTEM ROLE: backend-architect-sabine\n**Identity:** You are the Lead Python...",
                "allowed_tools": ["github_*", "mcp_gmail_*"],
                "model_preference": None
            }
        }
