"""
Example Usage - Personal Super Agent

This script demonstrates how to use the Personal Super Agent with:
- Local skills
- MCP integrations
- Deep context injection

Run this script to test the agent system:
    python lib/agent/example_usage.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.agent import (
    create_agent,
    run_agent,
    get_all_tools,
    load_deep_context,
    get_mcp_servers
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def demo_tool_loading():
    """Demonstrate loading tools from local skills and MCP servers."""
    print("\n" + "=" * 60)
    print("DEMO 1: Tool Loading")
    print("=" * 60)

    # Load all tools
    tools = await get_all_tools()

    print(f"\n✓ Loaded {len(tools)} tools total\n")

    print("Available tools:")
    for i, tool in enumerate(tools, 1):
        print(f"  {i}. {tool.name}")
        print(f"     {tool.description}")
        print()

    # Show MCP servers
    mcp_servers = get_mcp_servers()
    if mcp_servers:
        print(f"MCP Servers configured: {len(mcp_servers)}")
        for server in mcp_servers:
            print(f"  - {server}")
    else:
        print("No MCP servers configured (set MCP_SERVERS env var)")

    print()


async def demo_deep_context(user_id: str):
    """Demonstrate loading deep context for a user."""
    print("\n" + "=" * 60)
    print("DEMO 2: Deep Context Loading")
    print("=" * 60)

    # Load deep context
    context = await load_deep_context(user_id)

    print(f"\nLoaded deep context for user: {user_id}")
    print(f"  - Rules: {len(context.get('rules', []))}")
    print(f"  - Config settings: {len(context.get('user_config', {}))}")
    print(f"  - Recent memories: {len(context.get('recent_memories', []))}")

    custody_state = context.get('custody_state', {})
    current_period = custody_state.get('current_period')

    if current_period:
        print(f"\n  Current Custody Period:")
        print(f"    - Child: {current_period.get('child_name')}")
        print(f"    - With: {current_period.get('parent_with_custody')}")
        print(f"    - Dates: {current_period.get('start_date')} to {current_period.get('end_date')}")
    else:
        print(f"\n  No current custody period found")

    print()


async def demo_agent_creation(user_id: str, session_id: str):
    """Demonstrate creating an agent instance."""
    print("\n" + "=" * 60)
    print("DEMO 3: Agent Creation")
    print("=" * 60)

    print(f"\nCreating agent for user {user_id}...")

    try:
        agent, deep_context = await create_agent(user_id, session_id)
        print("✓ Agent created successfully!")
        print(f"  - Deep context loaded: {len(deep_context)} keys")
        print(f"  - User ID: {deep_context.get('user_id')}")
        print(f"  - Loaded at: {deep_context.get('loaded_at')}")
        print()

    except Exception as e:
        print(f"✗ Failed to create agent: {e}")
        print("  Make sure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set")
        print()


async def demo_agent_conversation(user_id: str, session_id: str):
    """Demonstrate a full agent conversation."""
    print("\n" + "=" * 60)
    print("DEMO 4: Agent Conversation")
    print("=" * 60)

    test_messages = [
        "Hello! Who are you?",
        "What tools do you have access to?",
        "What's on my custody schedule this week?"
    ]

    conversation_history = []

    for message in test_messages:
        print(f"\n👤 User: {message}")

        try:
            result = await run_agent(
                user_id=user_id,
                session_id=session_id,
                user_message=message,
                conversation_history=conversation_history
            )

            if result["success"]:
                response = result["response"]
                print(f"🤖 Agent: {response}")

                # Update conversation history
                conversation_history.append({"role": "user", "content": message})
                conversation_history.append({"role": "assistant", "content": response})

            else:
                print(f"✗ Error: {result.get('error')}")
                break

        except Exception as e:
            print(f"✗ Exception: {e}")
            break

    print()


async def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("Personal Super Agent - Example Usage")
    print("=" * 60)

    # Check environment
    print("\nEnvironment Check:")
    required_vars = [
        "ANTHROPIC_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY"
    ]

    missing_vars = []
    for var in required_vars:
        if os.getenv(var):
            print(f"  ✓ {var}")
        else:
            print(f"  ✗ {var} (missing)")
            missing_vars.append(var)

    if missing_vars:
        print(f"\n⚠️  Warning: Some environment variables are missing.")
        print("   Set them in .env file for full functionality")

    # Test user ID (you can replace with an actual user ID from your database)
    test_user_id = "00000000-0000-0000-0000-000000000000"
    test_session_id = "demo-session-001"

    # Run demos
    await demo_tool_loading()

    if not missing_vars:
        await demo_deep_context(test_user_id)
        await demo_agent_creation(test_user_id, test_session_id)

        # Uncomment to run full conversation demo
        # await demo_agent_conversation(test_user_id, test_session_id)
    else:
        print("\n⚠️  Skipping database-dependent demos due to missing credentials")

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Set up your .env file with all required credentials")
    print("  2. Add MCP server URLs to MCP_SERVERS environment variable")
    print("  3. Create test users in Supabase")
    print("  4. Run this script again to test full functionality")
    print()


if __name__ == "__main__":
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Run demos
    asyncio.run(main())
