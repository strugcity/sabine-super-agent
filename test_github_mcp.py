"""Quick test to verify GitHub MCP server connectivity."""
import asyncio
import os
import sys

# Add lib to path
sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))

from lib.agent.mcp_client import MCPClient, get_mcp_tools

async def test_github_mcp():
    """Test the GitHub MCP server."""
    # Use the local script path
    command = "./deploy/start-github-mcp.sh"
    
    print(f"Testing GitHub MCP server: {command}")
    print(f"GITHUB_TOKEN set: {'Yes' if os.getenv('GITHUB_TOKEN') else 'No'}")
    print(f"GITHUB_ACCESS_TOKEN set: {'Yes' if os.getenv('GITHUB_ACCESS_TOKEN') else 'No'}")
    
    try:
        tools = await get_mcp_tools(command=command, timeout=30)
        print(f"\nSuccess! Loaded {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:60]}...")
        return True
    except Exception as e:
        print(f"\nFailed to load GitHub MCP tools: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Set a test token if not already set
    if not os.getenv("GITHUB_TOKEN") and not os.getenv("GITHUB_ACCESS_TOKEN"):
        print("WARNING: No GitHub token set. Please set GITHUB_TOKEN environment variable.")
        sys.exit(1)
    
    result = asyncio.run(test_github_mcp())
    sys.exit(0 if result else 1)
