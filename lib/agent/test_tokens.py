"""
Quick token diagnostic script.
Run in Railway to see which tokens are being used.
"""
import os

def show_token_info():
    """Display token information without exposing full tokens."""

    print("=" * 60)
    print("TOKEN DIAGNOSTIC")
    print("=" * 60)

    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    user_token = os.getenv("USER_REFRESH_TOKEN", "")
    agent_token = os.getenv("AGENT_REFRESH_TOKEN", "")

    print(f"\nGOOGLE_CLIENT_ID:")
    if client_id:
        print(f"  First 20 chars: {client_id[:20]}...")
        print(f"  Length: {len(client_id)}")
    else:
        print("  NOT SET!")

    print(f"\nGOOGLE_CLIENT_SECRET:")
    if client_secret:
        print(f"  First 10 chars: {client_secret[:10]}...")
        print(f"  Length: {len(client_secret)}")
    else:
        print("  NOT SET!")

    print(f"\nUSER_REFRESH_TOKEN:")
    if user_token:
        print(f"  First 20 chars: {user_token[:20]}...")
        print(f"  Length: {len(user_token)}")
    else:
        print("  NOT SET!")

    print(f"\nAGENT_REFRESH_TOKEN:")
    if agent_token:
        print(f"  First 20 chars: {agent_token[:20]}...")
        print(f"  Length: {len(agent_token)}")
    else:
        print("  NOT SET!")

    # Check authorized emails
    auth_emails = os.getenv("GMAIL_AUTHORIZED_EMAILS", "")
    print(f"\nGMAIL_AUTHORIZED_EMAILS: {auth_emails}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    show_token_info()
