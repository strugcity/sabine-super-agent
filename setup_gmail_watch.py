"""
Setup Gmail Watch - Enable push notifications for sabine@strugcity.com

Uses the AGENT credentials (sabine@strugcity.com) since the watch must be
set up on the inbox that receives the emails.

Reads GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and AGENT_REFRESH_TOKEN from .env
so the watch is created with the same OAuth client that Railway uses.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Load environment variables
load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
AGENT_REFRESH_TOKEN = os.getenv("AGENT_REFRESH_TOKEN", "")
PUBSUB_TOPIC = os.getenv("GMAIL_PUBSUB_TOPIC", "projects/sabine-super-agent/topics/gmail-notification")

if not CLIENT_ID or not CLIENT_SECRET or not AGENT_REFRESH_TOKEN:
    print("ERROR: Missing GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or AGENT_REFRESH_TOKEN in .env")
    sys.exit(1)

print(f"Using OAuth Client ID: {CLIENT_ID[:30]}...")
print(f"Using PubSub Topic: {PUBSUB_TOPIC}")
print(f"Agent refresh token: {AGENT_REFRESH_TOKEN[:30]}...")

# Create credentials object from .env values (sabine@strugcity.com)
creds = Credentials(
    token=None,  # Will be auto-refreshed
    refresh_token=AGENT_REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    scopes=[
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ],
)

# Build Gmail service
print("\nBuilding Gmail API service for sabine@strugcity.com...")
service = build('gmail', 'v1', credentials=creds)

# Setup watch request
watch_request = {
    'topicName': PUBSUB_TOPIC,
    'labelIds': ['INBOX']  # Only watch INBOX
}

print(f"\nSetting up Gmail watch for sabine@strugcity.com...")
print(f"Topic: {watch_request['topicName']}")
print(f"Labels: {watch_request['labelIds']}")

try:
    result = service.users().watch(userId='me', body=watch_request).execute()

    print("\n[OK] Gmail watch enabled successfully!")
    print(f"\nWatch details:")
    print(f"  History ID: {result['historyId']}")
    print(f"  Expiration: {result['expiration']} (Unix timestamp in milliseconds)")

    # Convert expiration to readable format
    import datetime
    expiration_ms = int(result['expiration'])
    expiration_dt = datetime.datetime.fromtimestamp(expiration_ms / 1000)
    print(f"  Expires on: {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    print(f"\n[OK] Gmail will now send notifications to Pub/Sub when new emails arrive!")

except Exception as e:
    print(f"\n[FAIL] Error setting up Gmail watch:")
    print(f"  {str(e)}")
    print(f"\nMake sure:")
    print(f"  1. Gmail API is enabled")
    print(f"  2. The Pub/Sub topic exists")
    print(f"  3. Gmail has permission to publish to the topic")
    print(f"     Run: gcloud pubsub topics add-iam-policy-binding gmail-notification \\")
    print(f"          --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \\")
    print(f"          --role=roles/pubsub.publisher")
