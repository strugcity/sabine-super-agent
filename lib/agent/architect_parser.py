"""
Architect Parser - Markdown to GitHub Issues Sync

This module parses Markdown files (especially SABINE_ARCHITECT.md and role files)
to extract task definitions and synchronize them with GitHub Issues.

Task Format in Markdown:
```
### TASK: [Task Title]
**Description:** [Task description]
**Assignee:** [Role name, e.g., backend-architect-sabine]
**Priority:** [high|medium|low]
**Labels:** [comma-separated labels]
```

The parser will:
1. Extract all ### TASK: sections from the file
2. Check if an issue with that title already exists
3. Create new issues for tasks that don't exist
4. Update existing issues if content has changed (optional)
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex patterns for parsing task sections
TASK_PATTERN = re.compile(
    r'###\s+TASK:\s*(.+?)(?=\n)',  # Capture task title
    re.IGNORECASE
)

# Pattern to extract task metadata
DESCRIPTION_PATTERN = re.compile(
    r'\*\*Description:\*\*\s*(.+?)(?=\*\*|\n###|\Z)',
    re.DOTALL | re.IGNORECASE
)
ASSIGNEE_PATTERN = re.compile(
    r'\*\*Assignee:\*\*\s*(.+?)(?=\n)',
    re.IGNORECASE
)
PRIORITY_PATTERN = re.compile(
    r'\*\*Priority:\*\*\s*(.+?)(?=\n)',
    re.IGNORECASE
)
LABELS_PATTERN = re.compile(
    r'\*\*Labels:\*\*\s*(.+?)(?=\n)',
    re.IGNORECASE
)


def extract_tasks_from_markdown(content: str) -> List[Dict[str, Any]]:
    """
    Extract task definitions from Markdown content.

    Args:
        content: Raw Markdown content

    Returns:
        List of task dictionaries with title, description, assignee, priority, labels
    """
    tasks = []

    # Split content by ### TASK: headers
    sections = re.split(r'(?=###\s+TASK:)', content, flags=re.IGNORECASE)

    for section in sections:
        # Check if this section contains a task
        title_match = TASK_PATTERN.search(section)
        if not title_match:
            continue

        title = title_match.group(1).strip()

        # Extract metadata
        task = {
            "title": title,
            "description": "",
            "assignee": None,
            "priority": "medium",
            "labels": []
        }

        # Extract description
        desc_match = DESCRIPTION_PATTERN.search(section)
        if desc_match:
            task["description"] = desc_match.group(1).strip()

        # Extract assignee
        assignee_match = ASSIGNEE_PATTERN.search(section)
        if assignee_match:
            task["assignee"] = assignee_match.group(1).strip()

        # Extract priority
        priority_match = PRIORITY_PATTERN.search(section)
        if priority_match:
            priority = priority_match.group(1).strip().lower()
            if priority in ["high", "medium", "low"]:
                task["priority"] = priority

        # Extract labels
        labels_match = LABELS_PATTERN.search(section)
        if labels_match:
            labels_str = labels_match.group(1).strip()
            task["labels"] = [l.strip() for l in labels_str.split(",") if l.strip()]

        # Add source role label based on assignee
        if task["assignee"]:
            role_label = f"role:{task['assignee']}"
            if role_label not in task["labels"]:
                task["labels"].append(role_label)

        # Add priority label
        priority_label = f"priority:{task['priority']}"
        if priority_label not in task["labels"]:
            task["labels"].append(priority_label)

        tasks.append(task)
        logger.debug(f"Extracted task: {title}")

    logger.info(f"Extracted {len(tasks)} tasks from Markdown")
    return tasks


async def parse_and_sync_issues(
    file_path: str,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Parse a Markdown file and sync tasks to GitHub Issues.

    This function:
    1. Reads the specified Markdown file
    2. Extracts all ### TASK: sections
    3. Checks existing GitHub issues to avoid duplicates
    4. Creates new issues for tasks that don't exist

    Args:
        file_path: Path to the Markdown file (relative to project root or absolute)
        owner: GitHub repo owner (default: from env or "strugcity")
        repo: GitHub repo name (default: from env or "sabine-super-agent")
        dry_run: If True, don't actually create issues, just return what would be created

    Returns:
        Dict with status, created issues, skipped issues, and errors
    """
    from lib.skills.github.handler import execute as github_execute, DEFAULT_OWNER, DEFAULT_REPO

    owner = owner or os.getenv("GITHUB_OWNER", DEFAULT_OWNER)
    repo = repo or os.getenv("GITHUB_REPO", DEFAULT_REPO)

    result = {
        "status": "success",
        "file_path": file_path,
        "repository": f"{owner}/{repo}",
        "dry_run": dry_run,
        "tasks_found": 0,
        "issues_created": [],
        "issues_skipped": [],
        "errors": []
    }

    # Resolve file path
    if not os.path.isabs(file_path):
        # Try relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        file_path = os.path.join(project_root, file_path)

    # Read the Markdown file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.info(f"Read {len(content)} chars from {file_path}")
    except FileNotFoundError:
        result["status"] = "error"
        result["errors"].append(f"File not found: {file_path}")
        return result
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(f"Error reading file: {e}")
        return result

    # Extract tasks from Markdown
    tasks = extract_tasks_from_markdown(content)
    result["tasks_found"] = len(tasks)

    if not tasks:
        result["message"] = "No tasks found in file. Tasks should be formatted as '### TASK: [Title]'"
        return result

    # Get existing issues from GitHub
    try:
        existing_issues_result = await github_execute({
            "action": "list",
            "owner": owner,
            "repo": repo,
            "state": "all"  # Check both open and closed
        })

        if existing_issues_result.get("status") != "success":
            result["errors"].append(f"Failed to fetch existing issues: {existing_issues_result.get('error')}")
            # Continue anyway, might create duplicates but better than failing

        existing_titles = set()
        if existing_issues_result.get("issues"):
            existing_titles = {issue["title"].lower() for issue in existing_issues_result["issues"]}
            logger.info(f"Found {len(existing_titles)} existing issues")

    except Exception as e:
        logger.error(f"Error fetching existing issues: {e}")
        result["errors"].append(f"Error fetching existing issues: {e}")
        existing_titles = set()

    # Process each task
    for task in tasks:
        task_title = task["title"]

        # Check if issue already exists (case-insensitive)
        if task_title.lower() in existing_titles:
            result["issues_skipped"].append({
                "title": task_title,
                "reason": "Issue already exists"
            })
            logger.info(f"Skipping existing issue: {task_title}")
            continue

        # Build issue body
        body_parts = []
        if task["description"]:
            body_parts.append(task["description"])
        if task["assignee"]:
            body_parts.append(f"\n**Assigned Role:** {task['assignee']}")
        if task["priority"]:
            body_parts.append(f"**Priority:** {task['priority']}")

        body_parts.append("\n---\n*Auto-generated by SABINE_ARCHITECT from Markdown planning document*")
        body = "\n".join(body_parts)

        if dry_run:
            result["issues_created"].append({
                "title": task_title,
                "labels": task["labels"],
                "body_preview": body[:200] + "..." if len(body) > 200 else body,
                "dry_run": True
            })
            logger.info(f"[DRY RUN] Would create issue: {task_title}")
            continue

        # Create the issue
        try:
            create_result = await github_execute({
                "action": "create",
                "owner": owner,
                "repo": repo,
                "title": task_title,
                "body": body,
                "labels": task["labels"]
            })

            if create_result.get("status") == "success":
                result["issues_created"].append({
                    "title": task_title,
                    "number": create_result.get("issue", {}).get("number"),
                    "url": create_result.get("issue", {}).get("url"),
                    "labels": task["labels"]
                })
                logger.info(f"Created issue: {task_title}")
                # Add to existing titles to prevent duplicates in same run
                existing_titles.add(task_title.lower())
            else:
                result["errors"].append({
                    "task": task_title,
                    "error": create_result.get("error", "Unknown error")
                })
                logger.error(f"Failed to create issue '{task_title}': {create_result.get('error')}")

        except Exception as e:
            result["errors"].append({
                "task": task_title,
                "error": str(e)
            })
            logger.error(f"Exception creating issue '{task_title}': {e}")

    # Set final status
    if result["errors"]:
        result["status"] = "partial" if result["issues_created"] else "error"

    result["summary"] = {
        "tasks_found": len(tasks),
        "issues_created": len(result["issues_created"]),
        "issues_skipped": len(result["issues_skipped"]),
        "errors": len(result["errors"])
    }

    return result


async def sync_project_board(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool wrapper for parse_and_sync_issues.

    This is exposed as a tool to the SABINE_ARCHITECT role.

    Args:
        params: Dict with:
            - file_path (str): Path to Markdown file (default: docs/roles/SABINE_ARCHITECT.md)
            - dry_run (bool): If True, don't create issues, just preview (default: False)
            - owner (str): GitHub owner (optional)
            - repo (str): GitHub repo (optional)

    Returns:
        Result from parse_and_sync_issues
    """
    file_path = params.get("file_path", "docs/roles/SABINE_ARCHITECT.md")
    dry_run = params.get("dry_run", False)
    owner = params.get("owner")
    repo = params.get("repo")

    return await parse_and_sync_issues(
        file_path=file_path,
        owner=owner,
        repo=repo,
        dry_run=dry_run
    )
