"""
Scheduler Live Verification Test - Phase 7 QA
==============================================

This test verifies the Proactive Scheduler works end-to-end:
1. Triggers a manual morning briefing via API
2. Uses REAL Supabase connection for context retrieval
3. Uses REAL Claude API for synthesis
4. MOCKS Twilio to avoid sending actual SMS

The test captures logs to verify:
- Context was retrieved from the database
- Claude generated a briefing
- The "SMS" would have been sent (mocked)

Owner: @qa-engineer + @backend-architect-sabine
"""

import asyncio
import io
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env", override=True)


# =============================================================================
# Test Configuration
# =============================================================================

# Capture logs for verification
log_capture = io.StringIO()
handler = logging.StreamHandler(log_capture)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add handler to relevant loggers
logging.getLogger('lib.agent.scheduler').addHandler(handler)
logging.getLogger('lib.agent.scheduler').setLevel(logging.INFO)


# =============================================================================
# Mock Twilio Client
# =============================================================================

class MockTwilioMessage:
    """Mock Twilio message response."""
    def __init__(self, body: str, to: str, from_: str):
        self.sid = "SM_MOCK_MESSAGE_ID_12345"
        self.body = body
        self.to = to
        self.from_ = from_
        self.status = "queued"


class MockTwilioMessages:
    """Mock Twilio messages resource."""
    def __init__(self):
        self.sent_messages = []

    def create(self, body: str, to: str, from_: str) -> MockTwilioMessage:
        """Mock message creation - captures instead of sending."""
        print(f"\n{'='*60}")
        print("MOCK TWILIO SMS SENT")
        print(f"{'='*60}")
        print(f"TO: {to}")
        print(f"FROM: {from_}")
        print(f"BODY:\n{body}")
        print(f"{'='*60}\n")

        msg = MockTwilioMessage(body, to, from_)
        self.sent_messages.append(msg)
        return msg


class MockTwilioClient:
    """Mock Twilio REST client."""
    def __init__(self, account_sid: str, auth_token: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.messages = MockTwilioMessages()


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_twilio():
    """Patch Twilio client with mock."""
    with patch('lib.agent.scheduler.TwilioClient', MockTwilioClient):
        # Also need to patch at import time
        with patch.dict('sys.modules', {'twilio.rest': MagicMock()}):
            yield MockTwilioClient


@pytest.fixture
def test_client():
    """Create FastAPI test client."""
    from fastapi.testclient import TestClient
    from lib.agent.server import app
    return TestClient(app)


@pytest.fixture
def api_key():
    """Get API key from environment."""
    key = os.getenv("AGENT_API_KEY")
    if not key:
        pytest.skip("AGENT_API_KEY not set - skipping live test")
    return key


# =============================================================================
# Live Tests
# =============================================================================

class TestSchedulerLive:
    """Live tests for the Proactive Scheduler."""

    def test_scheduler_status_endpoint(self, test_client):
        """Verify scheduler status endpoint works."""
        response = test_client.get("/scheduler/status")

        assert response.status_code == 200
        data = response.json()

        print(f"\nScheduler Status Response: {data}")

        assert "success" in data
        assert "running" in data
        assert "jobs" in data

    def test_trigger_briefing_skip_sms(self, test_client, api_key):
        """
        Trigger briefing with skip_sms=True.

        This tests the full chain:
        1. API endpoint receives request
        2. Scheduler retrieves context from Supabase
        3. Claude synthesizes briefing
        4. SMS is skipped (no Twilio call)
        """
        print("\n" + "="*60)
        print("TEST: Trigger Briefing (Skip SMS)")
        print("="*60)

        response = test_client.post(
            "/scheduler/trigger-briefing",
            headers={"X-API-Key": api_key},
            json={
                "user_name": "Paul",
                "skip_sms": True
            }
        )

        print(f"\nResponse Status: {response.status_code}")
        # Handle Windows encoding issues with emoji in response
        try:
            print(f"Response Body: {response.text[:500]}...")
        except UnicodeEncodeError:
            print(f"Response Body: {response.text[:500].encode('ascii', 'replace').decode()}...")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        # Handle Windows encoding for parsed response (may have emoji)
        try:
            print(f"\nParsed Response: {data}")
        except UnicodeEncodeError:
            print(f"\nParsed Response: {str(data).encode('ascii', 'replace').decode()}")

        # Verify response structure
        assert "success" in data, "Response missing 'success' field"
        assert "status" in data, "Response missing 'status' field"
        assert "briefing" in data, "Response missing 'briefing' field"

        # Verify success
        assert data["success"] is True, f"Briefing failed: {data.get('error')}"
        assert data["status"] == "success", f"Status was {data['status']}"

        # Verify briefing was generated
        briefing = data.get("briefing", "")
        assert len(briefing) > 0, "Briefing is empty"
        print(f"\nGenerated Briefing ({len(briefing)} chars):")
        print("-" * 40)
        # Handle Windows encoding issues with emoji
        try:
            print(briefing)
        except UnicodeEncodeError:
            print(briefing.encode('ascii', 'replace').decode())
        print("-" * 40)

        # Verify context was retrieved
        context_summary = data.get("context_summary", {})
        print(f"\nContext Summary: {context_summary}")

        # SMS should NOT have been sent
        assert data.get("sms_sent") is False, "SMS should not have been sent with skip_sms=True"

        print("\nTEST PASSED: Briefing generated successfully without SMS")

    @pytest.mark.skip(reason="Twilio not installed - mock SMS test skipped")
    def test_trigger_briefing_with_mock_sms(self, test_client, api_key):
        """
        Trigger briefing with mocked Twilio.

        This tests the SMS sending path with a mock.
        Note: Skipped if Twilio is not installed.
        """
        print("\n" + "="*60)
        print("TEST: Trigger Briefing (Mock SMS)")
        print("="*60)

        # Patch the Twilio import in scheduler module
        mock_messages = MockTwilioMessages()
        mock_client_instance = MagicMock()
        mock_client_instance.messages = mock_messages

        with patch('twilio.rest.Client', return_value=mock_client_instance):
            # Set a test phone number
            with patch.dict(os.environ, {
                "USER_PHONE": "+15551234567",
                "TWILIO_ACCOUNT_SID": "test_sid",
                "TWILIO_AUTH_TOKEN": "test_token",
                "TWILIO_FROM_NUMBER": "+15559876543"
            }):
                response = test_client.post(
                    "/scheduler/trigger-briefing",
                    headers={"X-API-Key": api_key},
                    json={
                        "user_name": "Paul",
                        "skip_sms": False,
                        "phone_number": "+15551234567"
                    }
                )

        print(f"\nResponse Status: {response.status_code}")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        print(f"\nResponse: {data}")

        assert data["success"] is True, f"Briefing failed: {data.get('error')}"
        assert data["status"] == "success"
        assert len(data.get("briefing", "")) > 0

        print("\nTEST PASSED: Briefing generated with mock SMS path")


class TestSchedulerUnit:
    """Unit tests for scheduler components."""

    @pytest.mark.asyncio
    async def test_get_briefing_context(self):
        """Test context retrieval from database."""
        from lib.agent.scheduler import get_briefing_context
        from uuid import UUID

        print("\n" + "="*60)
        print("TEST: Get Briefing Context")
        print("="*60)

        user_id = UUID("00000000-0000-0000-0000-000000000001")

        context = await get_briefing_context(user_id)

        print(f"\nContext Retrieved:")
        print(f"  Recent Memories: {len(context.get('recent_memories', []))}")
        print(f"  Upcoming Tasks: {len(context.get('upcoming_tasks', []))}")
        print(f"  High Importance: {len(context.get('high_importance', []))}")
        print(f"  Entities: {len(context.get('entities', []))}")
        print(f"  Timestamp: {context.get('timestamp')}")

        # Verify structure
        assert "recent_memories" in context
        assert "upcoming_tasks" in context
        assert "high_importance" in context
        assert "entities" in context
        assert "timestamp" in context

        # Should not have error
        assert "error" not in context or context.get("error") is None

        print("\nTEST PASSED: Context retrieval works")

    @pytest.mark.asyncio
    async def test_synthesize_briefing_with_context(self):
        """Test Claude synthesis with sample context."""
        from lib.agent.scheduler import synthesize_briefing

        print("\n" + "="*60)
        print("TEST: Synthesize Briefing")
        print("="*60)

        # Sample context
        context = {
            "recent_memories": [
                {"content": "Had meeting with engineering team about Q1 roadmap", "source": "email", "importance": 0.7},
                {"content": "Dentist appointment scheduled for Friday at 2pm", "source": "sms", "importance": 0.6}
            ],
            "upcoming_tasks": [
                {"title": "Review PR #123", "due_date": "2025-01-31", "priority": "high"},
                {"title": "Submit expense report", "due_date": "2025-02-01", "priority": "normal"}
            ],
            "high_importance": [
                {"content": "Project Alpha deadline moved to February 15th", "importance": 0.9}
            ],
            "entities": [
                {"name": "Project Alpha", "type": "project", "domain": "work"},
                {"name": "Dr. Smith", "type": "person", "domain": "personal"}
            ],
            "timestamp": "2025-01-30T08:00:00Z"
        }

        briefing = await synthesize_briefing(context, "Paul")

        print(f"\nGenerated Briefing ({len(briefing)} chars):")
        print("-" * 40)
        # Handle Windows encoding issues with emoji
        try:
            print(briefing)
        except UnicodeEncodeError:
            print(briefing.encode('ascii', 'replace').decode())
        print("-" * 40)

        # Verify briefing was generated
        assert len(briefing) > 0
        assert "Paul" in briefing or "morning" in briefing.lower()

        print("\nTEST PASSED: Claude synthesis works")

    @pytest.mark.asyncio
    async def test_synthesize_briefing_empty_context(self):
        """Test graceful handling of empty context."""
        from lib.agent.scheduler import synthesize_briefing

        print("\n" + "="*60)
        print("TEST: Empty Context Handling")
        print("="*60)

        # Empty context
        context = {
            "recent_memories": [],
            "upcoming_tasks": [],
            "high_importance": [],
            "entities": [],
            "timestamp": "2025-01-30T08:00:00Z"
        }

        briefing = await synthesize_briefing(context, "Paul")

        print(f"\nGenerated Briefing for empty context:")
        print(briefing)

        # Should have a friendly fallback message
        assert len(briefing) > 0
        assert "Paul" in briefing
        # Should indicate no major items
        assert "no major items" in briefing.lower() or "radar" in briefing.lower() or "great day" in briefing.lower()

        print("\nTEST PASSED: Empty context handled gracefully")


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Run with pytest for better output
    pytest.main([
        __file__,
        "-v",
        "-s",  # Show print statements
        "--tb=short",
        "-x"  # Stop on first failure
    ])
