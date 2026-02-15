"""
Sabine Agent - Personal Assistant Agent Module

This module contains the run_sabine_agent() function that handles
conversational interactions for Sabine, the personal AI assistant.

Part of Phase 2: Separate Agent Cores refactoring.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

logger = logging.getLogger(__name__)


async def run_sabine_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    source_channel: Optional[str] = None,  # "email-work", "email-personal", "sms", "api"
) -> Dict[str, Any]:
    """
    Run the Sabine personal assistant agent.
    
    This function:
    1. Loads ONLY Sabine tools (calendar, reminders, weather, custody)
    2. Loads deep context (user rules, custody schedule, preferences)
    3. Builds system prompt from static and dynamic context
    4. Retrieves relevant memories from the Context Engine (with domain filtering)
    5. Optionally performs cross-context scan for conflicts/overlaps
    6. Creates and runs the agent
    7. Returns response in the same format as the original run_agent()
    
    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        user_message: The user's input message
        conversation_history: Optional previous conversation history
        source_channel: Optional source channel (email-work, email-personal, sms, api)
                       for domain-aware memory retrieval
        
    Returns:
        Dictionary with agent response and metadata, same structure as run_agent():
        {
            "success": bool,
            "response": str,
            "user_id": str,
            "session_id": str,
            "timestamp": str,
            "deep_context_loaded": bool,
            "tools_available": int,
            "latency_ms": float,
            "cache_metrics": dict,
            "tool_execution": dict,
            "role": None,  # Always None for Sabine
            "role_title": None,  # Always None for Sabine
        }
    """
    start_time = time.time()
    
    try:
        # Lazy imports to avoid circular dependencies
        from .registry import get_scoped_tools
        from .core import (
            load_deep_context,
            build_static_context,
            build_dynamic_context,
            create_react_agent_with_tools,
            extract_tool_execution_details,
            classify_agent_error,
        )
        from .retrieval import retrieve_context
        
        logger.info(f"Running Sabine agent for user {user_id}, session {session_id}")
        
        # === STEP 1: Load Sabine-specific tools ===
        tools = await get_scoped_tools("assistant")
        logger.info(f"Loaded {len(tools)} Sabine tools")
        tool_names = [t.name for t in tools]
        logger.debug(f"Sabine tool names: {tool_names}")
        
        # === STEP 2: Load deep context ===
        deep_context = await load_deep_context(user_id)
        logger.info(f"Loaded deep context for user {user_id}")
        
        # === STEP 3: Build system prompt ===
        static_prompt = build_static_context(deep_context, role=None)
        dynamic_prompt = build_dynamic_context(deep_context)
        full_system_prompt = static_prompt + dynamic_prompt
        
        # === STEP 3b: Determine domain context ===
        domain_filter = None
        if source_channel == "email-work":
            domain_filter = "work"
        elif source_channel == "email-personal":
            domain_filter = "personal"
        # SMS and API: no domain filter (retrieve all)
        
        logger.info(f"Domain filter: {domain_filter} (source_channel: {source_channel})")
        
        # === STEP 4: Retrieve memory context ===
        # Try to retrieve relevant memories for context augmentation
        try:
            retrieved_context = await retrieve_context(
                user_id=UUID(user_id),
                query=user_message,
                role_filter="assistant",  # Only retrieve Sabine memories, not Dream Team task content
                domain_filter=domain_filter,
                include_graph=True,  # Include MAGMA entity relationships
            )
            logger.info(f"Retrieved context from memory ({len(retrieved_context)} chars)")
            
            # === STEP 4b: Cross-context scan ===
            cross_advisory = ""
            if domain_filter:
                try:
                    from .retrieval import cross_context_scan
                    cross_advisory = await cross_context_scan(
                        user_id=UUID(user_id),
                        query=user_message,
                        primary_domain=domain_filter,
                    )
                    if cross_advisory:
                        logger.info(f"Cross-context advisory generated ({len(cross_advisory)} chars)")
                except Exception as e:
                    logger.warning(f"Cross-context scan failed (non-fatal): {e}")
            
            # Augment the user message with retrieved context
            if retrieved_context:
                enhanced_message = f"Context from Memory:\n{retrieved_context}"
                if cross_advisory:
                    enhanced_message += f"\n\n{cross_advisory}"
                enhanced_message += f"\n\nUser Query: {user_message}"
            else:
                enhanced_message = user_message
                
        except Exception as e:
            logger.warning(f"Context retrieval failed, continuing without: {e}")
            enhanced_message = user_message
        
        # === STEP 5: Create the agent ===
        agent, metadata = await create_react_agent_with_tools(
            tools=tools,
            system_prompt=full_system_prompt,
            user_id=user_id,
            session_id=session_id,
            role=None,  # Sabine has no role
            use_hybrid_routing=True,
            task_payload=None,
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
        
        # Add current user message (with memory context if available)
        messages.append(HumanMessage(content=enhanced_message))
        
        # === STEP 7: Run the agent ===
        logger.info(f"Running Sabine agent with {len(messages)} messages")
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
        
        # === STEP 9: Persistent audit logging ===
        # Log all tool executions to database for debugging and compliance
        if tool_executions:
            try:
                from backend.services.audit_logging import log_tool_executions_batch
                logged_count = await log_tool_executions_batch(
                    executions=tool_executions,
                    user_id=user_id,
                    agent_role=None,  # Sabine has no role
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
            "deep_context_loaded": True,
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
            # Sabine always has no role
            "role": None,
            "role_title": None,
        }
        
        return response_data
    
    except Exception as e:
        logger.error(f"Error running Sabine agent: {e}", exc_info=True)
        
        # Classify the error for better handling
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
            "role": None,
            "timestamp": datetime.now().isoformat()
        }
