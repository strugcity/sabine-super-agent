#!/usr/bin/env python3
"""
Setup Gmail Watch - Configures Gmail push notifications via Pub/Sub.

This script:
1. Loads Google credentials from workspace-mcp credentials directory
2. Sets up or renews the Gmail watch for push notifications
3. Updates the .env file with the current ngrok URL if provided

Usage:
    python scripts/setup_gmail_watch.py [--ngrok-url URL]
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")


def get_credentials():
    """Load Google credentials from workspace-mcp credentials directory."""
    from google.oauth2.credentials import Credentials

    creds_dir = Path.home() / ".google_workspace_mcp" / "credentials"

    # Try user-specific credentials first
    user_email = os.getenv("USER_GOOGLE_EMAIL", "sabine@strugcity.com")
    token_file = creds_dir / f"{user_email}.json"

    if not token_file.exists():
        token_file = creds_dir / "default_user.json"

    if not token_file.exists():
        print(f"ERROR: No credentials found at {creds_dir}")
        print("Please run OAuth flow first via workspace-mcp")
        return None

    with open(token_file, "r") as f:
        token_data = json.load(f)

    return Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )


def setup_gmail_watch(credentials):
    """Set up Gmail push notification watch."""
    from googleapiclient.discovery import build

    topic_name = os.getenv(
        "GMAIL_PUBSUB_TOPIC", "projects/super-agent-485222/topics/gmail-notification"
    )

    service = build("gmail", "v1", credentials=credentials)

    watch_request = {"topicName": topic_name, "labelIds": ["INBOX"]}

    try:
        result = service.users().watch(userId="me", body=watch_request).execute()

        history_id = result["historyId"]
        expiration_ms = int(result["expiration"])
        expiration_dt = datetime.datetime.fromtimestamp(expiration_ms / 1000)

        print(f"SUCCESS: Gmail watch enabled")
        print(f"  History ID: {history_id}")
        print(f"  Expiration: {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Topic: {topic_name}")

        return True

    except Exception as e:
        print(f"ERROR: Failed to set up Gmail watch: {e}")
        return False


def update_env_ngrok_url(ngrok_url: str):
    """Update the .env file with the new ngrok URL."""
    env_file = project_root / ".env"

    if not env_file.exists():
        print("ERROR: .env file not found")
        return False

    content = env_file.read_text()

    # Update GMAIL_WEBHOOK_URL
    webhook_url = f"{ngrok_url}/api/gmail/webhook"
    new_content = re.sub(
        r"^GMAIL_WEBHOOK_URL=.*$",
        f"GMAIL_WEBHOOK_URL={webhook_url}",
        content,
        flags=re.MULTILINE,
    )

    if new_content == content:
        # Line doesn't exist, add it
        new_content += f"\nGMAIL_WEBHOOK_URL={webhook_url}\n"

    env_file.write_text(new_content)
    print(f"Updated .env with GMAIL_WEBHOOK_URL={webhook_url}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Setup Gmail push notifications")
    parser.add_argument(
        "--ngrok-url",
        help="ngrok public URL to use for webhook (e.g., https://abc123.ngrok-free.dev)",
    )
    parser.add_argument(
        "--update-env-only",
        action="store_true",
        help="Only update .env file with ngrok URL, skip Gmail watch setup",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("Gmail Watch Setup")
    print("=" * 50)
    print()

    # Update .env with ngrok URL if provided
    if args.ngrok_url:
        update_env_ngrok_url(args.ngrok_url)
        print()

    if args.update_env_only:
        return 0

    # Get credentials
    print("Loading Google credentials...")
    credentials = get_credentials()
    if not credentials:
        return 1

    # Setup Gmail watch
    print("Setting up Gmail watch...")
    if not setup_gmail_watch(credentials):
        return 1

    print()
    print("Gmail push notifications configured!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
