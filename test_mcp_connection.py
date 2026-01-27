#!/usr/bin/env python3
"""
Test script to validate MCP server connection.

Usage:
    python test_mcp_connection.py
    
This script tests the Stdio-based MCP client connection to workspace-mcp.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from lib.agent.mcp_client import get_mcp_tools, test_mcp_connection

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Test MCP connection and tool loading."""
    logger.info("=" * 70)
    logger.info("MCP Connection Test")
    logger.info("=" * 70)
    
    # Test 1: Check if workspace-mcp is available
    logger.info("\n[TEST 1] Testing workspace-mcp availability...")
    try:
        is_available = await test_mcp_connection()
        if is_available:
            logger.info("✓ workspace-mcp is available and responding")
        else:
            logger.error("✗ workspace-mcp is not responding")
            return False
    except Exception as e:
        logger.error(f"✗ Error testing connection: {e}")
        return False
    
    # Test 2: Load tools
    logger.info("\n[TEST 2] Loading tools from workspace-mcp...")
    try:
        tools = await get_mcp_tools()
        if tools:
            logger.info(f"✓ Successfully loaded {len(tools)} tools")
            logger.info("\nAvailable tools:")
            for i, tool in enumerate(tools, 1):
                logger.info(f"  {i}. {tool.name}: {tool.description[:60]}...")
            return True
        else:
            logger.warning("⚠ No tools were loaded")
            return False
    except Exception as e:
        logger.error(f"✗ Error loading tools: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
