"""
MCP Client - Model Context Protocol Integration (Stdio-based)

This module handles connections to MCP servers via Stdio transport (stdin/stdout pipes).
It provides an async context manager (MCPClient) that maintains the session for tool calls.

The Personal Super Agent uses this to integrate external services like Google Workspace
(Gmail, Calendar, Drive, Docs, Sheets) through standardized MCP servers.

Transport: Stdio (direct process communication via stdin/stdout)
MCP Spec: 2024-11-05+
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Async context manager for MCP server connections.

    Maintains the session open for the duration of the context, allowing
    multiple tool calls without reconnecting.

    Usage:
        async with MCPClient() as client:
            result = await client.call_tool("gmail.search", {"query": "in:inbox"})
            # Session stays open for additional calls
            content = await client.call_tool("gmail.get", {"messageId": "123"})
    """

    def __init__(
        self,
        command: str = "/app/deploy/start-mcp-server.sh",
        args: List[str] = None
    ):
        """
        Initialize MCP client configuration.

        Args:
            command: The MCP server command (e.g., "/app/deploy/start-mcp-server.sh" or "npx")
            args: Arguments for the command (default: ["--transport", "stdio"])
        """
        self.command = command
        self.args = args or ["--transport", "stdio"]
        self._session: Optional[ClientSession] = None
        self._transport_cm = None
        self._session_cm = None
        self._tools: Dict[str, Any] = {}

    async def __aenter__(self) -> "MCPClient":
        """Enter the async context and establish MCP connection."""
        logger.info(f"Connecting to MCP server: {self.command} {' '.join(self.args)}")

        stdio_params = StdioServerParameters(
            command=self.command,
            args=self.args
        )

        # Enter the transport context
        self._transport_cm = stdio_client(stdio_params)
        read_stream, write_stream = await self._transport_cm.__aenter__()

        # Enter the session context
        self._session_cm = ClientSession(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()

        # Initialize the session
        await self._session.initialize()
        logger.debug("MCP session initialized")

        # Cache available tools
        tools_response = await self._session.list_tools()
        for tool in tools_response.tools:
            self._tools[tool.name] = tool
        logger.info(f"✓ Connected to MCP server with {len(self._tools)} tools available")

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context and close the MCP connection."""
        # Close session first
        if self._session_cm:
            try:
                await self._session_cm.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.warning(f"Error closing MCP session: {e}")

        # Then close transport
        if self._transport_cm:
            try:
                await self._transport_cm.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.warning(f"Error closing MCP transport: {e}")

        self._session = None
        self._tools = {}
        logger.debug("MCP connection closed")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """
        Call an MCP tool by name.

        Args:
            tool_name: Name of the tool (e.g., "gmail.search", "gmail.send")
            arguments: Dict of arguments for the tool

        Returns:
            String result from the tool (typically JSON or text)

        Raises:
            RuntimeError: If called outside of async context
            ValueError: If tool is not found
        """
        if self._session is None:
            raise RuntimeError("MCPClient must be used as an async context manager")

        if tool_name not in self._tools:
            available = list(self._tools.keys())
            raise ValueError(f"Tool '{tool_name}' not found. Available: {available[:10]}...")

        arguments = arguments or {}

        try:
            response = await self._session.call_tool(tool_name, arguments)

            if response.content:
                text_contents = [c.text for c in response.content if hasattr(c, 'text')]
                if text_contents:
                    return '\n'.join(text_contents)
                return str(response.content)

            return "Tool executed successfully but returned no content"

        except Exception as e:
            logger.error(f"Error executing MCP tool {tool_name}: {e}")
            raise

    def list_tools(self) -> List[str]:
        """Return list of available tool names."""
        return list(self._tools.keys())

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get info about a specific tool."""
        tool = self._tools.get(tool_name)
        if tool:
            return {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema
            }
        return None


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
    try:
        async with MCPClient(command=command, args=args) as client:
            tools = client.list_tools()
            logger.info(f"✓ MCP server {command} is reachable with {len(tools)} tools")
            return True
    except Exception as e:
        logger.warning(f"MCP server {command} connection test failed: {e}")
        return False


async def get_mcp_tools(
    command: str = "/app/deploy/start-mcp-server.sh",
    args: List[str] = None,
    timeout: int = 30,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> List:
    """
    Get LangChain-compatible tools from an MCP server.

    NOTE: These tools create a new MCP session for each invocation, which has
    overhead. For multiple tool calls, prefer using MCPClient context manager.

    Args:
        command: The MCP server command
        args: Arguments for the MCP server
        timeout: Timeout in seconds
        max_retries: Number of retry attempts
        retry_delay: Delay between retries

    Returns:
        List of LangChain StructuredTool objects
    """
    from langchain_core.tools import StructuredTool

    tools = []

    try:
        async with MCPClient(command=command, args=args) as client:
            for tool_name in client.list_tools():
                tool_info = client.get_tool_info(tool_name)
                if tool_info:
                    # Create a tool that opens its own session
                    def make_tool_func(name: str, cmd: str, tool_args: List[str]):
                        async def tool_func(**kwargs) -> str:
                            try:
                                async with MCPClient(command=cmd, args=tool_args) as c:
                                    return await c.call_tool(name, kwargs)
                            except Exception as e:
                                logger.error(f"Error executing MCP tool {name}: {e}")
                                return f"Error: {str(e)}"
                        return tool_func

                    func = make_tool_func(tool_name, command, args or ["--transport", "stdio"])

                    tool = StructuredTool.from_function(
                        name=tool_name,
                        description=tool_info.get("description", ""),
                        func=func,
                        coroutine=func
                    )
                    tools.append(tool)

            logger.info(f"✓ Created {len(tools)} LangChain tools from {command}")

    except Exception as e:
        logger.error(f"Failed to get MCP tools from {command}: {e}")

    return tools


def get_mcp_tools_sync(
    command: str = "/app/deploy/start-mcp-server.sh",
    args: List[str] = None,
    timeout: int = 30
) -> List:
    """
    Synchronous wrapper for get_mcp_tools.
    """
    import asyncio
    return asyncio.run(get_mcp_tools(command, args, timeout))
