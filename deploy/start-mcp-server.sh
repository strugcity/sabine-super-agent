#!/bin/bash
# Wrapper script to start workspace-mcp (Node.js MCP server) with proper environment
# This ensures Railway's PORT doesn't conflict and captures any errors

# Unset Railway's PORT to prevent workspace-mcp from using it
unset PORT

# Explicitly set workspace-mcp port
export WORKSPACE_MCP_PORT=8000

# Enable Python to show full tracebacks
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1

echo "[MCP Wrapper] Starting workspace-mcp (via npx) on port ${WORKSPACE_MCP_PORT}..."
echo "[MCP Wrapper] Environment: WORKSPACE_MCP_PORT=${WORKSPACE_MCP_PORT}"

# Run workspace-mcp via npx (Node Package eXecute)
# npx resolves and runs the executable from node_modules
# Using @presto-ai/google-workspace-mcp which provides CLI via streamable-http transport
exec npx -y @presto-ai/google-workspace-mcp --transport streamable-http 2>&1
