#!/usr/bin/env python3
"""
Prompt Caching Benchmark

Tests the new prompt caching implementation by comparing:
1. Direct API with caching (via /invoke/cached endpoint)
2. Standard LangGraph agent (via /invoke endpoint)

This benchmark demonstrates the performance improvements from caching.
"""

import asyncio
import httpx
import time
from dotenv import load_dotenv
from pathlib import Path

# Load environment
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

API_BASE_URL = "http://localhost:8001"
TEST_USER_ID = "cache-benchmark-user"


async def reset_cache_metrics():
    """Reset cache metrics before benchmark."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(f"{API_BASE_URL}/cache/reset")


async def get_cache_metrics():
    """Get current cache metrics."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{API_BASE_URL}/cache/metrics")
        return response.json().get("metrics", {})


async def invoke_cached(message: str, session_id: str) -> dict:
    """Call the cached invoke endpoint."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        start = time.time()
        response = await client.post(
            f"{API_BASE_URL}/invoke/cached",
            json={
                "message": message,
                "user_id": TEST_USER_ID,
                "session_id": session_id
            }
        )
        duration = (time.time() - start) * 1000

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "response": data.get("response", "")[:100],
                "duration_ms": duration,
                "cache_metrics": data.get("cache_metrics", {})
            }
        else:
            return {
                "success": False,
                "error": response.text[:200],
                "duration_ms": duration
            }


async def invoke_standard(message: str, session_id: str) -> dict:
    """Call the standard invoke endpoint."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        start = time.time()
        response = await client.post(
            f"{API_BASE_URL}/invoke",
            json={
                "message": message,
                "user_id": TEST_USER_ID,
                "session_id": session_id
            }
        )
        duration = (time.time() - start) * 1000

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "response": data.get("response", "")[:100],
                "duration_ms": duration
            }
        else:
            return {
                "success": False,
                "error": response.text[:200],
                "duration_ms": duration
            }


async def run_cached_benchmark():
    """Run benchmark using cached endpoint."""
    print("\n" + "="*60)
    print("CACHED ENDPOINT BENCHMARK (/invoke/cached)")
    print("="*60)

    # Reset metrics
    await reset_cache_metrics()

    questions = [
        "What tools do you have access to?",
        "What is your purpose?",
        "How can you help me with scheduling?"
    ]

    results = []
    session_id = f"cached-benchmark-{int(time.time())}"

    for i, question in enumerate(questions):
        print(f"\n--- Call {i+1} ---")
        print(f"Q: {question}")

        result = await invoke_cached(question, session_id)

        if result["success"]:
            cache = result.get("cache_metrics", {})
            cache_status = cache.get("status", "N/A")
            cache_read = cache.get("cache_read_tokens", 0)
            cache_create = cache.get("cache_creation_tokens", 0)

            print(f"A: {result['response']}...")
            print(f"Duration: {result['duration_ms']:.0f}ms")
            print(f"Cache: {cache_status} (read: {cache_read}, create: {cache_create})")

            results.append({
                "question": question,
                "duration_ms": result["duration_ms"],
                "cache_status": cache_status,
                "cache_read": cache_read,
                "cache_create": cache_create
            })
        else:
            print(f"ERROR: {result.get('error', 'Unknown error')}")
            results.append({
                "question": question,
                "error": result.get("error")
            })

        await asyncio.sleep(0.5)

    # Get final metrics
    final_metrics = await get_cache_metrics()

    print("\n--- CACHED BENCHMARK RESULTS ---")
    print(f"Total calls: {len(results)}")

    successful = [r for r in results if "duration_ms" in r]
    if successful:
        avg_duration = sum(r["duration_ms"] for r in successful) / len(successful)
        print(f"Average duration: {avg_duration:.0f}ms")

        cache_hits = sum(1 for r in successful if r.get("cache_status") == "HIT")
        print(f"Cache hits: {cache_hits}/{len(successful)}")

    print(f"\nFinal cache metrics: {final_metrics}")

    return results


async def run_standard_benchmark():
    """Run benchmark using standard endpoint."""
    print("\n" + "="*60)
    print("STANDARD ENDPOINT BENCHMARK (/invoke)")
    print("="*60)

    questions = [
        "What tools do you have access to?",
        "What is your purpose?",
        "How can you help me with scheduling?"
    ]

    results = []
    session_id = f"standard-benchmark-{int(time.time())}"

    for i, question in enumerate(questions):
        print(f"\n--- Call {i+1} ---")
        print(f"Q: {question}")

        result = await invoke_standard(question, session_id)

        if result["success"]:
            print(f"A: {result['response']}...")
            print(f"Duration: {result['duration_ms']:.0f}ms")

            results.append({
                "question": question,
                "duration_ms": result["duration_ms"]
            })
        else:
            print(f"ERROR: {result.get('error', 'Unknown error')}")
            results.append({
                "question": question,
                "error": result.get("error")
            })

        await asyncio.sleep(0.5)

    print("\n--- STANDARD BENCHMARK RESULTS ---")
    print(f"Total calls: {len(results)}")

    successful = [r for r in results if "duration_ms" in r]
    if successful:
        avg_duration = sum(r["duration_ms"] for r in successful) / len(successful)
        print(f"Average duration: {avg_duration:.0f}ms")

    return results


async def run_comparison():
    """Run both benchmarks and compare."""
    print("="*60)
    print("PROMPT CACHING BENCHMARK COMPARISON")
    print("="*60)

    # Run cached benchmark
    cached_results = await run_cached_benchmark()

    print("\n" + "-"*60)
    print("Waiting 2 seconds before standard benchmark...")
    await asyncio.sleep(2)

    # Run standard benchmark
    standard_results = await run_standard_benchmark()

    # Compare results
    print("\n" + "="*60)
    print("COMPARISON SUMMARY")
    print("="*60)

    cached_successful = [r for r in cached_results if "duration_ms" in r]
    standard_successful = [r for r in standard_results if "duration_ms" in r]

    if cached_successful and standard_successful:
        cached_avg = sum(r["duration_ms"] for r in cached_successful) / len(cached_successful)
        standard_avg = sum(r["duration_ms"] for r in standard_successful) / len(standard_successful)

        # First call comparison (cache creation vs standard)
        cached_first = cached_successful[0]["duration_ms"] if cached_successful else 0
        standard_first = standard_successful[0]["duration_ms"] if standard_successful else 0

        # Subsequent calls (cache hits vs standard)
        cached_subsequent = cached_successful[1:] if len(cached_successful) > 1 else []
        standard_subsequent = standard_successful[1:] if len(standard_successful) > 1 else []

        cached_subsequent_avg = sum(r["duration_ms"] for r in cached_subsequent) / len(cached_subsequent) if cached_subsequent else 0
        standard_subsequent_avg = sum(r["duration_ms"] for r in standard_subsequent) / len(standard_subsequent) if standard_subsequent else 0

        print(f"\nFirst call (cache creation vs standard):")
        print(f"  Cached:   {cached_first:.0f}ms")
        print(f"  Standard: {standard_first:.0f}ms")

        print(f"\nSubsequent calls (cache hits vs standard):")
        print(f"  Cached avg:   {cached_subsequent_avg:.0f}ms")
        print(f"  Standard avg: {standard_subsequent_avg:.0f}ms")

        if standard_subsequent_avg > 0 and cached_subsequent_avg > 0:
            speedup = standard_subsequent_avg / cached_subsequent_avg
            print(f"  Speedup: {speedup:.2f}x")

        print(f"\nOverall average:")
        print(f"  Cached:   {cached_avg:.0f}ms")
        print(f"  Standard: {standard_avg:.0f}ms")

        if standard_avg > 0:
            overall_speedup = standard_avg / cached_avg
            print(f"  Overall speedup: {overall_speedup:.2f}x")


async def main():
    import sys

    print("Prompt Caching Benchmark")
    print("========================\n")

    # Check server health
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{API_BASE_URL}/health")
            if response.status_code != 200:
                print(f"Server not healthy: {response.status_code}")
                return
            print(f"Server healthy: {response.json()}")
    except Exception as e:
        print(f"Cannot connect to server at {API_BASE_URL}: {e}")
        print("Please start the server first: python -m uvicorn lib.agent.server:app --port 8001")
        return

    # Parse arguments
    mode = sys.argv[1] if len(sys.argv) > 1 else "cached"

    if mode == "cached":
        await run_cached_benchmark()
    elif mode == "standard":
        await run_standard_benchmark()
    elif mode == "compare":
        await run_comparison()
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python test_caching_benchmark.py [cached|standard|compare]")


if __name__ == "__main__":
    asyncio.run(main())
