# RUBE Recipe: Sabine 2.0 Nightly Consolidation

**Recipe Name:** `sabine-slow-path-consolidation`
**Purpose:** Automate nightly Slow Path processing without human-in-loop
**Status:** Template (ready for Phase 1 implementation)
**Created:** February 13, 2026

---

## Overview

The Sabine 2.0 Slow Path consolidation runs nightly at 2:00 AM UTC to:
1. Process Write-Ahead Log (WAL) entries from the fast path
2. Extract entity relationships (MAGMA graph building)
3. Calculate salience scores for memories
4. Archive low-salience memories to cold storage
5. Monitor worker health and alert on failures

This RUBE recipe removes the need for manual scheduling or human monitoring.

---

## Recipe Configuration

### Basic Info

```json
{
  "name": "sabine-slow-path-consolidation",
  "description": "Nightly consolidation: WAL processing, relationship extraction, salience calculation, memory archival",
  "schedule": "0 2 * * *",  // 2:00 AM UTC daily
  "enabled": true,
  "timeout_minutes": 45,
  "retry_policy": {
    "max_attempts": 3,
    "backoff_multiplier": 2,
    "initial_delay_minutes": 5
  }
}
```

### Schedule (Cron)

```
0 2 * * *
│ │ │ │ └─ Day of week (0-6, 0=Sunday)
│ │ │ └─── Month (1-12)
│ │ └───── Day of month (1-31)
│ └─────── Hour (0-23, UTC)
└───────── Minute (0-59)

→ Runs every day at 2:00 AM UTC
```

**Alternative schedules:**
- `0 2 * * 0` - Weekly (Sundays 2 AM)
- `0 2 1 * *` - Monthly (1st of month at 2 AM)
- `0 */6 * * *` - Every 6 hours

---

## Input Parameters

None required (uses production database). All configuration via environment variables.

**Environment Variables (already set in Phase 1):**
- `SUPABASE_URL` - Database connection
- `SUPABASE_KEY` - Service role API key (for writes)
- `ANTHROPIC_API_KEY` - Claude Haiku for relationship extraction
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` - Job queue
- `SLACK_WEBHOOK_URL` - Failure notifications (optional)

---

## Execution Flow

```
START (2:00 AM UTC)
    │
    ├─→ [STEP 1] Trigger Worker Job
    │   • Submit slow-path-consolidation job to Redis queue
    │   • Get job ID for tracking
    │   • Log start time + context
    │
    ├─→ [STEP 2] Monitor Job Progress (Poll every 30s)
    │   • Check job status: pending → running → completed/failed
    │   • Log progress milestones
    │   • Timeout if > 45 minutes
    │
    ├─→ [STEP 3] On Successful Completion
    │   • Verify output metrics:
    │     - WAL entries processed
    │     - Relationships extracted
    │     - Memories archived
    │   • Memory usage < 2GB (safety check)
    │   • Log completion with metrics
    │
    ├─→ [STEP 4] On Failure
    │   • Retry up to 3x (exponential backoff)
    │   • Alert to Slack (if webhook configured)
    │   • Log error details + stack trace
    │   • Trigger PagerDuty (critical failures only)
    │
    └─→ END (log summary + metrics)
```

---

## Recipe Implementation (Python/Node.js)

### Pseudocode

```python
# This runs in RUBE automation context
async def sabine_slow_path_consolidation():
    """Nightly consolidation automation recipe"""

    start_time = datetime.utcnow()
    job_id = None
    max_attempts = 3
    attempt = 0

    while attempt < max_attempts:
        try:
            # STEP 1: Submit job to queue
            logging.info(f"[{start_time}] Submitting slow path consolidation job")

            job_id = await redis_queue.enqueue(
                "slow_path_consolidation",
                priority="high",
                timeout="45m"
            )
            logging.info(f"Job submitted: {job_id}")

            # STEP 2: Monitor progress
            logging.info(f"[{start_time}] Monitoring job progress...")

            job_status = None
            poll_interval_seconds = 30
            max_wait_minutes = 45
            start_polling = time.time()

            while True:
                elapsed = (time.time() - start_polling) / 60

                if elapsed > max_wait_minutes:
                    raise TimeoutError(f"Job {job_id} exceeded {max_wait_minutes}m timeout")

                job_status = await redis_queue.get_job_status(job_id)

                if job_status == "completed":
                    logging.info(f"Job {job_id} completed in {elapsed:.1f}m")
                    break
                elif job_status == "failed":
                    raise JobFailedError(f"Job {job_id} failed")

                logging.debug(f"Job {job_id} status: {job_status} ({elapsed:.1f}m elapsed)")
                await asyncio.sleep(poll_interval_seconds)

            # STEP 3: Verify completion
            logging.info(f"[{start_time}] Verifying consolidation metrics...")

            result = await redis_queue.get_job_result(job_id)

            metrics = result.get("metrics", {})
            wal_entries = metrics.get("wal_entries_processed", 0)
            relationships_extracted = metrics.get("relationships_extracted", 0)
            memories_archived = metrics.get("memories_archived", 0)
            memory_peak_mb = metrics.get("memory_peak_mb", 0)
            duration_seconds = metrics.get("duration_seconds", 0)

            logging.info(f"Consolidation metrics:")
            logging.info(f"  • WAL entries processed: {wal_entries}")
            logging.info(f"  • Relationships extracted: {relationships_extracted}")
            logging.info(f"  • Memories archived: {memories_archived}")
            logging.info(f"  • Peak memory: {memory_peak_mb:.1f}MB")
            logging.info(f"  • Duration: {duration_seconds}s")

            # Safety checks
            if memory_peak_mb > 2000:  # 2GB limit
                logging.warning(f"Memory peak {memory_peak_mb:.1f}MB exceeded 2GB safety limit")

            if wal_entries == 0:
                logging.warning("No WAL entries processed - possible issue?")

            # Success
            logging.info(f"✓ Consolidation completed successfully")
            await notify_slack(
                channel="sabine-ops",
                message=f"""
✓ Sabine Slow Path Consolidation Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Job ID: {job_id}
Duration: {duration_seconds}s
WAL entries: {wal_entries}
Relationships: {relationships_extracted}
Archived: {memories_archived}
Memory peak: {memory_peak_mb:.1f}MB
                """,
                level="info"
            )

            return {
                "status": "success",
                "job_id": job_id,
                "metrics": metrics,
                "timestamp": start_time
            }

        except (TimeoutError, JobFailedError) as e:
            attempt += 1
            logging.warning(f"Attempt {attempt}/{max_attempts} failed: {e}")

            if attempt >= max_attempts:
                # Final failure
                logging.error(f"✗ Consolidation failed after {max_attempts} attempts")

                await notify_slack(
                    channel="sabine-ops",
                    message=f"""
✗ Sabine Slow Path Consolidation FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Job ID: {job_id}
Error: {str(e)}
Attempts: {max_attempts}/{max_attempts}
Timestamp: {start_time}
→ Manual investigation required
                    """,
                    level="error",
                    mentions="@sabine-ops-team"
                )

                # Trigger PagerDuty for critical failures
                await trigger_pagerduty_incident(
                    service="Sabine 2.0",
                    title="Slow Path Consolidation Failed",
                    severity="error",
                    description=f"Slow path consolidation failed after 3 attempts: {e}"
                )

                raise

            # Retry with backoff
            backoff_seconds = 5 * (2 ** (attempt - 1))  # 5s, 10s, 20s
            logging.info(f"Retrying in {backoff_seconds}s...")
            await asyncio.sleep(backoff_seconds)
```

---

## Alerting Strategy

### Success Notification

**Channel:** `#sabine-ops` (Slack)
**Frequency:** Daily (if consolidation succeeds)
**Info included:**
- Job ID (for audit trail)
- Duration + metrics
- Memory usage
- Status: ✓ Success

### Failure Notification

**Channel:** `#sabine-ops-critical` (Slack)
**Mentions:** `@sabine-ops-team`
**Frequency:** On failure (after retries exhausted)
**Info included:**
- Job ID + error message
- Attempt count + last error
- Investigation steps
- Triggers PagerDuty incident

### Metrics Logged to Telemetry

```json
{
  "metric": "sabine.consolidation.duration",
  "value": 245,
  "unit": "seconds",
  "tags": {
    "phase": "slow-path",
    "status": "success"
  }
}
```

**All metrics:**
- `sabine.consolidation.duration` - Seconds to complete
- `sabine.consolidation.wal_entries_processed` - Count
- `sabine.consolidation.relationships_extracted` - Count
- `sabine.consolidation.memories_archived` - Count
- `sabine.consolidation.memory_peak_mb` - Peak memory in MB
- `sabine.consolidation.status` - success|failed|timeout

---

## Phase 1 Integration

### Step 1: Deploy RUBE Recipe

```bash
# In Phase 1, Week 1-2
# Copy this recipe to RUBE automation system
curl -X POST https://rube-api.example.com/recipes \
  -H "Authorization: Bearer $RUBE_API_KEY" \
  -H "Content-Type: application/json" \
  -d @docs/RUBE_RECIPE_nightly-consolidation.json
```

### Step 2: Enable Schedule

```bash
# Set schedule (cron: 0 2 * * * = daily 2:00 AM UTC)
curl -X POST https://rube-api.example.com/recipes/sabine-slow-path-consolidation/schedule \
  -d '{"cron": "0 2 * * *", "enabled": true}'
```

### Step 3: Test Run (Manual)

```bash
# Trigger manually to verify before 2 AM UTC
curl -X POST https://rube-api.example.com/recipes/sabine-slow-path-consolidation/execute \
  -d '{"dry_run": false}'
```

Expected output:
```
Job ID: consolidation-2026-02-13-test
Status: success
Metrics: { "wal_entries": 45, "relationships": 230, "archived": 12, ... }
```

### Step 4: Monitor First Week

- Watch first 7 daily runs (Feb 14-20)
- Verify 2:00 AM UTC trigger consistently
- Check Slack notifications arriving
- Monitor memory usage + latency trends
- Adjust retry policy if needed

---

## Cost Analysis

**Per consolidation run:**
- Redis queue: ~$0.001 (negligible)
- Haiku API: ~$0.002 (relationship extraction)
- Supabase compute: ~$0.001
- **Total:** ~$0.004 per run

**Monthly cost (assuming 30 runs):**
- ~$0.12/month (negligible)
- Infrastructure: $10-20 (Redis already provisioned)

---

## Troubleshooting

### Recipe doesn't trigger at scheduled time

**Check:**
1. RUBE service timezone (should be UTC)
2. Recipe `enabled: true` status
3. Job queue connectivity (Redis)
4. Cron syntax: `0 2 * * *` = 2 AM UTC daily

**Fix:**
```bash
# Verify timezone
curl https://rube-api.example.com/system/info | jq '.timezone'

# Re-enable recipe
curl -X PATCH https://rube-api.example.com/recipes/sabine-slow-path-consolidation \
  -d '{"enabled": true}'
```

### Job times out (>45 minutes)

**Causes:**
1. Too many WAL entries (>1000)
2. Relationship extraction accuracy tuning
3. Database slow queries

**Fix:**
1. Increase timeout to 60 minutes
2. Profile slow-path-consolidation worker
3. Add database indexes (see Phase 1 checklist)

### Memory exceeds 2GB limit

**Causes:**
1. WAL entries not paginating
2. Relationship graph explosion
3. Memory leak in worker

**Fix:**
1. Add checkpoint after every 100 WAL entries (see Phase 1 Week 3)
2. Verify salience calculation doesn't hold all in memory
3. Profile with `memory_profiler`

### Slack notifications not arriving

**Check:**
1. `SLACK_WEBHOOK_URL` environment variable set
2. Webhook URL not expired
3. Recipe has permission to notify

**Fix:**
```bash
# Regenerate webhook
# In Slack: Apps → Sabine Bot → Incoming Webhooks → Add New
# Test webhook
curl -X POST $SLACK_WEBHOOK_URL -d '{"text":"Test"}'
```

---

## Success Criteria (Phase 1)

- [x] Recipe created and saved to docs/
- [ ] RUBE automation system accepts recipe (Phase 1 Week 2)
- [ ] Manual test run succeeds (Phase 1 Week 2)
- [ ] 7 consecutive daily runs complete without human intervention (Feb 14-20)
- [ ] All metrics logged to telemetry dashboard
- [ ] Slack notifications working
- [ ] Response time <60 seconds for monitoring queries

---

## Next Steps

1. **Phase 1 Week 1-2:** Implement Slow Path worker (see implementation plan)
2. **Phase 1 Week 2:** Deploy RUBE recipe with manual test
3. **Phase 1 Week 3:** Enable scheduled daily runs
4. **Phase 1 Week 4:** Monitor + validate for full week
5. **Phase 2+:** Enhance recipe with additional analytics as new Slow Path features launch

---

## Related Documentation

- Implementation Plan: `docs/plans/2026-02-13-sabine-2.0-implementation.md`
- Slow Path Design: `docs/Sabine_2.0_Executive_Summary.md` (Architecture section)
- Phase 1 Checklist: `docs/Sabine_2.0_Implementation_Checklist.md` (Weeks 1-4)

---

**Last Updated:** February 13, 2026
**Status:** Ready for Phase 1 Implementation
**Recipe ID:** `sabine-slow-path-consolidation` (TBD after RUBE deployment)
