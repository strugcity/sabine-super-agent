"""
Manually exchange the authorization code for OAuth tokens.
"""
import requests
import json
from pathlib import Path

# The authorization code from your URL
AUTH_CODE = "4/0ASc3gC0PtUGi-Jhv5HT5Um1gIQLM5GdOVlUypYALDI2GuTxhyD3kHQJxonacKrXnDw2CjA"

# OAuth credentials
CLIENT_ID = "1015418157789-gctjhmblg1s8hm6674kituke2ki0t7rj.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-u9kF9cHhNHyYPh3wku-xskOe7Td"
REDIRECT_URI = "http://localhost:8080/"
TOKEN_URI = "https://oauth2.googleapis.com/token"

print("Exchanging authorization code for tokens...")

# Exchange the authorization code for tokens
response = requests.post(TOKEN_URI, data={
    'code': AUTH_CODE,
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'redirect_uri': REDIRECT_URI,
    'grant_type': 'authorization_code'
})

print(f"Response status: {response.status_code}")
print(f"Response: {response.text}")

if response.status_code == 200:
    token_data = response.json()

    print("\n✓ Token exchange successful!")
    print(f"Access token obtained")

    # Save credentials to workspace-mcp's expected location
    creds_dir = Path.home() / '.google_workspace_mcp' / 'credentials'
    creds_dir.mkdir(parents=True, exist_ok=True)

    # Save as default_user.json
    token_file = creds_dir / 'default_user.json'
    with open(token_file, 'w') as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✓ Credentials saved to: {token_file}")
    print("\nYou can now use workspace-mcp with these credentials!")
else:
    print(f"\n✗ Token exchange failed!")
    print(f"Error: {response.text}")
