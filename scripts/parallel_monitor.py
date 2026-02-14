#!/usr/bin/env python3
"""
Parallel Session Monitor CLI
==============================

Standalone script to monitor parallel Claude Code sessions.
Run from the project root to see a live dashboard.

Usage:
    # One-shot dashboard
    python scripts/parallel_monitor.py --workspace adrs

    # Live polling every 30s
    python scripts/parallel_monitor.py --workspace adrs --watch

    # Check a specific session's log
    python scripts/parallel_monitor.py --workspace adrs --session adr-01 --log

    # Custom timeouts
    python scripts/parallel_monitor.py --workspace adrs --watch \
        --heartbeat-timeout 600 --session-timeout 7200

    # Wait for all sessions to finish (blocks)
    python scripts/parallel_monitor.py --workspace adrs --wait --timeout 120
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from lib.parallel.monitor import SessionMonitor


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Show the dashboard once."""
    monitor = SessionMonitor(
        workspace=args.workspace,
        project_root=PROJECT_ROOT,
        heartbeat_timeout=args.heartbeat_timeout,
        session_timeout=args.session_timeout,
    )
    summary = monitor.poll_all()
    if summary.total_sessions == 0:
        print(f"\n  No sessions found in workspace '{args.workspace}'.")
        print(f"  Looking in: {monitor.workspace_dir}")
        print(f"  Tip: Sessions write to .parallel/{args.workspace}/<session-id>/\n")
        return 0

    monitor.print_dashboard(summary)
    return 1 if summary.failed > 0 or summary.timed_out > 0 else 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Live-poll the dashboard."""
    monitor = SessionMonitor(
        workspace=args.workspace,
        project_root=PROJECT_ROOT,
        heartbeat_timeout=args.heartbeat_timeout,
        session_timeout=args.session_timeout,
    )
    poll_interval = args.poll_interval
    print(f"Watching workspace '{args.workspace}' (poll every {poll_interval}s, Ctrl+C to stop)")

    try:
        while True:
            # Clear screen (cross-platform)
            print("\033[2J\033[H", end="")
            summary = monitor.poll_all()
            if summary.total_sessions == 0:
                print(f"\n  Waiting for sessions in workspace '{args.workspace}'...")
                print(f"  Looking in: {monitor.workspace_dir}\n")
            else:
                monitor.print_dashboard(summary)

            # Check if all terminal
            if summary.total_sessions > 0:
                all_done = all(s.is_terminal() for s in summary.sessions)
                if all_done:
                    print("  All sessions reached terminal state.")
                    return 1 if summary.failed > 0 or summary.timed_out > 0 else 0

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        return 0


def cmd_wait(args: argparse.Namespace) -> int:
    """Block until all sessions complete."""
    monitor = SessionMonitor(
        workspace=args.workspace,
        project_root=PROJECT_ROOT,
        heartbeat_timeout=args.heartbeat_timeout,
        session_timeout=args.session_timeout,
    )
    summary = monitor.wait_for_all(
        timeout_minutes=args.timeout,
        poll_interval_seconds=args.poll_interval,
        print_updates=True,
    )
    if summary.failed > 0 or summary.timed_out > 0:
        print(f"\n  WARNING: {summary.failed} failed, {summary.timed_out} timed out.")
        return 1
    print(f"\n  All {summary.total_sessions} sessions completed successfully.")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    """Show a session's log."""
    monitor = SessionMonitor(
        workspace=args.workspace,
        project_root=PROJECT_ROOT,
    )
    if not args.session:
        print("Error: --session is required with --log")
        return 1

    entries = monitor.read_session_log(args.session, tail=args.tail)
    if not entries:
        print(f"No log entries for session '{args.session}'.")
        return 0

    print(f"\nLog for {args.workspace}/{args.session} (last {len(entries)} entries):")
    print("-" * 70)
    for entry in entries:
        ts = entry.get("timestamp", "?")[:19]
        event = entry.get("event", "?")
        state = entry.get("state", "?")
        pct = entry.get("progress_pct", 0)
        details = entry.get("details", {})
        detail_str = ""
        if details:
            detail_str = " | " + json.dumps(details)[:60]
        print(f"  [{ts}] {event:<12} state={state:<10} pct={pct:3d}%{detail_str}")
    print()
    return 0


def cmd_status_json(args: argparse.Namespace) -> int:
    """Output machine-readable JSON status."""
    monitor = SessionMonitor(
        workspace=args.workspace,
        project_root=PROJECT_ROOT,
        heartbeat_timeout=args.heartbeat_timeout,
        session_timeout=args.session_timeout,
    )
    summary = monitor.poll_all()
    print(summary.model_dump_json(indent=2))
    return 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor parallel Claude Code sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--workspace", "-w",
        required=True,
        help="Workspace name (e.g., 'adrs', 'features')",
    )
    parser.add_argument(
        "--session", "-s",
        help="Specific session ID (used with --log)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Live-poll the dashboard",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Block until all sessions complete",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Show a session's log entries",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output machine-readable JSON",
    )
    parser.add_argument(
        "--tail", "-n",
        type=int,
        default=20,
        help="Number of log entries to show (default: 20)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds between polls (default: 30)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Wait timeout in minutes (default: 60)",
    )
    parser.add_argument(
        "--heartbeat-timeout",
        type=int,
        default=300,
        help="Heartbeat staleness threshold in seconds (default: 300)",
    )
    parser.add_argument(
        "--session-timeout",
        type=int,
        default=14400,
        help="Overall session timeout in seconds (default: 14400 = 4h)",
    )

    args = parser.parse_args()

    if args.log:
        return cmd_log(args)
    elif args.output_json:
        return cmd_status_json(args)
    elif args.wait:
        return cmd_wait(args)
    elif args.watch:
        return cmd_watch(args)
    else:
        return cmd_dashboard(args)


if __name__ == "__main__":
    sys.exit(main())
