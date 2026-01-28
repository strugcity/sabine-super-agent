#!/bin/bash
# MCP Server Launcher - Stdio Transport (Direct stdin/stdout pipe)
#
# This script launches the Google Workspace MCP server via Stdio transport.
# The Python agent communicates via direct stdin/stdout pipes (JSON-RPC 2.0).
#
# CRITICAL: All logging must go to stderr (>&2) to preserve stdout for JSON-RPC stream.

# Log startup info to stderr only (preserves stdout for JSON-RPC)
echo "[MCP Server] Launching Google Workspace MCP server (Stdio transport)..." >&2

# Enable Python to show full tracebacks (for any Python subprocess)
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1

echo "[MCP Server] Starting: npx @modelcontextprotocol/server-google-workspace" >&2

# Launch the MCP server via Stdio transport
# - npx resolves and executes the Node.js package
# - Stdio is the default/native transport for MCP (stdin/stdout pipes)
# - JSON-RPC 2.0 messages flow via stdout to parent Python process
# - stderr is available for server diagnostics/logging
exec npx -y @modelcontextprotocol/server-google-workspace
