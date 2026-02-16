"""
Tests for Skill Generator Service
==================================

Unit tests for the autonomous skill generator service.
Tests all functions with full mocking of Anthropic and E2B.

Run with: pytest tests/test_skill_generator.py -v
"""

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.skill_generator import (
    _indent,
    _parse_generation_response,
    _test_in_sandbox,
    generate_and_test_skill,
    generate_skill_from_description,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for skill generator."""
    with patch("backend.services.skill_generator._get_supabase_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_haiku():
    """Mock Haiku API calls."""
    with patch("backend.services.skill_generator._call_haiku", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_sandbox():
    """Mock E2B sandbox execution."""
    with patch("backend.services.skill_generator._test_in_sandbox", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def valid_skill_json() -> str:
    """Valid skill generation response JSON."""
    return json.dumps({
        "manifest": {
            "name": "test_skill",
            "description": "A test skill",
            "version": "1.0.0",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Test message"}
                },
                "required": ["message"]
            }
        },
        "handler_code": "async def execute(params: dict) -> dict:\n    return {'status': 'success'}",
        "test_code": "result = await execute({'message': 'test'})",
        "roi_estimate": "This skill will save 10 hours per week"
    })


# =============================================================================
# Test: _parse_generation_response()
# =============================================================================

class TestParseGenerationResponse:
    """Test the _parse_generation_response pure function."""

    def test_valid_json_returns_parsed_dict(self, valid_skill_json):
        """Valid JSON string returns parsed dict with manifest + handler_code."""
        result = _parse_generation_response(valid_skill_json)

        assert result is not None
        assert "manifest" in result
        assert "handler_code" in result
        assert result["manifest"]["name"] == "test_skill"

    def test_json_with_markdown_fences_strips_fences(self, valid_skill_json):
        """JSON wrapped in triple-backtick markdown fences strips fences, parses correctly."""
        wrapped = f"```\n{valid_skill_json}\n```"
        result = _parse_generation_response(wrapped)

        assert result is not None
        assert result["manifest"]["name"] == "test_skill"

    def test_json_with_json_label_strips_label(self, valid_skill_json):
        """JSON with ```json label strips label and fences."""
        wrapped = f"```json\n{valid_skill_json}\n```"
        result = _parse_generation_response(wrapped)

        assert result is not None
        assert result["manifest"]["name"] == "test_skill"

    def test_invalid_json_returns_none(self):
        """Invalid JSON returns None."""
        result = _parse_generation_response("not valid json {{{")

        assert result is None

    def test_missing_manifest_key_returns_none(self):
        """Missing required key 'manifest' returns None."""
        json_str = json.dumps({
            "handler_code": "async def execute(): pass",
            "test_code": "pass"
        })
        result = _parse_generation_response(json_str)

        assert result is None

    def test_missing_handler_code_key_returns_none(self):
        """Missing required key 'handler_code' returns None."""
        json_str = json.dumps({
            "manifest": {"name": "test"},
            "test_code": "pass"
        })
        result = _parse_generation_response(json_str)

        assert result is None

    def test_manifest_missing_name_returns_none(self):
        """Manifest missing 'name' field returns None."""
        json_str = json.dumps({
            "manifest": {"description": "test"},
            "handler_code": "pass"
        })
        result = _parse_generation_response(json_str)

        assert result is None


# =============================================================================
# Test: _indent()
# =============================================================================

class TestIndent:
    """Test the _indent pure function."""

    def test_single_line_indented(self):
        """Single line with 4 spaces correctly indented."""
        result = _indent("print('hello')", 4)
        assert result == "    print('hello')"

    def test_multi_line_each_line_indented(self):
        """Multi-line code each line indented."""
        code = "line1\nline2\nline3"
        result = _indent(code, 2)
        assert result == "  line1\n  line2\n  line3"

    def test_empty_string_returns_empty_indented(self):
        """Empty string returns empty string with indent."""
        result = _indent("", 4)
        # Empty string produces just the indent prefix for the empty line
        assert result == ""


# =============================================================================
# Test: generate_and_test_skill()
# =============================================================================

class TestGenerateAndTestSkill:
    """Test the generate_and_test_skill async function."""

    @pytest.mark.asyncio
    async def test_no_supabase_returns_failed(self, mock_haiku, mock_sandbox):
        """Supabase not configured returns failed status."""
        with patch("backend.services.skill_generator._get_supabase_client", return_value=None):
            result = await generate_and_test_skill("gap-123")

            assert result["status"] == "failed"
            assert "Supabase not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_gap_not_found_returns_failed(self, mock_supabase, mock_haiku, mock_sandbox):
        """Gap not found returns failed status."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

        result = await generate_and_test_skill("gap-123")

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_haiku_fails_all_retries_returns_failed(self, mock_supabase, mock_haiku, mock_sandbox):
        """Haiku fails all retries returns failed, resets gap status to 'open'."""
        # Mock gap fetch
        mock_gap = MagicMock()
        mock_gap.data = {
            "id": "gap-123",
            "user_id": "user-123",
            "tool_name": "test_tool",
            "gap_type": "repeated_failure",
            "pattern_description": "Test pattern",
            "occurrence_count": 5,
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_gap

        # Mock status updates
        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        # Haiku fails all attempts
        mock_haiku.return_value = None

        result = await generate_and_test_skill("gap-123")

        assert result["status"] == "failed"
        assert "Haiku generation failed" in result["error"]

    @pytest.mark.asyncio
    async def test_haiku_succeeds_sandbox_passes_creates_proposal(
        self, mock_supabase, mock_haiku, mock_sandbox, valid_skill_json
    ):
        """Haiku succeeds + sandbox passes creates proposal with sandbox_passed=True."""
        # Mock gap fetch
        mock_gap = MagicMock()
        mock_gap.data = {
            "id": "gap-123",
            "user_id": "user-123",
            "tool_name": "test_tool",
            "gap_type": "repeated_failure",
            "pattern_description": "Test pattern",
            "occurrence_count": 5,
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_gap

        # Mock status updates
        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        # Mock successful Haiku response
        mock_haiku.return_value = valid_skill_json

        # Mock successful sandbox test
        mock_sandbox.return_value = {
            "passed": True,
            "test_output": "{'status': 'success'}",
            "stdout": ["TEST_RESULT: {'status': 'success'}"],
            "stderr": [],
            "errors": [],
        }

        # Mock proposal insert
        mock_proposal = MagicMock()
        mock_proposal.data = [{"id": "proposal-123"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_proposal

        result = await generate_and_test_skill("gap-123")

        assert result["status"] == "proposed"
        assert result["proposal_id"] == "proposal-123"
        assert result["sandbox_passed"] is True

    @pytest.mark.asyncio
    async def test_haiku_succeeds_sandbox_fails_creates_proposal_with_failure(
        self, mock_supabase, mock_haiku, mock_sandbox, valid_skill_json
    ):
        """Haiku succeeds + sandbox fails creates proposal with sandbox_passed=False."""
        # Mock gap fetch
        mock_gap = MagicMock()
        mock_gap.data = {
            "id": "gap-123",
            "user_id": "user-123",
            "tool_name": "test_tool",
            "gap_type": "repeated_failure",
            "pattern_description": "Test pattern",
            "occurrence_count": 5,
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_gap

        # Mock status updates
        mock_update = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update

        # Mock successful Haiku response
        mock_haiku.return_value = valid_skill_json

        # Mock failed sandbox test
        mock_sandbox.return_value = {
            "passed": False,
            "stderr": ["SyntaxError: invalid syntax"],
            "errors": [{"phase": "execution", "error": "syntax error"}],
        }

        # Mock proposal insert
        mock_proposal = MagicMock()
        mock_proposal.data = [{"id": "proposal-456"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_proposal

        result = await generate_and_test_skill("gap-123")

        assert result["status"] == "proposed"
        assert result["proposal_id"] == "proposal-456"
        assert result["sandbox_passed"] is False


# =============================================================================
# Test: generate_skill_from_description()
# =============================================================================

class TestGenerateSkillFromDescription:
    """Test the generate_skill_from_description async function."""

    @pytest.mark.asyncio
    async def test_success_creates_proposal(self, mock_supabase, mock_haiku, mock_sandbox, valid_skill_json):
        """Success path creates proposal, returns proposed."""
        # Mock successful Haiku response
        mock_haiku.return_value = valid_skill_json

        # Mock sandbox
        mock_sandbox.return_value = {"passed": True}

        # Mock proposal insert
        mock_proposal = MagicMock()
        mock_proposal.data = [{"id": "proposal-789"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_proposal

        result = await generate_skill_from_description(
            user_id="user-123",
            description="Create a skill to format dates"
        )

        assert result["status"] == "proposed"
        assert result["proposal_id"] == "proposal-789"

    @pytest.mark.asyncio
    async def test_haiku_returns_none_returns_failed(self, mock_supabase, mock_haiku, mock_sandbox):
        """Haiku returns None returns failed."""
        mock_haiku.return_value = None

        result = await generate_skill_from_description(
            user_id="user-123",
            description="Test description"
        )

        assert result["status"] == "failed"
        assert "Haiku generation failed" in result["error"]

    @pytest.mark.asyncio
    async def test_no_supabase_returns_failed(self, mock_haiku, mock_sandbox):
        """No Supabase configured returns failed."""
        with patch("backend.services.skill_generator._get_supabase_client", return_value=None):
            result = await generate_skill_from_description(
                user_id="user-123",
                description="Test"
            )

            assert result["status"] == "failed"


# =============================================================================
# Test: _test_in_sandbox()
# =============================================================================

class TestTestInSandbox:
    """Test the _test_in_sandbox async function."""

    @pytest.mark.asyncio
    async def test_sandbox_success_returns_passed_true(self):
        """Sandbox returns success: passed=True."""
        with patch("lib.skills.e2b_sandbox.handler.execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "status": "success",
                "stdout": ["TEST_RESULT: {'status': 'success'}"],
                "stderr": [],
                "errors": [],
            }

            result = await _test_in_sandbox(
                handler_code="async def execute(params): return {'status': 'success'}",
                test_code="result = await execute({})"
            )

            assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_sandbox_failure_returns_passed_false(self):
        """Sandbox returns failure: passed=False with stderr."""
        with patch("lib.skills.e2b_sandbox.handler.execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "status": "error",
                "stdout": [],
                "stderr": ["TypeError: 'NoneType' object is not callable"],
                "errors": [{"phase": "execution", "error": "TypeError"}],
            }

            result = await _test_in_sandbox(
                handler_code="async def execute(params): raise TypeError()",
                test_code="result = await execute({})"
            )

            assert result["passed"] is False
            assert len(result["stderr"]) > 0

    @pytest.mark.asyncio
    async def test_exception_returns_graceful_error(self):
        """Exception during sandbox: graceful error dict with passed=False."""
        with patch("lib.skills.e2b_sandbox.handler.execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = Exception("Sandbox connection failed")

            result = await _test_in_sandbox(
                handler_code="code",
                test_code="test"
            )

            assert result["passed"] is False
            assert "error" in result
            assert "Sandbox connection failed" in result["error"]


# =============================================================================
# Batch Pipeline Tests
# =============================================================================

class TestSkillGenerationBatch:
    """Tests for the batch gap-to-proposal pipeline."""

    @pytest.mark.asyncio
    async def test_batch_processes_open_gaps(self):
        """Should call generate_and_test_skill for each open gap."""
        with patch("backend.worker.jobs.asyncio") as mock_asyncio:
            # Mock get_open_gaps to return 2 gaps
            gaps = [
                {"id": "gap-1", "tool_name": "search_emails", "status": "open"},
                {"id": "gap-2", "tool_name": "calendar_create", "status": "open"},
            ]
            mock_asyncio.run.side_effect = [
                gaps,  # First call: get_open_gaps
                {"status": "proposed", "proposal_id": "prop-1"},  # Second: generate for gap-1
                {"status": "proposed", "proposal_id": "prop-2"},  # Third: generate for gap-2
            ]

            import os
            with patch.dict(os.environ, {"DEFAULT_USER_ID": "user-123"}):
                from backend.worker.jobs import run_skill_generation_batch
                result = run_skill_generation_batch()

            assert result["status"] == "completed"
            assert result["gaps_processed"] == 2
            assert result["proposals_created"] == 2
            assert result["failures"] == 0

    @pytest.mark.asyncio
    async def test_batch_limits_to_three(self):
        """Should process at most 3 gaps even if more are open."""
        with patch("backend.worker.jobs.asyncio") as mock_asyncio:
            gaps = [{"id": f"gap-{i}", "status": "open"} for i in range(5)]
            mock_asyncio.run.side_effect = [
                gaps,  # get_open_gaps returns 5
                {"status": "proposed"},  # gap-0
                {"status": "proposed"},  # gap-1
                {"status": "proposed"},  # gap-2
                # gap-3 and gap-4 should NOT be processed
            ]

            import os
            with patch.dict(os.environ, {"DEFAULT_USER_ID": "user-123"}):
                from backend.worker.jobs import run_skill_generation_batch
                result = run_skill_generation_batch()

            assert result["gaps_found"] == 5
            assert result["gaps_processed"] == 3
            assert result["proposals_created"] == 3

    @pytest.mark.asyncio
    async def test_batch_skips_without_user_id(self):
        """Should return skipped if DEFAULT_USER_ID not set."""
        import os
        with patch.dict(os.environ, {}, clear=True):
            # Ensure DEFAULT_USER_ID is not set
            os.environ.pop("DEFAULT_USER_ID", None)
            from backend.worker.jobs import run_skill_generation_batch
            result = run_skill_generation_batch()

        assert result["status"] == "skipped"
        assert "no DEFAULT_USER_ID" in result["reason"]

    @pytest.mark.asyncio
    async def test_batch_handles_generation_failure(self):
        """Should count failures when generate_and_test_skill fails."""
        with patch("backend.worker.jobs.asyncio") as mock_asyncio:
            gaps = [{"id": "gap-1", "status": "open"}]
            mock_asyncio.run.side_effect = [
                gaps,  # get_open_gaps
                {"status": "failed", "error": "Haiku API error"},  # generation failed
            ]

            import os
            with patch.dict(os.environ, {"DEFAULT_USER_ID": "user-123"}):
                from backend.worker.jobs import run_skill_generation_batch
                result = run_skill_generation_batch()

            assert result["status"] == "completed"
            assert result["failures"] == 1
            assert result["proposals_created"] == 0


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running skill generator service tests...")
    pytest.main([__file__, "-v"])
