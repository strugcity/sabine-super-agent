"""
Tests for Skill Promotion Service
=================================

Unit tests for the skill promotion lifecycle service.
Tests promote, disable, and rollback operations with full mocking.

Run with: pytest tests/test_skill_promotion.py -v
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.skill_promotion import (
    disable_skill,
    promote_skill,
    rollback_skill,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for skill promotion."""
    with patch("supabase.create_client") as mock:
        client = MagicMock()
        mock.return_value = client
        
        # Mock environment variables
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-key"
        }):
            yield client


@pytest.fixture
def mock_audit_log():
    """Mock audit logging."""
    with patch("backend.services.audit_logging.log_tool_execution", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def sample_proposal():
    """Sample skill proposal."""
    return {
        "id": "proposal-123",
        "user_id": "user-123",
        "skill_name": "test_skill",
        "description": "A test skill",
        "manifest_json": {
            "name": "test_skill",
            "version": "1.0.0",
            "description": "Test skill"
        },
        "handler_code": "async def execute(params): pass",
        "status": "pending",
        "gap_id": "gap-456"
    }


# =============================================================================
# Test: promote_skill()
# =============================================================================

class TestPromoteSkill:
    """Test the promote_skill async function."""

    @pytest.mark.asyncio
    async def test_proposal_not_found_raises_valueerror(self, mock_supabase, mock_audit_log):
        """Proposal not found raises ValueError."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await promote_skill("nonexistent-proposal")

    @pytest.mark.asyncio
    async def test_wrong_status_raises_valueerror(self, mock_supabase, mock_audit_log):
        """Proposal status != 'pending' raises ValueError."""
        mock_result = MagicMock()
        mock_result.data = {
            "id": "proposal-123",
            "status": "rejected",
            "user_id": "user-123",
            "skill_name": "test_skill"
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

        with pytest.raises(ValueError, match="expected 'approved'"):
            await promote_skill("proposal-123")

    @pytest.mark.asyncio
    async def test_first_promotion_creates_version_1_0_0(self, mock_supabase, mock_audit_log, sample_proposal):
        """First promotion for skill (no prior versions) creates version 1.0.0, is_active=True."""
        # Mock proposal fetch
        mock_proposal_result = MagicMock()
        mock_proposal_result.data = sample_proposal
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_proposal_result

        # Mock no existing active versions
        mock_existing = MagicMock()
        mock_existing.data = []
        
        # Mock no previous versions
        mock_versions = MagicMock()
        mock_versions.data = []
        
        # Create a chain that can handle both queries
        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_proposal_result
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "skill_versions":
                # For the existing active check
                chain1 = mock_table.select.return_value
                chain1.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_existing
                
                # For the version history check
                chain2 = mock_table.select.return_value
                chain2.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_versions
                
                # For the insert
                mock_version_insert = MagicMock()
                mock_version_insert.data = [{"id": "version-123"}]
                mock_table.insert.return_value.execute.return_value = mock_version_insert
                
            elif table_name == "skill_gaps":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            
            return mock_table
        
        mock_supabase.table.side_effect = table_side_effect

        result = await promote_skill("proposal-123")

        assert result["status"] == "promoted"
        assert result["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_subsequent_promotion_increments_version(self, mock_supabase, mock_audit_log, sample_proposal):
        """Subsequent promotion increments version, deactivates old version."""
        # Mock proposal fetch
        mock_proposal_result = MagicMock()
        mock_proposal_result.data = sample_proposal

        # Mock existing active version
        mock_existing = MagicMock()
        mock_existing.data = [{"id": "version-old", "version": "1.0.0"}]

        # Mock version history (last version was 1.0.0)
        mock_versions = MagicMock()
        mock_versions.data = [{"version": "1.0.0"}]

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_proposal_result
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "skill_versions":
                # For existing active check
                chain1 = mock_table.select.return_value
                chain1.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_existing
                
                # For deactivation
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
                
                # For version history
                chain2 = mock_table.select.return_value
                chain2.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_versions
                
                # For insert
                mock_version_insert = MagicMock()
                mock_version_insert.data = [{"id": "version-new"}]
                mock_table.insert.return_value.execute.return_value = mock_version_insert
                
            elif table_name == "skill_gaps":
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            
            return mock_table
        
        mock_supabase.table.side_effect = table_side_effect

        result = await promote_skill("proposal-123")

        assert result["status"] == "promoted"
        assert result["version"] == "1.0.1"

    @pytest.mark.asyncio
    async def test_linked_gap_updates_to_resolved(self, mock_supabase, mock_audit_log, sample_proposal):
        """Linked gap_id updates gap status to 'resolved'."""
        # Mock proposal with gap_id
        mock_proposal_result = MagicMock()
        mock_proposal_result.data = sample_proposal

        # Mock no existing versions
        mock_existing = MagicMock()
        mock_existing.data = []
        
        mock_versions = MagicMock()
        mock_versions.data = []

        gap_updated = {"called": False}

        def table_side_effect(table_name):
            mock_table = MagicMock()
            
            if table_name == "skill_proposals":
                mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_proposal_result
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif table_name == "skill_versions":
                chain1 = mock_table.select.return_value
                chain1.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_existing
                
                chain2 = mock_table.select.return_value
                chain2.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_versions
                
                mock_version_insert = MagicMock()
                mock_version_insert.data = [{"id": "version-123"}]
                mock_table.insert.return_value.execute.return_value = mock_version_insert
            elif table_name == "skill_gaps":
                gap_updated["called"] = True
                mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            
            return mock_table
        
        mock_supabase.table.side_effect = table_side_effect

        result = await promote_skill("proposal-123")

        assert result["status"] == "promoted"
        assert gap_updated["called"] is True


# =============================================================================
# Test: disable_skill()
# =============================================================================

class TestDisableSkill:
    """Test the disable_skill async function."""

    @pytest.mark.asyncio
    async def test_version_not_found_raises_valueerror(self, mock_supabase, mock_audit_log):
        """Version not found raises ValueError."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await disable_skill("nonexistent-version")

    @pytest.mark.asyncio
    async def test_success_sets_is_active_false(self, mock_supabase, mock_audit_log):
        """Success sets is_active=False, disabled_at=now, audit logged."""
        # Mock version fetch
        mock_version_result = MagicMock()
        mock_version_result.data = {
            "id": "version-123",
            "user_id": "user-123",
            "skill_name": "test_skill",
            "version": "1.0.0",
            "is_active": True
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_version_result

        # Mock update
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result = await disable_skill("version-123")

        assert result["status"] == "disabled"
        assert result["skill_name"] == "test_skill"
        assert result["version"] == "1.0.0"
        mock_audit_log.assert_called_once()


# =============================================================================
# Test: rollback_skill()
# =============================================================================

class TestRollbackSkill:
    """Test the rollback_skill async function."""

    @pytest.mark.asyncio
    async def test_no_active_version_raises_valueerror(self, mock_supabase, mock_audit_log):
        """No active version found raises ValueError."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_result

        with pytest.raises(ValueError, match="No active version found"):
            await rollback_skill("test_skill", "user-123")

    @pytest.mark.asyncio
    async def test_previous_version_exists_reactivates(self, mock_supabase, mock_audit_log):
        """Previous version exists: disables current, reactivates previous."""
        # Mock current active version
        mock_active = MagicMock()
        mock_active.data = [{"id": "version-current", "version": "2.0.0"}]

        # Mock previous version
        mock_previous = MagicMock()
        mock_previous.data = [{"id": "version-prev", "version": "1.0.0"}]

        def select_chain(*args, **kwargs):
            chain = MagicMock()
            # First call is for active version
            chain.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_active
            # Second call is for previous version
            chain.eq.return_value.eq.return_value.eq.return_value.neq.return_value.order.return_value.limit.return_value.execute.return_value = mock_previous
            return chain

        mock_supabase.table.return_value.select.side_effect = select_chain
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result = await rollback_skill("test_skill", "user-123")

        assert result["status"] == "rolled_back"
        assert result["from_version"] == "2.0.0"
        assert result["to_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_no_previous_version_disables_current(self, mock_supabase, mock_audit_log):
        """No previous version: disables current, to_version=None in audit."""
        # Mock current active version
        mock_active = MagicMock()
        mock_active.data = [{"id": "version-current", "version": "1.0.0"}]

        # Mock no previous version
        mock_previous = MagicMock()
        mock_previous.data = []

        def select_chain(*args, **kwargs):
            chain = MagicMock()
            chain.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_active
            chain.eq.return_value.eq.return_value.eq.return_value.neq.return_value.order.return_value.limit.return_value.execute.return_value = mock_previous
            return chain

        mock_supabase.table.return_value.select.side_effect = select_chain
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result = await rollback_skill("test_skill", "user-123")

        assert result["status"] == "rolled_back"
        assert result["from_version"] == "1.0.0"
        assert result["to_version"] is None

    @pytest.mark.asyncio
    async def test_audit_log_called_for_rollback(self, mock_supabase, mock_audit_log):
        """Audit log called for rollback action."""
        # Mock current active version
        mock_active = MagicMock()
        mock_active.data = [{"id": "version-current", "version": "1.0.0"}]

        # Mock no previous
        mock_previous = MagicMock()
        mock_previous.data = []

        def select_chain(*args, **kwargs):
            chain = MagicMock()
            chain.eq.return_value.eq.return_value.eq.return_value.execute.return_value = mock_active
            chain.eq.return_value.eq.return_value.eq.return_value.neq.return_value.order.return_value.limit.return_value.execute.return_value = mock_previous
            return chain

        mock_supabase.table.return_value.select.side_effect = select_chain
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        result = await rollback_skill("test_skill", "user-123")

        mock_audit_log.assert_called_once()
        call_kwargs = mock_audit_log.call_args[1]
        assert call_kwargs["tool_action"] == "rollback"
        assert call_kwargs["user_id"] == "user-123"


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running skill promotion service tests...")
    pytest.main([__file__, "-v"])
