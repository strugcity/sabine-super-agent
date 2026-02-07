"""
Task Agent - Dream Team Coding Agent Module

This module contains the run_task_agent() function that handles
coding tasks for the Dream Team specialized agent roles.

Part of Phase 2: Separate Agent Cores refactoring.
"""

import fnmatch
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


def _filter_tools_by_patterns(
    tools: List[StructuredTool],
    allowed_patterns: List[str]
) -> List[StructuredTool]:
    """
    Filter tools by wildcard patterns from RoleManifest.allowed_tools.
    
    Supports patterns like:
    - "github_*" - matches github_issues, github_create_pr, etc.
    - "mcp_*" - matches all MCP tools
    - "run_python_sandbox" - exact match
    
    Args:
        tools: List of all available tools
        allowed_patterns: List of pattern strings (may contain wildcards)
        
    Returns:
        Filtered list of tools matching at least one pattern
    """
    if not allowed_patterns:
        return tools
    
    filtered_tools = []
    for tool in tools:
        for pattern in allowed_patterns:
            if fnmatch.fnmatch(tool.name, pattern):
                filtered_tools.append(tool)
                break  # Tool matched, no need to check other patterns
    
    logger.info(f"Filtered {len(filtered_tools)} tools from {len(tools)} using patterns: {allowed_patterns}")
    return filtered_tools


async def run_task_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    role: str,  # REQUIRED for task agents
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Run a Dream Team task/coding agent with a specific role.
    
    This function:
    1. Loads the role manifest for specialized instructions
    2. Loads ONLY Dream Team tools (GitHub, sandbox, Slack, project board)
    3. Further filters tools by role's allowed_tools if specified
    4. Builds a minimal system prompt from role manifest (NO deep context)
    5. Does NOT call retrieve_context() - coding agents don't need Sabine's memories
    6. Does NOT call load_deep_context() - coding agents don't need custody/calendar
    7. Creates and runs the agent
    8. Returns response in the same format as the original run_agent()
    
    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        user_message: The user's input message (task instructions)
        role: The role ID (REQUIRED) - e.g., "backend-architect-sabine"
        conversation_history: Optional previous conversation history
        
    Returns:
        Dictionary with agent response and metadata, same structure as run_agent():
        {
            "success": bool,
            "response": str,
            "user_id": str,
            "session_id": str,
            "timestamp": str,
            "deep_context_loaded": bool,  # Always False for task agents
            "tools_available": int,
            "latency_ms": float,
            "cache_metrics": dict,
            "tool_execution": dict,
            "role": str,
            "role_title": str,
        }
    """
    start_time = time.time()
    
    try:
        # Lazy imports to avoid circular dependencies
        from .registry import get_scoped_tools
        from .core import (
            load_role_manifest,
            create_react_agent_with_tools,
            extract_tool_execution_details,
            classify_agent_error,
        )
        
        logger.info(f"Running task agent for user {user_id}, session {session_id}, role: {role}")
        
        # === STEP 1: Load role manifest ===
        role_manifest = load_role_manifest(role)
        if not role_manifest:
            error_msg = f"Role manifest not found for role: {role}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg,
                "error_type": "role_not_found",
                "error_category": "validation",
                "http_status": 404,
                "user_id": user_id,
                "session_id": session_id,
                "role": role,
                "timestamp": datetime.now().isoformat()
            }
        
        logger.info(f"Loaded role manifest: {role} ({role_manifest.title})")
        
        # === STEP 2: Load Dream Team tools ===
        tools = await get_scoped_tools("coder")
        logger.info(f"Loaded {len(tools)} Dream Team tools")
        tool_names = [t.name for t in tools]
        logger.debug(f"Dream Team tool names: {tool_names}")
        
        # === STEP 3: Apply role-specific tool filtering ===
        # If the role manifest has allowed_tools specified, further filter
        if role_manifest.allowed_tools:
            logger.info(f"Role {role} has tool restrictions: {role_manifest.allowed_tools}")
            tools = _filter_tools_by_patterns(tools, role_manifest.allowed_tools)
            logger.info(f"After role filtering: {len(tools)} tools available")
            tool_names = [t.name for t in tools]
            logger.info(f"Final tool names: {tool_names}")
        
        # === STEP 4: Build system prompt from role manifest ===
        # Task agents get a minimal prompt - just the role instructions
        # NO deep context (custody, calendar, user preferences)
        system_prompt = f"""# ROLE INSTRUCTIONS

{role_manifest.instructions}

# CURRENT TASK

The user has assigned you the following task. Execute it using the tools available to you.

"""
        
        logger.info(f"Built system prompt for role {role} ({len(system_prompt)} chars)")
        
        # === STEP 5: Create the agent ===
        agent, metadata = await create_react_agent_with_tools(
            tools=tools,
            system_prompt=system_prompt,
            user_id=user_id,
            session_id=session_id,
            role=role,
            use_hybrid_routing=True,
            task_payload=None,  # Could be enhanced to pass task complexity hints
        )
        
        # === STEP 6: Build message history ===
        messages: List[BaseMessage] = []
        
        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        
        # Add current user message (task instructions)
        messages.append(HumanMessage(content=user_message))
        
        # === STEP 7: Run the agent ===
        logger.info(f"Running task agent with {len(messages)} messages")
        result = await agent.ainvoke({"messages": messages})
        
        duration_ms = (time.time() - start_time) * 1000
        
        # === STEP 8: Extract tool execution details ===
        agent_messages = result.get("messages", [])
        logger.info(f"Agent returned {len(agent_messages)} messages")
        
        # Use shared helper to extract tool execution details
        tool_details = extract_tool_execution_details(agent_messages)
        tool_executions = tool_details["tool_executions"]
        tool_calls_detected = tool_details["tool_calls_detected"]
        tool_successes = tool_details["tool_successes"]
        tool_failures = tool_details["tool_failures"]
        tool_names_used = tool_details["tool_names_used"]
        artifacts_created = tool_details["artifacts_created"]
        failed_tools = tool_details["failed_tools"]
        
        logger.info(f"Tool calls detected: {tool_calls_detected}, Tools used: {tool_names_used}")
        logger.info(f"Tool results: {tool_successes} succeeded, {tool_failures} failed")
        if artifacts_created:
            logger.info(f"Artifacts created: {artifacts_created}")
        if failed_tools:
            logger.warning(f"Failed tool calls: {[(t['tool_name'], t.get('error')) for t in failed_tools]}")
        
        # Note: Audit logging is handled by task_runner.py with task_id context
        # This prevents double-logging and ensures task_id is included
        
        # === STEP 9: Extract response ===
        if agent_messages:
            last_message = agent_messages[-1]
            response_text = last_message.content if hasattr(last_message, "content") else str(last_message)
        else:
            response_text = "I apologize, but I couldn't generate a response."
        
        # === STEP 11: Build response dictionary (same format as run_agent) ===
        response_data = {
            "success": True,
            "response": response_text,
            "user_id": user_id,
            "session_id": session_id,
            "deep_context_loaded": False,  # Task agents don't load deep context
            "tools_available": len(tools),
            "timestamp": datetime.now().isoformat(),
            "latency_ms": duration_ms,
            "cache_metrics": metadata.get("_cache_info", {}),
            # Tool execution tracking for verification
            "tool_execution": {
                "tools_called": tool_names_used,
                "call_count": tool_calls_detected,
                "success_count": tool_successes,
                "failure_count": tool_failures,
                "artifacts_created": artifacts_created,
                "all_succeeded": tool_failures == 0 and tool_successes > 0,
                "executions": tool_executions
            },
            # Role info from manifest
            "role": role,
            "role_title": role_manifest.title,
        }
        
        return response_data
    
    except Exception as e:
        logger.error(f"Error running task agent: {e}", exc_info=True)
        
        # Use shared helper to classify the error
        error_info = classify_agent_error(e)
        
        return {
            "success": False,
            "error": str(e),
            "error_type": error_info["error_type"],
            "error_category": error_info["error_category"],
            "error_class": error_info["error_class"],
            "http_status": error_info["http_status"],
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
            "timestamp": datetime.now().isoformat()
        }
