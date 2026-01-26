#!/bin/bash
# Wrapper script to start workspace-mcp with proper environment
# This ensures Railway's PORT doesn't conflict and captures any errors

# Unset Railway's PORT to prevent workspace-mcp from using it
unset PORT

# Explicitly set workspace-mcp port
export WORKSPACE_MCP_PORT=8000

# Enable Python to show full tracebacks
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1

echo "[MCP Wrapper] Starting workspace-mcp on port ${WORKSPACE_MCP_PORT}..."
echo "[MCP Wrapper] Environment: WORKSPACE_MCP_PORT=${WORKSPACE_MCP_PORT}"

# Run workspace-mcp and capture any errors
exec workspace-mcp --transport streamable-http 2>&1
