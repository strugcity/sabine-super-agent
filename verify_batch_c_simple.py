#!/usr/bin/env python3
"""
Verification Script for Batch C: Memory Role Tagging + Filtered Retrieval
(File-based verification - no module imports needed)
"""

import sys
import os
import re

print("=" * 70)
print("BATCH C VERIFICATION - File-Based Checks")
print("=" * 70)

all_passed = True

# Test 1: Check ingest_user_message signature
print("\n" + "=" * 70)
print("TEST 1: Verify ingest_user_message() has role parameter")
print("=" * 70)

with open("lib/agent/memory.py", 'r') as f:
    memory_content = f.read()

# Look for the function signature
pattern = r'async def ingest_user_message\([^)]*role\s*:\s*str\s*=\s*"assistant"[^)]*\)'
if re.search(pattern, memory_content, re.DOTALL):
    print("✓ PASS: ingest_user_message() has role: str = 'assistant' parameter")
else:
    print("❌ FAIL: ingest_user_message() signature doesn't have role parameter with default")
    all_passed = False

# Check that role is stored in metadata
if '"role": role' in memory_content or "'role': role" in memory_content:
    print("✓ PASS: role is stored in metadata dict")
else:
    print("❌ FAIL: role is not stored in metadata dict")
    all_passed = False

# Test 2: Check retrieve_context signature
print("\n" + "=" * 70)
print("TEST 2: Verify retrieve_context() has role_filter parameter")
print("=" * 70)

with open("lib/agent/retrieval.py", 'r') as f:
    retrieval_content = f.read()

# Look for the function signature
pattern = r'async def retrieve_context\([^)]*role_filter\s*:\s*str\s*=\s*"assistant"[^)]*\)'
if re.search(pattern, retrieval_content, re.DOTALL):
    print("✓ PASS: retrieve_context() has role_filter: str = 'assistant' parameter")
else:
    print("❌ FAIL: retrieve_context() signature doesn't have role_filter parameter with default")
    all_passed = False

# Check that role_filter is passed to search_similar_memories
if 'role_filter=role_filter' in retrieval_content:
    print("✓ PASS: role_filter is passed to search_similar_memories()")
else:
    print("❌ FAIL: role_filter is not passed to search_similar_memories()")
    all_passed = False

# Test 3: Check search_similar_memories signature
print("\n" + "=" * 70)
print("TEST 3: Verify search_similar_memories() has role_filter parameter")
print("=" * 70)

# Look for the function signature
pattern = r'async def search_similar_memories\([^)]*role_filter\s*:[^)]*\)'
if re.search(pattern, retrieval_content, re.DOTALL):
    print("✓ PASS: search_similar_memories() has role_filter parameter")
else:
    print("❌ FAIL: search_similar_memories() signature doesn't have role_filter parameter")
    all_passed = False

# Check that role_filter is passed to RPC
if '"role_filter": role_filter' in retrieval_content or "'role_filter': role_filter" in retrieval_content:
    print("✓ PASS: role_filter is passed to match_memories RPC call")
else:
    print("❌ FAIL: role_filter is not passed to match_memories RPC call")
    all_passed = False

# Test 4: Check SQL migration exists
print("\n" + "=" * 70)
print("TEST 4: Verify SQL migration file exists and has correct content")
print("=" * 70)

migration_file = "supabase/migrations/20260207170000_add_role_filter_to_match_memories.sql"

if not os.path.exists(migration_file):
    print(f"❌ FAIL: Migration file not found: {migration_file}")
    all_passed = False
else:
    print(f"✓ PASS: Migration file exists: {migration_file}")
    
    with open(migration_file, 'r') as f:
        migration_content = f.read()
    
    required_patterns = [
        ("role_filter parameter", "role_filter text DEFAULT NULL"),
        ("NULL check", "role_filter IS NULL OR"),
        ("Role match", "metadata->>'role' = role_filter"),
        ("Legacy support", "metadata->>'role' IS NULL")
    ]
    
    for name, pattern in required_patterns:
        if pattern in migration_content:
            print(f"✓ PASS: {name} found in migration")
        else:
            print(f"❌ FAIL: {name} not found in migration")
            all_passed = False

# Test 5: Check caller updates
print("\n" + "=" * 70)
print("TEST 5: Verify callers pass role parameter")
print("=" * 70)

# Check sabine.py router
with open("lib/agent/routers/sabine.py", 'r') as f:
    sabine_content = f.read()

if 'role="assistant"' in sabine_content:
    print("✓ PASS: sabine.py passes role='assistant'")
else:
    print("❌ FAIL: sabine.py does not pass role='assistant'")
    all_passed = False

# Check memory.py router
with open("lib/agent/routers/memory.py", 'r') as f:
    memory_router_content = f.read()

count = memory_router_content.count('role="assistant"')
if count >= 2:  # Should have at least 2 calls (ingest endpoint + file upload)
    print(f"✓ PASS: memory.py router passes role='assistant' ({count} occurrences)")
else:
    print(f"❌ FAIL: memory.py router has {count} occurrences of role='assistant', expected at least 2")
    all_passed = False

# Test 6: Verify Python syntax
print("\n" + "=" * 70)
print("TEST 6: Verify Python syntax for modified files")
print("=" * 70)

import py_compile

files_to_check = [
    "lib/agent/memory.py",
    "lib/agent/retrieval.py",
    "lib/agent/routers/sabine.py",
    "lib/agent/routers/memory.py"
]

for file_path in files_to_check:
    try:
        py_compile.compile(file_path, doraise=True)
        print(f"✓ PASS: {file_path} syntax is valid")
    except py_compile.PyCompileError as e:
        print(f"❌ FAIL: {file_path} has syntax errors: {e}")
        all_passed = False

# Test 7: Verify task agent doesn't call ingest_user_message
print("\n" + "=" * 70)
print("TEST 7: Verify task agent path doesn't call ingest_user_message")
print("=" * 70)

task_files = ["lib/agent/task_runner.py", "lib/agent/task_agent.py"]
found_in_task = False

for file_path in task_files:
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            content = f.read()
        if 'ingest_user_message' in content:
            print(f"❌ FAIL: {file_path} calls ingest_user_message (should not)")
            found_in_task = True
            all_passed = False

if not found_in_task:
    print("✓ PASS: Task agent files do not call ingest_user_message")

# Summary
print("\n" + "=" * 70)
if all_passed:
    print("ALL TESTS PASSED ✓")
    print("=" * 70)
    print("\nBatch C Implementation Complete:")
    print("✓ Memory ingestion accepts and stores role parameter")
    print("✓ Memory retrieval supports role filtering")
    print("✓ SQL migration adds role_filter to match_memories RPC")
    print("✓ Backward compatibility maintained (NULL role values)")
    print("✓ All Python files have valid syntax")
    print("✓ Task agent path does not call ingest_user_message")
    print("\nNext Steps:")
    print("1. Deploy SQL migration to Supabase")
    print("2. Test end-to-end memory ingestion with different roles")
    print("3. Verify Sabine memories don't mix with Dream Team task memories")
    sys.exit(0)
else:
    print("SOME TESTS FAILED ❌")
    print("=" * 70)
    sys.exit(1)
