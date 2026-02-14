#!/usr/bin/env python3
"""
Quick Redis connectivity verification script.

Usage:
    python scripts/verify_redis.py                          # uses REDIS_URL from .env
    python scripts/verify_redis.py redis://localhost:6379    # explicit URL
"""
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import os


def main() -> None:
    """Verify Redis connectivity and print diagnostics."""
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Mask password for display
    safe_url = url
    if "@" in url:
        pre, post = url.split("@", 1)
        if ":" in pre.split("//", 1)[-1]:
            safe_url = pre.rsplit(":", 1)[0] + ":****@" + post

    print(f"Connecting to: {safe_url}")
    print("-" * 50)

    try:
        import redis
    except ImportError:
        print("ERROR: 'redis' package not installed.")
        print("  Fix: pip install redis")
        sys.exit(1)

    try:
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=5)

        # Test 1: PING
        start = time.time()
        pong = client.ping()
        ping_ms = (time.time() - start) * 1000
        print(f"  PING:        {'PONG' if pong else 'FAILED'} ({ping_ms:.1f}ms)")

        # Test 2: SET/GET roundtrip
        start = time.time()
        client.set("sabine:health_check", "ok", ex=60)
        val = client.get("sabine:health_check")
        roundtrip_ms = (time.time() - start) * 1000
        print(f"  SET/GET:     {'OK' if val == 'ok' else 'FAILED'} ({roundtrip_ms:.1f}ms)")

        # Test 3: Server info
        info = client.info("server")
        print(f"  Redis ver:   {info.get('redis_version', '?')}")
        print(f"  OS:          {info.get('os', '?')}")

        # Test 4: Memory
        mem_info = client.info("memory")
        used_mb = mem_info.get("used_memory", 0) / 1024 / 1024
        print(f"  Memory used: {used_mb:.1f} MB")

        # Cleanup
        client.delete("sabine:health_check")

        print("-" * 50)
        print("Redis is READY for Sabine 2.0")

    except redis.ConnectionError as e:
        print(f"  CONNECTION FAILED: {e}")
        print("\nTroubleshooting:")
        print("  1. Is Redis running?")
        print("  2. Is REDIS_URL correct in your .env?")
        print("  3. Check firewall / network settings")
        sys.exit(1)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
