#!/bin/bash
# MCP Server Launcher - Headless Gmail (Stdio Transport)
#
# This script launches the headless Gmail MCP server via Stdio transport.
# The Python agent communicates via direct stdin/stdout pipes (JSON-RPC 2.0).
#
# CRITICAL: All logging must go to stderr (>&2) to preserve stdout for JSON-RPC stream.
#
# Package: @peakmojo/mcp-server-headless-gmail
# - Designed for headless/server environments (no browser OAuth required)
# - Credentials passed as tool parameters, not env vars
# - Supports: gmail_refresh_token, get_recent_emails, get_email_content, send_email

# Log startup info to stderr only (preserves stdout for JSON-RPC)
echo "[MCP Server] Launching Headless Gmail MCP server (Stdio transport)..." >&2

# Enable Python to show full tracebacks (for any Python subprocess)
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1

echo "[MCP Server] Starting: npx @peakmojo/mcp-server-headless-gmail" >&2

# Launch the headless Gmail MCP server via Stdio transport
# - npx resolves and executes the Node.js package
# - JSON-RPC 2.0 messages flow via stdout to parent Python process
# - stderr is available for server diagnostics/logging
exec npx -y @peakmojo/mcp-server-headless-gmail
