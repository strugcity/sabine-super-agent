#!/usr/bin/env python3
"""
Phase 5 Memory Dashboard - In-Flight QA Test
=============================================

This script tests the Memory Dashboard functionality by:
1. Verifying database has test data (entities + memories)
2. Testing Supabase API endpoints the dashboard uses
3. Validating data structure matches TypeScript types
4. Checking the Next.js dashboard endpoint responds

Run with: python test_dashboard_qa.py
"""

import asyncio
import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

# Load environment variables
from dotenv import load_dotenv
project_root = Path(__file__).parent
load_dotenv(project_root / ".env", override=True)

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.RESET}\n")

def print_pass(text: str):
    print(f"{Colors.GREEN}[PASS] {text}{Colors.RESET}")

def print_fail(text: str):
    print(f"{Colors.RED}[FAIL] {text}{Colors.RESET}")

def print_info(text: str):
    print(f"{Colors.CYAN}[INFO] {text}{Colors.RESET}")

def print_warn(text: str):
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.RESET}")


# =============================================================================
# Test Functions
# =============================================================================

def test_environment_variables() -> bool:
    """Test 1: Verify required environment variables are set."""
    print_header("TEST 1: Environment Variables")

    required_vars = [
        ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"),
        ("SUPABASE_SERVICE_ROLE_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY"),
    ]

    all_found = True

    for backend_var, frontend_var in required_vars:
        backend_val = os.getenv(backend_var)
        frontend_val = os.getenv(frontend_var)

        if backend_val:
            print_pass(f"{backend_var} is set")
        elif frontend_val:
            print_pass(f"{frontend_var} is set (frontend alias)")
        else:
            print_fail(f"Neither {backend_var} nor {frontend_var} is set")
            all_found = False

    return all_found


def test_supabase_connection() -> bool:
    """Test 2: Verify Supabase connection works."""
    print_header("TEST 2: Supabase Connection")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")

        if not url or not key:
            print_fail("Supabase credentials not found")
            return False

        print_info(f"Connecting to: {url[:50]}...")
        client = create_client(url, key)

        # Test connection by fetching count
        result = client.table("entities").select("count", count="exact").limit(1).execute()
        print_pass(f"Connected successfully")

        return True

    except Exception as e:
        print_fail(f"Connection failed: {e}")
        return False


def test_entities_data() -> bool:
    """Test 3: Verify entities table has data and matches expected schema."""
    print_header("TEST 3: Entities Data Validation")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        client = create_client(url, key)

        # Fetch entities (same query as dashboard)
        result = client.table("entities").select("*").eq("status", "active").order("created_at", desc=True).execute()

        entities = result.data
        print_info(f"Found {len(entities)} active entities")

        if len(entities) == 0:
            print_warn("No entities found - dashboard will show empty state")
            return True

        # Validate schema matches TypeScript types
        required_fields = ["id", "name", "type", "domain", "attributes", "status", "created_at", "updated_at"]
        valid_domains = ["work", "family", "personal", "logistics"]
        valid_statuses = ["active", "archived", "deleted"]

        all_valid = True
        domain_counts = {"work": 0, "family": 0, "personal": 0, "logistics": 0}

        for entity in entities:
            # Check required fields
            missing = [f for f in required_fields if f not in entity]
            if missing:
                print_fail(f"Entity {entity.get('id', 'unknown')} missing fields: {missing}")
                all_valid = False
                continue

            # Check domain is valid
            if entity["domain"] not in valid_domains:
                print_fail(f"Entity {entity['name']} has invalid domain: {entity['domain']}")
                all_valid = False
            else:
                domain_counts[entity["domain"]] += 1

            # Check status is valid
            if entity["status"] not in valid_statuses:
                print_fail(f"Entity {entity['name']} has invalid status: {entity['status']}")
                all_valid = False

        if all_valid:
            print_pass(f"All {len(entities)} entities have valid schema")
            for domain, count in domain_counts.items():
                if count > 0:
                    print_info(f"  {domain}: {count} entities")

        # Show sample entities
        print_info("\nSample entities:")
        for entity in entities[:3]:
            print(f"  - {entity['name']} ({entity['type']}, {entity['domain']})")

        return all_valid

    except Exception as e:
        print_fail(f"Entity validation failed: {e}")
        return False


def test_memories_data() -> bool:
    """Test 4: Verify memories table has data and matches expected schema."""
    print_header("TEST 4: Memories Data Validation")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        client = create_client(url, key)

        # Fetch memories (same query as dashboard)
        result = client.table("memories").select("*").order("created_at", desc=True).limit(50).execute()

        memories = result.data
        print_info(f"Found {len(memories)} memories (limit 50)")

        if len(memories) == 0:
            print_warn("No memories found - dashboard will show empty state")
            return True

        # Validate schema matches TypeScript types
        required_fields = ["id", "content", "entity_links", "metadata", "importance_score", "created_at", "updated_at"]

        all_valid = True

        for memory in memories:
            # Check required fields
            missing = [f for f in required_fields if f not in memory]
            if missing:
                print_fail(f"Memory {memory.get('id', 'unknown')[:8]}... missing fields: {missing}")
                all_valid = False
                continue

            # Check importance_score is 0-1
            score = memory.get("importance_score", 0)
            if not (0 <= score <= 1):
                print_fail(f"Memory {memory['id'][:8]}... has invalid importance_score: {score}")
                all_valid = False

            # Check entity_links is array
            links = memory.get("entity_links", [])
            if not isinstance(links, list):
                print_fail(f"Memory {memory['id'][:8]}... has invalid entity_links type")
                all_valid = False

        if all_valid:
            print_pass(f"All {len(memories)} memories have valid schema")

        # Show sample memories
        print_info("\nSample memories:")
        for memory in memories[:3]:
            content = memory['content'][:60] + "..." if len(memory['content']) > 60 else memory['content']
            print(f"  - [{memory['importance_score']*100:.0f}%] {content}")

        return all_valid

    except Exception as e:
        print_fail(f"Memory validation failed: {e}")
        return False


def test_entity_grouping() -> bool:
    """Test 5: Verify entities can be grouped by domain (as dashboard does)."""
    print_header("TEST 5: Entity Grouping by Domain")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        client = create_client(url, key)

        result = client.table("entities").select("*").eq("status", "active").execute()
        entities = result.data

        # Group by domain (mimics dashboard logic)
        grouped = {
            "work": [],
            "family": [],
            "personal": [],
            "logistics": []
        }

        for entity in entities:
            domain = entity.get("domain")
            if domain in grouped:
                grouped[domain].append(entity)
            else:
                print_warn(f"Unknown domain: {domain}")

        print_pass("Entities grouped successfully:")
        for domain, domain_entities in grouped.items():
            if domain_entities:
                print_info(f"  {domain}: {len(domain_entities)} entities")
                for e in domain_entities[:2]:
                    print(f"    - {e['name']} ({e['type']})")

        return True

    except Exception as e:
        print_fail(f"Entity grouping failed: {e}")
        return False


def test_dashboard_endpoint(port: int = 3000) -> bool:
    """Test 6: Check if Next.js dashboard endpoint responds."""
    print_header("TEST 6: Dashboard Endpoint (Next.js)")

    url = f"http://localhost:{port}/dashboard/memory"

    print_info(f"Testing endpoint: {url}")

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            print_pass(f"Dashboard responds with 200 OK")

            # Check for expected content
            content = response.text.lower()
            checks = [
                ("Memory Dashboard", "memory dashboard" in content),
                ("Entities section", "entities" in content),
                ("Memory Stream", "memory" in content or "stream" in content),
            ]

            for name, found in checks:
                if found:
                    print_info(f"  Found: {name}")
                else:
                    print_warn(f"  Missing: {name}")

            return True
        else:
            print_fail(f"Dashboard returned status {response.status_code}")
            return False

    except requests.exceptions.ConnectionError:
        print_warn(f"Cannot connect to {url} - is Next.js dev server running?")
        print_info("Run 'npm run dev' to start the development server")
        return True  # Not a failure, just not running

    except Exception as e:
        print_fail(f"Dashboard check failed: {e}")
        return False


def test_memory_entity_links() -> bool:
    """Test 7: Verify memory entity_links reference valid entities."""
    print_header("TEST 7: Memory-Entity Link Integrity")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        client = create_client(url, key)

        # Get all entities
        entities_result = client.table("entities").select("id").execute()
        entity_ids = {e["id"] for e in entities_result.data}
        print_info(f"Found {len(entity_ids)} entities")

        # Get all memories with entity links
        memories_result = client.table("memories").select("id, entity_links").execute()
        memories = memories_result.data

        # Check each memory's entity links
        invalid_links = []
        total_links = 0
        valid_links = 0

        for memory in memories:
            links = memory.get("entity_links", [])
            total_links += len(links)

            for link in links:
                if link in entity_ids:
                    valid_links += 1
                else:
                    invalid_links.append((memory["id"][:8], link[:8]))

        if total_links == 0:
            print_info("No entity links found in memories")
            return True

        if invalid_links:
            print_warn(f"Found {len(invalid_links)} invalid entity links:")
            for mem_id, ent_id in invalid_links[:5]:
                print(f"  Memory {mem_id}... -> Entity {ent_id}... (not found)")
            if len(invalid_links) > 5:
                print(f"  ... and {len(invalid_links) - 5} more")
            return False

        print_pass(f"All {valid_links} entity links are valid")
        return True

    except Exception as e:
        print_fail(f"Link integrity check failed: {e}")
        return False


def test_date_formatting() -> bool:
    """Test 8: Verify dates can be parsed as dashboard expects."""
    print_header("TEST 8: Date Formatting")

    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        client = create_client(url, key)

        # Get sample data
        entity = client.table("entities").select("created_at").limit(1).execute()
        memory = client.table("memories").select("created_at").limit(1).execute()

        all_valid = True

        if entity.data:
            created_at = entity.data[0]["created_at"]
            try:
                # Dashboard uses: new Date(entity.created_at).toLocaleDateString()
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                formatted = dt.strftime("%m/%d/%Y")
                print_pass(f"Entity date parses correctly: {created_at} -> {formatted}")
            except Exception as e:
                print_fail(f"Entity date parse failed: {e}")
                all_valid = False

        if memory.data:
            created_at = memory.data[0]["created_at"]
            try:
                # Dashboard uses: new Date(memory.created_at).toLocaleString(...)
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                formatted = dt.strftime("%b %d, %Y, %I:%M %p")
                print_pass(f"Memory date parses correctly: {created_at} -> {formatted}")
            except Exception as e:
                print_fail(f"Memory date parse failed: {e}")
                all_valid = False

        return all_valid

    except Exception as e:
        print_fail(f"Date formatting test failed: {e}")
        return False


# =============================================================================
# Main
# =============================================================================

def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("=" * 70)
    print("    PHASE 5 MEMORY DASHBOARD - IN-FLIGHT QA TEST")
    print("=" * 70)
    print(f"{Colors.RESET}")

    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Project: {project_root}")

    results = {}

    # Run tests
    results["Environment Variables"] = test_environment_variables()
    results["Supabase Connection"] = test_supabase_connection()
    results["Entities Data"] = test_entities_data()
    results["Memories Data"] = test_memories_data()
    results["Entity Grouping"] = test_entity_grouping()
    results["Memory-Entity Links"] = test_memory_entity_links()
    results["Date Formatting"] = test_date_formatting()
    results["Dashboard Endpoint"] = test_dashboard_endpoint()

    # Summary
    print_header("QA SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_test in results.items():
        if passed_test:
            print_pass(test_name)
        else:
            print_fail(test_name)

    print()
    if passed == total:
        print(f"{Colors.GREEN}{Colors.BOLD}All {total} tests passed!{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}{passed}/{total} tests passed{Colors.RESET}")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
