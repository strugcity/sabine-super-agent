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
        
        # Track all tool calls and their results
        tool_executions = []
        tool_calls_detected = 0
        tool_successes = 0
        tool_failures = 0
        
        for i, msg in enumerate(agent_messages):
            msg_type = type(msg).__name__
            content_preview = ""
            
            # Check for ToolMessage (tool results)
            if msg_type == "ToolMessage":
                tool_name = getattr(msg, 'name', 'unknown')
                tool_content = msg.content if hasattr(msg, 'content') else None
                
                # Parse tool result to determine success/failure
                tool_status = "unknown"
                tool_error = None
                artifact_created = None
                
                if tool_content:
                    # Try to parse as JSON to extract status
                    try:
                        import json
                        if isinstance(tool_content, str):
                            result_data = json.loads(tool_content)
                        elif isinstance(tool_content, dict):
                            result_data = tool_content
                        else:
                            result_data = {}
                        
                        # Check for status field
                        if "status" in result_data:
                            tool_status = result_data["status"]
                            if tool_status == "success":
                                tool_successes += 1
                                # Extract artifact info if available
                                if "file" in result_data:
                                    artifact_created = result_data["file"].get("path") or result_data["file"].get("url")
                                elif "issue" in result_data:
                                    artifact_created = f"Issue #{result_data['issue'].get('number')}"
                                elif "commit" in result_data:
                                    artifact_created = f"Commit {result_data['commit'].get('sha', '')[:7]}"
                            elif tool_status == "error":
                                tool_failures += 1
                                tool_error = result_data.get("error", "Unknown error")
                        
                        # Check for error field without status
                        elif "error" in result_data:
                            tool_status = "error"
                            tool_failures += 1
                            tool_error = result_data["error"]
                        
                        # Check for success indicators
                        elif "success" in result_data:
                            tool_status = "success" if result_data["success"] else "error"
                            if tool_status == "success":
                                tool_successes += 1
                            else:
                                tool_failures += 1
                                tool_error = result_data.get("error", "Operation failed")
                        
                        else:
                            # Assume success if no error indicators
                            tool_status = "success"
                            tool_successes += 1
                    
                    except (json.JSONDecodeError, TypeError):
                        # If not JSON, check for error patterns in string
                        content_str = str(tool_content).lower()
                        if "error" in content_str or "failed" in content_str or "exception" in content_str:
                            tool_status = "error"
                            tool_failures += 1
                            tool_error = str(tool_content)[:200]
                        else:
                            tool_status = "success"
                            tool_successes += 1
                
                tool_executions.append({
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "tool_call_id": getattr(msg, 'tool_call_id', None),
                    "status": tool_status,
                    "error": tool_error,
                    "artifact_created": artifact_created,
                    "content_preview": str(tool_content)[:500] if tool_content else None
                })
                status_indicator = "OK" if tool_status == "success" else "FAIL"
                content_preview = f"[TOOL_RESULT: {tool_name} - {status_indicator}]"
            
            elif hasattr(msg, 'content'):
                if isinstance(msg.content, str):
                    content_preview = msg.content[:100]
                elif isinstance(msg.content, list):
                    # Check for tool_use blocks in AIMessage
                    for block in msg.content:
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            tool_calls_detected += 1
                            tool_name = block.get('name', 'unknown')
                            tool_executions.append({
                                "type": "tool_call",
                                "tool_name": tool_name,
                                "tool_call_id": block.get('id'),
                                "input_preview": str(block.get('input', {}))[:200]
                            })
                            content_preview = f"[TOOL_USE: {tool_name}]"
                    if not content_preview:
                        content_preview = f"[list with {len(msg.content)} items]"
                else:
                    content_preview = str(msg.content)[:100]
            
            logger.debug(f"  Message {i}: [{msg_type}] {content_preview}")
        
        # Summarize tool executions
        tool_names_used = list(set(t['tool_name'] for t in tool_executions if t['type'] == 'tool_call'))
        artifacts_created = [t['artifact_created'] for t in tool_executions if t.get('artifact_created')]
        failed_tools = [t for t in tool_executions if t.get('status') == 'error']
        
        logger.info(f"Tool calls detected: {tool_calls_detected}, Tools used: {tool_names_used}")
        logger.info(f"Tool results: {tool_successes} succeeded, {tool_failures} failed")
        if artifacts_created:
            logger.info(f"Artifacts created: {artifacts_created}")
        if failed_tools:
            logger.warning(f"Failed tool calls: {[(t['tool_name'], t.get('error')) for t in failed_tools]}")
        
        # === STEP 9: Persistent audit logging ===
        # Log all tool executions to database for debugging and compliance
        if tool_executions:
            try:
                from backend.services.audit_logging import log_tool_executions_batch
                logged_count = await log_tool_executions_batch(
                    executions=tool_executions,
                    user_id=user_id,
                    agent_role=role,
                )
                logger.info(f"Audit logging: {logged_count} tool executions logged to database")
            except ImportError:
                logger.debug("Audit logging service not available - skipping persistent logging")
            except Exception as e:
                # Don't let audit logging failures break the main flow
                logger.warning(f"Audit logging failed (non-fatal): {e}")
        
        # === STEP 10: Extract response ===
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
        
        # Classify the error for better handling
        error_type = "unknown"
        error_category = "internal"
        http_status = None
        
        error_str = str(e).lower()
        error_class = type(e).__name__
        
        # Check for API-related errors (LLM, external services)
        if "rate" in error_str and "limit" in error_str:
            error_type = "rate_limited"
            error_category = "external_service"
            http_status = 429
        elif "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
            error_type = "auth_failed"
            error_category = "authentication"
            http_status = 401
        elif "403" in error_str or "forbidden" in error_str or "permission" in error_str:
            error_type = "permission_denied"
            error_category = "authorization"
            http_status = 403
        elif "404" in error_str or "not found" in error_str:
            error_type = "not_found"
            error_category = "validation"
            http_status = 404
        elif "timeout" in error_str or "timed out" in error_str:
            error_type = "timeout"
            error_category = "external_service"
            http_status = 504
        elif "connection" in error_str or "network" in error_str:
            error_type = "network_error"
            error_category = "external_service"
            http_status = 502
        elif "validation" in error_str or "invalid" in error_str:
            error_type = "validation_error"
            error_category = "validation"
            http_status = 400
        
        return {
            "success": False,
            "error": str(e),
            "error_type": error_type,
            "error_category": error_category,
            "error_class": error_class,
            "http_status": http_status,
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
            "timestamp": datetime.now().isoformat()
        }
