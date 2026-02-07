#!/usr/bin/env python3
"""
Verification script for Batch B - Phase 2 Agent Separation

This script verifies that all the required files and functions exist
without actually importing them (to avoid dependency issues in CI).
"""

import os
import re
import sys


def check_file_exists(path: str) -> bool:
    """Check if a file exists."""
    exists = os.path.exists(path)
    if exists:
        print(f"✓ {path} exists")
    else:
        print(f"✗ {path} MISSING")
    return exists


def check_function_exists(path: str, function_name: str) -> bool:
    """Check if a function definition exists in a file."""
    if not os.path.exists(path):
        print(f"✗ {path} does not exist, cannot check for {function_name}")
        return False
    
    with open(path, 'r') as f:
        content = f.read()
    
    # Look for function definition (either def or async def)
    pattern = rf'(async\s+)?def\s+{re.escape(function_name)}\s*\('
    if re.search(pattern, content):
        print(f"✓ {function_name}() found in {path}")
        return True
    else:
        print(f"✗ {function_name}() NOT FOUND in {path}")
        return False


def check_import_exists(path: str, import_statement: str) -> bool:
    """Check if an import statement exists in a file."""
    if not os.path.exists(path):
        print(f"✗ {path} does not exist, cannot check for import")
        return False
    
    with open(path, 'r') as f:
        content = f.read()
    
    if import_statement in content:
        print(f"✓ Import found in {path}: {import_statement[:50]}...")
        return True
    else:
        print(f"✗ Import NOT FOUND in {path}: {import_statement[:50]}...")
        return False


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("BATCH B VERIFICATION - Phase 2 Agent Separation")
    print("=" * 60)
    print()
    
    all_passed = True
    
    # B1: Check create_react_agent_with_tools in core.py
    print("B1: Checking create_react_agent_with_tools() helper...")
    all_passed &= check_function_exists(
        'lib/agent/core.py',
        'create_react_agent_with_tools'
    )
    print()
    
    # B2: Check sabine_agent.py
    print("B2: Checking sabine_agent.py...")
    all_passed &= check_file_exists('lib/agent/sabine_agent.py')
    all_passed &= check_function_exists(
        'lib/agent/sabine_agent.py',
        'run_sabine_agent'
    )
    # Check that it calls get_scoped_tools("assistant")
    with open('lib/agent/sabine_agent.py', 'r') as f:
        content = f.read()
        if 'get_scoped_tools("assistant")' in content or "get_scoped_tools('assistant')" in content:
            print('✓ Calls get_scoped_tools("assistant")')
        else:
            print('✗ Does NOT call get_scoped_tools("assistant")')
            all_passed = False
        if 'retrieve_context' in content:
            print('✓ Calls retrieve_context()')
        else:
            print('✗ Does NOT call retrieve_context()')
            all_passed = False
    print()
    
    # B3: Check task_agent.py
    print("B3: Checking task_agent.py...")
    all_passed &= check_file_exists('lib/agent/task_agent.py')
    all_passed &= check_function_exists(
        'lib/agent/task_agent.py',
        'run_task_agent'
    )
    # Check that it calls get_scoped_tools("coder")
    with open('lib/agent/task_agent.py', 'r') as f:
        content = f.read()
        if 'get_scoped_tools("coder")' in content or "get_scoped_tools('coder')" in content:
            print('✓ Calls get_scoped_tools("coder")')
        else:
            print('✗ Does NOT call get_scoped_tools("coder")')
            all_passed = False
        if 'load_role_manifest' in content:
            print('✓ Calls load_role_manifest()')
        else:
            print('✗ Does NOT call load_role_manifest()')
            all_passed = False
        # Check that it does NOT call retrieve_context
        # (ignore comments that mention it)
        lines = content.split('\n')
        has_actual_call = False
        for line in lines:
            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Check for import or call
            if 'from' in line and 'import' in line and 'retrieve_context' in line:
                has_actual_call = True
                break
            if 'await retrieve_context(' in line or line.strip().startswith('retrieve_context('):
                has_actual_call = True
                break
        
        if not has_actual_call:
            print('✓ Does NOT call retrieve_context() (correct)')
        else:
            print('✗ INCORRECTLY calls retrieve_context()')
            all_passed = False
    print()
    
    # B4a: Check sabine router uses run_sabine_agent
    print("B4a: Checking sabine router...")
    all_passed &= check_import_exists(
        'lib/agent/routers/sabine.py',
        'from lib.agent.sabine_agent import run_sabine_agent'
    )
    with open('lib/agent/routers/sabine.py', 'r') as f:
        content = f.read()
        if 'run_sabine_agent(' in content:
            print('✓ Calls run_sabine_agent()')
        else:
            print('✗ Does NOT call run_sabine_agent()')
            all_passed = False
    print()
    
    # B4b: Check task_runner.py exists and has the functions
    print("B4b: Checking task_runner.py...")
    all_passed &= check_file_exists('lib/agent/task_runner.py')
    all_passed &= check_function_exists(
        'lib/agent/task_runner.py',
        '_run_task_agent'
    )
    all_passed &= check_function_exists(
        'lib/agent/task_runner.py',
        '_dispatch_task'
    )
    all_passed &= check_function_exists(
        'lib/agent/task_runner.py',
        '_task_requires_tool_execution'
    )
    # Check that it calls run_task_agent
    with open('lib/agent/task_runner.py', 'r') as f:
        content = f.read()
        if 'from lib.agent.task_agent import run_task_agent' in content:
            print('✓ Imports run_task_agent from task_agent')
        else:
            print('✗ Does NOT import run_task_agent')
            all_passed = False
        if 'await run_task_agent(' in content:
            print('✓ Calls run_task_agent()')
        else:
            print('✗ Does NOT call run_task_agent()')
            all_passed = False
    print()
    
    # B4c: Check dream_team router imports from task_runner
    print("B4c: Checking dream_team router...")
    all_passed &= check_import_exists(
        'lib/agent/routers/dream_team.py',
        'from lib.agent.task_runner import'
    )
    print()
    
    # B4d: Check server.py imports from task_runner
    print("B4d: Checking server.py...")
    all_passed &= check_import_exists(
        'lib/agent/server.py',
        'from lib.agent.task_runner import'
    )
    # Check that server.py does NOT have duplicate function definitions
    with open('lib/agent/server.py', 'r') as f:
        content = f.read()
        # Count how many times async def _run_task_agent appears
        count = content.count('async def _run_task_agent(')
        if count == 0:
            print('✓ No duplicate _run_task_agent() definition')
        else:
            print(f'✗ Found {count} duplicate _run_task_agent() definitions')
            all_passed = False
    print()
    
    # Final result
    print("=" * 60)
    if all_passed:
        print("✅ ALL CHECKS PASSED")
        print("=" * 60)
        return 0
    else:
        print("❌ SOME CHECKS FAILED")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
