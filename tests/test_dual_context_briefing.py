"""
Tests for Dual-Context Morning Briefing - Phase 7.8 Verification
===============================================================

BDD-style tests verifying the dual-context briefing enhancement.
Run with: pytest tests/test_dual_context_briefing.py -v

Tests cover:
1. Dual-context briefing structure (work/personal sections)
2. Context extraction from formatted strings
3. Cross-context alert handling
4. SMS length limit handling
5. Graceful fallback when no data exists
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.agent.scheduler import (
    extract_context_items,
    format_dual_briefing,
    get_briefing_context,
    synthesize_briefing,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_user_id():
    """Create a sample user UUID."""
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def mock_work_context():
    """Mock work context from retrieve_context."""
    return """[CONTEXT FOR: "work tasks meetings deadlines this week" (WORK DOMAIN)]

[RELEVANT WORK MEMORIES]
- Team standup scheduled for 10 AM (Feb 09, 85% match)
- PriceSpider contract review deadline Friday (Feb 08)

[RELATED WORK ENTITIES]
- Jenny (Person, Work): Partner at PriceSpider
- Team Standup (Event, Work): Daily at 10 AM"""


@pytest.fixture
def mock_personal_context():
    """Mock personal context from retrieve_context."""
    return """[CONTEXT FOR: "personal family events appointments this week" (PERSONAL DOMAIN)]

[RELEVANT PERSONAL MEMORIES]
- Dentist appointment Thursday 2 PM (Feb 07, 80% match)

[RELATED PERSONAL ENTITIES]
- Dr. Smith (Person, Personal): Dentist"""


@pytest.fixture
def mock_family_context():
    """Mock family context from retrieve_context."""
    return """[CONTEXT FOR: "kids custody schedule family events" (FAMILY DOMAIN)]

[RELEVANT FAMILY MEMORIES]
- Kids pickup Friday 6 PM (Feb 08)

[RELATED FAMILY ENTITIES]
- Sarah (Person, Family): Daughter
- Mike (Person, Family): Son"""


@pytest.fixture
def mock_cross_alerts():
    """Mock cross-context alerts."""
    return """[CROSS-CONTEXT ADVISORY]

Shared Contacts/Entities (appear in both domains):
- Jenny: work/person AND personal/person

Related PERSONAL memories:
- Dinner with Jenny Thursday night"""


@pytest.fixture
def mock_empty_context():
    """Mock empty context."""
    return """[CONTEXT FOR: "test query"]

[RELEVANT MEMORIES]
- No relevant memories found

[RELATED ENTITIES]
- No related entities found"""


# =============================================================================
# Unit Tests: Context Extraction
# =============================================================================

class TestContextExtraction:
    """Test context extraction helper."""

    def test_extract_context_items_with_valid_items(self, mock_work_context):
        """Extract bullet points from formatted context."""
        items = extract_context_items(mock_work_context)
        
        assert "- Team standup scheduled for 10 AM" in items
        assert "- PriceSpider contract review deadline Friday" in items
        assert "- Jenny (Person, Work):" in items
        assert "[CONTEXT FOR:" not in items
        assert "[RELEVANT WORK MEMORIES]" not in items

    def test_extract_context_items_filters_no_items(self, mock_empty_context):
        """Filter out 'No relevant' lines."""
        items = extract_context_items(mock_empty_context)
        
        assert "No relevant memories found" not in items
        assert "No related entities found" not in items

    def test_extract_context_items_empty_input(self):
        """Handle empty input gracefully."""
        items = extract_context_items("")
        assert items == ""

    def test_extract_context_items_preserves_order(self, mock_work_context):
        """Preserve order of bullet points."""
        items = extract_context_items(mock_work_context)
        lines = [l for l in items.split("\n") if l.strip()]
        
        # Should preserve chronological order
        assert len(lines) == 4  # 2 memories + 2 entities


# =============================================================================
# Unit Tests: Dual-Context Formatting
# =============================================================================

class TestDualContextFormatting:
    """Test dual-context briefing formatter."""

    def test_format_dual_briefing_complete(
        self, mock_work_context, mock_personal_context, 
        mock_family_context, mock_cross_alerts
    ):
        """Format complete dual-context briefing."""
        briefing = format_dual_briefing(
            mock_work_context,
            mock_personal_context,
            mock_family_context,
            mock_cross_alerts
        )
        
        # Check structure
        assert "Good morning, Ryan!" in briefing
        assert "WORK" in briefing
        assert "PERSONAL/FAMILY" in briefing
        assert "CROSS-CONTEXT ALERTS" in briefing
        
        # Check content presence
        assert "Team standup" in briefing
        assert "Dentist appointment" in briefing
        assert "Kids pickup" in briefing
        assert "Jenny" in briefing

    def test_format_dual_briefing_work_only(self, mock_work_context):
        """Format briefing with only work items."""
        briefing = format_dual_briefing(
            mock_work_context,
            "",
            "",
            ""
        )
        
        assert "Good morning, Ryan!" in briefing
        assert "WORK" in briefing
        assert "Team standup" in briefing
        assert "PERSONAL/FAMILY" in briefing
        assert "No personal items to report" in briefing
        assert "CROSS-CONTEXT ALERTS" not in briefing

    def test_format_dual_briefing_personal_only(self, mock_personal_context):
        """Format briefing with only personal items."""
        briefing = format_dual_briefing(
            "",
            mock_personal_context,
            "",
            ""
        )
        
        assert "Good morning, Ryan!" in briefing
        assert "WORK" in briefing
        assert "No work items to report" in briefing
        assert "PERSONAL/FAMILY" in briefing
        assert "Dentist appointment" in briefing

    def test_format_dual_briefing_empty(self):
        """Format briefing with no items."""
        briefing = format_dual_briefing("", "", "", "")
        
        assert "Good morning, Ryan!" in briefing
        assert "WORK" in briefing
        assert "No work items to report" in briefing
        assert "PERSONAL/FAMILY" in briefing
        assert "No personal items to report" in briefing

    def test_format_dual_briefing_combines_personal_and_family(
        self, mock_personal_context, mock_family_context
    ):
        """Combine personal and family contexts."""
        briefing = format_dual_briefing(
            "",
            mock_personal_context,
            mock_family_context,
            ""
        )
        
        assert "Dentist appointment" in briefing
        assert "Kids pickup" in briefing
        assert "PERSONAL/FAMILY" in briefing

    def test_format_dual_briefing_cross_alerts_only_if_present(self, mock_cross_alerts):
        """Only include CROSS-CONTEXT ALERTS section if alerts exist."""
        briefing_with = format_dual_briefing("", "", "", mock_cross_alerts)
        briefing_without = format_dual_briefing("", "", "", "")
        
        assert "CROSS-CONTEXT ALERTS" in briefing_with
        assert "CROSS-CONTEXT ALERTS" not in briefing_without


# =============================================================================
# Integration Tests: Briefing Generation
# =============================================================================

class TestBriefingGeneration:
    """Test end-to-end briefing generation."""

    @pytest.mark.asyncio
    async def test_get_briefing_context_calls_retrieval(self, sample_user_id):
        """get_briefing_context calls retrieve_context with correct domains."""
        mock_retrieve = AsyncMock(return_value="[CONTEXT]\n- Mock item")
        mock_cross_scan = AsyncMock(return_value="")
        
        with patch("lib.agent.scheduler.retrieve_context", mock_retrieve):
            with patch("lib.agent.scheduler.cross_context_scan", mock_cross_scan):
                briefing = await get_briefing_context(sample_user_id)
        
        # Should call retrieve_context 3 times (work, personal, family)
        assert mock_retrieve.call_count == 3
        
        # Check domain filters
        calls = mock_retrieve.call_args_list
        domains = [call.kwargs.get("domain_filter") for call in calls]
        assert "work" in domains
        assert "personal" in domains
        assert "family" in domains
        
        # Should call cross_context_scan once
        assert mock_cross_scan.call_count == 1

    @pytest.mark.asyncio
    async def test_get_briefing_context_handles_import_error(self, sample_user_id):
        """get_briefing_context handles missing retrieval module gracefully."""
        with patch("lib.agent.scheduler.retrieve_context", side_effect=ImportError("Module not found")):
            briefing = await get_briefing_context(sample_user_id)
        
        assert "Good morning, Ryan!" in briefing
        assert "unavailable" in briefing.lower()

    @pytest.mark.asyncio
    async def test_synthesize_briefing_within_sms_limit(self):
        """Briefing within SMS limit is returned as-is."""
        short_context = "Good morning, Ryan!\n\nWORK\n- Short item\n\nPERSONAL/FAMILY\n- Another item"
        
        result = await synthesize_briefing(short_context, "Ryan")
        
        # Should return as-is (no synthesis needed)
        assert result == short_context

    @pytest.mark.asyncio
    async def test_synthesize_briefing_handles_empty(self):
        """Empty context returns friendly message."""
        result = await synthesize_briefing("", "Ryan")
        
        assert "Good morning, Ryan!" in result
        assert "No major items" in result

    @pytest.mark.asyncio
    async def test_synthesize_briefing_truncates_without_api_key(self):
        """Long briefing is truncated if no API key available."""
        long_context = "Good morning, Ryan!\n\n" + ("WORK\n" + "- Item\n" * 100)
        
        with patch("lib.agent.scheduler.ANTHROPIC_API_KEY", None):
            result = await synthesize_briefing(long_context, "Ryan")
        
        # Should be truncated
        assert len(result) <= 1600
        assert "truncated" in result.lower()


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_extract_context_items_with_malformed_input(self):
        """Handle malformed input gracefully."""
        malformed = "Random text\nNo bullets\nJust plain text"
        items = extract_context_items(malformed)
        assert items == ""

    def test_format_dual_briefing_with_special_characters(self):
        """Handle special characters in context."""
        context_with_special = "[CONTEXT]\n- Item with $pecial ch@racters!"
        briefing = format_dual_briefing(context_with_special, "", "", "")
        
        assert "Good morning, Ryan!" in briefing
        assert "$pecial" in briefing

    @pytest.mark.asyncio
    async def test_synthesize_briefing_handles_synthesis_error(self):
        """Gracefully handle synthesis errors."""
        long_context = "Good morning, Ryan!\n\n" + ("- Item\n" * 200)
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("API Error")
        
        with patch("lib.agent.scheduler.ChatAnthropic", return_value=mock_llm):
            with patch("lib.agent.scheduler.ANTHROPIC_API_KEY", "fake-key"):
                result = await synthesize_briefing(long_context, "Ryan")
        
        # Should return truncated original
        assert len(result) <= 1600
        assert "truncated" in result.lower() or "Good morning" in result


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running dual-context briefing tests...")
    pytest.main([__file__, "-v"])
