"""
Tests for Skill Digest Service
===============================

Unit tests for the weekly skill acquisition digest service.
Tests digest generation and Slack webhook sending with full mocking.

Run with: pytest tests/test_skill_digest.py -v
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.skill_digest import (
    generate_weekly_digest,
    send_weekly_digest,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for digest queries."""
    with patch("backend.services.skill_digest._get_supabase_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_httpx():
    """Mock httpx for Slack webhook calls."""
    with patch("httpx.AsyncClient") as mock:
        yield mock


# =============================================================================
# Test: generate_weekly_digest()
# =============================================================================

class TestGenerateWeeklyDigest:
    """Test the generate_weekly_digest async function."""

    @pytest.mark.asyncio
    async def test_no_supabase_returns_skipped(self):
        """Supabase not configured returns skipped status."""
        with patch("backend.services.skill_digest._get_supabase_client", return_value=None):
            result = await generate_weekly_digest()

            assert result["status"] == "skipped"
            assert result["reason"] == "Supabase not configured"

    @pytest.mark.asyncio
    async def test_no_activity_all_counts_zero(self, mock_supabase):
        """No activity: all counts zero, summary text contains 'No new gaps'."""
        # Mock all queries returning empty results
        mock_result = MagicMock()
        mock_result.count = 0
        mock_result.data = []

        # Create a chain that handles all table queries
        def table_side_effect(table_name):
            mock_table = MagicMock()
            mock_chain = mock_table.select.return_value
            
            if table_name == "skill_gaps":
                mock_chain.gte.return_value.execute.return_value = mock_result
            elif table_name == "skill_proposals":
                mock_chain.eq.return_value.execute.return_value = mock_result
            elif table_name == "skill_versions":
                # Handle both promoted and disabled queries
                mock_chain.gte.return_value.eq.return_value.execute.return_value = mock_result
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        result = await generate_weekly_digest()

        assert result["status"] == "generated"
        assert result["gaps_opened"] == 0
        assert result["proposals_pending"] == 0
        assert result["skills_promoted"] == 0
        assert result["skills_disabled"] == 0
        assert "No new gaps detected" in result["summary_text"]

    @pytest.mark.asyncio
    async def test_with_activity_correct_counts(self, mock_supabase):
        """With gaps + proposals + promotions: correct counts and formatted text."""
        # Mock gaps query
        mock_gaps = MagicMock()
        mock_gaps.count = 3
        mock_gaps.data = [
            {"id": "gap-1", "tool_name": "tool1"},
            {"id": "gap-2", "tool_name": "tool2"},
            {"id": "gap-3", "tool_name": "tool3"},
        ]

        # Mock proposals query
        mock_proposals = MagicMock()
        mock_proposals.count = 2
        mock_proposals.data = [
            {"id": "prop-1", "skill_name": "skill1"},
            {"id": "prop-2", "skill_name": "skill2"},
        ]

        # Mock promoted versions
        mock_promoted = MagicMock()
        mock_promoted.count = 1
        mock_promoted.data = [{"id": "ver-1", "skill_name": "skill1", "version": "1.0.0"}]

        # Mock disabled versions
        mock_disabled = MagicMock()
        mock_disabled.count = 0
        mock_disabled.data = []

        # Track which field is being filtered (promoted_at vs disabled_at)
        call_tracker = {"skill_versions_calls": 0}

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_gaps":
                mock_table.select.return_value.gte.return_value.execute.return_value = mock_gaps
            elif table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_proposals
            elif table_name == "skill_versions":
                # First call is for promoted, second for disabled
                if call_tracker["skill_versions_calls"] == 0:
                    call_tracker["skill_versions_calls"] += 1
                    # Promoted query
                    mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_promoted
                else:
                    # Disabled query
                    mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_disabled
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        result = await generate_weekly_digest()

        assert result["status"] == "generated"
        assert result["gaps_opened"] == 3
        assert result["proposals_pending"] == 2
        assert result["skills_promoted"] == 1
        assert result["skills_disabled"] == 0
        assert "3 new gaps detected" in result["summary_text"]
        assert "2 proposals awaiting review" in result["summary_text"]
        assert "1 skills promoted" in result["summary_text"]

    @pytest.mark.asyncio
    async def test_disabled_skills_included_in_summary(self, mock_supabase):
        """Disabled skills included in summary."""
        # Mock all empty except disabled
        mock_empty = MagicMock()
        mock_empty.count = 0
        mock_empty.data = []

        mock_disabled = MagicMock()
        mock_disabled.count = 2
        mock_disabled.data = [
            {"id": "ver-1", "skill_name": "old_skill"},
            {"id": "ver-2", "skill_name": "broken_skill"},
        ]

        # Track which skill_versions call is being made
        call_tracker = {"skill_versions_calls": 0}

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_gaps":
                mock_table.select.return_value.gte.return_value.execute.return_value = mock_empty
            elif table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_empty
            elif table_name == "skill_versions":
                # First call is for promoted, second for disabled
                if call_tracker["skill_versions_calls"] == 0:
                    call_tracker["skill_versions_calls"] += 1
                    # Promoted query returns empty
                    mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_empty
                else:
                    # Disabled query returns data
                    mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_disabled
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        result = await generate_weekly_digest()

        assert result["status"] == "generated"
        assert result["skills_disabled"] == 2
        assert "2 skills disabled" in result["summary_text"]


# =============================================================================
# Test: send_weekly_digest()
# =============================================================================

class TestSendWeeklyDigest:
    """Test the send_weekly_digest async function."""

    @pytest.mark.asyncio
    async def test_no_activity_returns_skipped(self, mock_supabase, mock_httpx):
        """No activity returns skipped, no HTTP call."""
        # Mock digest with no activity
        mock_empty = MagicMock()
        mock_empty.count = 0
        mock_empty.data = []

        def table_side_effect(table_name):
            mock_table = MagicMock()
            mock_chain = mock_table.select.return_value
            
            if table_name == "skill_gaps":
                mock_chain.gte.return_value.execute.return_value = mock_empty
            elif table_name == "skill_proposals":
                mock_chain.eq.return_value.execute.return_value = mock_empty
            elif table_name == "skill_versions":
                mock_chain.gte.return_value.eq.return_value.execute.return_value = mock_empty
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        result = await send_weekly_digest()

        assert result["status"] == "skipped"
        assert result["reason"] == "no activity"
        # Verify no HTTP call was made
        mock_httpx.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_webhook_url_returns_skipped(self, mock_supabase):
        """No SLACK_WEBHOOK_URL returns skipped."""
        # Mock digest with activity
        mock_gaps = MagicMock()
        mock_gaps.count = 1
        mock_gaps.data = [{"id": "gap-1", "tool_name": "tool1"}]

        mock_empty = MagicMock()
        mock_empty.count = 0
        mock_empty.data = []

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_gaps":
                mock_table.select.return_value.gte.return_value.execute.return_value = mock_gaps
            elif table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_empty
            elif table_name == "skill_versions":
                mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_empty
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": ""}, clear=False):
            result = await send_weekly_digest()

            assert result["status"] == "skipped"
            assert result["reason"] == "no webhook configured"

    @pytest.mark.asyncio
    async def test_success_posts_to_webhook(self, mock_supabase, mock_httpx):
        """Success POSTs to webhook with summary_text, returns sent."""
        # Mock digest with activity
        mock_gaps = MagicMock()
        mock_gaps.count = 2
        mock_gaps.data = [
            {"id": "gap-1", "tool_name": "tool1"},
            {"id": "gap-2", "tool_name": "tool2"},
        ]

        mock_empty = MagicMock()
        mock_empty.count = 0
        mock_empty.data = []

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_gaps":
                mock_table.select.return_value.gte.return_value.execute.return_value = mock_gaps
            elif table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_empty
            elif table_name == "skill_versions":
                mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_empty
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        # Mock httpx client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        mock_httpx.return_value = mock_client

        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}, clear=False):
            result = await send_weekly_digest()

            assert result["status"] == "sent"
            assert result["gaps_opened"] == 2
            # Verify webhook was called
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "https://hooks.slack.com/test" in str(call_args)
            assert call_args[1]["json"]["text"]  # Summary text was sent

    @pytest.mark.asyncio
    async def test_webhook_http_error_returns_failed(self, mock_supabase, mock_httpx):
        """Webhook HTTP error returns failed with error message."""
        # Mock digest with activity
        mock_gaps = MagicMock()
        mock_gaps.count = 1
        mock_gaps.data = [{"id": "gap-1", "tool_name": "tool1"}]

        mock_empty = MagicMock()
        mock_empty.count = 0
        mock_empty.data = []

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_gaps":
                mock_table.select.return_value.gte.return_value.execute.return_value = mock_gaps
            elif table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.execute.return_value = mock_empty
            elif table_name == "skill_versions":
                mock_table.select.return_value.gte.return_value.eq.return_value.execute.return_value = mock_empty
            
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        # Mock httpx client that raises an error
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=Exception("Connection failed"))
        
        mock_httpx.return_value = mock_client

        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}, clear=False):
            result = await send_weekly_digest()

            assert result["status"] == "failed"
            assert "Connection failed" in result["error"]


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running skill digest service tests...")
    pytest.main([__file__, "-v"])
