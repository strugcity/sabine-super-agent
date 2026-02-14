"""
Sabine Router - Core agent conversation endpoints.

Endpoints:
- POST /invoke - Main agent conversation endpoint with context retrieval
- POST /invoke/stream - SSE streaming endpoint with acknowledgment support
- POST /invoke/cached - Fast cached agent endpoint
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional, List, Dict
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Import from server.py
from lib.agent.shared import verify_api_key, InvokeRequest, InvokeResponse
from lib.agent.core import run_agent_with_caching
from lib.agent.sabine_agent import run_sabine_agent
from lib.agent.memory import ingest_user_message
from backend.services.wal import WALService
from backend.services.output_sanitization import (
    sanitize_agent_output,
    sanitize_error_message,
    sanitize_for_logging,
)

logger = logging.getLogger(__name__)

# Create router (no prefix - these are root-level endpoints)
router = APIRouter(tags=["sabine"])


# =============================================================================
# SSE Helpers
# =============================================================================


class SSEEvent(BaseModel):
    """A single Server-Sent Event payload."""

    type: str = Field(
        ..., description="Event type: ack, thinking, response, error, done"
    )
    data: str = Field(
        default="", description="Event data payload"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of this event",
    )


def _format_sse(event: SSEEvent) -> str:
    """
    Format an SSE event for the wire.

    Follows the standard SSE format: ``data: {json}\\n\\n``

    Args:
        event: The SSEEvent to format.

    Returns:
        The formatted SSE string ready to be yielded.
    """
    payload = event.model_dump()
    return f"data: {json.dumps(payload)}\n\n"


# =============================================================================
# POST /invoke — Main endpoint (backwards compatible, with SMS ack support)
# =============================================================================


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

    SMS Channel Support (Phase 1 Week 4):
    - If source_channel is "sms" and response takes >5s, an SMS ack is sent
    - For non-SMS channels, behaviour is unchanged (fully backwards compatible)

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
            logger.info(f"WAL entry created: {wal_entry_id}")
        except Exception as wal_error:
            # WAL failure should not block the request - log and continue
            logger.warning(f"WAL write failed (non-blocking): {wal_error}")

        # Deprecation warnings for removed parameters
        if hasattr(request, 'role') and request.role:
            logger.warning(
                f"Deprecation: 'role' parameter is no longer supported in /invoke endpoint. "
                f"Sabine agent has no role. Ignoring role='{request.role}'"
            )
        if hasattr(request, 'use_caching') and request.use_caching:
            logger.info(
                f"Note: 'use_caching' parameter is handled internally by run_sabine_agent(). "
                f"Explicit use_caching={request.use_caching} is no longer needed."
            )

        # --- SMS Acknowledgment Setup ---
        # If the channel is SMS, set up an ack timer that fires if the agent
        # takes longer than the configured threshold (default 5s).
        ack_manager = None
        channel = getattr(request, "source_channel", None)

        # Lazy import to avoid circular dependencies
        from backend.services.sms_ack import should_send_sms_ack

        if should_send_sms_ack(channel):
            from backend.services.streaming_ack import AcknowledgmentManager, AckConfig
            from backend.services.sms_ack import handle_sms_ack

            logger.info("SMS channel detected; starting ack timer for user %s", request.user_id)

            # TODO: Extract phone number from request metadata when Twilio integration is wired
            sms_phone = request.user_id  # Placeholder until phone mapping exists

            async def _sms_ack_callback(ack_message: str) -> None:
                """Send SMS acknowledgment when the timer fires."""
                await handle_sms_ack(to_number=sms_phone, ack_message=ack_message)

            ack_manager = AcknowledgmentManager(
                config=AckConfig(timeout_seconds=5.0, enabled=True),
                on_ack=_sms_ack_callback,
                user_message=request.message,
            )
            ack_manager.start()

        # Run the Sabine agent (handles context retrieval internally)
        result = await run_sabine_agent(
            user_id=request.user_id,
            session_id=session_id,
            user_message=request.message,
            conversation_history=request.conversation_history,
        )

        # --- Cancel SMS ack (response arrived) ---
        if ack_manager is not None:
            ack_result = await ack_manager.cancel()
            if ack_result.sent:
                logger.info("SMS ack was sent before agent completed")
            else:
                logger.debug("SMS ack cancelled (agent responded in time)")

        # PHASE 4: Ingest message as background task (after response)
        if result["success"]:
            background_tasks.add_task(
                ingest_user_message,
                user_id=UUID(request.user_id),
                content=request.message,
                source="api",
                role="assistant"
            )
            logger.info("Queued message ingestion as background task")

        if result["success"]:
            cache_info = result.get("cache_metrics", {})
            if cache_info.get("status"):
                logger.info(f"Cache: {cache_info.get('status')} | "
                            f"Read: {cache_info.get('cache_read_tokens', 0)} tokens")

            sanitized_response = sanitize_agent_output(
                result["response"],
                redact_credentials=True,
                redact_pii=False
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
            error_type = result.get("error_type", "unknown")
            error_category = result.get("error_category", "internal")
            http_status = result.get("http_status", 500)

            logger.error(
                f"Agent failed: {sanitize_for_logging(result.get('error'))} "
                f"[type={error_type}, category={error_category}, status={http_status}]"
            )

            sanitized_error = sanitize_error_message(result.get("error"))

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
        raise
    except Exception as e:
        # Cancel ack manager on unexpected errors
        if ack_manager is not None:
            try:
                await ack_manager.cancel()
            except Exception:
                pass

        sanitized_error = sanitize_error_message(e)
        logger.error(f"Exception in invoke endpoint: {sanitize_for_logging(str(e))}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke agent: {sanitized_error}"
        )


# =============================================================================
# POST /invoke/stream — SSE Streaming endpoint
# =============================================================================


@router.post("/invoke/stream")
async def invoke_agent_stream(
    request: InvokeRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key)
):
    """
    SSE streaming endpoint for the Sabine agent.

    Streams events as Server-Sent Events (SSE):
    - ``ack`` — Acknowledgment message (sent if response takes >5s)
    - ``thinking`` — Optional thinking indicator
    - ``response`` — The full agent response
    - ``error`` — Error details
    - ``done`` — Stream complete signal

    Each event is JSON: ``{"type": "...", "data": "...", "timestamp": "..."}``

    The endpoint:
    1. Starts the AcknowledgmentManager timer
    2. Begins running run_sabine_agent() as a task
    3. If timer fires before agent completes, yields an ``ack`` event
    4. When agent completes, yields ``response`` event then ``done``
    5. If agent fails, yields ``error`` event then ``done``

    Args:
        request: InvokeRequest with message, user_id, session_id, etc.
        background_tasks: FastAPI background tasks for async ingestion.

    Returns:
        StreamingResponse with text/event-stream content type.
    """
    logger.info(
        "Received streaming invoke request for user %s", request.user_id
    )

    session_id = request.session_id or f"session-{request.user_id[:8]}"

    async def _event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for the streaming response."""
        # Lazy imports to avoid circular dependencies
        from backend.services.streaming_ack import AcknowledgmentManager, AckConfig

        # Queue for ack events (populated by the ack callback)
        ack_queue: asyncio.Queue[str] = asyncio.Queue()

        async def _ack_callback(ack_message: str) -> None:
            """Push ack message into the queue for the SSE generator."""
            await ack_queue.put(ack_message)

        ack_manager = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=5.0, enabled=True),
            on_ack=_ack_callback,
            user_message=request.message,
        )

        # Start the ack timer
        ack_manager.start()

        # Start the agent as a concurrent task
        agent_task: asyncio.Task[Dict] = asyncio.create_task(
            run_sabine_agent(
                user_id=request.user_id,
                session_id=session_id,
                user_message=request.message,
                conversation_history=request.conversation_history,
            )
        )

        # Yield thinking indicator
        yield _format_sse(SSEEvent(type="thinking", data="Processing your request..."))

        # Poll for ack events and agent completion
        agent_done = False
        result: Optional[Dict] = None

        while not agent_done:
            # Check if agent task finished
            if agent_task.done():
                agent_done = True
                try:
                    result = agent_task.result()
                except Exception as exc:
                    logger.error(
                        "Agent task raised exception: %s", exc, exc_info=True
                    )
                    result = {
                        "success": False,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                break

            # Check if ack fired
            try:
                ack_msg = ack_queue.get_nowait()
                yield _format_sse(SSEEvent(type="ack", data=ack_msg))
            except asyncio.QueueEmpty:
                pass

            # Brief sleep to avoid busy-wait
            await asyncio.sleep(0.1)

        # Cancel the ack manager now that the agent is done
        await ack_manager.cancel()

        # Drain any remaining ack messages
        while not ack_queue.empty():
            try:
                ack_msg = ack_queue.get_nowait()
                yield _format_sse(SSEEvent(type="ack", data=ack_msg))
            except asyncio.QueueEmpty:
                break

        # Yield the final response or error
        if result is not None and result.get("success"):
            sanitized_response = sanitize_agent_output(
                result["response"],
                redact_credentials=True,
                redact_pii=False,
            )

            yield _format_sse(SSEEvent(type="response", data=sanitized_response))

            # Queue background ingestion
            background_tasks.add_task(
                ingest_user_message,
                user_id=UUID(request.user_id),
                content=request.message,
                source="api",
                role="assistant",
            )
        elif result is not None:
            error_msg = sanitize_error_message(result.get("error"))
            yield _format_sse(SSEEvent(type="error", data=str(error_msg)))
        else:
            yield _format_sse(SSEEvent(type="error", data="Unknown error: no result returned"))

        # Done signal
        yield _format_sse(SSEEvent(type="done", data=""))

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# POST /invoke/cached — Cached agent endpoint (unchanged)
# =============================================================================


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
            http_status = result.get("http_status", 500)
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

            raise HTTPException(
                status_code=http_status,
                detail=error_detail
            )

    except HTTPException:
        raise
    except Exception as e:
        sanitized_error = sanitize_error_message(e)
        logger.error(
            f"Exception in cached invoke endpoint: {sanitize_for_logging(str(e))}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke cached agent: {sanitized_error}"
        )
