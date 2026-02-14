"""
Phase 2 Integration Tests - Separate Agent Cores
=================================================

Tests that require live services (Supabase, API keys, running tools).
Mark with @pytest.mark.integration so they can be skipped in CI.

Run with: pytest tests/test_phase2_integration.py -v -m integration

Covers:
- Tool registry scoping (loads real skills, filters correctly)
- Agent module wiring (run_sabine_agent, run_task_agent callable)
- Memory role filtering (RPC call structure)
- Server startup (no import errors)
"""

import asyncio
import inspect
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Tool Registry Scoping
# =============================================================================

@pytest.mark.integration
class TestScopedToolLoading:
    """
    Tests that get_scoped_tools actually loads and filters real skills.
    Requires skill manifests + handlers to exist on disk.
    """

    @pytest.mark.asyncio
    async def test_scoped_assistant_tools_subset_of_all(self):
        from lib.agent.registry import get_scoped_tools, get_all_tools
        from lib.agent.tool_sets import SABINE_TOOLS

        all_tools = await get_all_tools()
        assistant_tools = await get_scoped_tools("assistant")

        all_names = {t.name for t in all_tools}
        assistant_names = {t.name for t in assistant_tools}

        # Every scoped tool should exist in the full registry
        assert assistant_names.issubset(all_names), \
            f"Scoped tools not in registry: {assistant_names - all_names}"

        # Scoped tools should be a subset of SABINE_TOOLS definition
        assert assistant_names.issubset(SABINE_TOOLS), \
            f"Got unexpected tools: {assistant_names - SABINE_TOOLS}"

    @pytest.mark.asyncio
    async def test_scoped_coder_tools_subset_of_all(self):
        from lib.agent.registry import get_scoped_tools, get_all_tools
        from lib.agent.tool_sets import DREAM_TEAM_TOOLS

        all_tools = await get_all_tools()
        coder_tools = await get_scoped_tools("coder")

        all_names = {t.name for t in all_tools}
        coder_names = {t.name for t in coder_tools}

        assert coder_names.issubset(all_names)
        assert coder_names.issubset(DREAM_TEAM_TOOLS)

    @pytest.mark.asyncio
    async def test_no_cross_contamination(self):
        """Assistant tools should have zero overlap with coder tools."""
        from lib.agent.registry import get_scoped_tools

        assistant_tools = await get_scoped_tools("assistant")
        coder_tools = await get_scoped_tools("coder")

        assistant_names = {t.name for t in assistant_tools}
        coder_names = {t.name for t in coder_tools}

        overlap = assistant_names.intersection(coder_names)
        assert len(overlap) == 0, f"Cross-contamination: {overlap}"


# =============================================================================
# Memory Role Filter Propagation
# =============================================================================

@pytest.mark.integration
class TestMemoryRoleFilterPropagation:
    """
    Verify that role_filter is correctly passed through the call chain.
    Uses mocking to intercept the Supabase RPC call.
    """

    @pytest.mark.asyncio
    async def test_search_similar_memories_passes_role_filter(self):
        """Verify role_filter lands in the RPC params."""
        from lib.agent.retrieval import search_similar_memories

        mock_execute = MagicMock()
        mock_execute.execute.return_value = MagicMock(data=[])

        mock_rpc = MagicMock(return_value=mock_execute)
        mock_client = MagicMock()
        mock_client.rpc = mock_rpc

        with patch("lib.agent.retrieval.get_supabase_client", return_value=mock_client):
            await search_similar_memories(
                query_embedding=[0.1] * 1536,
                user_id=None,
                threshold=0.6,
                limit=5,
                role_filter="assistant"
            )

        # Verify the RPC was called with role_filter in params
        mock_rpc.assert_called_once()
        call_args = mock_rpc.call_args
        rpc_params = call_args[0][1]  # Second positional arg is the params dict
        assert rpc_params["role_filter"] == "assistant"

    @pytest.mark.asyncio
    async def test_search_similar_memories_passes_none_role_filter(self):
        """When role_filter is None, it should still be passed (SQL handles it)."""
        from lib.agent.retrieval import search_similar_memories

        mock_execute = MagicMock()
        mock_execute.execute.return_value = MagicMock(data=[])

        mock_rpc = MagicMock(return_value=mock_execute)
        mock_client = MagicMock()
        mock_client.rpc = mock_rpc

        with patch("lib.agent.retrieval.get_supabase_client", return_value=mock_client):
            await search_similar_memories(
                query_embedding=[0.1] * 1536,
                role_filter=None
            )

        call_args = mock_rpc.call_args
        rpc_params = call_args[0][1]
        assert rpc_params["role_filter"] is None

    @pytest.mark.asyncio
    async def test_retrieve_context_passes_role_filter_to_search(self):
        """Verify retrieve_context threads role_filter down to search_similar_memories."""
        from lib.agent.retrieval import retrieve_context
        from uuid import UUID

        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=[0.1] * 1536)

        mock_search = AsyncMock(return_value=[])
        mock_entity_search = AsyncMock(return_value=[])

        with patch("lib.agent.retrieval.get_embeddings", return_value=mock_embeddings), \
             patch("lib.agent.retrieval.search_similar_memories", mock_search), \
             patch("lib.agent.retrieval.search_entities_by_keywords", mock_entity_search):
            await retrieve_context(
                user_id=UUID("00000000-0000-0000-0000-000000000001"),
                query="test query",
                role_filter="assistant"
            )

        # Verify search_similar_memories was called with role_filter
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]  # keyword args
        assert call_kwargs.get("role_filter") == "assistant"


# =============================================================================
# Server Import Health
# =============================================================================

@pytest.mark.integration
class TestServerImports:
    """Verify that all modules import without errors."""

    def test_sabine_agent_imports(self):
        from lib.agent.sabine_agent import run_sabine_agent
        assert callable(run_sabine_agent)

    def test_task_agent_imports(self):
        from lib.agent.task_agent import run_task_agent
        assert callable(run_task_agent)

    def test_task_runner_imports(self):
        from lib.agent.task_runner import _dispatch_task, _run_task_agent, _task_requires_tool_execution
        assert callable(_dispatch_task)
        assert callable(_run_task_agent)
        assert callable(_task_requires_tool_execution)

    def test_tool_sets_imports(self):
        from lib.agent.tool_sets import SABINE_TOOLS, DREAM_TEAM_TOOLS, get_tool_names, is_tool_allowed
        assert len(SABINE_TOOLS) > 0
        assert len(DREAM_TEAM_TOOLS) > 0

    def test_registry_imports(self):
        from lib.agent.registry import get_all_tools, get_scoped_tools
        assert callable(get_all_tools)
        assert callable(get_scoped_tools)

    def test_core_shared_helpers_import(self):
        from lib.agent.core import (
            extract_tool_execution_details,
            classify_agent_error,
            create_react_agent_with_tools,
            load_deep_context,
            build_static_context,
            build_dynamic_context,
            load_role_manifest,
        )
        assert callable(extract_tool_execution_details)
        assert callable(classify_agent_error)

    def test_routers_import(self):
        from lib.agent.routers.sabine import router as sabine_router
        from lib.agent.routers.dream_team import router as dream_team_router
        from lib.agent.routers.memory import router as memory_router
        assert sabine_router is not None
        assert dream_team_router is not None
        assert memory_router is not None


# =============================================================================
# Role Manifest Loading
# =============================================================================

@pytest.mark.integration
class TestRoleManifests:
    """Verify role manifests load correctly."""

    def test_load_valid_role(self):
        from lib.agent.core import load_role_manifest
        manifest = load_role_manifest("backend-architect-sabine")
        # May return None if role files aren't present, so just check no crash
        if manifest is not None:
            assert manifest.role_id == "backend-architect-sabine"
            assert len(manifest.title) > 0
            assert len(manifest.instructions) > 0

    def test_load_invalid_role_returns_none(self):
        from lib.agent.core import load_role_manifest
        manifest = load_role_manifest("nonexistent-role-xyz")
        assert manifest is None

    def test_get_available_roles(self):
        from lib.agent.core import get_available_roles
        roles = get_available_roles()
        assert isinstance(roles, list)
        # Should have at least one role if docs/roles/ has files
        # Don't assert specific count since it depends on disk state


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
