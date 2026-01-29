"""
Integration Example: Using Memory Ingestion in the Main Agent

This shows how to integrate the memory ingestion pipeline with the existing
Sabine agent (lib/agent/core.py) to automatically build the context engine
as users interact with the system.
"""

import asyncio
import logging
from typing import Dict, Any
from uuid import UUID

from lib.agent.memory import ingest_user_message

logger = logging.getLogger(__name__)


# =============================================================================
# Integration Pattern 1: Async Background Ingestion
# =============================================================================

async def process_user_message_with_memory(
    user_id: str,
    message: str,
    source: str = "sms"
) -> Dict[str, Any]:
    """
    Process a user message AND ingest it into the context engine.

    This pattern runs ingestion in the background while the agent
    generates a response, so there's no added latency for the user.

    Args:
        user_id: User UUID as string
        message: User's message content
        source: Message source (sms, email, api, etc.)

    Returns:
        Agent response dict
    """
    user_uuid = UUID(user_id)

    # Start ingestion in background (don't await)
    ingestion_task = asyncio.create_task(
        ingest_user_message(
            user_id=user_uuid,
            content=message,
            source=source
        )
    )

    # TODO: Call your existing agent logic here
    # For example:
    # agent_response = await run_agent(user_id, message)

    agent_response = {
        "reply": "Processing your message...",
        "status": "success"
    }

    # Optionally wait for ingestion to complete before returning
    # (or just let it run in background)
    try:
        ingestion_result = await ingestion_task
        logger.info(f"✓ Memory ingestion: {ingestion_result['status']}")
    except Exception as e:
        logger.error(f"Memory ingestion failed: {e}", exc_info=True)
        # Don't fail the whole request if ingestion fails

    return agent_response


# =============================================================================
# Integration Pattern 2: Hook into Message Pipeline
# =============================================================================

async def on_message_received(user_id: str, content: str, source: str):
    """
    Webhook-style handler that ingests every message.

    Add this to your FastAPI route handlers, Twilio webhooks, etc.
    """
    try:
        result = await ingest_user_message(
            user_id=UUID(user_id),
            content=content,
            source=source
        )

        logger.info(
            f"✓ Ingested message from {user_id}: "
            f"{result['entities_created']} created, "
            f"{result['entities_updated']} updated"
        )

    except Exception as e:
        logger.error(f"Failed to ingest message: {e}", exc_info=True)


# =============================================================================
# Integration Pattern 3: Batch Processing (For Historical Data)
# =============================================================================

async def backfill_messages_to_memory(messages: list[Dict[str, Any]]):
    """
    Backfill historical messages into the context engine.

    Useful for importing existing chat history.

    Args:
        messages: List of dicts with keys: user_id, content, source, timestamp
    """
    results = {
        "total": len(messages),
        "success": 0,
        "failed": 0
    }

    for msg in messages:
        try:
            result = await ingest_user_message(
                user_id=UUID(msg["user_id"]),
                content=msg["content"],
                source=msg.get("source", "backfill")
            )

            if result["status"] == "success":
                results["success"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            logger.error(f"Failed to backfill message: {e}")
            results["failed"] += 1

    logger.info(
        f"✓ Backfill complete: "
        f"{results['success']}/{results['total']} succeeded"
    )

    return results


# =============================================================================
# Integration Pattern 4: FastAPI Endpoint
# =============================================================================

"""
Add this to your FastAPI app (e.g., src/app/api/memory/route.py):

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from uuid import UUID

router = APIRouter()

class IngestRequest(BaseModel):
    user_id: str
    content: str
    source: str = "api"

@router.post("/ingest")
async def ingest_endpoint(request: IngestRequest):
    '''Ingest a user message into the context engine.'''
    try:
        result = await ingest_user_message(
            user_id=UUID(request.user_id),
            content=request.content,
            source=request.source
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Usage:
# POST /api/memory/ingest
# {
#   "user_id": "00000000-0000-0000-0000-000000000001",
#   "content": "Baseball game at 5 PM",
#   "source": "sms"
# }
"""


# =============================================================================
# Integration Pattern 5: LangGraph Node
# =============================================================================

async def memory_ingestion_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node that ingests the current message.

    Add this to your agent graph in lib/agent/core.py:

    graph = StateGraph(AgentState)
    graph.add_node("ingest_memory", memory_ingestion_node)
    graph.add_edge("__start__", "ingest_memory")
    graph.add_edge("ingest_memory", "agent")
    """
    user_id = state.get("user_id")
    messages = state.get("messages", [])

    if not messages or not user_id:
        return state

    # Get the last human message
    last_message = None
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            last_message = msg
            break

    if last_message:
        try:
            await ingest_user_message(
                user_id=UUID(user_id),
                content=last_message.content,
                source="chat"
            )
            logger.info("✓ Memory ingested during agent flow")
        except Exception as e:
            logger.error(f"Memory ingestion failed in graph: {e}")

    return state


# =============================================================================
# Example Usage
# =============================================================================

async def main():
    """Test the integration patterns."""
    test_user_id = "00000000-0000-0000-0000-000000000001"

    # Pattern 1: Background ingestion
    print("\n1. Testing background ingestion...")
    result = await process_user_message_with_memory(
        user_id=test_user_id,
        message="Baseball game moved to 5 PM",
        source="sms"
    )
    print(f"   Agent response: {result}")

    # Pattern 2: Direct hook
    print("\n2. Testing webhook handler...")
    await on_message_received(
        user_id=test_user_id,
        content="Meeting with Alice on Friday",
        source="email"
    )

    print("\n✅ Integration examples complete")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    asyncio.run(main())
