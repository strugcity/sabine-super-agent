"""
VoI Gate Integration Tests
===========================

Tests for the Value of Information gate wiring in lib/agent/voi_gate.py.
All external dependencies (Supabase, VoI calculation, push-back) are mocked.

Run with::

    python -m pytest tests/test_voi_gate.py -v
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


# =============================================================================
# Test Fixtures and Helpers
# =============================================================================

class SimpleToolInput(BaseModel):
    """Simple tool input schema for test tools."""
    query: str = Field(..., description="Test query parameter")


async def dummy_tool_func(query: str) -> str:
    """Dummy async function for testing tool wrapping."""
    return f"Tool executed with: {query}"


# =============================================================================
# Test: _voi_gated_invoke
# =============================================================================

class TestVoIGatedInvoke:
    """Tests for _voi_gated_invoke function."""

    @pytest.mark.asyncio
    async def test_push_back_triggered(self) -> None:
        """When should_clarify=True, should return push-back message instead of tool result."""
        from lib.agent.voi_gate import _voi_gated_invoke
        from backend.inference.value_of_info import VoIResult, ActionType
        from backend.inference.push_back import PushBackResponse

        mock_voi_result = VoIResult(
            should_clarify=True,
            voi_score=0.35,
            action_type=ActionType.IRREVERSIBLE,
            c_error=0.8,
            p_error=0.6,
            c_int=0.13,
            reasoning="High risk action",
        )

        mock_push_back = PushBackResponse(
            concern="High risk action",
            formatted_message="Are you sure?",
            voi_score=0.35,
            evidence=[],
            alternatives=[],
        )

        original_coro = AsyncMock(return_value="tool result")

        with patch(
            "backend.inference.value_of_info.evaluate_action",
            new_callable=AsyncMock,
            return_value=mock_voi_result,
        ), patch(
            "backend.inference.push_back.build_push_back",
            new_callable=AsyncMock,
            return_value=mock_push_back,
        ), patch(
            "backend.inference.push_back.log_push_back_event",
            new_callable=AsyncMock,
        ) as mock_log:
            result = await _voi_gated_invoke(
                original_coroutine=original_coro,
                tool_name="dangerous_tool",
                user_id="user-123",
                arg1="val",
            )

        # Assert: returns push-back message, NOT tool result
        assert result == "Are you sure?"
        # Assert: original tool was NOT called
        original_coro.assert_not_called()
        # Assert: log_push_back_event was called with push_back_triggered=True
        mock_log.assert_called_once()
        call_args = mock_log.call_args[0][0]
        assert call_args.push_back_triggered is True
        assert call_args.tool_name == "dangerous_tool"
        assert call_args.user_id == "user-123"

    @pytest.mark.asyncio
    async def test_pass_through(self) -> None:
        """When should_clarify=False, should execute tool and return its result."""
        from lib.agent.voi_gate import _voi_gated_invoke
        from backend.inference.value_of_info import VoIResult, ActionType

        mock_voi_result = VoIResult(
            should_clarify=False,
            voi_score=-0.2,
            action_type=ActionType.INFORMATIONAL,
            c_error=0.1,
            p_error=0.2,
            c_int=0.22,
            reasoning="Low risk",
        )

        original_coro = AsyncMock(return_value="tool result")

        with patch(
            "backend.inference.value_of_info.evaluate_action",
            new_callable=AsyncMock,
            return_value=mock_voi_result,
        ), patch(
            "backend.inference.push_back.log_push_back_event",
            new_callable=AsyncMock,
        ) as mock_log:
            result = await _voi_gated_invoke(
                original_coroutine=original_coro,
                tool_name="safe_tool",
                user_id="user-123",
                query="test",
            )
            await asyncio.sleep(0)  # drain fire-and-forget task while mock is active

        # Assert: returns tool result
        assert result == "tool result"
        # Assert: original tool was called with correct args
        original_coro.assert_called_once_with(query="test")

    @pytest.mark.asyncio
    async def test_empty_user_id_bypasses_voi(self) -> None:
        """Empty user_id should bypass VoI gate entirely."""
        from lib.agent.voi_gate import _voi_gated_invoke

        original_coro = AsyncMock(return_value="result")

        # No patch for evaluate_action - if it's called, it will raise AttributeError
        result = await _voi_gated_invoke(
            original_coroutine=original_coro,
            tool_name="any_tool",
            user_id="",
            query="x",
        )

        # Assert: returns tool result
        assert result == "result"
        # Assert: tool was called
        original_coro.assert_called_once_with(query="x")

    @pytest.mark.asyncio
    async def test_voi_gate_failure_falls_through(self) -> None:
        """VoI gate failure should never block tool execution."""
        from lib.agent.voi_gate import _voi_gated_invoke

        original_coro = AsyncMock(return_value="still works")

        with patch(
            "backend.inference.value_of_info.evaluate_action",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await _voi_gated_invoke(
                original_coroutine=original_coro,
                tool_name="tool",
                user_id="user-123",
            )

        # Assert: returns tool result despite gate failure
        assert result == "still works"
        original_coro.assert_called_once()


# =============================================================================
# Test: wrap_tools_with_voi_gate
# =============================================================================

class TestWrapToolsWithVoIGate:
    """Tests for wrap_tools_with_voi_gate function."""

    @pytest.mark.asyncio
    async def test_preserves_tool_metadata(self) -> None:
        """wrap_tools_with_voi_gate should preserve tool name, description, and args_schema."""
        from lib.agent.voi_gate import wrap_tools_with_voi_gate

        # Create a test tool
        original_tool = StructuredTool.from_function(
            name="test_tool",
            description="A test tool",
            coroutine=dummy_tool_func,
            args_schema=SimpleToolInput,
        )

        # Wrap it
        wrapped_tools = wrap_tools_with_voi_gate([original_tool], user_id="u1")

        # Assert: returned list has length 1
        assert len(wrapped_tools) == 1

        wrapped_tool = wrapped_tools[0]
        # Assert: metadata preserved
        assert wrapped_tool.name == "test_tool"
        assert wrapped_tool.description == "A test tool"
        assert wrapped_tool.args_schema == SimpleToolInput
        # Assert: has a coroutine
        assert wrapped_tool.coroutine is not None
