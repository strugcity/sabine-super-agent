"""
Trigger OAuth flow for workspace-mcp by sending an MCP tools/list request.
This script acts as a minimal MCP client to initiate the OAuth flow.
"""
import subprocess
import json
import sys

# Start workspace-mcp in stdio mode
process = subprocess.Popen(
    [
        "python", "-m", "uv", "tool", "run", "workspace-mcp",
        "--transport", "stdio",
        "--tools", "gmail",
        "--single-user"
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env={
        **subprocess.os.environ,
        "GOOGLE_OAUTH_CLIENT_ID": "1015418157789-gctjhmblg1s8hm6674kituke2ki0t7rj.apps.googleusercontent.com",
        "GOOGLE_OAUTH_CLIENT_SECRET": "GOCSPX-u9kF9cHhNHyYPh3wku-xskOe7Td",
        "OAUTHLIB_INSECURE_TRANSPORT": "1"
    }
)

# Send initialize request
init_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "oauth-trigger",
            "version": "1.0.0"
        }
    }
}

print("Sending initialize request...", file=sys.stderr)
process.stdin.write(json.dumps(init_request) + "\n")
process.stdin.flush()

# Read response
try:
    response = process.stdout.readline()
    print(f"Initialize response: {response}", file=sys.stderr)
except Exception as e:
    print(f"Error reading initialize response: {e}", file=sys.stderr)

# Send tools/list request (this should trigger OAuth)
tools_request = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
}

print("Sending tools/list request (this should trigger OAuth)...", file=sys.stderr)
process.stdin.write(json.dumps(tools_request) + "\n")
process.stdin.flush()

# Read response and stderr for OAuth URL
print("\n" + "="*80, file=sys.stderr)
print("Waiting for OAuth URL in stderr...", file=sys.stderr)
print("="*80 + "\n", file=sys.stderr)

# Read both stdout and stderr for a bit
import time
for i in range(30):  # Wait up to 30 seconds
    # Check stderr for OAuth URL
    line = process.stderr.readline()
    if line:
        print(f"[STDERR] {line.rstrip()}", file=sys.stderr)
        if "http" in line.lower() and ("authorize" in line.lower() or "oauth" in line.lower() or "accounts.google" in line.lower()):
            print("\n" + "!"*80, file=sys.stderr)
            print("FOUND OAUTH URL:", file=sys.stderr)
            print(line.strip(), file=sys.stderr)
            print("!"*80 + "\n", file=sys.stderr)

    # Check stdout for responses
    try:
        # Non-blocking read attempt
        import select
        if select.select([process.stdout], [], [], 0.1)[0]:
            stdout_line = process.stdout.readline()
            if stdout_line:
                print(f"[STDOUT] {stdout_line.rstrip()}", file=sys.stderr)
    except:
        pass

    time.sleep(1)

print("\nClosing process...", file=sys.stderr)
process.terminate()
process.wait(timeout=5)
