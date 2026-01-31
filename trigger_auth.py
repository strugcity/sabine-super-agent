"""Trigger OAuth authentication for workspace-mcp using proper MCP protocol"""
import httpx
import json
import sys

MCP_URL = "http://localhost:8000/mcp"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}

def make_request(method: str, params: dict = None, req_id: int = 1):
    """Make an MCP JSON-RPC request"""
    body = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
    }
    if params:
        body["params"] = params
    return body

print("=" * 60)
print("Workspace-MCP OAuth Authentication Trigger")
print("=" * 60)
print()

client = httpx.Client(timeout=120.0)

try:
    # Step 1: Initialize session
    print("Step 1: Initializing MCP session...")
    init_request = make_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "auth-trigger", "version": "1.0.0"}
    })

    response = client.post(MCP_URL, json=init_request, headers=HEADERS)
    print(f"  Status: {response.status_code}")

    # Get session ID from response header
    session_id = response.headers.get("mcp-session-id")
    if not session_id:
        try:
            data = response.json()
            print(f"  Response: {json.dumps(data, indent=2)[:500]}")
        except:
            print(f"  Response: {response.text[:500]}")
        print("\nERROR: No session ID received.")
        sys.exit(1)

    print(f"  Session ID: {session_id}")
    HEADERS["mcp-session-id"] = session_id

    # Step 2: Send initialized notification
    print("\nStep 2: Sending initialized notification...")
    init_notification = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    }
    response = client.post(MCP_URL, json=init_notification, headers=HEADERS)
    print(f"  Status: {response.status_code}")

    # Step 3: List available tools to find correct parameter names
    print("\nStep 3: Listing available Gmail tools...")
    list_tools = make_request("tools/list", {}, req_id=2)
    response = client.post(MCP_URL, json=list_tools, headers=HEADERS)

    # Parse SSE response
    gmail_tool = None
    for line in response.text.split('\n'):
        if line.startswith('data: '):
            try:
                data = json.loads(line[6:])
                if 'result' in data and 'tools' in data['result']:
                    for tool in data['result']['tools']:
                        if 'gmail' in tool['name'].lower() and 'search' in tool['name'].lower():
                            gmail_tool = tool
                            print(f"  Found tool: {tool['name']}")
                            print(f"  Parameters: {json.dumps(tool.get('inputSchema', {}), indent=4)[:500]}")
                            break
            except:
                pass

    # Step 4: Call Gmail tool with correct parameters
    print("\nStep 4: Calling Gmail tool to trigger OAuth for rknollmaier@gmail.com...")
    print("  (A browser window should open for authentication)")
    print()

    # Use minimal parameters - just the email
    tool_request = make_request("tools/call", {
        "name": "search_gmail_messages",
        "arguments": {
            "user_google_email": "rknollmaier@gmail.com",
            "query": "is:inbox"
        }
    }, req_id=3)

    response = client.post(MCP_URL, json=tool_request, headers=HEADERS)
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.text[:1500]}")

    print()
    print("=" * 60)
    print("Check for new credentials at:")
    print("  C:\\Users\\rktra\\.google_workspace_mcp\\credentials\\rknollmaier@gmail.com.json")
    print("=" * 60)

except httpx.ConnectError:
    print("ERROR: Cannot connect to workspace-mcp at http://localhost:8000")
    print("Make sure workspace-mcp is running.")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    client.close()
