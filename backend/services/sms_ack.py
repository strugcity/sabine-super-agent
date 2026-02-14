"""
SMS Acknowledgment Service for Sabine 2.0
==========================================

Stub implementation for sending SMS acknowledgment messages when the
main agent response takes longer than the configured threshold.

The actual Twilio integration is handled separately; this module provides
the interface and logging for the ack-over-SMS path.

Owner: @backend-architect-sabine
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================


class SMSAckResult(BaseModel):
    """Result from an SMS acknowledgment send attempt."""

    sent: bool = Field(
        default=False,
        description="Whether the SMS ack was sent successfully",
    )
    message: str = Field(
        default="",
        description="The acknowledgment message that was sent",
    )
    timestamp: str = Field(
        default="",
        description="ISO timestamp of the send attempt",
    )


# =============================================================================
# Channel Detection
# =============================================================================

# Channels that should receive SMS acknowledgments
SMS_CHANNELS = {"sms", "twilio", "text"}


def should_send_sms_ack(channel: Optional[str]) -> bool:
    """
    Determine whether an SMS acknowledgment should be sent for this request.

    Returns True only for SMS-type channel requests.

    Args:
        channel: The source channel identifier from the request
                 (e.g., "sms", "api", "email-work").

    Returns:
        True if the channel is an SMS-type channel, False otherwise.
    """
    if channel is None:
        return False

    normalised = channel.strip().lower()
    is_sms = normalised in SMS_CHANNELS
    logger.debug(
        "Channel detection: channel=%r normalised=%r is_sms=%s",
        channel,
        normalised,
        is_sms,
    )
    return is_sms


# =============================================================================
# SMS Sending (Twilio)
# =============================================================================


def _send_sms_sync(to_number: str, message: str) -> str:
    """
    Blocking helper that sends an SMS via Twilio and returns the message SID.

    Separated so it can be run inside ``asyncio.to_thread`` without leaking
    async context into the synchronous Twilio client.

    Raises:
        twilio.base.exceptions.TwilioRestException: on Twilio API errors.
    """
    from twilio.rest import Client as TwilioClient  # lazy import

    account_sid: str = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token: str = os.environ["TWILIO_AUTH_TOKEN"]
    from_number: str = os.environ["TWILIO_FROM_NUMBER"]

    client = TwilioClient(account_sid, auth_token)
    sms = client.messages.create(
        body=message,
        from_=from_number,
        to=to_number,
    )
    return sms.sid


async def send_sms_acknowledgment(to_number: str, message: str) -> bool:
    """
    Send an SMS acknowledgment message to the user via Twilio.

    If Twilio credentials are not configured the function logs a warning
    and returns ``False`` without raising.

    Args:
        to_number: The recipient phone number (E.164 format).
        message: The acknowledgment message text.

    Returns:
        True if the SMS was sent successfully, False otherwise.
    """
    # ---- guard: check env vars before attempting the send ----
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    twilio_from = os.getenv("TWILIO_FROM_NUMBER")

    if not all([twilio_sid, twilio_token, twilio_from]):
        logger.warning(
            "Twilio credentials not configured - skipping SMS ack "
            "(to=%s message=%r)",
            to_number,
            message[:100],
        )
        return False

    try:
        # Twilio's REST client is blocking; offload to a thread so we
        # don't stall the async event loop.
        sid = await asyncio.to_thread(_send_sms_sync, to_number, message)
        logger.info("SMS ack sent successfully: sid=%s to=%s", sid, to_number)
        return True

    except Exception as exc:
        # Try to extract Twilio-specific error details first.
        from twilio.base.exceptions import TwilioRestException  # lazy import

        if isinstance(exc, TwilioRestException):
            logger.error(
                "Twilio API error sending SMS ack: code=%s msg=%s to=%s",
                exc.code,
                exc.msg,
                to_number,
                exc_info=True,
            )
        else:
            logger.error(
                "Failed to send SMS ack: error=%s to=%s",
                exc,
                to_number,
                exc_info=True,
            )
        return False


async def handle_sms_ack(
    to_number: str,
    ack_message: str,
) -> SMSAckResult:
    """
    High-level handler for SMS acknowledgment delivery.

    Calls the stub sender and returns a structured result.

    Args:
        to_number: Recipient phone number.
        ack_message: The acknowledgment message text.

    Returns:
        ``SMSAckResult`` with send status and metadata.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        success = await send_sms_acknowledgment(
            to_number=to_number,
            message=ack_message,
        )
        return SMSAckResult(
            sent=success,
            message=ack_message,
            timestamp=timestamp,
        )
    except Exception as exc:
        logger.error(
            "SMS ack delivery failed: to=%s error=%s",
            to_number,
            exc,
            exc_info=True,
        )
        return SMSAckResult(
            sent=False,
            message=ack_message,
            timestamp=timestamp,
        )
