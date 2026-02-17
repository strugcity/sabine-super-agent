"""
Gmail Get Message Skill Handler

Fetches the full content of a Gmail message, including body text and
attachment extraction. Supports plain text, HTML, CSV, and PDF (via pypdf).

Uses the same OAuth2 credential architecture as the calendar skill.
"""

import base64
import io
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

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
        logger.error("Missing Google OAuth credentials for Gmail get message")
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


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace from an HTML string."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_header(headers: List[Dict[str, str]], name: str) -> str:
    """Extract a header value by name from a list of header dicts."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body_data(data: str) -> bytes:
    """Decode base64url-encoded body data from the Gmail API."""
    # Gmail uses URL-safe base64 without padding; add padding if needed
    padded = data + "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _walk_parts(
    payload: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Recursively walk the MIME payload to extract body text and attachment metadata.

    Returns:
        (body_text, attachments)
        body_text: best available plain-text representation of the email body
        attachments: list of dicts with filename, mimeType, size, attachmentId
    """
    mime_type: str = payload.get("mimeType", "")
    parts: List[Dict[str, Any]] = payload.get("parts", [])
    body_obj: Dict[str, Any] = payload.get("body", {})
    filename: str = payload.get("filename", "")

    # Collect results across recursive calls
    plain_text: str = ""
    html_text: str = ""
    attachments: List[Dict[str, Any]] = []

    # Leaf node with actual body data
    if not parts:
        raw_data: str = body_obj.get("data", "")
        if filename:
            # This is an attachment leaf
            attachment_id: str = body_obj.get("attachmentId", "")
            size: int = body_obj.get("size", 0)
            attachments.append({
                "filename": filename,
                "mime_type": mime_type,
                "size": size,
                "attachmentId": attachment_id,
            })
        elif raw_data:
            try:
                decoded = _decode_body_data(raw_data).decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"Failed to decode body part ({mime_type}): {e}")
                decoded = ""

            if mime_type == "text/plain":
                plain_text = decoded
            elif mime_type == "text/html":
                html_text = decoded
        return plain_text or (_strip_html(html_text) if html_text else ""), attachments

    # Multipart node — recurse into each part
    for part in parts:
        part_body, part_attachments = _walk_parts(part)
        attachments.extend(part_attachments)

        part_mime: str = part.get("mimeType", "")
        if part_mime == "text/plain" and part_body and not plain_text:
            plain_text = part_body
        elif part_mime == "text/html" and part_body and not html_text:
            html_text = part_body
        elif part_mime.startswith("multipart/") and part_body and not plain_text:
            # Nested multipart result — use as fallback body
            plain_text = part_body

    body_text = plain_text or (_strip_html(html_text) if html_text else "")
    return body_text, attachments


def _extract_text_from_bytes(raw: bytes, mime_type: str, filename: str) -> Dict[str, Any]:
    """
    Extract readable text from raw attachment bytes based on MIME type.

    Returns a dict suitable for inclusion in the attachments list.
    """
    result: Dict[str, Any] = {
        "filename": filename,
        "mime_type": mime_type,
        "size": len(raw),
    }

    if mime_type in ("text/plain",):
        try:
            result["content"] = raw.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Failed to decode text/plain attachment '{filename}': {e}")
            result["content"] = ""

    elif mime_type == "text/csv":
        try:
            result["content"] = raw.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Failed to decode text/csv attachment '{filename}': {e}")
            result["content"] = ""

    elif mime_type == "text/html":
        try:
            html = raw.decode("utf-8", errors="replace")
            result["content"] = _strip_html(html)
        except Exception as e:
            logger.warning(f"Failed to decode text/html attachment '{filename}': {e}")
            result["content"] = ""

    elif mime_type == "application/pdf":
        try:
            import pypdf  # lazy import — optional dependency
            reader = pypdf.PdfReader(io.BytesIO(raw))
            pages_text = []
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    pages_text.append(extracted)
            result["content"] = "\n".join(pages_text)
        except ImportError:
            result["note"] = "PDF extraction requires pypdf"
        except Exception as e:
            logger.warning(f"Failed to extract PDF text from '{filename}': {e}")
            result["note"] = f"PDF extraction failed: {e}"

    else:
        result["note"] = "Binary attachment, cannot extract text"

    return result


async def get_gmail_message_content(
    message_id: str,
    include_attachments: bool = True,
) -> Dict[str, Any]:
    """
    Get the full content of a Gmail message by its ID.

    Args:
        message_id: Gmail message ID (from search_gmail_messages)
        include_attachments: Whether to download and extract text from attachments

    Returns:
        Dict with message_id, subject, sender, date, body, and attachments list.
    """
    logger.info(
        f"Fetching Gmail message id={message_id} include_attachments={include_attachments}"
    )

    access_token = await get_access_token()
    if not access_token:
        return {
            "status": "error",
            "message": "Failed to authenticate with Gmail. Please check credentials.",
        }

    try:
        async with httpx.AsyncClient() as client:
            # Step 1: Fetch the full message
            msg_response = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": "full"},
            )

            if msg_response.status_code != 200:
                logger.error(
                    f"Failed to fetch message {message_id}: "
                    f"{msg_response.status_code} - {msg_response.text}"
                )
                return {
                    "status": "error",
                    "message": (
                        f"Failed to fetch message with status {msg_response.status_code}"
                    ),
                }

            msg_data = msg_response.json()
            payload = msg_data.get("payload", {})
            headers_list: List[Dict[str, str]] = payload.get("headers", [])

            # Step 2: Extract headers
            subject = _extract_header(headers_list, "Subject")
            sender = _extract_header(headers_list, "From")
            recipient = _extract_header(headers_list, "To")
            date = _extract_header(headers_list, "Date")

            # Step 3: Walk MIME payload for body text and attachment metadata
            body_text, attachment_meta = _walk_parts(payload)

            # Step 4: Download and extract attachment content if requested
            processed_attachments: List[Dict[str, Any]] = []

            for meta in attachment_meta:
                attachment_id: str = meta.get("attachmentId", "")
                filename: str = meta.get("filename", "")
                mime_type: str = meta.get("mime_type", "application/octet-stream")
                size: int = meta.get("size", 0)

                if not include_attachments or not attachment_id:
                    # Just report metadata without content
                    processed_attachments.append({
                        "filename": filename,
                        "mime_type": mime_type,
                        "size": size,
                    })
                    continue

                try:
                    att_response = await client.get(
                        f"{GMAIL_API_BASE}/users/me/messages/{message_id}"
                        f"/attachments/{attachment_id}",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )

                    if att_response.status_code != 200:
                        logger.warning(
                            f"Failed to fetch attachment '{filename}': "
                            f"{att_response.status_code}"
                        )
                        processed_attachments.append({
                            "filename": filename,
                            "mime_type": mime_type,
                            "size": size,
                            "note": (
                                f"Download failed with status {att_response.status_code}"
                            ),
                        })
                        continue

                    att_data = att_response.json()
                    encoded: str = att_data.get("data", "")
                    raw_bytes = _decode_body_data(encoded)

                    extracted = _extract_text_from_bytes(raw_bytes, mime_type, filename)
                    # Preserve size from metadata if available
                    if size and "size" not in extracted:
                        extracted["size"] = size
                    processed_attachments.append(extracted)

                except Exception as e:
                    logger.error(f"Error processing attachment '{filename}': {e}")
                    processed_attachments.append({
                        "filename": filename,
                        "mime_type": mime_type,
                        "size": size,
                        "note": f"Error processing attachment: {e}",
                    })

            return {
                "status": "success",
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "to": recipient,
                "date": date,
                "body": body_text,
                "attachments": processed_attachments,
            }

    except Exception as e:
        logger.error(f"Unexpected error in get_gmail_message_content: {e}")
        return {
            "status": "error",
            "message": f"Unexpected error: {e}",
        }


async def execute(params: dict) -> dict:
    """Entry point called by the agent skill runner."""
    message_id = params.get("message_id", "")
    include_attachments = params.get("include_attachments", True)
    return await get_gmail_message_content(
        message_id=message_id,
        include_attachments=include_attachments,
    )
