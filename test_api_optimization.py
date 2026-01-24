#!/usr/bin/env python3
"""
Anthropic API Testing & Optimization Suite

This script tests and benchmarks the Anthropic API independently of Gmail/email processes.
It provides multiple test modes:
1. Direct API calls (bypassing LangGraph)
2. Agent invocation via HTTP endpoints
3. Prompt caching benchmarks
4. Tool execution tests
5. Latency and token usage tracking

Usage:
    python test_api_optimization.py [test_name]

    Available tests:
    - direct_api       : Test direct Anthropic API calls
    - agent_invoke     : Test agent via /invoke endpoint
    - prompt_caching   : Benchmark prompt caching savings
    - tool_listing     : Test tool loading performance
    - streaming        : Test streaming responses
    - all              : Run all tests
"""

import asyncio
import httpx
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment variables from .env file in current directory
# Use override=True to override any empty env vars set in system
from pathlib import Path
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Test user/session IDs
TEST_USER_ID = "test-user-optimization"
TEST_SESSION_ID = f"test-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


@dataclass
class TestResult:
    """Container for test results."""
    test_name: str
    success: bool
    duration_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    error: Optional[str] = None
    response_preview: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def cache_hit_rate(self) -> float:
        total = self.input_tokens + self.cache_read_tokens
        if total == 0:
            return 0.0
        return (self.cache_read_tokens / total) * 100

    def __str__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        result = f"[{status}] {self.test_name} | {self.duration_ms:.0f}ms"
        if self.input_tokens > 0:
            result += f" | Tokens: {self.input_tokens}in/{self.output_tokens}out"
        if self.cache_read_tokens > 0:
            result += f" | Cache: {self.cache_hit_rate:.1f}%"
        if self.error:
            result += f" | Error: {self.error}"
        return result


class APITester:
    """Anthropic API testing and optimization utility."""

    def __init__(self):
        self.results: List[TestResult] = []
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=120.0)
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()

    # =========================================================================
    # Test 1: Direct Anthropic API Calls
    # =========================================================================
    async def test_direct_api(self) -> TestResult:
        """
        Test direct Anthropic API calls without LangGraph overhead.
        This establishes a baseline for API performance.
        """
        print("\n" + "="*60)
        print("TEST: Direct Anthropic API Call")
        print("="*60)

        if not ANTHROPIC_API_KEY:
            return TestResult(
                test_name="direct_api",
                success=False,
                duration_ms=0,
                error="ANTHROPIC_API_KEY not set"
            )

        start_time = time.time()

        try:
            response = await self.client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 256,
                    "messages": [
                        {
                            "role": "user",
                            "content": "What is 2 + 2? Reply with just the number."
                        }
                    ]
                }
            )

            duration_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                return TestResult(
                    test_name="direct_api",
                    success=False,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()
            usage = data.get("usage", {})

            result = TestResult(
                test_name="direct_api",
                success=True,
                duration_ms=duration_ms,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                response_preview=data.get("content", [{}])[0].get("text", "")[:100]
            )

            print(f"Response: {result.response_preview}")
            print(f"Duration: {duration_ms:.0f}ms")
            print(f"Tokens: {result.input_tokens} in / {result.output_tokens} out")

            return result

        except Exception as e:
            return TestResult(
                test_name="direct_api",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )

    # =========================================================================
    # Test 2: Agent Invocation via HTTP
    # =========================================================================
    async def test_agent_invoke(self, message: str = "What tools do you have access to?") -> TestResult:
        """
        Test agent invocation via the /invoke HTTP endpoint.
        This tests the full LangGraph agent pipeline.
        """
        print("\n" + "="*60)
        print("TEST: Agent Invoke Endpoint")
        print("="*60)

        start_time = time.time()

        try:
            response = await self.client.post(
                f"{API_BASE_URL}/invoke",
                json={
                    "message": message,
                    "user_id": TEST_USER_ID,
                    "session_id": TEST_SESSION_ID
                }
            )

            duration_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                return TestResult(
                    test_name="agent_invoke",
                    success=False,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()

            result = TestResult(
                test_name="agent_invoke",
                success=data.get("success", False),
                duration_ms=duration_ms,
                response_preview=data.get("response", "")[:200],
                metadata={
                    "tools_available": data.get("tools_available", 0),
                    "deep_context_loaded": data.get("deep_context_loaded", False)
                }
            )

            print(f"Response preview: {result.response_preview[:100]}...")
            print(f"Duration: {duration_ms:.0f}ms")
            print(f"Tools available: {result.metadata.get('tools_available', 'N/A')}")

            return result

        except httpx.ConnectError:
            return TestResult(
                test_name="agent_invoke",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=f"Cannot connect to {API_BASE_URL}. Is the server running?"
            )
        except Exception as e:
            return TestResult(
                test_name="agent_invoke",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )

    # =========================================================================
    # Test 3: Prompt Caching Benchmark
    # =========================================================================
    async def test_prompt_caching(self) -> List[TestResult]:
        """
        Benchmark prompt caching by making multiple requests with the same context.

        This demonstrates the performance gains from caching:
        - First call: Creates cache (normal processing time)
        - Second call: Reads from cache (should be faster)
        """
        print("\n" + "="*60)
        print("TEST: Prompt Caching Benchmark")
        print("="*60)

        if not ANTHROPIC_API_KEY:
            return [TestResult(
                test_name="prompt_caching",
                success=False,
                duration_ms=0,
                error="ANTHROPIC_API_KEY not set"
            )]

        results = []

        # Large static context to cache (simulating user rules, custody schedule, etc.)
        large_context = """
        <user_profile>
        You are helping a parent manage their family schedule and communications.

        CUSTODY SCHEDULE:
        - Monday-Wednesday: Child with Parent A
        - Thursday-Sunday: Child with Parent B
        - Holiday exceptions apply per custody agreement
        - School pickup: 3:15 PM on custodial days
        - Soccer practice: Tuesdays and Thursdays at 5 PM

        USER RULES:
        1. Always check custody schedule before confirming any plans
        2. Prioritize messages from school and medical providers
        3. Auto-respond to routine inquiries with standard templates
        4. Flag any scheduling conflicts immediately
        5. Track all expenses related to child activities

        USER PREFERENCES:
        - Communication style: Professional but friendly
        - Timezone: America/Los_Angeles
        - Notification preferences: SMS for urgent, email for routine
        - Calendar integration: Google Calendar
        - Preferred response length: Concise
        </user_profile>

        <additional_context>
        Recent important events:
        - Dental appointment scheduled for next Tuesday
        - School conference on the 15th
        - Birthday party invitation pending response
        - Soccer registration due by Friday
        </additional_context>
        """ * 3  # Repeat to make it larger (needs 1024+ tokens for caching)

        # Questions to ask
        questions = [
            "What day does the child have soccer practice?",
            "When is the dental appointment?",
            "What is the school pickup time?"
        ]

        for i, question in enumerate(questions):
            call_type = "cache_creation" if i == 0 else f"cache_read_{i}"
            print(f"\n--- Call {i+1}: {call_type} ---")

            start_time = time.time()

            try:
                # Use cache_control on the large context
                response = await self.client.post(
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
                        "messages": [
                            {
                                "role": "user",
                                "content": question
                            }
                        ]
                    }
                )

                duration_ms = (time.time() - start_time) * 1000

                if response.status_code != 200:
                    results.append(TestResult(
                        test_name=f"prompt_caching_{call_type}",
                        success=False,
                        duration_ms=duration_ms,
                        error=f"HTTP {response.status_code}: {response.text[:200]}"
                    ))
                    continue

                data = response.json()
                usage = data.get("usage", {})

                result = TestResult(
                    test_name=f"prompt_caching_{call_type}",
                    success=True,
                    duration_ms=duration_ms,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    response_preview=data.get("content", [{}])[0].get("text", "")[:100]
                )

                print(f"Question: {question}")
                print(f"Response: {result.response_preview}")
                print(f"Duration: {duration_ms:.0f}ms")
                print(f"Input tokens: {result.input_tokens}")
                print(f"Cache read tokens: {result.cache_read_tokens}")
                print(f"Cache creation tokens: {result.cache_creation_tokens}")
                print(f"Cache hit rate: {result.cache_hit_rate:.1f}%")

                results.append(result)

                # Brief pause between calls
                await asyncio.sleep(0.5)

            except Exception as e:
                results.append(TestResult(
                    test_name=f"prompt_caching_{call_type}",
                    success=False,
                    duration_ms=(time.time() - start_time) * 1000,
                    error=str(e)
                ))

        # Summary
        if len(results) >= 2:
            first_call = results[0]
            second_call = results[1]
            if first_call.success and second_call.success:
                speedup = first_call.duration_ms / second_call.duration_ms if second_call.duration_ms > 0 else 0
                print(f"\n--- CACHING SUMMARY ---")
                print(f"First call (cache creation): {first_call.duration_ms:.0f}ms")
                print(f"Second call (cache read): {second_call.duration_ms:.0f}ms")
                print(f"Speedup: {speedup:.2f}x")
                print(f"Cache hit rate: {second_call.cache_hit_rate:.1f}%")

        return results

    # =========================================================================
    # Test 4: Tool Listing Performance
    # =========================================================================
    async def test_tool_listing(self) -> TestResult:
        """
        Test tool loading performance via the /tools endpoint.
        """
        print("\n" + "="*60)
        print("TEST: Tool Listing Performance")
        print("="*60)

        start_time = time.time()

        try:
            response = await self.client.get(f"{API_BASE_URL}/tools")
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                return TestResult(
                    test_name="tool_listing",
                    success=False,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}"
                )

            data = response.json()
            tools = data.get("tools", [])

            print(f"Tools loaded: {len(tools)}")
            print(f"Duration: {duration_ms:.0f}ms")
            for tool in tools[:5]:
                print(f"  - {tool.get('name', 'unnamed')}")
            if len(tools) > 5:
                print(f"  ... and {len(tools) - 5} more")

            return TestResult(
                test_name="tool_listing",
                success=True,
                duration_ms=duration_ms,
                metadata={"tool_count": len(tools), "tools": [t.get("name") for t in tools]}
            )

        except httpx.ConnectError:
            return TestResult(
                test_name="tool_listing",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=f"Cannot connect to {API_BASE_URL}"
            )
        except Exception as e:
            return TestResult(
                test_name="tool_listing",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )

    # =========================================================================
    # Test 5: Health Check
    # =========================================================================
    async def test_health(self) -> TestResult:
        """
        Test server health and connectivity.
        """
        print("\n" + "="*60)
        print("TEST: Health Check")
        print("="*60)

        start_time = time.time()

        try:
            response = await self.client.get(f"{API_BASE_URL}/health")
            duration_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                return TestResult(
                    test_name="health_check",
                    success=False,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}"
                )

            data = response.json()
            print(f"Status: {data.get('status', 'unknown')}")
            print(f"Version: {data.get('version', 'unknown')}")
            print(f"Tools loaded: {data.get('tools_loaded', 'unknown')}")
            print(f"Database connected: {data.get('database_connected', 'unknown')}")
            print(f"Duration: {duration_ms:.0f}ms")

            return TestResult(
                test_name="health_check",
                success=data.get("status") == "healthy",
                duration_ms=duration_ms,
                metadata=data
            )

        except httpx.ConnectError:
            return TestResult(
                test_name="health_check",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=f"Cannot connect to {API_BASE_URL}. Is the server running?"
            )
        except Exception as e:
            return TestResult(
                test_name="health_check",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )

    # =========================================================================
    # Test 6: Multi-turn Conversation
    # =========================================================================
    async def test_conversation(self) -> List[TestResult]:
        """
        Test multi-turn conversation to verify context retention.
        """
        print("\n" + "="*60)
        print("TEST: Multi-turn Conversation")
        print("="*60)

        results = []
        conversation_history = []

        messages = [
            "My name is Alex. Please remember that.",
            "What is my name?",
            "What tools can you use to help me?"
        ]

        for i, message in enumerate(messages):
            print(f"\n--- Turn {i+1} ---")
            print(f"User: {message}")

            start_time = time.time()

            try:
                response = await self.client.post(
                    f"{API_BASE_URL}/invoke",
                    json={
                        "message": message,
                        "user_id": TEST_USER_ID,
                        "session_id": TEST_SESSION_ID,
                        "conversation_history": conversation_history
                    }
                )

                duration_ms = (time.time() - start_time) * 1000

                if response.status_code != 200:
                    results.append(TestResult(
                        test_name=f"conversation_turn_{i+1}",
                        success=False,
                        duration_ms=duration_ms,
                        error=f"HTTP {response.status_code}"
                    ))
                    continue

                data = response.json()
                agent_response = data.get("response", "")

                # Update conversation history
                conversation_history.append({"role": "user", "content": message})
                conversation_history.append({"role": "assistant", "content": agent_response})

                print(f"Agent: {agent_response[:150]}...")
                print(f"Duration: {duration_ms:.0f}ms")

                results.append(TestResult(
                    test_name=f"conversation_turn_{i+1}",
                    success=data.get("success", False),
                    duration_ms=duration_ms,
                    response_preview=agent_response[:100]
                ))

            except Exception as e:
                results.append(TestResult(
                    test_name=f"conversation_turn_{i+1}",
                    success=False,
                    duration_ms=(time.time() - start_time) * 1000,
                    error=str(e)
                ))

        return results

    # =========================================================================
    # Test 7: Direct API with Extended Thinking
    # =========================================================================
    async def test_extended_thinking(self) -> TestResult:
        """
        Test extended thinking capability for complex reasoning.
        Note: Extended thinking requires claude-sonnet-4-5 or claude-opus models.
        """
        print("\n" + "="*60)
        print("TEST: Extended Thinking")
        print("="*60)

        if not ANTHROPIC_API_KEY:
            return TestResult(
                test_name="extended_thinking",
                success=False,
                duration_ms=0,
                error="ANTHROPIC_API_KEY not set"
            )

        start_time = time.time()

        try:
            # Note: Extended thinking requires specific models
            response = await self.client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-5-20250929",  # Required for extended thinking
                    "max_tokens": 8000,
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": 2000
                    },
                    "messages": [
                        {
                            "role": "user",
                            "content": "A parent has custody Monday-Wednesday. Their child has soccer Tuesday and Thursday. The other parent wants to take the child to a Saturday birthday party but needs to pick up early on Friday. Analyze the scheduling implications."
                        }
                    ]
                }
            )

            duration_ms = (time.time() - start_time) * 1000

            if response.status_code != 200:
                error_msg = response.text[:300]
                # Check if it's a model access issue
                if "model" in error_msg.lower() or "not found" in error_msg.lower():
                    error_msg = "Extended thinking requires claude-sonnet-4-5 or claude-opus model access. " + error_msg
                return TestResult(
                    test_name="extended_thinking",
                    success=False,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}: {error_msg}"
                )

            data = response.json()
            usage = data.get("usage", {})

            # Extract thinking and response
            thinking_content = ""
            response_content = ""
            for block in data.get("content", []):
                if block.get("type") == "thinking":
                    thinking_content = block.get("thinking", "")[:200]
                elif block.get("type") == "text":
                    response_content = block.get("text", "")[:200]

            print(f"Thinking preview: {thinking_content}...")
            print(f"Response preview: {response_content}...")
            print(f"Duration: {duration_ms:.0f}ms")
            print(f"Tokens: {usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out")

            return TestResult(
                test_name="extended_thinking",
                success=True,
                duration_ms=duration_ms,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                response_preview=response_content,
                metadata={"thinking_preview": thinking_content}
            )

        except Exception as e:
            return TestResult(
                test_name="extended_thinking",
                success=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )

    # =========================================================================
    # Run All Tests
    # =========================================================================
    async def run_all_tests(self) -> List[TestResult]:
        """Run all available tests."""
        all_results = []

        # Health check first
        result = await self.test_health()
        all_results.append(result)
        self.results.append(result)

        # Direct API test
        result = await self.test_direct_api()
        all_results.append(result)
        self.results.append(result)

        # Only run server-dependent tests if health check passed
        if all_results[0].success:
            # Tool listing
            result = await self.test_tool_listing()
            all_results.append(result)
            self.results.append(result)

            # Agent invocation
            result = await self.test_agent_invoke()
            all_results.append(result)
            self.results.append(result)

            # Multi-turn conversation
            conv_results = await self.test_conversation()
            all_results.extend(conv_results)
            self.results.extend(conv_results)

        # Prompt caching (direct API)
        cache_results = await self.test_prompt_caching()
        all_results.extend(cache_results)
        self.results.extend(cache_results)

        # Extended thinking (may fail if model not available)
        result = await self.test_extended_thinking()
        all_results.append(result)
        self.results.append(result)

        return all_results

    def print_summary(self):
        """Print a summary of all test results."""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)

        passed = sum(1 for r in self.results if r.success)
        failed = sum(1 for r in self.results if not r.success)
        total_duration = sum(r.duration_ms for r in self.results)

        for result in self.results:
            print(result)

        print("-"*60)
        print(f"Total: {len(self.results)} tests | {passed} passed | {failed} failed")
        print(f"Total duration: {total_duration:.0f}ms ({total_duration/1000:.1f}s)")

        # Token summary
        total_input = sum(r.input_tokens for r in self.results)
        total_output = sum(r.output_tokens for r in self.results)
        total_cache_read = sum(r.cache_read_tokens for r in self.results)

        if total_input > 0:
            print(f"Total tokens: {total_input} input / {total_output} output")
            if total_cache_read > 0:
                print(f"Tokens from cache: {total_cache_read} ({total_cache_read/(total_input+total_cache_read)*100:.1f}%)")


async def main():
    """Main entry point."""
    import sys

    print("="*60)
    print("ANTHROPIC API TESTING & OPTIMIZATION SUITE")
    print("="*60)
    print(f"API Base URL: {API_BASE_URL}")
    print(f"API Key configured: {'Yes' if ANTHROPIC_API_KEY else 'No'}")
    print(f"Test Session: {TEST_SESSION_ID}")

    # Determine which test to run
    test_name = sys.argv[1] if len(sys.argv) > 1 else "all"

    async with APITester() as tester:
        if test_name == "direct_api":
            await tester.test_direct_api()
        elif test_name == "agent_invoke":
            await tester.test_agent_invoke()
        elif test_name == "prompt_caching":
            await tester.test_prompt_caching()
        elif test_name == "tool_listing":
            await tester.test_tool_listing()
        elif test_name == "health":
            await tester.test_health()
        elif test_name == "conversation":
            await tester.test_conversation()
        elif test_name == "extended_thinking":
            await tester.test_extended_thinking()
        elif test_name == "all":
            await tester.run_all_tests()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests: direct_api, agent_invoke, prompt_caching, tool_listing, health, conversation, extended_thinking, all")
            return

        tester.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
