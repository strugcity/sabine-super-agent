"""
Get a refresh token for a Google account.

Usage:
    python get_refresh_token.py

This will:
1. Open a browser for you to log in with the Google account you want to authorize
2. Print the refresh token that you can add to Railway environment variables

IMPORTANT: Log in with the account you want to grant access to:
- For USER_REFRESH_TOKEN: log in as rknollmaier@gmail.com
- For AGENT_REFRESH_TOKEN: log in as sabine@strugcity.com
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check for required env vars
client_id = os.getenv('GOOGLE_CLIENT_ID') or os.getenv('GOOGLE_OAUTH_CLIENT_ID')
client_secret = os.getenv('GOOGLE_CLIENT_SECRET') or os.getenv('GOOGLE_OAUTH_CLIENT_SECRET')

if not client_id or not client_secret:
    print("ERROR: Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env file")
    print("\nPlease ensure your .env file has:")
    print("  GOOGLE_CLIENT_ID=your_client_id")
    print("  GOOGLE_CLIENT_SECRET=your_client_secret")
    sys.exit(1)

print(f"Using OAuth Client ID: {client_id[:20]}...")
print()

from google_auth_oauthlib.flow import InstalledAppFlow

# Comprehensive scopes for full Google Workspace access
SCOPES = [
    # Gmail
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels',
    # Calendar
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
    # Drive
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file',
    # Docs
    'https://www.googleapis.com/auth/documents',
    # Sheets
    'https://www.googleapis.com/auth/spreadsheets',
]

# Create client config
client_config = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]
    }
}

# Allow HTTP for localhost OAuth redirect
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

print("=" * 60)
print("GOOGLE OAUTH FLOW")
print("=" * 60)
print()
print("A browser window will open.")
print("Log in with the Google account you want to authorize.")
print()
print("  - For USER credentials:  log in as rknollmaier@gmail.com")
print("  - For AGENT credentials: log in as sabine@strugcity.com")
print()
print("=" * 60)
input("Press Enter to continue...")

# Create flow and run
flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

try:
    creds = flow.run_local_server(port=8080, open_browser=True)
except Exception as e:
    print(f"\nError during OAuth flow: {e}")
    print("\nTroubleshooting:")
    print("1. Make sure port 8080 is not in use")
    print("2. Make sure the OAuth app has http://localhost:8080 as a redirect URI")
    sys.exit(1)

print()
print("=" * 60)
print("SUCCESS! Authorization complete.")
print("=" * 60)
print()
print(f"Authorized account scopes: {len(creds.scopes)} scopes granted")
print()
print("-" * 60)
print("REFRESH TOKEN (copy this to Railway):")
print("-" * 60)
print()
print(creds.refresh_token)
print()
print("-" * 60)
print()
print("Add this to Railway as:")
print("  - USER_REFRESH_TOKEN   (if you logged in as rknollmaier@gmail.com)")
print("  - AGENT_REFRESH_TOKEN  (if you logged in as sabine@strugcity.com)")
print()
