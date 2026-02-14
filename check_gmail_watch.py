"""
Check Gmail Watch Status

Uses AGENT credentials (sabine@strugcity.com) from .env.
"""
import os
import sys

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

creds = Credentials(
    token=None,
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
service = build('gmail', 'v1', credentials=creds)

# Setup watch (this also renews/checks status)
watch_request = {
    'topicName': PUBSUB_TOPIC,
    'labelIds': ['INBOX']
}

try:
    result = service.users().watch(userId='me', body=watch_request).execute()
    print("SUCCESS! Gmail watch enabled")
    print(f"History ID: {result['historyId']}")
    print(f"Expiration: {result['expiration']}")

    import datetime
    exp_ms = int(result['expiration'])
    exp_dt = datetime.datetime.fromtimestamp(exp_ms / 1000)
    print(f"Expires on: {exp_dt.strftime('%Y-%m-%d %H:%M:%S')}")

except Exception as e:
    print(f"Error: {e}")
