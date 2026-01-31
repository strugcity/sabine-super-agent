"""
Check Gmail Watch Status
"""
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Load credentials
creds_dir = Path.home() / '.google_workspace_mcp' / 'credentials'
token_file = creds_dir / 'default_user.json'

with open(token_file, 'r') as f:
    token_data = json.load(f)

creds = Credentials(
    token=token_data['token'],
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri'),
    client_id=token_data.get('client_id'),
    client_secret=token_data.get('client_secret'),
    scopes=token_data.get('scopes'),
)

# Build Gmail service
service = build('gmail', 'v1', credentials=creds)

# Setup watch
watch_request = {
    'topicName': 'projects/super-agent-485222/topics/gmail-notification',
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
