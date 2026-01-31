"""
Trigger a test of the Gmail flow by calling the Railway endpoint directly.

This simulates what happens when a Pub/Sub notification is received.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

RAILWAY_URL = "https://sabine-super-agent-production.up.railway.app"
API_KEY = os.getenv("AGENT_API_KEY", "")

def trigger_gmail_handler():
    """Call the Gmail handler with a fake history ID to trigger email processing."""

    print(f"\n{'='*60}")
    print("Triggering Gmail Handler on Railway")
    print(f"{'='*60}")

    # Use a dummy history ID - the handler will fetch recent emails anyway
    payload = {"historyId": "test-manual-trigger"}

    print(f"URL: {RAILWAY_URL}/gmail/handle")
    print(f"Payload: {payload}")

    try:
        response = requests.post(
            f"{RAILWAY_URL}/gmail/handle",
            json=payload,
            headers={"X-API-Key": API_KEY},
            timeout=120  # Email processing can take a while
        )

        print(f"\nStatus: {response.status_code}")
        print(f"Response: {response.json()}")

        return response.json()

    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: AGENT_API_KEY not set in .env")
    else:
        trigger_gmail_handler()
