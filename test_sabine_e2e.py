"""
End-to-end test of Gmail integration with sabine@strugcity.com
"""
import httpx
import asyncio
import json

async def main():
    api_url = "http://localhost:8001"

    # Test Gmail send from sabine@strugcity.com
    request_data = {
        "user_id": "test-user",
        "message": "Send a test email from sabine@strugcity.com to rknollmaier@gmail.com with subject 'Test from Sabine' and body 'This is a test email from your assistant Sabine at Strug City.'",
        "session_id": "test-sabine-session"
    }

    print("Sending test email request to agent API...")
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
