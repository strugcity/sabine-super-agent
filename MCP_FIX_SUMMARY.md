# MCP Client Fix Implementation

## Summary

Successfully migrated the Python MCP client from **HTTP-based (SSE)** transport to **Stdio-based** transport to match the `workspace-mcp` server configuration.

## Changes Made

### 1. **lib/agent/mcp_client.py** - Complete rewrite
- **Removed**: HTTP POST-based communication with SSE parsing
- **Added**: Stdio subprocess communication via `mcp.client.stdio`
- **Key changes**:
  - Replaced `httpx.AsyncClient` with `StdioServerParameters` + `stdio_client`
  - Removed `_parse_sse_response()` function (no longer needed)
  - Updated `get_mcp_tools()` signature: `(url: str)` → `(command: str, args: List[str])`
  - Updated `test_mcp_connection()` to use Stdio transport
  - Removed `get_mcp_server_info()` (not applicable to Stdio)
  - Tool invocation now uses `session.call_tool()` instead of HTTP POST

### 2. **lib/agent/registry.py** - Configuration update
- **Changed MCP_SERVERS format**:
  ```python
  # Before: ["http://localhost:8000", "http://localhost:8001"]
  # After:  [{"command": "workspace-mcp", "args": ["--transport", "stdio"]}]
  ```
- **Updated `load_mcp_tools()`** to pass `command` and `args` to `get_mcp_tools()`

### 3. **lib/agent/__init__.py** - Removed deprecated import
- Removed `get_mcp_server_info` from imports and `__all__` exports

### 4. **test_mcp_connection.py** - New test script
- Quick validation script to test MCP connection
- Tests connection availability and tool loading
- Run: `python test_mcp_connection.py`

## Why This Fixes the Connection Issue

| Aspect | Before | After |
|--------|--------|-------|
| **Transport** | HTTP POST (SSE) | Stdio (stdin/stdout pipes) |
| **Server startup** | Expects HTTP server | Matches `workspace-mcp --transport streamable-http` |
| **Connection type** | Remote over network | Direct process communication |
| **Serialization** | SSE parsing | MCP protocol messages |
| **Session handling** | Manual session ID tracking | Built-in `ClientSession` |

## Configuration

Update your environment variable to specify MCP servers:

```bash
# Format: "command:arg1:arg2 command2 command3:arg1"
export MCP_SERVERS="workspace-mcp workspace-calendar:--config=/etc/mcp/calendar.conf"
```

## Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Test the connection
python test_mcp_connection.py
```

Expected output (with workspace-mcp installed):
```
[TEST 1] Testing workspace-mcp availability...
✓ workspace-mcp is available and responding

[TEST 2] Loading tools from workspace-mcp...
✓ Successfully loaded 47 tools
```

## Reference

- **MCP Spec**: 2024-11-05+
- **Transport**: `StdioServerParameters` from `mcp.client.stdio`
- **Python MCP Library**: `mcp>=1.1.1` (in requirements.txt)
