#!/bin/bash
# Setup MCP credentials from environment variables
# This script runs at container startup to create the credentials file
# needed by @presto-ai/google-workspace-mcp for Google OAuth authentication.
#
# The MCP server expects:
# - Credentials in ~/.config/google-workspace-mcp/
# - Environment variables: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

set -e

echo "[MCP Setup] Checking for Google OAuth credentials..."

# Support both naming conventions for env vars (GOOGLE_OAUTH_* and GOOGLE_*)
CLIENT_ID="${GOOGLE_CLIENT_ID:-$GOOGLE_OAUTH_CLIENT_ID}"
CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-$GOOGLE_OAUTH_CLIENT_SECRET}"

# Check if required environment variables are set
if [ -z "$GOOGLE_REFRESH_TOKEN" ]; then
    echo "[MCP Setup] WARNING: GOOGLE_REFRESH_TOKEN not set. MCP server may fail to authenticate."
    exit 0
fi

if [ -z "$CLIENT_ID" ]; then
    echo "[MCP Setup] WARNING: GOOGLE_CLIENT_ID not set. MCP server may fail to authenticate."
    exit 0
fi

if [ -z "$CLIENT_SECRET" ]; then
    echo "[MCP Setup] WARNING: GOOGLE_CLIENT_SECRET not set. MCP server may fail to authenticate."
    exit 0
fi

# Export the correct env var names that the MCP server expects
export GOOGLE_CLIENT_ID="$CLIENT_ID"
export GOOGLE_CLIENT_SECRET="$CLIENT_SECRET"

# @presto-ai/google-workspace-mcp uses ~/.config/google-workspace-mcp/
CONFIG_DIR="/root/.config/google-workspace-mcp"
CRED_FILE="${CONFIG_DIR}/credentials.json"

echo "[MCP Setup] Creating config directory: ${CONFIG_DIR}"
mkdir -p "${CONFIG_DIR}"

# Write credentials file in the format expected by the MCP server
echo "[MCP Setup] Writing credentials file: ${CRED_FILE}"
cat > "${CRED_FILE}" << EOF
{
  "installed": {
    "client_id": "${CLIENT_ID}",
    "client_secret": "${CLIENT_SECRET}",
    "redirect_uris": ["http://localhost"]
  },
  "refresh_token": "${GOOGLE_REFRESH_TOKEN}",
  "token_uri": "https://oauth2.googleapis.com/token",
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
  ]
}
EOF
chmod 600 "${CRED_FILE}"

# Also write a token file if needed
TOKEN_FILE="${CONFIG_DIR}/token.json"
echo "[MCP Setup] Writing token file: ${TOKEN_FILE}"
cat > "${TOKEN_FILE}" << EOF
{
  "access_token": "",
  "refresh_token": "${GOOGLE_REFRESH_TOKEN}",
  "token_type": "Bearer",
  "expiry_date": 0
}
EOF
chmod 600 "${TOKEN_FILE}"

# Legacy path support - also write to old location for compatibility
LEGACY_DIR="/root/.google_workspace_mcp/credentials"
mkdir -p "${LEGACY_DIR}"
MCP_USER_EMAIL="${USER_GOOGLE_EMAIL:-default_user}"
LEGACY_FILE="${LEGACY_DIR}/${MCP_USER_EMAIL}.json"
echo "[MCP Setup] Writing legacy credentials: ${LEGACY_FILE}"
cat > "${LEGACY_FILE}" << EOF
{
  "token": "",
  "refresh_token": "${GOOGLE_REFRESH_TOKEN}",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "${CLIENT_ID}",
  "client_secret": "${CLIENT_SECRET}",
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
chmod 600 "${LEGACY_FILE}"

# Also create default_user.json
cp "${LEGACY_FILE}" "${LEGACY_DIR}/default_user.json"

echo "[MCP Setup] Credentials files created successfully:"
echo "  - ${CRED_FILE} (primary)"
echo "  - ${TOKEN_FILE}"
echo "  - ${LEGACY_FILE} (legacy)"
echo "[MCP Setup] Environment: GOOGLE_CLIENT_ID=${CLIENT_ID:0:20}..."
echo "[MCP Setup] MCP server will use refresh token to obtain access token on first request"
