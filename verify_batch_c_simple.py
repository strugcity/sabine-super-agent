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

# Test 8: Verify sabine_agent.py passes role_filter explicitly
print("\n" + "=" * 70)
print("TEST 8: Verify sabine_agent.py passes role_filter explicitly")
print("=" * 70)

with open("lib/agent/sabine_agent.py", 'r') as f:
    sabine_agent_content = f.read()

if 'role_filter="assistant"' in sabine_agent_content:
    print("✓ PASS: sabine_agent.py explicitly passes role_filter='assistant'")
else:
    print("❌ FAIL: sabine_agent.py does not explicitly pass role_filter")
    all_passed = False

# Test 9: Verify MemoryQueryRequest has role_filter field
print("\n" + "=" * 70)
print("TEST 9: Verify MemoryQueryRequest has role_filter field")
print("=" * 70)

with open("lib/agent/shared.py", 'r') as f:
    shared_content = f.read()

# Check for role_filter in MemoryQueryRequest
memory_query_pattern = r'class MemoryQueryRequest.*?role_filter.*?Field'
if re.search(memory_query_pattern, shared_content, re.DOTALL):
    print("✓ PASS: MemoryQueryRequest has role_filter field")
else:
    print("❌ FAIL: MemoryQueryRequest missing role_filter field")
    all_passed = False

# Test 10: Verify memory router passes role_filter from request
print("\n" + "=" * 70)
print("TEST 10: Verify memory router passes role_filter from request")
print("=" * 70)

with open("lib/agent/routers/memory.py", 'r') as f:
    memory_router_content = f.read()

if 'role_filter=request.role_filter' in memory_router_content:
    print("✓ PASS: memory router passes role_filter from request")
else:
    print("❌ FAIL: memory router does not pass role_filter")
    all_passed = False

# Test 11: Verify SQL migration drops both function signatures
print("\n" + "=" * 70)
print("TEST 11: Verify SQL migration drops both function signatures")
print("=" * 70)

with open("supabase/migrations/20260207170000_add_role_filter_to_match_memories.sql", 'r') as f:
    migration_content = f.read()

# Check for both DROP statements
drop_4_param = "DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid);"
drop_5_param = "DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid, text);"

if drop_4_param in migration_content and drop_5_param in migration_content:
    print("✓ PASS: SQL migration drops both 4-param and 5-param function signatures")
else:
    print("❌ FAIL: SQL migration missing proper DROP statements")
    all_passed = False

# Test 12: Verify SQL migration has TODO comment about NULL leak path
print("\n" + "=" * 70)
print("TEST 12: Verify SQL migration has TODO about legacy NULL role")
print("=" * 70)

if "TODO" in migration_content and "NULL" in migration_content and "leak" in migration_content.lower():
    print("✓ PASS: SQL migration includes TODO comment about NULL role leak path")
else:
    print("❌ FAIL: SQL migration missing TODO comment about future tightening")
    all_passed = False

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
    print("✓ sabine_agent.py explicitly passes role_filter='assistant'")
    print("✓ MemoryQueryRequest accepts role_filter parameter")
    print("✓ Memory router passes role_filter from request")
    print("✓ SQL migration drops both old and new function signatures")
    print("✓ SQL migration includes TODO about NULL role leak path")
    print("\nNext Steps:")
    print("1. Deploy SQL migration to Supabase")
    print("2. Test end-to-end memory ingestion with different roles")
    print("3. Verify Sabine memories don't mix with Dream Team task memories")
    sys.exit(0)
else:
    print("SOME TESTS FAILED ❌")
    print("=" * 70)
    sys.exit(1)
