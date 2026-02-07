"""
Unified Tool Registry - Local Skills + MCP Integrations

This module implements the "Skill Registry" pattern for the Personal Super Agent.
It dynamically loads tools from two sources:

1. LOCAL SKILLS: Python modules in /lib/skills with handler.py and manifest.json
2. MCP SERVERS: Remote integrations via Model Context Protocol

The registry provides a unified interface (get_all_tools()) that merges both sources,
allowing the agent to seamlessly use internal skills and external integrations.
"""

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .mcp_client import get_mcp_tools

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Base path for local skills
SKILLS_DIR = Path(__file__).parent.parent / "skills"

# MCP Server configurations (loaded from environment variables)
# Format: "workspace-mcp" or "workspace-mcp:arg1:arg2" (colon-separated)
# Example: MCP_SERVERS="workspace-mcp workspace-calendar:--config=/path/to/config"
MCP_SERVERS = []

mcp_server_specs = os.getenv("MCP_SERVERS", "").strip()
if mcp_server_specs:
    for spec in mcp_server_specs.split(" "):
        spec = spec.strip()
        if spec:
            # Parse "command:arg1:arg2" format
            parts = spec.split(":")
            MCP_SERVERS.append({
                "command": parts[0],
                "args": parts[1:] if len(parts) > 1 else ["--transport", "stdio"]
            })

logger.info(f"Configured MCP servers: {[s['command'] for s in MCP_SERVERS]}")


# =============================================================================
# Local Skill Models
# =============================================================================

class SkillManifest(BaseModel):
    """Manifest schema for local Python skills."""
    name: str
    description: str
    version: str = "1.0.0"
    parameters: Dict[str, Any] = Field(default_factory=dict)


class LoadedSkill(BaseModel):
    """Represents a loaded local skill."""
    name: str
    description: str
    handler: Callable
    manifest: SkillManifest


# =============================================================================
# Local Skill Loading
# =============================================================================

def load_local_skills() -> List[LoadedSkill]:
    """
    Scan /lib/skills directory and load all valid skills.

    A valid skill must have:
    - A manifest.json file
    - A handler.py file with an execute() function

    Returns:
        List of LoadedSkill objects
    """
    skills: List[LoadedSkill] = []

    if not SKILLS_DIR.exists():
        logger.warning(f"Skills directory not found: {SKILLS_DIR}")
        return skills

    # Scan all subdirectories in /lib/skills
    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
            continue

        manifest_path = skill_dir / "manifest.json"
        handler_path = skill_dir / "handler.py"

        # Check if both required files exist
        if not manifest_path.exists() or not handler_path.exists():
            logger.debug(f"Skipping {skill_dir.name}: missing manifest.json or handler.py")
            continue

        try:
            # Load manifest
            with open(manifest_path, "r") as f:
                manifest_data = json.load(f)
                manifest = SkillManifest(**manifest_data)

            # Load handler module
            spec = importlib.util.spec_from_file_location(
                f"skills.{skill_dir.name}.handler",
                handler_path
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Get the execute function
                if hasattr(module, "execute"):
                    skill = LoadedSkill(
                        name=manifest.name,
                        description=manifest.description,
                        handler=module.execute,
                        manifest=manifest
                    )
                    skills.append(skill)
                    logger.info(f"✓ Loaded local skill: {manifest.name}")
                else:
                    logger.warning(f"Skill {skill_dir.name} has no execute() function")

        except Exception as e:
            logger.error(f"Failed to load skill {skill_dir.name}: {e}")

    return skills


def create_args_schema_from_manifest(skill: LoadedSkill) -> Optional[type]:
    """
    Dynamically create a Pydantic model from the skill manifest's parameters schema.

    This allows LangChain to understand what parameters the tool accepts.
    """
    from pydantic import create_model
    from typing import Optional as OptionalType, List as ListType

    params = skill.manifest.parameters
    if not params or "properties" not in params:
        return None

    properties = params.get("properties", {})
    required = params.get("required", [])

    # Map JSON schema types to Python types
    type_mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    field_definitions = {}
    for field_name, field_schema in properties.items():
        field_type = type_mapping.get(field_schema.get("type", "string"), str)
        description = field_schema.get("description", "")

        # Handle arrays with items
        if field_schema.get("type") == "array" and "items" in field_schema:
            item_type = type_mapping.get(field_schema["items"].get("type", "string"), str)
            field_type = ListType[item_type]

        # Make optional if not in required list
        if field_name not in required:
            field_type = OptionalType[field_type]
            field_definitions[field_name] = (field_type, Field(default=None, description=description))
        else:
            field_definitions[field_name] = (field_type, Field(..., description=description))

    # Create the model dynamically
    model_name = f"{skill.name.title().replace('_', '')}Args"
    return create_model(model_name, **field_definitions)


def convert_local_skill_to_tool(skill: LoadedSkill) -> StructuredTool:
    """
    Convert a local Python skill to a LangChain StructuredTool.

    Args:
        skill: The loaded skill

    Returns:
        A LangChain StructuredTool
    """

    # Wrap the handler to handle both sync and async
    async def async_wrapper(**kwargs) -> str:
        """Async wrapper for skill handler."""
        try:
            logger.info(f"Executing skill {skill.name} with args: {kwargs}")
            result = skill.handler(kwargs)

            # Handle async handlers
            if asyncio.iscoroutine(result):
                result = await result

            logger.info(f"Skill {skill.name} returned: {type(result)} - status={result.get('status') if isinstance(result, dict) else 'N/A'}")

            # Convert result to string
            if isinstance(result, dict):
                # For sandbox/code execution results, include the output
                if "output" in result and result.get("status") == "success":
                    return f"SUCCESS: {result.get('message', 'Code executed')}\n\nOutput:\n{result['output']}"
                # For error results, include full details
                if result.get("status") == "error":
                    error_msg = result.get("error", result.get("message", "Unknown error"))
                    logger.warning(f"Skill {skill.name} returned error: {error_msg}")
                    return f"ERROR: {error_msg}"
                # For other results with status/message, show full JSON to preserve data
                return json.dumps(result, indent=2)

            return str(result)

        except Exception as e:
            logger.error(f"Error executing skill {skill.name}: {e}", exc_info=True)
            return f"Error: {str(e)}"

    # Create args_schema from manifest for proper LangChain integration
    args_schema = create_args_schema_from_manifest(skill)

    return StructuredTool.from_function(
        name=skill.name,
        description=skill.description,
        func=async_wrapper,
        coroutine=async_wrapper,
        args_schema=args_schema
    )


# =============================================================================
# MCP Tool Loading
# =============================================================================

async def load_mcp_tools() -> List[StructuredTool]:
    """
    Load tools from all configured MCP servers.

    Returns:
        List of LangChain StructuredTool objects from MCP servers
    """
    all_mcp_tools: List[StructuredTool] = []

    if not MCP_SERVERS:
        logger.info("No MCP servers configured")
        return all_mcp_tools

    # Load tools from each MCP server concurrently
    tasks = [
        get_mcp_tools(
            command=server["command"],
            args=server.get("args", ["--transport", "stdio"])
        )
        for server in MCP_SERVERS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        server_name = MCP_SERVERS[i]["command"]
        if isinstance(result, Exception):
            logger.error(f"Failed to load tools from {server_name}: {result}")
        elif isinstance(result, list):
            all_mcp_tools.extend(result)
            logger.info(f"✓ Loaded {len(result)} tools from {server_name}")

    return all_mcp_tools


async def get_mcp_diagnostics() -> Dict[str, Any]:
    """
    Get detailed diagnostics about MCP server loading.

    Returns:
        Dict with MCP server status, errors, and tool counts
    """
    diagnostics = {
        "configured_servers": [s["command"] for s in MCP_SERVERS],
        "server_count": len(MCP_SERVERS),
        "servers": []
    }

    if not MCP_SERVERS:
        diagnostics["message"] = "No MCP servers configured"
        return diagnostics

    # Test each server individually
    for server in MCP_SERVERS:
        server_info = {
            "command": server["command"],
            "args": server.get("args", ["--transport", "stdio"]),
            "status": "unknown",
            "tools": [],
            "error": None
        }

        try:
            tools = await get_mcp_tools(
                command=server["command"],
                args=server.get("args", ["--transport", "stdio"]),
                timeout=15
            )
            server_info["status"] = "success"
            server_info["tool_count"] = len(tools)
            server_info["tools"] = [t.name for t in tools]
        except Exception as e:
            server_info["status"] = "failed"
            server_info["error"] = str(e)
            import traceback
            server_info["traceback"] = traceback.format_exc()

        diagnostics["servers"].append(server_info)

    return diagnostics


# =============================================================================
# Unified Tool Registry
# =============================================================================

async def get_all_tools() -> List[StructuredTool]:
    """
    Get all available tools from both local skills and MCP servers.

    This is the main entry point for the agent. It merges:
    - Local Python skills from /lib/skills
    - Remote tools from MCP servers

    Returns:
        Unified list of LangChain StructuredTool objects

    Example:
        >>> tools = await get_all_tools()
        >>> print(f"Loaded {len(tools)} tools total")
        >>> for tool in tools:
        >>>     print(f"  - {tool.name}: {tool.description}")
    """
    all_tools: List[StructuredTool] = []

    # Load local skills
    logger.info("Loading local skills...")
    local_skills = load_local_skills()
    for skill in local_skills:
        tool = convert_local_skill_to_tool(skill)
        all_tools.append(tool)

    logger.info(f"Loaded {len(local_skills)} local skills")

    # Load MCP tools
    logger.info("Loading MCP tools...")
    mcp_tools = await load_mcp_tools()
    all_tools.extend(mcp_tools)

    logger.info(f"Loaded {len(mcp_tools)} MCP tools")

    # Log summary
    logger.info(f"=" * 60)
    logger.info(f"TOTAL TOOLS LOADED: {len(all_tools)}")
    logger.info(f"  - Local Skills: {len(local_skills)}")
    logger.info(f"  - MCP Tools: {len(mcp_tools)}")
    logger.info(f"=" * 60)

    if all_tools:
        logger.info("Available tools:")
        for tool in all_tools:
            logger.info(f"  ✓ {tool.name}: {tool.description[:60]}...")

    return all_tools


def get_all_tools_sync() -> List[StructuredTool]:
    """
    Synchronous wrapper for get_all_tools().

    Returns:
        Unified list of LangChain StructuredTool objects
    """
    return asyncio.run(get_all_tools())


async def get_scoped_tools(role: str) -> List[StructuredTool]:
    """
    Get tools scoped to a specific agent role.

    This function loads all tools and filters them based on the role's
    allowed tool set as defined in tool_sets.py.

    Args:
        role: Agent role ("assistant" for Sabine, "coder" for Dream Team)

    Returns:
        List of StructuredTool objects allowed for the role

    Raises:
        ValueError: If an invalid role is provided

    Example:
        >>> tools = await get_scoped_tools("assistant")
        >>> print(f"Sabine has {len(tools)} tools")
    """
    from .tool_sets import get_tool_names

    # Get all available tools
    all_tools = await get_all_tools()

    # Get allowed tool names for this role
    allowed_names = get_tool_names(role)  # type: ignore

    # Filter tools to only those allowed for this role
    scoped_tools = [tool for tool in all_tools if tool.name in allowed_names]

    logger.info(f"Scoped {len(scoped_tools)} tools for role '{role}' (from {len(all_tools)} total)")

    return scoped_tools


# =============================================================================
# Registry Management
# =============================================================================

def get_tool_by_name(tool_name: str, tools: List[StructuredTool]) -> Optional[StructuredTool]:
    """
    Find a tool by name.

    Args:
        tool_name: The name of the tool to find
        tools: List of available tools

    Returns:
        The tool if found, None otherwise
    """
    for tool in tools:
        if tool.name == tool_name:
            return tool
    return None


def list_available_tools(tools: List[StructuredTool]) -> Dict[str, str]:
    """
    Get a dictionary of tool names and descriptions.

    Args:
        tools: List of available tools

    Returns:
        Dict mapping tool names to descriptions
    """
    return {tool.name: tool.description for tool in tools}


# =============================================================================
# Configuration Helpers
# =============================================================================

def add_mcp_server(url: str) -> None:
    """
    Add an MCP server URL to the configuration.

    Note: This only affects the current runtime. To persist,
    add to the MCP_SERVERS environment variable.

    Args:
        url: The MCP server URL to add
    """
    if url not in MCP_SERVERS:
        MCP_SERVERS.append(url)
        logger.info(f"Added MCP server: {url}")


def remove_mcp_server(url: str) -> None:
    """
    Remove an MCP server URL from the configuration.

    Args:
        url: The MCP server URL to remove
    """
    if url in MCP_SERVERS:
        MCP_SERVERS.remove(url)
        logger.info(f"Removed MCP server: {url}")


def get_mcp_servers() -> List[str]:
    """
    Get the list of configured MCP servers.

    Returns:
        List of MCP server URLs
    """
    return MCP_SERVERS.copy()
