# ADR-004: Cold Storage Format for Archived Memories

## Status
Accepted

## Date
2026-02-13

## Context

### The Memory Accumulation Problem

Sabine's memory system ingests every user interaction through the Context Engine pipeline (`lib/agent/memory.py`). Each ingested message produces:

- A `Memory` row in the `memories` table with a 1536-dimension pgvector embedding (approximately 6 KB per embedding stored as `float4[]`).
- One or more `Entity` rows in the `entities` table with JSONB attributes.
- Entity-to-memory links stored as UUID arrays in `Memory.entity_links`.

At current usage rates, the system generates approximately 50-100 new memories per day. Over 12 months, this projects to 18,000-36,000 memories consuming:

| Component | Per Memory | At 10k | At 50k | At 100k |
|-----------|-----------|--------|--------|---------|
| Embedding vector (1536 x float4) | ~6 KB | 60 MB | 300 MB | 600 MB |
| Content + metadata (JSONB) | ~1 KB | 10 MB | 50 MB | 100 MB |
| pgvector index overhead | ~2 KB | 20 MB | 100 MB | 200 MB |
| **Total per memory** | **~9 KB** | **90 MB** | **450 MB** | **900 MB** |

The Supabase Postgres instance on Railway has practical storage and performance constraints. As the `memories` table grows:

1. **Vector search degrades.** pgvector's HNSW index performance declines as the index grows. Queries over 100k+ vectors with 1536 dimensions show measurable latency increases.
2. **Storage costs increase linearly.** Every memory persists indefinitely, regardless of whether it is ever accessed again.
3. **Context windows are wasted.** The retrieval pipeline (`search_memories_by_similarity` in `lib/agent/memory.py`) returns the top-k most similar memories. Low-salience memories that happen to be semantically close to the query displace higher-value results.

### Access Patterns

Analysis of the expected memory access distribution reveals a pronounced long tail:

- **Hot memories** (accessed within the last 7 days, high salience): ~5-10% of total memories, account for ~80% of retrieval hits.
- **Warm memories** (accessed within 30 days, moderate salience): ~15-20% of total.
- **Cold memories** (not accessed in 90+ days, low salience): ~70-80% of total memories, account for <1% of retrieval hits.

The current system (`lib/db/models.py`) tracks an `importance_score` (0.0-1.0) on each memory but has no mechanism to act on it -- all memories remain in the hot path regardless of score.

### What We Need

A cold storage strategy that:

1. Removes cold memories from the active pgvector index to keep vector search fast.
2. Preserves enough semantic information to answer "did I ever know about X?" queries.
3. Allows full recovery of the original memory content when needed.
4. Costs less than keeping everything in the active Postgres instance.

## Decision

We will use the **Compressed Summary** format for cold storage of archived memories.

When a memory is archived:

1. An LLM (Claude 3 Haiku) generates a 2-3 sentence semantic summary of the original memory.
2. Key entity links are preserved in a lightweight archive record.
3. The full original memory (content, embedding, metadata) is exported to object storage (Cloudflare R2 or AWS S3) as a JSON file.
4. The original memory row is deleted from the active `memories` table, freeing pgvector index space.
5. A new row is inserted into the `archived_memories` table with the summary, entity references, and a pointer to the object storage backup.

## Options Considered

### Option 1: Full Archive (Keep Everything in Postgres)

Move cold memories to a separate `archived_memories` table within the same Postgres instance, retaining full content and embeddings.

**Approach:** `INSERT INTO archived_memories SELECT * FROM memories WHERE ...` followed by `DELETE FROM memories WHERE ...`.

### Option 2: Compressed Summary (Selected)

Replace cold memories with LLM-generated summaries in a lightweight archive table. Store full originals in object storage.

**Approach:** Summarize via Haiku, store summary + entity links in Postgres, export full original to S3/R2.

### Option 3: Tombstone Only

Delete cold memories entirely, leaving only a tombstone record (ID, archived timestamp, deletion reason).

**Approach:** `INSERT INTO tombstones (original_id, reason, archived_at)` followed by hard delete.

### Comparison

| Criterion | Full Archive | Compressed Summary | Tombstone Only |
|-----------|-------------|-------------------|----------------|
| **Postgres storage savings** | None (same data, different table) | ~85% (summary replaces embedding + content) | ~99% (minimal record) |
| **pgvector index relief** | Full (removed from active index) | Full (removed from active index) | Full (removed from active index) |
| **Retrieval fidelity** | 100% -- original content intact | 70-80% -- semantic meaning preserved, exact wording lost | 0% -- only know something existed |
| **Retrieval latency** | <100ms (local Postgres read) | <500ms (read summary; optionally fetch full from S3) | N/A (nothing to retrieve) |
| **LLM cost at archival time** | $0 | ~$0.001 per memory (Haiku) | $0 |
| **Object storage cost** | Not needed | ~$0.01/GB/month for backups | Not needed |
| **Reversibility** | Full -- can restore to active table | Full -- original in S3, summary in Postgres | None -- data is permanently lost |
| **Answers "did I know X?"** | Yes -- full text search | Yes -- summary search | Barely -- only ID existence |
| **Implementation complexity** | Low | Medium | Low |
| **Long-term Postgres growth** | Continues growing (just slower) | Minimal growth (summaries are small) | Minimal growth |

## Rationale

**Compressed Summary** is selected because it strikes the optimal balance across the dimensions that matter most for Sabine:

### 1. Storage Efficiency Without Data Loss

The Full Archive option moves the problem without solving it -- cold memories still consume substantial Postgres storage and will eventually need a second archival tier. Compressed Summary reduces per-memory Postgres footprint by approximately 85% (a ~9 KB active memory becomes a ~1.3 KB archive record), while the full original lives cheaply in object storage at ~$0.01/GB/month.

### 2. Semantic Preservation

Tombstone Only destroys the ability to answer questions about past knowledge. A user asking "did we ever discuss the PriceSpider deal?" would get no answer from a tombstone. The Compressed Summary retains enough semantic content for the retrieval pipeline to surface relevant archived memories and, when needed, fetch the full original from S3/R2.

### 3. Cost-Effective Summarization

Claude 3 Haiku is the current extraction model used in the ingestion pipeline (`lib/agent/memory.py`, line 80). The cost to summarize a single memory is approximately $0.001 (based on ~500 input tokens + ~100 output tokens at Haiku pricing). Archiving 10,000 memories costs roughly $10 -- a one-time expense that saves ongoing storage and performance costs.

### 4. Clean Separation of Hot and Cold Paths

By physically removing archived memories from the `memories` table and pgvector index, the active retrieval path remains fast regardless of how many memories have been archived over the system's lifetime. This is not achievable with the Full Archive option unless a separate Postgres instance is provisioned.

## Consequences

### Positive

1. **pgvector index stays lean.** Removing cold memories from the active index maintains sub-100ms vector search latency as the system scales.
2. **Postgres storage grows slowly.** Archive records are ~85% smaller than active memories. At 100k total memories with 80% archived, Postgres holds ~180 MB instead of ~900 MB.
3. **Cold memories remain discoverable.** The summary in `archived_memories` is searchable and can be included in retrieval results with a "[archived]" label, letting the user decide whether to expand.
4. **Full recoverability.** The S3/R2 backup means no data is ever permanently lost. An archived memory can be fully restored to the active table if needed.
5. **Aligns with existing model usage.** Haiku is already initialized in the codebase for entity extraction, so no new LLM integration is required for summarization.

### Negative

1. **One-time LLM cost at archival.** Each archived memory incurs a ~$0.001 Haiku call. For the initial archival run of existing memories, this is a batch cost (e.g., $10 for 10k memories). Ongoing archival costs are negligible.
2. **Summary lossy by nature.** A 2-3 sentence summary cannot capture every nuance of the original memory. Exact quotes, specific numbers, and fine-grained details may be lost in the summary (though they remain available in S3).
3. **S3/R2 dependency.** Introduces a new external service dependency for object storage. If the object storage bucket is inaccessible, full restoration is temporarily blocked (though summaries remain available).
4. **Increased archival pipeline complexity.** The archival process has more steps than a simple table move or delete, requiring orchestration of LLM calls, S3 uploads, and database transactions.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Haiku summarization loses critical detail** | Medium | Medium | Store full original in S3/R2; surface "[archived -- click to expand]" in UI so user can request full version |
| **S3/R2 bucket becomes unavailable** | Low | Medium | Summaries remain in Postgres for basic retrieval; implement health checks on the bucket; consider multi-region replication for critical data |
| **Archival job fails mid-batch** | Medium | Low | Process memories individually with idempotent operations; track archival status per-memory; use checkpoint-based resumption |
| **Re-archived memory is needed frequently** | Low | Low | Track "expansion requests" per archived memory; if an archived memory is expanded more than 3 times in 30 days, automatically promote it back to the active table |
| **Initial archival run overloads Haiku API** | Low | Medium | Rate-limit to 10 requests/second; run during off-peak hours (2:00 AM Slow Path window); implement exponential backoff |

## Implementation Notes

### Archive Record Schema

The `archived_memories` table schema:

```sql
CREATE TABLE archived_memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_id     UUID NOT NULL UNIQUE,       -- ID of the original memory (for deduplication and reference)
    summary         TEXT NOT NULL,               -- 2-3 sentence LLM-generated semantic summary
    summary_embedding VECTOR(1536),             -- Embedding of the summary (for cold retrieval via similarity search)
    key_entities    UUID[] DEFAULT '{}',         -- Preserved entity links from the original memory
    original_domain TEXT,                        -- Domain classification (work, family, personal, logistics)
    importance_score FLOAT DEFAULT 0.0,          -- Original importance score at time of archival
    access_count    INTEGER DEFAULT 0,           -- Number of times this archive has been expanded/retrieved
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    original_created_at TIMESTAMPTZ,             -- When the original memory was created
    storage_ref     TEXT,                        -- S3/R2 URI: "s3://sabine-archive/memories/{original_id}.json"
    storage_verified BOOLEAN DEFAULT FALSE,      -- Whether S3 upload was confirmed successful
    metadata        JSONB DEFAULT '{}'           -- Preserved metadata from original memory
);

-- Index for similarity search on archived summaries
CREATE INDEX idx_archived_memories_embedding
    ON archived_memories
    USING hnsw (summary_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index for looking up by original ID (restoration)
CREATE INDEX idx_archived_memories_original_id
    ON archived_memories (original_id);

-- Index for domain-scoped queries
CREATE INDEX idx_archived_memories_domain
    ON archived_memories (original_domain);
```

### Pydantic Models

```python
class ArchivedMemory(BaseModel):
    """A cold-stored memory with compressed summary."""
    id: Optional[UUID] = None
    original_id: UUID
    summary: str = Field(..., description="2-3 sentence semantic summary")
    summary_embedding: Optional[List[float]] = Field(
        default=None, description="Embedding of the summary (1536 dims)"
    )
    key_entities: List[UUID] = Field(default_factory=list)
    original_domain: Optional[DomainEnum] = None
    importance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    access_count: int = Field(default=0, ge=0)
    archived_at: Optional[datetime] = None
    original_created_at: Optional[datetime] = None
    storage_ref: Optional[str] = Field(
        default=None, description="S3/R2 URI for full original backup"
    )
    storage_verified: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### S3/R2 Backup Object Format

Each archived memory's full original is stored as a JSON file at `s3://sabine-archive/memories/{original_id}.json`:

```json
{
    "schema_version": 1,
    "original_id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "Full original memory content text...",
    "embedding": [0.0123, -0.0456, ...],
    "entity_links": ["uuid1", "uuid2"],
    "metadata": {
        "user_id": "...",
        "source": "sms",
        "timestamp": "2026-01-15T12:00:00Z",
        "domain": "family",
        "role": "assistant"
    },
    "importance_score": 0.3,
    "created_at": "2026-01-15T12:00:00Z",
    "archived_at": "2026-04-15T02:00:00Z",
    "archive_reason": "low_salience_aged_out"
}
```

The `schema_version` field enables future format migrations without re-processing existing archives.

### Haiku Summarization Cost Analysis

The summarization prompt template:

```
System: You are a memory archival assistant. Summarize the following memory
into 2-3 sentences that preserve the core semantic meaning, key facts,
names, dates, and actionable details. The summary must be useful for
future retrieval via similarity search.

User: {memory_content}

Additional context - Domain: {domain}, Entities: {entity_names}
```

Cost breakdown per memory (Claude 3 Haiku pricing as of 2026):

| Component | Tokens | Cost |
|-----------|--------|------|
| System prompt | ~80 tokens | -- |
| Memory content (average) | ~300 tokens | -- |
| Entity context | ~50 tokens | -- |
| **Total input** | **~430 tokens** | **$0.00011** |
| Summary output | ~80 tokens | **$0.00010** |
| **Total per memory** | -- | **~$0.0002** |

*Note: At current Haiku pricing ($0.25/M input, $1.25/M output), the cost is actually closer to $0.0002 per memory. The $0.001 estimate in the Technical Decisions doc includes safety margin for retries, longer-than-average memories, and embedding generation for the summary.*

Batch cost projections:

| Batch Size | Summarization Cost | S3 Storage (annual) | Total First-Year Cost |
|-----------|-------------------|--------------------|-----------------------|
| 1,000 memories | $0.20 | $0.10 | $0.30 |
| 10,000 memories | $2.00 | $1.00 | $3.00 |
| 50,000 memories | $10.00 | $5.00 | $15.00 |
| 100,000 memories | $20.00 | $10.00 | $30.00 |

These costs are negligible compared to the Postgres storage and performance savings.

### Archival Trigger Criteria

A memory becomes eligible for archival when it meets **all** of the following:

```python
ARCHIVAL_CRITERIA = {
    # Minimum age before a memory can be archived
    "min_age_days": 90,

    # Maximum importance score for archival eligibility
    # Memories above this threshold are never auto-archived
    "max_importance_score": 0.3,

    # Maximum access count in the last 90 days
    # Frequently accessed memories stay hot regardless of age
    "max_recent_access_count": 2,

    # Minimum age for force-archive regardless of score
    # Even important memories get archived after this period
    # (they can still be retrieved via summary search)
    "force_archive_age_days": 365,
}
```

The archival evaluation runs during the Slow Path nightly job (2:00 AM window), consistent with the existing architecture described in the Executive Summary.

**Evaluation query:**

```sql
SELECT m.id, m.content, m.embedding, m.entity_links, m.metadata,
       m.importance_score, m.created_at
FROM memories m
WHERE (
    -- Standard archival: old + low importance + rarely accessed
    (m.created_at < NOW() - INTERVAL '90 days'
     AND m.importance_score <= 0.3
     AND (m.metadata->>'access_count')::int <= 2)
    OR
    -- Force archival: very old regardless of importance
    (m.created_at < NOW() - INTERVAL '365 days')
)
AND m.id NOT IN (SELECT original_id FROM archived_memories)
ORDER BY m.importance_score ASC, m.created_at ASC
LIMIT 500;  -- Process in batches to avoid OOM
```

### Archival Pipeline Steps

The archival job executes as a step in the Slow Path worker:

```
1. QUERY:    Select batch of archival-eligible memories (max 500 per run)
2. FOR EACH memory in batch:
   a. SUMMARIZE: Call Haiku to generate 2-3 sentence summary
   b. EMBED:     Generate embedding for the summary (text-embedding-3-small)
   c. UPLOAD:    Write full original as JSON to S3/R2
   d. VERIFY:    Confirm S3 upload succeeded (HEAD request)
   e. INSERT:    Write archive record to archived_memories table
   f. DELETE:    Remove original from memories table
   g. CHECKPOINT: Record this memory ID as processed
3. LOG:      Report batch summary (archived count, errors, duration)
```

Steps 2c through 2f are wrapped in a transaction: if any step fails, the memory remains in the active table unchanged. The checkpoint in step 2g enables resumption if the job crashes mid-batch.

## Retrieval Strategy

### How Cold Memories Surface in Queries

The retrieval pipeline is extended with a two-phase search:

**Phase 1: Hot Path Search (existing behavior)**

```python
# Search active memories via pgvector similarity
active_results = await search_memories_by_similarity(
    query=user_query,
    limit=5,
    threshold=0.7
)
```

**Phase 2: Cold Path Search (new)**

```python
# Search archived memory summaries via pgvector similarity
# Only triggered when:
#   a) Active results are fewer than requested limit, OR
#   b) Query explicitly asks about past/historical information, OR
#   c) No active results exceed the similarity threshold
archived_results = await search_archived_memories(
    query=user_query,
    limit=3,
    threshold=0.65  # Slightly lower threshold for summaries
)
```

**Phase 3: Merge and Rank**

Active and archived results are merged into a single ranked list. Archived results are annotated with an `[archived]` flag so the agent can communicate provenance to the user:

```python
merged_results = rank_and_merge(
    active=active_results,
    archived=archived_results,
    active_boost=1.2  # Slight preference for active memories
)
```

### Expansion on Demand

When an archived memory is relevant and the user (or agent) needs the full original:

1. The archive record's `storage_ref` is used to fetch the JSON object from S3/R2.
2. The full content is injected into the current context window.
3. The `access_count` on the archive record is incremented.
4. If `access_count` exceeds the re-promotion threshold (3 expansions in 30 days), the memory is automatically restored to the active `memories` table.

```python
async def expand_archived_memory(archive_id: UUID) -> Dict[str, Any]:
    """Fetch full original from S3/R2 and return expanded content."""
    archive = await get_archived_memory(archive_id)

    # Fetch from object storage
    full_original = await fetch_from_s3(archive.storage_ref)

    # Increment access count
    await increment_archive_access_count(archive_id)

    # Check re-promotion threshold
    if should_repromote(archive):
        await restore_to_active(archive, full_original)

    return full_original
```

### Latency Expectations

| Operation | Expected Latency | Notes |
|-----------|-----------------|-------|
| Summary-only retrieval (Phase 2) | <200ms | pgvector search on archived_memories table |
| Full expansion from S3/R2 | <500ms | S3 GET for a small JSON object (~10 KB) |
| Re-promotion to active table | <1s | INSERT to memories + DELETE from archived_memories |

## Migration Plan

### Handling Existing Memories During Initial Archival Run

The initial archival is a one-time batch job that processes the existing backlog of cold memories. It must be carefully staged to avoid disruption.

#### Phase 1: Preparation (Day 1)

1. **Deploy schema.** Run the `CREATE TABLE archived_memories` migration. This is additive and does not affect the existing `memories` table.
2. **Deploy S3/R2 bucket.** Create the `sabine-archive` bucket with appropriate IAM/access policies.
3. **Add importance_score tracking.** Ensure all memories have a populated `importance_score`. Backfill any NULL values with a default of 0.5.
4. **Add access tracking.** Backfill `metadata.access_count` for existing memories based on retrieval logs (if available) or default to 0.

#### Phase 2: Dry Run (Day 2)

1. **Run archival evaluation query** in read-only mode. Report how many memories would be archived under the current criteria.
2. **Sample 50 memories** from the candidate set. Run Haiku summarization on them and manually review summary quality.
3. **Verify S3 upload/download** with the 50 sample memories. Confirm round-trip fidelity (original content matches after download).
4. **Estimate batch cost and duration.** Based on the 50-memory sample, project cost and wall-clock time for the full run.

#### Phase 3: Initial Archival (Day 3-4)

1. **Run the archival job during the 2:00 AM Slow Path window.** Process up to 500 memories per nightly run.
2. **Monitor after each batch:** Check archive record count, S3 upload success rate, Haiku error rate.
3. **Pause if error rate exceeds 5%.** Investigate and fix before continuing.
4. **Continue nightly until backlog is cleared.** For a backlog of 5,000 cold memories, this takes approximately 10 nightly runs.

#### Phase 4: Steady State (Ongoing)

1. **Archival evaluation runs nightly** as part of the Slow Path worker, processing newly eligible memories.
2. **Monitor dashboard tracks:** active memory count, archived memory count, archive expansion rate, S3 storage size.
3. **Review archival criteria quarterly.** Adjust thresholds based on retrieval patterns and user feedback.

### Rollback Plan

If the archival system causes problems (e.g., users report missing memories, summary quality is unacceptable):

1. **Stop archival.** Disable the archival step in the Slow Path worker.
2. **Restore from S3.** Bulk-restore archived memories from S3/R2 back to the active `memories` table using the `storage_ref` pointers. This is a scripted operation that reads each archived JSON and re-inserts it.
3. **Drop archive table.** Once all originals are restored, the `archived_memories` table can be dropped.

The S3/R2 backup is specifically designed to make this rollback safe and complete.

## References

- `docs/Sabine_2.0_Technical_Decisions.md` -- ADR-004 decision framework and spike requirements
- `docs/Sabine_2.0_Executive_Summary.md` -- MAGMA Memory architecture and Slow Path description
- `lib/agent/memory.py` -- Current memory ingestion pipeline (Haiku extraction, embedding generation, Supabase storage)
- `lib/db/models.py` -- Pydantic v2 models for Memory, Entity, and related schemas
- `lib/db/__init__.py` -- Database package public API
