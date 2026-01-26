#!/bin/bash
# Setup MCP credentials from environment variables
# This script runs at container startup to create the credentials file
# needed by workspace-mcp for Google OAuth authentication.

set -e

# Default user for workspace-mcp credentials
MCP_USER_EMAIL="${USER_GOOGLE_EMAIL:-sabine@strugcity.com}"
CRED_DIR="/root/.google_workspace_mcp/credentials"
CRED_FILE="${CRED_DIR}/${MCP_USER_EMAIL}.json"

echo "[MCP Setup] Checking for Google OAuth credentials..."

# Check if required environment variables are set
if [ -z "$GOOGLE_REFRESH_TOKEN" ]; then
    echo "[MCP Setup] WARNING: GOOGLE_REFRESH_TOKEN not set. MCP server may fail to authenticate."
    exit 0
fi

if [ -z "$GOOGLE_OAUTH_CLIENT_ID" ]; then
    echo "[MCP Setup] WARNING: GOOGLE_OAUTH_CLIENT_ID not set. MCP server may fail to authenticate."
    exit 0
fi

if [ -z "$GOOGLE_OAUTH_CLIENT_SECRET" ]; then
    echo "[MCP Setup] WARNING: GOOGLE_OAUTH_CLIENT_SECRET not set. MCP server may fail to authenticate."
    exit 0
fi

echo "[MCP Setup] Creating credentials directory: ${CRED_DIR}"
mkdir -p "${CRED_DIR}"

echo "[MCP Setup] Writing credentials file for ${MCP_USER_EMAIL}"
cat > "${CRED_FILE}" << EOF
{
  "token": "",
  "refresh_token": "${GOOGLE_REFRESH_TOKEN}",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "${GOOGLE_OAUTH_CLIENT_ID}",
  "client_secret": "${GOOGLE_OAUTH_CLIENT_SECRET}",
  "scopes": [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets"
  ],
  "expiry": "1970-01-01T00:00:00.000000"
}
EOF

# Set appropriate permissions
chmod 600 "${CRED_FILE}"

echo "[MCP Setup] Credentials file created successfully at ${CRED_FILE}"
echo "[MCP Setup] MCP server will use refresh token to obtain access token on first request"
