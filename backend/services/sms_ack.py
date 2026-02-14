"""
SMS Acknowledgment Service for Sabine 2.0
==========================================

Stub implementation for sending SMS acknowledgment messages when the
main agent response takes longer than the configured threshold.

The actual Twilio integration is handled separately; this module provides
the interface and logging for the ack-over-SMS path.

Owner: @backend-architect-sabine
"""

import logging
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
# SMS Sending (Stub)
# =============================================================================


async def send_sms_acknowledgment(to_number: str, message: str) -> bool:
    """
    Send an SMS acknowledgment message to the user.

    This is a **stub implementation** that logs the ack message.
    The real Twilio send is wired in separately.

    Args:
        to_number: The recipient phone number (E.164 format).
        message: The acknowledgment message text.

    Returns:
        True if the "send" was successful (always True in stub mode).
    """
    logger.info(
        "SMS ack stub: to=%s message=%r (Twilio integration pending)",
        to_number,
        message,
    )
    return True


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
