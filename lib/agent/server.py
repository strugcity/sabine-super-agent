"""
FastAPI Server - Personal Super Agent

This server exposes the LangGraph agent via HTTP endpoints.
It receives requests from the Next.js proxy (Twilio webhook handler)
and returns agent responses.

Run with:
    python lib/agent/server.py

Or with uvicorn:
    uvicorn lib.agent.server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.agent.core import run_agent, create_agent
from lib.agent.registry import get_all_tools

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Personal Super Agent API",
    description="LangGraph agent powered by Claude 3.5 Sonnet with MCP integrations",
    version="1.0.0"
)

# Add CORS middleware (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Request/Response Models
# =============================================================================

class InvokeRequest(BaseModel):
    """Request body for /invoke endpoint."""
    message: str = Field(..., description="User message to send to the agent")
    user_id: str = Field(..., description="User UUID")
    session_id: Optional[str] = Field(None, description="Conversation session ID")
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Previous conversation history"
    )


class InvokeResponse(BaseModel):
    """Response from /invoke endpoint."""
    success: bool
    response: str
    user_id: str
    session_id: str
    timestamp: str
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    tools_loaded: int
    database_connected: bool


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": "Personal Super Agent API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "POST /invoke": "Run the agent with a user message",
            "GET /health": "Health check and system status",
            "GET /tools": "List available tools"
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns system status, tool count, and database connectivity.
    """
    try:
        # Check if tools can be loaded
        tools = await get_all_tools()
        tools_count = len(tools)

        # Check database connection
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        database_connected = bool(supabase_url and supabase_key)

        return HealthResponse(
            status="healthy",
            version="1.0.0",
            tools_loaded=tools_count,
            database_connected=database_connected
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")


@app.get("/tools")
async def list_tools():
    """
    List all available tools (local skills + MCP integrations).

    Returns tool names and descriptions.
    """
    try:
        tools = await get_all_tools()

        return {
            "success": True,
            "count": len(tools),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description
                }
                for tool in tools
            ]
        }
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list tools: {str(e)}")


@app.post("/invoke", response_model=InvokeResponse)
async def invoke_agent(request: InvokeRequest):
    """
    Invoke the Personal Super Agent with a user message.

    This is the main endpoint that the Next.js proxy calls.
    It runs the LangGraph agent and returns the response.

    Args:
        request: InvokeRequest with message, user_id, session_id, etc.

    Returns:
        InvokeResponse with agent's reply
    """
    logger.info(f"Received invoke request for user {request.user_id}")
    logger.info(f"Message: {request.message}")

    try:
        # Generate session ID if not provided
        session_id = request.session_id or f"session-{request.user_id[:8]}"

        # Run the agent
        result = await run_agent(
            user_id=request.user_id,
            session_id=session_id,
            user_message=request.message,
            conversation_history=request.conversation_history
        )

        if result["success"]:
            logger.info(f"Agent response: {result['response'][:100]}...")
            return InvokeResponse(
                success=True,
                response=result["response"],
                user_id=request.user_id,
                session_id=session_id,
                timestamp=result["timestamp"]
            )
        else:
            logger.error(f"Agent failed: {result.get('error')}")
            return InvokeResponse(
                success=False,
                response="I apologize, but I encountered an error processing your request.",
                user_id=request.user_id,
                session_id=session_id,
                timestamp=result["timestamp"],
                error=result.get("error")
            )

    except Exception as e:
        logger.error(f"Exception in invoke endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke agent: {str(e)}"
        )


@app.post("/test")
async def test_agent():
    """
    Test endpoint for quick verification.

    Runs a simple test query to verify the agent is working.
    """
    test_user_id = "00000000-0000-0000-0000-000000000000"
    test_session_id = "test-session"
    test_message = "Hello! Can you tell me what tools you have access to?"

    try:
        result = await run_agent(
            user_id=test_user_id,
            session_id=test_session_id,
            user_message=test_message
        )

        return {
            "success": True,
            "test_message": test_message,
            "agent_response": result.get("response", "No response"),
            "timestamp": result.get("timestamp")
        }

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# Startup/Shutdown Events
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info("=" * 60)
    logger.info("Personal Super Agent API Starting...")
    logger.info("=" * 60)

    # Load environment variables from project root
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    # Check required environment variables
    required_vars = ["ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.warning("Some functionality may be limited")
    else:
        logger.info("✓ All required environment variables present")

    # Preload tools
    try:
        tools = await get_all_tools()
        logger.info(f"✓ Loaded {len(tools)} tools")
        for tool in tools:
            logger.info(f"  - {tool.name}")
    except Exception as e:
        logger.error(f"Failed to load tools: {e}")

    logger.info("=" * 60)
    logger.info("API Ready!")
    logger.info("Listening on http://0.0.0.0:8000")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("Personal Super Agent API shutting down...")


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Load environment variables from project root
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    # Get configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("NODE_ENV", "development") == "development"

    logger.info(f"Starting server on {host}:{port}")
    logger.info(f"Reload: {reload}")

    # Run server
    uvicorn.run(
        "lib.agent.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
