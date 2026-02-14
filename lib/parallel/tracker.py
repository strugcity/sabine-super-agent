"""
Session Tracker - Used by parallel sessions to report their status.
====================================================================

Each parallel Claude Code session instantiates a SessionTracker
to write heartbeats, progress updates, and completion markers
to the shared .parallel/ directory.

Example:
    tracker = SessionTracker(session_id="adr-01", workspace="adrs")
    tracker.start("Writing ADR-001: Auth Strategy")
    tracker.heartbeat(progress_pct=50, message="Drafted options section")
    tracker.complete(output_file="docs/architecture/ADR-001-auth-strategy.md")
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.parallel.models import (
    CompletionMarker,
    SessionState,
    SessionStatus,
)

logger = logging.getLogger(__name__)

# Root directory for all parallel session data
PARALLEL_ROOT = ".parallel"


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


class SessionTracker:
    """
    File-based status reporter for a single parallel session.

    Writes to: .parallel/<workspace>/<session_id>/
        status.json   - Current status (updated on every heartbeat)
        log.jsonl      - Append-only log of all status changes
        COMPLETED      - Marker file on success
        FAILED         - Marker file on failure
    """

    def __init__(
        self,
        session_id: str,
        workspace: str,
        project_root: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.workspace = workspace
        root = Path(project_root) if project_root else Path.cwd()
        self.session_dir = root / PARALLEL_ROOT / workspace / session_id
        _ensure_dir(self.session_dir)

        self._status = SessionStatus(
            session_id=session_id,
            workspace=workspace,
        )
        logger.info(
            "SessionTracker initialized: %s/%s at %s",
            workspace, session_id, self.session_dir,
        )

    @property
    def status_file(self) -> Path:
        """Path to status.json."""
        return self.session_dir / "status.json"

    @property
    def log_file(self) -> Path:
        """Path to append-only log."""
        return self.session_dir / "log.jsonl"

    def _write_status(self) -> None:
        """Write current status to status.json."""
        self.status_file.write_text(
            self._status.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _append_log(self, event: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Append a timestamped event to the log file."""
        entry = {
            "timestamp": _now_iso(),
            "event": event,
            "session_id": self.session_id,
            "state": self._status.state.value,
            "progress_pct": self._status.progress_pct,
        }
        if details:
            entry["details"] = details
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _write_marker(self, marker_name: str, marker: CompletionMarker) -> None:
        """Write a completion/failure marker file."""
        marker_path = self.session_dir / marker_name
        marker_path.write_text(
            marker.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def start(self, task_description: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Mark session as started/running."""
        self._status.state = SessionState.RUNNING
        self._status.task_description = task_description
        self._status.started_at = _now_iso()
        self._status.last_heartbeat = _now_iso()
        self._status.progress_pct = 0
        if metadata:
            self._status.metadata = metadata
        self._write_status()
        self._append_log("started", {"task": task_description})
        logger.info("Session started: %s - %s", self.session_id, task_description)

    def heartbeat(
        self,
        progress_pct: Optional[int] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update heartbeat timestamp and optional progress/message."""
        self._status.last_heartbeat = _now_iso()
        if progress_pct is not None:
            self._status.progress_pct = max(0, min(100, progress_pct))
        if message is not None:
            self._status.message = message
        if metadata:
            self._status.metadata.update(metadata)
        self._write_status()
        self._append_log("heartbeat", {"message": message or ""})

    def error(self, error_msg: str) -> None:
        """Record an error without failing the session."""
        self._status.errors.append(f"[{_now_iso()}] {error_msg}")
        self._status.last_heartbeat = _now_iso()
        self._write_status()
        self._append_log("error", {"error": error_msg})
        logger.warning("Session %s error: %s", self.session_id, error_msg)

    def complete(self, output_files: Optional[List[str]] = None, message: Optional[str] = None) -> None:
        """Mark session as successfully completed."""
        self._status.state = SessionState.COMPLETED
        self._status.progress_pct = 100
        self._status.completed_at = _now_iso()
        self._status.last_heartbeat = _now_iso()
        if output_files:
            self._status.output_files = output_files
        if message:
            self._status.message = message
        self._write_status()

        marker = CompletionMarker(
            session_id=self.session_id,
            state=SessionState.COMPLETED,
            timestamp=_now_iso(),
            output_files=self._status.output_files,
        )
        self._write_marker("COMPLETED", marker)
        self._append_log("completed", {"output_files": self._status.output_files})
        logger.info("Session completed: %s", self.session_id)

    def fail(self, error_summary: str, output_files: Optional[List[str]] = None) -> None:
        """Mark session as failed."""
        self._status.state = SessionState.FAILED
        self._status.completed_at = _now_iso()
        self._status.last_heartbeat = _now_iso()
        self._status.message = f"FAILED: {error_summary}"
        self._status.errors.append(f"[{_now_iso()}] FATAL: {error_summary}")
        if output_files:
            self._status.output_files = output_files
        self._write_status()

        marker = CompletionMarker(
            session_id=self.session_id,
            state=SessionState.FAILED,
            timestamp=_now_iso(),
            error_summary=error_summary,
            output_files=output_files or [],
        )
        self._write_marker("FAILED", marker)
        self._append_log("failed", {"error": error_summary})
        logger.error("Session failed: %s - %s", self.session_id, error_summary)

    def get_status(self) -> SessionStatus:
        """Return current in-memory status."""
        return self._status.model_copy()
