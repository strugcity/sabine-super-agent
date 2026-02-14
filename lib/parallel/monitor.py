"""
Session Monitor - Used by main/coordinator session to observe parallel work.
=============================================================================

The coordinator session uses SessionMonitor to:
- Poll all sessions in a workspace for status
- Detect stale/timed-out sessions
- Print a human-readable dashboard
- Wait for all sessions to reach terminal state

Example:
    monitor = SessionMonitor(workspace="adrs")
    summary = monitor.poll_all()
    monitor.print_dashboard()
    results = monitor.wait_for_all(timeout_minutes=60)
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from lib.parallel.models import (
    SessionState,
    SessionStatus,
    WorkspaceSummary,
)
from lib.parallel.tracker import PARALLEL_ROOT

logger = logging.getLogger(__name__)

# Default heartbeat timeout: 5 minutes
DEFAULT_HEARTBEAT_TIMEOUT = 300

# Default overall session timeout: 4 hours
DEFAULT_SESSION_TIMEOUT = 14400


class SessionMonitor:
    """
    File-based monitor that reads status from .parallel/<workspace>/.

    Designed to be called from a main/coordinator Claude Code session
    or from a standalone monitoring script.
    """

    def __init__(
        self,
        workspace: str,
        project_root: Optional[str] = None,
        heartbeat_timeout: int = DEFAULT_HEARTBEAT_TIMEOUT,
        session_timeout: int = DEFAULT_SESSION_TIMEOUT,
    ) -> None:
        self.workspace = workspace
        self.heartbeat_timeout = heartbeat_timeout
        self.session_timeout = session_timeout
        root = Path(project_root) if project_root else Path.cwd()
        self.workspace_dir = root / PARALLEL_ROOT / workspace

    def list_sessions(self) -> List[str]:
        """List all session IDs in this workspace."""
        if not self.workspace_dir.exists():
            return []
        return [
            d.name for d in sorted(self.workspace_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]

    def read_session(self, session_id: str) -> Optional[SessionStatus]:
        """Read a single session's status.json."""
        status_file = self.workspace_dir / session_id / "status.json"
        if not status_file.exists():
            return None
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            return SessionStatus(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to read %s: %s", status_file, e)
            return None

    def has_completion_marker(self, session_id: str) -> Optional[str]:
        """Check if COMPLETED or FAILED marker exists. Returns marker name or None."""
        for marker in ("COMPLETED", "FAILED"):
            if (self.workspace_dir / session_id / marker).exists():
                return marker
        return None

    def _check_timeouts(self, status: SessionStatus) -> SessionStatus:
        """Check if a running session has timed out."""
        if status.state != SessionState.RUNNING:
            return status

        now = datetime.now(timezone.utc)

        # Check overall session timeout
        if status.started_at:
            started = datetime.fromisoformat(status.started_at)
            if (now - started).total_seconds() > self.session_timeout:
                status.state = SessionState.TIMED_OUT
                status.message = (
                    f"Session timed out after {self.session_timeout}s "
                    f"(started at {status.started_at})"
                )
                return status

        # Check heartbeat staleness
        if status.is_stale(self.heartbeat_timeout):
            status.state = SessionState.TIMED_OUT
            status.message = (
                f"No heartbeat for {self.heartbeat_timeout}s "
                f"(last: {status.last_heartbeat})"
            )

        return status

    def poll_all(self) -> WorkspaceSummary:
        """Poll all sessions and return aggregated summary."""
        session_ids = self.list_sessions()
        sessions: List[SessionStatus] = []

        for sid in session_ids:
            status = self.read_session(sid)
            if status is None:
                # Session dir exists but no status.json yet
                status = SessionStatus(
                    session_id=sid,
                    workspace=self.workspace,
                    state=SessionState.PENDING,
                    message="No status.json found",
                )
            else:
                status = self._check_timeouts(status)
            sessions.append(status)

        summary = WorkspaceSummary(
            workspace=self.workspace,
            total_sessions=len(sessions),
            sessions=sessions,
        )

        for s in sessions:
            if s.state == SessionState.PENDING:
                summary.pending += 1
            elif s.state == SessionState.RUNNING:
                if s.is_stale(self.heartbeat_timeout):
                    summary.stale += 1
                summary.running += 1
            elif s.state == SessionState.COMPLETED:
                summary.completed += 1
            elif s.state == SessionState.FAILED:
                summary.failed += 1
            elif s.state == SessionState.TIMED_OUT:
                summary.timed_out += 1

        return summary

    def print_dashboard(self, summary: Optional[WorkspaceSummary] = None) -> str:
        """Return a formatted dashboard string."""
        if summary is None:
            summary = self.poll_all()

        lines: List[str] = []
        lines.append("")
        lines.append(f"  Parallel Session Dashboard: {summary.workspace}")
        lines.append(f"  {'=' * 55}")
        lines.append(
            f"  Total: {summary.total_sessions} | "
            f"Running: {summary.running} | "
            f"Done: {summary.completed} | "
            f"Failed: {summary.failed} | "
            f"Timed Out: {summary.timed_out} | "
            f"Stale: {summary.stale}"
        )
        lines.append(f"  {'-' * 55}")

        for s in summary.sessions:
            icon = {
                SessionState.PENDING: "[.]",
                SessionState.RUNNING: "[~]",
                SessionState.COMPLETED: "[+]",
                SessionState.FAILED: "[X]",
                SessionState.TIMED_OUT: "[!]",
            }.get(s.state, "[?]")

            progress_bar = _progress_bar(s.progress_pct)
            lines.append(
                f"  {icon} {s.session_id:<20} "
                f"{progress_bar} {s.progress_pct:3d}% "
                f"| {s.message[:40] if s.message else s.task_description[:40]}"
            )
            if s.errors:
                lines.append(f"      Last error: {s.errors[-1][:60]}")

        lines.append(f"  {'-' * 55}")
        lines.append(f"  Polled at: {datetime.now(timezone.utc).isoformat()}")
        lines.append("")

        output = "\n".join(lines)
        print(output)
        return output

    def wait_for_all(
        self,
        timeout_minutes: int = 60,
        poll_interval_seconds: int = 30,
        print_updates: bool = True,
    ) -> WorkspaceSummary:
        """
        Block until all sessions reach a terminal state or overall timeout.

        Returns the final WorkspaceSummary.
        """
        deadline = time.time() + (timeout_minutes * 60)

        while time.time() < deadline:
            summary = self.poll_all()

            if print_updates:
                self.print_dashboard(summary)

            all_terminal = all(
                s.is_terminal() for s in summary.sessions
            )
            if all_terminal and summary.total_sessions > 0:
                logger.info(
                    "All %d sessions in '%s' reached terminal state.",
                    summary.total_sessions, self.workspace,
                )
                return summary

            time.sleep(poll_interval_seconds)

        # Timeout reached
        final = self.poll_all()
        for s in final.sessions:
            if not s.is_terminal():
                s.state = SessionState.TIMED_OUT
                s.message = f"Overall wait timeout ({timeout_minutes}m) exceeded"
        logger.warning(
            "Wait timeout (%dm) for workspace '%s'.",
            timeout_minutes, self.workspace,
        )
        return final

    def read_session_log(self, session_id: str, tail: int = 20) -> List[Dict]:
        """Read the last N entries from a session's log.jsonl."""
        log_file = self.workspace_dir / session_id / "log.jsonl"
        if not log_file.exists():
            return []
        try:
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            entries = [json.loads(line) for line in lines if line.strip()]
            return entries[-tail:]
        except Exception as e:
            logger.warning("Failed to read log for %s: %s", session_id, e)
            return []


def _progress_bar(pct: int, width: int = 20) -> str:
    """Render a text progress bar."""
    filled = int(width * pct / 100)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}]"
