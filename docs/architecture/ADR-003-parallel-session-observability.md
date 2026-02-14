# ADR-003: Parallel Session Observability Architecture

## Status
Accepted

## Date
2026-02-13

## Context

### Problem

When working with Claude Code, a common workflow pattern is to launch multiple Claude Code sessions in parallel -- for example, writing several ADRs simultaneously, implementing features across different branches, or running batch processing tasks. Before this system existed, we had **zero visibility** into the status of those sessions:

- A session could hang silently, and the coordinator would not discover it until manually checking.
- A session could crash partway through, producing partial output with no notification.
- There was no way to tell how far along a session was or whether it was still actively working.
- The coordinator had to manually poll terminal windows or rely on hope.

This created a reliability problem: parallel work was faster in wall-clock time, but fragile and opaque. The coordinator (the human or the main Claude Code session) needed a lightweight way to observe parallel sessions without adding heavy infrastructure.

### Constraints

1. **No network dependency.** Parallel Claude Code sessions run on the local machine. Any observability system must work purely on the local filesystem -- no database, no HTTP server, no cloud service.
2. **No external services.** Adding Redis, a message broker, or a monitoring service would be overkill for coordinating 2-8 local sessions.
3. **Minimal overhead.** The tracker must not slow down the actual work. Writing a JSON file every few minutes is acceptable; running a background daemon is not.
4. **Separation from production infrastructure.** The project already has production-grade orchestration (`backend/services/task_queue.py`) and data pipelines (`backend/services/wal.py`). This system must not be confused with or entangled with those.

## Decision

We implement a **file-based observability system** in `lib/parallel/` consisting of two primary components:

### 1. SessionTracker (Writer)

Each parallel session instantiates a `SessionTracker` that writes status to a well-known directory structure:

```
.parallel/
  <workspace>/              # Logical group (e.g., "adrs", "features")
    <session-id>/           # One directory per parallel session
      status.json           # Current status (overwritten on each heartbeat)
      log.jsonl             # Append-only event log
      COMPLETED             # Marker file (written on success)
      FAILED                # Marker file (written on failure)
```

The tracker provides a simple lifecycle API:

- `tracker.start(description)` -- marks the session as RUNNING, records start time
- `tracker.heartbeat(progress_pct, message)` -- updates progress and timestamp
- `tracker.error(msg)` -- records a non-fatal error without failing the session
- `tracker.complete(output_files, message)` -- marks COMPLETED, writes marker file
- `tracker.fail(error_summary)` -- marks FAILED, writes marker file

### 2. SessionMonitor (Reader)

The coordinator session (or a standalone script) uses `SessionMonitor` to read status from the `.parallel/` directory:

- `monitor.poll_all()` -- reads all session statuses and returns a `WorkspaceSummary`
- `monitor.print_dashboard()` -- renders a text-based dashboard to the terminal
- `monitor.wait_for_all(timeout_minutes)` -- blocks until all sessions reach terminal state
- `monitor.read_session_log(session_id)` -- reads the append-only event log

The monitor also implements **automatic timeout detection**:

- **Heartbeat timeout** (default: 5 minutes): If a running session has not sent a heartbeat within this window, the monitor marks it as `TIMED_OUT`.
- **Session timeout** (default: 4 hours): If a session has been running for longer than this, the monitor marks it as `TIMED_OUT`.

### 3. Pydantic Models

All data structures are defined as Pydantic v2 `BaseModel` classes in `lib/parallel/models.py`:

- `SessionState` -- enum: `pending`, `running`, `completed`, `failed`, `timed_out`
- `SessionStatus` -- the primary status payload written to `status.json`
- `CompletionMarker` -- written to `COMPLETED` or `FAILED` marker files
- `WorkspaceSummary` -- aggregated status across all sessions in a workspace

### Key Design Choices

| Choice | Rationale |
|--------|-----------|
| **File-based, not database-backed** | No network dependency, trivially debuggable (just `cat status.json`), no setup required |
| **Overwrite `status.json` on every heartbeat** | Latest-wins semantics; we only care about current state, not history (that is what `log.jsonl` is for) |
| **Append-only `log.jsonl`** | Provides a full audit trail without the cost of version-controlled JSON |
| **Marker files (`COMPLETED` / `FAILED`)** | Enables fast terminal-state detection via `Path.exists()` without parsing JSON |
| **Workspace grouping** | Isolates unrelated parallel work (ADRs vs. feature branches vs. batch jobs) |
| **Monitor is read-only** | Prevents the coordinator from accidentally mutating session state; sessions are sovereign over their own directories |

## Alternatives Considered

### Alternative 1: Reuse Dream Team Task Queue

**Description:** Use the existing `backend/services/task_queue.py` (Supabase-backed, priority-based, dependency-tracking task queue) to track parallel Claude Code sessions.

**Rejected because:**

- The task queue requires a live Supabase connection with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` environment variables. Parallel Claude Code sessions may not have (and should not need) production database credentials.
- The task queue is designed for multi-agent orchestration in a deployed environment (roles, claims, dependency graphs, auto-dispatch). Tracking local coding sessions is a fundamentally different concern.
- Coupling dev tooling to production infrastructure means a production schema change could break local workflows and vice versa.
- The task queue has concepts (TaskStatus.AWAITING_APPROVAL, CANCELLED_FAILED, role-based routing) that have no meaning in the context of parallel coding sessions.

### Alternative 2: Database-Backed Local Tracking

**Description:** Use SQLite (or a local Supabase instance) to store session status in a relational database.

**Rejected because:**

- Adds a dependency (SQLite driver or local Supabase) that JSON files do not require.
- JSON files on disk are trivially inspectable (`cat`, `jq`), while a database requires a client tool.
- There is no query complexity that justifies a database -- we read a handful of files from known paths.
- File-based state survives process crashes naturally (the file is on disk). Database transactions require explicit commit handling.

### Alternative 3: No Tracking (Status Quo)

**Description:** Continue launching parallel sessions without any observability. Rely on terminal output and manual checking.

**Rejected because:**

- Multiple sessions printing to different terminals provides no aggregated view.
- No timeout detection: a session could silently hang for hours.
- No completion signaling: the coordinator has to manually check each session's output directory.
- This approach does not scale beyond 2-3 sessions.

### Alternative 4: Shared Log File

**Description:** All sessions append to a single shared log file, and the coordinator tails it.

**Rejected because:**

- Concurrent writes to a single file create race conditions and interleaved output.
- Parsing a shared log to reconstruct per-session state is fragile and error-prone.
- No structured status (progress percentage, state machine, output files).

## Consequences

### Positive

1. **Full visibility into parallel work.** The coordinator can see which sessions are running, their progress, and whether any have failed or timed out.
2. **Automatic failure detection.** Heartbeat and session timeouts catch silently hung sessions without human intervention.
3. **Zero infrastructure cost.** No database, no network, no services to run. Just filesystem reads and writes.
4. **Debuggable.** When something goes wrong, `cat .parallel/adrs/adr-03/status.json` gives immediate answers. No log aggregation tool needed.
5. **Crash-resilient.** If the coordinator crashes, session state persists on disk. Restarting the monitor picks up right where it left off. If a session crashes, the stale heartbeat triggers timeout detection.
6. **Clean separation from production systems.** The `.parallel/` directory is `.gitignore`-d and has no connection to the Dream Team task queue, WAL service, or production observability.

### Negative

1. **Filesystem-only.** This does not work for remote or distributed Claude Code sessions (though that is not a current use case).
2. **No push notifications.** The monitor must poll; there is no event-driven mechanism for instant state change notification.
3. **Manual cleanup.** Old `.parallel/` directories accumulate until manually deleted (though since they are gitignored, they do not pollute the repo).

### Neutral

1. **Parallel sessions must opt in.** If a session does not use `SessionTracker`, it is invisible to the monitor. This is by design (no implicit tracking), but requires discipline.
2. **Heartbeat frequency is the session's responsibility.** If a session forgets to heartbeat for 6 minutes, the monitor will mark it as timed out even if it is still working. This is a deliberate tradeoff: false positives from missing heartbeats are less harmful than false negatives from silently hung sessions.

## Key Distinction: Dev Tooling, Not Production Infrastructure

This system is **development tooling** for coordinating parallel Claude Code sessions on a local machine. It must not be confused with:

| System | Purpose | Backing Store | Deployed? |
|--------|---------|---------------|-----------|
| `lib/parallel/` (this ADR) | Local session observability | Filesystem (`.parallel/`) | No -- local dev only |
| `backend/services/task_queue.py` | Dream Team multi-agent orchestration | Supabase (Postgres) | Yes -- production |
| `backend/services/wal.py` | Fast Path / Slow Path decoupling | Supabase (Postgres) | Yes -- production |
| `lib/agent/routers/observability.py` | Production API health checks | In-memory / Supabase | Yes -- production |

These systems serve different audiences, run in different environments, and have different reliability requirements. They must remain decoupled.

## Implementation

The implementation lives in `lib/parallel/` with three source files:

- **`lib/parallel/models.py`** -- Pydantic v2 models (`SessionState`, `SessionStatus`, `CompletionMarker`, `WorkspaceSummary`)
- **`lib/parallel/tracker.py`** -- `SessionTracker` class (writer side)
- **`lib/parallel/monitor.py`** -- `SessionMonitor` class (reader side)
- **`lib/parallel/__init__.py`** -- Public API re-exports

Usage conventions and operational guidelines are documented in `docs/plans/parallel-work-best-practices.md`.

## References

- `lib/parallel/tracker.py` -- SessionTracker implementation
- `lib/parallel/monitor.py` -- SessionMonitor implementation
- `lib/parallel/models.py` -- Pydantic v2 data models
- `docs/plans/parallel-work-best-practices.md` -- Operational best practices
- `backend/services/task_queue.py` -- Dream Team task queue (production, for contrast)
- `backend/services/wal.py` -- WAL service (production, for contrast)
