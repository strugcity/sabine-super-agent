"""
MCP Client - Model Context Protocol Integration

This module handles connections to remote MCP servers via streamable-http protocol
and converts MCP tools into LangChain-compatible StructuredTool objects.

The Personal Super Agent uses this to integrate external services like Google Drive,
Slack, Calendar, etc. through standardized MCP servers.

Updated to support streamable-http protocol (MCP spec 2024-11-05+)
"""

import asyncio
import logging
import json
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
import httpx
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


def _parse_sse_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Server-Sent Events (SSE) format response to extract JSON data.

    Args:
        text: SSE formatted text (e.g., "event: message\\ndata: {...}\\n\\n")

    Returns:
        Parsed JSON data or None if parsing fails
    """
    try:
        # SSE format: "event: message\ndata: {...}\n\n"
        lines = text.strip().split('\n')
        for line in lines:
            if line.startswith('data: '):
                json_str = line[6:]  # Remove "data: " prefix
                return json.loads(json_str)
    except Exception as e:
        logger.debug(f"Failed to parse SSE response: {e}")
    return None


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
    Connect to a remote MCP server via streamable-http and fetch available tools.

    This function:
    1. Sends an initialize request to the MCP server and gets session ID
    2. Sends a 'tools/list' request with session ID
    3. Receives the tool definitions
    4. Converts them to LangChain StructuredTool objects

    Args:
        url: The MCP server URL (e.g., 'http://localhost:8000/mcp')
        timeout: Connection timeout in seconds (default: 10)

    Returns:
        List of LangChain StructuredTool objects (empty list if connection fails)

    Example:
        >>> tools = await get_mcp_tools('http://localhost:8000/mcp')
        >>> print(f"Loaded {len(tools)} tools from MCP server")
    """
    tools: List[StructuredTool] = []

    try:
        logger.info(f"Connecting to MCP server: {url}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                # Send initialization request (streamable-http uses POST for all operations)
                init_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "personal-super-agent",
                            "version": "1.0.0"
                        }
                    }
                }

                init_response = await client.post(
                    url,
                    json=init_request,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                )

                if init_response.status_code != 200:
                    logger.warning(f"Initialize failed for {url}: {init_response.status_code}")
                    return tools

                # Extract session ID from response headers
                session_id = init_response.headers.get("mcp-session-id")
                if not session_id:
                    logger.warning(f"No session ID received from {url}")
                    return tools

                logger.debug(f"Got session ID: {session_id}")

                # Request tool list with session ID
                tools_response = await client.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {}
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "mcp-session-id": session_id
                    }
                )

                if tools_response.status_code == 200:
                    # Parse SSE response
                    data = _parse_sse_response(tools_response.text)
                    if not data:
                        logger.warning(f"Failed to parse SSE response from {url}")
                        return tools

                    if "result" in data and "tools" in data["result"]:
                        mcp_tools = [MCPTool(**tool) for tool in data["result"]["tools"]]

                        # Convert MCP tools to LangChain StructuredTools
                        # Pass session_id so tools can use it
                        for mcp_tool in mcp_tools:
                            langchain_tool = _convert_mcp_to_langchain_tool(mcp_tool, url, session_id)
                            tools.append(langchain_tool)

                        logger.info(f"Successfully loaded {len(tools)} tools from {url}")
                    else:
                        logger.warning(f"No tools found in MCP server response: {url}")
                else:
                    logger.warning(f"Failed to fetch tools from {url}: {tools_response.status_code} - {tools_response.text}")

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
    session_id: str
) -> StructuredTool:
    """
    Convert an MCP tool definition to a LangChain StructuredTool.

    Args:
        mcp_tool: The MCP tool definition
        server_url: The MCP server URL (for making tool calls)
        session_id: The MCP session ID for this connection

    Returns:
        A LangChain StructuredTool that wraps the MCP tool
    """

    # Create an async function that will be called when the tool is invoked
    async def tool_func(**kwargs) -> str:
        """Execute the MCP tool via streamable-http call."""
        try:
            # Auto-inject user_google_email for Gmail/Calendar/Drive/Docs/Sheets tools
            if mcp_tool.name.startswith(('search_gmail', 'get_gmail', 'send_gmail', 'draft_gmail',
                                         'list_gmail', 'manage_gmail', 'create_gmail', 'delete_gmail',
                                         'modify_gmail', 'batch_modify_gmail',
                                         'list_calendars', 'get_events', 'create_event', 'modify_event', 'delete_event',
                                         'search_drive', 'get_drive', 'list_drive', 'create_drive', 'update_drive', 'check_drive',
                                         'list_documents', 'get_document', 'create_document', 'update_document', 'export_doc',
                                         'read_document', 'create_table', 'debug_table',
                                         'list_spreadsheets', 'get_spreadsheet', 'create_spreadsheet', 'create_sheet',
                                         'read_sheet', 'modify_sheet', 'format_sheet', 'add_conditional', 'update_conditional', 'delete_conditional',
                                         'read_spreadsheet_comment', 'create_spreadsheet_comment', 'reply_to_spreadsheet', 'resolve_spreadsheet')):
                if 'user_google_email' not in kwargs:
                    kwargs['user_google_email'] = 'sabine@strugcity.com'

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    server_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": f"call_{mcp_tool.name}",
                        "method": "tools/call",
                        "params": {
                            "name": mcp_tool.name,
                            "arguments": kwargs
                        }
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "mcp-session-id": session_id
                    }
                )

                if response.status_code == 200:
                    # Parse SSE response
                    data = _parse_sse_response(response.text)
                    if not data:
                        return f"Failed to parse response from MCP server"

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
            # Try to initialize connection
            response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": "test",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0.0"}
                    }
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            )
            return response.status_code == 200
    except Exception as e:
        logger.debug(f"MCP server {url} connection test failed: {e}")
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
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": "info",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "info-request", "version": "1.0.0"}
                    }
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
            )

            if response.status_code == 200:
                data = response.json()
                if "result" in data and "serverInfo" in data["result"]:
                    return MCPServerInfo(**data["result"]["serverInfo"])
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
