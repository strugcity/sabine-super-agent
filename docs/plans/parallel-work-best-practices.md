# Parallel Claude Code Sessions - Best Practices

> **Status**: Active
> **Owner**: All developers
> **Applies to**: Any multi-session Claude Code workflow (ADRs, feature branches, batch tasks)

## Problem

When launching multiple Claude Code sessions in parallel (e.g., 4 ADR writers, 3 feature branches), we had **zero visibility** into progress. Sessions could silently fail, hang, or produce partial output with no way for the coordinator to know.

## Solution: File-Based Observability

We use a lightweight file-based system in `.parallel/` that requires **no database, no network, no extra services**. Just filesystem reads and writes.

## Architecture

```
.parallel/
  <workspace>/              # Logical group (e.g., "adrs", "features")
    <session-id>/           # One directory per parallel session
      status.json           # Current status (overwritten on each heartbeat)
      log.jsonl             # Append-only event log
      COMPLETED             # Marker file (written on success)
      FAILED                # Marker file (written on failure)
```

### Status File Schema

```json
{
  "session_id": "adr-01",
  "workspace": "adrs",
  "state": "running",
  "task_description": "Writing ADR-001: Auth Strategy",
  "progress_pct": 65,
  "message": "Drafting decision section",
  "errors": [],
  "started_at": "2026-02-13T10:00:00+00:00",
  "last_heartbeat": "2026-02-13T10:15:00+00:00",
  "completed_at": null,
  "output_files": [],
  "metadata": {}
}
```

## Rules for Parallel Sessions

### MUST (Non-Negotiable)

1. **Every parallel session MUST use `SessionTracker`** to report status
2. **Heartbeats MUST be sent at least every 5 minutes** (default timeout threshold)
3. **Sessions MUST call `.complete()` or `.fail()`** before exiting
4. **The coordinator MUST use `SessionMonitor`** to watch progress
5. **`.parallel/` MUST be in `.gitignore`** (it's transient local state)

### SHOULD (Strongly Recommended)

1. Sessions SHOULD report progress percentage for long-running work
2. Sessions SHOULD include meaningful messages with each heartbeat
3. Sessions SHOULD record non-fatal errors via `.error()` (don't just log them)
4. The coordinator SHOULD set a session timeout (default: 4 hours)
5. The coordinator SHOULD set a heartbeat timeout (default: 5 minutes)

### MUST NOT

1. Sessions MUST NOT share the same `session_id` within a workspace
2. Sessions MUST NOT write to another session's directory
3. The coordinator MUST NOT modify session files (read-only monitoring)

## Usage Patterns

### Pattern 1: ADR Writing Sessions

```python
# In each ADR session:
from lib.parallel import SessionTracker

tracker = SessionTracker(session_id="adr-01", workspace="adrs")
tracker.start("ADR-001: Authentication Strategy")

# Phase 1: Research
tracker.heartbeat(progress_pct=20, message="Researching auth patterns")

# Phase 2: Draft
tracker.heartbeat(progress_pct=50, message="Drafting options analysis")

# Phase 3: Finalize
tracker.heartbeat(progress_pct=80, message="Writing decision rationale")

tracker.complete(
    output_files=["docs/architecture/ADR-001-auth-strategy.md"],
    message="ADR-001 complete",
)
```

```bash
# Coordinator monitors:
python scripts/parallel_monitor.py --workspace adrs --watch
```

### Pattern 2: Feature Branch Sessions

```python
tracker = SessionTracker(session_id="feat-dark-mode", workspace="features")
tracker.start("Implement dark mode toggle", metadata={"branch": "feat/dark-mode"})

tracker.heartbeat(progress_pct=30, message="Added theme context provider")
tracker.heartbeat(progress_pct=60, message="Updated 12 components")
tracker.heartbeat(progress_pct=90, message="Running tests")

tracker.complete(output_files=["src/contexts/ThemeContext.tsx"])
```

### Pattern 3: Batch Processing

```python
tracker = SessionTracker(session_id="batch-emails-01", workspace="batch-jan")
tracker.start("Process January emails batch 1/4")

for i, email in enumerate(emails):
    process(email)
    if i % 100 == 0:
        pct = int((i / len(emails)) * 100)
        tracker.heartbeat(progress_pct=pct, message=f"Processed {i}/{len(emails)}")

tracker.complete(message=f"Processed {len(emails)} emails")
```

## CLI Reference

```bash
# One-shot dashboard
python scripts/parallel_monitor.py -w adrs

# Live dashboard (polls every 30s)
python scripts/parallel_monitor.py -w adrs --watch

# Watch with faster polling
python scripts/parallel_monitor.py -w adrs --watch --poll-interval 10

# Block until all done (CI-friendly)
python scripts/parallel_monitor.py -w adrs --wait --timeout 120

# Check specific session log
python scripts/parallel_monitor.py -w adrs -s adr-01 --log

# Machine-readable output
python scripts/parallel_monitor.py -w adrs --json

# Custom timeouts
python scripts/parallel_monitor.py -w adrs --watch \
    --heartbeat-timeout 600 --session-timeout 7200
```

## Dashboard Output Example

```
  Parallel Session Dashboard: adrs
  =======================================================
  Total: 4 | Running: 1 | Done: 2 | Failed: 1 | Timed Out: 0 | Stale: 0
  -------------------------------------------------------
  [+] adr-01               [####################] 100% | ADR-001 complete
  [+] adr-02               [####################] 100% | ADR-002 complete
  [~] adr-03               [############--------]  60% | Drafting options
  [X] adr-04               [######--------------]  30% | FAILED: API timeout
      Last error: [2026-02-13T10:30:00] FATAL: API timeout
  -------------------------------------------------------
  Polled at: 2026-02-13T10:45:00+00:00
```

## Checklist: Launching Parallel Work

Before kicking off parallel sessions, use this checklist:

- [ ] Defined workspace name (e.g., `adrs`, `features-v2`)
- [ ] Assigned unique session IDs
- [ ] Each session script uses `SessionTracker`
- [ ] Each session calls `tracker.start()` with a description
- [ ] Each session has heartbeats at least every 5 minutes
- [ ] Each session calls `tracker.complete()` or `tracker.fail()`
- [ ] Coordinator has `parallel_monitor.py` ready to run
- [ ] `.parallel/` is in `.gitignore`
- [ ] Timeout values are set appropriately for the work

## Failure Recovery

| Scenario | Detection | Response |
|----------|-----------|----------|
| Session hangs silently | Heartbeat timeout (5m) | Monitor marks as TIMED_OUT |
| Session crashes | No COMPLETED/FAILED marker | Monitor detects via stale heartbeat |
| Session takes too long | Session timeout (4h) | Monitor marks as TIMED_OUT |
| Partial output | Check `output_files` in status | Coordinator decides whether to retry |
| Coordinator crashes | Restart monitor, state persists in files | Just re-run `parallel_monitor.py` |

## What NOT to Use This For

This system is for **local Claude Code session coordination**. Do NOT confuse it with:

- **Dream Team Task Queue** (`backend/services/task_queue.py`) - that's for multi-agent orchestration in production
- **WAL Service** (`backend/services/wal.py`) - that's for Fast Path/Slow Path decoupling
- **Backend observability** (`lib/agent/routers/observability.py`) - that's for production API health

This is a **development-time tool** for managing parallel coding sessions.
