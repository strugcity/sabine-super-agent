"""
Gmail Search Skill Handler

Searches Gmail messages using the Gmail API with OAuth2 refresh tokens.
Uses the same credential architecture as the calendar skill (USER_REFRESH_TOKEN).
"""

import os
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"


async def get_access_token() -> Optional[str]:
    """
    Get a fresh access token using the USER_REFRESH_TOKEN.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.getenv("USER_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        logger.error("Missing Google OAuth credentials for Gmail search")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("access_token")
            else:
                logger.error(
                    f"Failed to refresh token: {response.status_code} - {response.text}"
                )
                return None

    except Exception as e:
        logger.error(f"Error refreshing access token: {e}")
        return None


def _extract_header(headers: List[Dict[str, str]], name: str) -> str:
    """Extract a header value by name from a list of header dicts."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


async def search_gmail_messages(
    query: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """
    Search Gmail messages using Gmail query syntax.

    Args:
        query: Gmail search query (e.g. 'from:user@example.com is:unread')
        max_results: Maximum number of messages to return (default 10)

    Returns:
        Dict with 'messages' list and 'total' count.
        Each message has: message_id, subject, sender, date, snippet.
    """
    logger.info(f"Searching Gmail with query='{query}' max_results={max_results}")

    access_token = await get_access_token()
    if not access_token:
        return {
            "status": "error",
            "message": "Failed to authenticate with Gmail. Please check credentials.",
            "messages": [],
            "total": 0,
        }

    try:
        async with httpx.AsyncClient() as client:
            # Step 1: Search for message IDs
            search_response = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "q": query,
                    "maxResults": max_results,
                },
            )

            if search_response.status_code != 200:
                logger.error(
                    f"Gmail search failed: {search_response.status_code} - {search_response.text}"
                )
                return {
                    "status": "error",
                    "message": f"Gmail search failed with status {search_response.status_code}",
                    "messages": [],
                    "total": 0,
                }

            search_data = search_response.json()
            message_refs = search_data.get("messages", [])
            result_size_estimate = search_data.get("resultSizeEstimate", 0)

            if not message_refs:
                return {
                    "status": "success",
                    "messages": [],
                    "total": 0,
                }

            # Step 2: Fetch metadata for each message
            messages: List[Dict[str, Any]] = []
            for ref in message_refs[:max_results]:
                msg_id = ref.get("id", "")
                try:
                    meta_response = await client.get(
                        f"{GMAIL_API_BASE}/users/me/messages/{msg_id}",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={
                            "format": "metadata",
                            "metadataHeaders": ["Subject", "From", "Date"],
                        },
                    )

                    if meta_response.status_code != 200:
                        logger.warning(
                            f"Failed to fetch metadata for message {msg_id}: "
                            f"{meta_response.status_code}"
                        )
                        continue

                    msg_data = meta_response.json()
                    headers_list = msg_data.get("payload", {}).get("headers", [])

                    messages.append({
                        "message_id": msg_id,
                        "subject": _extract_header(headers_list, "Subject"),
                        "sender": _extract_header(headers_list, "From"),
                        "date": _extract_header(headers_list, "Date"),
                        "snippet": msg_data.get("snippet", ""),
                    })

                except Exception as e:
                    logger.error(f"Error fetching metadata for message {msg_id}: {e}")
                    continue

            return {
                "status": "success",
                "messages": messages,
                "total": len(messages),
            }

    except Exception as e:
        logger.error(f"Unexpected error in search_gmail_messages: {e}")
        return {
            "status": "error",
            "message": f"Unexpected error: {e}",
            "messages": [],
            "total": 0,
        }


async def execute(params: dict) -> dict:
    """Entry point called by the agent skill runner."""
    query = params.get("query", "")
    max_results = params.get("max_results", 10)
    return await search_gmail_messages(query=query, max_results=max_results)
