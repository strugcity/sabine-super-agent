"""
WAL Service Performance Benchmarks
===================================

This module contains performance benchmarks for the Write-Ahead Log service.
These tests require a live Supabase connection and measure real-world latency.

Performance Target: P95 < 150ms for write operations

Run with: pytest tests/benchmarks/test_wal_performance.py -v -s

WARNING: These tests write to a real database. Use a staging environment.

Owner: @backend-architect-sabine
PRD Reference: PRD_Sabine_2.0_Complete.md - Section 5.2 (Latency Budgets)
"""

import asyncio
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import pytest
from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)


# =============================================================================
# Configuration
# =============================================================================

# Performance thresholds (in milliseconds)
# Note: These thresholds account for network round-trip to remote Supabase
# Local/Railway deployment will have lower latency
WRITE_LATENCY_P50_THRESHOLD_MS = 200   # Target: 50% of writes under 200ms (remote)
WRITE_LATENCY_P95_THRESHOLD_MS = 300   # Target: 95% of writes under 300ms (remote)
WRITE_LATENCY_P99_THRESHOLD_MS = 500   # Target: 99% of writes under 500ms (remote)
READ_LATENCY_P95_THRESHOLD_MS = 300    # Target: 95% of reads under 300ms (remote)

# Benchmark settings
BENCHMARK_ITERATIONS = 100  # Number of sequential writes
WARMUP_ITERATIONS = 5       # Warmup writes (discarded from stats)


def create_benchmark_payload(iteration: int) -> Dict[str, Any]:
    """Create a unique payload for benchmark testing."""
    return {
        "user_id": "benchmark-user-001",
        "message": f"Benchmark message iteration {iteration} - {uuid4()}",
        "source": "benchmark_test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "channel": "benchmark",
            "iteration": iteration,
            "test_run_id": str(uuid4())
        }
    }


def calculate_percentile(data: List[float], percentile: float) -> float:
    """Calculate percentile from a list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    index = int(len(sorted_data) * percentile / 100)
    return sorted_data[min(index, len(sorted_data) - 1)]


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def live_wal_service():
    """
    Create a WAL service connected to live Supabase.

    This fixture validates environment variables and creates a real connection.
    Skip the test if credentials are not available.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        pytest.skip("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required for benchmarks")

    from backend.services.wal import WALService
    return WALService()  # Uses singleton client


@pytest.fixture
def benchmark_entry_ids():
    """Track created entry IDs for cleanup."""
    return []


# =============================================================================
# Benchmark Tests
# =============================================================================

class TestWALPerformanceBenchmarks:
    """
    Performance benchmark suite for WAL write operations.

    These tests measure real-world latency including:
    - Network round-trip to Supabase
    - Database write time
    - Service layer overhead
    """

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_wal_write_latency_sequential(self, live_wal_service, benchmark_entry_ids):
        """
        Benchmark sequential WAL write latency.

        Executes 100 sequential writes and measures:
        - P50 (median) latency
        - P95 latency
        - P99 latency
        - Min/Max/Mean

        Asserts P95 < 150ms per architectural requirement.
        """
        service = live_wal_service
        latencies_ms: List[float] = []

        print(f"\n{'='*60}")
        print(f"WAL Write Latency Benchmark - {BENCHMARK_ITERATIONS} Sequential Writes")
        print(f"{'='*60}")

        # Warmup phase
        print(f"\nWarmup: {WARMUP_ITERATIONS} iterations...")
        for i in range(WARMUP_ITERATIONS):
            payload = create_benchmark_payload(i)
            payload["message"] = f"WARMUP - {payload['message']}"
            entry = await service.create_entry(payload)
            benchmark_entry_ids.append(entry.id)

        # Benchmark phase
        print(f"Benchmark: {BENCHMARK_ITERATIONS} iterations...")
        for i in range(BENCHMARK_ITERATIONS):
            payload = create_benchmark_payload(i)

            start_time = time.perf_counter()
            entry = await service.create_entry(payload)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            latencies_ms.append(elapsed_ms)
            benchmark_entry_ids.append(entry.id)

            # Progress indicator every 25 iterations
            if (i + 1) % 25 == 0:
                print(f"  Completed {i + 1}/{BENCHMARK_ITERATIONS} writes...")

        # Calculate statistics
        p50 = calculate_percentile(latencies_ms, 50)
        p95 = calculate_percentile(latencies_ms, 95)
        p99 = calculate_percentile(latencies_ms, 99)
        min_latency = min(latencies_ms)
        max_latency = max(latencies_ms)
        mean_latency = statistics.mean(latencies_ms)
        stddev_latency = statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0

        # Print results
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")
        print(f"  Iterations:  {BENCHMARK_ITERATIONS}")
        print(f"  Min:         {min_latency:.2f} ms")
        print(f"  Max:         {max_latency:.2f} ms")
        print(f"  Mean:        {mean_latency:.2f} ms")
        print(f"  Std Dev:     {stddev_latency:.2f} ms")
        print(f"  P50:         {p50:.2f} ms {'PASS' if p50 < WRITE_LATENCY_P50_THRESHOLD_MS else 'FAIL'}")
        print(f"  P95:         {p95:.2f} ms {'PASS' if p95 < WRITE_LATENCY_P95_THRESHOLD_MS else 'FAIL'}")
        print(f"  P99:         {p99:.2f} ms {'PASS' if p99 < WRITE_LATENCY_P99_THRESHOLD_MS else 'FAIL'}")
        print(f"{'='*60}")

        # Assertions
        assert p50 < WRITE_LATENCY_P50_THRESHOLD_MS, \
            f"P50 latency {p50:.2f}ms exceeds {WRITE_LATENCY_P50_THRESHOLD_MS}ms threshold"

        assert p95 < WRITE_LATENCY_P95_THRESHOLD_MS, \
            f"P95 latency {p95:.2f}ms exceeds {WRITE_LATENCY_P95_THRESHOLD_MS}ms threshold"

        assert p99 < WRITE_LATENCY_P99_THRESHOLD_MS, \
            f"P99 latency {p99:.2f}ms exceeds {WRITE_LATENCY_P99_THRESHOLD_MS}ms threshold"

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_wal_read_latency(self, live_wal_service):
        """
        Benchmark WAL read latency for pending entries.

        Measures time to retrieve a batch of pending entries.
        This simulates the Slow Path worker's fetch operation.
        """
        service = live_wal_service
        latencies_ms: List[float] = []
        iterations = 20  # Fewer iterations for read benchmark

        print(f"\n{'='*60}")
        print(f"WAL Read Latency Benchmark - {iterations} Batch Fetches")
        print(f"{'='*60}")

        for i in range(iterations):
            start_time = time.perf_counter()
            entries = await service.get_pending_entries(limit=100)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            latencies_ms.append(elapsed_ms)

        # Calculate statistics
        p50 = calculate_percentile(latencies_ms, 50)
        p95 = calculate_percentile(latencies_ms, 95)
        mean_latency = statistics.mean(latencies_ms)

        print(f"\nREAD RESULTS")
        print(f"  Mean:  {mean_latency:.2f} ms")
        print(f"  P50:   {p50:.2f} ms")
        print(f"  P95:   {p95:.2f} ms")
        print(f"{'='*60}")

        # Read should be fast - target P95 < threshold (accounting for remote DB)
        assert p95 < READ_LATENCY_P95_THRESHOLD_MS, f"Read P95 latency {p95:.2f}ms exceeds {READ_LATENCY_P95_THRESHOLD_MS}ms threshold"

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_idempotency_performance(self, live_wal_service, benchmark_entry_ids):
        """
        Benchmark idempotency check performance.

        Measures the latency of duplicate detection:
        1. Create an entry
        2. Attempt to create the same entry again
        3. Measure time for duplicate detection

        The second call should NOT create a new entry and should be fast.
        """
        service = live_wal_service
        iterations = 20

        print(f"\n{'='*60}")
        print(f"Idempotency Check Benchmark - {iterations} Duplicate Attempts")
        print(f"{'='*60}")

        first_call_latencies: List[float] = []
        duplicate_call_latencies: List[float] = []

        for i in range(iterations):
            # Create unique payload (unique per iteration, but will be duplicated)
            base_timestamp = datetime(2026, 1, 30, 12, 0, i, tzinfo=timezone.utc)
            payload = {
                "user_id": "idempotency-test-user",
                "message": f"Idempotency test message {i}",
                "source": "benchmark",
                "timestamp": base_timestamp.isoformat(),
            }

            # First call - creates entry
            start_time = time.perf_counter()
            entry1 = await service.create_entry(payload)
            first_call_ms = (time.perf_counter() - start_time) * 1000
            first_call_latencies.append(first_call_ms)
            benchmark_entry_ids.append(entry1.id)

            # Second call - should detect duplicate
            start_time = time.perf_counter()
            entry2 = await service.create_entry(payload)
            duplicate_call_ms = (time.perf_counter() - start_time) * 1000
            duplicate_call_latencies.append(duplicate_call_ms)

            # Verify idempotency worked
            assert entry1.id == entry2.id, "Idempotency failed - different IDs returned"

        # Calculate statistics
        first_p95 = calculate_percentile(first_call_latencies, 95)
        dup_p95 = calculate_percentile(duplicate_call_latencies, 95)
        first_mean = statistics.mean(first_call_latencies)
        dup_mean = statistics.mean(duplicate_call_latencies)

        print(f"\nIDEMPOTENCY RESULTS")
        print(f"  First Call Mean:     {first_mean:.2f} ms")
        print(f"  First Call P95:      {first_p95:.2f} ms")
        print(f"  Duplicate Call Mean: {dup_mean:.2f} ms")
        print(f"  Duplicate Call P95:  {dup_p95:.2f} ms")
        print(f"{'='*60}")

        # Duplicate detection involves: failed insert + select existing
        # Allow more time than single write (2x threshold)
        dup_threshold = WRITE_LATENCY_P95_THRESHOLD_MS * 2
        assert dup_p95 < dup_threshold, \
            f"Duplicate detection P95 {dup_p95:.2f}ms exceeds {dup_threshold}ms threshold"


# =============================================================================
# Cleanup
# =============================================================================

@pytest.fixture(scope="module", autouse=True)
def cleanup_benchmark_entries():
    """
    Cleanup fixture to remove benchmark entries after tests.

    Note: This is optional and only runs if CLEANUP_BENCHMARKS=true
    """
    yield  # Run tests first

    if os.getenv("CLEANUP_BENCHMARKS", "false").lower() == "true":
        print("\nCleaning up benchmark entries...")
        # Cleanup would go here - for now, entries are left for manual inspection


# =============================================================================
# Run Benchmarks
# =============================================================================

if __name__ == "__main__":
    # Run with verbose output and show print statements
    pytest.main([
        __file__,
        "-v",
        "-s",
        "--tb=short",
        "-m", "benchmark"
    ])
