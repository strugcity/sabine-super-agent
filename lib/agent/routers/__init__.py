"""
Router package for FastAPI endpoints.

This package contains modular routers for different API domains:
- sabine: Core agent conversation endpoints
- gmail: Gmail integration endpoints
- memory: Context engine and memory endpoints
- dream_team: Task queue and orchestration endpoints
- observability: Health, metrics, and monitoring endpoints
- queue_routes: rq job queue management endpoints (ADR-002)
- salience_settings: Salience scoring weight management (MEM-004)
- archive: Archive configuration and trigger endpoints (MEM-004)
- user_config: Per-user configuration management (DEBT-004)
- graph: MAGMA entity relationship graph endpoints
"""

from .sabine import router as sabine_router
from .gmail import router as gmail_router
from .memory import router as memory_router
from .dream_team import router as dream_team_router
from .observability import router as observability_router
from .queue_routes import router as queue_router
from .salience_settings import router as salience_settings_router
from .archive import router as archive_router
from .user_config import router as user_config_router
from .graph import router as graph_router

__all__ = [
    "sabine_router",
    "gmail_router",
    "memory_router",
    "dream_team_router",
    "observability_router",
    "queue_router",
    "salience_settings_router",
    "archive_router",
    "user_config_router",
    "graph_router",
]
