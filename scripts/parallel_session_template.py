#!/usr/bin/env python3
"""
Parallel Session Runner Template
==================================

Copy and adapt this template for any parallel Claude Code workstream.
It wraps your actual work with observability: heartbeats, progress
tracking, completion markers, and structured logging.

Usage:
    1. Copy this file for your specific task
    2. Implement the `run_session()` function
    3. Launch it as a parallel session

The main/coordinator session can then monitor progress via:
    python scripts/parallel_monitor.py --workspace <workspace> --watch
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from lib.parallel.tracker import SessionTracker


def run_session(tracker: SessionTracker) -> None:
    """
    Replace this with your actual parallel work.

    Use tracker.heartbeat() regularly to report progress.
    Use tracker.error() to record non-fatal errors.
    tracker.complete() or tracker.fail() is called automatically
    by the wrapper below.
    """
    # Example: ADR writing session
    tracker.heartbeat(progress_pct=10, message="Researching topic")
    # ... do research ...

    tracker.heartbeat(progress_pct=30, message="Analyzing options")
    # ... analyze options ...

    tracker.heartbeat(progress_pct=60, message="Drafting document")
    # ... write document ...

    tracker.heartbeat(progress_pct=90, message="Reviewing and finalizing")
    # ... final review ...

    # Return output files when done
    # tracker.complete() is called by the wrapper


def main() -> int:
    """Entry point with observability wrapper."""
    # Configure these for your specific session
    SESSION_ID = "example-01"      # Unique within workspace
    WORKSPACE = "example"          # Logical group
    TASK_DESC = "Example task"     # What this session does
    OUTPUT_FILES: list[str] = []   # Files this session produces

    tracker = SessionTracker(
        session_id=SESSION_ID,
        workspace=WORKSPACE,
        project_root=PROJECT_ROOT,
    )

    try:
        tracker.start(TASK_DESC)
        run_session(tracker)
        tracker.complete(
            output_files=OUTPUT_FILES,
            message="Done",
        )
        return 0
    except KeyboardInterrupt:
        tracker.fail("Interrupted by user")
        return 130
    except Exception as e:
        tracker.fail(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
