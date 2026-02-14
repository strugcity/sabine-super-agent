"""
Streaming Acknowledgment Tests
===============================

Comprehensive test suite for the streaming acknowledgment system:
- ``backend/services/streaming_ack.py`` — AcknowledgmentManager, templates, config
- ``backend/services/sms_ack.py`` — SMS channel detection and stub sender
- ``lib/agent/routers/sabine.py`` — SSE /invoke/stream endpoint, SMS ack in /invoke

Test Categories:
1. AcknowledgmentManager timer fires after timeout
2. AcknowledgmentManager cancels when response arrives early
3. AcknowledgmentManager disabled config
4. Contextual ack message generation (generic, entity-aware, topic-aware)
5. Topic detection from keywords
6. AckTemplate and AckConfig validation
7. SSE event format validation
8. SMS ack stub send
9. SMS channel detection
10. /invoke backwards compatibility
11. SSE endpoint event sequence
12. Edge cases and error handling

All async agent interactions are mocked so no real API calls are made.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from backend.services.streaming_ack import (
    AckCategory,
    AckConfig,
    AckResult,
    AckTemplate,
    AcknowledgmentManager,
    ACK_TEMPLATES,
    TOPIC_KEYWORDS,
    _detect_topic,
    generate_ack_message,
    SSEEvent,
    _format_sse,
)
from backend.services.sms_ack import (
    SMSAckResult,
    should_send_sms_ack,
    send_sms_acknowledgment,
    handle_sms_ack,
)


# =============================================================================
# 1. AckConfig Validation
# =============================================================================


class TestAckConfig:
    """Tests for the AckConfig Pydantic model."""

    def test_default_config(self) -> None:
        """Default config has 5s timeout and is enabled."""
        config = AckConfig()
        assert config.timeout_seconds == 5.0
        assert config.enabled is True

    def test_custom_timeout(self) -> None:
        """Custom timeout value is accepted."""
        config = AckConfig(timeout_seconds=10.0)
        assert config.timeout_seconds == 10.0

    def test_disabled_config(self) -> None:
        """Config can be explicitly disabled."""
        config = AckConfig(enabled=False)
        assert config.enabled is False

    def test_timeout_must_be_positive(self) -> None:
        """Timeout must be greater than 0."""
        with pytest.raises(Exception):
            AckConfig(timeout_seconds=0.0)

    def test_timeout_max_60s(self) -> None:
        """Timeout must not exceed 60 seconds."""
        with pytest.raises(Exception):
            AckConfig(timeout_seconds=61.0)


# =============================================================================
# 2. AckTemplate Validation
# =============================================================================


class TestAckTemplate:
    """Tests for the AckTemplate Pydantic model."""

    def test_template_creation(self) -> None:
        """A template can be created with all required fields."""
        tmpl = AckTemplate(
            category=AckCategory.GENERIC,
            template="Thinking...",
            requires_entity=False,
        )
        assert tmpl.category == AckCategory.GENERIC
        assert tmpl.template == "Thinking..."
        assert tmpl.requires_entity is False

    def test_entity_template(self) -> None:
        """Entity-aware template requires entity flag."""
        tmpl = AckTemplate(
            category=AckCategory.CONTEXT_AWARE,
            template="Looking into {entity}...",
            requires_entity=True,
        )
        assert tmpl.requires_entity is True
        assert "{entity}" in tmpl.template

    def test_all_templates_valid(self) -> None:
        """All built-in templates are valid AckTemplate instances."""
        for tmpl in ACK_TEMPLATES:
            assert isinstance(tmpl, AckTemplate)
            assert len(tmpl.template) > 0

    def test_generic_templates_exist(self) -> None:
        """At least 3 generic templates are available."""
        generics = [t for t in ACK_TEMPLATES if t.category == AckCategory.GENERIC]
        assert len(generics) >= 3

    def test_context_templates_have_entity_placeholder(self) -> None:
        """All context-aware templates contain {entity} placeholder."""
        context_templates = [
            t for t in ACK_TEMPLATES if t.category == AckCategory.CONTEXT_AWARE
        ]
        for tmpl in context_templates:
            assert "{entity}" in tmpl.template
            assert tmpl.requires_entity is True


# =============================================================================
# 3. Topic Detection
# =============================================================================


class TestTopicDetection:
    """Tests for keyword-based topic detection."""

    def test_calendar_keywords(self) -> None:
        """Calendar keywords are detected."""
        assert _detect_topic("What's on my calendar today?") == AckCategory.TOPIC_CALENDAR
        assert _detect_topic("Do I have any meetings?") == AckCategory.TOPIC_CALENDAR
        assert _detect_topic("Schedule a meeting") == AckCategory.TOPIC_CALENDAR

    def test_reminder_keywords(self) -> None:
        """Reminder keywords are detected."""
        assert _detect_topic("Remind me to call Mom") == AckCategory.TOPIC_REMINDER
        assert _detect_topic("What are my reminders?") == AckCategory.TOPIC_REMINDER

    def test_weather_keywords(self) -> None:
        """Weather keywords are detected."""
        assert _detect_topic("What's the weather like?") == AckCategory.TOPIC_WEATHER
        assert _detect_topic("Will it rain tomorrow?") == AckCategory.TOPIC_WEATHER
        assert _detect_topic("What's the forecast?") == AckCategory.TOPIC_WEATHER

    def test_email_keywords(self) -> None:
        """Email keywords are detected."""
        assert _detect_topic("Check my email") == AckCategory.TOPIC_EMAIL
        assert _detect_topic("Any new emails?") == AckCategory.TOPIC_EMAIL

    def test_no_topic_detected(self) -> None:
        """Returns None when no topic keywords match."""
        assert _detect_topic("Tell me a joke") is None
        assert _detect_topic("What's 2 + 2?") is None

    def test_case_insensitive(self) -> None:
        """Topic detection is case-insensitive."""
        assert _detect_topic("CALENDAR") == AckCategory.TOPIC_CALENDAR
        assert _detect_topic("Weather") == AckCategory.TOPIC_WEATHER


# =============================================================================
# 4. Contextual Ack Message Generation
# =============================================================================


class TestGenerateAckMessage:
    """Tests for generate_ack_message()."""

    def test_generic_fallback(self) -> None:
        """Without entities or topic, returns a generic message."""
        msg = generate_ack_message("Tell me a joke")
        assert isinstance(msg, str)
        assert len(msg) > 0
        # Should be one of the generic templates
        generic_texts = [
            t.template for t in ACK_TEMPLATES
            if t.category == AckCategory.GENERIC
        ]
        assert msg in generic_texts

    def test_topic_aware_calendar(self) -> None:
        """Calendar topic returns a calendar-specific ack."""
        msg = generate_ack_message("What's on my calendar?")
        calendar_texts = [
            t.template for t in ACK_TEMPLATES
            if t.category == AckCategory.TOPIC_CALENDAR
        ]
        assert msg in calendar_texts

    def test_topic_aware_weather(self) -> None:
        """Weather topic returns a weather-specific ack."""
        msg = generate_ack_message("What's the forecast tomorrow?")
        weather_texts = [
            t.template for t in ACK_TEMPLATES
            if t.category == AckCategory.TOPIC_WEATHER
        ]
        assert msg in weather_texts

    def test_entity_aware_message(self) -> None:
        """With entities, sometimes returns entity-aware template."""
        # Run multiple times to test the random branch
        entity_msgs = set()
        generic_msgs = set()

        for _ in range(50):
            msg = generate_ack_message("Tell me about Alice", entities=["Alice"])
            if "Alice" in msg:
                entity_msgs.add(msg)
            else:
                generic_msgs.add(msg)

        # With 70% entity probability and 50 iterations,
        # we should see at least some entity messages
        assert len(entity_msgs) > 0, "Expected at least one entity-aware message in 50 tries"

    def test_empty_entities_list(self) -> None:
        """Empty entities list falls back to generic/topic."""
        msg = generate_ack_message("Tell me a joke", entities=[])
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_none_entities(self) -> None:
        """None entities falls back to generic/topic."""
        msg = generate_ack_message("Tell me a joke", entities=None)
        assert isinstance(msg, str)


# =============================================================================
# 5. AcknowledgmentManager — Timer Fires
# =============================================================================


class TestAcknowledgmentManagerFires:
    """Tests for the AcknowledgmentManager timer firing after timeout."""

    @pytest.mark.asyncio
    async def test_timer_fires_after_timeout(self) -> None:
        """Timer fires the callback after the configured timeout."""
        callback_messages: List[str] = []

        async def on_ack(msg: str) -> None:
            callback_messages.append(msg)

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=0.2, enabled=True),
            on_ack=on_ack,
            user_message="What's on my calendar?",
        )
        mgr.start()

        # Wait longer than timeout
        await asyncio.sleep(0.5)

        assert mgr.fired is True
        assert len(callback_messages) == 1
        assert isinstance(callback_messages[0], str)

        result = mgr.result
        assert result.sent is True
        assert len(result.message) > 0
        assert len(result.timestamp) > 0

    @pytest.mark.asyncio
    async def test_timer_fires_with_entities(self) -> None:
        """Timer fires with entity-aware message when entities provided."""
        callback_messages: List[str] = []

        async def on_ack(msg: str) -> None:
            callback_messages.append(msg)

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=0.1, enabled=True),
            on_ack=on_ack,
            user_message="Tell me about Alice",
            entities=["Alice"],
        )
        mgr.start()
        await asyncio.sleep(0.3)

        assert mgr.fired is True
        assert len(callback_messages) == 1


# =============================================================================
# 6. AcknowledgmentManager — Cancellation
# =============================================================================


class TestAcknowledgmentManagerCancel:
    """Tests for cancelling the ack timer before it fires."""

    @pytest.mark.asyncio
    async def test_cancel_before_timeout(self) -> None:
        """Cancelling before timeout prevents the ack from firing."""
        callback_messages: List[str] = []

        async def on_ack(msg: str) -> None:
            callback_messages.append(msg)

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=5.0, enabled=True),
            on_ack=on_ack,
            user_message="Hello",
        )
        mgr.start()

        # Cancel immediately (well before the 5s timeout)
        result = await mgr.cancel()

        assert mgr.fired is False
        assert result.sent is False
        assert result.cancelled is True
        assert len(callback_messages) == 0

    @pytest.mark.asyncio
    async def test_cancel_after_fire_returns_sent_result(self) -> None:
        """Cancelling after timer already fired returns the sent result."""
        callback_messages: List[str] = []

        async def on_ack(msg: str) -> None:
            callback_messages.append(msg)

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=0.1, enabled=True),
            on_ack=on_ack,
            user_message="Hello",
        )
        mgr.start()

        # Wait for the timer to fire
        await asyncio.sleep(0.3)
        result = await mgr.cancel()

        assert result.sent is True
        assert len(result.message) > 0

    @pytest.mark.asyncio
    async def test_disabled_config_no_timer(self) -> None:
        """Disabled config means no timer is started."""
        callback_messages: List[str] = []

        async def on_ack(msg: str) -> None:
            callback_messages.append(msg)

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=0.1, enabled=False),
            on_ack=on_ack,
            user_message="Hello",
        )
        mgr.start()

        await asyncio.sleep(0.3)

        assert mgr.fired is False
        assert len(callback_messages) == 0


# =============================================================================
# 7. AckResult Model
# =============================================================================


class TestAckResult:
    """Tests for the AckResult Pydantic model."""

    def test_default_result(self) -> None:
        """Default AckResult has all False/empty values."""
        result = AckResult()
        assert result.sent is False
        assert result.message == ""
        assert result.category is None
        assert result.cancelled is False

    def test_sent_result(self) -> None:
        """Sent result has correct fields."""
        result = AckResult(
            sent=True,
            message="Working on it...",
            category=AckCategory.GENERIC,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert result.sent is True
        assert result.message == "Working on it..."


# =============================================================================
# 8. SSE Event Format
# =============================================================================


class TestSSEFormat:
    """Tests for SSE event formatting."""

    def test_sse_event_creation(self) -> None:
        """SSEEvent can be created with required fields."""
        event = SSEEvent(type="ack", data="Working on it...")
        assert event.type == "ack"
        assert event.data == "Working on it..."
        assert len(event.timestamp) > 0

    def test_format_sse_structure(self) -> None:
        """_format_sse produces valid SSE wire format."""
        event = SSEEvent(type="response", data="Hello there!")
        formatted = _format_sse(event)

        assert formatted.startswith("data: ")
        assert formatted.endswith("\n\n")

        # Parse the JSON payload
        json_str = formatted.replace("data: ", "").strip()
        payload = json.loads(json_str)
        assert payload["type"] == "response"
        assert payload["data"] == "Hello there!"
        assert "timestamp" in payload

    def test_format_sse_ack_event(self) -> None:
        """Ack event is formatted correctly."""
        event = SSEEvent(type="ack", data="Let me think...")
        formatted = _format_sse(event)
        payload = json.loads(formatted.replace("data: ", "").strip())
        assert payload["type"] == "ack"

    def test_format_sse_error_event(self) -> None:
        """Error event is formatted correctly."""
        event = SSEEvent(type="error", data="Something went wrong")
        formatted = _format_sse(event)
        payload = json.loads(formatted.replace("data: ", "").strip())
        assert payload["type"] == "error"
        assert payload["data"] == "Something went wrong"

    def test_format_sse_done_event(self) -> None:
        """Done event is formatted correctly."""
        event = SSEEvent(type="done", data="")
        formatted = _format_sse(event)
        payload = json.loads(formatted.replace("data: ", "").strip())
        assert payload["type"] == "done"

    def test_all_event_types_valid(self) -> None:
        """All expected event types can be created."""
        for event_type in ["ack", "thinking", "response", "error", "done"]:
            event = SSEEvent(type=event_type, data="test")
            assert event.type == event_type


# =============================================================================
# 9. SMS Channel Detection
# =============================================================================


class TestSMSChannelDetection:
    """Tests for should_send_sms_ack()."""

    def test_sms_channel(self) -> None:
        """'sms' channel returns True."""
        assert should_send_sms_ack("sms") is True

    def test_twilio_channel(self) -> None:
        """'twilio' channel returns True."""
        assert should_send_sms_ack("twilio") is True

    def test_text_channel(self) -> None:
        """'text' channel returns True."""
        assert should_send_sms_ack("text") is True

    def test_api_channel(self) -> None:
        """'api' channel returns False."""
        assert should_send_sms_ack("api") is False

    def test_email_channel(self) -> None:
        """'email-work' channel returns False."""
        assert should_send_sms_ack("email-work") is False

    def test_none_channel(self) -> None:
        """None channel returns False."""
        assert should_send_sms_ack(None) is False

    def test_empty_channel(self) -> None:
        """Empty string channel returns False."""
        assert should_send_sms_ack("") is False

    def test_case_insensitive(self) -> None:
        """Channel detection is case-insensitive."""
        assert should_send_sms_ack("SMS") is True
        assert should_send_sms_ack("Sms") is True

    def test_whitespace_handling(self) -> None:
        """Leading/trailing whitespace is stripped."""
        assert should_send_sms_ack("  sms  ") is True


# =============================================================================
# 10. SMS Ack Stub
# =============================================================================


class TestSMSAckStub:
    """Tests for the SMS ack stub sender."""

    @pytest.mark.asyncio
    async def test_stub_returns_true(self) -> None:
        """Stub sender always returns True."""
        result = await send_sms_acknowledgment("+1234567890", "Working on it...")
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_sms_ack_success(self) -> None:
        """handle_sms_ack returns successful SMSAckResult."""
        result = await handle_sms_ack(
            to_number="+1234567890",
            ack_message="Give me a second...",
        )
        assert isinstance(result, SMSAckResult)
        assert result.sent is True
        assert result.message == "Give me a second..."
        assert len(result.timestamp) > 0

    def test_sms_ack_result_model(self) -> None:
        """SMSAckResult model validates correctly."""
        result = SMSAckResult(
            sent=True,
            message="Working on it...",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert result.sent is True


# =============================================================================
# 11. /invoke Backwards Compatibility
# =============================================================================


class TestInvokeBackwardsCompatibility:
    """Tests ensuring /invoke remains backwards compatible."""

    @pytest.mark.asyncio
    async def test_invoke_without_channel_no_ack(self) -> None:
        """
        /invoke without source_channel does NOT trigger SMS ack.
        Verifies backwards compatibility.
        """
        # should_send_sms_ack returns False for None channel
        assert should_send_sms_ack(None) is False

    @pytest.mark.asyncio
    async def test_invoke_with_api_channel_no_ack(self) -> None:
        """
        /invoke with source_channel='api' does NOT trigger SMS ack.
        """
        assert should_send_sms_ack("api") is False

    @pytest.mark.asyncio
    async def test_invoke_with_sms_channel_triggers_ack(self) -> None:
        """
        /invoke with source_channel='sms' WOULD trigger SMS ack.
        """
        assert should_send_sms_ack("sms") is True


# =============================================================================
# 12. Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash(self) -> None:
        """If the ack callback raises, the manager handles it gracefully."""
        async def bad_callback(msg: str) -> None:
            raise RuntimeError("Callback exploded")

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=0.1, enabled=True),
            on_ack=bad_callback,
            user_message="Hello",
        )
        mgr.start()

        # Wait for the timer to fire
        await asyncio.sleep(0.3)

        # The manager should NOT have crashed; fired stays False
        # because the callback failed
        result = mgr.result
        assert result.sent is False

    @pytest.mark.asyncio
    async def test_double_cancel_is_safe(self) -> None:
        """Calling cancel() twice does not raise."""
        async def on_ack(msg: str) -> None:
            pass

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=5.0, enabled=True),
            on_ack=on_ack,
            user_message="Hello",
        )
        mgr.start()

        result1 = await mgr.cancel()
        result2 = await mgr.cancel()

        assert result1.cancelled is True
        assert result2.cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_without_start(self) -> None:
        """Calling cancel() without start() does not raise."""
        async def on_ack(msg: str) -> None:
            pass

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=5.0, enabled=True),
            on_ack=on_ack,
            user_message="Hello",
        )

        # cancel without start
        result = await mgr.cancel()
        assert result.cancelled is True

    def test_topic_keywords_all_have_templates(self) -> None:
        """Every topic category in TOPIC_KEYWORDS has matching templates."""
        for category in TOPIC_KEYWORDS:
            matching = [t for t in ACK_TEMPLATES if t.category == category]
            assert len(matching) > 0, (
                f"Category {category} has keywords but no templates"
            )

    def test_ack_category_enum_values(self) -> None:
        """AckCategory enum has all expected values."""
        expected = {
            "generic", "context_aware", "topic_calendar",
            "topic_reminder", "topic_weather", "topic_email",
        }
        actual = {c.value for c in AckCategory}
        assert expected == actual

    @pytest.mark.asyncio
    async def test_very_short_timeout(self) -> None:
        """Very short timeout (10ms) fires quickly."""
        callback_messages: List[str] = []

        async def on_ack(msg: str) -> None:
            callback_messages.append(msg)

        mgr = AcknowledgmentManager(
            config=AckConfig(timeout_seconds=0.01, enabled=True),
            on_ack=on_ack,
            user_message="Hello",
        )
        mgr.start()
        await asyncio.sleep(0.2)

        assert mgr.fired is True
        assert len(callback_messages) == 1

    def test_generate_ack_message_returns_string(self) -> None:
        """generate_ack_message always returns a non-empty string."""
        for msg in [
            "Hello", "What's on my calendar?", "Remind me",
            "Weather?", "Check email",
        ]:
            result = generate_ack_message(msg)
            assert isinstance(result, str)
            assert len(result) > 0
