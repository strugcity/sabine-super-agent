"""
Tests for Skill Effectiveness Tracker
=======================================

Unit tests for the skill effectiveness tracking service.
Tests all functions with full mocking of Supabase client.

Run with: pytest tests/test_skill_effectiveness.py -v
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.skill_effectiveness import (
    auto_disable_underperformers,
    compute_effectiveness,
    record_skill_execution,
    score_all_skills,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for skill effectiveness."""
    with patch("backend.services.skill_effectiveness._get_supabase_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def sample_executions_all_success() -> List[Dict[str, Any]]:
    """Sample execution records: all success, no edits, no repeats, all gratitude."""
    return [
        {
            "execution_status": "success",
            "user_edited_output": False,
            "user_sent_thank_you": True,
            "user_repeated_request": False,
        }
        for _ in range(10)
    ]


@pytest.fixture
def sample_executions_all_failure() -> List[Dict[str, Any]]:
    """Sample execution records: all failures, all edits, all repeats, no gratitude."""
    return [
        {
            "execution_status": "error",
            "user_edited_output": True,
            "user_sent_thank_you": False,
            "user_repeated_request": True,
        }
        for _ in range(10)
    ]


@pytest.fixture
def sample_executions_mixed() -> List[Dict[str, Any]]:
    """Sample execution records: 7 success / 3 error, 2 edits, 1 repeat, 5 gratitude."""
    base = []
    for i in range(10):
        base.append({
            "execution_status": "success" if i < 7 else "error",
            "user_edited_output": i < 2,
            "user_sent_thank_you": i < 5,
            "user_repeated_request": i == 9,
        })
    return base


# =============================================================================
# Test: record_skill_execution()
# =============================================================================

class TestRecordSkillExecution:
    """Test the record_skill_execution async function."""

    @pytest.mark.asyncio
    async def test_success_insert_returns_id(self, mock_supabase):
        """Successful insert returns the execution UUID."""
        mock_result = MagicMock()
        mock_result.data = [{"id": "exec-123"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_result

        result = await record_skill_execution(
            skill_version_id="version-abc",
            user_id="user-123",
            execution_status="success",
        )

        assert result == "exec-123"
        mock_supabase.table.assert_called_with("skill_executions")

    @pytest.mark.asyncio
    async def test_error_handling_returns_none(self, mock_supabase):
        """On Supabase error, returns None and does not raise."""
        mock_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
            "DB connection error"
        )

        result = await record_skill_execution(
            skill_version_id="version-abc",
            user_id="user-123",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_none_on_empty_insert_result(self, mock_supabase):
        """Returns None when insert returns empty data."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_result

        result = await record_skill_execution(
            skill_version_id="version-abc",
            user_id="user-123",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_all_params_passed_correctly(self, mock_supabase):
        """All optional params are included in the insert payload."""
        mock_result = MagicMock()
        mock_result.data = [{"id": "exec-456"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_result

        result = await record_skill_execution(
            skill_version_id="version-abc",
            user_id="user-123",
            session_id="session-xyz",
            execution_status="error",
            user_edited_output=True,
            user_sent_thank_you=False,
            user_repeated_request=True,
            conversation_turns=5,
            execution_time_ms=1234,
            error_message="Something went wrong",
        )

        assert result == "exec-456"

        # Verify the insert was called with the right data
        insert_call = mock_supabase.table.return_value.insert.call_args
        payload = insert_call[0][0]
        assert payload["skill_version_id"] == "version-abc"
        assert payload["user_id"] == "user-123"
        assert payload["session_id"] == "session-xyz"
        assert payload["execution_status"] == "error"
        assert payload["user_edited_output"] is True
        assert payload["user_sent_thank_you"] is False
        assert payload["user_repeated_request"] is True
        assert payload["conversation_turns"] == 5
        assert payload["execution_time_ms"] == 1234
        assert payload["error_message"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_no_supabase_returns_none(self):
        """When Supabase not configured, returns None."""
        with patch("backend.services.skill_effectiveness._get_supabase_client", return_value=None):
            result = await record_skill_execution(
                skill_version_id="version-abc",
                user_id="user-123",
            )
            assert result is None


# =============================================================================
# Test: compute_effectiveness()
# =============================================================================

class TestComputeEffectiveness:
    """Test the compute_effectiveness async function."""

    @pytest.mark.asyncio
    async def test_all_success_signals_perfect_score(
        self, mock_supabase, sample_executions_all_success,
    ):
        """All success, no edits, no repeats, all gratitude yields maximum score."""
        mock_result = MagicMock()
        mock_result.data = sample_executions_all_success
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_result

        result = await compute_effectiveness("version-abc")

        assert result["score"] is not None
        # Perfect score: 0.40*1.0 + 0.25*(1-0) + 0.20*(1-0) + 0.15*1.0 = 1.0
        assert result["score"] == 1.0
        assert result["total_executions"] == 10
        assert result["success_rate"] == 1.0
        assert result["edit_rate"] == 0.0
        assert result["repeat_rate"] == 0.0
        assert result["gratitude_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_all_failure_signals_minimum_score(
        self, mock_supabase, sample_executions_all_failure,
    ):
        """All failures, all edits, all repeats, no gratitude yields minimum score."""
        mock_result = MagicMock()
        mock_result.data = sample_executions_all_failure
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_result

        result = await compute_effectiveness("version-abc")

        assert result["score"] is not None
        # Worst score: 0.40*0 + 0.25*(1-1) + 0.20*(1-1) + 0.15*0 = 0.0
        assert result["score"] == 0.0
        assert result["success_rate"] == 0.0
        assert result["edit_rate"] == 1.0
        assert result["repeat_rate"] == 1.0
        assert result["gratitude_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_signals_correct_calculation(
        self, mock_supabase, sample_executions_mixed,
    ):
        """Mixed signals produce correct intermediate score."""
        mock_result = MagicMock()
        mock_result.data = sample_executions_mixed
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_result

        result = await compute_effectiveness("version-abc")

        assert result["score"] is not None
        assert result["total_executions"] == 10
        assert result["success_rate"] == 0.7
        assert result["edit_rate"] == 0.2
        assert result["repeat_rate"] == 0.1
        assert result["gratitude_rate"] == 0.5

        # 0.40*0.7 + 0.25*(1-0.2) + 0.20*(1-0.1) + 0.15*0.5
        # = 0.28 + 0.20 + 0.18 + 0.075 = 0.735
        expected = round(0.40 * 0.7 + 0.25 * 0.8 + 0.20 * 0.9 + 0.15 * 0.5, 4)
        assert result["score"] == expected

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none_score(self, mock_supabase):
        """Fewer than 5 executions returns score=None with reason."""
        mock_result = MagicMock()
        mock_result.data = [
            {"execution_status": "success", "user_edited_output": False,
             "user_sent_thank_you": True, "user_repeated_request": False}
            for _ in range(3)
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_result

        result = await compute_effectiveness("version-abc")

        assert result["score"] is None
        assert result["reason"] == "insufficient_data"
        assert result["total_executions"] == 3

    @pytest.mark.asyncio
    async def test_empty_data_returns_insufficient(self, mock_supabase):
        """Empty execution data returns insufficient_data."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = mock_result

        result = await compute_effectiveness("version-abc")

        assert result["score"] is None
        assert result["reason"] == "insufficient_data"
        assert result["total_executions"] == 0


# =============================================================================
# Test: score_all_skills()
# =============================================================================

class TestScoreAllSkills:
    """Test the score_all_skills async function."""

    @pytest.mark.asyncio
    async def test_scores_multiple_skills(self, mock_supabase):
        """Scores multiple active skills and returns results."""
        # Mock fetching active skill versions
        versions_result = MagicMock()
        versions_result.data = [
            {"id": "v1", "skill_name": "email_search", "version": "1.0.0"},
            {"id": "v2", "skill_name": "calendar_check", "version": "2.0.0"},
        ]

        # Mock execution data for compute_effectiveness
        exec_result = MagicMock()
        exec_result.data = [
            {"execution_status": "success", "user_edited_output": False,
             "user_sent_thank_you": True, "user_repeated_request": False}
            for _ in range(10)
        ]

        # Mock the update call
        update_result = MagicMock()
        update_result.data = [{}]

        # Configure chain for select().eq().eq().execute()
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = versions_result
        # Configure chain for select().eq().gte().execute() (compute_effectiveness)
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = exec_result
        # Configure chain for update().eq().execute()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = update_result

        result = await score_all_skills("user-123")

        assert len(result) == 2
        assert result[0]["skill_name"] == "email_search"
        assert result[1]["skill_name"] == "calendar_check"

    @pytest.mark.asyncio
    async def test_updates_db_with_scores(self, mock_supabase):
        """Updates skill_versions with effectiveness_score and total_executions."""
        versions_result = MagicMock()
        versions_result.data = [
            {"id": "v1", "skill_name": "test_skill", "version": "1.0.0"},
        ]

        exec_result = MagicMock()
        exec_result.data = [
            {"execution_status": "success", "user_edited_output": False,
             "user_sent_thank_you": True, "user_repeated_request": False}
            for _ in range(10)
        ]

        update_result = MagicMock()
        update_result.data = [{}]

        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = versions_result
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = exec_result
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = update_result

        result = await score_all_skills("user-123")

        assert len(result) == 1
        # Verify update was called on skill_versions table
        mock_supabase.table.return_value.update.assert_called()

    @pytest.mark.asyncio
    async def test_handles_empty_skills(self, mock_supabase):
        """Returns empty list when no active skills found."""
        versions_result = MagicMock()
        versions_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = versions_result

        result = await score_all_skills("user-123")

        assert result == []


# =============================================================================
# Test: auto_disable_underperformers()
# =============================================================================

class TestAutoDisableUnderperformers:
    """Test the auto_disable_underperformers async function."""

    @pytest.mark.asyncio
    async def test_disables_below_threshold(self, mock_supabase):
        """Disables skills below effectiveness threshold."""
        # Mock underperformer query
        underperformer_result = MagicMock()
        underperformer_result.data = [
            {
                "id": "v1",
                "skill_name": "bad_skill",
                "version": "1.0.0",
                "effectiveness_score": 0.15,
                "total_executions": 20,
            },
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.gte.return_value.execute.return_value = underperformer_result

        with patch("backend.services.skill_effectiveness.disable_skill", new_callable=AsyncMock) as mock_disable, \
             patch("backend.services.skill_effectiveness.log_tool_execution", new_callable=AsyncMock) as mock_audit:
            # Patch the lazy imports inside auto_disable_underperformers
            with patch("backend.services.skill_promotion.disable_skill", new_callable=AsyncMock) as mock_promo_disable:
                mock_promo_disable.return_value = {"status": "disabled", "skill_name": "bad_skill", "version": "1.0.0"}

                # We need to patch at the point of import in auto_disable
                with patch.dict("sys.modules", {}):
                    # Re-read the module to patch properly
                    pass

        # Simpler approach: mock the entire disable_skill import
        with patch("backend.services.skill_promotion.disable_skill", new_callable=AsyncMock) as mock_disable, \
             patch("backend.services.audit_logging.log_tool_execution", new_callable=AsyncMock) as mock_audit:
            mock_disable.return_value = {"status": "disabled"}

            result = await auto_disable_underperformers("user-123", threshold=0.3, min_executions=10)

            assert len(result) == 1
            assert result[0]["skill_name"] == "bad_skill"
            assert result[0]["reason"] == "auto_disabled_low_effectiveness"
            mock_disable.assert_called_once_with("v1")

    @pytest.mark.asyncio
    async def test_skips_above_threshold(self, mock_supabase):
        """Does not disable skills above threshold (query returns empty)."""
        underperformer_result = MagicMock()
        underperformer_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.gte.return_value.execute.return_value = underperformer_result

        result = await auto_disable_underperformers("user-123", threshold=0.3, min_executions=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_skips_insufficient_executions(self, mock_supabase):
        """Does not disable skills without enough executions (query returns empty)."""
        underperformer_result = MagicMock()
        underperformer_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.gte.return_value.execute.return_value = underperformer_result

        result = await auto_disable_underperformers("user-123", threshold=0.3, min_executions=50)

        assert result == []

    @pytest.mark.asyncio
    async def test_no_skills_to_disable(self, mock_supabase):
        """Returns empty list when no skills need disabling."""
        underperformer_result = MagicMock()
        underperformer_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.gte.return_value.execute.return_value = underperformer_result

        result = await auto_disable_underperformers("user-123")

        assert result == []

    @pytest.mark.asyncio
    async def test_no_supabase_returns_empty(self):
        """When Supabase not configured, returns empty list."""
        with patch("backend.services.skill_effectiveness._get_supabase_client", return_value=None):
            result = await auto_disable_underperformers("user-123")
            assert result == []


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running skill effectiveness service tests...")
    pytest.main([__file__, "-v"])
