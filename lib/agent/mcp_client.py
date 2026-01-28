"""
MCP Client - Model Context Protocol Integration (Stdio-based)

This module handles connections to MCP servers via Stdio transport (stdin/stdout pipes).
It converts MCP tools into LangChain-compatible StructuredTool objects.

The Personal Super Agent uses this to integrate external services like Google Workspace
(Gmail, Calendar, Drive, Docs, Sheets) through standardized MCP servers.

Transport: Stdio (direct process communication via stdin/stdout)
MCP Spec: 2024-11-05+
"""

import asyncio
import logging
import json
import os
import subprocess
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession, Tool
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)

# Default Google email for MCP tools - can be overridden via environment variable
DEFAULT_USER_GOOGLE_EMAIL = os.environ.get('USER_GOOGLE_EMAIL', 'rknollmaier@gmail.com')


class MCPConnectionConfig(BaseModel):
    """Configuration for an MCP server connection."""
    name: str
    command: str  # The MCP server command (e.g., "/app/deploy/start-mcp-server.sh")
    args: List[str] = Field(default_factory=list)  # Command arguments
    env: Dict[str, str] = Field(default_factory=dict)  # Environment variables


async def get_mcp_tools(
    command: str = "/app/deploy/start-mcp-server.sh",
    args: List[str] = None,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> List[StructuredTool]:
    """
    Connect to an MCP server via Stdio and fetch available tools.

    This function:
    1. Spawns an MCP server process (stdio-based)
    2. Initializes the connection
    3. Lists all available tools
    4. Converts them to LangChain StructuredTool objects
    5. Cleans up the connection

    Args:
        command: The MCP server command (e.g., "workspace-mcp")
        args: List of arguments to pass to the MCP server (default: ["--transport", "stdio"])
        timeout: Timeout for operations in seconds (default: 30)
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Seconds to wait between retries (default: 1.0)

    Returns:
        List of LangChain StructuredTool objects (empty list if connection fails)

    Example:
        >>> tools = await get_mcp_tools("/app/deploy/start-mcp-server.sh")
        >>> print(f"Loaded {len(tools)} tools from MCP server")
    """
    if args is None:
        args = ["--transport", "stdio"]

    tools: List[StructuredTool] = []

    logger.info(f"Connecting to MCP server: {command} {' '.join(args)}")

    for attempt in range(1, max_retries + 1):
        try:
            # Create Stdio parameters for the MCP server
            stdio_params = StdioServerParameters(
                command=command,
                args=args
            )

            # Create a client transport and session
            async with stdio_client(stdio_params) as transport:
                async with ClientSession(transport) as session:
                    try:
                        # Initialize the session
                        await session.initialize()
                        logger.debug(f"MCP session initialized")

                        # List all available tools
                        tools_response = await session.list_tools()
                        logger.debug(f"Retrieved {len(tools_response.tools)} tools from MCP server")

                        # Convert MCP Tool objects to LangChain StructuredTools
                        for mcp_tool in tools_response.tools:
                            try:
                                langchain_tool = _convert_mcp_to_langchain_tool(mcp_tool, session)
                                tools.append(langchain_tool)
                            except Exception as e:
                                logger.warning(f"Failed to convert tool {mcp_tool.name}: {e}")
                                continue

                        logger.info(f"✓ Successfully loaded {len(tools)} tools from {command}")
                        return tools  # Success - exit retry loop

                    except Exception as e:
                        logger.warning(f"Error during MCP session: {e} (attempt {attempt}/{max_retries})")
                        if attempt < max_retries:
                            await asyncio.sleep(retry_delay)
                            continue
                        raise

        except Exception as e:
            logger.warning(f"Failed to connect to MCP server {command}: {e} (attempt {attempt}/{max_retries})")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
                continue

    logger.error(f"Failed to connect to MCP server {command} after {max_retries} attempts")
    return tools


def _convert_mcp_to_langchain_tool(
    mcp_tool: Tool,
    session: ClientSession
) -> StructuredTool:
    """
    Convert an MCP Tool object to a LangChain StructuredTool.

    Args:
        mcp_tool: The MCP Tool object (from list_tools response)
        session: The active MCP ClientSession for making tool calls

    Returns:
        A LangChain StructuredTool that wraps the MCP tool
    """

    # Create an async function that will be called when the tool is invoked
    async def tool_func(**kwargs) -> str:
        """Execute the MCP tool via the Stdio session."""
        try:
            # Auto-inject user_google_email for Google Workspace tools
            if mcp_tool.name.startswith((
                'search_gmail', 'get_gmail', 'send_gmail', 'draft_gmail',
                'list_gmail', 'manage_gmail', 'create_gmail', 'delete_gmail',
                'modify_gmail', 'batch_modify_gmail',
                'list_calendars', 'get_events', 'create_event', 'modify_event', 'delete_event',
                'search_drive', 'get_drive', 'list_drive', 'create_drive', 'update_drive', 'check_drive',
                'list_documents', 'get_document', 'create_document', 'update_document', 'export_doc',
                'read_document', 'create_table', 'debug_table',
                'list_spreadsheets', 'get_spreadsheet', 'create_spreadsheet', 'create_sheet',
                'read_sheet', 'modify_sheet', 'format_sheet', 'add_conditional', 'update_conditional', 'delete_conditional',
                'read_spreadsheet_comment', 'create_spreadsheet_comment', 'reply_to_spreadsheet', 'resolve_spreadsheet'
            )):
                if 'user_google_email' not in kwargs:
                    kwargs['user_google_email'] = DEFAULT_USER_GOOGLE_EMAIL

            # Call the MCP tool
            response = await session.call_tool(mcp_tool.name, kwargs)

            # Process the response
            if response.content:
                # Extract text from response content
                text_contents = [c.text for c in response.content if hasattr(c, 'text')]
                if text_contents:
                    return '\n'.join(text_contents)
                # Fallback to string representation
                return str(response.content)

            return "Tool executed successfully but returned no content"

        except Exception as e:
            logger.error(f"Error executing MCP tool {mcp_tool.name}: {e}")
            return f"Error executing tool: {str(e)}"

    return StructuredTool.from_function(
        name=mcp_tool.name,
        description=mcp_tool.description,
        func=tool_func,
        coroutine=tool_func  # Support async execution
    )


async def test_mcp_connection(
    command: str = "/app/deploy/start-mcp-server.sh",
    args: List[str] = None,
    timeout: int = 10
) -> bool:
    """
    Test if an MCP server is reachable and responsive.

    Args:
        command: The MCP server command
        args: Arguments for the MCP server
        timeout: Connection timeout in seconds

    Returns:
        True if the server is reachable, False otherwise
    """
    if args is None:
        args = ["--transport", "stdio"]

    try:
        stdio_params = StdioServerParameters(command=command, args=args)
        async with stdio_client(stdio_params) as transport:
            async with ClientSession(transport) as session:
                await session.initialize()
                logger.info(f"✓ MCP server {command} is reachable")
                return True
    except Exception as e:
        logger.warning(f"MCP server {command} connection test failed: {e}")
        return False


def get_mcp_tools_sync(
    command: str = "/app/deploy/start-mcp-server.sh",
    args: List[str] = None,
    timeout: int = 30
) -> List[StructuredTool]:
    """
    Synchronous wrapper for get_mcp_tools.

    Args:
        command: The MCP server command
        args: Arguments for the MCP server
        timeout: Timeout in seconds

    Returns:
        List of LangChain StructuredTool objects
    """
    if args is None:
        args = ["--transport", "stdio"]

    return asyncio.run(get_mcp_tools(command, args, timeout))
