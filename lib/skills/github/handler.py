"""
GitHub Issues Skill - Local Python implementation

This skill provides GitHub issue management via the GitHub REST API.
It replaces the broken npm-based MCP servers with a reliable Python implementation.

Requires: GITHUB_TOKEN environment variable with 'repo' scope
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Default repository (can be overridden in params)
DEFAULT_OWNER = "strugcity"
DEFAULT_REPO = "sabine-super-agent"

# =============================================================================
# Repository Authorization Enforcement
# =============================================================================
# Valid repositories that can be accessed through this skill.
# This provides a secondary layer of protection beyond the orchestrator-level
# authorization (see server.py ROLE_REPO_AUTHORIZATION).

ALLOWED_REPOS = {
    ("strugcity", "sabine-super-agent"),
    ("strugcity", "dream-team-strug"),
}


def validate_repo_access(owner: str, repo: str) -> tuple[bool, str]:
    """
    Validate that the requested repository is in the allowed list.

    This is a SECONDARY layer of protection. The primary layer is at the
    orchestrator level (server.py validate_role_repo_authorization).

    This layer ensures that even if the orchestrator check is bypassed
    (e.g., direct API call, agent prompt injection), the skill itself
    will refuse to access unauthorized repositories.

    Args:
        owner: Repository owner (e.g., "strugcity")
        repo: Repository name (e.g., "sabine-super-agent")

    Returns:
        Tuple of (is_allowed, error_message)
    """
    if (owner, repo) in ALLOWED_REPOS:
        return True, ""

    allowed_list = [f"{o}/{r}" for o, r in ALLOWED_REPOS]
    return False, (
        f"Repository '{owner}/{repo}' is not in the allowed list. "
        f"Allowed repositories: {allowed_list}. "
        f"This may indicate an agent misconfiguration or prompt injection attempt."
    )

# GitHub API base URL
GITHUB_API = "https://api.github.com"


def get_github_token() -> Optional[str]:
    """Get GitHub token from environment variables."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")


def get_headers() -> Dict[str, str]:
    """Get headers for GitHub API requests."""
    token = get_github_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def list_issues(
    owner: str, repo: str, state: str = "open", limit: int = 30
) -> Dict[str, Any]:
    """List issues in a repository."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    params = {"state": state, "per_page": min(limit, 100)}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=get_headers(), params=params)

        if response.status_code == 200:
            issues = response.json()
            # Filter out pull requests (they appear in issues endpoint)
            issues = [i for i in issues if "pull_request" not in i]
            return {
                "status": "success",
                "count": len(issues),
                "issues": [
                    {
                        "number": i["number"],
                        "title": i["title"],
                        "state": i["state"],
                        "labels": [l["name"] for l in i.get("labels", [])],
                        "created_at": i["created_at"],
                        "url": i["html_url"],
                    }
                    for i in issues
                ],
            }
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def get_issue(owner: str, repo: str, issue_number: int) -> Dict[str, Any]:
    """Get a single issue by number."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=get_headers())

        if response.status_code == 200:
            issue = response.json()
            return {
                "status": "success",
                "issue": {
                    "number": issue["number"],
                    "title": issue["title"],
                    "body": issue.get("body", ""),
                    "state": issue["state"],
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "assignees": [a["login"] for a in issue.get("assignees", [])],
                    "created_at": issue["created_at"],
                    "updated_at": issue["updated_at"],
                    "url": issue["html_url"],
                    "comments": issue["comments"],
                },
            }
        elif response.status_code == 404:
            return {"status": "error", "error": f"Issue #{issue_number} not found"}
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new issue."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    data = {"title": title}
    if body:
        data["body"] = body
    if labels:
        data["labels"] = labels

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=get_headers(), json=data)

        if response.status_code == 201:
            issue = response.json()
            return {
                "status": "success",
                "message": f"Created issue #{issue['number']}",
                "issue": {
                    "number": issue["number"],
                    "title": issue["title"],
                    "url": issue["html_url"],
                },
            }
        elif response.status_code == 401:
            return {
                "status": "error",
                "error": "Authentication failed. Check GITHUB_TOKEN.",
            }
        elif response.status_code == 403:
            return {
                "status": "error",
                "error": "Permission denied. Token may lack 'repo' scope.",
            }
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def update_issue(
    owner: str,
    repo: str,
    issue_number: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    state: Optional[str] = None,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update an existing issue."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}"
    data = {}
    if title:
        data["title"] = title
    if body:
        data["body"] = body
    if state:
        data["state"] = state
    if labels is not None:
        data["labels"] = labels

    if not data:
        return {"status": "error", "error": "No fields to update provided"}

    async with httpx.AsyncClient() as client:
        response = await client.patch(url, headers=get_headers(), json=data)

        if response.status_code == 200:
            issue = response.json()
            return {
                "status": "success",
                "message": f"Updated issue #{issue_number}",
                "issue": {
                    "number": issue["number"],
                    "title": issue["title"],
                    "state": issue["state"],
                    "url": issue["html_url"],
                },
            }
        elif response.status_code == 404:
            return {"status": "error", "error": f"Issue #{issue_number} not found"}
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def add_comment(
    owner: str, repo: str, issue_number: int, body: str
) -> Dict[str, Any]:
    """Add a comment to an issue."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    data = {"body": body}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=get_headers(), json=data)

        if response.status_code == 201:
            comment = response.json()
            return {
                "status": "success",
                "message": f"Added comment to issue #{issue_number}",
                "comment": {
                    "id": comment["id"],
                    "url": comment["html_url"],
                },
            }
        elif response.status_code == 404:
            return {"status": "error", "error": f"Issue #{issue_number} not found"}
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def get_file(
    owner: str, repo: str, path: str, branch: Optional[str] = None
) -> Dict[str, Any]:
    """Get a file's content and SHA from a repository."""
    import base64

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    params = {}
    if branch:
        params["ref"] = branch

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=get_headers(), params=params)

        if response.status_code == 200:
            data = response.json()
            content = ""
            if data.get("content"):
                content = base64.b64decode(data["content"]).decode("utf-8")
            return {
                "status": "success",
                "file": {
                    "path": data["path"],
                    "sha": data["sha"],
                    "size": data["size"],
                    "content": content,
                    "url": data["html_url"],
                },
            }
        elif response.status_code == 404:
            return {"status": "not_found", "error": f"File not found: {path}"}
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def create_or_update_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: Optional[str] = None,
    sha: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create or update a file in a repository.

    If the file exists, sha must be provided (get it via get_file first).
    If creating a new file, sha should be None.
    """
    import base64

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"

    # Base64 encode the content
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    data = {
        "message": message,
        "content": content_b64,
    }
    if branch:
        data["branch"] = branch
    if sha:
        data["sha"] = sha  # Required for updates

    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=get_headers(), json=data)

        if response.status_code in [200, 201]:
            result = response.json()
            action = "updated" if sha else "created"
            return {
                "status": "success",
                "message": f"File {action}: {path}",
                "file": {
                    "path": result["content"]["path"],
                    "sha": result["content"]["sha"],
                    "url": result["content"]["html_url"],
                },
                "commit": {
                    "sha": result["commit"]["sha"],
                    "message": result["commit"]["message"],
                    "url": result["commit"]["html_url"],
                },
            }
        elif response.status_code == 409:
            return {
                "status": "error",
                "error": "Conflict - file may have been modified. Get latest SHA and retry.",
                "detail": response.text,
            }
        elif response.status_code == 422:
            return {
                "status": "error",
                "error": "Invalid request - check path and content",
                "detail": response.text,
            }
        elif response.status_code == 401:
            return {
                "status": "error",
                "error": "Authentication failed. Check GITHUB_TOKEN.",
            }
        elif response.status_code == 403:
            return {
                "status": "error",
                "error": "Permission denied. Token may lack 'repo' scope.",
            }
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def delete_file(
    owner: str,
    repo: str,
    path: str,
    message: str,
    sha: str,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete a file from a repository. Requires the file's current SHA."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"

    data = {
        "message": message,
        "sha": sha,
    }
    if branch:
        data["branch"] = branch

    async with httpx.AsyncClient() as client:
        response = await client.request("DELETE", url, headers=get_headers(), json=data)

        if response.status_code == 200:
            result = response.json()
            return {
                "status": "success",
                "message": f"File deleted: {path}",
                "commit": {
                    "sha": result["commit"]["sha"],
                    "message": result["commit"]["message"],
                    "url": result["commit"]["html_url"],
                },
            }
        elif response.status_code == 404:
            return {"status": "error", "error": f"File not found: {path}"}
        else:
            return {
                "status": "error",
                "error": f"GitHub API error: {response.status_code}",
                "detail": response.text,
            }


async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the GitHub skill.

    Args:
        params: Dict with action and action-specific parameters

    Returns:
        Dict with status, message, and data
    """
    # Check for token
    if not get_github_token():
        return {
            "status": "error",
            "error": "GITHUB_TOKEN environment variable not set",
            "message": "Please set GITHUB_TOKEN with 'repo' scope to use GitHub integration",
        }

    action = params.get("action")
    owner = params.get("owner", DEFAULT_OWNER)
    repo = params.get("repo", DEFAULT_REPO)

    # === REPOSITORY ACCESS VALIDATION ===
    # Secondary layer of protection - validate repo is in allowed list
    is_allowed, error_msg = validate_repo_access(owner, repo)
    if not is_allowed:
        logger.warning(f"BLOCKED: GitHub skill access to {owner}/{repo} - {error_msg}")
        return {
            "status": "error",
            "error": f"Repository access denied: {error_msg}",
            "blocked_repo": f"{owner}/{repo}",
            "allowed_repos": [f"{o}/{r}" for o, r in ALLOWED_REPOS],
        }

    logger.info(f"GitHub skill: {action} on {owner}/{repo}")

    try:
        if action == "list":
            state = params.get("state", "open")
            return await list_issues(owner, repo, state)

        elif action == "get":
            issue_number = params.get("issue_number")
            if not issue_number:
                return {"status": "error", "error": "issue_number is required for 'get' action"}
            return await get_issue(owner, repo, issue_number)

        elif action == "create":
            title = params.get("title")
            if not title:
                return {"status": "error", "error": "title is required for 'create' action"}
            return await create_issue(
                owner, repo, title, params.get("body"), params.get("labels")
            )

        elif action == "update":
            issue_number = params.get("issue_number")
            if not issue_number:
                return {"status": "error", "error": "issue_number is required for 'update' action"}
            return await update_issue(
                owner,
                repo,
                issue_number,
                params.get("title"),
                params.get("body"),
                params.get("state"),
                params.get("labels"),
            )

        elif action == "comment":
            issue_number = params.get("issue_number")
            body = params.get("body")
            if not issue_number:
                return {"status": "error", "error": "issue_number is required for 'comment' action"}
            if not body:
                return {"status": "error", "error": "body is required for 'comment' action"}
            return await add_comment(owner, repo, issue_number, body)

        # File operations
        elif action == "get_file":
            path = params.get("path")
            if not path:
                return {"status": "error", "error": "path is required for 'get_file' action"}
            return await get_file(owner, repo, path, params.get("branch"))

        elif action == "create_file":
            path = params.get("path")
            content = params.get("content")
            message = params.get("message", f"Create {path}")
            if not path:
                return {"status": "error", "error": "path is required for 'create_file' action"}
            if content is None:
                return {"status": "error", "error": "content is required for 'create_file' action"}
            return await create_or_update_file(
                owner, repo, path, content, message, params.get("branch"), sha=None
            )

        elif action == "update_file":
            path = params.get("path")
            content = params.get("content")
            message = params.get("message", f"Update {path}")
            sha = params.get("sha")
            if not path:
                return {"status": "error", "error": "path is required for 'update_file' action"}
            if content is None:
                return {"status": "error", "error": "content is required for 'update_file' action"}
            if not sha:
                # Try to get current SHA automatically
                existing = await get_file(owner, repo, path, params.get("branch"))
                if existing["status"] == "success":
                    sha = existing["file"]["sha"]
                else:
                    return {"status": "error", "error": "sha is required for 'update_file' action (file not found for auto-fetch)"}
            return await create_or_update_file(
                owner, repo, path, content, message, params.get("branch"), sha=sha
            )

        elif action == "delete_file":
            path = params.get("path")
            message = params.get("message", f"Delete {path}")
            sha = params.get("sha")
            if not path:
                return {"status": "error", "error": "path is required for 'delete_file' action"}
            if not sha:
                # Try to get current SHA automatically
                existing = await get_file(owner, repo, path, params.get("branch"))
                if existing["status"] == "success":
                    sha = existing["file"]["sha"]
                else:
                    return {"status": "error", "error": "sha is required for 'delete_file' action (file not found for auto-fetch)"}
            return await delete_file(owner, repo, path, message, sha, params.get("branch"))

        else:
            return {
                "status": "error",
                "error": f"Unknown action: {action}",
                "valid_actions": ["list", "create", "get", "update", "comment", "get_file", "create_file", "update_file", "delete_file"],
            }

    except httpx.RequestError as e:
        logger.error(f"GitHub API request error: {e}")
        return {"status": "error", "error": f"Network error: {str(e)}"}
    except Exception as e:
        logger.error(f"GitHub skill error: {e}")
        return {"status": "error", "error": str(e)}
