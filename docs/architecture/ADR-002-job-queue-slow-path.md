# ADR-002: Job Queue for Slow Path Processing

## Status

**Accepted**

## Date

2026-02-13

## Deciders

Tech Lead, Backend Architect

---

## Context

Sabine's ingestion architecture follows a **Dual-Stream** design (PRD Section 4.3):

- **Fast Path:** Real-time message handling with <100ms write to the Write-Ahead Log (WAL) in Supabase. Runs inside the FastAPI process.
- **Slow Path:** Asynchronous consolidation that reads pending WAL entries, performs entity extraction, memory consolidation, relationship graph updates, and embedding generation.

### Current Implementation

The Slow Path consolidation is driven by **APScheduler** (`AsyncIOScheduler`) running inside the FastAPI process:

| Component | File | Role |
|---|---|---|
| WAL Service | `backend/services/wal.py` | WAL entry CRUD, claim/retry/checkpoint logic |
| Proactive Scheduler | `lib/agent/scheduler.py` | APScheduler singleton for morning briefings, cron jobs |
| Email Poller | `lib/agent/email_poller.py` | APScheduler-based 2-minute polling fallback for Gmail |

The scheduler runs as an `AsyncIOScheduler` singleton inside FastAPI, sharing the same process and memory space. Jobs are added via `CronTrigger` and execute as async coroutines in the FastAPI event loop.

### Problems with the Current Approach

1. **OOM Risk (Critical):** Consolidation of 100-500 WAL entries involves loading payloads, calling Claude for entity extraction, generating embeddings, and writing to multiple tables. This all runs in the same process as the web server. A large batch can spike memory to the point where Railway's 512 MB container OOM-kills the entire service, taking down both the API and all scheduled jobs.

2. **No Crash Isolation:** If the consolidation worker panics or hits an unrecoverable error, it can corrupt the APScheduler state or crash the entire FastAPI process. The WAL service has `recover_abandoned_entries()` (entries stuck in `processing` for >15 minutes), but recovery depends on the process restarting cleanly.

3. **No Built-in Retry Visibility:** The WAL service implements manual retry logic with exponential backoff (30s, 5m, 15m) and a 3-retry cap. However, there is no dashboard, no dead-letter queue inspection, and no alerting. Failed entries require manual SQL queries to diagnose.

4. **Blocking the Event Loop:** Heavy CPU-bound work (embedding generation, hash computation) running as async tasks in the FastAPI event loop can increase API response latency for concurrent users.

5. **Scaling Ceiling:** APScheduler is single-process. There is no way to add a second worker for parallelism without significant re-architecture.

---

## Decision

We will adopt **Redis Queue (rq)** as the job queue for all Slow Path processing.

- Redis will be provisioned as a Railway add-on attached to the existing project.
- A dedicated `rq` worker process will run as a separate Railway service.
- The FastAPI process will enqueue jobs to Redis rather than executing consolidation inline.
- APScheduler will remain for lightweight cron triggers (morning briefing, email polling) but will enqueue rq jobs instead of doing heavy work itself.

---

## Options Considered

### Option A: APScheduler (Current - Status Quo)

Keep the existing `AsyncIOScheduler` running consolidation inside the FastAPI process.

**Pros:**
- Already implemented and working.
- Zero additional infrastructure cost.
- No new dependencies to learn or maintain.

**Cons:**
- OOM risk is unmitigated; consolidation and API share memory.
- No crash isolation; a consolidation failure can take down the API.
- Retry logic, monitoring, and dead-letter handling are all custom code.
- Single-process; cannot scale workers independently.
- Event loop contention during heavy processing.

### Option B: Redis Queue (rq)

Use `rq` (Redis Queue) with a separate worker process, backed by a Railway Redis add-on.

**Pros:**
- Full memory isolation: worker crashes do not affect the FastAPI API.
- Built-in retry with configurable backoff and TTL.
- `rq-dashboard` provides a free web UI for job inspection, retry, and dead-letter queue management.
- Minimal API surface; easy to learn (pure Python, ~500 lines of core code).
- Worker can be scaled horizontally by adding Railway service replicas.
- Redis add-on cost is $5-10/month on Railway.

**Cons:**
- New infrastructure dependency (Redis).
- Requires a separate Railway service for the worker process.
- `rq` workers are synchronous by default; async consolidation code needs minor adaptation (run in `asyncio.run()` wrapper or use `rq`'s async support).
- Redis is an additional point of failure (mitigated by Railway's managed Redis with persistence).

### Option C: Dramatiq

Use `dramatiq` with a Redis broker and a separate worker process.

**Pros:**
- More feature-rich than rq: rate limiting, priority queues, middleware pipeline.
- Strong typing support and good documentation.
- Built-in support for periodic tasks via `periodiq` (could fully replace APScheduler).
- Battle-tested at higher scale than rq.

**Cons:**
- Heavier dependency footprint; more concepts to learn (middleware, broker, results backend).
- Overkill for current scale (100-500 WAL entries/night).
- Dashboard (`dramatiq-dashboard`) is less mature than `rq-dashboard`.
- More complex configuration and debugging.
- Community and maintenance pace is slower than rq.

### Comparison Table

| Criterion | APScheduler (Current) | Redis Queue (rq) | Dramatiq |
|---|---|---|---|
| **OOM Isolation** | None | Full (separate process) | Full (separate process) |
| **Crash Isolation** | None | Full | Full |
| **Retry Logic** | Manual (custom WAL code) | Built-in (configurable) | Built-in (middleware) |
| **Monitoring / Dashboard** | None (custom SQL) | rq-dashboard (free) | dramatiq-dashboard (basic) |
| **Setup Complexity** | Already done | Low (~2 hours) | Medium (~4 hours) |
| **Learning Curve** | None | Low (simple API) | Medium (middleware concepts) |
| **Async Support** | Native (asyncio) | Wrapper needed | Native via async middleware |
| **Periodic/Cron Tasks** | Built-in (CronTrigger) | Needs rq-scheduler add-on | periodiq extension |
| **Horizontal Scaling** | Not possible | Add worker replicas | Add worker replicas |
| **Infrastructure Cost** | $0 | ~$5-10/mo (Redis add-on) | ~$5-10/mo (Redis add-on) |
| **Maturity** | Very mature | Mature, widely used | Mature, smaller community |
| **Dependencies** | Already installed | redis, rq | dramatiq, redis |

---

## Rationale

**Redis Queue (rq) is selected** because it provides the critical OOM and crash isolation we need, with the lowest complexity overhead for our current scale:

1. **OOM Isolation is the primary driver.** The WAL consolidation workload (entity extraction via Claude, embedding generation, multi-table writes) is memory-intensive and unpredictable. Running it in a separate process means the FastAPI API stays responsive even if the worker hits memory limits. Railway can restart the worker independently without affecting API availability.

2. **Built-in retry and monitoring reduce custom code.** The existing WAL service already has ~80 lines of manual retry logic (`mark_failed`, `get_backoff_seconds`, `recover_abandoned_entries`). With rq, retry configuration is declarative, and `rq-dashboard` provides immediate visibility into queued, failed, and completed jobs without writing custom SQL queries.

3. **Minimal cost and complexity.** Railway's Redis add-on is $5-10/month. rq's API is intentionally simple (~5 core concepts: Queue, Job, Worker, FailedJobRegistry, rq-dashboard). The learning curve is measured in hours, not days.

4. **Dramatiq is overkill.** While Dramatiq offers features like rate limiting and priority queues, these are not needed at our current scale. The additional complexity of its middleware pipeline and configuration is not justified. If we outgrow rq (unlikely before 10x scale), migrating to Dramatiq is straightforward since both use Redis as the broker.

5. **APScheduler remains for cron triggers.** APScheduler is lightweight and well-suited for "trigger at 2:00 AM" or "every 2 minutes" scheduling. The key change is that APScheduler will enqueue an rq job rather than executing the heavy work itself. This preserves existing patterns in `scheduler.py` and `email_poller.py` while offloading the actual processing.

---

## Consequences

### Positive

- **Production stability:** API process is protected from OOM during consolidation. Worker crashes are isolated and auto-recovered by Railway.
- **Operational visibility:** `rq-dashboard` provides real-time insight into job status, failure reasons, and queue depth without custom tooling.
- **Simplified retry logic:** Declarative retry configuration replaces ~80 lines of manual retry/backoff code in `wal.py`.
- **Independent scaling:** Worker can be allocated more memory or replicated without affecting API resource allocation.
- **Foundation for future workloads:** Skills acquisition, cold storage archival, and other Slow Path tasks can be enqueued to rq without architectural changes.

### Negative

- **New infrastructure dependency:** Redis becomes a required service. If Redis goes down, Slow Path processing halts (but Fast Path WAL writes to Supabase continue unaffected).
- **Separate deployment unit:** The rq worker is a distinct Railway service that must be deployed, monitored, and versioned alongside the API.
- **Async adaptation:** Existing async consolidation code must be wrapped for rq's synchronous worker model (minor, one-time effort).
- **Cold start latency:** Worker process startup includes importing the full backend module graph. First job after deploy may have 5-10s overhead.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Redis unavailable | Low | Medium (Slow Path halts; Fast Path unaffected) | Railway managed Redis with persistence and auto-restart. WAL entries remain in Supabase as durable source of truth; processing resumes when Redis recovers. |
| Worker OOM on very large batches | Low | Low (worker restarts, job retries) | Configure batch size limits. Set Railway memory limits with auto-restart. rq marks job as failed on worker death; retry picks it up. |
| Job serialization issues | Low | Low | Use simple dict payloads (WAL entry IDs, not full payloads). Worker fetches full data from Supabase. |
| Dashboard exposed publicly | Medium | Medium (info leak) | Run rq-dashboard on internal port only, behind authentication, or access via Railway private networking. |
| Redis memory growth | Low | Medium | Set Redis `maxmemory` with `allkeys-lru` policy. Completed jobs are cleaned up by TTL. Monitor with Railway metrics. |

---

## Implementation Notes

### Worker Architecture

```
                    +-------------------+
                    |   Railway Redis   |
                    |   (managed)       |
                    +--------+----------+
                             |
              +--------------+--------------+
              |                             |
    +---------v---------+       +-----------v-----------+
    |  FastAPI API       |       |  rq Worker            |
    |  (Railway Service) |       |  (Railway Service)    |
    |                    |       |                       |
    |  APScheduler       |       |  Consolidation jobs   |
    |  (cron triggers)   |       |  Entity extraction    |
    |        |           |       |  Embedding generation |
    |        v           |       |  Graph updates        |
    |  enqueue rq job    |       |  Memory consolidation |
    |                    |       |                       |
    +--------+-----------+       +-----------+-----------+
             |                               |
             +-------------------------------+
                             |
                    +--------v----------+
                    |  Supabase         |
                    |  (WAL + Entities) |
                    +-------------------+
```

### Key Design Decisions

1. **Job payload is minimal.** Enqueue only WAL entry IDs (or a batch range). The worker fetches full payloads from Supabase. This keeps Redis memory usage low and avoids serialization issues with complex objects.

2. **One queue, one worker (initially).** Start with a single `slow-path` queue and a single worker process. Add queues (e.g., `slow-path-priority`) or workers only when monitoring shows a need.

3. **APScheduler as cron trigger only.** The scheduler's `_run_morning_briefing_wrapper` and email poll functions will be refactored to enqueue rq jobs instead of executing heavy logic directly. The scheduler remains lightweight.

### Railway Redis Setup

```yaml
# railway.toml (worker service)
[deploy]
startCommand = "rq worker slow-path --url $REDIS_URL --with-scheduler"
healthcheckPath = ""  # Worker has no HTTP endpoint
restartPolicyType = "always"

[build]
builder = "nixpacks"
```

Environment variables (shared via Railway service variables):
- `REDIS_URL` - Automatically set by Railway Redis add-on
- `SUPABASE_URL` - Existing
- `SUPABASE_SERVICE_ROLE_KEY` - Existing
- `ANTHROPIC_API_KEY` - Existing

### Retry Configuration

```python
from rq import Queue, Retry
from redis import Redis

redis_conn = Redis.from_url(os.getenv("REDIS_URL"))
slow_path_queue = Queue("slow-path", connection=redis_conn)

# Enqueue with retry policy matching current WAL backoff: 30s, 5m, 15m
slow_path_queue.enqueue(
    consolidate_wal_batch,
    entry_ids=["uuid1", "uuid2", ...],
    retry=Retry(max=3, interval=[30, 300, 900]),
    job_timeout="10m",       # Max execution time per job
    result_ttl=86400,        # Keep results for 24h
    failure_ttl=604800,      # Keep failures for 7 days
)
```

### Worker Entry Point

```python
# backend/workers/slow_path_worker.py

import asyncio
import logging
from typing import List
from backend.services.wal import WALService, WALStatus

logger = logging.getLogger(__name__)

def consolidate_wal_batch(entry_ids: List[str]) -> dict:
    """
    Process a batch of WAL entries.

    This function runs in the rq worker process (synchronous).
    It wraps the async consolidation logic.
    """
    return asyncio.run(_async_consolidate(entry_ids))

async def _async_consolidate(entry_ids: List[str]) -> dict:
    """Async implementation of WAL batch consolidation."""
    wal_service = WALService()
    results = {"processed": 0, "failed": 0, "errors": []}

    for entry_id in entry_ids:
        try:
            entry = await wal_service.get_entry_by_id(entry_id)
            if not entry or entry.status != WALStatus.PENDING.value:
                continue

            await wal_service.mark_processing(entry.id, worker_id="rq-worker")

            # ... entity extraction, embedding, graph update ...

            await wal_service.mark_completed(entry.id)
            results["processed"] += 1

        except Exception as e:
            logger.error(f"Failed to process WAL entry {entry_id}: {e}")
            await wal_service.mark_failed(entry.id, str(e))
            results["failed"] += 1
            results["errors"].append({"id": entry_id, "error": str(e)})

    return results
```

### Monitoring Approach

1. **rq-dashboard:** Deploy as a lightweight route or standalone service for job inspection.
   ```python
   # Optional: Mount rq-dashboard in FastAPI (dev/staging only)
   from rq_dashboard import RQDashboard
   # Or run standalone: rq-dashboard --redis-url $REDIS_URL
   ```

2. **Health Check Endpoint:** Extend the existing FastAPI `/health` endpoint to include Redis connectivity and queue depth.
   ```python
   @router.get("/health")
   async def health():
       redis_ok = ping_redis()
       queue_depth = get_queue_depth("slow-path")
       failed_count = get_failed_count("slow-path")
       return {
           "api": "ok",
           "redis": "ok" if redis_ok else "degraded",
           "slow_path_queue_depth": queue_depth,
           "slow_path_failed_jobs": failed_count,
       }
   ```

3. **Alerting:** Log warnings when queue depth exceeds threshold (>500 pending jobs) or failed job count exceeds threshold (>10 in 24 hours). Integrate with existing logging pipeline.

---

## Migration Plan

The migration from APScheduler-based consolidation to rq workers will be executed in four phases with zero-downtime transitions.

### Phase 1: Add Redis and rq Infrastructure (No Behavior Change)

**Duration:** 1 day

1. Provision Railway Redis add-on. Verify connectivity from the existing API service via `REDIS_URL`.
2. Add `redis` and `rq` to `requirements.txt`.
3. Create `backend/workers/slow_path_worker.py` with the consolidation job function.
4. Create a `worker` Railway service with `rq worker slow-path --url $REDIS_URL` start command.
5. Deploy. Verify the worker starts and connects to Redis. No jobs are enqueued yet.

**Rollback:** Remove the worker service. No impact on existing behavior.

### Phase 2: Dual-Write (Shadow Mode)

**Duration:** 2-3 days of observation

1. Modify the APScheduler consolidation trigger to **both** run the existing in-process logic **and** enqueue an rq job with the same WAL entry IDs.
2. The rq job runs in "dry-run" mode: it fetches entries, logs what it would do, but does not write results.
3. Compare logs between the in-process execution and the rq dry-run to verify parity.

**Rollback:** Remove the dual-write. In-process logic continues unchanged.

### Phase 3: Switch Primary to rq

**Duration:** 1 day, with 48-hour monitoring window

1. Modify the APScheduler trigger to enqueue rq jobs **only** (remove in-process execution).
2. Enable the rq worker to write results (exit dry-run mode).
3. Monitor via rq-dashboard and health endpoint for 48 hours.
4. Verify: all WAL entries processed, no increase in failed entries, API latency stable.

**Rollback:** Re-enable in-process execution in the APScheduler trigger. WAL entries are idempotent, so any partially processed entries will be safely re-processed.

### Phase 4: Cleanup

**Duration:** 1 day

1. Remove the in-process consolidation code paths from the APScheduler jobs.
2. Simplify `WALService.mark_failed()` retry logic (rq handles retries now; WAL status tracking remains for audit).
3. Remove `recover_abandoned_entries()` (rq handles this via job TTL and failure registry).
4. Update documentation and runbooks.
5. Add rq-dashboard to the internal tools page.

### Migration Safety Net

Throughout the migration, the **WAL table in Supabase remains the source of truth.** Even if Redis is lost entirely, pending WAL entries persist in Postgres. A fallback script can revert to direct processing from the WAL table if needed. This dual-durability (Supabase WAL + Redis queue) means data loss is not possible during migration.

---

## References

- [rq Documentation](https://python-rq.org/)
- [rq-dashboard](https://github.com/Selwin/rq-dashboard)
- [Railway Redis Add-on](https://docs.railway.app/databases/redis)
- PRD: `PRD_Sabine_2.0_Complete.md` - Section 4.3 (Dual-Stream Ingestion)
- Technical Decisions Framework: `docs/Sabine_2.0_Technical_Decisions.md` - ADR-002
- Current WAL Implementation: `backend/services/wal.py`
- Current Scheduler: `lib/agent/scheduler.py`
- Current Email Poller: `lib/agent/email_poller.py`
