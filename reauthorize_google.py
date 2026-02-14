"""
Re-authorize Google OAuth for the Super Agent.

Opens a browser window to complete the OAuth flow and obtain a new
refresh token.  The token is saved to the workspace-mcp credentials
directory and printed so it can be pasted into Railway.

IMPORTANT: This script reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
from your .env file so that the refresh token is generated with the SAME
OAuth client that Railway uses.  Using a different client ID is the #1
cause of recurring ``invalid_grant`` errors.
"""

import json
import os
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv

# ── Load environment ────────────────────────────────────────────────
load_dotenv()

CLIENT_ID = (
    os.getenv("GOOGLE_CLIENT_ID")
    or os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    or ""
)
CLIENT_SECRET = (
    os.getenv("GOOGLE_CLIENT_SECRET")
    or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    or ""
)

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env")
    print("These MUST match what Railway uses, otherwise the refresh token")
    print("will fail with invalid_grant when the server tries to use it.")
    sys.exit(1)

print(f"Using OAuth Client ID: {CLIENT_ID[:30]}...")
print(f"  (from .env — must match Railway)")

REDIRECT_URI = "http://localhost:8765/oauth/callback"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

CREDS_DIR = Path.home() / ".google_workspace_mcp" / "credentials"

# Global to store the auth code
auth_code = None
auth_error = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass  # Suppress default logging

    def do_GET(self):
        global auth_code, auth_error

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:system-ui;text-align:center;padding:50px;'>"
                b"<h1>Authorization Successful!</h1>"
                b"<p>You can close this window and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "error" in params:
            auth_error = params.get(
                "error_description", params.get("error", ["Unknown error"])
            )[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body style='font-family:system-ui;text-align:center;padding:50px;'>"
                f"<h1>Authorization Failed</h1>"
                f"<p>Error: {auth_error}</p>"
                f"</body></html>".encode()
            )
        else:
            self.send_response(404)
            self.end_headers()


def exchange_code_for_tokens(code: str) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
    )
    if response.status_code == 200:
        return response.json()
    raise Exception(f"Token exchange failed: {response.text}")


def get_user_email(access_token: str) -> str | None:
    """Get the email address of the authenticated user."""
    response = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code == 200:
        return response.json().get("email")
    return None


def save_credentials(email: str, tokens: dict) -> Path:
    """Save credentials to the workspace-mcp credentials directory."""
    CREDS_DIR.mkdir(parents=True, exist_ok=True)

    cred_data = {
        "token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scopes": SCOPES,
    }

    cred_file = CREDS_DIR / f"{email}.json"
    with open(cred_file, "w") as f:
        json.dump(cred_data, f, indent=2)
    print(f"Saved credentials to: {cred_file}")

    # Also update default_user.json for primary user
    default_file = CREDS_DIR / "default_user.json"
    if not default_file.exists() or email == "rknollmaier@gmail.com":
        with open(default_file, "w") as f:
            json.dump(cred_data, f, indent=2)
        print("Updated default_user.json")

    return cred_file


def main() -> None:
    global auth_code, auth_error

    print("=" * 60)
    print("Google OAuth Re-authorization")
    print("=" * 60)
    print()
    print(f"Client ID:  {CLIENT_ID[:30]}...")
    print(f"Client Secret: {CLIENT_SECRET[:10]}...")
    print()

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        "response_type=code&"
        f"scope={'+'.join(SCOPES)}&"
        "access_type=offline&"
        "prompt=consent"  # Force consent to get new refresh token
    )

    print("Starting local server on port 8765...")

    server = HTTPServer(("localhost", 8765), OAuthCallbackHandler)
    server.timeout = 120

    print("\nOpening browser for authorization...")
    print("\nIf the browser doesn't open, go to this URL:")
    print("-" * 60)
    print(auth_url)
    print("-" * 60)

    webbrowser.open(auth_url)

    print("\nWaiting for authorization...")

    while auth_code is None and auth_error is None:
        server.handle_request()

    server.server_close()

    if auth_error:
        print(f"\nAuthorization failed: {auth_error}")
        return

    if not auth_code:
        print("\nNo authorization code received")
        return

    print("\nReceived authorization code, exchanging for tokens...")

    try:
        tokens = exchange_code_for_tokens(auth_code)

        email = get_user_email(tokens["access_token"])
        if not email:
            email = input("Enter email address for these credentials: ")

        print(f"\nAuthorized as: {email}")

        save_credentials(email, tokens)

        print()
        print("=" * 60)
        print("SUCCESS!")
        print("=" * 60)
        print(f"\nNew credentials saved for: {email}")
        print(f"Refresh token: {tokens['refresh_token'][:30]}...")

        print()
        print("-" * 60)
        print("NEXT STEPS — update Railway environment variable:")
        print("-" * 60)
        if email and "strugcity" in email:
            print(f"  AGENT_REFRESH_TOKEN={tokens['refresh_token']}")
        else:
            print(f"  USER_REFRESH_TOKEN={tokens['refresh_token']}")
        print()
        print("IMPORTANT: The token was generated with this client ID:")
        print(f"  {CLIENT_ID}")
        print("Railway's GOOGLE_CLIENT_ID must match EXACTLY.")
        print("-" * 60)

    except Exception as e:
        print(f"\nError exchanging code for tokens: {e}")


if __name__ == "__main__":
    main()
