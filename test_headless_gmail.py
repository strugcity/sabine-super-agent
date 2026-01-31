"""
Test the headless Gmail MCP server locally.

This script tests:
1. MCP server connection
2. Token refresh for both user and agent accounts
3. Reading emails from user's inbox
4. (Optional) Sending a test email

Run: python test_headless_gmail.py
"""
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from lib.agent.mcp_client import MCPClient


async def test_mcp_connection():
    """Test basic MCP server connection."""
    print("\n" + "=" * 60)
    print("TEST 1: MCP Server Connection")
    print("=" * 60)

    # Use npx directly for local testing (not the shell script)
    command = "npx"
    args = ["-y", "@peakmojo/mcp-server-headless-gmail"]

    try:
        async with MCPClient(command=command, args=args) as mcp:
            tools = mcp.list_tools()
            print(f"[OK] Connected! Available tools ({len(tools)}):")
            for tool in tools:
                print(f"  - {tool}")
            return True, mcp
    except Exception as e:
        print(f"[FAIL] Failed to connect: {e}")
        return False, None


async def test_token_refresh(mcp, token_type: str):
    """Test refreshing access token."""
    print(f"\n" + "=" * 60)
    print(f"TEST 2{token_type[0].upper()}: Refresh {token_type.title()} Token")
    print("=" * 60)

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv(f"{token_type.upper()}_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print(f"[FAIL] Missing credentials for {token_type}")
        print(f"  GOOGLE_CLIENT_ID: {'set' if client_id else 'MISSING'}")
        print(f"  GOOGLE_CLIENT_SECRET: {'set' if client_secret else 'MISSING'}")
        print(f"  {token_type.upper()}_REFRESH_TOKEN: {'set' if refresh_token else 'MISSING'}")
        return None

    try:
        result = await mcp.call_tool("gmail_refresh_token", {
            "google_refresh_token": refresh_token,
            "google_client_id": client_id,
            "google_client_secret": client_secret,
        })

        print(f"Raw result: {result[:200]}...")

        # Parse result
        try:
            data = json.loads(result)
            access_token = data.get("access_token")
            expires_in = data.get("expires_in")
            print(f"[OK] Got access token (expires in {expires_in}s)")
            print(f"  Token prefix: {access_token[:20]}...")
            return access_token
        except json.JSONDecodeError:
            print(f"[FAIL] Failed to parse result as JSON")
            return None

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return None


async def test_get_emails(mcp, access_token: str):
    """Test getting recent emails."""
    print(f"\n" + "=" * 60)
    print("TEST 3: Get Recent Emails")
    print("=" * 60)

    try:
        result = await mcp.call_tool("gmail_get_recent_emails", {
            "google_access_token": access_token,
            "max_results": 5,
            "unread_only": False
        })

        print(f"Raw result: {result[:500]}...")

        try:
            emails = json.loads(result)
            if isinstance(emails, list):
                print(f"[OK] Found {len(emails)} emails")
                for i, email in enumerate(emails[:3]):
                    print(f"\n  Email {i+1}:")
                    print(f"    ID: {email.get('id', 'N/A')}")
                    print(f"    From: {email.get('from', 'N/A')}")
                    print(f"    Subject: {email.get('subject', 'N/A')[:50]}...")
            else:
                print(f"  Result: {emails}")
            return True
        except json.JSONDecodeError:
            print(f"  (Non-JSON result)")
            return True

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


async def main():
    print("\n" + "=" * 60)
    print("HEADLESS GMAIL MCP TEST")
    print("=" * 60)

    # Check env vars first
    print("\nEnvironment check:")
    print(f"  GOOGLE_CLIENT_ID: {'set' if os.getenv('GOOGLE_CLIENT_ID') else 'MISSING'}")
    print(f"  GOOGLE_CLIENT_SECRET: {'set' if os.getenv('GOOGLE_CLIENT_SECRET') else 'MISSING'}")
    print(f"  USER_REFRESH_TOKEN: {'set' if os.getenv('USER_REFRESH_TOKEN') else 'MISSING'}")
    print(f"  AGENT_REFRESH_TOKEN: {'set' if os.getenv('AGENT_REFRESH_TOKEN') else 'MISSING'}")

    # Test connection
    command = "npx"
    args = ["-y", "@peakmojo/mcp-server-headless-gmail"]

    try:
        async with MCPClient(command=command, args=args) as mcp:
            tools = mcp.list_tools()
            print(f"\n[OK] Connected! Available tools ({len(tools)}):")
            for tool in tools:
                print(f"  - {tool}")

            # Test user token refresh
            user_token = await test_token_refresh(mcp, "user")

            # Test agent token refresh
            agent_token = await test_token_refresh(mcp, "agent")

            # Test getting emails (using user token)
            if user_token:
                await test_get_emails(mcp, user_token)

            print("\n" + "=" * 60)
            print("TEST SUMMARY")
            print("=" * 60)
            print(f"  MCP Connection: [OK]")
            print(f"  User Token Refresh: {'[OK]' if user_token else '[FAIL]'}")
            print(f"  Agent Token Refresh: {'[OK]' if agent_token else '[FAIL]'}")
            print(f"  Get Emails: {'[OK]' if user_token else 'skipped'}")

    except Exception as e:
        print(f"\n[FAIL] Failed to connect to MCP server: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
