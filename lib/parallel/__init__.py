"""
Parallel Session Observability Library
=======================================

Provides file-based monitoring, heartbeat, and status reporting
for parallel Claude Code workstreams.

This is NOT part of the Dream Team task queue or backend services.
This is a local-filesystem-based system for coordinating parallel
Claude Code sessions (e.g., ADR writing, feature branches, etc.).

Usage:
    from lib.parallel import SessionTracker, SessionMonitor

    # In a parallel session:
    tracker = SessionTracker(session_id="adr-01", workspace="adrs")
    tracker.start("Writing ADR-001")
    tracker.heartbeat(progress_pct=25, message="Researching options")
    tracker.complete(output_file="docs/architecture/ADR-001.md")

    # In the main/coordinator session:
    monitor = SessionMonitor(workspace="adrs")
    status = monitor.poll_all()
    monitor.print_dashboard()
"""

from lib.parallel.tracker import SessionTracker
from lib.parallel.monitor import SessionMonitor
from lib.parallel.models import SessionStatus, SessionState

__all__ = [
    "SessionTracker",
    "SessionMonitor",
    "SessionStatus",
    "SessionState",
]
