"""
Debug MCP connection to workspace-mcp server.
"""
import httpx
import asyncio
import json

async def main():
    url = "http://localhost:8000/mcp"

    async with httpx.AsyncClient(timeout=10.0) as client:
        print(f"Sending initialize request to {url}...")

        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }

        print(f"Request: {json.dumps(request_data, indent=2)}")

        try:
            response = await client.post(
                url,
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )

            print(f"\nResponse status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            print(f"Response body: {response.text}")

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
