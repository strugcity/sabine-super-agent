# Sabine 2.0 Backward Compatibility Strategy

**Purpose:** Ensure Sabine 1.0 runs untouched during entire 16-week Sabine 2.0 development
**Status:** Strategy (ready for Phase 1 implementation)
**Last Updated:** February 13, 2026

---

## Executive Summary

Sabine 2.0 is built in parallel to Sabine 1.0 with **zero production risk**:
- Sabine 1.0 code is NEVER modified
- Sabine 2.0 code is isolated in `/backend/v2/`
- If Sabine 2.0 breaks: rollback in <1 minute with kill switch
- User impact guarantee: 0 downtime

---

## Architecture Isolation

### Sabine 1.0 (Production - UNCHANGED)
```
/lib/agent/
├─ memory.py      ✓ UNTOUCHED
├─ retrieval.py   ✓ UNTOUCHED
├─ core.py        ✓ UNTOUCHED
├─ registry.py    ✓ UNTOUCHED
└─ scheduler.py   ✓ UNTOUCHED

FastAPI Server (Sabine 1.0)
└─ Responds to user queries instantly (<12s)
```

### Sabine 2.0 (Development - ISOLATED)
```
/backend/v2/
├─ memory.py              [NEW]
├─ wal.py                 [NEW]
├─ worker/consolidate.py  [NEW]
├─ magma/extract.py       [NEW]
└─ belief/revision.py     [NEW]

Worker Process (separate Railway service)
└─ Runs nightly at 2:00 AM, isolated memory/CPU
```

### Database Schema

**Existing tables (Sabine 1.0 reads/writes):**
```sql
memories           ← Sabine 1.0 primary table
entities           ← Sabine 1.0
entities_connections ← Sabine 1.0
```

**Modified tables (backward-compatible):**
```sql
ALTER TABLE memories ADD COLUMN salience_score FLOAT DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN is_archived BOOLEAN DEFAULT false;
ALTER TABLE memories ADD COLUMN confidence FLOAT DEFAULT 1.0;

-- Sabine 1.0 queries still work perfectly:
SELECT * FROM memories;  ✓ (new columns ignored)
```

**New tables (Sabine 2.0 only):**
```sql
write_ahead_log          ← Sabine 2.0 writes here (WAL)
entity_relationships     ← Sabine 2.0 builds MAGMA graphs
memory_archive           ← Sabine 2.0 archives cold memories
salience_scores          ← Sabine 2.0 tracks salience

-- Sabine 1.0 never reads these ✓
```

---

## Dual-Write Strategy (Fast Path)

### What Happens on Every User Message

```
User: "What's the status of Project X?"
         │
         ▼
    FastAPI /invoke
         │
         ├─→ Sabine 1.0 (unchanged logic)
         │   ├─→ LLM reasoning
         │   ├─→ Tool execution
         │   ├─→ WRITE to memories table ✓
         │   └─→ RESPOND to user <12s ✓
         │
         └─→ Sabine 2.0 (new, non-blocking)
             ├─→ TRY WRITE to write_ahead_log
             │   ├─→ Success: logged for nightly processing
             │   └─→ Failure: logged as warning (doesn't affect user)
             └─→ [No latency impact on user response]
```

### Code Pattern

```python
async def invoke(user_message: str) -> str:
    """Fast Path: unchanged behavior + optional 2.0 logging"""

    # SABINE 1.0: Original logic (untouched)
    response = await lm_run(user_message)
    await save_to_memories(response)

    # SABINE 2.0: New, non-blocking (feature-flagged)
    if ENABLE_SABINE_V2:
        try:
            await wal.write(user_message, response)
        except Exception as e:
            logging.warning(f"WAL write failed (non-critical): {e}")
            # ✓ If this fails, user still gets response
            # ✓ Sabine 1.0 unaffected

    return response  # ✓ User gets response regardless
```

### Guarantees

- **No latency impact:** WAL write is async, doesn't block user response
- **Non-critical:** If WAL fails, user still gets response
- **Idempotent:** Same message written twice = same result
- **Easy disable:** Set `ENABLE_SABINE_V2=false` in config

---

## Rollback Plan (Emergency)

### If Sabine 2.0 Breaks Production

**Step 1: Set kill switch**
```bash
ENABLE_SABINE_V2=false
```

**Step 2: Restart FastAPI (optional, not required)**
```bash
railway deploy --service sabine-api
```

**Step 3: Verify Sabine 1.0**
```bash
curl -X POST /invoke -d '{"message": "test"}'
→ ✓ Response in <12s
```

### Rollback Metrics

| Metric | Value |
|--------|-------|
| Time to rollback | <1 minute |
| Code restart needed | No (config only) |
| User downtime | 0 seconds |
| Data loss | 0 bytes |
| 1.0 recovery | 100% (unchanged) |

---

## Schema Safety Rules

### ✅ SAFE Operations

```sql
ALTER TABLE memories ADD COLUMN salience_score FLOAT DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN is_archived BOOLEAN;
CREATE TABLE write_ahead_log (...);
CREATE INDEX idx_wal_created ON write_ahead_log(created_at);
```

### ❌ DANGEROUS Operations

```sql
ALTER TABLE memories DROP COLUMN old_field;
ALTER TABLE memories RENAME COLUMN x TO y;
ALTER TABLE memories ALTER COLUMN id SET DATA TYPE BIGINT;
ALTER TABLE memories ADD COLUMN new_field VARCHAR NOT NULL;
```

---

## Regression Testing

### Must Run After Every Commit

```bash
# Sabine 1.0 regression tests
pytest tests/sabine_v1/test_retrieval_consistency.py -v

# Schema compatibility tests
pytest tests/integration/test_schema_compatibility.py -v

# Canary tests (production data)
pytest tests/canary/test_production_sabine_v1.py -v
```

---

## Deployment Timeline

### Week 1-3: Development (Dark Mode)
- Code building in `/backend/v2/`
- Feature flag OFF (no WAL writes)
- **Sabine 1.0:** ✓ unchanged, fully operational

### Week 4: Manual Testing
- Worker testing on staging only
- Verify memory <1.5GB
- Verify accuracy >80%
- **Sabine 1.0:** ✓ unchanged, production running

### Week 5+: Shadow Mode
- Worker runs at 2:00 AM UTC
- Processes real user WAL entries
- Sabine 1.0 unaware (doesn't read v2 tables)
- **Sabine 1.0:** ✓ unchanged, primary retrieval

### Week 8+: Dual-Read (Optional)
- Both 1.0 + 2.0 retrieve context
- Compare results, log mismatches
- Still serve 1.0 to users
- **Sabine 1.0:** ✓ available as fallback

### Week 12+: Optional Migration
- After 4 weeks validation (zero issues)
- Sabine 2.0 becomes primary
- Sabine 1.0 as instant fallback
- **Sabine 1.0:** ✓ available forever as safety net

---

## Monitoring

### Key Metrics (Must Stay Green)

**Sabine 1.0:**
- Latency P95: <12s
- Retrieval accuracy: unchanged
- Tool success rate: unchanged
- Error rate: <0.1%

**Sabine 2.0:**
- WAL write success: >99.9%
- Worker memory peak: <2GB
- Extraction accuracy: >80%
- Worker crashes: 0

---

## Verification Checklist (Before Phase 1)

- [ ] Sabine 1.0 regression tests passing
- [ ] Schema migrations backward-compatible
- [ ] Feature flag implemented
- [ ] Kill switch tested
- [ ] Dual-write latency <100ms
- [ ] Worker process isolated
- [ ] Rollback plan tested
- [ ] Monitoring configured
- [ ] Team trained on rollback

---

**Last Updated:** 2026-02-13 | **Status:** Ready for Phase 1 | **Owner:** Tech Lead
