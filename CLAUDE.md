# CLAUDE.md: Sabine 2.0 Development Context

**Last Updated:** February 13, 2026
**Status:** Active Development (Phase 0 - Architecture Decisions)
**Project:** Sabine Super Agent 2.0 - Memory-Based AI Partnership Platform

---

## Project Overview

### What is Sabine?

Sabine is an AI assistant that transforms from a reactive tool into a proactive strategic partner through:
- **Memory intelligence** - Extracting causal relationships from past interactions
- **Belief revision** - Updating knowledge confidently without hallucination
- **Autonomous learning** - Detecting gaps and testing fixes in sandboxes
- **Strategic push-back** - Challenging requests when they conflict with known goals

### Current Status: Phase 0 (Week of Feb 13, 2026)

**Phase 0:** Architecture Decision Records (ADRs) for 4 critical choices
- ADR-001: Graph storage (pg_graphql vs Neo4j)
- ADR-002: Job queue (Redis vs APScheduler)
- ADR-003: Sandbox provider (E2B vs Modal)
- ADR-004: Cold storage (compressed summary vs full archive)

**Next:** Phase 1 (Foundation) - Parallel 4-stream execution starting Week 1

---

## Strug City Context

### Team & Organization

**Strug City** is a virtual engineering team building AI-powered platforms. Key repos:
- **strugEnterprise** - Main company website + products portfolio
- **sabine-super-agent** (this repo) - Sabine 2.0 development
- **BanditsTracker** - Fitness tracking platform with video analysis
- **Dream Team Strug** - Multi-agent orchestration platform

### Current Stack (Strug City)

| Component | Technology | Notes |
|-----------|------------|-------|
| Frontend | Next.js 16 (App Router) + TypeScript | Vercel deployment |
| CMS | Sanity (headless) | 3 schemas: Product, BlogPost, StreamEntry |
| Styling | Tailwind CSS v4 | Aurora-themed dark mode |
| Backend | Node.js + Railway deployment | Serverless functions |
| Database | Supabase PostgreSQL | pgvector for embeddings |
| CI/CD | GitHub Actions | 7+ workflows (Gemini-powered automation) |
| LLM | Claude (Anthropic API) + Gemini | Prompt caching enabled |

### Sabine 1.0 Stack (Baseline)

| Component | Status | Location |
|-----------|--------|----------|
| Vector DB | Supabase pgvector (1536 dims) | lib/agent/memory.py |
| Embedding | OpenAI text-embedding-3-small | lib/agent/memory.py |
| Entity extraction | Claude 3 Haiku | lib/agent/memory.py |
| RAG pipeline | Vector + keyword fuzzy match | lib/agent/retrieval.py |
| Scheduler | APScheduler (morning briefing) | lib/agent/scheduler.py |
| Tool registry | Local + MCP tools | lib/agent/registry.py |
| Agent core | LangGraph ReAct | lib/agent/core.py |
| Caching | Anthropic prompt caching | lib/agent/core.py |

---

## Sabine 2.0 Architecture (In Development)

### Four Pillars

1. **MAGMA MEMORY** - Multi-graph: Semantic + Temporal + Causal + Entity relationships
2. **DUAL-STREAM PIPELINE** - Fast Path (10-12s) + Slow Path (async consolidation at 2:00 AM)
3. **BELIEF SYSTEM** - Non-monotonic revision, conflict detection, evidence-based push-back
4. **AUTONOMOUS LEARNING** - Gap detection, skill proposals, E2B sandbox testing, hot-reload

### Tech Decisions (Phase 0 - In Progress)

- **Graph Storage:** pg_graphql (via Supabase) - recommended
- **Job Queue:** Redis + rq - recommended for isolation
- **Sandbox:** E2B - recommended for AI agent focus
- **Cold Storage:** Compressed summaries - recommended for cost/fidelity balance

---

## Development Workflow

### Available Skills & Plugins

**Superpowers Suite:**
- superpowers:writing-plans (architecture planning)
- superpowers:dispatching-parallel-agents (parallel task execution)
- superpowers:subagent-driven-development (parallel stream execution)
- superpowers:test-driven-development (TDD workflow)
- superpowers:systematic-debugging (structured debugging)

**Vercel:** deploy, logs, setup
**Figma:** implement-design, code-connect, design-system-rules
**Content:** Notion (task tracking), pr-review-toolkit, claude-md-management
**RUBE Automation:** SEARCH_TOOLS, MULTI_EXECUTE_TOOL, CREATE_UPDATE_RECIPE, MANAGE_RECIPE_SCHEDULE

**GitHub MCP Connector (Local, Interactive):**
- Create draft PRs per stream from Claude Code
- Check regression tests pass before merge
- Link issues/labels interactively
- View PR status without terminal

### GitHub MCP Quick Commands (Phase 1+ Development)

From Claude Code during Sabine 2.0 implementation:

```bash
# Create draft PR for current branch
gh pr create --draft --title "Phase 1 Stream A: <feature>" --body "Implementation details..."

# Check Sabine 1.0 regression tests passed
gh run list --workflow sabine-v1-regression.yml | head -5

# View specific workflow run details
gh run view <RUN_ID> --log

# Link issue to PR + add labels
gh pr edit <PR#> --add-label "phase-1" --add-label "stream-a"

# Check PR status (draft/ready/merged)
gh pr status

# View PR details
gh pr view <PR#>

# Request review before merge
gh pr ready <PR#>
```

**Integration with Existing Workflows:**
- GitHub MCP: Local, interactive (during development)
- GitHub Actions: Post-commit, automated (tests, deploys)
- Gemini Workflows: Cross-org orchestration, scheduled tasks
- No conflicts: All three enabled simultaneously

### Workflow per Phase

**Phase 0 (ADRs - This Week)**
1. dispatching-parallel-agents → Run 4 ADR spikes in parallel
2. Review ADR decisions
3. Commit ADRs to docs/architecture/

**Phase 1-3 (Implementation - Weeks 1-14)**
1. writing-plans → Implementation plan per phase
2. Create git worktree for isolation
3. subagent-driven-development → 4 parallel streams/phase
4. TDD within each stream
5. Frequent commits per task

**Phase 4 (Polish - Weeks 15-16)**
1. Sequential execution (stabilization)
2. Load testing + documentation
3. Final verification

---

## Environment Variables

```bash
# Supabase
SUPABASE_URL=https://[project].supabase.co
SUPABASE_KEY=[service_role_key]
SUPABASE_PUBLIC_KEY=[public_key]

# Anthropic API
ANTHROPIC_API_KEY=sk-...

# Redis (Phase 1+)
REDIS_HOST=redis-[project].railway.app
REDIS_PORT=6379
REDIS_PASSWORD=[password]

# E2B Sandbox (Phase 3+)
E2B_API_KEY=user_[key]

# Observability (Phase 4+)
GRAFANA_URL=https://[org].grafana.net
GRAFANA_API_TOKEN=[token]
```

---

## Cost Summary (16-week project)

**Token Budget:** ~18.7k Haiku tokens = $0.29 (Haiku-only optimization)

**Infrastructure:** ~$465 total
- Supabase: ~$73
- Redis: ~$37
- E2B: ~$300
- Railway: ~$55

**Total:** ~$495 (comparable to current $300-500/month spend, full system built)

---

## Critical Files

**Documentation:**
- docs/PRD_Sabine_2.0_Complete.md - Full requirements
- docs/Sabine_2.0_Executive_Summary.md - Overview
- docs/Sabine_2.0_Technical_Decisions.md - ADR framework
- docs/Sabine_2.0_Implementation_Checklist.md - Phase tasks
- docs/plans/2026-02-13-sabine-2.0-implementation.md - Implementation plan
- docs/architecture/ADR-*.md - Architecture decisions (Phase 0 output)

**Code (Baseline):**
- lib/agent/memory.py - Vector DB + extraction
- lib/agent/retrieval.py - RAG pipeline
- lib/agent/core.py - Agent logic
- lib/agent/registry.py - Tool registry
- lib/agent/scheduler.py - Background jobs

---

## Testing Strategy

**Phase 1:** Schema validation, WAL integrity, Redis roundtrip, salience calc
**Phase 2:** Extraction accuracy (>80%), traversal perf (<200ms), conflict detection
**Phase 3:** Gap detection, E2B isolation, hot-reload, ROI accuracy
**Phase 4:** Load testing (P95 <12s), telemetry correctness, runbook validation

---

## Backward Compatibility & Zero-Downtime Strategy

### Critical Principle: Sabine 1.0 Never Changes

**Sabine 1.0 code is UNTOUCHED during Sabine 2.0 development:**
```
/lib/agent/memory.py      ✓ UNCHANGED (Sabine 1.0 uses this)
/lib/agent/retrieval.py   ✓ UNCHANGED
/lib/agent/core.py        ✓ UNCHANGED
/lib/agent/registry.py    ✓ UNCHANGED
/lib/agent/scheduler.py   ✓ UNCHANGED
```

**Sabine 2.0 is built in isolation:**
```
/backend/v2/
├─ memory.py              ← NEW (salience, archival)
├─ wal.py                 ← NEW (write-ahead log)
├─ worker/consolidate.py  ← NEW (isolated process)
├─ magma/                 ← NEW (relationship graphs)
└─ belief/revision.py     ← NEW (conflict resolution)
```

### Schema Evolution (Additive Only)

**New columns added to existing tables (backward-compatible):**
```sql
-- ✅ SAFE: Add columns with defaults + NULL
ALTER TABLE memories ADD COLUMN salience_score FLOAT DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN is_archived BOOLEAN DEFAULT false;
ALTER TABLE memories ADD COLUMN confidence FLOAT DEFAULT 1.0;
ALTER TABLE memories ADD COLUMN last_accessed_at TIMESTAMP;

-- ✓ Sabine 1.0 queries: SELECT * FROM memories still work
-- ✓ No breaking changes
-- ✓ Easy rollback: just don't use new columns
```

**New tables created for 2.0 (zero impact on 1.0):**
```sql
CREATE TABLE write_ahead_log (...);        -- 1.0 never reads this
CREATE TABLE entity_relationships (...);   -- 1.0 never reads this
CREATE TABLE memory_archive (...);         -- 1.0 never reads this
```

### Dual-Write Strategy (Fast Path)

**Every user message written to BOTH systems (non-blocking):**
```python
async def invoke(user_message: str):
    # Sabine 1.0: Original behavior (unchanged)
    response = await lm_run(user_message)
    await save_to_memories(response)  # ✓ Goes to memories table

    # Sabine 2.0: NEW (isolated, non-blocking)
    try:
        await wal.write(user_message, response)  # ✓ Goes to WAL table
    except Exception as e:
        logging.warning(f"WAL write failed (non-critical): {e}")
        # ✓ If WAL fails, user response still sent
        # ✓ Sabine 1.0 completely unaffected

    return response
```

### Isolated Worker Process

**Sabine 2.0 Slow Path runs in SEPARATE Railway service:**
- Separate deployment
- Separate memory/CPU limits
- If worker crashes: Sabine 1.0 unaffected (different process)
- If worker OOMs: production FastAPI untouched

**Timeline:**
- Weeks 1-3: Worker code built, not running
- Week 4: Manual testing on dev/staging
- Week 5+: Scheduled at 2:00 AM UTC (shadow mode)
- Week 8+: Validated + optional cutover to 2.0 retrieval

### Feature Flags (Instant Kill Switches)

```python
# Environment variable
ENABLE_SABINE_V2=false  # ← Disables ALL 2.0 code paths

# Immediate effects:
# - WAL stops writing
# - Worker won't process
# - Retrieval uses V1 only
# - Rollback time: <1 minute (config flip, no restart)
```

### Rollback Guarantees

**If Sabine 2.0 breaks:**
1. Set `ENABLE_SABINE_V2=false`
2. Sabine 1.0 continues untouched
3. All 2.0 data in separate tables (easy cleanup)
4. Production memories 100% recoverable

**Rollback time:** <1 minute | **Data loss:** $0 | **User impact:** 0

### Testing Strategy (Continuous Validation)

**Sabine 1.0 Regression Tests (run after every commit):**
```bash
pytest tests/sabine_v1/ -v
├─ test_retrieval_consistency.py    # Same queries → same results
├─ test_memory_preservation.py      # No data loss
├─ test_latency_budget.py          # <12s P95 latency
└─ test_tool_execution.py          # All tools work
```

**Schema Compatibility Tests:**
```bash
pytest tests/integration/test_schema_compatibility.py -v
├─ New columns don't break 1.0 queries
├─ Default values work correctly
└─ Dual-write doesn't cause conflicts
```

**Dual-Read Validation (Week 5+):**
```python
# Run both 1.0 + 2.0 retrieval, compare results
context_v1 = await retrieval_v1.get_context(query)  # ✓ Serve to user
context_v2 = await retrieval_v2.get_context(query)  # Run in shadow
if context_v1 != context_v2:
    logging.warning(f"V2 mismatch: {context_v2}")  # Log for investigation
```

### Canary Metrics (Real User Data)

**Week 1-2 (Dark):**
- Sabine 1.0 latency: baseline (unchanged)
- Sabine 1.0 correctness: 100%

**Week 4 (Testing):**
- Worker crashes: 0%
- WAL write success: >99.9%
- No Sabine 1.0 impact: verified

**Week 5+ (Shadow):**
- Sabine 1.0 latency: baseline (still unchanged)
- Sabine 2.0 retrieval accuracy: >Sabine 1.0
- User-perceived improvement: measured

---

## Common Pitfalls

1. **Parallel scope** - Streams must be truly independent
2. **ADR decisions upfront** - Mid-phase changes cost 2-3x rework
3. **Checkpoint patterns** - WAL processing needs idempotent recovery
4. **Memory monitoring** - Slow Path OOM appears suddenly
5. **Schema safety** - ALWAYS add columns, NEVER delete/rename
6. **Feature flags** - Implement kill switches BEFORE going live
7. **Regression tests** - Run 1.0 tests after EVERY commit

---

## Next Steps (This Session)

1. ✅ Phase 0 ADR Spikes - 4 agents running in parallel
2. ⏳ Review ADR Decisions - Expected completion 2-4 hours
3. ⏳ Create RUBE Recipe - Automate nightly consolidation
4. ⏳ Phase 1 Kickoff - Set up worktree + parallel streams

**Date:** February 13, 2026 (Week 0 Day 1)

---

**Last Updated:** 2026-02-13 | **Maintained By:** Claude Code | **Status:** Active Development
