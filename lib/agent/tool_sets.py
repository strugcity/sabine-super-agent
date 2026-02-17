"""
Tool Set Definitions for Sabine Super Agent

This module defines which tools are available to which agent roles:
- SABINE: Personal assistant tools (calendar, reminders, weather, custody)
- DREAM_TEAM: Coding/project management tools (GitHub, sandbox, Slack)

Part of Phase 2: Separate Agent Cores refactoring.

NOTE: This is a different tool-scoping mechanism from RoleManifest.allowed_tools.
- tool_sets.py: Hard-coded, agent-type-level scoping (assistant vs. coder)
- RoleManifest.allowed_tools: Per-role tool filtering with wildcard support

The relationship:
1. Agent type (assistant/coder) determines base tool set via tool_sets.py
2. RoleManifest.allowed_tools can further restrict tools for specific roles
3. If RoleManifest.allowed_tools is empty, all tools from the agent type are allowed

This layered approach allows coarse-grained agent separation (Phase 2) while
preserving fine-grained per-role control (existing RoleManifest system).
"""

from typing import Set, Literal

# Public API
__all__ = [
    "AgentRole",
    "SABINE_TOOLS",
    "DREAM_TEAM_TOOLS",
    "get_tool_names",
    "is_tool_allowed",
]

# =============================================================================
# Type Definitions
# =============================================================================

AgentRole = Literal["assistant", "coder"]


# =============================================================================
# Tool Set Definitions
# =============================================================================

# Personal assistant tools for Sabine
SABINE_TOOLS: Set[str] = {
    "get_calendar_events",
    "create_calendar_event",
    "get_custody_schedule",
    "get_weather",
    "create_reminder",
    "cancel_reminder",
    "list_reminders",
    "search_gmail_messages",
    "get_gmail_message_content",
    "send_gmail_message",
}

# Coding and project management tools for Dream Team
DREAM_TEAM_TOOLS: Set[str] = {
    "github_issues",
    "run_python_sandbox",
    "sync_project_board",
    "send_team_update",
}

# Validate that tool sets don't overlap
assert SABINE_TOOLS.isdisjoint(DREAM_TEAM_TOOLS), \
    f"Tool sets must not overlap. Found in both: {SABINE_TOOLS.intersection(DREAM_TEAM_TOOLS)}"


# =============================================================================
# Helper Functions
# =============================================================================

def get_tool_names(role: AgentRole) -> Set[str]:
    """
    Get the set of tool names for a specific agent role.

    Args:
        role: The agent role ("assistant" for Sabine, "coder" for Dream Team)

    Returns:
        Set of tool names available to that role

    Raises:
        ValueError: If an invalid role is provided

    Example:
        >>> tools = get_tool_names("assistant")
        >>> print(tools)
        {'get_calendar_events', 'create_calendar_event', ...}
    """
    if role == "assistant":
        return SABINE_TOOLS
    elif role == "coder":
        return DREAM_TEAM_TOOLS
    else:
        raise ValueError(f"Invalid role: {role}. Must be 'assistant' or 'coder'")


def is_tool_allowed(tool_name: str, role: AgentRole) -> bool:
    """
    Check if a tool is allowed for a specific agent role.

    Args:
        tool_name: The name of the tool to check
        role: The agent role to check against

    Returns:
        True if the tool is allowed for the role, False otherwise

    Example:
        >>> is_tool_allowed("get_calendar_events", "assistant")
        True
        >>> is_tool_allowed("github_issues", "assistant")
        False
    """
    allowed_tools = get_tool_names(role)
    return tool_name in allowed_tools
