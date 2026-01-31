"""
Quick test to verify sabine@strugcity.com OAuth credentials work
"""
import httpx
import asyncio
import json

async def test_gmail_with_sabine():
    """Test Gmail access with sabine@strugcity.com credentials"""

    # MCP server endpoint
    mcp_url = "http://localhost:8000/mcp"

    print("Testing Gmail access with sabine@strugcity.com credentials...\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Initialize session
        init_response = await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {}
            },
            headers={"Accept": "application/json, text/event-stream"}
        )

        print(f"Initialize response: {init_response.status_code}")

        # Get session ID
        session_id = init_response.headers.get("mcp-session-id")
        print(f"Session ID: {session_id}\n")

        # Try to list Gmail labels (will show which account is authenticated)
        labels_response = await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "list_gmail_labels",
                    "arguments": {
                        "user_google_email": "sabine@strugcity.com"
                    }
                }
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id
            }
        )

        print(f"List labels response: {labels_response.status_code}")

        # Parse SSE response
        response_text = labels_response.text
        for line in response_text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    result = data['result']
                    print(f"\n✅ Successfully authenticated as sabine@strugcity.com!")
                    print(f"\nGmail labels found: {len(result.get('content', [{}])[0].get('text', '').split(',')) if result.get('content') else 0}")
                    if result.get('content'):
                        print(f"Sample labels: {result['content'][0]['text'][:200]}...")
                elif 'error' in data:
                    print(f"\n❌ Error: {data['error']}")

if __name__ == "__main__":
    asyncio.run(test_gmail_with_sabine())
