"""
Tests for the parallel session observability system.

Tests the tracker, monitor, and models without any database
or network dependencies (pure filesystem operations).

Run: python -m pytest tests/test_parallel_observability.py -v
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from lib.parallel.models import (
    CompletionMarker,
    SessionState,
    SessionStatus,
    WorkspaceSummary,
)
from lib.parallel.tracker import SessionTracker
from lib.parallel.monitor import SessionMonitor, _progress_bar


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project root."""
    return tmp_path


@pytest.fixture
def tracker(tmp_project: Path) -> SessionTracker:
    """Create a tracker with a temp project root."""
    return SessionTracker(
        session_id="test-session-01",
        workspace="test-workspace",
        project_root=str(tmp_project),
    )


@pytest.fixture
def monitor(tmp_project: Path) -> SessionMonitor:
    """Create a monitor with a temp project root."""
    return SessionMonitor(
        workspace="test-workspace",
        project_root=str(tmp_project),
    )


# =============================================================================
# Model Tests
# =============================================================================

class TestSessionStatus:
    """Test SessionStatus model behavior."""

    def test_default_state(self) -> None:
        status = SessionStatus(session_id="s1", workspace="w1")
        assert status.state == SessionState.PENDING
        assert status.progress_pct == 0
        assert not status.is_terminal()

    def test_terminal_states(self) -> None:
        for state in (SessionState.COMPLETED, SessionState.FAILED, SessionState.TIMED_OUT):
            status = SessionStatus(session_id="s1", workspace="w1", state=state)
            assert status.is_terminal()

    def test_non_terminal_states(self) -> None:
        for state in (SessionState.PENDING, SessionState.RUNNING):
            status = SessionStatus(session_id="s1", workspace="w1", state=state)
            assert not status.is_terminal()

    def test_stale_detection_no_heartbeat(self) -> None:
        status = SessionStatus(session_id="s1", workspace="w1")
        assert status.is_stale(timeout_seconds=60)

    def test_stale_detection_recent_heartbeat(self) -> None:
        status = SessionStatus(
            session_id="s1",
            workspace="w1",
            last_heartbeat=datetime.now(timezone.utc).isoformat(),
        )
        assert not status.is_stale(timeout_seconds=60)

    def test_stale_detection_old_heartbeat(self) -> None:
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        status = SessionStatus(
            session_id="s1",
            workspace="w1",
            last_heartbeat=old_time,
        )
        assert status.is_stale(timeout_seconds=60)

    def test_serialization_roundtrip(self) -> None:
        status = SessionStatus(
            session_id="s1",
            workspace="w1",
            state=SessionState.RUNNING,
            progress_pct=42,
            message="doing work",
            errors=["error1"],
            output_files=["file.md"],
            metadata={"key": "val"},
        )
        json_str = status.model_dump_json()
        restored = SessionStatus.model_validate_json(json_str)
        assert restored.session_id == "s1"
        assert restored.progress_pct == 42
        assert restored.errors == ["error1"]
        assert restored.metadata == {"key": "val"}


class TestCompletionMarker:
    """Test CompletionMarker model."""

    def test_success_marker(self) -> None:
        marker = CompletionMarker(
            session_id="s1",
            state=SessionState.COMPLETED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            output_files=["out.md"],
        )
        assert marker.error_summary is None

    def test_failure_marker(self) -> None:
        marker = CompletionMarker(
            session_id="s1",
            state=SessionState.FAILED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error_summary="Something broke",
        )
        assert marker.error_summary == "Something broke"


class TestWorkspaceSummary:
    """Test WorkspaceSummary model."""

    def test_empty_summary(self) -> None:
        summary = WorkspaceSummary(workspace="w1")
        assert summary.total_sessions == 0
        assert summary.completed == 0


# =============================================================================
# Tracker Tests
# =============================================================================

class TestSessionTracker:
    """Test SessionTracker file operations."""

    def test_creates_session_directory(self, tracker: SessionTracker) -> None:
        assert tracker.session_dir.exists()
        assert tracker.session_dir.is_dir()

    def test_start_writes_status(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        assert tracker.status_file.exists()

        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["state"] == "running"
        assert data["task_description"] == "Test task"
        assert data["started_at"] is not None

    def test_start_writes_log(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        assert tracker.log_file.exists()

        lines = tracker.log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "started"

    def test_heartbeat_updates_status(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        tracker.heartbeat(progress_pct=50, message="Halfway done")

        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["progress_pct"] == 50
        assert data["message"] == "Halfway done"

    def test_heartbeat_clamps_progress(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        tracker.heartbeat(progress_pct=150)
        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["progress_pct"] == 100

        tracker.heartbeat(progress_pct=-10)
        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["progress_pct"] == 0

    def test_error_records_without_failing(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        tracker.error("Non-fatal issue")

        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["state"] == "running"
        assert len(data["errors"]) == 1
        assert "Non-fatal issue" in data["errors"][0]

    def test_complete_writes_marker(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        tracker.complete(output_files=["output.md"], message="All done")

        # status.json updated
        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["state"] == "completed"
        assert data["progress_pct"] == 100
        assert data["output_files"] == ["output.md"]

        # COMPLETED marker exists
        marker_file = tracker.session_dir / "COMPLETED"
        assert marker_file.exists()
        marker = json.loads(marker_file.read_text(encoding="utf-8"))
        assert marker["state"] == "completed"
        assert marker["output_files"] == ["output.md"]

    def test_fail_writes_marker(self, tracker: SessionTracker) -> None:
        tracker.start("Test task")
        tracker.fail("Catastrophic error")

        # status.json updated
        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["state"] == "failed"
        assert "Catastrophic error" in data["message"]

        # FAILED marker exists
        marker_file = tracker.session_dir / "FAILED"
        assert marker_file.exists()
        marker = json.loads(marker_file.read_text(encoding="utf-8"))
        assert marker["error_summary"] == "Catastrophic error"

    def test_full_lifecycle(self, tracker: SessionTracker) -> None:
        tracker.start("Full lifecycle test")
        tracker.heartbeat(progress_pct=25, message="Step 1")
        tracker.error("Minor issue")
        tracker.heartbeat(progress_pct=75, message="Step 3")
        tracker.complete(output_files=["result.md"])

        # Verify log has all entries
        lines = tracker.log_file.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(line)["event"] for line in lines]
        assert events == ["started", "heartbeat", "error", "heartbeat", "completed"]

    def test_get_status_returns_copy(self, tracker: SessionTracker) -> None:
        tracker.start("Test")
        status = tracker.get_status()
        assert status.session_id == "test-session-01"
        # Modifying the copy shouldn't affect the tracker
        status.progress_pct = 99
        assert tracker.get_status().progress_pct == 0

    def test_metadata_in_start_and_heartbeat(self, tracker: SessionTracker) -> None:
        tracker.start("Test", metadata={"phase": 1})
        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["metadata"]["phase"] == 1

        tracker.heartbeat(metadata={"phase": 2, "extra": "val"})
        data = json.loads(tracker.status_file.read_text(encoding="utf-8"))
        assert data["metadata"]["phase"] == 2
        assert data["metadata"]["extra"] == "val"


# =============================================================================
# Monitor Tests
# =============================================================================

class TestSessionMonitor:
    """Test SessionMonitor reading and aggregation."""

    def test_empty_workspace(self, monitor: SessionMonitor) -> None:
        sessions = monitor.list_sessions()
        assert sessions == []

    def test_poll_empty(self, monitor: SessionMonitor) -> None:
        summary = monitor.poll_all()
        assert summary.total_sessions == 0

    def test_reads_active_session(
        self, tmp_project: Path, monitor: SessionMonitor
    ) -> None:
        # Create a session via tracker
        tracker = SessionTracker(
            session_id="sess-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Research")
        tracker.heartbeat(progress_pct=50, message="Working")

        # Monitor should see it
        sessions = monitor.list_sessions()
        assert "sess-01" in sessions

        status = monitor.read_session("sess-01")
        assert status is not None
        assert status.state == SessionState.RUNNING
        assert status.progress_pct == 50

    def test_poll_multiple_sessions(self, tmp_project: Path, monitor: SessionMonitor) -> None:
        # Create 3 sessions in different states
        for sid, final_state in [("s1", "complete"), ("s2", "fail"), ("s3", "running")]:
            t = SessionTracker(
                session_id=sid,
                workspace="test-workspace",
                project_root=str(tmp_project),
            )
            t.start(f"Task {sid}")
            if final_state == "complete":
                t.complete(output_files=[f"{sid}.md"])
            elif final_state == "fail":
                t.fail("Oops")

        summary = monitor.poll_all()
        assert summary.total_sessions == 3
        assert summary.completed == 1
        assert summary.failed == 1
        assert summary.running == 1

    def test_completion_marker_detection(
        self, tmp_project: Path, monitor: SessionMonitor
    ) -> None:
        tracker = SessionTracker(
            session_id="done-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Task")
        assert monitor.has_completion_marker("done-01") is None

        tracker.complete()
        assert monitor.has_completion_marker("done-01") == "COMPLETED"

    def test_failure_marker_detection(
        self, tmp_project: Path, monitor: SessionMonitor
    ) -> None:
        tracker = SessionTracker(
            session_id="fail-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Task")
        tracker.fail("Boom")
        assert monitor.has_completion_marker("fail-01") == "FAILED"

    def test_stale_session_detection(
        self, tmp_project: Path
    ) -> None:
        # Create a monitor with very short heartbeat timeout
        monitor = SessionMonitor(
            workspace="test-workspace",
            project_root=str(tmp_project),
            heartbeat_timeout=1,  # 1 second
        )

        tracker = SessionTracker(
            session_id="stale-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Task")

        # Simulate staleness by waiting
        time.sleep(1.5)

        summary = monitor.poll_all()
        stale_session = next(s for s in summary.sessions if s.session_id == "stale-01")
        assert stale_session.state == SessionState.TIMED_OUT

    def test_read_session_log(self, tmp_project: Path, monitor: SessionMonitor) -> None:
        tracker = SessionTracker(
            session_id="log-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Task")
        tracker.heartbeat(progress_pct=50)
        tracker.complete()

        entries = monitor.read_session_log("log-01")
        assert len(entries) == 3
        assert entries[0]["event"] == "started"
        assert entries[1]["event"] == "heartbeat"
        assert entries[2]["event"] == "completed"

    def test_read_session_log_tail(self, tmp_project: Path, monitor: SessionMonitor) -> None:
        tracker = SessionTracker(
            session_id="logtail-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Task")
        for i in range(10):
            tracker.heartbeat(progress_pct=i * 10)
        tracker.complete()

        # Only get last 3
        entries = monitor.read_session_log("logtail-01", tail=3)
        assert len(entries) == 3
        assert entries[-1]["event"] == "completed"

    def test_dashboard_output(self, tmp_project: Path, monitor: SessionMonitor) -> None:
        tracker = SessionTracker(
            session_id="dash-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Dashboard test")
        tracker.heartbeat(progress_pct=75, message="Almost there")

        output = monitor.print_dashboard()
        assert "test-workspace" in output
        assert "dash-01" in output
        assert "75%" in output

    def test_nonexistent_session(self, monitor: SessionMonitor) -> None:
        status = monitor.read_session("does-not-exist")
        assert status is None

    def test_session_timeout_detection(self, tmp_project: Path) -> None:
        monitor = SessionMonitor(
            workspace="test-workspace",
            project_root=str(tmp_project),
            session_timeout=1,  # 1 second total timeout
        )

        tracker = SessionTracker(
            session_id="timeout-01",
            workspace="test-workspace",
            project_root=str(tmp_project),
        )
        tracker.start("Long task")

        time.sleep(1.5)
        # Keep heartbeat fresh so only session timeout triggers
        tracker.heartbeat(progress_pct=10)

        summary = monitor.poll_all()
        sess = next(s for s in summary.sessions if s.session_id == "timeout-01")
        assert sess.state == SessionState.TIMED_OUT
        assert "timed out" in sess.message.lower()


# =============================================================================
# Utility Tests
# =============================================================================

class TestProgressBar:
    """Test the progress bar renderer."""

    def test_zero(self) -> None:
        assert _progress_bar(0) == "[--------------------]"

    def test_fifty(self) -> None:
        assert _progress_bar(50) == "[##########----------]"

    def test_hundred(self) -> None:
        assert _progress_bar(100) == "[####################]"

    def test_custom_width(self) -> None:
        assert _progress_bar(50, width=10) == "[#####-----]"
