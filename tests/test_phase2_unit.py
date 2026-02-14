"""
Phase 2 Unit Tests - Separate Agent Cores
==========================================

Tests for all Phase 2 components that can run WITHOUT live services.
No API keys, no database, no running server required.

Run with: pytest tests/test_phase2_unit.py -v

Covers:
- Batch A: Tool sets, tool scoping
- Batch B: Tool filtering, error classification, tool execution parsing
- Batch C: Memory role tagging signatures, retrieval filter signatures
"""

import fnmatch
import inspect
import json
import os
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Batch A: Tool Set Definitions
# =============================================================================

class TestToolSets:
    """Tests for lib/agent/tool_sets.py"""

    def test_sabine_tools_is_set_of_strings(self):
        from lib.agent.tool_sets import SABINE_TOOLS
        assert isinstance(SABINE_TOOLS, set)
        assert all(isinstance(t, str) for t in SABINE_TOOLS)

    def test_dream_team_tools_is_set_of_strings(self):
        from lib.agent.tool_sets import DREAM_TEAM_TOOLS
        assert isinstance(DREAM_TEAM_TOOLS, set)
        assert all(isinstance(t, str) for t in DREAM_TEAM_TOOLS)

    def test_tool_sets_are_disjoint(self):
        """SABINE_TOOLS and DREAM_TEAM_TOOLS must have zero overlap."""
        from lib.agent.tool_sets import SABINE_TOOLS, DREAM_TEAM_TOOLS
        overlap = SABINE_TOOLS.intersection(DREAM_TEAM_TOOLS)
        assert len(overlap) == 0, f"Tool sets overlap: {overlap}"

    def test_sabine_tools_contains_expected(self):
        from lib.agent.tool_sets import SABINE_TOOLS
        expected = {
            "get_calendar_events",
            "create_calendar_event",
            "get_custody_schedule",
            "get_weather",
            "create_reminder",
            "cancel_reminder",
            "list_reminders",
        }
        assert SABINE_TOOLS == expected

    def test_dream_team_tools_contains_expected(self):
        from lib.agent.tool_sets import DREAM_TEAM_TOOLS
        expected = {
            "github_issues",
            "run_python_sandbox",
            "sync_project_board",
            "send_team_update",
        }
        assert DREAM_TEAM_TOOLS == expected


class TestGetToolNames:
    """Tests for get_tool_names()"""

    def test_assistant_returns_sabine_tools(self):
        from lib.agent.tool_sets import get_tool_names, SABINE_TOOLS
        assert get_tool_names("assistant") == SABINE_TOOLS

    def test_coder_returns_dream_team_tools(self):
        from lib.agent.tool_sets import get_tool_names, DREAM_TEAM_TOOLS
        assert get_tool_names("coder") == DREAM_TEAM_TOOLS

    def test_invalid_role_raises_value_error(self):
        from lib.agent.tool_sets import get_tool_names
        with pytest.raises(ValueError, match="Invalid role"):
            get_tool_names("invalid_role")

    def test_empty_string_raises_value_error(self):
        from lib.agent.tool_sets import get_tool_names
        with pytest.raises(ValueError):
            get_tool_names("")


class TestIsToolAllowed:
    """Tests for is_tool_allowed()"""

    def test_calendar_allowed_for_assistant(self):
        from lib.agent.tool_sets import is_tool_allowed
        assert is_tool_allowed("get_calendar_events", "assistant") is True

    def test_github_not_allowed_for_assistant(self):
        from lib.agent.tool_sets import is_tool_allowed
        assert is_tool_allowed("github_issues", "assistant") is False

    def test_github_allowed_for_coder(self):
        from lib.agent.tool_sets import is_tool_allowed
        assert is_tool_allowed("github_issues", "coder") is True

    def test_calendar_not_allowed_for_coder(self):
        from lib.agent.tool_sets import is_tool_allowed
        assert is_tool_allowed("get_calendar_events", "coder") is False

    def test_nonexistent_tool_not_allowed(self):
        from lib.agent.tool_sets import is_tool_allowed
        assert is_tool_allowed("nonexistent_tool", "assistant") is False
        assert is_tool_allowed("nonexistent_tool", "coder") is False

    def test_every_sabine_tool_allowed_for_assistant(self):
        from lib.agent.tool_sets import is_tool_allowed, SABINE_TOOLS
        for tool_name in SABINE_TOOLS:
            assert is_tool_allowed(tool_name, "assistant") is True, f"{tool_name} should be allowed"

    def test_every_dream_team_tool_allowed_for_coder(self):
        from lib.agent.tool_sets import is_tool_allowed, DREAM_TEAM_TOOLS
        for tool_name in DREAM_TEAM_TOOLS:
            assert is_tool_allowed(tool_name, "coder") is True, f"{tool_name} should be allowed"


# =============================================================================
# Batch B: Tool Filtering by Patterns
# =============================================================================

def _make_mock_tool(name: str) -> MagicMock:
    """Create a mock StructuredTool with a .name attribute."""
    tool = MagicMock()
    tool.name = name
    return tool


class TestFilterToolsByPatterns:
    """Tests for task_agent._filter_tools_by_patterns()"""

    def test_empty_patterns_returns_all_tools(self):
        from lib.agent.task_agent import _filter_tools_by_patterns
        tools = [_make_mock_tool("a"), _make_mock_tool("b")]
        result = _filter_tools_by_patterns(tools, [])
        assert len(result) == 2

    def test_exact_match(self):
        from lib.agent.task_agent import _filter_tools_by_patterns
        tools = [_make_mock_tool("github_issues"), _make_mock_tool("run_python_sandbox")]
        result = _filter_tools_by_patterns(tools, ["github_issues"])
        assert len(result) == 1
        assert result[0].name == "github_issues"

    def test_wildcard_match(self):
        from lib.agent.task_agent import _filter_tools_by_patterns
        tools = [
            _make_mock_tool("github_issues"),
            _make_mock_tool("github_create_pr"),
            _make_mock_tool("run_python_sandbox"),
        ]
        result = _filter_tools_by_patterns(tools, ["github_*"])
        assert len(result) == 2
        assert all("github" in t.name for t in result)

    def test_no_match_returns_empty(self):
        from lib.agent.task_agent import _filter_tools_by_patterns
        tools = [_make_mock_tool("github_issues")]
        result = _filter_tools_by_patterns(tools, ["nonexistent_*"])
        assert len(result) == 0

    def test_multiple_patterns_union(self):
        from lib.agent.task_agent import _filter_tools_by_patterns
        tools = [
            _make_mock_tool("github_issues"),
            _make_mock_tool("run_python_sandbox"),
            _make_mock_tool("send_team_update"),
        ]
        result = _filter_tools_by_patterns(tools, ["github_*", "run_*"])
        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"github_issues", "run_python_sandbox"}

    def test_tool_matched_only_once(self):
        """A tool matching multiple patterns should only appear once."""
        from lib.agent.task_agent import _filter_tools_by_patterns
        tools = [_make_mock_tool("github_issues")]
        result = _filter_tools_by_patterns(tools, ["github_*", "git*"])
        assert len(result) == 1

    def test_empty_tools_list(self):
        from lib.agent.task_agent import _filter_tools_by_patterns
        result = _filter_tools_by_patterns([], ["github_*"])
        assert len(result) == 0


# =============================================================================
# Batch B: Error Classification
# =============================================================================

class TestClassifyAgentError:
    """Tests for core.classify_agent_error()"""

    def test_rate_limit(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("Rate limit exceeded"))
        assert result["error_type"] == "rate_limited"
        assert result["http_status"] == 429
        assert result["error_category"] == "external_service"

    def test_unauthorized(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("401 Unauthorized"))
        assert result["error_type"] == "auth_failed"
        assert result["http_status"] == 401

    def test_forbidden(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("403 Forbidden"))
        assert result["error_type"] == "permission_denied"
        assert result["http_status"] == 403

    def test_not_found(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("404 Not found"))
        assert result["error_type"] == "not_found"
        assert result["http_status"] == 404

    def test_timeout(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("Connection timed out"))
        assert result["error_type"] == "timeout"
        assert result["http_status"] == 504

    def test_network_error(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("Network connection refused"))
        assert result["error_type"] == "network_error"
        assert result["http_status"] == 502

    def test_validation_error(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("Validation failed: invalid input"))
        assert result["error_type"] == "validation_error"
        assert result["http_status"] == 400

    def test_unknown_error(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(Exception("Something completely unexpected"))
        assert result["error_type"] == "unknown"
        assert result["http_status"] is None
        assert result["error_category"] == "internal"

    def test_returns_error_class(self):
        from lib.agent.core import classify_agent_error
        result = classify_agent_error(ValueError("test"))
        assert result["error_class"] == "ValueError"


# =============================================================================
# Batch B: Tool Execution Detail Parsing
# =============================================================================

def _make_tool_message(name: str, content: str, tool_call_id: str = "tc_1") -> MagicMock:
    """Create a mock ToolMessage."""
    msg = MagicMock()
    msg.__class__.__name__ = "ToolMessage"
    type(msg).__name__ = "ToolMessage"
    msg.name = name
    msg.content = content
    msg.tool_call_id = tool_call_id
    return msg


def _make_ai_message_with_tool_use(tool_name: str, tool_id: str = "tu_1", input_data: dict = None) -> MagicMock:
    """Create a mock AIMessage with tool_use content blocks."""
    msg = MagicMock()
    msg.__class__.__name__ = "AIMessage"
    type(msg).__name__ = "AIMessage"
    msg.content = [
        {"type": "tool_use", "name": tool_name, "id": tool_id, "input": input_data or {}}
    ]
    return msg


def _make_ai_message_text(text: str) -> MagicMock:
    """Create a mock AIMessage with text content."""
    msg = MagicMock()
    msg.__class__.__name__ = "AIMessage"
    type(msg).__name__ = "AIMessage"
    msg.content = text
    return msg


class TestExtractToolExecutionDetails:
    """Tests for core.extract_tool_execution_details()"""

    def test_empty_messages(self):
        from lib.agent.core import extract_tool_execution_details
        result = extract_tool_execution_details([])
        assert result["tool_calls_detected"] == 0
        assert result["tool_successes"] == 0
        assert result["tool_failures"] == 0
        assert result["tool_executions"] == []

    def test_successful_json_tool_result(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("github_issues", '{"status": "success", "issue": {"number": 42}}')
        result = extract_tool_execution_details([msg])
        assert result["tool_successes"] == 1
        assert result["tool_failures"] == 0
        assert result["artifacts_created"] == ["Issue #42"]

    def test_failed_json_tool_result(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("github_issues", '{"status": "error", "error": "Repo not found"}')
        result = extract_tool_execution_details([msg])
        assert result["tool_successes"] == 0
        assert result["tool_failures"] == 1
        assert len(result["failed_tools"]) == 1

    def test_error_field_without_status(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("github_issues", '{"error": "Something went wrong"}')
        result = extract_tool_execution_details([msg])
        assert result["tool_failures"] == 1

    def test_success_field_true(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("some_tool", '{"success": true}')
        result = extract_tool_execution_details([msg])
        assert result["tool_successes"] == 1

    def test_success_field_false(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("some_tool", '{"success": false, "error": "Nope"}')
        result = extract_tool_execution_details([msg])
        assert result["tool_failures"] == 1

    def test_no_status_no_error_assumes_success(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("some_tool", '{"data": "some result"}')
        result = extract_tool_execution_details([msg])
        assert result["tool_successes"] == 1

    def test_non_json_with_error_string(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("some_tool", "Error: permission denied")
        result = extract_tool_execution_details([msg])
        assert result["tool_failures"] == 1

    def test_non_json_without_error_string(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("some_tool", "Operation completed successfully")
        result = extract_tool_execution_details([msg])
        assert result["tool_successes"] == 1

    def test_tool_use_blocks_counted(self):
        from lib.agent.core import extract_tool_execution_details
        ai_msg = _make_ai_message_with_tool_use("github_issues", "tu_1")
        result = extract_tool_execution_details([ai_msg])
        assert result["tool_calls_detected"] == 1
        assert "github_issues" in result["tool_names_used"]

    def test_file_artifact_extraction(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("create_file", '{"status": "success", "file": {"path": "src/app.py"}}')
        result = extract_tool_execution_details([msg])
        assert "src/app.py" in result["artifacts_created"]

    def test_commit_artifact_extraction(self):
        from lib.agent.core import extract_tool_execution_details
        msg = _make_tool_message("git_commit", '{"status": "success", "commit": {"sha": "abc1234567890"}}')
        result = extract_tool_execution_details([msg])
        assert any("abc1234" in a for a in result["artifacts_created"])

    def test_mixed_messages(self):
        """Full flow: AI requests tool -> tool succeeds -> AI responds."""
        from lib.agent.core import extract_tool_execution_details
        messages = [
            _make_ai_message_with_tool_use("github_issues"),
            _make_tool_message("github_issues", '{"status": "success", "issue": {"number": 1}}'),
            _make_ai_message_text("I created the issue."),
        ]
        result = extract_tool_execution_details(messages)
        assert result["tool_calls_detected"] == 1
        assert result["tool_successes"] == 1
        assert result["tool_failures"] == 0


# =============================================================================
# Batch B: Task Requires Tool Execution Heuristic
# =============================================================================

class TestTaskRequiresToolExecution:
    """Tests for task_runner._task_requires_tool_execution()"""

    def test_action_keywords_detected(self):
        from lib.agent.task_runner import _task_requires_tool_execution
        assert _task_requires_tool_execution({"message": "Create a new file"}) is True
        assert _task_requires_tool_execution({"message": "Implement the auth module"}) is True
        assert _task_requires_tool_execution({"message": "Run the test suite"}) is True

    def test_analysis_keywords_only(self):
        from lib.agent.task_runner import _task_requires_tool_execution
        assert _task_requires_tool_execution({"message": "Analyze the codebase"}) is False
        assert _task_requires_tool_execution({"message": "Review the architecture"}) is False

    def test_explicit_tool_requirement(self):
        from lib.agent.task_runner import _task_requires_tool_execution
        assert _task_requires_tool_execution({"requires_tools": True}) is True
        assert _task_requires_tool_execution({"deliverables": ["file.py"]}) is True
        assert _task_requires_tool_execution({"target_files": ["app.ts"]}) is True


# =============================================================================
# Batch C: Memory Ingestion Signature
# =============================================================================

class TestMemoryIngestionSignature:
    """Verify ingest_user_message has role parameter with correct default."""

    def test_role_parameter_exists(self):
        from lib.agent.memory import ingest_user_message
        sig = inspect.signature(ingest_user_message)
        assert "role" in sig.parameters

    def test_role_default_is_assistant(self):
        from lib.agent.memory import ingest_user_message
        sig = inspect.signature(ingest_user_message)
        assert sig.parameters["role"].default == "assistant"

    def test_role_type_is_str(self):
        from lib.agent.memory import ingest_user_message
        sig = inspect.signature(ingest_user_message)
        assert sig.parameters["role"].annotation == str


# =============================================================================
# Batch C: Memory Retrieval Signature
# =============================================================================

class TestRetrievalSignatures:
    """Verify retrieve_context and search_similar_memories have role_filter."""

    def test_retrieve_context_has_role_filter(self):
        from lib.agent.retrieval import retrieve_context
        sig = inspect.signature(retrieve_context)
        assert "role_filter" in sig.parameters

    def test_retrieve_context_role_filter_default_is_assistant(self):
        from lib.agent.retrieval import retrieve_context
        sig = inspect.signature(retrieve_context)
        assert sig.parameters["role_filter"].default == "assistant"

    def test_search_similar_memories_has_role_filter(self):
        from lib.agent.retrieval import search_similar_memories
        sig = inspect.signature(search_similar_memories)
        assert "role_filter" in sig.parameters

    def test_search_similar_memories_role_filter_default_is_none(self):
        from lib.agent.retrieval import search_similar_memories
        sig = inspect.signature(search_similar_memories)
        assert sig.parameters["role_filter"].default is None


# =============================================================================
# Batch C: Memory Metadata Includes Role (Source Code Check)
# =============================================================================

class TestMemoryRoleInMetadata:
    """Verify that the role field is added to metadata in ingest_user_message source."""

    def test_role_stored_in_metadata(self):
        """Read memory.py source and verify 'role' is in the metadata dict."""
        memory_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "lib", "agent", "memory.py"
        )
        with open(memory_path, "r", encoding="utf-8") as f:
            source = f.read()
        assert '"role": role' in source or "'role': role" in source, \
            "role field not found in metadata dict in memory.py"


# =============================================================================
# Batch C: SQL Migration Exists and Is Correct
# =============================================================================

class TestSQLMigration:
    """Verify the match_memories migration file exists and has correct content."""

    @pytest.fixture
    def migration_content(self):
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "supabase", "migrations",
            "20260207170000_add_role_filter_to_match_memories.sql"
        )
        assert os.path.exists(migration_path), f"Migration file not found: {migration_path}"
        with open(migration_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_has_role_filter_parameter(self, migration_content):
        assert "role_filter text DEFAULT NULL" in migration_content

    def test_has_null_check_for_backward_compat(self, migration_content):
        assert "role_filter IS NULL OR" in migration_content

    def test_has_role_match_logic(self, migration_content):
        assert "metadata->>'role' = role_filter" in migration_content

    def test_has_legacy_null_role_support(self, migration_content):
        assert "metadata->>'role' IS NULL" in migration_content


# =============================================================================
# Cross-Batch: Task Agent Does Not Ingest Memory
# =============================================================================

class TestTaskAgentNoMemoryIngestion:
    """Verify task_agent.py and task_runner.py do NOT call ingest_user_message."""

    def _read_file(self, filename):
        filepath = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "lib", "agent", filename
        )
        if not os.path.exists(filepath):
            pytest.skip(f"{filename} not found")
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def test_task_agent_no_ingest(self):
        source = self._read_file("task_agent.py")
        assert "ingest_user_message" not in source

    def test_task_runner_no_ingest(self):
        source = self._read_file("task_runner.py")
        assert "ingest_user_message" not in source


# =============================================================================
# Cross-Batch: Agent Function Signatures
# =============================================================================

class TestAgentFunctionSignatures:
    """Verify run_sabine_agent and run_task_agent have correct signatures."""

    def test_sabine_agent_no_role_param(self):
        from lib.agent.sabine_agent import run_sabine_agent
        sig = inspect.signature(run_sabine_agent)
        assert "role" not in sig.parameters, "Sabine agent should NOT accept a role parameter"

    def test_task_agent_requires_role(self):
        from lib.agent.task_agent import run_task_agent
        sig = inspect.signature(run_task_agent)
        assert "role" in sig.parameters, "Task agent MUST accept a role parameter"
        # role should NOT have a default (it is required)
        role_param = sig.parameters["role"]
        assert role_param.default == inspect.Parameter.empty, \
            "Task agent role parameter should be required (no default)"

    def test_both_agents_return_dict(self):
        from lib.agent.sabine_agent import run_sabine_agent
        from lib.agent.task_agent import run_task_agent
        # Check return annotations exist
        sabine_hints = inspect.signature(run_sabine_agent).return_annotation
        task_hints = inspect.signature(run_task_agent).return_annotation
        assert sabine_hints == Dict[str, Any]
        assert task_hints == Dict[str, Any]


# =============================================================================
# Cross-Batch: Caller Updates Pass Role Explicitly
# =============================================================================

class TestCallerUpdates:
    """Verify all callers pass role='assistant' to ingest_user_message."""

    def _read_file(self, *path_parts):
        filepath = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            *path_parts
        )
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def test_sabine_router_passes_role(self):
        source = self._read_file("lib", "agent", "routers", "sabine.py")
        assert 'role="assistant"' in source

    def test_memory_router_passes_role(self):
        source = self._read_file("lib", "agent", "routers", "memory.py")
        assert source.count('role="assistant"') >= 2, \
            "memory.py should pass role='assistant' in both ingest and upload endpoints"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
