# Sabine 2.0: Technical Decision Framework

**Purpose:** Guide for Tech Lead architecture spikes
**Last Updated:** January 30, 2026

---

## Overview

Before implementation begins, four key architectural decisions must be made. This document provides the analysis framework, evaluation criteria, and recommended approaches for each.

---

## ADR-001: Graph Storage

### Decision Question
Should MAGMA graph relationships be stored in pg_graphql (Supabase extension) or an external graph database (Neo4j)?

### Context
- Current stack: Supabase (PostgreSQL) on Railway
- Graph operations: Primarily read-heavy traversals
- Scale: Estimated 50k-200k relationships at maturity
- Query patterns: 3-5 hop traversals, cross-graph joins

### Options Analysis

| Criterion | pg_graphql | Neo4j |
|-----------|------------|-------|
| **Setup Complexity** | Low (Supabase extension) | High (new service, connection management) |
| **Operational Overhead** | Low (managed by Supabase) | Medium (separate backups, scaling) |
| **Query Performance** | Good for <500k nodes | Excellent for complex traversals |
| **Cypher vs. SQL** | SQL + graphql | Native Cypher |
| **Cost** | Included in Supabase | Additional $20-100/mo |
| **Transaction Consistency** | Same DB as entities | Cross-DB coordination needed |
| **Team Familiarity** | High (SQL) | Low (new language) |

### Spike Requirements
1. Implement sample `entity_relationships` table in Supabase
2. Write 5-hop causal traversal query in SQL
3. Measure latency at 10k, 50k, 100k relationships
4. Compare with Neo4j Aura free tier

### Recommendation
**pg_graphql** for Phase 1-2, with Neo4j migration path if:
- Traversal latency exceeds 500ms at scale
- Query complexity requires Cypher's expressiveness
- Graph-specific algorithms (PageRank, community detection) needed

### Decision Template
```markdown
## ADR-001: Graph Storage Decision

**Date:** [DATE]
**Status:** [Proposed/Accepted/Superseded]
**Deciders:** [Names]

### Decision
We will use [pg_graphql / Neo4j] for MAGMA graph storage.

### Rationale
[Key reasons based on spike findings]

### Consequences
- Positive: [List]
- Negative: [List]
- Risks: [List with mitigations]
```

---

## ADR-002: Job Queue for Slow Path

### Decision Question
Should the Slow Path consolidation use Redis-based job queue or continue with in-process APScheduler?

### Context
- Current: APScheduler runs at 2:00 AM in FastAPI process
- Concern: OOM during heavy consolidation
- Scale: Processing 100-500 WAL entries nightly
- Failure mode: Must resume after crash

### Options Analysis

| Criterion | In-Process (APScheduler) | Redis Queue (rq/dramatiq) |
|-----------|--------------------------|---------------------------|
| **Isolation** | None (shares FastAPI memory) | Full (separate worker) |
| **OOM Risk** | High | Low (worker can crash independently) |
| **Checkpointing** | Manual implementation | Built-in job state |
| **Retry Logic** | Manual | Built-in |
| **Monitoring** | Custom | Dashboard included |
| **Setup Complexity** | Already done | New service + Redis |
| **Cost** | $0 | Redis add-on ~$5-20/mo |

### Spike Requirements
1. Measure memory usage during current consolidation
2. Implement checkpoint save/restore with APScheduler
3. Spin up Railway Redis add-on, test connectivity
4. Create minimal worker with rq, process sample job

### Recommendation
**Redis Queue (rq)** because:
- OOM isolation is critical for production stability
- Built-in retry and monitoring reduce custom code
- Cost is minimal ($5-10/mo for Railway Redis)
- Worker can scale independently if needed

### Decision Template
```markdown
## ADR-002: Job Queue Decision

**Date:** [DATE]
**Status:** [Proposed/Accepted/Superseded]
**Deciders:** [Names]

### Decision
We will use [APScheduler / Redis + rq / Redis + dramatiq] for Slow Path processing.

### Rationale
[Key reasons based on spike findings]

### Consequences
- Positive: [List]
- Negative: [List]
- Risks: [List with mitigations]
```

---

## ADR-003: Sandbox Provider for Skill Acquisition

### Decision Question
Which sandbox-as-a-service should be used for testing auto-generated skills?

### Context
- Need: Isolated Python execution environment
- Security: No access to production env vars, network
- Lifecycle: Ephemeral (spin up, run, tear down)
- Output: Capture stdout, stderr, exit code

### Options Analysis

| Criterion | E2B | Modal | Local Docker |
|-----------|-----|-------|--------------|
| **Setup Complexity** | Low (SDK) | Medium | High (Docker-in-Docker) |
| **Cold Start** | ~2s | ~5s | N/A (always warm) |
| **Pricing** | Pay-per-use | Pay-per-use | Railway compute |
| **Python Support** | Native | Native | Manual setup |
| **File System** | Virtual, mountable | Virtual | Shared with host (risky) |
| **Network Isolation** | Enforced | Enforced | Manual |
| **SDK Quality** | Excellent (Python) | Good (Python) | N/A |
| **AI-Agent Focus** | Yes (designed for it) | General compute | N/A |

### Spike Requirements
1. Create E2B account, test SDK locally
2. Execute sample skill code, capture output
3. Measure cold start latency
4. Test file mounting (read-only input folder)
5. Verify network isolation (attempt outbound request)

### Recommendation
**E2B** because:
- Designed specifically for AI agent code execution
- Python SDK is clean and well-documented
- Cold start (~2s) acceptable for skill testing workflow
- Pricing transparent and reasonable

### Decision Template
```markdown
## ADR-003: Sandbox Provider Decision

**Date:** [DATE]
**Status:** [Proposed/Accepted/Superseded]
**Deciders:** [Names]

### Decision
We will use [E2B / Modal / Docker] for skill sandbox execution.

### Rationale
[Key reasons based on spike findings]

### Consequences
- Positive: [List]
- Negative: [List]
- Risks: [List with mitigations]
```

---

## ADR-004: Cold Storage Format

### Decision Question
How should low-salience archived memories be stored for space efficiency while maintaining retrievability?

### Context
- Problem: Memories accumulate, most rarely accessed
- Goal: Reduce storage cost, maintain recoverability
- Access pattern: Cold retrieval expected <1% of queries
- Requirement: Retrieval latency <500ms

### Options Analysis

| Criterion | Full Archive | Compressed Summary | Tombstone Only |
|-----------|--------------|--------------------|--------------------|
| **Storage Cost** | High | Medium | Low |
| **Retrieval Fidelity** | 100% | 70-80% (semantic) | 0% (reference only) |
| **Retrieval Latency** | <100ms | <500ms (regenerate) | N/A |
| **LLM Cost** | None | One-time summarize | None |
| **Reversibility** | Full | Partial | None |

### Spike Requirements
1. Measure current memory table size distribution
2. Test Claude Haiku summarization quality on sample memories
3. Benchmark cold retrieval with summary expansion
4. Calculate storage savings at 10k, 50k, 100k memories

### Recommendation
**Compressed Summary** because:
- Balances storage savings with recoverability
- Summary preserves semantic meaning
- One-time Haiku call is cheap (~$0.001/memory)
- Full original can be stored in object storage (S3/R2) as backup

### Implementation Note
```python
# Archive format
{
    "original_id": "uuid",
    "summary": "3-sentence semantic summary",
    "key_entities": ["entity_uuid1", "entity_uuid2"],
    "archived_at": "timestamp",
    "original_storage_ref": "s3://bucket/archived/uuid.json"  # Optional full backup
}
```

### Decision Template
```markdown
## ADR-004: Cold Storage Format Decision

**Date:** [DATE]
**Status:** [Proposed/Accepted/Superseded]
**Deciders:** [Names]

### Decision
We will use [Full Archive / Compressed Summary / Tombstone] for cold storage.

### Rationale
[Key reasons based on spike findings]

### Consequences
- Positive: [List]
- Negative: [List]
- Risks: [List with mitigations]
```

---

## Spike Timeline

| ADR | Owner | Start | End | Deliverable |
|-----|-------|-------|-----|-------------|
| ADR-001: Graph Storage | Tech Lead | Week 0 Day 1 | Week 0 Day 3 | ADR + benchmark data |
| ADR-002: Job Queue | Tech Lead | Week 0 Day 2 | Week 0 Day 4 | ADR + POC code |
| ADR-003: Sandbox | Tech Lead | Week 0 Day 3 | Week 0 Day 5 | ADR + POC code |
| ADR-004: Cold Storage | Tech Lead | Week 0 Day 4 | Week 0 Day 5 | ADR + size analysis |

**Total Spike Duration:** 5 working days (1 week)

---

## Post-Spike Review Meeting

**Agenda:**
1. Present each ADR (15 min each)
2. Discuss trade-offs and concerns
3. Make final decisions
4. Update PRD with chosen approaches
5. Kick off Phase 1 implementation

**Attendees:** PM, Tech Lead, CTO

---

*This document supports the Architecture Spike phase before PRD implementation begins.*
