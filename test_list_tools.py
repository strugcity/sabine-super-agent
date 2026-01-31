"""
Debug tools/list request
"""
import httpx
import asyncio
import json

async def main():
    url = "http://localhost:8000/mcp"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # First initialize
        print("1. Initializing...")
        init_resp = await client.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test",
                        "version": "1.0.0"
                    }
                }
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )

        print(f"Initialize response: {init_resp.status_code}")
        print(f"Body: {init_resp.text}\n")

        # Then list tools
        print("2. Listing tools...")
        tools_resp = await client.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )

        print(f"Tools/list response: {tools_resp.status_code}")
        print(f"Body: {tools_resp.text}")

if __name__ == "__main__":
    asyncio.run(main())
