"""
Project Sync Skill - Markdown to GitHub Issues

This skill wraps the architect_parser module to expose sync_project_board
as a tool available to the SABINE_ARCHITECT role.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the project board sync.

    This parses a Markdown file for ### TASK: sections and creates
    corresponding GitHub issues.

    Args:
        params: Dict with file_path, dry_run, owner, repo

    Returns:
        Dict with sync results
    """
    try:
        from lib.agent.architect_parser import sync_project_board
        return await sync_project_board(params)
    except ImportError as e:
        logger.error(f"Failed to import architect_parser: {e}")
        return {
            "status": "error",
            "error": f"Import error: {e}",
            "message": "The architect_parser module could not be loaded"
        }
    except Exception as e:
        logger.error(f"Error in sync_project_board: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "An unexpected error occurred during project board sync"
        }
