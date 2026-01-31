"""
End-to-end test of Gmail integration through the agent API
"""
import httpx
import asyncio
import json

async def main():
    api_url = "http://localhost:8001"

    # Test Gmail search request with email address
    request_data = {
        "user_id": "test-user",
        "message": "Search my Gmail (rknollmaier@gmail.com) for messages from the last week",
        "session_id": "test-session-2"
    }

    print("Sending request to agent API...")
    print(f"Request: {json.dumps(request_data, indent=2)}\n")

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{api_url}/invoke",
                json=request_data
            )

            print(f"Response status: {response.status_code}")
            print(f"Response body:\n{json.dumps(response.json(), indent=2)}")

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
