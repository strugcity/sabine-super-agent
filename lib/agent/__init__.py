"""
Personal Super Agent - Core Agent Module

This module provides the main agent orchestration system with:
- Deep Context Injection (custody schedules, rules, memories)
- Unified Tool Registry (local skills + MCP integrations)
- LangGraph ReAct agent with Anthropic Claude

Usage:
    from lib.agent import create_agent, run_agent

    # Create and run agent
    result = await run_agent(
        user_id="user-uuid",
        session_id="session-123",
        user_message="What's on my custody schedule this week?"
    )

    print(result["response"])
"""

from .core import (
    create_agent,
    run_agent,
    run_agent_sync,
    load_deep_context,
    build_system_prompt
)

from .registry import (
    get_all_tools,
    get_all_tools_sync,
    load_local_skills,
    load_mcp_tools,
    get_mcp_servers,
    add_mcp_server,
    remove_mcp_server
)

from .mcp_client import (
    get_mcp_tools,
    get_mcp_tools_sync,
    test_mcp_connection,
    get_mcp_server_info
)

__all__ = [
    # Core functions
    "create_agent",
    "run_agent",
    "run_agent_sync",
    "load_deep_context",
    "build_system_prompt",

    # Registry functions
    "get_all_tools",
    "get_all_tools_sync",
    "load_local_skills",
    "load_mcp_tools",
    "get_mcp_servers",
    "add_mcp_server",
    "remove_mcp_server",

    # MCP client functions
    "get_mcp_tools",
    "get_mcp_tools_sync",
    "test_mcp_connection",
    "get_mcp_server_info",
]
