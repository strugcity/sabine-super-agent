"""
Streaming Acknowledgment Service for Sabine 2.0
=================================================

Prevents SMS and other channel timeouts by sending an early acknowledgment
message when the main agent response takes longer than a configurable
threshold (default 5 seconds).

Features:
- Async timer using ``asyncio.Event`` and ``asyncio.create_task``
- Cancellable: if the real response arrives before the timer, ack is suppressed
- Contextual ack templates (generic, entity-aware, topic-aware)
- Warm, personal-assistant tone matching Sabine's personality

Owner: @backend-architect-sabine
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Awaitable, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Config Models
# =============================================================================


class AckConfig(BaseModel):
    """Configuration for the acknowledgment timer."""

    timeout_seconds: float = Field(
        default=5.0,
        gt=0.0,
        le=60.0,
        description="Seconds to wait before sending an acknowledgment (default 5s)",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the acknowledgment system is active",
    )


class AckCategory(str, Enum):
    """Category of acknowledgment template."""

    GENERIC = "generic"
    CONTEXT_AWARE = "context_aware"
    TOPIC_CALENDAR = "topic_calendar"
    TOPIC_REMINDER = "topic_reminder"
    TOPIC_WEATHER = "topic_weather"
    TOPIC_EMAIL = "topic_email"


class AckTemplate(BaseModel):
    """A single acknowledgment template."""

    category: AckCategory = Field(
        ..., description="Template category (generic, context_aware, topic_*)"
    )
    template: str = Field(
        ..., description="Template string, may contain {entity} placeholder"
    )
    requires_entity: bool = Field(
        default=False,
        description="Whether the template requires an entity to be injected",
    )


class AckResult(BaseModel):
    """Result from an acknowledgment attempt."""

    sent: bool = Field(
        default=False,
        description="Whether an acknowledgment was actually sent",
    )
    message: str = Field(
        default="",
        description="The acknowledgment message that was sent (empty if not sent)",
    )
    category: Optional[AckCategory] = Field(
        default=None,
        description="Category of the template used",
    )
    cancelled: bool = Field(
        default=False,
        description="Whether the ack was cancelled before firing",
    )
    timestamp: str = Field(
        default="",
        description="ISO timestamp when the ack was sent/cancelled",
    )


# =============================================================================
# Acknowledgment Templates
# =============================================================================

ACK_TEMPLATES: List[AckTemplate] = [
    # --- Generic templates ---
    AckTemplate(
        category=AckCategory.GENERIC,
        template="Let me think about that...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.GENERIC,
        template="Working on it \u2014 one moment...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.GENERIC,
        template="Give me a second...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.GENERIC,
        template="On it! Just a moment...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.GENERIC,
        template="Hang tight, working on that for you...",
        requires_entity=False,
    ),
    # --- Context-aware templates (require entity) ---
    AckTemplate(
        category=AckCategory.CONTEXT_AWARE,
        template="Pulling up your {entity} info...",
        requires_entity=True,
    ),
    AckTemplate(
        category=AckCategory.CONTEXT_AWARE,
        template="Looking into {entity}...",
        requires_entity=True,
    ),
    AckTemplate(
        category=AckCategory.CONTEXT_AWARE,
        template="Let me check on {entity} for you...",
        requires_entity=True,
    ),
    # --- Topic-aware: Calendar ---
    AckTemplate(
        category=AckCategory.TOPIC_CALENDAR,
        template="Checking your schedule...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.TOPIC_CALENDAR,
        template="Looking at your calendar...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.TOPIC_CALENDAR,
        template="Let me pull up your upcoming events...",
        requires_entity=False,
    ),
    # --- Topic-aware: Reminder ---
    AckTemplate(
        category=AckCategory.TOPIC_REMINDER,
        template="Looking at your reminders...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.TOPIC_REMINDER,
        template="Checking your reminders...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.TOPIC_REMINDER,
        template="Let me set that up for you...",
        requires_entity=False,
    ),
    # --- Topic-aware: Weather ---
    AckTemplate(
        category=AckCategory.TOPIC_WEATHER,
        template="Checking the forecast...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.TOPIC_WEATHER,
        template="Let me look up the weather...",
        requires_entity=False,
    ),
    # --- Topic-aware: Email ---
    AckTemplate(
        category=AckCategory.TOPIC_EMAIL,
        template="Checking your inbox...",
        requires_entity=False,
    ),
    AckTemplate(
        category=AckCategory.TOPIC_EMAIL,
        template="Looking through your emails...",
        requires_entity=False,
    ),
]

# Topic keyword mapping for simple keyword-based topic detection
TOPIC_KEYWORDS: dict[AckCategory, List[str]] = {
    AckCategory.TOPIC_CALENDAR: [
        "calendar", "schedule", "meeting", "appointment", "event",
        "busy", "free", "availability", "book", "reschedule",
    ],
    AckCategory.TOPIC_REMINDER: [
        "remind", "reminder", "reminders", "don't forget",
        "alert", "notify", "notification",
    ],
    AckCategory.TOPIC_WEATHER: [
        "weather", "forecast", "temperature", "rain", "sunny",
        "snow", "cold", "hot", "humid", "wind",
    ],
    AckCategory.TOPIC_EMAIL: [
        "email", "emails", "inbox", "mail", "message",
        "send email", "check email",
    ],
}


def _detect_topic(message: str) -> Optional[AckCategory]:
    """
    Detect the topic category from message keywords.

    Performs case-insensitive keyword matching against the message text.

    Args:
        message: The user's message text.

    Returns:
        The matched ``AckCategory`` or None if no topic keywords match.
    """
    lower_message = message.lower()
    for category, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower_message:
                return category
    return None


def generate_ack_message(
    message: str,
    entities: Optional[List[str]] = None,
) -> str:
    """
    Generate a contextual acknowledgment message.

    Selection priority:
    1. If entities are available, use a context-aware template (70% chance)
    2. If a topic is detected from keywords, use a topic-specific template
    3. Fall back to a generic template

    Args:
        message: The user's message text (used for topic detection).
        entities: Optional list of entity names extracted from the message.

    Returns:
        A human-friendly acknowledgment string.
    """
    # Priority 1: Context-aware if entities present
    if entities and len(entities) > 0:
        # 70% chance to use entity-aware template, 30% generic/topic
        if random.random() < 0.7:
            entity = entities[0]
            context_templates = [
                t for t in ACK_TEMPLATES
                if t.category == AckCategory.CONTEXT_AWARE
            ]
            if context_templates:
                chosen = random.choice(context_templates)
                return chosen.template.format(entity=entity)

    # Priority 2: Topic-aware from keyword detection
    topic = _detect_topic(message)
    if topic is not None:
        topic_templates = [
            t for t in ACK_TEMPLATES if t.category == topic
        ]
        if topic_templates:
            chosen = random.choice(topic_templates)
            return chosen.template

    # Priority 3: Generic fallback
    generic_templates = [
        t for t in ACK_TEMPLATES if t.category == AckCategory.GENERIC
    ]
    chosen = random.choice(generic_templates)
    return chosen.template


# =============================================================================
# Acknowledgment Manager
# =============================================================================


class AcknowledgmentManager:
    """
    Manages an async timer that fires an acknowledgment if the main agent
    response takes longer than the configured threshold.

    Usage::

        async def on_ack(msg: str) -> None:
            print(f"Ack sent: {msg}")

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=5.0),
            on_ack=on_ack,
            user_message="What's on my calendar today?",
        )
        mgr.start()

        # ... do the slow work ...
        result = await run_sabine_agent(...)

        # Cancel the ack if we finished in time
        ack_result = await mgr.cancel()

    Attributes:
        config: Acknowledgment configuration.
        on_ack: Async callback invoked with the ack message when the timer fires.
        user_message: The user's original message (for context-aware ack generation).
        entities: Optional list of entity names for context-aware templates.
    """

    def __init__(
        self,
        config: AckConfig,
        on_ack: Callable[[str], Awaitable[None]],
        user_message: str,
        entities: Optional[List[str]] = None,
    ) -> None:
        self._config = config
        self._on_ack = on_ack
        self._user_message = user_message
        self._entities = entities
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._task: Optional[asyncio.Task[None]] = None
        self._result: AckResult = AckResult()
        self._fired: bool = False

    @property
    def config(self) -> AckConfig:
        """Return the acknowledgment configuration."""
        return self._config

    @property
    def fired(self) -> bool:
        """Whether the ack timer has already fired."""
        return self._fired

    @property
    def result(self) -> AckResult:
        """The result of the acknowledgment attempt."""
        return self._result

    def start(self) -> None:
        """
        Start the acknowledgment timer as an async task.

        If the config is disabled, this is a no-op.
        """
        if not self._config.enabled:
            logger.debug("AcknowledgmentManager disabled, not starting timer")
            return

        self._task = asyncio.create_task(self._timer_loop())
        logger.debug(
            "AcknowledgmentManager started: timeout=%.1fs",
            self._config.timeout_seconds,
        )

    async def _timer_loop(self) -> None:
        """
        Internal timer coroutine.

        Waits for ``timeout_seconds``. If the cancel event is NOT set by then,
        generates and sends an acknowledgment message via the callback.
        """
        try:
            # Wait for either the timeout or cancellation
            cancelled = await asyncio.wait_for(
                self._cancel_event.wait(),
                timeout=self._config.timeout_seconds,
            )
            # If we get here, the event was set (cancelled before timeout)
            if cancelled:
                self._result = AckResult(
                    sent=False,
                    cancelled=True,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                logger.debug("AcknowledgmentManager cancelled before timeout")

        except asyncio.TimeoutError:
            # Timer fired — generate and send ack
            try:
                ack_message = generate_ack_message(
                    message=self._user_message,
                    entities=self._entities,
                )
                self._fired = True
                await self._on_ack(ack_message)
                self._result = AckResult(
                    sent=True,
                    message=ack_message,
                    category=_detect_topic(self._user_message) or AckCategory.GENERIC,
                    cancelled=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                logger.info(
                    "Ack sent after %.1fs: %s",
                    self._config.timeout_seconds,
                    ack_message,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send acknowledgment: %s", exc, exc_info=True
                )
                self._result = AckResult(
                    sent=False,
                    cancelled=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        except asyncio.CancelledError:
            self._result = AckResult(
                sent=False,
                cancelled=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            logger.debug("AcknowledgmentManager task was cancelled")

    async def cancel(self) -> AckResult:
        """
        Cancel the acknowledgment timer.

        If the timer has already fired, this returns the result of the fired ack.
        If the timer hasn't fired yet, it cancels it and returns a cancelled result.

        Returns:
            ``AckResult`` describing what happened.
        """
        self._cancel_event.set()

        if self._task is not None and not self._task.done():
            # Give the task a moment to process the cancel event
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        if not self._result.sent and not self._result.cancelled:
            self._result = AckResult(
                sent=False,
                cancelled=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        return self._result


# =============================================================================
# SSE Event Helpers
# =============================================================================


class SSEEvent(BaseModel):
    """A single Server-Sent Event payload."""

    type: str = Field(
        ..., description="Event type: ack, thinking, response, error, done"
    )
    data: str = Field(
        default="", description="Event data payload"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO timestamp of this event",
    )


def _format_sse(event: SSEEvent) -> str:
    """
    Format an SSE event for the wire.

    Follows the standard SSE format: ``data: {json}\\n\\n``

    Args:
        event: The SSEEvent to format.

    Returns:
        The formatted SSE string ready to be yielded.
    """
    payload = event.model_dump()
    return f"data: {json.dumps(payload)}\n\n"
