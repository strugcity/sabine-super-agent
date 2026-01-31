"""
Test session-based communication
"""
import httpx
import asyncio

async def main():
    url = "http://localhost:8000/mcp"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Initialize and get session
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
                    "clientInfo": {"name": "test", "version": "1.0.0"}
                }
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )

        print(f"Status: {init_resp.status_code}")
        session_id = init_resp.headers.get("mcp-session-id")
        print(f"Session ID: {session_id}")
        print(f"Content-Type: {init_resp.headers.get('content-type')}")
        print(f"Response text:\n{init_resp.text[:500]}\n")

        # Now list tools with session
        print("2. Listing tools with session...")
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
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id
            }
        )

        print(f"Status: {tools_resp.status_code}")
        print(f"Content-Type: {tools_resp.headers.get('content-type')}")
        print(f"Response text:\n{tools_resp.text[:1000]}")

if __name__ == "__main__":
    asyncio.run(main())
