"""
VoI Gate — Active Inference wrapper for tool execution.
=========================================================

Wraps agent tools with a Value of Information (VoI) check.
Before any tool executes, the gate calculates whether the action
needs clarification. If VoI > 0 (should_clarify), a push-back
message is returned instead of executing the tool.

Usage::

    tools = await get_scoped_tools("assistant")
    gated_tools = wrap_tools_with_voi_gate(tools, user_id=user_id)
    agent = create_react_agent(llm, gated_tools, ...)
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


async def _voi_gated_invoke(
    original_coroutine: Callable[..., Coroutine[Any, Any, str]],
    tool_name: str,
    user_id: str,
    **kwargs: Any,
) -> str:
    """
    Wrapper that checks VoI before invoking the original tool.

    Parameters
    ----------
    original_coroutine : callable
        The original async tool function.
    tool_name : str
        Name of the tool being invoked.
    user_id : str
        UUID of the user (for VoI + push-back context).
    **kwargs
        Tool arguments passed by the LLM.

    Returns
    -------
    str
        Either the original tool result or a push-back message.
    """
    if not user_id:
        # No user context — skip VoI to avoid spurious DB errors
        return await original_coroutine(**kwargs)

    try:
        from backend.inference.value_of_info import evaluate_action

        voi_result = await evaluate_action(
            tool_name=tool_name,
            user_id=user_id,
            tool_input=kwargs,
        )

        if voi_result.should_clarify:
            # VoI says we should push back — build the response
            from backend.inference.push_back import (
                PushBackLogEntry,
                build_push_back,
                log_push_back_event,
            )

            push_back = await build_push_back(
                tool_name=tool_name,
                tool_input=kwargs,
                user_id=user_id,
                voi_score=voi_result.voi_score,
            )

            # Log the push-back event
            log_entry = PushBackLogEntry(
                user_id=user_id,
                action_type=voi_result.action_type.value,
                tool_name=tool_name,
                c_error=voi_result.c_error,
                p_error=voi_result.p_error,
                c_int=voi_result.c_int,
                voi_score=voi_result.voi_score,
                push_back_triggered=True,
                evidence_memory_ids=[
                    e.memory_id for e in push_back.evidence if e.memory_id
                ],
                alternatives_offered=[
                    a.model_dump() for a in push_back.alternatives
                ],
            )
            await log_push_back_event(log_entry)

            logger.info(
                "VoI push-back triggered: tool=%s user=%s voi=%.3f",
                tool_name,
                user_id[:8] if user_id else "?",
                voi_result.voi_score,
            )

            return push_back.formatted_message

        else:
            # Log that VoI was calculated but no push-back (fire-and-forget)
            from backend.inference.push_back import (
                PushBackLogEntry,
                log_push_back_event,
            )

            log_entry = PushBackLogEntry(
                user_id=user_id,
                action_type=voi_result.action_type.value,
                tool_name=tool_name,
                c_error=voi_result.c_error,
                p_error=voi_result.p_error,
                c_int=voi_result.c_int,
                voi_score=voi_result.voi_score,
                push_back_triggered=False,
            )
            # Fire-and-forget — don't block tool execution on logging
            task = asyncio.create_task(log_push_back_event(log_entry))
            task.add_done_callback(
                lambda t: logger.error("VoI log task failed: %s", t.exception())
                if t.exception() else None
            )

    except Exception as exc:
        # VoI gate failure should NEVER block tool execution
        logger.warning(
            "VoI gate failed for tool=%s, proceeding with execution: %s",
            tool_name,
            exc,
        )

    # Execute the original tool
    return await original_coroutine(**kwargs)


def wrap_tools_with_voi_gate(
    tools: List[StructuredTool],
    user_id: str,
) -> List[StructuredTool]:
    """
    Wrap a list of tools with VoI gate checks.

    Each tool's coroutine is replaced with a wrapper that calculates VoI
    before execution. If VoI triggers a push-back, the tool returns the
    push-back message instead of executing.

    Parameters
    ----------
    tools : list[StructuredTool]
        Original tools from ``get_scoped_tools()`` or MCP.
    user_id : str
        UUID of the user for VoI context.

    Returns
    -------
    list[StructuredTool]
        New tool objects with VoI gating.
    """
    if not tools:
        return tools

    gated_tools: List[StructuredTool] = []
    gated_count: int = 0

    for tool in tools:
        original_coroutine = tool.coroutine
        if original_coroutine is None:
            # Tool has no async function — skip VoI gating
            gated_tools.append(tool)
            continue

        # Capture loop variables via default arguments to avoid closure bug
        tool_name_captured = tool.name

        async def gated_func(
            _orig: Callable[..., Coroutine[Any, Any, str]] = original_coroutine,
            _name: str = tool_name_captured,
            _uid: str = user_id,
            **kwargs: Any,
        ) -> str:
            return await _voi_gated_invoke(
                original_coroutine=_orig,
                tool_name=_name,
                user_id=_uid,
                **kwargs,
            )

        gated_tool = StructuredTool.from_function(
            name=tool.name,
            description=tool.description,
            coroutine=gated_func,
            args_schema=tool.args_schema,
        )

        gated_tools.append(gated_tool)
        gated_count += 1

    logger.info(
        "VoI gate applied to %d/%d tools for user=%s",
        gated_count,
        len(tools),
        user_id[:8] if user_id else "unknown",
    )

    return gated_tools
