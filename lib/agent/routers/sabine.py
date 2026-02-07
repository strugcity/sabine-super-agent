"""
Sabine Router - Core agent conversation endpoints.

Endpoints:
- POST /invoke - Main agent conversation endpoint with context retrieval
- POST /invoke/cached - Fast cached agent endpoint
"""

import logging
from typing import Optional, List, Dict
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field

# Import from server.py
from lib.agent.shared import verify_api_key, InvokeRequest, InvokeResponse
from lib.agent.core import run_agent, run_agent_with_caching
from lib.agent.memory import ingest_user_message
from lib.agent.retrieval import retrieve_context
from backend.services.wal import WALService
from backend.services.output_sanitization import (
    sanitize_agent_output,
    sanitize_error_message,
    sanitize_for_logging,
)

logger = logging.getLogger(__name__)

# Create router (no prefix - these are root-level endpoints)
router = APIRouter(tags=["sabine"])


@router.post("/invoke", response_model=InvokeResponse)
async def invoke_agent(
    request: InvokeRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key)
):
    """
    Invoke the Personal Super Agent with a user message.

    This is the main endpoint that the Next.js proxy calls.
    It runs the LangGraph agent and returns the response.

    Phase 4 Integration: Context Engine
    - Retrieves relevant memories and entities before generating response
    - Ingests the user message in the background after response is sent

    Args:
        request: InvokeRequest with message, user_id, session_id, etc.
                 Set use_caching=True for faster responses with prompt caching
        background_tasks: FastAPI background tasks for async ingestion

    Returns:
        InvokeResponse with agent's reply
    """
    logger.info(
        f"Received invoke request for user {request.user_id} (caching: {request.use_caching})")
    logger.info(f"Message: {request.message}")

    try:
        # Generate session ID if not provided
        session_id = request.session_id or f"session-{request.user_id[:8]}"

        # SABINE 2.0: Write-Ahead Log (Fast Path)
        # Capture the interaction BEFORE processing for durability
        wal_entry_id = None
        try:
            wal_service = WALService()
            wal_payload = {
                "user_id": request.user_id,
                "message": request.message,
                "source": "api_invoke",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "metadata": {
                    "use_caching": request.use_caching,
                    "has_conversation_history": bool(request.conversation_history),
                }
            }
            wal_entry = await wal_service.create_entry(wal_payload)
            wal_entry_id = wal_entry.id
            logger.info(f"✓ WAL entry created: {wal_entry_id}")
        except Exception as wal_error:
            # WAL failure should not block the request - log and continue
            logger.warning(f"WAL write failed (non-blocking): {wal_error}")

        # PHASE 4: Retrieve context from Context Engine
        try:
            retrieved_context = await retrieve_context(
                user_id=UUID(request.user_id),
                query=request.message
            )
            logger.info(
                f"✓ Retrieved context ({len(retrieved_context)} chars)")

            # Prepend context to the message for the agent
            # The agent will receive both the context and the user's query
            enhanced_message = f"Context from Memory:\n{retrieved_context}\n\nUser Query: {request.message}"

        except Exception as e:
            logger.warning(
                f"Context retrieval failed, continuing without: {e}")
            enhanced_message = request.message
            retrieved_context = None

        # Run the agent (with optional caching and role-based persona)
        result = await run_agent(
            user_id=request.user_id,
            session_id=session_id,
            user_message=enhanced_message,  # Use enhanced message with context
            conversation_history=request.conversation_history,
            use_caching=request.use_caching,
            role=request.role  # Pass role for specialized persona
        )

        # PHASE 4: Ingest message as background task (after response)
        # This prevents adding latency to the user's response
        if result["success"]:
            background_tasks.add_task(
                ingest_user_message,
                user_id=UUID(request.user_id),
                content=request.message,  # Ingest original message, not enhanced
                source="api"
            )
            logger.info("✓ Queued message ingestion as background task")

        if result["success"]:
            # Log cache metrics if available
            cache_info = result.get("cache_metrics", {})
            if cache_info.get("status"):
                logger.info(f"Cache: {cache_info.get('status')} | "
                            f"Read: {cache_info.get('cache_read_tokens', 0)} tokens")

            # Sanitize the agent output before returning
            sanitized_response = sanitize_agent_output(
                result["response"],
                redact_credentials=True,
                redact_pii=False  # Don't redact PII in agent responses by default
            )

            logger.info(f"Agent response: {sanitize_for_logging(result['response'][:100])}...")
            return InvokeResponse(
                success=True,
                response=sanitized_response,
                user_id=request.user_id,
                session_id=session_id,
                timestamp=result["timestamp"],
                role=result.get("role"),
                role_title=result.get("role_title")
            )
        else:
            # Log detailed error information
            error_type = result.get("error_type", "unknown")
            error_category = result.get("error_category", "internal")
            http_status = result.get("http_status", 500)

            logger.error(
                f"Agent failed: {sanitize_for_logging(result.get('error'))} "
                f"[type={error_type}, category={error_category}, status={http_status}]"
            )

            # Sanitize error message before returning
            sanitized_error = sanitize_error_message(result.get("error"))

            # Return appropriate HTTP status code based on error classification
            raise HTTPException(
                status_code=http_status,
                detail={
                    "success": False,
                    "error": sanitized_error,
                    "error_type": error_type,
                    "error_category": error_category,
                    "user_id": request.user_id,
                    "session_id": session_id,
                    "timestamp": result.get("timestamp"),
                    "role": result.get("role")
                }
            )

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping
        raise
    except Exception as e:
        # Sanitize exception message before logging and returning
        sanitized_error = sanitize_error_message(e)
        logger.error(f"Exception in invoke endpoint: {sanitize_for_logging(str(e))}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke agent: {sanitized_error}"
        )


@router.post("/invoke/cached")
async def invoke_agent_cached(request: InvokeRequest, _: bool = Depends(verify_api_key)):
    """
    Invoke the agent with prompt caching enabled.

    This endpoint uses direct Anthropic API calls with prompt caching
    for faster responses (up to 2x) and lower costs (up to 90% savings).

    Best for:
    - Simple queries that don't require tool execution loops
    - Repeated queries with the same context
    - High-volume scenarios where cost matters

    Note: This mode doesn't support multi-step tool execution.
    For complex queries requiring multiple tool calls, use /invoke instead.
    """
    logger.info(f"Received CACHED invoke request for user {request.user_id}")

    try:
        session_id = request.session_id or f"session-{request.user_id[:8]}"

        result = await run_agent_with_caching(
            user_id=request.user_id,
            session_id=session_id,
            user_message=request.message,
            conversation_history=request.conversation_history
        )

        if result["success"]:
            cache_metrics = result.get("cache_metrics", {})
            logger.info(
                f"Cached response: {result.get('latency_ms', 0):.0f}ms | "
                f"Cache: {cache_metrics.get('status', 'N/A')} | "
                f"Read: {cache_metrics.get('cache_read_tokens', 0)} tokens"
            )

            # Sanitize the agent output before returning
            sanitized_response = sanitize_agent_output(
                result["response"],
                redact_credentials=True
            )

            return {
                "success": True,
                "response": sanitized_response,
                "user_id": request.user_id,
                "session_id": session_id,
                "timestamp": result["timestamp"],
                "cache_metrics": cache_metrics,
                "latency_ms": result.get("latency_ms", 0)
            }
        else:
            # Use HTTP status from error classification if available
            http_status = result.get("http_status", 500)

            # Sanitize error message
            sanitized_error = sanitize_error_message(result.get("error"))

            error_detail = {
                "success": False,
                "response": "Error processing request",
                "error": sanitized_error,
                "error_type": result.get("error_type"),
                "error_category": result.get("error_category"),
                "user_id": request.user_id,
                "session_id": session_id,
                "timestamp": result.get("timestamp")
            }

            # Raise HTTPException with proper status code
            raise HTTPException(
                status_code=http_status,
                detail=error_detail
            )

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping
        raise
    except Exception as e:
        sanitized_error = sanitize_error_message(e)
        logger.error(
            f"Exception in cached invoke endpoint: {sanitize_for_logging(str(e))}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke cached agent: {sanitized_error}"
        )
