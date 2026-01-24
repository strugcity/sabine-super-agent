#!/usr/bin/env python3
"""
Interactive Anthropic API Tester

A simple REPL for testing and experimenting with the Anthropic API
and your super agent without email dependencies.

Usage:
    python test_api_interactive.py

Commands:
    /direct <message>    - Send directly to Anthropic API (bypasses agent)
    /agent <message>     - Send to super agent via /invoke endpoint
    /tools               - List available tools
    /health              - Check server health
    /cache               - Run prompt caching demo
    /thinking <message>  - Use extended thinking (requires Sonnet 4.5+)
    /model <name>        - Switch model (haiku, sonnet, opus)
    /help                - Show this help
    /quit                - Exit
"""

import asyncio
import httpx
import os
import time
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Default model
CURRENT_MODEL = "claude-3-haiku-20240307"

MODEL_MAP = {
    "haiku": "claude-3-haiku-20240307",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-5-20251101"
}


async def direct_api_call(message: str, model: str = None) -> dict:
    """Make a direct call to Anthropic API."""
    model = model or CURRENT_MODEL

    async with httpx.AsyncClient(timeout=60.0) as client:
        start = time.time()
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": message}]
            }
        )
        duration = (time.time() - start) * 1000

        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}

        data = response.json()
        return {
            "response": data.get("content", [{}])[0].get("text", ""),
            "model": model,
            "duration_ms": duration,
            "input_tokens": data.get("usage", {}).get("input_tokens", 0),
            "output_tokens": data.get("usage", {}).get("output_tokens", 0)
        }


async def agent_call(message: str) -> dict:
    """Call the super agent via /invoke endpoint."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        start = time.time()
        try:
            response = await client.post(
                f"{API_BASE_URL}/invoke",
                json={
                    "message": message,
                    "user_id": "test-interactive",
                    "session_id": f"interactive-{int(time.time())}"
                }
            )
            duration = (time.time() - start) * 1000

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}

            data = response.json()
            return {
                "response": data.get("response", "No response"),
                "duration_ms": duration,
                "tools_available": data.get("tools_available", 0),
                "success": data.get("success", False)
            }
        except httpx.ConnectError:
            return {"error": f"Cannot connect to {API_BASE_URL}. Is the server running?"}


async def list_tools() -> dict:
    """List available tools."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{API_BASE_URL}/tools")
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}
            return response.json()
        except httpx.ConnectError:
            return {"error": f"Cannot connect to {API_BASE_URL}"}


async def health_check() -> dict:
    """Check server health."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{API_BASE_URL}/health")
            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}"}
            return response.json()
        except httpx.ConnectError:
            return {"error": f"Cannot connect to {API_BASE_URL}"}


async def prompt_caching_demo() -> None:
    """Demonstrate prompt caching."""
    print("\n--- Prompt Caching Demo ---")
    print("Making 3 calls with the same cached context...")

    large_context = """
    <context>
    You are a family scheduling assistant. Here is the current schedule:
    - Monday: School 8am-3pm, Soccer 5pm
    - Tuesday: School 8am-3pm, Piano 4pm
    - Wednesday: School 8am-3pm, Homework help 4pm
    - Thursday: School 8am-3pm, Soccer 5pm
    - Friday: School 8am-3pm, Free day
    - Weekend: Varies by custody schedule

    Custody arrangement:
    - Parent A: Monday-Wednesday
    - Parent B: Thursday-Sunday
    - Exchanges at 6pm on transition days
    </context>
    """ * 5  # Repeat to ensure it's large enough for caching

    questions = [
        "What day is piano?",
        "When does custody switch to Parent B?",
        "What time is soccer?"
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, question in enumerate(questions):
            start = time.time()
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 256,
                    "system": [
                        {
                            "type": "text",
                            "text": large_context,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ],
                    "messages": [{"role": "user", "content": question}]
                }
            )
            duration = (time.time() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                usage = data.get("usage", {})
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_create = usage.get("cache_creation_input_tokens", 0)
                answer = data.get("content", [{}])[0].get("text", "")

                call_type = "CREATE" if cache_create > 0 else "READ" if cache_read > 0 else "NONE"
                print(f"\nCall {i+1} [{call_type}]: {question}")
                print(f"  Answer: {answer[:100]}")
                print(f"  Duration: {duration:.0f}ms | Cache: {cache_read} read, {cache_create} created")
            else:
                print(f"\nCall {i+1} FAILED: {response.status_code}")

            await asyncio.sleep(0.3)


async def extended_thinking_call(message: str) -> dict:
    """Call API with extended thinking enabled."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        start = time.time()
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-5-20250929",
                "max_tokens": 8000,
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 2000
                },
                "messages": [{"role": "user", "content": message}]
            }
        )
        duration = (time.time() - start) * 1000

        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}

        data = response.json()

        thinking = ""
        response_text = ""
        for block in data.get("content", []):
            if block.get("type") == "thinking":
                thinking = block.get("thinking", "")
            elif block.get("type") == "text":
                response_text = block.get("text", "")

        return {
            "thinking": thinking,
            "response": response_text,
            "duration_ms": duration,
            "usage": data.get("usage", {})
        }


def print_help():
    """Print help message."""
    print("""
Commands:
    /direct <message>    - Send directly to Anthropic API (bypasses agent)
    /agent <message>     - Send to super agent via /invoke endpoint
    /tools               - List available tools
    /health              - Check server health
    /cache               - Run prompt caching demo
    /thinking <message>  - Use extended thinking (requires Sonnet 4.5+)
    /model <name>        - Switch model (haiku, sonnet, opus)
    /help                - Show this help
    /quit                - Exit

Or just type a message to send it directly to the API.
    """)


async def main():
    global CURRENT_MODEL

    print("="*60)
    print("Interactive Anthropic API Tester")
    print("="*60)
    print(f"API Key: {'Configured' if ANTHROPIC_API_KEY else 'NOT SET!'}")
    print(f"Server: {API_BASE_URL}")
    print(f"Current Model: {CURRENT_MODEL}")
    print("\nType /help for commands or just enter a message.\n")

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/quit") or user_input.startswith("/exit"):
            print("Goodbye!")
            break

        elif user_input.startswith("/help"):
            print_help()

        elif user_input.startswith("/direct "):
            message = user_input[8:].strip()
            if message:
                print(f"Sending to API ({CURRENT_MODEL})...")
                result = await direct_api_call(message)
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(f"\nResponse ({result['duration_ms']:.0f}ms):")
                    print(result['response'])
                    print(f"\nTokens: {result['input_tokens']} in / {result['output_tokens']} out")

        elif user_input.startswith("/agent "):
            message = user_input[7:].strip()
            if message:
                print("Sending to super agent...")
                result = await agent_call(message)
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(f"\nResponse ({result['duration_ms']:.0f}ms):")
                    print(result['response'])
                    print(f"\nTools available: {result['tools_available']}")

        elif user_input.startswith("/tools"):
            print("Fetching tools...")
            result = await list_tools()
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                tools = result.get("tools", [])
                print(f"\nAvailable tools ({len(tools)}):")
                for tool in tools:
                    print(f"  - {tool.get('name', 'unnamed')}: {tool.get('description', '')[:60]}")

        elif user_input.startswith("/health"):
            print("Checking health...")
            result = await health_check()
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"\nServer Status:")
                for key, value in result.items():
                    print(f"  {key}: {value}")

        elif user_input.startswith("/cache"):
            await prompt_caching_demo()

        elif user_input.startswith("/thinking "):
            message = user_input[10:].strip()
            if message:
                print("Sending with extended thinking (Sonnet 4.5)...")
                result = await extended_thinking_call(message)
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    print(f"\nThinking ({result['duration_ms']:.0f}ms):")
                    print("-"*40)
                    print(result['thinking'][:500] + "..." if len(result['thinking']) > 500 else result['thinking'])
                    print("-"*40)
                    print("\nResponse:")
                    print(result['response'])

        elif user_input.startswith("/model "):
            model_name = user_input[7:].strip().lower()
            if model_name in MODEL_MAP:
                CURRENT_MODEL = MODEL_MAP[model_name]
                print(f"Switched to {CURRENT_MODEL}")
            else:
                print(f"Unknown model. Available: {', '.join(MODEL_MAP.keys())}")

        else:
            # Default: direct API call
            print(f"Sending to API ({CURRENT_MODEL})...")
            result = await direct_api_call(user_input)
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"\nResponse ({result['duration_ms']:.0f}ms):")
                print(result['response'])
                print(f"\nTokens: {result['input_tokens']} in / {result['output_tokens']} out")


if __name__ == "__main__":
    asyncio.run(main())
