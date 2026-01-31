"""
Setup Gmail Watch - Enable push notifications for sabine@strugcity.com
"""
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Load credentials from workspace-mcp
creds_dir = Path.home() / '.google_workspace_mcp' / 'credentials'
token_file = creds_dir / 'default_user.json'

print(f"Loading credentials from: {token_file}")

with open(token_file, 'r') as f:
    token_data = json.load(f)

# Create credentials object
creds = Credentials(
    token=token_data['token'],
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri'),
    client_id=token_data.get('client_id'),
    client_secret=token_data.get('client_secret'),
    scopes=token_data.get('scopes'),
)

# Build Gmail service
print("Building Gmail API service...")
service = build('gmail', 'v1', credentials=creds)

# Setup watch request
watch_request = {
    'topicName': 'projects/super-agent-485222/topics/gmail-notification',
    'labelIds': ['INBOX']  # Only watch INBOX
}

print(f"\nSetting up Gmail watch for sabine@strugcity.com...")
print(f"Topic: {watch_request['topicName']}")
print(f"Labels: {watch_request['labelIds']}")

try:
    result = service.users().watch(userId='me', body=watch_request).execute()

    print("\n✓ Gmail watch enabled successfully!")
    print(f"\nWatch details:")
    print(f"  History ID: {result['historyId']}")
    print(f"  Expiration: {result['expiration']} (Unix timestamp in milliseconds)")

    # Convert expiration to readable format
    import datetime
    expiration_ms = int(result['expiration'])
    expiration_dt = datetime.datetime.fromtimestamp(expiration_ms / 1000)
    print(f"  Expires on: {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    print(f"\n✓ Gmail will now send notifications to Pub/Sub when new emails arrive!")

except Exception as e:
    print(f"\n✗ Error setting up Gmail watch:")
    print(f"  {str(e)}")
    print(f"\nMake sure:")
    print(f"  1. Gmail API is enabled")
    print(f"  2. The Pub/Sub topic exists")
    print(f"  3. Gmail has permission to publish to the topic")
    print(f"     Run: gcloud pubsub topics add-iam-policy-binding gmail-notification \\")
    print(f"          --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \\")
    print(f"          --role=roles/pubsub.publisher")
