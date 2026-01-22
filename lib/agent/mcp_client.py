"""
MCP Client - Model Context Protocol Integration

This module handles connections to remote MCP servers via SSE (Server-Sent Events)
and converts MCP tools into LangChain-compatible StructuredTool objects.

The Personal Super Agent uses this to integrate external services like Google Drive,
Slack, Calendar, etc. through standardized MCP servers.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
import httpx
from httpx_sse import aconnect_sse
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


class MCPToolSchema(BaseModel):
    """Schema for MCP tool parameters."""
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class MCPTool(BaseModel):
    """Represents a tool from an MCP server."""
    name: str
    description: str
    inputSchema: MCPToolSchema


class MCPServerInfo(BaseModel):
    """Information about an MCP server."""
    name: str
    version: str
    protocolVersion: str = "1.0"


async def get_mcp_tools(url: str, timeout: int = 10) -> List[StructuredTool]:
    """
    Connect to a remote MCP server via SSE and fetch available tools.

    This function:
    1. Connects to the MCP server using SSE
    2. Sends a 'list_tools' request
    3. Receives the tool definitions
    4. Converts them to LangChain StructuredTool objects

    Args:
        url: The MCP server URL (e.g., 'https://mcp.example.com/sse')
        timeout: Connection timeout in seconds (default: 10)

    Returns:
        List of LangChain StructuredTool objects (empty list if connection fails)

    Example:
        >>> tools = await get_mcp_tools('https://gdrive-mcp.example.com/sse')
        >>> print(f"Loaded {len(tools)} tools from MCP server")
    """
    tools: List[StructuredTool] = []

    try:
        logger.info(f"Connecting to MCP server: {url}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            # Connect to the SSE endpoint
            try:
                async with aconnect_sse(client, "GET", url) as event_source:
                    # Send initialization request
                    init_request = {
                        "jsonrpc": "2.0",
                        "id": "init",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "1.0",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "personal-super-agent",
                                "version": "1.0.0"
                            }
                        }
                    }

                    # In a real SSE MCP implementation, you'd POST requests
                    # and listen for responses via SSE. This is a simplified version.
                    # For now, we'll make a separate request to list tools.

                    # Request tool list
                    tools_response = await client.post(
                        url.replace('/sse', '/rpc'),  # Adjust endpoint as needed
                        json={
                            "jsonrpc": "2.0",
                            "id": "list_tools",
                            "method": "tools/list",
                            "params": {}
                        }
                    )

                    if tools_response.status_code == 200:
                        data = tools_response.json()

                        if "result" in data and "tools" in data["result"]:
                            mcp_tools = [MCPTool(**tool) for tool in data["result"]["tools"]]

                            # Convert MCP tools to LangChain StructuredTools
                            for mcp_tool in mcp_tools:
                                langchain_tool = _convert_mcp_to_langchain_tool(mcp_tool, url, client)
                                tools.append(langchain_tool)

                            logger.info(f"Successfully loaded {len(tools)} tools from {url}")
                        else:
                            logger.warning(f"No tools found in MCP server response: {url}")
                    else:
                        logger.warning(f"Failed to fetch tools from {url}: {tools_response.status_code}")

            except httpx.ConnectError as e:
                logger.warning(f"Connection error to MCP server {url}: {e}")
            except httpx.TimeoutException as e:
                logger.warning(f"Timeout connecting to MCP server {url}: {e}")

    except Exception as e:
        logger.error(f"Unexpected error fetching MCP tools from {url}: {e}")

    return tools


def _convert_mcp_to_langchain_tool(
    mcp_tool: MCPTool,
    server_url: str,
    client: httpx.AsyncClient
) -> StructuredTool:
    """
    Convert an MCP tool definition to a LangChain StructuredTool.

    Args:
        mcp_tool: The MCP tool definition
        server_url: The MCP server URL (for making tool calls)
        client: The HTTP client to use for requests

    Returns:
        A LangChain StructuredTool that wraps the MCP tool
    """

    # Create an async function that will be called when the tool is invoked
    async def tool_func(**kwargs) -> str:
        """Execute the MCP tool via RPC call."""
        try:
            response = await client.post(
                server_url.replace('/sse', '/rpc'),
                json={
                    "jsonrpc": "2.0",
                    "id": f"call_{mcp_tool.name}",
                    "method": "tools/call",
                    "params": {
                        "name": mcp_tool.name,
                        "arguments": kwargs
                    }
                },
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    # MCP tools return structured results
                    result = data["result"]
                    if isinstance(result, dict) and "content" in result:
                        # Extract text content from MCP response
                        content = result["content"]
                        if isinstance(content, list) and len(content) > 0:
                            return content[0].get("text", str(result))
                        return str(content)
                    return str(result)
                elif "error" in data:
                    return f"Error: {data['error'].get('message', 'Unknown error')}"

            return f"Failed to execute tool: HTTP {response.status_code}"

        except Exception as e:
            logger.error(f"Error executing MCP tool {mcp_tool.name}: {e}")
            return f"Error executing tool: {str(e)}"

    # Convert MCP schema to LangChain-compatible args_schema
    # For now, we'll use a simple approach - in production you'd want
    # to dynamically create a Pydantic model from the inputSchema

    return StructuredTool.from_function(
        name=mcp_tool.name,
        description=mcp_tool.description,
        func=tool_func,
        coroutine=tool_func  # Support async execution
    )


async def test_mcp_connection(url: str) -> bool:
    """
    Test if an MCP server is reachable and responsive.

    Args:
        url: The MCP server URL

    Returns:
        True if the server is reachable, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url.replace('/sse', '/health'))
            return response.status_code == 200
    except Exception as e:
        logger.debug(f"MCP server {url} health check failed: {e}")
        return False


async def get_mcp_server_info(url: str) -> Optional[MCPServerInfo]:
    """
    Get information about an MCP server.

    Args:
        url: The MCP server URL

    Returns:
        MCPServerInfo object if successful, None otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                url.replace('/sse', '/rpc'),
                json={
                    "jsonrpc": "2.0",
                    "id": "info",
                    "method": "info",
                    "params": {}
                }
            )

            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    return MCPServerInfo(**data["result"])
    except Exception as e:
        logger.debug(f"Failed to get MCP server info from {url}: {e}")

    return None


# Convenience function for synchronous contexts
def get_mcp_tools_sync(url: str, timeout: int = 10) -> List[StructuredTool]:
    """
    Synchronous wrapper for get_mcp_tools.

    Args:
        url: The MCP server URL
        timeout: Connection timeout in seconds

    Returns:
        List of LangChain StructuredTool objects
    """
    return asyncio.run(get_mcp_tools(url, timeout))
