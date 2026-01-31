"""
Complete OAuth flow for workspace-mcp by directly using Google's OAuth library.
This creates the tokens that workspace-mcp expects.
"""
import os
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes needed for Gmail, Calendar, Drive, Docs, Sheets
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
]

# Create client_secret data (Desktop app type)
client_config = {
    "installed": {
        "client_id": "1015418157789-t6ruhsn6qdsb438tg8eoql66upvtg6jl.apps.googleusercontent.com",
        "client_secret": "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",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]
    }
}

# Set environment variable to allow HTTP (for localhost)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

print("Starting OAuth flow...")
print("A browser window will open for you to authorize the application.")
print()

# Create flow from client config
flow = InstalledAppFlow.from_client_config(
    client_config,
    scopes=SCOPES
)

# Run local server to complete OAuth
# This will open a browser and wait for authorization
creds = flow.run_local_server(port=8080, open_browser=True)

print("\nAuthorization successful!")
print(f"Access token obtained (expires: {creds.expiry})")

# Save credentials to workspace-mcp's expected location
creds_dir = Path.home() / '.google_workspace_mcp' / 'credentials'
creds_dir.mkdir(parents=True, exist_ok=True)

# workspace-mcp expects a specific format - let's save as 'default_user.json'
token_data = {
    'token': creds.token,
    'refresh_token': creds.refresh_token,
    'token_uri': creds.token_uri,
    'client_id': creds.client_id,
    'client_secret': creds.client_secret,
    'scopes': creds.scopes,
    'expiry': creds.expiry.isoformat() if creds.expiry else None
}

token_file = creds_dir / 'default_user.json'
with open(token_file, 'w') as f:
    json.dump(token_data, f, indent=2)

print(f"\nCredentials saved to: {token_file}")
print("\nYou can now use workspace-mcp with these credentials!")
