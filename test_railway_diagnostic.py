"""
Test Railway diagnostic endpoint to verify credentials.

Usage:
    python test_railway_diagnostic.py <railway_url>

Example:
    python test_railway_diagnostic.py https://sabine-super-agent-production.up.railway.app
"""
import sys
import requests
import os
from dotenv import load_dotenv

load_dotenv()

def test_diagnostic(railway_url: str):
    """Call the diagnostic endpoint and display results."""

    api_key = os.getenv("AGENT_API_KEY", "")
    if not api_key:
        print("ERROR: AGENT_API_KEY not set in .env")
        return

    # Remove trailing slash
    railway_url = railway_url.rstrip('/')

    print(f"\n{'='*60}")
    print(f"Testing Railway Diagnostic Endpoint")
    print(f"{'='*60}")
    print(f"URL: {railway_url}/gmail/diagnostic")

    try:
        response = requests.get(
            f"{railway_url}/gmail/diagnostic",
            headers={"X-API-Key": api_key},
            timeout=30
        )

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"\n{'='*60}")
            print("CREDENTIAL STATUS")
            print(f"{'='*60}")

            # Check each credential
            for key in ["google_client_id", "google_client_secret", "user_refresh_token", "agent_refresh_token"]:
                info = data.get(key, {})
                status = "✓" if info.get("set") else "✗"
                print(f"\n{key}:")
                print(f"  Set: {status}")
                print(f"  Prefix: {info.get('prefix', 'N/A')}")
                print(f"  Length: {info.get('length', 0)}")

            print(f"\n{'='*60}")
            print("EMAIL CONFIGURATION")
            print(f"{'='*60}")
            print(f"gmail_authorized_emails: {data.get('gmail_authorized_emails', 'N/A')}")
            print(f"assistant_email: {data.get('assistant_email', 'N/A')}")
            print(f"agent_email: {data.get('agent_email', 'N/A')}")
            print(f"user_google_email: {data.get('user_google_email', 'N/A')}")

            # Compare with expected values
            print(f"\n{'='*60}")
            print("EXPECTED VS ACTUAL")
            print(f"{'='*60}")

            expected_client_id_prefix = "987434494231-msbeg"
            expected_user_token_prefix = "1//04xRI_WBknUJb"
            expected_agent_token_prefix = "1//04eDDb2hnUPMS"

            client_id_match = data.get("google_client_id", {}).get("prefix", "").startswith(expected_client_id_prefix)
            user_token_match = data.get("user_refresh_token", {}).get("prefix", "").startswith(expected_user_token_prefix)
            agent_token_match = data.get("agent_refresh_token", {}).get("prefix", "").startswith(expected_agent_token_prefix)

            print(f"google_client_id: {'✓ MATCH' if client_id_match else '✗ MISMATCH'}")
            print(f"  Expected prefix: {expected_client_id_prefix}...")
            print(f"  Actual prefix:   {data.get('google_client_id', {}).get('prefix', 'N/A')}")

            print(f"\nuser_refresh_token: {'✓ MATCH' if user_token_match else '✗ MISMATCH'}")
            print(f"  Expected prefix: {expected_user_token_prefix}...")
            print(f"  Actual prefix:   {data.get('user_refresh_token', {}).get('prefix', 'N/A')}")

            print(f"\nagent_refresh_token: {'✓ MATCH' if agent_token_match else '✗ MISMATCH'}")
            print(f"  Expected prefix: {expected_agent_token_prefix}...")
            print(f"  Actual prefix:   {data.get('agent_refresh_token', {}).get('prefix', 'N/A')}")

            if client_id_match and user_token_match and agent_token_match:
                print(f"\n{'='*60}")
                print("✓ ALL CREDENTIALS MATCH! Railway should be working correctly.")
                print(f"{'='*60}")
            else:
                print(f"\n{'='*60}")
                print("✗ CREDENTIAL MISMATCH DETECTED!")
                print("  Railway environment variables need to be updated.")
                print("  Go to Railway dashboard and verify/update the env vars.")
                print(f"{'='*60}")

        else:
            print(f"Error response: {response.text}")

    except requests.exceptions.ConnectionError:
        print(f"ERROR: Could not connect to {railway_url}")
        print("  - Is Railway deployed?")
        print("  - Is the URL correct?")
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_railway_diagnostic.py <railway_url>")
        print("Example: python test_railway_diagnostic.py https://sabine-super-agent-production.up.railway.app")
        sys.exit(1)

    test_diagnostic(sys.argv[1])
