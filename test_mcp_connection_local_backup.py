"""
Test MCP connection to workspace-mcp server.
"""
import asyncio
import sys
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.agent.mcp_client import get_mcp_tools, test_mcp_connection

async def main():
    url = "http://localhost:8000/mcp"

    print(f"Testing connection to {url}...")
    is_connected = await test_mcp_connection(url)

    if is_connected:
        print("[OK] Connection successful!")
    else:
        print("[FAIL] Connection failed")
        return

    print(f"\nLoading tools from {url}...")
    tools = await get_mcp_tools(url, timeout=15)

    print(f"\n[OK] Successfully loaded {len(tools)} tools:")
    for i, tool in enumerate(tools, 1):
        print(f"  {i}. {tool.name}: {tool.description}")

if __name__ == "__main__":
    asyncio.run(main())
