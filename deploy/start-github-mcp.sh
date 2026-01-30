#!/bin/bash
# MCP Server Launcher - GitHub (Stdio Transport)
#
# This script launches the GitHub MCP server via Stdio transport.
# The Python agent communicates via direct stdin/stdout pipes (JSON-RPC 2.0).
#
# CRITICAL: All logging must go to stderr (>&2) to preserve stdout for JSON-RPC stream.
#
# Package: @modelcontextprotocol/server-github
# - Requires GITHUB_TOKEN environment variable
# - Supports: repository operations, issues, PRs, file content

# Log startup info to stderr only (preserves stdout for JSON-RPC)
echo "[MCP GitHub] Launching GitHub MCP server (Stdio transport)..." >&2

# The GitHub MCP server expects GITHUB_PERSONAL_ACCESS_TOKEN
# We accept either GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN for flexibility
if [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ] && [ -z "$GITHUB_TOKEN" ]; then
    echo "[MCP GitHub] ERROR: Neither GITHUB_PERSONAL_ACCESS_TOKEN nor GITHUB_TOKEN is set" >&2
    echo "[MCP GitHub] Please set GITHUB_PERSONAL_ACCESS_TOKEN in Railway environment variables" >&2
    exit 1
fi

# Export as GITHUB_PERSONAL_ACCESS_TOKEN (what the MCP server expects)
if [ -n "$GITHUB_TOKEN" ] && [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
    export GITHUB_PERSONAL_ACCESS_TOKEN="$GITHUB_TOKEN"
    echo "[MCP GitHub] Using GITHUB_TOKEN as GITHUB_PERSONAL_ACCESS_TOKEN" >&2
fi

# Enable Python to show full tracebacks (for any Python subprocess)
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1

echo "[MCP GitHub] Starting: npx @modelcontextprotocol/server-github" >&2
echo "[MCP GitHub] Token present: ${GITHUB_PERSONAL_ACCESS_TOKEN:0:4}..." >&2

# Launch the GitHub MCP server via Stdio transport
# - npx resolves and executes the Node.js package
# - JSON-RPC 2.0 messages flow via stdout to parent Python process
# - stderr is available for server diagnostics/logging
exec npx -y @modelcontextprotocol/server-github
