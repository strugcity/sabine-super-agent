#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strug City System Integration Test - "The Trinity Verification"
Tests: Supabase (Data) + Slack (Communication) + Dashboard (Visual Feedback)

This script creates a mock project with interconnected tasks to verify
end-to-end synchronization between all system components.
"""

import asyncio
import io
import os
import sys
import time
import uuid
from datetime import datetime
from dotenv import load_dotenv

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from supabase import create_client
import httpx

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
API_URL = os.getenv("RAILWAY_PUBLIC_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")

# Initialize clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

PROJECT_NAME = "Connectivity Stress Test v1.0"
SESSION_ID = str(uuid.uuid4())


def log(emoji: str, message: str):
    """Pretty print with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {emoji} {message}")


async def emit_agent_event(
    event_type: str,
    content: str,
    role: str = None,
    task_id: str = None,
    metadata: dict = None
):
    """Insert an event into agent_events table"""
    event = {
        "event_type": event_type,
        "content": content,
        "role": role,
        "task_id": task_id,
    }

    # Try with metadata first, fallback without if column doesn't exist
    try:
        event["metadata"] = metadata or {}
        result = supabase.table("agent_events").insert(event).execute()
    except Exception as e:
        if "metadata" in str(e):
            # Remove metadata and retry - column doesn't exist
            del event["metadata"]
            log("⚠️", "metadata column not found, inserting without it")
            result = supabase.table("agent_events").insert(event).execute()
        else:
            raise

    log("📡", f"Event emitted: {event_type} - {content[:50]}...")
    return result.data[0] if result.data else None


async def create_task(
    role: str,
    title: str,
    description: str,
    status: str = "queued",
    priority: int = 5,
    depends_on: list = None,
    metadata: dict = None
) -> dict:
    """Create a task in task_queue"""
    task = {
        "id": str(uuid.uuid4()),
        "role": role,
        "status": status,
        "priority": priority,
        "payload": {
            "title": title,
            "description": description,
            "project": PROJECT_NAME,
        },
        "depends_on": depends_on or [],
        "session_id": SESSION_ID,
        "created_by": "trinity_test",
    }

    if metadata:
        task["payload"]["metadata"] = metadata

    result = supabase.table("task_queue").insert(task).execute()
    log("📋", f"Task created: {title} ({status})")
    return result.data[0] if result.data else task


async def send_slack_update(message: str, channel: str = "#dream-team-ops"):
    """Send update via the API's Slack integration"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {"X-API-Key": API_KEY} if API_KEY else {}

            # Try using the invoke endpoint with slack_ops skill
            response = await client.post(
                f"{API_URL}/invoke",
                json={
                    "message": f"[SLACK UPDATE] {message}",
                    "role": "SABINE_ARCHITECT",
                    "session_id": SESSION_ID,
                },
                headers=headers,
                timeout=30.0
            )

            if response.status_code == 200:
                log("💬", f"Slack update sent: {message[:50]}...")
                return True
            else:
                log("⚠️", f"Slack API returned {response.status_code}")
                return False
    except Exception as e:
        log("❌", f"Slack update failed: {e}")
        return False


async def task_1_create_project():
    """
    Task 1: Simulation Project Creation
    Create 3 interconnected tasks in task_queue
    """
    log("🚀", "=" * 60)
    log("🚀", "TASK 1: Simulation Project Creation")
    log("🚀", f"Project: {PROJECT_NAME}")
    log("🚀", "=" * 60)

    # Emit project start event
    await emit_agent_event(
        "system_startup",
        f"🏗️ Initializing project: {PROJECT_NAME}",
        role="SABINE_ARCHITECT",  # System events use architect role
        metadata={"project": PROJECT_NAME, "session_id": SESSION_ID}
    )

    # Task A (Architect) - Completed
    task_a = await create_task(
        role="SABINE_ARCHITECT",
        title="Analyze system health and draft test report",
        description="Review all system components and create a comprehensive health report for the integration test.",
        status="completed",  # Set as completed immediately
        priority=9,
        metadata={"report_type": "health_check", "completed_at": datetime.now().isoformat()}
    )

    await emit_agent_event(
        "task_completed",
        "✅ System health analysis complete. All components operational.",
        role="SABINE_ARCHITECT",
        task_id=task_a["id"],
        metadata={"result": "healthy", "components_checked": ["supabase", "slack", "api"]}
    )

    # Task B (Backend) - Queued (will be dispatched later)
    task_b = await create_task(
        role="backend-architect-sabine",
        title="Simulate long-running data process",
        description="Execute a 10-second data processing simulation with progress events.",
        status="queued",
        priority=7,
        depends_on=[task_a["id"]],
        metadata={"duration_seconds": 10, "emit_thoughts": True}
    )

    # Task C (QA) - Queued but requires approval before execution
    # Note: DB constraint only allows queued/in_progress/completed/failed
    # The approval_required flag signals this needs human review
    task_c = await create_task(
        role="qa-security-sabine",
        title="Validate integration test results [NEEDS APPROVAL]",
        description="Review all test outputs and verify system integrity.",
        status="queued",
        priority=5,
        depends_on=[task_b["id"]],
        metadata={
            "approval_required": True,
            "plan": {
                "steps": [
                    "1. Verify all agent_events were recorded",
                    "2. Confirm Slack messages were delivered",
                    "3. Check dashboard real-time updates",
                    "4. Validate task status transitions"
                ],
                "estimated_time": "5 minutes",
                "requires_human_review": True
            }
        }
    )

    log("✅", f"Created 3 tasks: A={task_a['id'][:8]}, B={task_b['id'][:8]}, C={task_c['id'][:8]}")

    return task_a, task_b, task_c


async def task_2_handshake_verification(task_b: dict):
    """
    Task 2: The Handshake Verification
    Execute dispatcher for Task B with Slack + Events
    """
    log("🤝", "=" * 60)
    log("🤝", "TASK 2: The Handshake Verification")
    log("🤝", "=" * 60)

    task_id = task_b["id"]

    # Update task to in_progress
    supabase.table("task_queue").update({
        "status": "in_progress",
        "updated_at": datetime.now().isoformat()
    }).eq("id", task_id).execute()

    log("▶️", f"Task B started: {task_id[:8]}")

    # Emit start event
    await emit_agent_event(
        "task_started",
        f"🚀 Starting long-running data process simulation",
        role="backend-architect-sabine",
        task_id=task_id,
        metadata={"step": 0, "total_steps": 3}
    )

    # Send Slack thread start
    await send_slack_update(
        f"🧵 *New Thread: {PROJECT_NAME}*\n"
        f"Task B starting: Simulating data process\n"
        f"Session: `{SESSION_ID[:8]}...`"
    )

    # Thought 1: Initializing
    await asyncio.sleep(2)
    await emit_agent_event(
        "agent_thought",
        "🔄 Initializing... Setting up data processing pipeline and allocating resources.",
        role="backend-architect-sabine",
        task_id=task_id,
        metadata={"thought_index": 1, "phase": "initialization"}
    )
    await send_slack_update("💭 Thought 1: Initializing data pipeline...")

    # Thought 2: Processing
    await asyncio.sleep(4)
    await emit_agent_event(
        "agent_thought",
        "⚙️ Processing data blocks... Transforming 1,024 records across 3 shards.",
        role="backend-architect-sabine",
        task_id=task_id,
        metadata={"thought_index": 2, "phase": "processing", "records": 1024, "shards": 3}
    )
    await send_slack_update("💭 Thought 2: Processing data blocks (1,024 records)...")

    # Thought 3: Finalizing
    await asyncio.sleep(4)
    await emit_agent_event(
        "agent_thought",
        "✨ Finalizing... Committing results and cleaning up resources.",
        role="backend-architect-sabine",
        task_id=task_id,
        metadata={"thought_index": 3, "phase": "finalization"}
    )
    await send_slack_update("💭 Thought 3: Finalizing and committing results...")

    # Complete the task
    supabase.table("task_queue").update({
        "status": "completed",
        "result": {
            "records_processed": 1024,
            "duration_seconds": 10,
            "success": True
        },
        "updated_at": datetime.now().isoformat()
    }).eq("id", task_id).execute()

    await emit_agent_event(
        "task_completed",
        "✅ Data process simulation complete! All 1,024 records processed successfully.",
        role="backend-architect-sabine",
        task_id=task_id,
        metadata={"result": "success", "duration": 10}
    )

    # Emit handshake event
    await emit_agent_event(
        "handshake",
        "🤝 Agent Handshake: backend-architect-sabine → qa-security-sabine. Task C is now unblocked.",
        role="backend-architect-sabine",
        task_id=task_id,
        metadata={"from_role": "backend-architect-sabine", "to_role": "qa-security-sabine"}
    )

    await send_slack_update(
        "🤝 *Handshake Complete!*\n"
        "Task B finished → Task C (QA Validation) is now ready for approval."
    )

    log("✅", "Task B completed with all thoughts emitted")


async def task_3_god_view_pulse():
    """
    Task 3: The God View "Pulse" Test
    Instructions for monitoring the dashboard
    """
    log("👁️", "=" * 60)
    log("👁️", "TASK 3: The God View 'Pulse' Test")
    log("👁️", "=" * 60)

    log("📺", "")
    log("📺", "🎯 VERIFICATION CHECKLIST:")
    log("📺", "")
    log("📺", "1. Open the dashboard at: http://localhost:3000")
    log("📺", "")
    log("📺", "2. CHECK LiveLog (Event Stream tab):")
    log("📺", "   □ Events appear in real-time WITHOUT refresh")
    log("📺", "   □ Role badges show correct colors")
    log("📺", "   □ 'agent_thought' events visible with 💭 icon")
    log("📺", "   □ 'handshake' event shows 🤝 icon")
    log("📺", "")
    log("📺", "3. CHECK TaskBoard (Task Board tab):")
    log("📺", "   □ Task A in GREEN (Completed) column")
    log("📺", "   □ Task B in GREEN (Completed) column")
    log("📺", "   □ Task C in GRAY (Queued) column with '[NEEDS APPROVAL]' in title")
    log("📺", "")
    log("📺", "4. CHECK OrchestrationStatus (Overview tab):")
    log("📺", "   □ Total Tasks: 3")
    log("📺", "   □ Completed: 2")
    log("📺", "   □ Queued: 1 (Task C waiting for approval)")
    log("📺", "")

    await emit_agent_event(
        "info",
        "👁️ God View Pulse Test: Dashboard should now display all events in real-time.",
        role="SABINE_ARCHITECT",
        metadata={"test_phase": "god_view_verification"}
    )


async def task_4_human_in_loop(task_c: dict):
    """
    Task 4: The Human-in-the-Loop Test
    Post approval request to Slack
    """
    log("🧑‍💻", "=" * 60)
    log("🧑‍💻", "TASK 4: The Human-in-the-Loop Test")
    log("🧑‍💻", "=" * 60)

    task_id = task_c["id"]

    # Emit approval request event
    await emit_agent_event(
        "info",
        f"🚨 APPROVAL REQUIRED: Task C (QA Validation) needs human review before proceeding.",
        role="qa-security-sabine",
        task_id=task_id,
        metadata={
            "approval_type": "human_in_loop",
            "task_title": "Validate integration test results",
            "options": ["Approve", "Reject", "Request Changes"]
        }
    )

    # Send Slack approval request
    await send_slack_update(
        "🚨 *Task C requires manual approval!*\n\n"
        f"*Task:* Validate integration test results\n"
        f"*Role:* qa-security-sabine\n"
        f"*ID:* `{task_id[:8]}...`\n\n"
        "📋 *Plan to execute:*\n"
        "1. Verify all agent_events were recorded\n"
        "2. Confirm Slack messages were delivered\n"
        "3. Check dashboard real-time updates\n"
        "4. Validate task status transitions\n\n"
        "👉 Check the God View Dashboard or reply 'Approve' to proceed."
    )

    log("✅", "Approval request sent to Slack")
    log("📱", "")
    log("📱", "🎯 HUMAN ACTION REQUIRED:")
    log("📱", "")
    log("📱", "   Option A: Click 'Approve' on Task C in the Dashboard TaskBoard")
    log("📱", "   Option B: Reply 'Approve' in the Slack #dream-team-ops channel")
    log("📱", "")


async def run_trinity_test():
    """Main test runner"""
    print("\n" + "=" * 70)
    print("  🏙️  STRUG CITY SYSTEM INTEGRATION TEST - THE TRINITY VERIFICATION")
    print("=" * 70)
    print(f"  Supabase: {SUPABASE_URL[:40]}...")
    print(f"  API URL:  {API_URL}")
    print(f"  Session:  {SESSION_ID}")
    print("=" * 70 + "\n")

    try:
        # Task 1: Create project and tasks
        task_a, task_b, task_c = await task_1_create_project()
        await asyncio.sleep(1)

        # Task 2: Execute Task B with handshake
        await task_2_handshake_verification(task_b)
        await asyncio.sleep(1)

        # Task 3: Dashboard verification instructions
        await task_3_god_view_pulse()
        await asyncio.sleep(1)

        # Task 4: Human-in-the-loop test
        await task_4_human_in_loop(task_c)

        print("\n" + "=" * 70)
        print("  ✅ TRINITY TEST COMPLETE")
        print("=" * 70)
        print("\n  📊 Summary:")
        print(f"     • Tasks created: 3")
        print(f"     • Events emitted: 8+")
        print(f"     • Slack updates: 6")
        print(f"     • Awaiting approval: Task C")
        print("\n  🎯 Next Steps:")
        print("     1. Verify dashboard at http://localhost:3000")
        print("     2. Check Slack #dream-team-ops for updates")
        print("     3. Approve Task C to complete the test")
        print("=" * 70 + "\n")

    except Exception as e:
        log("❌", f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(run_trinity_test())
