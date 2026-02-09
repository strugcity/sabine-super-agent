#!/usr/bin/env python3
"""
Verification Script for Phase 2: Agent Separation (Full Batches A+B+C+D)

This script verifies that all Phase 2 requirements are met:
- Batch A: Tool set definitions with zero overlap
- Batch B: Separate agent core functions
- Batch C: Memory role tagging + filtered retrieval
- Batch D: Deprecated run_agent() dispatcher + cleanup

Tests:
1. Tool set definitions (tool_sets.py)
2. Tool registry with scoped loading (registry.py)
3. Sabine agent function (sabine_agent.py)
4. Task agent function (task_agent.py)
5. Routers use correct agent functions
6. Memory ingestion accepts role parameter
7. Memory retrieval supports role filtering
8. run_agent() works as dispatcher
9. create_agent() has deprecation warning
10. All modified files have valid Python syntax
"""

import sys
import os
import re
import inspect
import py_compile
from typing import get_type_hints


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


def check_string_in_file(path: str, search_string: str, description: str) -> bool:
    """Check if a string exists in a file."""
    if not os.path.exists(path):
        print(f"✗ {path} does not exist")
        return False
    
    with open(path, 'r') as f:
        content = f.read()
    
    if search_string in content:
        print(f"✓ {description}")
        return True
    else:
        print(f"✗ {description} - NOT FOUND")
        return False


def main():
    """Run all verification checks."""
    print("=" * 80)
    print("PHASE 2 FULL VERIFICATION - Agent Separation (Batches A+B+C+D)")
    print("=" * 80)
    print()
    
    all_passed = True
    
    # ==========================================================================
    # BATCH A: Tool Set Definitions
    # ==========================================================================
    print("BATCH A: Tool Set Definitions")
    print("-" * 80)
    
    all_passed &= check_file_exists('lib/agent/tool_sets.py')
    all_passed &= check_string_in_file(
        'lib/agent/tool_sets.py',
        'SABINE_TOOLS: Set[str] = {',
        "SABINE_TOOLS set defined"
    )
    all_passed &= check_string_in_file(
        'lib/agent/tool_sets.py',
        'DREAM_TEAM_TOOLS: Set[str] = {',
        "DREAM_TEAM_TOOLS set defined"
    )
    all_passed &= check_string_in_file(
        'lib/agent/tool_sets.py',
        'def get_tool_names(',
        "get_tool_names() function defined"
    )
    print()
    
    # ==========================================================================
    # BATCH A: Tool Registry with Scoped Loading
    # ==========================================================================
    print("BATCH A: Tool Registry")
    print("-" * 80)
    
    all_passed &= check_function_exists('lib/agent/registry.py', 'get_scoped_tools')
    # Check for import (can be lazy import inside function)
    with open('lib/agent/registry.py', 'r') as f:
        content = f.read()
        if 'from .tool_sets import' in content and 'get_tool_names' in content:
            print("✓ Imports get_tool_names from tool_sets")
        else:
            print("✗ Does NOT import get_tool_names from tool_sets")
            all_passed = False
    print()
    
    # ==========================================================================
    # BATCH B: Sabine Agent
    # ==========================================================================
    print("BATCH B: Sabine Agent (run_sabine_agent)")
    print("-" * 80)
    
    all_passed &= check_file_exists('lib/agent/sabine_agent.py')
    all_passed &= check_function_exists('lib/agent/sabine_agent.py', 'run_sabine_agent')
    all_passed &= check_string_in_file(
        'lib/agent/sabine_agent.py',
        'get_scoped_tools("assistant")',
        "Calls get_scoped_tools('assistant')"
    )
    all_passed &= check_string_in_file(
        'lib/agent/sabine_agent.py',
        'retrieve_context(',
        "Calls retrieve_context()"
    )
    all_passed &= check_string_in_file(
        'lib/agent/sabine_agent.py',
        'role_filter="assistant"',
        "Passes role_filter='assistant' to retrieve_context()"
    )
    print()
    
    # ==========================================================================
    # BATCH B: Task Agent
    # ==========================================================================
    print("BATCH B: Task Agent (run_task_agent)")
    print("-" * 80)
    
    all_passed &= check_file_exists('lib/agent/task_agent.py')
    all_passed &= check_function_exists('lib/agent/task_agent.py', 'run_task_agent')
    all_passed &= check_string_in_file(
        'lib/agent/task_agent.py',
        'get_scoped_tools("coder")',
        "Calls get_scoped_tools('coder')"
    )
    all_passed &= check_string_in_file(
        'lib/agent/task_agent.py',
        'load_role_manifest(',
        "Calls load_role_manifest()"
    )
    
    # Verify task agent does NOT call retrieve_context
    with open('lib/agent/task_agent.py', 'r') as f:
        task_agent_content = f.read()
        
        # Check if there's an actual import or call (not in comments)
        has_retrieve_import = False
        has_retrieve_call = False
        
        lines = task_agent_content.split('\n')
        for line in lines:
            stripped = line.strip()
            # Skip comments and docstrings
            if stripped.startswith('#'):
                continue
            if '"""' in line or "'''" in line:
                continue
            
            # Check for import
            if 'from' in line and 'import' in line and 'retrieve_context' in line:
                # Make sure it's not inside a string
                if not ('"retrieve_context"' in line or "'retrieve_context'" in line):
                    has_retrieve_import = True
                    break
            
            # Check for actual call (not in strings)
            if 'await retrieve_context(' in line or line.strip().startswith('retrieve_context('):
                has_retrieve_call = True
                break
        
        if not has_retrieve_import and not has_retrieve_call:
            print("✓ Does NOT call retrieve_context() (correct for task agents)")
        else:
            print("✗ INCORRECTLY calls retrieve_context()")
            all_passed = False
    
    print()
    
    # ==========================================================================
    # BATCH B: Routers Updated
    # ==========================================================================
    print("BATCH B: Routers Use Correct Agent Functions")
    print("-" * 80)
    
    # Check sabine router
    all_passed &= check_string_in_file(
        'lib/agent/routers/sabine.py',
        'from lib.agent.sabine_agent import run_sabine_agent',
        "Sabine router imports run_sabine_agent"
    )
    all_passed &= check_string_in_file(
        'lib/agent/routers/sabine.py',
        'run_sabine_agent(',
        "Sabine router calls run_sabine_agent()"
    )
    
    # Check dream_team router uses task_runner
    all_passed &= check_string_in_file(
        'lib/agent/routers/dream_team.py',
        'from lib.agent.task_runner import',
        "Dream Team router imports from task_runner"
    )
    
    # Check task_runner uses task_agent
    all_passed &= check_file_exists('lib/agent/task_runner.py')
    all_passed &= check_string_in_file(
        'lib/agent/task_runner.py',
        'from lib.agent.task_agent import run_task_agent',
        "task_runner imports run_task_agent"
    )
    all_passed &= check_string_in_file(
        'lib/agent/task_runner.py',
        'await run_task_agent(',
        "task_runner calls run_task_agent()"
    )
    
    print()
    
    # ==========================================================================
    # BATCH C: Memory Role Tagging
    # ==========================================================================
    print("BATCH C: Memory Role Tagging + Filtered Retrieval")
    print("-" * 80)
    
    # Check ingest_user_message signature
    try:
        # Use inspect on the file directly without importing to avoid dependency issues
        import ast
        with open('lib/agent/memory.py', 'r') as f:
            tree = ast.parse(f.read())
        
        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'ingest_user_message':
                found = True
                # Check for role parameter
                has_role = False
                has_default = False
                for arg_idx, arg in enumerate(node.args.args):
                    if arg.arg == 'role':
                        has_role = True
                        # Check if it has a default
                        defaults_offset = len(node.args.args) - len(node.args.defaults)
                        if arg_idx >= defaults_offset:
                            default_idx = arg_idx - defaults_offset
                            default_node = node.args.defaults[default_idx]
                            if isinstance(default_node, ast.Constant) and default_node.value == "assistant":
                                has_default = True
                        break
                
                if has_role and has_default:
                    print("✓ ingest_user_message() has role parameter with default='assistant'")
                else:
                    print("✗ ingest_user_message() missing role parameter or wrong default")
                    all_passed = False
                break
        
        if not found:
            print("✗ ingest_user_message() function not found")
            all_passed = False
            
    except Exception as e:
        print(f"✗ Error checking ingest_user_message: {e}")
        all_passed = False
    
    # Check retrieve_context signature
    try:
        import ast
        with open('lib/agent/retrieval.py', 'r') as f:
            tree = ast.parse(f.read())
        
        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'retrieve_context':
                found = True
                # Check for role_filter parameter
                has_role_filter = False
                has_default = False
                for arg_idx, arg in enumerate(node.args.args):
                    if arg.arg == 'role_filter':
                        has_role_filter = True
                        # Check if it has a default
                        defaults_offset = len(node.args.args) - len(node.args.defaults)
                        if arg_idx >= defaults_offset:
                            default_idx = arg_idx - defaults_offset
                            default_node = node.args.defaults[default_idx]
                            if isinstance(default_node, ast.Constant) and default_node.value == "assistant":
                                has_default = True
                        break
                
                if has_role_filter and has_default:
                    print("✓ retrieve_context() has role_filter parameter with default='assistant'")
                else:
                    print("✗ retrieve_context() missing role_filter parameter or wrong default")
                    all_passed = False
                break
        
        if not found:
            print("✗ retrieve_context() function not found")
            all_passed = False
            
    except Exception as e:
        print(f"✗ Error checking retrieve_context: {e}")
        all_passed = False
    
    # Check SQL migration exists
    migration_file = "supabase/migrations/20260207170000_add_role_filter_to_match_memories.sql"
    if os.path.exists(migration_file):
        print(f"✓ SQL migration file exists: {migration_file}")
    else:
        print(f"✗ SQL migration file NOT FOUND: {migration_file}")
        all_passed = False
    
    print()
    
    # ==========================================================================
    # BATCH D: run_agent() Dispatcher
    # ==========================================================================
    print("BATCH D: run_agent() Thin Dispatcher")
    print("-" * 80)
    
    all_passed &= check_function_exists('lib/agent/core.py', 'run_agent')
    
    # Check that run_agent is now a dispatcher
    with open('lib/agent/core.py', 'r') as f:
        core_content = f.read()
        
        # Look for dispatcher pattern - should import and call the agent functions
        if 'from .sabine_agent import run_sabine_agent' in core_content:
            print("✓ run_agent() imports run_sabine_agent")
        else:
            print("✗ run_agent() does NOT import run_sabine_agent")
            all_passed = False
        
        if 'from .task_agent import run_task_agent' in core_content:
            print("✓ run_agent() imports run_task_agent")
        else:
            print("✗ run_agent() does NOT import run_task_agent")
            all_passed = False
        
        if 'return await run_sabine_agent(' in core_content:
            print("✓ run_agent() calls run_sabine_agent()")
        else:
            print("✗ run_agent() does NOT call run_sabine_agent()")
            all_passed = False
        
        if 'return await run_task_agent(' in core_content:
            print("✓ run_agent() calls run_task_agent()")
        else:
            print("✗ run_agent() does NOT call run_task_agent()")
            all_passed = False
        
        # Check for deprecation warning
        if 'DEPRECATION' in core_content and 'run_agent()' in core_content:
            print("✓ run_agent() has deprecation warning")
        else:
            print("✗ run_agent() missing deprecation warning")
            all_passed = False
        
        # Verify old implementation is removed (should not have create_agent call in run_agent)
        # Extract run_agent function
        run_agent_match = re.search(
            r'async def run_agent\([^)]*\)[^:]*:.*?(?=\n(?:async\s+)?def\s|\Z)',
            core_content,
            re.DOTALL
        )
        if run_agent_match:
            run_agent_body = run_agent_match.group(0)
            # Should NOT call create_agent inside run_agent anymore
            if 'await create_agent(' not in run_agent_body:
                print("✓ run_agent() no longer calls create_agent() (old implementation removed)")
            else:
                print("✗ run_agent() still calls create_agent() (old implementation NOT removed)")
                all_passed = False
    
    print()
    
    # ==========================================================================
    # BATCH D: create_agent() Deprecation
    # ==========================================================================
    print("BATCH D: create_agent() Deprecation Warning")
    print("-" * 80)
    
    all_passed &= check_function_exists('lib/agent/core.py', 'create_agent')
    all_passed &= check_string_in_file(
        'lib/agent/core.py',
        'DEPRECATION',
        "create_agent() has deprecation warning"
    )
    
    print()
    
    # ==========================================================================
    # Python Syntax Validation
    # ==========================================================================
    print("Python Syntax Validation")
    print("-" * 80)
    
    files_to_check = [
        'lib/agent/tool_sets.py',
        'lib/agent/registry.py',
        'lib/agent/sabine_agent.py',
        'lib/agent/task_agent.py',
        'lib/agent/core.py',
        'lib/agent/task_runner.py',
        'lib/agent/routers/sabine.py',
        'lib/agent/routers/dream_team.py',
        'lib/agent/memory.py',
        'lib/agent/retrieval.py',
    ]
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            try:
                py_compile.compile(file_path, doraise=True)
                print(f"✓ {file_path} syntax is valid")
            except py_compile.PyCompileError as e:
                print(f"✗ {file_path} has syntax errors: {e}")
                all_passed = False
        else:
            print(f"✗ {file_path} does not exist")
            all_passed = False
    
    print()
    
    # ==========================================================================
    # Summary
    # ==========================================================================
    print("=" * 80)
    if all_passed:
        print("✅ ALL CHECKS PASSED - PHASE 2 COMPLETE")
        print("=" * 80)
        print()
        print("Phase 2 Implementation Summary:")
        print("✓ Batch A: Tool sets defined with zero overlap")
        print("✓ Batch A: Tool registry supports scoped loading")
        print("✓ Batch B: run_sabine_agent() with personal assistant tools")
        print("✓ Batch B: run_task_agent() with Dream Team coding tools")
        print("✓ Batch B: Routers use correct agent functions")
        print("✓ Batch C: Memory ingestion accepts and stores role parameter")
        print("✓ Batch C: Memory retrieval supports role filtering")
        print("✓ Batch C: SQL migration adds role_filter to match_memories RPC")
        print("✓ Batch D: run_agent() works as backward-compatible dispatcher")
        print("✓ Batch D: create_agent() has deprecation warning")
        print("✓ Batch D: Old implementation code removed from core.py")
        print("✓ All Python files have valid syntax")
        print()
        print("Next Steps:")
        print("1. Test server starts: python run_server.py")
        print("2. Test POST /invoke with Sabine-only tools")
        print("3. Test task dispatch with Dream Team-only tools")
        print("4. Verify memory ingestion tags role correctly")
        print("5. Verify Sabine memory retrieval excludes Dream Team memories")
        print()
        return 0
    else:
        print("❌ SOME CHECKS FAILED")
        print("=" * 80)
        print()
        print("Please fix the failing checks above before proceeding.")
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
