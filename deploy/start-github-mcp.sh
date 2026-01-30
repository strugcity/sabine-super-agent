#!/bin/bash
# MCP Server Launcher - GitHub (Stdio Transport)
#
# NOTE: This script is currently DISABLED because the npm-based GitHub MCP servers
# (@modelcontextprotocol/server-github, github-mcp) have known bugs where list_tools
# returns empty arrays. See: https://github.com/modelcontextprotocol/servers/issues/493
#
# GitHub integration is instead provided via the local Python skill at:
# lib/skills/github/handler.py
#
# This script exists for future use when a working npm-based GitHub MCP becomes available.

echo "[MCP GitHub] DISABLED: Using local Python skill instead of MCP server" >&2
echo "[MCP GitHub] See lib/skills/github/ for GitHub integration" >&2

# Exit gracefully - the registry will handle this as a server with 0 tools
# We don't exit 1 to avoid error logs
sleep 1
exit 0
