"""
FastAPI Server - Personal Super Agent

This server exposes the LangGraph agent via HTTP endpoints.
It receives requests from the Next.js proxy (Twilio webhook handler)
and returns agent responses.

Run with:
    python lib/agent/server.py

Or with uvicorn:
    uvicorn lib.agent.server:app --host 0.0.0.0 --port 8001 --reload

Note: Railway sets PORT env var automatically. The server respects both
PORT and API_PORT environment variables for flexibility.
"""

from lib.agent.core import run_agent, run_agent_with_caching, create_agent, get_cache_metrics, reset_cache_metrics
from lib.agent.registry import get_all_tools, get_mcp_diagnostics, MCP_SERVERS
from lib.agent.gmail_handler import handle_new_email_notification
from lib.agent.memory import ingest_user_message
from lib.agent.retrieval import retrieve_context
from lib.agent.parsing import parse_file, is_supported_mime_type, SUPPORTED_MIME_TYPES
from lib.agent.scheduler import get_scheduler, SabineScheduler
from backend.services.wal import WALService
from backend.services.task_queue import TaskQueueService, Task, TaskStatus, get_task_queue_service
from backend.services.exceptions import (
    SABINEError,
    AuthorizationError,
    RepoAccessDeniedError,
    ValidationError,
    InvalidRoleError,
    DatabaseError,
    TaskNotFoundError,
    DependencyNotFoundError,
    CircularDependencyError,
    FailedDependencyError,
    AgentError,
    AgentNoToolsError,
    AgentToolFailuresError,
    OperationResult,
)
from backend.services.output_sanitization import (
    sanitize_api_response,
    sanitize_agent_output,
    sanitize_error_message,
    sanitize_for_logging,
)
import asyncio
import hmac
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends, Header, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import uvicorn

# Add project root to path BEFORE importing local modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Now import local modules after path is set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Import shared dependencies
# =============================================================================

from lib.agent.shared import (
    verify_api_key,
    InvokeRequest,
    InvokeResponse,
    MemoryIngestRequest,
    MemoryQueryRequest,
    CancelTaskRequest,
    RequeueTaskRequest,
    CreateTaskRequest,
    TaskResponse,
    ROLE_REPO_AUTHORIZATION,
    VALID_REPOS,
    validate_role_repo_authorization,
)


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Personal Super Agent API",
    description="LangGraph agent powered by Claude 3.5 Sonnet with MCP integrations",
    version="1.0.0"
)

# Add CORS middleware
# Note: FastAPI CORSMiddleware doesn't support wildcard subdomains, so we list explicit origins
# For production, you can also use allow_origin_regex for pattern matching
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://dream-team-strug.vercel.app",
        "https://dream-team-strug-git-main-strugcity.vercel.app",
        "https://dream-team-strug-strugcity.vercel.app",
    ],
    allow_origin_regex=r"https://dream-team-strug.*\.vercel\.app",  # Catch preview deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Helper Functions
# =============================================================================
# Import task execution functions from task_runner module (Phase 2 refactoring)
# Only import what's needed by other modules - _task_requires_tool_execution is internal
from lib.agent.task_runner import _dispatch_task, _run_task_agent


from datetime import datetime, timezone



# =============================================================================
# Mount Routers
# =============================================================================
# Import routers after all models and helper functions are defined
# to avoid circular import issues
# IMPORTANT: This import must remain below _dispatch_task and _run_task_agent
# definitions (dream_team router imports them at load time)

from lib.agent.routers import (
    sabine_router,
    gmail_router,
    memory_router,
    dream_team_router,
    observability_router,
    queue_router,
    salience_settings_router,
    archive_router,
)

# Mount all routers
app.include_router(sabine_router)
app.include_router(gmail_router)
app.include_router(memory_router)
app.include_router(dream_team_router)
app.include_router(observability_router)
app.include_router(queue_router)
app.include_router(salience_settings_router)
app.include_router(archive_router)


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

    # Preflight checks — validates all required env vars and exits on
    # critical failures (e.g. missing ANTHROPIC_API_KEY / SUPABASE creds).
    from lib.agent.preflight import run_preflight_checks, check_redis_reachable
    run_preflight_checks(fail_on_critical=True)
    check_redis_reachable()

    # Preload tools
    try:
        tools = await get_all_tools()
        logger.info(f"✓ Loaded {len(tools)} tools")
        for tool in tools:
            logger.info(f"  - {tool.name}")
    except Exception as e:
        logger.error(f"Failed to load tools: {e}")

    # Start the proactive scheduler
    try:
        scheduler = get_scheduler()
        await scheduler.start()
        logger.info("✓ Proactive scheduler started")
        for job in scheduler.get_jobs():
            logger.info(f"  - {job['name']}: next run at {job['next_run']}")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

    # Start the reminder scheduler (for scheduled SMS/email reminders)
    try:
        from lib.agent.reminder_scheduler import initialize_reminder_scheduler
        reminder_scheduler = await initialize_reminder_scheduler()
        logger.info("✓ Reminder scheduler started")
        reminder_jobs = reminder_scheduler.get_reminder_jobs()
        if reminder_jobs:
            logger.info(f"  - Restored {len(reminder_jobs)} reminder jobs from database")
    except Exception as e:
        logger.error(f"Failed to start reminder scheduler: {e}")

    # Start the email poller (fallback for Gmail push notification delays)
    try:
        from lib.agent.email_poller import initialize_email_poller
        email_poller = await initialize_email_poller()
        logger.info("✓ Email poller started")
        status = email_poller.get_status()
        logger.info(f"  - Polling every {status['interval_minutes']} minutes")
    except Exception as e:
        logger.error(f"Failed to start email poller: {e}")

    # Start Slack Socket Mode (The Gantry)
    try:
        from lib.agent.slack_manager import start_socket_mode

        slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
        slack_app_token = os.getenv("SLACK_APP_TOKEN")

        if slack_bot_token and slack_app_token:
            success = await start_socket_mode()
            if success:
                logger.info("✓ The Gantry (Slack Socket Mode) connected")
            else:
                logger.warning("Failed to start Slack Socket Mode")
        else:
            logger.info("Slack tokens not configured - Gantry disabled")
    except Exception as e:
        logger.error(f"Failed to start Slack Socket Mode: {e}")

    # Get the port for logging
    api_port = os.getenv("PORT") or os.getenv("API_PORT", "8001")
    logger.info("=" * 60)
    logger.info("API Ready!")
    logger.info(f"Listening on http://0.0.0.0:{api_port}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("Personal Super Agent API shutting down...")

    # Stop Slack Socket Mode
    try:
        from lib.agent.slack_manager import stop_socket_mode
        await stop_socket_mode()
        logger.info("✓ Slack Socket Mode stopped")
    except Exception as e:
        logger.error(f"Error stopping Slack Socket Mode: {e}")

    # Gracefully shutdown the scheduler
    try:
        scheduler = get_scheduler()
        if scheduler.is_running():
            await scheduler.shutdown()
            logger.info("✓ Scheduler stopped gracefully")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")

    # Shutdown reminder scheduler
    try:
        from lib.agent.reminder_scheduler import get_reminder_scheduler
        reminder_scheduler = get_reminder_scheduler()
        if reminder_scheduler.is_running():
            await reminder_scheduler.shutdown()
            logger.info("✓ Reminder scheduler stopped gracefully")
    except Exception as e:
        logger.error(f"Error stopping reminder scheduler: {e}")

    # Shutdown email poller
    try:
        from lib.agent.email_poller import get_email_poller
        email_poller = get_email_poller()
        if email_poller.is_running():
            await email_poller.shutdown()
            logger.info("✓ Email poller stopped gracefully")
    except Exception as e:
        logger.error(f"Error stopping email poller: {e}")


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Load environment variables from project root
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    # Get configuration
    # Railway sets PORT env var, we also support API_PORT for backwards compatibility
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("API_PORT", "8001"))
    # Disable reload - it causes issues with PowerShell jobs and file locking
    # Set UVICORN_RELOAD=true to enable if needed
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"

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
